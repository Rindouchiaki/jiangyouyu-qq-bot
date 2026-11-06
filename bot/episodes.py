"""事件记忆：她记得和谁发生过什么（整理过的一句话，不是原话），会淡忘、被想起就记得更牢。

- 类别和在哪里能想起来见 persona_rules.episode_visible（群里的事不出群，私聊的事不进群，插话不点名）；
- 向量用本机 Ollama 的 bge-m3，相似度用 numpy 一次算完（每个范围几千条也只要几毫秒）；Ollama 不在时退回按 2 字片段比；
- 数据在 data/episodes.db（SQLite），不依赖 NoneBot，方便离线测。设计见 docs/记忆设计.md。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from persona_rules import episode_recency, episode_score, episode_visible, text_sim

_data_env = os.getenv("PERSONA_DATA_DIR", "").strip()
DATA_FILE = (Path(_data_env) if _data_env else Path(__file__).resolve().parent / "data") / "episodes.db"
EMBED_URL = os.getenv("EPISODES_EMBED_URL", "http://127.0.0.1:11434").rstrip("/")
EMBED_MODEL = os.getenv("EPISODES_EMBED_MODEL", "bge-m3")
EMBED_ON = os.getenv("EPISODES_EMBED", "1") == "1"
# 相关度过线才想起来：向量余弦 / 没向量时的片段重合度
MIN_SIM = float(os.getenv("EPISODES_MIN_SIM", "0.5"))
MIN_TEXT_SIM = float(os.getenv("EPISODES_MIN_TEXT_SIM", "0.15"))
# 合并：几乎一样就当重复，有点像交给模型判断（片段比不出「三岁」「四岁」的差别，没向量时只认一字不差的重复）
DUP_SIM, NEAR_SIM = 0.93, 0.75
DUP_TEXT_SIM, NEAR_TEXT_SIM = 0.97, 0.45
# 同一条在同一个会话里提过，隔多久才再带；刚记下的还在聊天记录里，先不带
RESURFACE_SEC = float(os.getenv("EPISODES_RESURFACE_HOURS", "6")) * 3600
FRESH_SEC = 2 * 3600
# 同一批消息重想（对方补了话）时，刚带过的照样带、不重复算被想起
RETHINK_SEC = 120
# 每个人 / 每个群最多留多少条，满了删最不重要、最旧的
CAP = int(os.getenv("EPISODES_CAP", "2000"))
# 近因低于这个就标「记不太清」
FUZZY_BELOW = 0.25
# Ollama 连不上时先别再试，免得每条消息都等超时
EMBED_RETRY_SEC = 300

_lock = threading.RLock()
_conn: list[sqlite3.Connection] = []
_embed_down = {"until": 0.0}
_surfaced: dict[tuple[str, int], float] = {}

_SCHEMA = """
create table if not exists mem (
    id integer primary key,
    kind text not null,
    uid text not null default '',
    gid text not null default '',
    src text not null default 'g',
    text text not null,
    imp integer not null default 3,
    mood text not null default '',
    t real not null,
    last real not null default 0,
    hits integer not null default 0,
    state text not null default 'now',
    vec blob,
    who text not null default ''
);
create index if not exists mem_uid on mem(uid);
create index if not exists mem_gid on mem(gid);
"""
_COLS = ("id", "kind", "uid", "gid", "src", "text", "imp", "mood", "t", "last", "hits", "state", "vec", "who")


def _db() -> sqlite3.Connection:
    if not _conn:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DATA_FILE), check_same_thread=False)
        conn.executescript(_SCHEMA)
        # #61 建的库没有 who 列（开发者 /记 的署名），补上
        if "who" not in {r[1] for r in conn.execute("pragma table_info(mem)")}:
            conn.execute("alter table mem add column who text not null default ''")
            conn.commit()
        _conn.append(conn)
    return _conn[0]


def close() -> None:
    with _lock:
        while _conn:
            _conn.pop().close()


def _row(row) -> dict:
    rec = dict(zip(_COLS, row))
    rec["vec"] = _unpack(rec["vec"])
    return rec


def _pack(vec) -> bytes | None:
    return np.asarray(vec, dtype=np.float32).tobytes() if vec is not None and len(vec) else None


def _unpack(blob) -> np.ndarray | None:
    return np.frombuffer(blob, dtype=np.float32) if blob else None


def _norm(vec) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32)
    size = float(np.linalg.norm(v)) or 1.0
    return v / size


_api_kind = {"prefer": os.getenv("EPISODES_EMBED_API", "").strip().lower()}


def _request_embeddings(texts: list[str]) -> list[list[float]] | None:
    """先按 Ollama 的 /api/embed，再按 OpenAI 的 /v1/embeddings（llama.cpp 用后者）。"""
    kinds = ["ollama", "openai"]
    if _api_kind["prefer"] in kinds:
        kinds.remove(_api_kind["prefer"])
        kinds.insert(0, _api_kind["prefer"])
    for kind in kinds:
        if kind == "ollama":
            url, key = f"{EMBED_URL}/api/embed", "embeddings"
        else:
            url, key = f"{EMBED_URL}/v1/embeddings", "data"
        body = json.dumps({"model": EMBED_MODEL, "input": texts}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError):
            continue
        if kind == "ollama":
            vecs = data.get(key) or []
        else:
            vecs = [d.get("embedding") for d in (data.get(key) or [])]
        if len(vecs) == len(texts) and all(vecs):
            _api_kind["prefer"] = kind
            return vecs
    return None


def embed(texts: list[str]) -> list[list[float] | None]:
    """本机 Ollama 算向量（归一化过）；关掉或连不上就全是 None，调用方退回按片段比。"""
    if not texts or not EMBED_ON or time.time() < _embed_down["until"]:
        return [None] * len(texts)
    vecs = _request_embeddings(texts)
    if vecs is None:
        _embed_down["until"] = time.time() + EMBED_RETRY_SEC
        return [None] * len(texts)
    if len(vecs) != len(texts):
        return [None] * len(texts)
    return [_norm(v) if v else None for v in vecs]


def match(query: str, qvec, recs: list[dict], text=lambda r: r.get("text", "")) -> list[tuple[float, bool]]:
    """每条和这句话的 (相似度, 是不是向量算的)：有向量的一次矩阵乘法算完，没向量的按字面片段比。"""
    out: list[tuple[float, bool] | None] = [None] * len(recs)
    if qvec is not None:
        idx = [i for i, r in enumerate(recs) if r.get("vec") is not None and len(r["vec"]) == len(qvec)]
        if idx:
            sims = np.stack([recs[i]["vec"] for i in idx]) @ np.asarray(qvec, dtype=np.float32)
            for i, v in zip(idx, sims.tolist()):
                out[i] = (v, True)
    return [o if o is not None else (text_sim(query, text(r)), False) for o, r in zip(out, recs)]


def _same_scope(kind: str, uid: str, gid: str) -> tuple[str, tuple]:
    """合并时只和同一个范围的比：群里的事比本群，开发者笔记比笔记，别的比同一个人（她自己的日常比她自己的）。"""
    if kind == "group":
        return "kind = 'group' and gid = ?", (gid,)
    if kind == "note":
        return "kind = 'note'", ()
    return "kind not in ('group', 'note') and uid = ?", (uid,)


def similar(text: str, vec, kind: str, uid: str = "", gid: str = "", limit: int = 3) -> list[tuple[float, bool, dict]]:
    """同范围里最像的几条：[(相似度, 是否向量, 记录)]，最像的在前。"""
    where, args = _same_scope(kind, uid, gid)
    with _lock:
        rows = _db().execute(f"select * from mem where {where} and state != 'past'", args).fetchall()
    recs = [_row(r) for r in rows]
    scored = [(*m, rec) for m, rec in zip(match(text, vec, recs), recs)]
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]


def plan(text: str, vec, kind: str, uid: str = "", gid: str = "") -> tuple[str, list[dict]]:
    """新记的这条怎么处理：("dup", [那条]) 只刷新；("ask", 候选) 交给模型判断；("add", []) 直接记。"""
    near = similar(text, vec, kind, uid, gid)
    if not near:
        return "add", []
    best, by_vec, rec = near[0]
    if best >= (DUP_SIM if by_vec else DUP_TEXT_SIM):
        return "dup", [rec]
    cands = [r for s, v, r in near if s >= (NEAR_SIM if v else NEAR_TEXT_SIM)]
    return ("ask", cands) if cands else ("add", [])


def add(kind: str, text: str, uid: str = "", gid: str = "", src: str = "g", imp: int = 3, mood: str = "",
        vec=None, now: float | None = None, who: str = "") -> int:
    now = time.time() if now is None else now
    with _lock:
        db = _db()
        cur = db.execute(
            "insert into mem (kind, uid, gid, src, text, imp, mood, t, vec, who) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, uid, gid, src, text, max(1, min(5, int(imp))), mood, now, _pack(vec), who),
        )
        _prune(kind, uid, gid, now)
        db.commit()
        return int(cur.lastrowid)


def _prune(kind: str, uid: str, gid: str, now: float) -> None:
    where, args = _same_scope(kind, uid, gid)
    rows = [_row(r) for r in _db().execute(f"select * from mem where {where}", args).fetchall()]
    if len(rows) <= CAP:
        return
    rows.sort(key=lambda r: episode_recency(now - r["t"], r["imp"], r["hits"]) * r["imp"])
    drop = [r["id"] for r in rows[: len(rows) - CAP]]
    _db().executemany("delete from mem where id = ?", [(i,) for i in drop])


def refresh(mem_id: int, imp: int | None = None, now: float | None = None) -> None:
    """又听说了一遍：时间刷新，重要度取高的。"""
    now = time.time() if now is None else now
    with _lock:
        db = _db()
        db.execute("update mem set t = ?, imp = max(imp, ?) where id = ?", (now, int(imp or 1), mem_id))
        db.commit()


def replace(mem_id: int, text: str, vec=None, imp: int = 3, mood: str = "", now: float | None = None) -> None:
    """同一件事有了更准的说法：换掉内容，被想起的次数留着。"""
    now = time.time() if now is None else now
    with _lock:
        db = _db()
        db.execute(
            "update mem set text = ?, vec = ?, imp = max(imp, ?), mood = ?, t = ?, state = 'now' where id = ?",
            (text, _pack(vec), int(imp), mood, now, mem_id),
        )
        db.commit()


def set_state(mem_id: int, state: str) -> None:
    with _lock:
        db = _db()
        db.execute("update mem set state = ? where id = ?", (state, mem_id))
        db.commit()


def recall(query: str, uid: str, gid: str = "", chat: str = "", chime: bool = False, upset: bool = False,
           asked: bool = False, limit: int = 2, now: float | None = None) -> list[dict]:
    """这句话勾起了哪些事（最多 limit 条，按分数）。被带出来的算被想起一次，记得更牢。

    chat 是会话 key：同一条在同一个会话里提过，RESURFACE_SEC 内不再带（明着问「记得吗」除外）。
    """
    now = time.time() if now is None else now
    if not query.strip():
        return []
    with _lock:
        rows = _db().execute(
            "select * from mem where (uid = ? and uid != '') or (kind = 'group' and gid = ? and gid != '') "
            "or (kind = 'self' and uid = '') or kind = 'note'",
            (uid, gid),
        ).fetchall()
    recs = [r for r in map(_row, rows) if episode_visible(r, uid, gid, chime, upset, asked) and now - r["t"] >= FRESH_SEC]
    if not recs:
        return []
    qvec = embed([query])[0] if any(r.get("vec") is not None for r in recs) else None
    picked = []
    for rec, (sim, by_vec) in zip(recs, match(query, qvec, recs)):
        # 刚带过（同一批重想）照样带；提过一阵了才不再提
        since = now - _surfaced.get((chat, rec["id"]), 0)
        if not asked and RETHINK_SEC < since < RESURFACE_SEC:
            continue
        if sim < (MIN_SIM if by_vec else MIN_TEXT_SIM):
            continue
        rec["score"] = episode_score(sim, now - rec["t"], rec["imp"], rec["hits"])
        rec["fuzzy"] = episode_recency(now - rec["t"], rec["imp"], rec["hits"]) < FUZZY_BELOW
        picked.append(rec)
    picked.sort(key=lambda r: -r["score"])
    picked = picked[:limit]
    fresh = [r for r in picked if now - _surfaced.get((chat, r["id"]), 0) >= RETHINK_SEC]
    if fresh:
        with _lock:
            db = _db()
            db.executemany("update mem set hits = hits + 1, last = ? where id = ?", [(now, r["id"]) for r in fresh])
            db.commit()
        for r in fresh:
            _surfaced[(chat, r["id"])] = now
    for r in picked:
        r.pop("vec", None)
    return picked


# 待跟进的事、她答应别人的事：他再出现时提一句，隔几天再提，提过两次就算了
DUE_MIN_AGE = 86400
DUE_GAP = 3 * 86400
DUE_TIMES = 2


def due(uid: str, gid: str = "", limit: int = 1, now: float | None = None) -> list[dict]:
    """他来了，有什么没下文的事可以问、答应他的事可以提（不看话题，只看隔了多久）。不在这里记「提过」，发出去了再 mark_due。"""
    now = time.time() if now is None else now
    with _lock:
        rows = [_row(r) for r in _db().execute(
            "select * from mem where uid = ? and state = 'now' and (kind = 'followup' or kind = 'self') "
            "and t <= ? and last <= ?",
            (uid, now - DUE_MIN_AGE, now - DUE_GAP),
        ).fetchall()]
    rows = [r for r in rows if episode_visible(r, uid, gid)]
    rows.sort(key=lambda r: (-r["imp"], r["t"]))
    for r in rows:
        r.pop("vec", None)
        r["due"] = True
    return rows[:limit]


def mark_due(ids: list[int], now: float | None = None) -> None:
    """真提了：记下时间，提够 DUE_TIMES 次就不再提（标 done，事还记得）。"""
    now = time.time() if now is None else now
    if not ids:
        return
    with _lock:
        db = _db()
        db.executemany("update mem set hits = hits + 1, last = ? where id = ?", [(now, i) for i in ids])
        db.executemany("update mem set state = 'done' where id = ? and hits >= ?", [(i, DUE_TIMES) for i in ids])
        db.commit()


def quiet_recent(uid: str, window: float = 3600, now: float | None = None) -> int:
    """「忘了吧」：这个人最近记下的事降权、不再主动提（不真删，他明着问还能想起）。"""
    now = time.time() if now is None else now
    with _lock:
        db = _db()
        cur = db.execute(
            "update mem set state = 'quiet', imp = 1 where uid = ? and kind != 'self' and t >= ?",
            (uid, now - window),
        )
        db.commit()
        return cur.rowcount


def forget_user(uid: str) -> int:
    """/小本本 删除：关于这个人的记忆全删（她答应他的也删）。"""
    with _lock:
        db = _db()
        cur = db.execute("delete from mem where uid = ?", (uid,))
        db.commit()
        return cur.rowcount


def search(keyword: str, uid: str = "", gid: str = "", limit: int = 5) -> list[dict]:
    """/回忆：只搜本会话（群里是本群的事，私聊是关于这个人的）和开发者笔记，按字面找，最新的在前。"""
    kw = keyword.strip()
    if not kw:
        return []
    if gid:
        where, args = "(kind = 'group' and gid = ?) or kind = 'note'", (gid,)
    else:
        where, args = "(uid = ? and uid != '' and kind != 'note') or kind = 'note'", (uid,)
    with _lock:
        rows = _db().execute(f"select * from mem where ({where}) and text like ? order by t desc limit ?",
                             (*args, f"%{kw}%", limit)).fetchall()
    return [{k: v for k, v in _row(r).items() if k != "vec"} for r in rows]


def own(limit: int = 20) -> list[dict]:
    """她自己的（日常、态度、答应别人的）：开发者 /记忆 能看的只有这些，群友的事不给看。"""
    with _lock:
        rows = _db().execute("select * from mem where kind = 'self' order by t desc limit ?", (limit,)).fetchall()
    return [{k: v for k, v in _row(r).items() if k != "vec"} for r in rows]


def backfill(limit: int = 64) -> int:
    """Ollama 不在时记下的没有向量，补上；返回补了几条。"""
    with _lock:
        rows = _db().execute("select id, text from mem where vec is null limit ?", (limit,)).fetchall()
    if not rows:
        return 0
    vecs = embed([t for _, t in rows])
    done = [(_pack(v), i) for (i, _), v in zip(rows, vecs) if v is not None]
    if done:
        with _lock:
            db = _db()
            db.executemany("update mem set vec = ? where id = ?", done)
            db.commit()
    return len(done)


def import_assoc(path: Path) -> int:
    """一次性：旧的关联记忆（assoc.json，按「群号」「私聊QQ」存）搬进来，搬完把文件改名，不再读。

    群里的记成本群的事（带上是谁说的），私聊的记成关于那个人的（只在私聊里想起）；说法打架的按不太重要算。
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    count = 0
    for scope, rec in (raw.get("scopes") or {}).items():
        for f in rec.get("facts") or []:
            fact = f"{f.get('s', '')}{f.get('p', '')}{f.get('o', '')}"
            if len(fact) < 4:
                continue
            imp = 2 if f.get("c", 1) else 1
            t = float(f.get("t") or time.time())
            if scope.startswith("群") and scope[1:].isdigit():
                who = str(f.get("who") or "")
                add("group", (f"{who}说{fact}" if who else fact)[:40], "", scope[1:], "g", imp, now=t)
            elif scope.startswith("私聊") and scope[2:].isdigit():
                add("person", f"他说{fact}"[:40], scope[2:], "", "p", imp, now=t)
            else:
                continue
            count += 1
    path.rename(path.with_name(path.name + ".imported"))
    return count


