"""后台数据的离线校验：只有全是开发者的对话能看、群日记里的关系认得出、关系图画得出来。"""

import io
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
    for _ in range(3):
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
        assert img.format == "PNG" and img.width == relation_graph.SIZE and img.height > relation_graph.SIZE
    empty = relation_graph.render("酱油鱼", [], [])
    with Image.open(io.BytesIO(empty)) as img:
        assert img.height == relation_graph.SIZE  # 没有认不出的关系就不加底栏
    print("PASS  关系图：她在中间、群友连线、认不出的关系列在下面，画得出 PNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
