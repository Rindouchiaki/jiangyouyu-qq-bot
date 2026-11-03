"""后台数据的离线校验：只有全是开发者的对话能看、群日记里的关系认得出、关系图画得出来。"""

import io
import math
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="backstage_"))
os.environ["PERSONA_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import bonds  # noqa: E402
import devs  # noqa: E402
from persona_rules import BACKSTAGE_PROMPT, DIARY_GROUP_PROMPT, parse_relation  # noqa: E402


def main() -> int:
    bot, a, b = "100000001", "289635657", "189963059"
    assert devs.only_devs([bot, a, b], bot) and devs.only_devs([a], bot) and devs.only_devs({a, b})
    assert not devs.only_devs([bot, a, "10002"], bot) and not devs.only_devs([bot], bot) and not devs.only_devs([])
    print("PASS  只有除了机器人全是开发者的对话才算内部对话")

    assert parse_relation("小红/小明：常一起打鸣潮") == ("小红", "小明", "常一起打鸣潮")
    assert parse_relation("阿猫、阿狗：情侣") == ("阿猫", "阿狗", "情侣")
    assert parse_relation("小红和小明常一起打鸣潮") == ("小红", "小明", "常一起打鸣潮")  # 旧格式尽量认
    assert parse_relation("小张是小李的室友") is None and parse_relation("本群爱玩谐音梗") is None
    assert parse_relation("小红/小红：自己") is None and parse_relation("") is None
    assert "甲/乙：关系" in DIARY_GROUP_PROMPT and "{topic}" in BACKSTAGE_PROMPT and "别逐条念" in BACKSTAGE_PROMPT
    print("PASS  群日记的关系拆成（甲, 乙, 关系），认不出的单独列")

    bonds.touch("10002", "小红", 0, now=1000.0)
    bonds.touch("10003", "小明", 0, now=1000.0)
    for _ in range(10):  # 初始熟悉 0，私聊 10 天才高过开发者保底 8
        bonds.touch("10003", "小明", 0, now=1000.0 + 86400 * (_ + 1), private=True)  # 熟悉度只有私聊才加
    bonds.touch(a, "酱酱鱼", 0, now=1000.0)
    bonds.add_group_notes("123", ["小红/小明：常一起打鸣潮"], now=1000.0)
    people = bonds.known_people(["10002", "10003", a, "99999"])
    assert [uid for uid, _ in people][:1] == ["10003"] and len(people) == 3, people  # 熟悉度高的在前，没记录的不算
    assert dict(people)[a]["aff"] >= 30  # 开发者按保底算
    assert bonds.known_groups() == ["123"]
    print("PASS  小本本能按群成员挑出记过的人、列出记过群日记的群")

    import relation_graph
    from PIL import Image

    png = relation_graph.render(
        "酱油鱼", [("小红", "普通"), ("小明", "亲近"), ("酱酱鱼", "有好感")],
        [("小红", "小明", "常一起打鸣潮"), ("小明", "路人乙", "同学")], ["小张是小李的室友"], "群 123 的关系图",
    )
    with Image.open(io.BytesIO(png)) as img:
        assert img.format == "PNG" and img.width == relation_graph.MIN_SIZE
        assert img.height > relation_graph.HEADER + relation_graph.MIN_SIZE  # 有认不出的关系就加底栏
    # 群日记写「我」、名片带后缀都并到中间；她和谁的关系写在连她的线上
    names, att, self_rel, pairs = relation_graph.arrange(
        "酱油鱼", [("小红", "普通"), ("酱油鱼🐟", "普通")],
        [("我", "小红", "常拉我聊番"), ("大肥鱼", "小明", "天天互怼"), ("小红", "小明", "同学"), ("我", "酱油鱼", "自己")],
        ("酱油鱼", "大肥鱼"),
    )
    assert sorted(names) == ["小明", "小红"] and "酱油鱼🐟" not in att, names
    assert self_rel == {"小红": "常拉我聊番", "小明": "天天互怼"} and pairs == [("小红", "小明", "同学")]
    assert "我/小红" in DIARY_GROUP_PROMPT
    empty = relation_graph.render("酱油鱼", [], [])
    with Image.open(io.BytesIO(empty)) as img:
        assert img.height == relation_graph.HEADER + relation_graph.MIN_SIZE  # 没有认不出的关系就不加底栏
    print("PASS  关系图：她在中间、群友连线、认不出的关系列在下面，画得出 PNG")

    # 大群：越亲近越靠里，一圈放不下往外加，人和人不叠；人多了图跟着变大，画不下的写在底下
    tiers = ["亲近", "有好感", "普通", "陌生", "讨厌", None]
    crowd = [(f"群友{i}", tiers[i % 6]) for i in range(120)]
    links = [(f"群友{i}", f"群友{i + 1}", "同学") for i in range(0, 60, 3)] + [("我", "群友7", "常拉我聊番")]
    names, att, _, pairs = relation_graph.arrange("酱油鱼", crowd, links)
    pos, r, outer = relation_graph.layout(names[: relation_graph.MAX_PEOPLE], att, pairs)
    pts = list(pos.values())
    assert len(pts) == relation_graph.MAX_PEOPLE
    assert all(math.dist(a, b) >= 2 * r for i, a in enumerate(pts) for b in pts[i + 1:])
    dist = {n: math.hypot(*xy) for n, xy in pos.items()}
    close = [dist[n] for n in pos if att.get(n) == "亲近"]
    far = [dist[n] for n in pos if att.get(n) in ("陌生", "讨厌")]
    assert max(close) <= min(far), (max(close), min(far))
    assert relation_graph.node_radius(6) > relation_graph.node_radius(80)
    big = relation_graph.render("酱油鱼", crowd, links, [], "大群")
    with Image.open(io.BytesIO(big)) as img:
        assert img.width > relation_graph.MIN_SIZE and img.height > img.width  # 底下列着编号的关系和没画进来的人
    assert relation_graph.caption_lines("常拉我聊番") == ["常拉我聊番"]
    assert relation_graph.caption_lines("一起打了一整个暑假的鸣潮") == ["一起打了一整个", "暑假的鸣潮"]
    print("PASS  大群关系图：按亲近程度一圈圈往外排、人不叠、图跟着变大，画不下的写明")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