def _scope_key(rec: dict) -> tuple:
    if rec["kind"] == "group":
        return ("g", rec["gid"])
    if rec["kind"] == "note":
        return ("n",)
    return ("u", rec["uid"])


def merge_dups(since: float, now: float | None = None) -> int:
    """夜里：最近记下的和同范围里的旧记忆几乎一样（向量）就并成一条，留重要的、想起次数加起来。返回并掉几条。"""
    now = time.time() if now is None else now
    with _lock:
        rows = [_row(r) for r in _db().execute("select * from mem where vec is not null and state != 'past'").fetchall()]
    scopes: dict[tuple, list[dict]] = {}
    for r in rows:
        scopes.setdefault(_scope_key(r), []).append(r)
    gone: set[int] = set()
    for recs in scopes.values():
        dim = len(recs[0]["vec"])
        recs = [r for r in recs if len(r["vec"]) == dim]
        fresh = [i for i, r in enumerate(recs) if r["t"] >= since]
        if not fresh:
            continue
        # 最近记的 × 同范围全部，一次算完
        mat = np.stack([r["vec"] for r in recs])
        sims = mat[fresh] @ mat.T
        for row, i in enumerate(fresh):
            new = recs[i]
            if new["id"] in gone:
                continue
            for j in np.flatnonzero(sims[row] >= DUP_SIM).tolist():
                old = recs[j]
                if old["id"] == new["id"] or old["id"] in gone:
                    continue
                keep, drop = (new, old) if new["imp"] >= old["imp"] else (old, new)
                with _lock:
                    db = _db()
                    db.execute("update mem set hits = hits + ?, t = max(t, ?) where id = ?",
                               (drop["hits"], drop["t"], keep["id"]))
                    db.execute("delete from mem where id = ?", (drop["id"],))
                    db.commit()
                gone.add(drop["id"])
                if drop is new:
                    break
    return len(gone)


