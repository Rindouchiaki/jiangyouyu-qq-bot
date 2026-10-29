"""刚推送过的链接要能被认出来，别让解析插件再抓一遍。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

import push_marks  # noqa: E402


def test_mark_and_hit():
    push_marks.clear()
    assert push_marks.mark_text("【崩坏星穹铁道】更新了新动态！\n传送门：https://www.bilibili.com/opus/1262294423083941894") == 1
    assert push_marks.contains_recent("这个 https://www.bilibili.com/opus/1262294423083941894 看看")
    assert not push_marks.contains_recent("看看 https://www.bilibili.com/video/BV1GJ411x7h7")


def test_mark_many_urls():
    push_marks.clear()
    text = "看 https://b23.tv/abc 和 https://www.bilibili.com/video/BV1xx，谢谢"
    assert push_marks.mark_text(text) == 2
    assert push_marks.contains_recent("https://b23.tv/abc")


def test_no_url():
    push_marks.clear()
    assert push_marks.mark_text("在吗") == 0
    assert not push_marks.contains_recent("在吗")


def test_expire():
    push_marks.clear()
    now = 1000.0
    push_marks.mark_text("https://www.bilibili.com/opus/1", now=now)
    assert push_marks.contains_recent("https://www.bilibili.com/opus/1", now=now + 10)
    assert not push_marks.contains_recent(
        "https://www.bilibili.com/opus/1", now=now + push_marks.TTL_SECONDS + 1
    )


def test_clear():
    push_marks.mark_text("https://www.bilibili.com/opus/2")
    push_marks.clear()
    assert push_marks.size() == 0
    assert not push_marks.contains_recent("https://www.bilibili.com/opus/2")
