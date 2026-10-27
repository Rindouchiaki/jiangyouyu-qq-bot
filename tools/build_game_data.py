"""手动重建游戏数据索引（等价于插件里的强制刷新）。

用法：
    python tools/build_game_data.py          # 过期才刷新
    python tools/build_game_data.py --force  # 强制刷新
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import game_data  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略缓存，强制重新抓取")
    args = ap.parse_args()

    refreshed, msg = game_data.ensure_fresh(force=args.force)
    print(("已刷新: " if refreshed else "未刷新: ") + msg)

    index = game_data.load_index()
    hsr = index.get("hsr", {}).get("items", [])
    zzz = index.get("zzz", {}).get("items", [])
    meta = index.get("meta", {})
    print(f"HSR {len(hsr)} 个，ZZZ {len(zzz)} 个，zzz 版本 {meta.get('zzz_version')}")
    if hsr:
        print("HSR 示例:", [c["name"] for c in hsr[:4]])
    if zzz:
        print("ZZZ 示例:", [c["name"] for c in zzz[:4]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