def changed_people(since: dict[str, float] | None = None) -> list[str]:
    """关于谁的记忆在他上次整理印象之后有变化（新记、刷新、被想起），按最近变化排。since 是 {QQ号: 上次整理时间}。"""
    since = since or {}
    with _lock:
        rows = _db().execute(
            "select uid, max(max(t, last)) from mem where uid != '' and kind in ('person', 'followup', 'grudge', 'self') "
            "group by uid order by 2 desc"
        ).fetchall()
    return [uid for uid, latest in rows if latest > since.get(uid, 0)]


def about(uid: str, private: bool, limit: int = 15, now: float | None = None) -> list[str]:
    """整理印象用：关于这个人的事（不含记仇和「忘了吧」的），private 为假时只要群里听来的；按记得多牢排。"""
    now = time.time() if now is None else now
    with _lock:
        rows = [_row(r) for r in _db().execute(
            "select * from mem where uid = ? and kind in ('person', 'followup') and state in ('now', 'done')", (uid,)
        ).fetchall()]
    rows = [r for r in rows if private or r["src"] != "p"]
    rows.sort(key=lambda r: -episode_recency(now - r["t"], r["imp"], r["hits"]) * r["imp"])
    return [r["text"] for r in rows[:limit]]


def grudge_owners() -> list[str]:
    with _lock:
        return [r[0] for r in _db().execute("select distinct uid from mem where kind = 'grudge' and state = 'now'")]


def soften_grudges(uid: str, now: float | None = None) -> None:
    """不讨厌他了：记仇一晚淡一点，淡到底又过了 30 天就不再翻。"""
    now = time.time() if now is None else now
    with _lock:
        db = _db()
        db.execute("update mem set imp = max(1, imp - 1) where uid = ? and kind = 'grudge'", (uid,))
        db.execute("update mem set state = 'quiet' where uid = ? and kind = 'grudge' and imp = 1 and t < ?",
                   (uid, now - 30 * 86400))
        db.commit()


def stats() -> dict:
    """按类别数条数，只给数字。"""
    with _lock:
        rows = _db().execute("select kind, count(*) from mem group by kind").fetchall()
    return {k: n for k, n in rows}
