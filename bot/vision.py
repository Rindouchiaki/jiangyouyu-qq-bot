"""本地图片感知：把一张图压成不超过 60 字的「图卡」，喂给模型。

顺序：
1. sha1 / dhash 命中表情库 → 直接给出类别和图上文字（0 计算）；
2. 未命中 → Windows 自带 OCR（Windows.Media.Ocr，离线）读字；
3. 还是没字 → 本地视觉模型（默认 llama.cpp 的 Qwen3-VL）描述一句；
4. 结果按 sha1 缓存，同一张图只算一次。

表情（库里的、群友发的）另外让视觉模型「读」一遍：动图截几帧拼成一张给它看，记下画面、意思、
适合的场景和画风（sticker_lib 的读后感，按 id 存，读过不再读），图卡就用这个，之后不再花算力。

全部本机完成，不调用任何在线识图接口。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from PIL import Image

import sticker_lib
from persona_rules import STICKER_READ_ANIM, STICKER_READ_PROMPT, parse_sticker_read, sticker_card

IMG_CARD_ENABLED = os.getenv("IMAGE_CARD_ENABLED", "1") not in ("0", "false", "False")
IMG_CARD_MAX = int(os.getenv("IMAGE_CARD_MAX_CHARS", "60"))
IMG_FETCH_MAX_MB = float(os.getenv("IMAGE_FETCH_MAX_MB", "5"))
IMG_OCR_TIMEOUT = float(os.getenv("IMAGE_OCR_TIMEOUT", "20"))
VLM_ENABLED = os.getenv("VLM_ENABLED", "1") not in ("0", "false", "False")
VLM_PROVIDER = os.getenv("VLM_PROVIDER", "openai").strip().lower()   # openai(llama.cpp) | ollama
VLM_MODEL = os.getenv("VLM_MODEL", "qwen2.5vl:3b")
VLM_URL = os.getenv("VLM_URL", "http://127.0.0.1:11434")
VLM_OPENAI_URL = os.getenv("VLM_OPENAI_URL", "http://127.0.0.1:11435").rstrip("/")
VLM_TIMEOUT = float(os.getenv("VLM_TIMEOUT", "120"))

BASE_DIR = Path(__file__).resolve().parent
OCR_SCRIPT = Path(os.getenv("OCR_SCRIPT", str(BASE_DIR.parent / "tools" / "ocr_win.ps1")))
STICKER_DIR = Path(os.getenv("STICKER_DIR") or BASE_DIR.parent / "stickers")
CACHE_DIR = Path(os.getenv("VISION_CACHE_DIR", str(BASE_DIR / "data" / "vision")))
HASH_CACHE = Path(os.getenv("STICKER_HASH_CACHE", str(BASE_DIR / "data" / "sticker_hashes.json")))
CARD_CACHE = CACHE_DIR / "cards.json"
CARD_CACHE_MAX = 3000
# 图卡格式变了就加一：旧缓存作废（v2 起表情用读后感）
CARD_VERSION = 2

_hashes: dict[str, str] = {}       # sha1 -> sticker id
_dhashes: dict[str, list[int]] = {}  # sticker id -> 多帧 dhash（静图一帧，动图最多几帧）
_cards: dict[str, dict] = {}       # sha1 -> {"at": ts, "card": str}
_vlm_state: tuple[float, bool] = (0.0, False)

# 动图只存一帧的首图哈希对不上：QQ 那边动图表情往往只剩一张中间帧的静态预览。
# 所以每张表情存多帧哈希，命中任意一帧就算认出。
HASH_VERSION = 2
DHASH_DIST_MAX = int(os.getenv("STICKER_DHASH_DIST", "6"))
FRAME_SAMPLES = int(os.getenv("STICKER_FRAME_SAMPLES", "4"))
OCR_FRAME_SAMPLES = int(os.getenv("STICKER_OCR_FRAMES", "3"))


# ---------------------------------------------------------------- 缓存
def _load_cards() -> None:
    global _cards
    try:
        _cards = json.loads(CARD_CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        _cards = {}


def _save_cards() -> None:
    if len(_cards) > CARD_CACHE_MAX:
        for key, _ in sorted(_cards.items(), key=lambda kv: kv[1].get("at", 0))[: len(_cards) - CARD_CACHE_MAX]:
            _cards.pop(key, None)
    try:
        CARD_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CARD_CACHE.write_text(json.dumps(_cards, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.debug(f"vision: 写缓存失败 {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- 表情库哈希
def _dhash(img: Image.Image) -> int:
    small = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            left = px[row * 9 + col]
            right = px[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _frame_indices(n_frames: int, k: int) -> list[int]:
    """挑要抽样哪几帧：首帧、中间、末帧优先，不够再均匀补。"""
    if n_frames <= 1 or k <= 1:
        return [0]
    picked = {0, n_frames // 2, n_frames - 1}
    step = max(1, n_frames // max(k, 2))
    idx = 0
    while len(picked) < k and idx < n_frames:
        picked.add(idx)
        idx += step
    return sorted(picked)[:k]


def _frame_dhashes(img: Image.Image, k: int = FRAME_SAMPLES) -> list[int]:
    """一张图（可能是动图）的多帧 dhash，跳过全透明/全黑的空帧。"""
    n_frames = getattr(img, "n_frames", 1) or 1
    out: list[int] = []
    for idx in _frame_indices(n_frames, k):
        try:
            img.seek(idx)
        except (EOFError, ValueError):
            break
        frame = img.convert("RGB")
        lo, hi = frame.convert("L").getextrema()
        if hi - lo < 8:  # 空帧没有信息量，比了也是误判
            continue
        value = _dhash(frame)
        if value not in out:
            out.append(value)
    if not out:
        img.seek(0)
        out = [_dhash(img.convert("RGB"))]
    return out


def _build_index() -> None:
    global _hashes, _dhashes
    if _hashes:
        return
    try:
        items = json.loads((STICKER_DIR / "index.json").read_text(encoding="utf-8")).get("items", [])
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning(f"vision: 表情索引不可用 {type(exc).__name__}")
        return

    cached: dict = {}
    try:
        cached = json.loads(HASH_CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cached = {}

    stamp = str((STICKER_DIR / "index.json").stat().st_mtime) if (STICKER_DIR / "index.json").is_file() else ""
    if (cached.get("stamp") == stamp and cached.get("hashes")
            and cached.get("version") == HASH_VERSION and cached.get("dhashes")):
        _hashes = cached["hashes"]
        _dhashes = {k: [int(v, 16) for v in vs] for k, vs in cached["dhashes"].items()}
        logger.info(f"vision: 表情哈希缓存 {len(_hashes)} 张 / {sum(len(v) for v in _dhashes.values())} 帧")
        return

    frames_total = 0
    for item in items:
        path = STICKER_DIR / item["file"]
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            _hashes[hashlib.sha1(raw).hexdigest()] = item["id"]
            with Image.open(io.BytesIO(raw)) as img:
                values = _frame_dhashes(img)
            _dhashes[item["id"]] = values
            frames_total += len(values)
        except (OSError, ValueError) as exc:
            logger.debug(f"vision: 跳过 {item['file']} {type(exc).__name__}")
    try:
        HASH_CACHE.parent.mkdir(parents=True, exist_ok=True)
        HASH_CACHE.write_text(
            json.dumps({
                "version": HASH_VERSION,
                "stamp": stamp,
                "hashes": _hashes,
                "dhashes": {k: [format(v, "016x") for v in vs] for k, vs in _dhashes.items()},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    logger.info(f"vision: 表情库索引 {len(_hashes)} 张 / {frames_total} 帧（sha1+多帧 dhash）")


def _match_sticker(raw: bytes, img: Image.Image) -> dict | None:
    _build_index()
    sid = _hashes.get(hashlib.sha1(raw).hexdigest())
    if sid is None and _dhashes:
        # 动图预览帧可能是任意一帧，所以拿多帧哈希两两比，取最近的那个
        incoming = _frame_dhashes(img)
        best, best_id = DHASH_DIST_MAX + 1, None
        for item_id, stored in _dhashes.items():
            if not stored:
                continue
            dist = min(bin(a ^ b).count("1") for a in incoming for b in stored)
            if dist < best:
                best, best_id = dist, item_id
                if best == 0:
                    break
        if best <= DHASH_DIST_MAX:
            sid = best_id
    if sid is None:
        return None
    try:
        items = json.loads((STICKER_DIR / "index.json").read_text(encoding="utf-8")).get("items", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    for item in items:
        if item.get("id") == sid:
            return item
    return None


# ---------------------------------------------------------------- OCR
def _clean_text(text: str) -> str:
    text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9，。！？、,.!?~“”‘’：:；;（）()\[\]…—\-]", "", text)
    text = re.sub(r"\s+", "", text)
    text = text.strip("·、。，,.；;：:")
    return text


async def _ocr(png_bytes: bytes) -> str:
    if not OCR_SCRIPT.is_file():
        logger.warning(f"vision: 找不到 OCR 脚本 {OCR_SCRIPT}")
        return ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".png", dir=str(CACHE_DIR))
    os.close(fd)
    path = Path(tmp)
    path.write_bytes(png_bytes)
    try:
        shell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        try:
            proc = await asyncio.create_subprocess_exec(
                shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(OCR_SCRIPT), "-Path", str(path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            # 认不了字也别耽误后面让视觉模型看
            logger.warning(f"vision: OCR 起不来 {type(exc).__name__}: {exc}")
            return ""
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=IMG_OCR_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("vision: OCR 超时")
            return ""
        if proc.returncode != 0:
            logger.warning(f"vision: OCR 退出码 {proc.returncode} {err[:120]!r}")
            return ""
        return _clean_text(out.decode("utf-8", errors="ignore"))
    finally:
        try:
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- VLM（可选）
async def _vlm_ok() -> bool:
    global _vlm_state
    ts, ok = _vlm_state
    if time.time() - ts < 30:
        return ok
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            if VLM_PROVIDER == "openai":
                r = await client.get(f"{VLM_OPENAI_URL}/health")
            else:
                r = await client.get(f"{VLM_URL}/api/tags")
            ok = r.status_code == 200
    except Exception:  # noqa: BLE001
        ok = False
    _vlm_state = (time.time(), ok)
    return ok


async def _describe(png_bytes: bytes) -> str:
    return _clean_text(await _vlm_ask(png_bytes, "用不超过二十个字描述这张图，只说要紧的，不要客套话。", 60))


async def _vlm_ask(png_bytes: bytes, prompt: str, max_tokens: int) -> str:
    """问本地视觉模型一句，返回原文（失败返回空串）。"""
    b64 = base64.b64encode(png_bytes).decode()
    try:
        if VLM_PROVIDER == "openai":
            payload = {
                "model": VLM_MODEL,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "stream": False,
            }
            async with httpx.AsyncClient(timeout=VLM_TIMEOUT) as client:
                r = await client.post(f"{VLM_OPENAI_URL}/v1/chat/completions", json=payload)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"] or ""
        payload = {
            "model": VLM_MODEL,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=VLM_TIMEOUT) as client:
            r = await client.post(f"{VLM_URL}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"vision: 本地视觉模型失败 {type(exc).__name__}: {exc}")
        return ""


# ---------------------------------------------------------------- 读表情
SHEET_CELL = 256


def _ffmpeg_exe() -> str:
    """一键启动会把 tools\\ffmpeg\\bin 放进 PATH；没有就用 imageio-ffmpeg 自带的那份。"""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return ""


def _ffmpeg_frames(raw: bytes, n_frames: int, k: int) -> list[Image.Image]:
    """用 ffmpeg 把动图均匀抽 k 帧（完整合成后的画面，不是 GIF 里只存了变化部分的那种帧）。"""
    exe = _ffmpeg_exe()
    if not exe:
        return []
    picks = "+".join(f"eq(n\\,{i})" for i in _frame_indices(n_frames, k))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.gif"
        src.write_bytes(raw)
        cmd = [
            exe, "-v", "error", "-i", str(src),
            "-vf", f"select={picks}", "-vsync", "0", "-frames:v", str(k),
            str(Path(tmp) / "f%02d.png"),
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        except (OSError, subprocess.SubprocessError):
            return []
        frames = []
        for path in sorted(Path(tmp).glob("f*.png")):
            with Image.open(path) as im:
                frames.append(im.convert("RGBA").copy())
        return frames


def _pil_frames(img: Image.Image, n_frames: int, k: int) -> list[Image.Image]:
    frames = []
    for idx in _frame_indices(n_frames, k):
        try:
            img.seek(idx)
        except (EOFError, ValueError):
            break
        frames.append(img.convert("RGBA").copy())
    return frames


def _sheet_png(raw: bytes, img: Image.Image, n_frames: int) -> bytes:
    """给视觉模型看的一张图：静图放大到能看清；动图截 4 帧拼成 2x2，透明底垫白。"""
    k = min(4, n_frames)
    frames = (_ffmpeg_frames(raw, n_frames, k) if n_frames > 1 else []) or _pil_frames(img, n_frames, k)
    if not frames:
        img.seek(0)
        frames = [img.convert("RGBA")]
    cols = 1 if len(frames) == 1 else 2
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (SHEET_CELL * cols, SHEET_CELL * rows), "white")
    for i, frame in enumerate(frames):
        frame = frame.copy()
        scale = SHEET_CELL / max(frame.size)
        frame = frame.resize((max(1, int(frame.width * scale)), max(1, int(frame.height * scale))), Image.Resampling.LANCZOS)
        x = (i % cols) * SHEET_CELL + (SHEET_CELL - frame.width) // 2
        y = (i // cols) * SHEET_CELL + (SHEET_CELL - frame.height) // 2
        sheet.paste(frame, (x, y), frame)
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    return buf.getvalue()


async def read_sticker(raw: bytes) -> dict | None:
    """让视觉模型读一张表情：画面、意思、场景、画风、可不可爱。没开、没起来或没看懂返回 None。"""
    if not VLM_ENABLED or not await _vlm_ok():
        return None
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            n_frames = getattr(img, "n_frames", 1) or 1
            png = await asyncio.to_thread(_sheet_png, raw, img, n_frames)
    except (OSError, ValueError) as exc:
        logger.debug(f"vision: 读表情时打不开图 {type(exc).__name__}")
        return None
    prompt = STICKER_READ_PROMPT.format(anim=STICKER_READ_ANIM if n_frames > 1 else "")
    return parse_sticker_read(await _vlm_ask(png, prompt, 120))


def in_library(raw: bytes) -> bool:
    """这张图是不是原库里的表情（按 sha1 / 多帧 dhash 认）。"""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            return _match_sticker(raw, img) is not None
    except (OSError, ValueError):
        return False


async def vlm_ready() -> bool:
    return VLM_ENABLED and await _vlm_ok()


async def _read_or_cached(sid: str, raw: bytes) -> dict | None:
    """读后感按 id 只读一次（后台读过但没看懂的不在这里重读）。"""
    if sticker_lib.has_read(sid):
        return sticker_lib.read_of(sid)
    read = await read_sticker(raw)
    if read:
        sticker_lib.set_read(sid, read)
    return read


# ---------------------------------------------------------------- 取图
def _seg_url(seg) -> str:
    data = seg.data or {}
    for key in ("url", "file", "path"):
        value = str(data.get(key) or "")
        if value.startswith(("http://", "https://", "file://", "base64://")):
            return value
    path = str(data.get("path") or "")
    if path and Path(path).is_file():
        return Path(path).as_uri()
    return ""


async def _fetch(seg) -> bytes | None:
    url = _seg_url(seg)
    if not url:
        return None
    if url.startswith("base64://"):
        return base64.b64decode(url[len("base64://"):])
    if url.startswith("file://"):
        try:
            return Path(url2pathname(unquote(urlparse(url).path))).read_bytes()
        except (OSError, ValueError):
            return None
    limit = int(IMG_FETCH_MAX_MB * 1024 * 1024)
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > limit:
                        logger.warning(f"vision: 图太大（>{IMG_FETCH_MAX_MB:g}MB），跳过")
                        return None
                return bytes(buf)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"vision: 下载图片失败 {type(exc).__name__}: {exc}")
        return None


async def fetch_seg(seg) -> bytes | None:
    """取图片段的原始字节（收藏表情用）。"""
    return await _fetch(seg)


# ---------------------------------------------------------------- 图卡
async def image_card(event: MessageEvent) -> str:
    """把消息里的第一张图压成图卡；没有图返回空串。"""
    if not IMG_CARD_ENABLED:
        return ""
    seg = next((s for s in event.get_message() if s.type == "image"), None)
    if seg is None:
        return ""
    return await card_for_seg(seg)


def _frame_png(img: Image.Image, idx: int) -> bytes:
    """取动图的第 idx 帧，缩到最长边 1600 转 PNG（省 OCR 时间，也不影响识别）。"""
    try:
        img.seek(idx)
    except (EOFError, ValueError):
        pass
    frame = img.convert("RGB")
    if max(frame.size) > 1600:
        frame.thumbnail((1600, 1600))
    buf = io.BytesIO()
    frame.save(buf, format="PNG")
    return buf.getvalue()


def _busiest_frame(img: Image.Image, n_frames: int) -> int:
    """挑信息量最大的那一帧给视觉模型看（对比度高的通常画面最完整）。"""
    best_idx, best_score = 0, -1
    for idx in _frame_indices(n_frames, FRAME_SAMPLES):
        try:
            img.seek(idx)
        except (EOFError, ValueError):
            break
        lo, hi = img.convert("L").getextrema()
        if hi - lo > best_score:
            best_idx, best_score = idx, hi - lo
    return best_idx


async def _ocr_animated(img: Image.Image, n_frames: int) -> str:
    """动图逐帧 OCR：文字往往只在某几帧出现，取识别到的最长一段。"""
    best = ""
    for idx in _frame_indices(n_frames, OCR_FRAME_SAMPLES):
        text = _clean_text(await _ocr(_frame_png(img, idx)))
        if len(text) > len(best):
            best = text
        if len(best) >= 8:  # 已经够一句了，别再多烧 OCR
            break
    return best


async def card_for_seg(seg) -> str:
    """给单个 image 段做图卡（支持拿「上一条图片消息」的段来补看）。"""
    if not IMG_CARD_ENABLED or seg is None:
        return ""
    raw = await _fetch(seg)
    if not raw:
        return "[图片]"

    sha1 = hashlib.sha1(raw).hexdigest()
    cached = _cards.get(sha1)
    if cached and cached.get("v") == CARD_VERSION and time.time() - cached.get("at", 0) < 86400 * 7:
        return cached.get("card", "")

    data = getattr(seg, "data", None) or {}
    hint_anim = str(data.get("sub_type", "")) == "1" or "动画表情" in str(data.get("summary", ""))
    is_sticker = str(data.get("sub_type", "")) == "1" or "表情" in str(data.get("summary", ""))

    card = "[图片]"
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()  # 动图先落在首帧，后面按需 seek
            width, height = img.size
            n_frames = getattr(img, "n_frames", 1) or 1
            animated = n_frames > 1 or hint_anim
            sticker = _match_sticker(raw, img)
            if sticker:
                cat = sticker.get("category") or "表情"
                text = _clean_text(sticker.get("text") or "")
                lib_file = STICKER_DIR / sticker["file"]
                read = await _read_or_cached(sticker["id"], lib_file.read_bytes() if lib_file.is_file() else raw)
                if read:
                    card = sticker_card(read, text, bool(animated or sticker.get("animated")))
                elif animated or sticker.get("animated"):
                    card = f"[表情:动图｜{cat}｜{text[:20]}]" if len(text) >= 2 else f"[表情:动图｜{cat}]"
                else:
                    card = f"[表情:{cat}｜{text[:20]}]" if len(text) >= 2 else f"[表情:{cat}]"
            else:
                if n_frames > 1:
                    text = await _ocr_animated(img, n_frames)
                else:
                    text = _clean_text(await _ocr(_frame_png(img, 0)))
                read = await _read_or_cached(sha1[:16], raw) if is_sticker or animated else None
                if read:
                    card = sticker_card(read, text, animated)
                elif len(text) >= 2:
                    kind = "截图" if (width > 600 and (width / max(height, 1) > 1.2 or height / max(width, 1) > 1.2)) else "图"
                    head = "动图" if animated else "图片"
                    card = f"[{head}:{kind}｜{text[:IMG_CARD_MAX]}]"
                elif VLM_ENABLED and await _vlm_ok():
                    desc = await _describe(_frame_png(img, _busiest_frame(img, n_frames)))
                    if desc:
                        card = f"[动图:{desc[:30]}]" if animated else f"[图片:{desc[:30]}]"
    except (OSError, ValueError) as exc:
        logger.warning(f"vision: 图片解析失败 {type(exc).__name__}: {exc}")

    _cards[sha1] = {"at": time.time(), "card": card, "v": CARD_VERSION}
    _save_cards()
    return card


def stats() -> dict:
    _build_index()
    return {
        "hashes": len(_hashes),
        "frames": sum(len(v) for v in _dhashes.values()),
        "cards": len(_cards),
        "ocr_script": OCR_SCRIPT.is_file(),
        "vlm": VLM_ENABLED,
        "vlm_model": VLM_MODEL,
    }


_load_cards()
