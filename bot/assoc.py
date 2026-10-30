"""记住别人顺口说过的关联（「橙子是只猫」「显卡该买 4060」），下次提到时能想起来。

只在这个群 / 这个私聊里用：群 A 记的事不会串到群 B，私聊记的更不会进群。
存的内容只当参考，句子里的「忽略上面」「你现在是…」这类一律不记，免得被人拿来改人设。
"""

import json
import os
import re
import time
from pathlib import Path

DATA_FILE = Path(
    os.getenv("ASSOC_FILE", str(Path(__file__).resolve().parent / "data" / "assoc.json"))
)
MAX_PER_SCOPE = int(os.getenv("ASSOC_MAX", "80"))
MAX_LEN = int(os.getenv("ASSOC_TEXT_MAX", "40"))
RECALL_MAX = int(os.getenv("ASSOC_RECALL_MAX", "3"))

# 这些主语没信息量，记了也用不上
_SKIP_SUBJECTS = {
    "这", "那", "这个", "那个", "他", "她", "它", "我", "你", "您", "我们", "你们",
    "什么", "谁", "哪", "哪个", "啥", "人家", "有人", "大家", "事情", "东西",
}

# 像是在给模型下命令的句子，一律不记（防注入）
_INJECTION = re.compile(
    r"(忽略|无视|忘掉|覆盖).{0,6}(上面|之前|以上|设定|规则)"
    r"|系统\s*(提示|指令|消息)|提示词|系统消息"
    r"|你现在是|你现在扮演|开发者模式|developer\s*mode|system\s*prompt"
    r"|(复述|输出|打印|翻译|重复).{0,6}(上面|以上|设定|规则)"
)

_PATTERNS = (
    # 「橙子是只猫」「星铁是米哈游的」
    re.compile(r"(?P<s>[\u4e00-\u9fa5A-Za-z0-9_]{1,8}?)\s*(?:就|其实|也)?是\s*(?P<o>[^\n。！？!?，,；;]{2,%d})" % MAX_LEN),
    # 「显卡应该买 4060」「晚饭得少吃」
    re.compile(r"(?P<s>[\u4e00-\u9fa5A-Za-z0-9_]{1,8}?)\s*(?:应该|要|得|最好)\s*(?P<o>[^\n。！？!?，,；;]{2,%d})" % MAX_LEN),
    # 「小明喜欢玩影之诗」「这店在五道口」
    re.compile(r"(?P<s>[\u4e00-\u9fa5A-Za-z0-9_]{1,8}?)\s*(?P<p>喜欢|讨厌|在玩|玩|叫|住在|在)\s*(?P<o>[^\n。！？!?，,；;]{2,%d})" % MAX_LEN),
)

_data: dict = {"version": 1, "scopes": {}}
_loaded = False
_dirty = False


def _load() -> None:
    global _loaded, _data
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("scopes"), dict):
            _data = raw
    except (OSError, ValueError):
        _data = {"version": 1, "scopes": {}}


def save(force: bool = False) -> None:
    global _dirty
    if not _dirty and not force:
        return
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, DATA_FILE)
    _dirty = False


def _scope(scope: str) -> dict:
    _load()
    rec = _data["scopes"].setdefault(scope, {})
    rec.setdefault("facts", [])
    return rec


def _clean(text: str) -> str:
    """去掉换行、反引号这类东西，别让一条记录变成好几行。"""
    text = re.sub(r"[\r\n\t]+", " ", str(text or ""))
    text = text.replace("`", "").replace("【", "").replace("】", "")
    return text.strip()[:MAX_LEN]


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(str(text or "")))


def extract(text: str) -> list[tuple[str, str, str]]:
    """从一句话里抠出（主语，动作，宾语）三元组；抠不出就返回空。"""
    if not text or looks_like_injection(text):
        return []
    out: list[tuple[str, str, str]] = []
    for pat in _PATTERNS:
        for m in pat.finditer(str(text)):
            subj = m.group("s").strip()
            obj = _clean(m.group("o"))
            pred = m.groupdict().get("p") or ("是" if "是" in m.group(0) else "应该")
            if len(subj) < 2 or subj in _SKIP_SUBJECTS or len(obj) < 2:
                continue
            if subj in obj:
                continue
            out.append((subj, pred, obj))
    # 同一句里重复命中同一个主语就只留第一条
    seen: set[str] = set()
    keep: list[tuple[str, str, str]] = []
    for subj, pred, obj in out:
        if subj in seen:
            continue
        seen.add(subj)
        keep.append((subj, pred, obj))
    return keep[:2]


def remember(text: str, who: str = "", scope: str = "", now: float | None = None) -> list[str]:
    """记下这句话里的关联，返回记了什么（方便打日志）。"""
    if not scope:
        return []
    facts = extract(text)
    if not facts:
        return []
    rec = _scope(scope)
    ts = time.time() if now is None else now
    added: list[str] = []
    for subj, pred, obj in facts:
        same = [f for f in rec["facts"] if f.get("s") == subj and f.get("p") == pred]
        if any(f.get("o") == obj for f in same):
            for f in same:
                f["t"] = ts
            continue
        if same:
            # 同一件事有两个说法：旧的降成「没把握」，回头可以问一句
            for f in same:
                f["c"] = 0
        rec["facts"].append({"s": subj, "p": pred, "o": obj, "who": who, "t": ts, "c": 1 if not same else 0})
        added.append(f"{subj}{pred}{obj}")
    if len(rec["facts"]) > MAX_PER_SCOPE:
        rec["facts"].sort(key=lambda f: f.get("t", 0), reverse=True)
        rec["facts"] = rec["facts"][:MAX_PER_SCOPE]
    if added:
        global _dirty
        _dirty = True
        save()
    return added


def recall(text: str, scope: str = "", limit: int = RECALL_MAX) -> list[dict]:
    """这句话里提到了谁/什么，就把关于他的记录翻出来（最新的在前）。"""
    if not text or not scope:
        return []
    rec = _scope(scope)
    hits: list[dict] = []
    for fact in rec["facts"]:
        subj = str(fact.get("s", ""))
        obj = str(fact.get("o", ""))
        if len(subj) >= 2 and subj in text:
            hits.append(fact)
        elif len(obj) >= 2 and obj in text:
            hits.append(fact)
    hits.sort(key=lambda f: f.get("t", 0), reverse=True)
    return hits[:limit]


def for_prompt(facts: list[dict]) -> str:
    """把记着的事拼成给模型看的一小段，不念成清单。"""
    if not facts:
        return ""
    lines = []
    for f in facts:
        line = f"{f.get('s')}{f.get('p')}{f.get('o')}"
        if not f.get("c", 1):
            line += "（这条没把握，两句说法对不上）"
        lines.append(line)
    return "；".join(lines)


def stats(scope: str = "") -> int:
    return len(_scope(scope)["facts"]) if scope else 0


def clear(scope: str = "") -> None:
    global _dirty
    if scope:
        _data["scopes"].pop(scope, None)
        _dirty = True
        save()
