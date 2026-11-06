"""以撒 wiki 知识库的离线测试（不联网、不启 NoneBot、不连 Ollama）。

临时库 + 假向量：验召回顺序、格式、Ollama 不可用时的关键词兜底。
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

TMP = Path(tempfile.mkdtemp(prefix="isaac-test-"))
DB = TMP / "isaac_wiki.db"
os.environ["ISAAC_WIKI_DB"] = str(DB)

import numpy as np  # noqa: E402

import episodes  # noqa: E402
import isaac_wiki  # noqa: E402


def _vec(*values) -> bytes:
    arr = np.asarray(values, dtype="float32")
    norm = np.linalg.norm(arr)
    if norm:
        arr = arr / norm
    return arr.tobytes()


def build_db() -> None:
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE pages (id INTEGER PRIMARY KEY, title TEXT UNIQUE, url TEXT, chars INTEGER, fetched_at REAL);
        CREATE TABLE chunks (id INTEGER PRIMARY KEY, page_id INTEGER, ord INTEGER, text TEXT, vec BLOB);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    pages = [
        (1, "蓝蜡烛", "https://isaac.huijiwiki.com/wiki/蓝蜡烛", 120),
        (2, "红蜡烛", "https://isaac.huijiwiki.com/wiki/红蜡烛", 120),
        (3, "以撒的结合", "https://isaac.huijiwiki.com/wiki/以撒的结合", 200),
    ]
    con.executemany("insert into pages(id,title,url,chars,fetched_at) values (?,?,?,?,0)", pages)
    chunks = [
        (1, 1, 0, "【蓝蜡烛】主动道具，使用时召唤一尊蓝火，碰到会掉魂心。", _vec(1, 0, 0)),
        (2, 2, 0, "【红蜡烛】主动道具，使用时召唤一尊红火，可以用来烧敌人。", _vec(0, 1, 0)),
        (3, 3, 0, "【以撒的结合】是一个随机生成地图的射击 RPG，主角叫以撒。", _vec(0, 0, 1)),
    ]
    con.executemany("insert into chunks(id,page_id,ord,text,vec) values (?,?,?,?,?)", chunks)
    con.execute("insert into meta(key,value) values ('crawled_at', ?)", ("0",))
    con.commit()
    con.close()


def main() -> None:
    build_db()
    assert isaac_wiki.ready()
    info = isaac_wiki.stats()
    assert info["pages"] == 3 and info["chunks"] == 3 and info["embedded"] == 3, info

    # 假向量：问蓝蜡烛就给第一维；问不相干的给一个都打不中的方向
    def fake_embed(texts):
        out = []
        for text in texts:
            if "蓝" in text:
                out.append([1.0, 0.0, 0.0])
            elif "红" in text:
                out.append([0.0, 1.0, 0.0])
            else:
                # 跟哪条都不像的方向，专门用来验「不硬凑」
                out.append([-1.0, -1.0, -1.0])
        return out

    episodes.embed = fake_embed
    hits = isaac_wiki.recall("蓝蜡烛有什么用", limit=2)
    assert hits and hits[0]["title"] == "蓝蜡烛", hits
    assert hits[0]["score"] > 0.9, hits[0]
    assert "蓝蜡烛" in hits[0]["url"] or hits[0]["url"].endswith("蓝蜡烛"), hits[0]

    # 不相干的词，分数不够就该空（不硬凑）
    assert isaac_wiki.recall("今天吃什么", limit=2) == []

    # Ollama 不可用：vocabulary 命中走关键词兜底
    episodes.embed = lambda texts: [None for _ in texts]
    fallback = isaac_wiki.recall("红蜡烛", limit=2)
    assert fallback and fallback[0]["title"] == "红蜡烛", fallback
    assert fallback[0]["score"] == 0.0
    assert isaac_wiki.recall("根本没有的东西", limit=2) == []

    # 进提示词：说明只作参考、别编
    note = isaac_wiki.format_note(hits, chars=20)
    assert "只作参考" in note and "蓝蜡烛" in note, note
    assert "…" in note, note  # 超过字数要截

    # 直接回群友：标题 + 原文链接
    reply = isaac_wiki.format_reply(hits)
    assert "【蓝蜡烛】" in reply and "原文：" in reply, reply

    # 空命中不产出
    assert isaac_wiki.format_note([]) == ""
    assert isaac_wiki.format_reply([]) == ""

    # 话题词去掉再查（「以撒的蓝蜡烛」不该让「以撒」词条顶上来）
    assert isaac_wiki.strip_topic("以撒的蓝蜡烛") == "蓝蜡烛"
    assert isaac_wiki.strip_topic("以撒") == "以撒"

    # 道具页第一块的信息框（ID/图鉴/道具池）要切掉，只留正文
    messy = "【C164】道具\n蓝蜡烛\nThe Candle\nID\n164\n道具信息\n图鉴\n蓝蜡烛（The Candle）是一个重生中加入的道具。\n效果\n使用后发射火焰。"
    tidy = isaac_wiki._tidy(messy)
    assert tidy.startswith("蓝蜡烛（The Candle）是一个"), tidy
    assert "ID" not in tidy.split("\n")[0], tidy

    # 编号页的显示名：label 用真名 + 编号
    assert isaac_wiki.label({"title": "C164", "display": "蓝蜡烛"}) == "蓝蜡烛（C164）"
    assert isaac_wiki.label({"title": "蓝蜡烛", "display": ""}) == "蓝蜡烛"

    # 聊天里不带「以撒」也认名字：mention 直接按页面名找
    m = isaac_wiki.mention("蓝蜡烛有什么用", 1)
    assert m and m[0]["title"] == "蓝蜡烛", m
    assert isaac_wiki.mention("今天吃什么") == []

    print("test_isaac_wiki: 全部通过")


if __name__ == "__main__":
    main()
