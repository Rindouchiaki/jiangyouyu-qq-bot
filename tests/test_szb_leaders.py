"""szb 抓取脚本的 leader 映射（站点 Nm=ネメシス，Nmr=ナイトメア）。"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("szb_crawl_t", ROOT / "tools" / "szb_crawl.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def main() -> int:
    assert mod.LEADERS["Nm"] == "超越者", mod.LEADERS
    assert mod.LEADERS["Nmr"] == "梦魇", mod.LEADERS
    assert len(mod.LEADERS) == 7, mod.LEADERS
    assert mod.CLASS_JP["ネメシス"] == "超越者"
    assert mod.CLASS_JP["ナイトメア"] == "梦魇"
    print("test_szb_leaders: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
