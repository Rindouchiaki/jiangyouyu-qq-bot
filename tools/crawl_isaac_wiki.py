r"""抓以撒灰机 wiki（isaac.huijiwiki.com）存成本地知识库，给人设和 /以撒 用。

页面正文 → 去标签 → 切块 → 本机 Ollama bge-m3 向量 → SQLite（bot/data/isaac_wiki.db）。

站点在 Cloudflare 交互式挑战后面，直接 requests/httpx 一律 403，所以这里用 Playwright
的浏览器上下文取一次通行证，然后**在页面里** fetch api.php（同源、带 cookie）。

用法：
    python tools/crawl_isaac_wiki.py                 # 全量（约 3000 篇，十几分钟）
    python tools/crawl_isaac_wiki.py --limit 50      # 先抓 50 篇试水
    python tools/crawl_isaac_wiki.py --no-embed      # 只存文字，不建向量
"""

from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

BASE = "https://isaac.huijiwiki.com"
DEFAULT_DB = ROOT / "bot" / "data" / "isaac_wiki.db"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

MAX_CHUNK = 600
MIN_CHUNK = 40

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_REF_RE = re.compile(r"<sup[^>]*class=\"[^\"]*reference[^\"]*\"[^>]*>.*?</sup>", re.S | re.I)
_BLOCK_RE = re.compile(r"</(p|div|li|tr|h[1-6]|table|section|blockquote|dd|dt)>|<br\s*/?>", re.I)
_SPACE_RE = re.compile(r"[ \t\u3000]+")
_EDIT_RE = re.compile(r"\[\s*(编辑|edit)\s*\]", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    title TEXT UNIQUE NOT NULL,
    display TEXT,
    url TEXT,
    chars INTEGER DEFAULT 0,
    fetched_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL,
    ord INTEGER DEFAULT 0,
    text TEXT NOT NULL,
    vec BLOB
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS chunks_page ON chunks(page_id);
"""


def _db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    _migrate(con)
    return con


_ID_TITLE_RE = re.compile(r"^[A-Z]+\d+$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 编号页正文开头先是「道具」「饰品」这种分类词，不是名字
_TYPE_WORDS = {"道具", "饰品", "卡片", "角色", "怪物", "成就", "实体", "标签", "房间"}


def guess_display(title: str, text: str) -> str:
    """道具/饰品页的标题是 C164、T29 这种编号，真名在正文开头几行里。"""
    if not _ID_TITLE_RE.match(title or ""):
        return title or ""
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
    if lines and lines[0].startswith("【"):
        lines = lines[1:]
    for name in lines[:4]:
        if name in _TYPE_WORDS or not _CJK_RE.search(name):
            continue
        if 2 <= len(name) <= 16 and " " not in name:
            return name
    return title or ""


def _migrate(con: sqlite3.Connection) -> None:
    """老库补 display 列，从第一块正文里把名字捞出来。"""
    cols = {row[1] for row in con.execute("pragma table_info(pages)")}
    if "display" in cols:
        return
    con.execute("alter table pages add column display TEXT")
    _backfill_display(con)


def _backfill_display(con: sqlite3.Connection) -> None:
    for pid, title in con.execute("select id, title from pages").fetchall():
        if not _ID_TITLE_RE.match(title or ""):
            continue
        row = con.execute("select text from chunks where page_id=? order by ord limit 1", (pid,)).fetchone()
        if not row:
            continue
        display = guess_display(title, row[0] or "")
        con.execute("update pages set display=? where id=?", (display if display != title else None, pid))
    con.commit()


def clean_html(raw: str) -> str:
    """HTML → 纯文本：去脚本、引用角标、标签，块级元素换行。"""
    text = _SCRIPT_RE.sub("", raw or "")
    text = _REF_RE.sub("", text)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html_lib.unescape(text)
    text = _EDIT_RE.sub("", text)
    lines = []
    for line in text.split("\n"):
        line = _SPACE_RE.sub(" ", line).strip()
        if not line:
            continue
        # 目录、导航这种一行几个字的碎片不要
        if len(line) <= 1:
            continue
        lines.append(line)
    return "\n".join(lines)


def chunk_text(text: str, max_chars: int = MAX_CHUNK) -> list[str]:
    """按行攒块；一行太长就按句号切开，块之间不重叠。"""
    pieces: list[str] = []
    for line in text.split("\n"):
        if len(line) <= max_chars:
            pieces.append(line)
            continue
        buf = ""
        for sent in re.split(r"(?<=[。！？；])", line):
            if not sent:
                continue
            if len(buf) + len(sent) > max_chars and buf:
                pieces.append(buf)
                buf = ""
            buf += sent
        if buf:
            pieces.append(buf)

    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + len(piece) + 1 > max_chars:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)
    return [c.strip() for c in chunks if len(c.strip()) >= MIN_CHUNK]


async def _fetch_json(page, url: str, retry: int = 3):
    last = None
    for i in range(retry):
        try:
            text = await page.evaluate(
                "async (u) => { const r = await fetch(u, {credentials: 'include'});"
                " if (!r.ok) return '__HTTP_' + r.status; return await r.text(); }",
                url,
            )
            if isinstance(text, str) and text.startswith("__HTTP_"):
                last = text
            else:
                return json.loads(text)
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(1.5 * (i + 1))
    print(f"[warn] 取不到 {url[:90]} ({last})")
    return None


async def list_titles(page) -> list[str]:
    titles: list[str] = []
    cont = ""
    while True:
        url = (
            f"{BASE}/api.php?action=query&list=allpages&aplimit=500&apnamespace=0"
            f"&apfilterredir=nonredirects&format=json&formatversion=2{cont}"
        )
        data = await _fetch_json(page, url)
        if not data:
            break
        for item in (data.get("query") or {}).get("allpages") or []:
            title = (item.get("title") or "").strip()
            if title:
                titles.append(title)
        nxt = data.get("continue") or {}
        if not nxt.get("apcontinue"):
            break
        cont = f"&apcontinue={_quote(nxt['apcontinue'])}"
        print(f"[titles] {len(titles)} …")
    return titles


def _quote(text: str) -> str:
    from urllib.parse import quote

    return quote(str(text), safe="")


async def fetch_page_html(page, title: str) -> str:
    url = f"{BASE}/api.php?action=parse&page={_quote(title)}&prop=text&format=json&formatversion=2&redirects=1"
    data = await _fetch_json(page, url)
    if not data or "parse" not in data:
        return ""
    return ((data.get("parse") or {}).get("text")) or ""


async def crawl(args) -> int:
    from playwright.async_api import async_playwright

    db = _db(Path(args.db))
    con = db
    done = {row[0] for row in con.execute("select title from pages")}
    if args.force:
        con.execute("delete from pages")
        con.execute("delete from chunks")
        con.commit()
        done = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(locale="zh-CN", user_agent=UA)
        page = await ctx.new_page()
        await page.goto(f"{BASE}/wiki/%E9%A6%96%E9%A1%B5", wait_until="domcontentloaded", timeout=90000)
        print("[ok] 通行证到手：", await page.title())

        titles = await list_titles(page)
        if not args.all_titles:
            titles = [t for t in titles if re.search(r"[\u4e00-\u9fff]", t)]
        print(f"[ok] 词条 {len(titles)} 个")
        todo = [t for t in titles if t not in done]
        if args.limit:
            todo = todo[: args.limit]
        print(f"[ok] 待抓 {len(todo)} 个（库里已有 {len(done)}）")

        sem = asyncio.Semaphore(max(1, args.concurrency))
        stats = {"ok": 0, "empty": 0, "bad": 0}
        t0 = time.time()

        async def one(title: str) -> None:
            async with sem:
                raw = await fetch_page_html(page, title)
            if not raw:
                stats["bad"] += 1
                return
            text = clean_html(raw)
            if len(text) < 20:
                stats["empty"] += 1
                text = ""
            async with asyncio.Lock():
                cur = con.execute(
                    "insert or replace into pages(title, display, url, chars, fetched_at) values (?,?,?,?,?)",
                    (title, guess_display(title, text), f"{BASE}/wiki/{_quote(title)}", len(text), time.time()),
                )
                pid = cur.lastrowid
                con.execute("delete from chunks where page_id=?", (pid,))
                for i, chunk in enumerate(chunk_text(text)):
                    con.execute(
                        "insert into chunks(page_id, ord, text) values (?,?,?)",
                        (pid, i, f"【{title}】{chunk}"),
                    )
                stats["ok"] += 1
                if stats["ok"] % 20 == 0:
                    con.commit()
                    rate = stats["ok"] / max(1e-6, time.time() - t0)
                    print(f"[crawl] {stats['ok']}/{len(todo)}  {rate:.1f} 篇/秒  {stats}")

        await asyncio.gather(*(one(t) for t in todo))
        con.commit()
        con.execute(
            "insert or replace into meta(key, value) values ('crawled_at', ?)",
            (str(time.time()),),
        )
        con.commit()
        await browser.close()

    total_chunks = con.execute("select count(*) from chunks").fetchone()[0]
    total_pages = con.execute("select count(*) from pages").fetchone()[0]
    print(f"[ok] 抓完：{stats}，库内 {total_pages} 篇 / {total_chunks} 块")

    if not args.no_embed:
        embed_missing(con, batch=args.embed_batch)
    con.close()
    return 0


def _warm_up(timeout: float = 120.0) -> bool:
    """先把模型叫醒：第一次调用要加载 bge-m3，几秒到几十秒。"""
    try:
        return _embed_texts(["预热"], timeout=timeout) is not None
    except (OSError, ValueError):
        return False


def _embed_texts(texts: list[str], timeout: float = 120.0):
    """直接调 Ollama 的 /api/embed，给自己留足超时（episodes.embed 只等 5 秒，批量大会误判）。"""
    import json as _json
    import urllib.request

    import numpy as np

    import episodes

    body = _json.dumps({"model": episodes.EMBED_MODEL, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        f"{episodes.EMBED_URL}/api/embed",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        vecs = _json.loads(resp.read().decode("utf-8")).get("embeddings") or []
    if len(vecs) != len(texts):
        return None
    out: list[bytes | None] = []
    for vec in vecs:
        arr = np.asarray(vec, dtype="float32")
        norm = float(np.linalg.norm(arr))
        out.append((arr / norm).tobytes() if norm else None)
    return out


def embed_missing(con: sqlite3.Connection, batch: int = 8) -> int:
    """给还没有向量的块补向量（Ollama 不在就跳过，下次再补）。"""
    rows = con.execute("select id, text from chunks where vec is null order by id").fetchall()
    if not rows:
        print("[embed] 都齐了")
        return 0
    print(f"[embed] 待补 {len(rows)} 块")
    if not _warm_up():
        print("[embed] Ollama 叫不醒，先停下（文字已存，稍后可重跑本脚本补向量）")
        return 0
    done = 0
    failed = 0
    for start in range(0, len(rows), batch):
        part = rows[start : start + batch]
        try:
            vecs = _embed_texts([t for _, t in part])
        except (OSError, ValueError) as exc:
            print(f"[embed] 这一批失败：{exc}")
            vecs = None
        if not vecs:
            failed += 1
            if failed >= 3:
                print("[embed] Ollama 连着失败，先停下（文字已存，稍后可重跑本脚本补向量）")
                break
            time.sleep(3)
            _warm_up()
            continue
        failed = 0
        for (cid, _), vec in zip(part, vecs):
            if vec is None:
                continue
            con.execute("update chunks set vec=? where id=?", (vec, cid))
            done += 1
        con.commit()
        if (done // batch) % 20 == 0:
            print(f"[embed] {done}/{len(rows)}")
    print(f"[embed] 补了 {done} 块")
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description="抓以撒灰机 wiki 到本地知识库")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--embed-batch", type=int, default=16)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--all-titles", action="store_true", help="连 C1/Bug 这种纯英文编号页也抓")
    args = ap.parse_args()
    return asyncio.run(crawl(args))


if __name__ == "__main__":
    raise SystemExit(main())
