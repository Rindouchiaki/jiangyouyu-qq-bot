"""知识库：她懂的东西（游戏、番、圈子里的事），聊天时当成自己本来就知道的，不用什么都上网查。

- 开发者 /学习 话题 [指引]：她自己列大纲、逐项搜、读网页、整理成知识（指引只是参考）；
- 每周看一眼每个话题有没有新东西（新版本、新卡包），有才针对变了的部分细查；
- 聊天时她自己上网查过的词记下来，常查的在 /知识库 里列出来，开发者一句话收进来（群友没法直接往库里塞）；
- 和记忆共用本机 bge-m3 向量；数据在 data/knowledge.db。设计见 docs/记忆设计.md 第七节。

模型和联网都从外面传进来（setup / search / fetch），不依赖 NoneBot，方便离线测。
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import episodes
import web_search
from persona_rules import (
    EPISODE_MERGE_PROMPT,
    KB_CARD_CHARS,
    KB_CARD_PROMPT,
    KB_CHECK_PROMPT,
    KB_FINGERPRINT_PROMPT,
    KB_OUTLINE_PROMPT,
    looks_like_injection,
    parse_cards,
    parse_check,
    parse_merge,
    parse_outline,
    text_sim,
)

_data_env = os.getenv("PERSONA_DATA_DIR", "").strip()
DATA_FILE = (Path(_data_env) if _data_env else Path(__file__).resolve().parent / "data") / "knowledge.db"
# 聊天时想起来：相关度过线才带，一次最多几条
MIN_SIM = float(os.getenv("KB_MIN_SIM", "0.55"))
MIN_TEXT_SIM = float(os.getenv("KB_MIN_TEXT_SIM", "0.2"))
RECALL_MAX = int(os.getenv("KB_RECALL_MAX", "3"))
# 录一个话题最多查几个子项，每项读几个网页；录入和每周检查每天最多用多少次搜索 / 看网页（不占聊天的联网额度）
OUTLINE_MAX = int(os.getenv("KB_OUTLINE_MAX", "8"))
PAGES_PER_ITEM = int(os.getenv("KB_PAGES_PER_ITEM", "2"))
DAILY_MAX = int(os.getenv("KB_SEARCH_DAILY", "300"))
CHECK_DAYS = float(os.getenv("KB_CHECK_DAYS", "7"))
# 聊天时同一个词查过几次才进待审区
PENDING_MIN = 2
DUP_SIM, NEAR_SIM = 0.93, 0.75

_lock = threading.RLock()
_conn: list[sqlite3.Connection] = []
_busy = asyncio.Lock()
_ask: list = []
# 测试时换成假的
search = web_search.search
fetch = web_search.fetch

_SCHEMA = """
create table if not exists topic (
    name text primary key,
    hint text not null default '',
    created real not null,
    updated real not null default 0,
    checked real not null default 0,
    finger text not null default ''
);
create table if not exists card (
    id integer primary key,
    topic text not null,
    title text not null,
    text text not null,
    url text not null default '',
    t real not null,
    state text not null default 'now',
    vec blob
);
create index if not exists card_topic on card(topic);
create table if not exists query (q text primary key, n integer not null default 0, last real not null default 0);
create table if not exists spend (day text primary key, n integer not null default 0);
"""


def setup(ask) -> None:
    """persona.py 把对话模型交进来（ask(messages, max_tokens, temperature=, stop=)）。"""
    _ask[:] = [ask]


def _db() -> sqlite3.Connection:
    if not _conn:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DATA_FILE), check_same_thread=False)
        conn.executescript(_SCHEMA)
        _conn.append(conn)
    return _conn[0]


def close() -> None:
    with _lock:
        while _conn:
            _conn.pop().close()


def busy() -> bool:
    return _busy.locked()


# ---------------------------------------------------------------- 额度
def spent_today() -> int:
    with _lock:
        row = _db().execute("select n from spend where day = ?", (datetime.now().strftime("%Y-%m-%d"),)).fetchone()
    return int(row[0]) if row else 0


def _spend() -> bool:
    """用掉一次搜索 / 看网页；今天用完了返回假。"""
    day = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        db = _db()
        row = db.execute("select n from spend where day = ?", (day,)).fetchone()
        if row and DAILY_MAX > 0 and row[0] >= DAILY_MAX:
            return False
        db.execute("insert into spend (day, n) values (?, 1) on conflict(day) do update set n = n + 1", (day,))
        db.commit()
    return True


# ---------------------------------------------------------------- 话题和条目
def topics() -> list[dict]:
    with _lock:
        rows = _db().execute(
            "select t.name, t.hint, t.updated, t.checked, t.finger, count(c.id) from topic t "
            "left join card c on c.topic = t.name and c.state = 'now' group by t.name order by t.updated desc"
        ).fetchall()
    return [dict(zip(("name", "hint", "updated", "checked", "finger", "cards"), r)) for r in rows]


def topic(name: str) -> dict | None:
    return next((t for t in topics() if t["name"] == name), None)


def delete(name: str) -> bool:
    with _lock:
        db = _db()
        cur = db.execute("delete from topic where name = ?", (name,))
        db.execute("delete from card where topic = ?", (name,))
        db.commit()
        return cur.rowcount > 0


def _cards(name: str) -> list[dict]:
    with _lock:
        rows = _db().execute("select id, title, text, vec from card where topic = ? and state = 'now'", (name,)).fetchall()
    return [{"id": i, "title": t, "text": x, "vec": episodes._unpack(v)} for i, t, x, v in rows]


def _sim(text: str, vec, card: dict) -> tuple[float, bool]:
    if vec and card.get("vec") and len(vec) == len(card["vec"]):
        return sum(a * b for a, b in zip(vec, card["vec"])), True
    return text_sim(text, f"{card['title']} {card['text']}"), False


async def _keep(name: str, title: str, text: str, url: str, now: float) -> str:
    """一条新知识：和这个话题里像的比，重复就刷新、像的问模型、不像才新记。返回 add / update / dup / skip。"""
    if looks_like_injection(title) or looks_like_injection(text):
        return "skip"
    vec = (await asyncio.to_thread(episodes.embed, [f"{title} {text}"]))[0]
    near = sorted(((*_sim(f"{title} {text}", vec, c), c) for c in _cards(name)), key=lambda x: -x[0])[:3]
    action, idx = "add", -1
    if near and near[0][0] >= (DUP_SIM if near[0][1] else 0.97):
        action, idx = "dup", 0
    else:
        cands = [c for s, v, c in near if s >= (NEAR_SIM if v else 0.45)]
        if cands and _ask:
            listing = "\n".join(f"{i + 1}. {c['title']}：{c['text']}" for i, c in enumerate(cands))
            raw = await _ask[0](
                [{"role": "system", "content": EPISODE_MERGE_PROMPT},
                 {"role": "user", "content": f"旧记忆：\n{listing}\n新记的：{title}：{text}"}],
                12, temperature=0.0,
            )
            action, idx = parse_merge(raw, len(cands))
            near = [(0, False, c) for c in cands]
    with _lock:
        db = _db()
        if action == "dup":
            db.execute("update card set t = ? where id = ?", (now, near[idx][2]["id"]))
        elif action == "update":
            db.execute("update card set title = ?, text = ?, url = ?, t = ?, vec = ? where id = ?",
                       (title, text, url, now, episodes._pack(vec), near[idx][2]["id"]))
        else:
            if action == "past":
                db.execute("update card set state = 'past' where id = ?", (near[idx][2]["id"],))
            db.execute("insert into card (topic, title, text, url, t, vec) values (?, ?, ?, ?, ?, ?)",
                       (name, title, text, url, now, episodes._pack(vec)))
            action = "add"
        db.commit()
    return action


async def _material(query: str) -> tuple[str, str]:
    """搜一个词、读前几个网页，拼成资料（标明不是指令）；返回 (资料, 第一个网址)。"""
    if not _spend():
        return "", ""
    results = await asyncio.to_thread(search, query, "", 5)
    parts, first = [], ""
    for r in results[:PAGES_PER_ITEM]:
        url = str(r.get("url") or "")
        page = ""
        if url and _spend():
            page = await asyncio.to_thread(fetch, url, "", 3000)
        body = page or str(r.get("summary") or r.get("snippet") or "")
        if body:
            first = first or url
            date = r.get("date") or ""
            parts.append(f"【{r.get('title') or url}】{f'（{date}）' if date else ''}\n{body}")
    for r in results[PAGES_PER_ITEM:]:
        snippet = str(r.get("summary") or r.get("snippet") or "")
        if snippet:
            parts.append(f"【{r.get('title') or ''}】{snippet}")
    return "\n\n".join(parts)[:7000], first


async def learn(name: str, hint: str = "", focus: list[str] | None = None, now: float | None = None) -> dict:
    """录一个话题（focus 给了就只查这几项）：列大纲 → 逐项搜、读 → 整理成知识、和旧的合并 → 写版本状态。"""
    if not _ask:
        return {"error": "模型没接上"}
    now = time.time() if now is None else now
    async with _busy:
        with _lock:
            db = _db()
            db.execute("insert into topic (name, hint, created) values (?, ?, ?) "
                       "on conflict(name) do update set hint = case when ? != '' then ? else hint end",
                       (name, hint, now, hint, hint))
            db.commit()
        known = [c["title"] for c in _cards(name)][:40]
        if focus:
            outline = [(f, f"{name} {f}") for f in focus][:OUTLINE_MAX]
        else:
            raw = await _ask[0](
                [{"role": "system", "content": KB_OUTLINE_PROMPT.format(n=OUTLINE_MAX)},
                 {"role": "user", "content": f"话题：{name}\n指引：{hint or '无'}\n已经懂的：{'、'.join(known) or '无'}"}],
                400, temperature=0.3, stop=None,
            )
            outline = parse_outline(raw, OUTLINE_MAX)
        done = {"items": [s for s, _ in outline], "add": 0, "update": 0, "dup": 0, "skip": 0, "short": False}
        for sub, query in outline:
            material, url = await _material(query)
            if not material:
                done["short"] = done["short"] or spent_today() >= DAILY_MAX > 0
                continue
            raw = await _ask[0](
                [{"role": "system", "content": KB_CARD_PROMPT.format(topic=name, sub=sub)},
                 {"role": "user", "content": material}],
                700, temperature=0.2, stop=None,
            )
            for title, text in parse_cards(raw):
                done[await _keep(name, title, text, url, now)] += 1
        cards = _cards(name)
        finger = ""
        if cards:
            raw = await _ask[0](
                [{"role": "system", "content": KB_FINGERPRINT_PROMPT},
                 {"role": "user", "content": "\n".join(f"{c['title']}：{c['text']}" for c in cards[:60])}],
                80, temperature=0.0,
            )
            finger = " ".join((raw or "").split())[:80]
        with _lock:
            db = _db()
            db.execute("update topic set updated = ?, checked = ?, finger = case when ? != '' then ? else finger end "
                       "where name = ?", (now, now, finger, finger, name))
            db.commit()
        done["cards"] = len(cards)
        return done


async def check(name: str, now: float | None = None) -> dict:
    """每周看一眼：搜两下最新消息，和上次的版本状态比；有新东西才对变了的子项细查。"""
    now = time.time() if now is None else now
    rec = topic(name)
    if not rec or not _ask:
        return {"error": "没有这个话题"}
    news = []
    for query in (f"{name} 最新", f"{name} 更新 公告"):
        if not _spend():
            break
        for r in (await asyncio.to_thread(search, query, "", 5))[:5]:
            news.append(f"【{r.get('title') or ''}】（{r.get('date') or '日期不明'}）{r.get('summary') or r.get('snippet') or ''}")
    changed, items = False, []
    if news:
        raw = await _ask[0](
            [{"role": "system", "content": KB_CHECK_PROMPT},
             {"role": "user", "content": f"上次的版本状态：{rec['finger'] or '无'}\n\n最新消息：\n" + "\n".join(news)[:5000]}],
            100, temperature=0.0,
        )
        changed, items = parse_check(raw)
    if changed:
        return {"changed": True, **await learn(name, rec["hint"], items, now)}
    with _lock:
        db = _db()
        db.execute("update topic set checked = ? where name = ?", (now, name))
        db.commit()
    return {"changed": False, "items": []}


def due_checks(now: float | None = None) -> list[str]:
    """该看一眼的话题（上次看超过 CHECK_DAYS 天），最久没看的在前。"""
    now = time.time() if now is None else now
    with _lock:
        rows = _db().execute("select name from topic where checked < ? order by checked", (now - CHECK_DAYS * 86400,))
        return [r[0] for r in rows.fetchall()]


# ---------------------------------------------------------------- 聊天时用
def recall(text: str, limit: int = RECALL_MAX) -> list[dict]:
    """这句话用得上哪些知识（全局，哪个群、私聊都用）。"""
    if not text.strip():
        return []
    with _lock:
        rows = _db().execute("select topic, title, text, vec from card where state = 'now'").fetchall()
    if not rows:
        return []
    cards = [{"topic": tp, "title": t, "text": x, "vec": episodes._unpack(v)} for tp, t, x, v in rows]
    qvec = episodes.embed([text])[0] if any(c["vec"] for c in cards) else None
    picked = []
    for c in cards:
        # 提到话题名本身也算相关（「影之诗最近什么环境」）
        sim, by_vec = _sim(text, qvec, c)
        if c["topic"] in text:
            sim = max(sim, MIN_SIM if by_vec else MIN_TEXT_SIM)
        if sim >= (MIN_SIM if by_vec else MIN_TEXT_SIM):
            picked.append((sim, c))
    picked.sort(key=lambda x: -x[0])
    out = []
    for _, c in picked[:limit]:
        c.pop("vec", None)
        c["text"] = c["text"][:KB_CARD_CHARS]
        out.append(c)
    return out


def note_query(query: str, now: float | None = None) -> None:
    """聊天时她自己上网查了什么：记下来，常查的进待审区。"""
    q = " ".join(str(query or "").split())[:40]
    if len(q) < 2:
        return
    now = time.time() if now is None else now
    with _lock:
        db = _db()
        db.execute("insert into query (q, n, last) values (?, 1, ?) on conflict(q) do update set n = n + 1, last = ?",
                   (q, now, now))
        db.commit()


def waiting(limit: int = 8) -> list[tuple[str, int]]:
    """待审区：聊天时查过不止一次、还没收进库的词。"""
    names = [t["name"] for t in topics()]
    with _lock:
        rows = _db().execute("select q, n from query where n >= ? order by n desc, last desc", (PENDING_MIN,)).fetchall()
    return [(q, n) for q, n in rows if not any(name in q for name in names)][:limit]


def drop_query(q: str) -> None:
    with _lock:
        db = _db()
        db.execute("delete from query where q = ?", (q,))
        db.commit()
