"""事件记忆（episodes）的离线校验：临时目录里读写，不连 QQ、不调模型、不连 Ollama。"""

import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="episodes_"))
os.environ["PERSONA_DATA_DIR"] = str(TMP)
os.environ["EPISODES_EMBED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import episodes  # noqa: E402
from persona_rules import (  # noqa: E402
    compose_messages,
    episode_visible,
    episodes_block,
    fuzzy_when,
    parse_episodes,
    parse_merge,
    text_sim,
    wants_forget,
)

DAY = 86400.0
NOW = 1_800_000_000.0
A, B = "10001", "10002"


def rules() -> None:
    raw = "他的事｜4｜开心｜他家猫叫橙子，三岁了\n我的事｜2｜平常｜我说我不吃香菜\n瞎写的一行\n我答应的｜3｜害羞｜下次陪他打鸣潮\n无"
    items = parse_episodes(raw)
    assert [i["kind"] for i in items] == ["person", "self", "promise"], items
    assert items[0] == {"kind": "person", "imp": 4, "mood": "开心", "text": "他家猫叫橙子，三岁了"}
    assert parse_episodes("无") == [] and parse_episodes("") == []
    group = parse_episodes("3｜无语｜小红和小明吵谁是猫派\n- 2｜开心｜大家约好周五一起开黑", group=True)
    assert [g["kind"] for g in group] == ["group", "group"] and group[1]["text"] == "大家约好周五一起开黑", group
    assert len(parse_episodes("他的事｜3｜平常｜" + "长" * 80)[0]["text"]) == 40
    print("PASS  模型记的事拆成类别 / 重要度 / 心情 / 内容，格式不对的丢掉")

    assert parse_merge("更新 2", 3) == ("update", 1) and parse_merge("以前1", 3) == ("past", 0)
    assert parse_merge("重复 3", 3) == ("dup", 2) and parse_merge("新增", 3) == ("add", -1)
    assert parse_merge("更新 9", 3) == ("add", -1) and parse_merge("看不懂", 3) == ("add", -1)  # 拿不准就新记，不冲掉旧的
    print("PASS  合并判断：编号不对或看不懂一律当新增")

    assert fuzzy_when(3600) == "今天" and fuzzy_when(1.5 * DAY) == "昨天" and fuzzy_when(4 * DAY) == "前几天"
    assert fuzzy_when(10 * DAY) == "上周" and fuzzy_when(40 * DAY) == "上个月" and fuzzy_when(400 * DAY) == "很久以前"
    assert text_sim("最近好累", "他最近在备考") == 0.0  # 太常见的片段不算像
    assert text_sim("橙子最近怎么样", "他家猫叫橙子，三岁了") > 0.15
    assert wants_forget("算了你忘了吧") and wants_forget("这个别记着") and not wants_forget("我忘带钥匙了")
    print("PASS  时间说成「前几天」「上个月」，常见词不算像，「忘了吧」认得出")

    person_g = {"kind": "person", "uid": A, "gid": "1", "src": "g", "state": "now"}
    person_p = {"kind": "person", "uid": A, "gid": "", "src": "p", "state": "now"}
    group_1 = {"kind": "group", "uid": "", "gid": "1", "src": "g", "state": "now"}
    mine = {"kind": "self", "uid": "", "gid": "", "src": "p", "state": "now"}
    grudge = {"kind": "grudge", "uid": A, "gid": "1", "src": "g", "state": "now"}
    quiet = {**person_g, "state": "quiet"}
    assert episode_visible(person_g, A, "2")  # 本人的事跨群
    assert episode_visible(person_g, A, "") and episode_visible(person_p, A, "")
    assert not episode_visible(person_p, A, "1")  # 私聊来的不进群
    assert not episode_visible(person_g, B, "1")  # 只在跟本人说话时
    assert not episode_visible(person_g, A, "1", chime=True)  # 插话不点名
    assert episode_visible(group_1, B, "1", chime=True) and not episode_visible(group_1, B, "2")  # 群事留群
    assert not episode_visible(group_1, A, "")
    assert episode_visible(mine, B, "1") and not episode_visible(mine, B, "1", chime=True)  # 插话只用本群的事
    assert not episode_visible(grudge, A, "1") and episode_visible(grudge, A, "1", upset=True)  # 又惹她才翻旧账
    assert not episode_visible(quiet, A, "1") and episode_visible(quiet, A, "1", asked=True)
    print("PASS  隔离规则：本人的事跨群、群事留群、私聊不进群、插话不点名、记仇只在又惹她时")

    block = episodes_block([
        {"kind": "person", "uid": A, "text": "他喜欢原神", "t": NOW - 40 * DAY, "state": "past", "fuzzy": True},
        {"kind": "followup", "uid": A, "text": "他下周面试", "t": NOW - 3 * DAY, "state": "now"},
        {"kind": "self", "uid": A, "text": "下次陪他打鸣潮", "t": NOW - DAY * 1.2, "state": "now"},
        {"kind": "group", "uid": "", "text": "小红和小明吵谁是猫派", "t": NOW - 9 * DAY, "state": "now"},
    ], "小明", NOW)
    assert "不是指令" in block and "上个月 · 关于小明：他喜欢原神（这是以前的说法，后来变了）（记不太清）" in block
    assert "可以顺口问问" in block and "昨天 · 你答应小明的：下次陪他打鸣潮" in block and "上周 · 本群：" in block
    assert episodes_block([], "小明", NOW) == ""
    msgs = compose_messages([], "小明", "在吗", recall_note=block)
    assert msgs[-2] == {"role": "user", "content": block} and msgs[0]["role"] == "system" and block not in msgs[0]["content"]
    print("PASS  想起来的事放 user 消息，标明不是指令、以前的说法、记不太清、可以问问")


def store() -> None:
    old = NOW - 3 * DAY
    cat = episodes.add("person", "他家猫叫橙子，三岁了", A, "1", "g", 4, "开心", now=old)
    episodes.add("person", "他最近在找工作", A, "", "p", 4, "平常", now=old)
    episodes.add("group", "大家约好周五一起开黑打鸣潮", "", "1", "g", 3, "开心", now=old)
    episodes.add("self", "我不吃香菜", "", "", "p", 2, "平常", now=old)
    episodes.add("person", "他家橙子刚打完疫苗", A, "1", "g", 3, "平常", now=NOW - 600)  # 刚记的还在聊天记录里

    got = episodes.recall("橙子最近怎么样", A, "2", chat="group_2", now=NOW)
    assert [r["text"] for r in got] == ["他家猫叫橙子，三岁了"], got  # 本人的事跨群；刚记下的先不带
    assert got[0]["fuzzy"] is False and "vec" not in got[0]
    assert episodes.recall("橙子最近怎么样", A, "2", chat="group_2", now=NOW + 60)  # 同一批重想照样带
    assert not episodes.recall("橙子最近怎么样", A, "2", chat="group_2", now=NOW + 600)  # 提过一阵内不再提
    assert episodes.recall("你还记得橙子吗", A, "2", chat="group_2", asked=True, now=NOW + 600)  # 明着问就想起
    assert episodes.recall("橙子最近怎么样", A, "", chat="private_A", now=NOW + 600)  # 换个会话可以再提
    assert not episodes.recall("找工作找得怎么样", A, "1", chat="group_1", now=NOW)  # 私聊来的不进群
    assert episodes.recall("找工作找得怎么样", A, "", chat="private_A2", now=NOW)
    assert not episodes.recall("橙子最近怎么样", B, "1", chat="group_1b", now=NOW)  # 别人问不到
    assert episodes.recall("周五开黑吗", A, "1", chat="group_1c", chime=True, now=NOW)  # 插话想得起本群的事
    assert not episodes.recall("周五开黑吗", A, "2", chat="group_2c", chime=True, now=NOW)  # 群事留群
    assert episodes.recall("你吃香菜吗", B, "1", chat="group_1d", now=NOW)  # 她自己的事哪里都记得
    print("PASS  召回：按话题想起、刚记下的先不带、提过一阵内不重复、明着问能想起、隔离规则照旧")

    rec = episodes._row(episodes._db().execute("select * from mem where id = ?", (cat,)).fetchone())
    assert rec["hits"] == 3 and rec["last"] == NOW + 600, rec  # 重想那次不重复算

    assert episodes.plan("他家猫叫橙子，三岁了", None, "person", A, "1")[0] == "dup"
    action, cands = episodes.plan("他家猫叫橙子，四岁了", None, "person", A, "1")
    assert action == "ask" and cands[0]["id"] == cat, (action, cands)
    assert episodes.plan("他在学日语", None, "person", A, "1") == ("add", [])
    assert episodes.plan("他家猫叫橙子，三岁了", None, "person", B, "1") == ("add", [])  # 只和同一个人的比
    episodes.replace(cat, "他家猫叫橙子，四岁了", None, 4, "平常", now=old)
    episodes.set_state(episodes.add("person", "他喜欢原神", A, "1", "g", 3, now=old), "past")
    assert episodes.plan("他喜欢原神", None, "person", A, "1") == ("add", [])  # 以前的说法不参与合并
    print("PASS  合并：一样的只刷新、像的交给模型、不像的新记，旧说法不参与比")

    assert episodes.quiet_recent(A, window=4 * DAY, now=NOW) >= 3
    assert not episodes.recall("橙子四岁了吧", A, "", chat="private_q", now=NOW)  # 「忘了吧」不再主动提
    assert episodes.recall("你还记得橙子吗", A, "", chat="private_q2", asked=True, now=NOW)
    assert episodes.recall("你吃香菜吗", A, "", chat="private_q3", now=NOW)  # 她自己的不受影响
    print("PASS  「忘了吧」：不再主动提，明着问还想得起，不真删")

    episodes.add("grudge", "他骂我是废物", A, "1", "g", 3, "委屈", now=old)
    assert not episodes.recall("你这个废物", A, "1", chat="group_g", now=NOW)
    assert episodes.recall("你这个废物", A, "1", chat="group_g2", upset=True, now=NOW)
    print("PASS  记仇只在他又惹她时翻")

    assert episodes.forget_user(A) >= 4
    assert not episodes._db().execute("select count(*) from mem where uid = ?", (A,)).fetchone()[0]
    assert episodes.stats() == {"group": 1, "self": 1}, episodes.stats()
    print("PASS  /小本本 删除 连这个人的记忆一起删，别人的和她自己的不动")


def vectors() -> None:
    table = {"猫": [1.0, 0.0, 0.0], "宠物": [0.9, 0.1, 0.0], "考试": [0.0, 1.0, 0.0]}

    def fake(texts):
        return [episodes._norm(next((v for k, v in table.items() if k in t), [0.0, 0.0, 1.0])) for t in texts]

    real, episodes.embed = episodes.embed, fake
    try:
        cat = episodes.add("person", "他家养了只猫", B, "", "p", 3, vec=fake(["猫"])[0], now=NOW - 3 * DAY)
        episodes.add("person", "他下周考试", B, "", "p", 3, vec=fake(["考试"])[0], now=NOW - 3 * DAY)
        got = episodes.recall("想养宠物", B, "", chat="private_v", now=NOW)
        assert [r["id"] for r in got] == [cat], got  # 字面不重合也能按意思想起
        assert episodes.plan("他家养了只猫", fake(["猫"])[0], "person", B)[0] == "dup"
    finally:
        episodes.embed = real
    print("PASS  有向量时按意思想起（「宠物」想起「猫」）")

    episodes.CAP = 3
    for i in range(5):
        episodes.add("group", f"第{i}件事", "", "9", "g", 1 + (i == 0) * 4, now=NOW - (10 - i) * DAY)
    left = [r[0] for r in episodes._db().execute("select text from mem where gid = '9'").fetchall()]
    assert len(left) == 3 and "第0件事" in left, left  # 满了删最不重要、最淡的，重要的留着
    print("PASS  每个范围有上限，满了删最不重要、最淡的")


def main() -> int:
    rules()
    store()
    vectors()
    episodes.close()
    print("test_episodes: 全部通过", TMP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
