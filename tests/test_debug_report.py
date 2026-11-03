"""debug 群的纯逻辑：报错攒批、合并重复、限流，读日志文件。临时目录里跑，不连 QQ。"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import debug_report  # noqa: E402
import devs  # noqa: E402

NOW = datetime(2026, 11, 4, 10, 0, 0).timestamp()


def main() -> int:
    assert devs.DEBUG_GROUP == "895462706"

    c = debug_report.Collector(hourly_max=3)
    assert c.drain(NOW) == []
    for i in range(5):  # 数字不同也算同一类，只记次数
        c.add("WARNING", "persona", f"persona: 摘个人日记失败 TimeoutError: 第 {i} 次", now=NOW + i)
    c.add("ERROR", "knowledge", "\x1b[31m学「影之诗」出错\x1b[0m", "Traceback (most recent call last):\n  ...\nValueError: x", NOW + 9)
    out = c.drain(NOW + 30)
    text = "\n".join(out)
    assert len(out) == 1 and "×5" in text and "[警告] 10:00:00~10:00:04 ×5 persona" in text, text
    assert "[错误]" in text and "ValueError: x" in text and "\x1b" not in text, text
    assert c.drain(NOW + 60) == []  # 发过就清空
    print("PASS  报错攒一批发：同一类只记次数，带上错误堆栈，去掉颜色码")

    for i in range(2):  # 上面那批已经用掉这个小时 3 条里的 1 条
        c.add("WARNING", "x", f"第 {i} 种 不一样的错 {'abc'[i]}", now=NOW + 100 + i)
        assert c.drain(NOW + 130 + i)
    c.add("WARNING", "x", "这个小时发够了", now=NOW + 200)
    assert c.drain(NOW + 230) == []  # 一小时最多 3 条，压着
    c.add("WARNING", "x", "下个小时的", now=NOW + 3600)
    later = "\n".join(c.drain(NOW + 3630))
    assert "压了 1 条没发" in later and "下个小时的" in later, later
    print("PASS  每小时有上限，压下的下个小时说一声")

    long = debug_report.chunks("\n".join("一行" * 50 for _ in range(100)), 500)
    assert all(len(part) <= 500 for part in long) and "".join(long).count("一行") == 5000
    assert debug_report.chunks("x" * 1200, 500) == ["x" * 500, "x" * 500, "x" * 200]
    print("PASS  长消息按行切段")

    log = Path(tempfile.mkdtemp(prefix="debuglog_")) / "nonebot.out.log"
    rows = [f"11-04 10:00:{i:02d} [INFO] persona | 第 {i} 行" for i in range(50)]
    rows[10] = "11-04 10:00:10 [WARNING] persona | \x1b[33m摘日记失败\x1b[0m"
    rows[20] = "11-04 10:00:20 [ERROR] knowledge | 出错了"
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert debug_report.tail(log, 3) == [rows[47], rows[48], rows[49]]
    assert debug_report.tail(log, 30, errors=True) == ["11-04 10:00:10 [WARNING] persona | 摘日记失败", rows[20]]
    assert debug_report.tail(log, 30, keyword="第 3 行") == [rows[3]]
    assert debug_report.tail(log.with_name("nope.log")) == []
    assert len(debug_report.tail(log, 30, scan_bytes=200)) <= 4  # 只读文件末尾一段
    assert debug_report.parse_log_args("") == (30, "", False)
    assert debug_report.parse_log_args("100 错误") == (100, "", True)
    assert debug_report.parse_log_args("999 persona") == (200, "persona", False)
    print("PASS  /日志：最后几行、只看报错、按关键词、行数有上限")
    print("test_debug_report: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
