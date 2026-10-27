"""缓存清理：解析插件下载的视频/音频/图片默认只留一天，过期自动删。"""

from __future__ import annotations

import os
import time
from pathlib import Path

from nonebot.log import logger

TTL_HOURS = float(os.getenv("VIDEO_CACHE_TTL_HOURS", "24"))
MEDIA_SUFFIXES = {
    ".mp4", ".flv", ".mkv", ".webm", ".mov", ".m4s", ".ts",
    ".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg",
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
}


def cache_dir() -> Path | None:
    """优先用解析插件自己的缓存目录，其次环境变量覆盖。"""
    env = os.getenv("VIDEO_CACHE_DIR", "").strip()
    if env:
        return Path(env)
    try:
        from nonebot_plugin_parser import pconfig

        return Path(pconfig.cache_dir)
    except Exception:  # noqa: BLE001
        return None


def clean(root: Path | None = None, ttl_hours: float | None = None, now: float | None = None) -> dict:
    """删掉 root 下超过 ttl 的媒体文件，返回统计。"""
    root = root or cache_dir()
    ttl = TTL_HOURS if ttl_hours is None else ttl_hours
    now = time.time() if now is None else now
    cutoff = now - ttl * 3600
    stats = {"dir": str(root) if root else "", "files": 0, "freed": 0, "kept": 0, "ok": False}
    if not root or not root.is_dir():
        return stats
    stats["ok"] = True
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MEDIA_SUFFIXES:
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime > cutoff:
            stats["kept"] += 1
            continue
        try:
            path.unlink()
            stats["files"] += 1
            stats["freed"] += st.st_size
        except OSError as exc:
            logger.warning(f"cache_clean: 删不掉 {path.name}: {exc}")
    if stats["files"]:
        logger.info(
            f"cache_clean: 清掉 {stats['files']} 个过期媒体文件，释放 {stats['freed'] / 1048576:.1f}MB"
            f"（保留 {stats['kept']} 个，TTL {ttl:.0f}h）"
        )
    return stats


def size_of(root: Path | None = None) -> dict:
    root = root or cache_dir()
    total, files = 0, 0
    if root and root.is_dir():
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                    files += 1
                except OSError:
                    pass
    return {"dir": str(root) if root else "", "files": files, "bytes": total}
