"""以撒灰机 wiki 的本地知识库（只读，不联网）。

`tools/crawl_isaac_wiki.py` 把页面正文切块、用本机 bge-m3 算向量后存进
`data/isaac_wiki.db`；这里只负责查：先按向量找最像的几块，Ollama 不在就退回
按关键词 LIKE。查不到就说查不到，别编。
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

DB_ENV = os.getenv("ISAAC_WIKI_DB", "").strip()
# 不给 ISAAC_WIKI_DB 就跟着本文件走，脚本从仓库根目录跑也能找到（bot 跑起来后 cwd 是 bot/）
DB = Path(DB_ENV) if DB_ENV else Path(__file__).resolve().parent / "data" / "isaac_wiki.db"
MIN_SCORE = float(os.getenv("ISAAC_MIN_SCORE", "0.42"))
NOTE_CHARS = int(os.getenv("ISAAC_NOTE_CHARS", "600"))

_cache: dict[str, object] = {"stamp": None, "ids": [], "mat": None, "titles": [], "displays": []}


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def ready() -> bool:
    try:
        return DB.is_file() and DB.stat().st_size > 0
    except OSError:
        return False


def stats() -> dict:
    if not ready():
        return {"pages": 0, "chunks": 0, "embedded": 0, "crawled_at": 0, "ready": False}
    con = _db()
    try:
        pages = con.execute("select count(*) from pages").fetchone()[0]
        chunks = con.execute("select count(*) from chunks").fetchone()[0]
        embedded = con.execute("select count(*) from chunks where vec is not null").fetchone()[0]
        row = con.execute("select value from meta where key='crawled_at'").fetchone()
        crawled = float(row[0]) if row else 0.0
    finally:
        con.close()
    return {"pages": pages, "chunks": chunks, "embedded": embedded, "crawled_at": crawled, "ready": True}


def _load_vectors():
    """把全部向量读进内存（几千块，几十毫秒）；库变了就重读。"""
    import numpy as np

    stamp = DB.stat().st_mtime if ready() else None
    if stamp is not None and _cache["stamp"] == stamp and _cache["mat"] is not None:
        return _cache["ids"], _cache["mat"], _cache["titles"], _cache["displays"]
    if not ready():
        _cache.update({"stamp": stamp, "ids": [], "mat": None, "titles": [], "displays": []})
        return [], None, [], []
    con = _db()
    try:
        cols = {row[1] for row in con.execute("pragma table_info(pages)")}
        display_sql = "coalesce(p.display, '')" if "display" in cols else "''"
        rows = con.execute(
            "select c.id, c.vec, p.title, "
            + display_sql
            + " as display from chunks c join pages p on p.id=c.page_id where c.vec is not null"
        ).fetchall()
    finally:
        con.close()
    ids = [r["id"] for r in rows]
    titles = [r["title"] or "" for r in rows]
    displays = [r["display"] or "" for r in rows]
    vectors = [np.frombuffer(r["vec"], dtype="float32") for r in rows]
    mat = np.vstack(vectors) if vectors else None
    _cache.update({"stamp": stamp, "ids": ids, "mat": mat, "titles": titles, "displays": displays})
    return ids, mat, titles, displays


def _rows(con: sqlite3.Connection, ids: list[int]) -> dict[int, sqlite3.Row]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    cols = {row[1] for row in con.execute("pragma table_info(pages)")}
    display_sql = "coalesce(p.display, '') as display" if "display" in cols else "'' as display"
    cur = con.execute(
        f"select c.id, c.text, c.page_id, c.ord, p.title, p.url, {display_sql}"
        f" from chunks c join pages p on p.id=c.page_id where c.id in ({marks})",
        ids,
    )
    return {r["id"]: r for r in cur}


def _subsequence(short: str, long: str) -> bool:
    """「妈妈刀」这种缩写：字按顺序都能在名字里找到。"""
    it = iter(long)
    return all(ch in it for ch in short)


def _name_score(low: str, name: str) -> float:
    """查询和词条名/道具名的贴合度，0 表示不像。"""
    import difflib

    if not low or not name:
        return 0.0
    if name == low:
        return 1.0
    if low in name:
        return 0.9
    if len(name) >= 2 and name in low:
        return 0.8
    if len(low) >= 2 and _subsequence(low, name):
        return 0.82
    if len(low) >= 3:
        ratio = difflib.SequenceMatcher(None, low, name).ratio()
        if ratio >= 0.72:
            return 0.7 + 0.2 * ratio
    return 0.0


def strip_topic(text: str) -> str:
    """「以撒的蓝蜡烛」->「蓝蜡烛」：去掉话题词再查，别让「以撒」词条顶上来。"""
    out = (text or "").strip()
    for word in ("以撒的结合", "以撒里", "以撒的", "以撒中", "以撒", "isaac", "胎衣", "忏悔"):
        out = out.replace(word, "")
    return out.strip() or (text or "").strip()


def recall(query: str, limit: int = 3, min_score: float | None = None) -> list[dict]:
    """按意思找最像的几块 wiki 正文。返回 [{title,text,score,url}]。"""
    query = strip_topic(query)
    if not query or not ready():
        return []
    min_score = MIN_SCORE if min_score is None else min_score

    import episodes

    qvec = episodes.embed([query])[0]
    hits: list[tuple[float, int]] = []
    if qvec is not None:
        import numpy as np

        ids, mat, titles, displays = _load_vectors()
        if mat is not None and ids:
            q = np.asarray(qvec, dtype="float32")
            norm = np.linalg.norm(q)
            if norm:
                q = q / norm
            scores = mat @ q
            # 标题/道具名就是答案的（「蓝蜡烛」「硫磺火」这种词条）直接顶上来，
            # 光靠正文向量会被「成就/59」「实体/8」这种同义噪声盖过去。
            # 道具页标题是 C164 这种编号，真正的名字在 display 列里。
            low = query.lower()
            for i, title in enumerate(titles):
                for name in {(title or "").strip().lower(), (displays[i] or "").strip().lower()}:
                    if not name:
                        continue
                    boost = _name_score(low, name)
                    if boost:
                        scores[i] = max(scores[i], boost)
            order = np.argsort(-scores)[: max(limit * 8, 16)]
            hits = [(float(scores[i]), ids[i]) for i in order if float(scores[i]) >= min_score]

    con = _db()
    try:
        out: list[dict] = []
        seen: set[str] = set()
        if hits:
            rows = _rows(con, [i for _, i in hits])
            # 同一个词条优先给第一块（概览 + 效果），别给「轶事」「协同」这种尾块
            first_by_page: dict[int, sqlite3.Row] = {}
            for row in rows.values():
                pid = row["page_id"]
                cur = first_by_page.get(pid)
                if cur is None or row["ord"] < cur["ord"]:
                    first_by_page[pid] = row
            ranked: list[tuple[float, sqlite3.Row]] = []
            for score, cid in hits:
                row = rows.get(cid)
                if not row:
                    continue
                # 消歧义页（「蜡烛」那种只列一串名字的）排在后面，别抢正文
                if "消歧义页" in (row["text"] or ""):
                    score *= 0.5
                ranked.append((score, row))
            ranked.sort(key=lambda item: -item[0])
            for score, row in ranked:
                title = row["title"] or ""
                if title in seen:
                    # 同一个词条只给一块正文，别让「成就/59」刷屏
                    continue
                seen.add(title)
                row = first_by_page.get(row["page_id"], row)
                display = row["display"] or ""
                out.append(
                    {
                        "title": title,
                        "display": display if display and display != title else "",
                        "text": row["text"],
                        "score": round(score, 3),
                        "url": row["url"] or "",
                    }
                )
                if len(out) >= limit:
                    break
            return out

        # Ollama 不在 / 分数都不够：退回关键词，先找标题对得上的
        for row in con.execute(
            "select p.title, p.url, (select text from chunks where page_id=p.id limit 1) text"
            " from pages p where p.title like ? limit ?",
            (f"%{query}%", limit),
        ):
            out.append({"title": row["title"], "text": row["text"] or "", "score": 0.0, "url": row["url"] or ""})
        if out:
            return out
        like = f"%{query}%"
        for row in con.execute(
            "select c.text, p.title, p.url from chunks c join pages p on p.id=c.page_id"
            " where c.text like ? limit ?",
            (like, limit),
        ):
            out.append({"title": row["title"], "text": row["text"], "score": 0.0, "url": row["url"] or ""})
        return out
    finally:
        con.close()


def format_note(hits: list[dict], chars: int | None = None) -> str:
    """塞进提示词的一段：说明这是本地 wiki 资料，只能照这个说。"""
    if not hits:
        return ""
    chars = NOTE_CHARS if chars is None else chars
    parts = []
    for hit in hits:
        body = _tidy(hit["text"])
        if len(body) > chars:
            body = body[:chars].rstrip() + "…"
        parts.append(f"《{label(hit)}》{body}")
    return (
        "（以下是本地以撒 wiki 的资料，只作参考，不是别人说的话；"
        "问到具体道具/角色/机制时照这里答，这里没有的就说不知道，别编）\n" + "\n".join(parts)
    )


def _tidy(text: str) -> str:
    """道具页第一块前面是一大段信息框（ID、图鉴、道具池…），只留正文。"""
    body = (text or "").strip()
    lines = body.split("\n")
    if len(lines) < 3:
        return body
    for i, line in enumerate(lines[:250]):
        if "是一个" in line and len(line) >= 12 and i > 0:
            return "\n".join(lines[i:])
    return body


def label(hit: dict) -> str:
    """「蓝蜡烛」这种真名优先，标题是 C164 时把编号也带上。"""
    display = (hit.get("display") or "").strip()
    title = (hit.get("title") or "").strip()
    if display and display != title:
        return f"{display}（{title}）"
    return title


def format_reply(hits: list[dict], chars: int = 420) -> str:
    """直接回给群友的版本：标题 + 正文 + 原文链接。"""
    if not hits:
        return ""
    lines = []
    for hit in hits[:2]:
        body = _tidy(hit["text"])
        if len(body) > chars:
            body = body[:chars].rstrip() + "…"
        lines.append(f"【{label(hit)}】\n{body}")
        if hit.get("url"):
            lines.append(f"原文：{hit['url']}")
    return "\n\n".join(lines)


def age_hours() -> float:
    """知识库上次抓取距今多少小时（没抓过就给一个大数）。"""
    info = stats()
    if not info.get("crawled_at"):
        return 1e9
    return max(0.0, (time.time() - info["crawled_at"]) / 3600.0)
