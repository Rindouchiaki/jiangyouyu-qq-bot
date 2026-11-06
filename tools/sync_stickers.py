"""同步表情索引：把「图片已经删了、索引里还留着」的条目清掉。

手动删过 `stickers/ori/` 或 `stickers/saved/` 里的图之后，`index.json` / `saved.json`
里会留下指向不存在文件的条目；`notes.json`、`reads.json` 也会留着这些死 id。
这个脚本按文件是否存在重建这几份数据，顺手把 `count` 改对。

用法：
    python tools/sync_stickers.py                 # 默认同步 repo 下的 stickers/
    python tools/sync_stickers.py --dir stickers  # 指定目录
    python tools/sync_stickers.py --dry-run       # 只报告，不写文件
"""

import argparse
import json
from pathlib import Path

INDEX_FILES = ("index.json", "saved.json")
ID_MAPS = ("notes.json", "reads.json")


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} 不是合法 JSON：{exc}") from exc


def _dump(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sync(root: Path, dry_run: bool = False) -> dict:
    """返回 {文件名: (原条数, 保留条数)}；dry_run 时不落盘。"""
    report = {}
    alive_ids: set[str] = set()

    for name in INDEX_FILES:
        path = root / name
        if not path.is_file():
            continue
        data = _load(path, None)
        if data is None:
            continue
        items = data.get("items") or []
        keep = [it for it in items if (root / str(it.get("file", ""))).is_file()]
        report[name] = (len(items), len(keep))
        alive_ids.update(str(it.get("id")) for it in keep if it.get("id"))
        data["items"] = keep
        if "count" in data:
            data["count"] = len(keep)
        if not dry_run:
            _dump(path, data)

    if alive_ids:
        for name in ID_MAPS:
            path = root / name
            if not path.is_file():
                continue
            data = _load(path, {})
            if not isinstance(data, dict):
                continue
            keep_map = {k: v for k, v in data.items() if k in alive_ids}
            report[name] = (len(data), len(keep_map))
            if not dry_run:
                _dump(path, keep_map)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="清理表情索引里指向已删除图片的条目")
    parser.add_argument("--dir", default="stickers", help="表情目录（默认 stickers）")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit(f"找不到目录 {root}")
    report = sync(root, args.dry_run)
    if not report:
        print(f"{root} 里没有可同步的索引文件")
        return 0
    for name, (before, after) in report.items():
        removed = before - after
        print(f"{name}: {before} → {after}" + (f"（清掉 {removed} 条）" if removed else "（无变化）"))
    if args.dry_run:
        print("dry-run：没有写文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
