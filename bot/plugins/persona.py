"""人设回复插件：把群聊消息交给 LLM，再压成一条像人的短回复。

触发规则：
- 被 @、或被叫外号（NICKNAMES）→ 必回，并记住"这段对话在聊"
- 正聊着的时候（被叫过一次、还没超时）→ 不带关键词也接着回
- 都没命中 → 以 REPLY_CHIME_PROB 概率自己插话，且要先过氛围判断
- 出现收尾词（睡了/拜拜/先这样…）或超时 → 认为这段聊完，停止接续

上下文：每个会话保留 HISTORY_SIZE 条，落盘到 data/history.json，重启后能接着聊。
回复硬性 ≤ REPLY_MAX_CHARS 字，去掉 emoji / 括号动作 / AI 字样。

小本本（bonds.py）：每个群友按 QQ 号一份好感度、熟悉度和简短日记，群聊私聊共用；
态度跟着档位变（persona_rules.attitude），日记隔一阵让模型从最近聊天里摘一两条。
看到喜欢的表情会收进自己的表情库（sticker_lib.save_sticker），以后配图会用。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import nonebot  # noqa: F401
from bot_guard import is_our_bot
from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.log import logger
from nonebot.params import CommandArg

import bonds
import memory
import sticker_lib
import vision
from persona_rules import (
    AFF_PESTER,
    ATTITUDE_REPLY_FACTOR,
    DERE_CHANCE,
    DEFAULT_GAME_PREFIXES,
    DIARY_GROUP_PROMPT,
    DIARY_USER_PROMPT,
    affinity_delta,
    attitude,
    compose_messages,
    follow_decision,
    humanize,
    is_conversation_ending,
    is_offensive,
    is_game_command,
    is_question,
    judge_annoyance,
    judge_atmosphere,
    judge_mood,
    looks_addressed,
    looks_self_disclosure,
    name_call_prob,
    parse_group_diary,
    parse_notes,
    pick_flavor,
    quota_allows,
    safe_name,
    sticker_category,
    sticker_scene,
    visible_notes,
    wants_help,
    wants_sticker,
)

BOT_UIN = os.getenv("BOT_UIN", "").strip()
DEV_UIN = os.getenv("DEV_UIN", "").strip()
DEV_NAME = os.getenv("DEV_NAME", "酱酱鱼").strip()
NICKNAMES = tuple(
    n.strip() for n in os.getenv("NICKNAMES", "酱油鱼,大肥鱼,鲸鱼娘").split(",") if n.strip()
)
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "").strip()
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
MOCK = os.getenv("LLM_MOCK", "0") == "1"

MAX_CHARS = int(os.getenv("REPLY_MAX_CHARS", "20"))
# 正经求助（查/看/找/翻译）放宽到一两句话，不然「帮我看看这个」只能挤出十几个字
MAX_CHARS_HELP = int(os.getenv("REPLY_MAX_CHARS_HELP", "80"))
# 直接问事（啥/怎么/能不能/问号）放宽一点，不然「还有啥游戏能绑定uid」答不完整
MAX_CHARS_QUESTION = int(os.getenv("REPLY_MAX_CHARS_QUESTION", "40"))
HELP_MAX_TOKENS = int(os.getenv("REPLY_HELP_MAX_TOKENS", "160"))
HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "24"))
COOLDOWN_SEC = float(os.getenv("REPLY_COOLDOWN", "8"))
FOLLOW_COOLDOWN_SEC = float(os.getenv("REPLY_GROUP_COOLDOWN", "10"))
CHIME_PROB = float(os.getenv("REPLY_CHIME_PROB", "0.02"))
CHIME_COOLDOWN_SEC = float(os.getenv("REPLY_CHIME_COOLDOWN", "2700"))
CHIME_HISTORY_BUDGET = int(os.getenv("CHIME_HISTORY_BUDGET", "260"))
# 私聊内容同时记进白守日记，慢慢养出固定人格
PRIVATE_MIRROR = os.getenv("PRIVATE_MIRROR", "1").strip() not in ("0", "false", "False")
# 群聊里「真的接上了」的对话也记（被叫/接续，不含随机插话），带群号和发言人
GROUP_MIRROR = os.getenv("GROUP_MIRROR", "1").strip() not in ("0", "false", "False")
GLOBAL_PER_MIN = int(os.getenv("REPLY_PER_MIN", "4"))
# 没被 @ 时（接话、冒泡、只发表情）：每个群每小时最多几条，同群两条之间至少隔几秒，不像住在群里。
# 被 @ 不受这两条限制，有人找她就回
GROUP_PER_HOUR = int(os.getenv("REPLY_GROUP_PER_HOUR", "6"))
CASUAL_GAP = float(os.getenv("REPLY_CASUAL_GAP", "180"))
# 被 @ 时的冷却（秒），只防同一秒被连 @ 刷屏
AT_COOLDOWN = float(os.getenv("REPLY_AT_COOLDOWN", "3"))

ENGAGE_TTL = float(os.getenv("ENGAGE_TTL", "120"))
ENGAGE_FOLLOW_WINDOW = float(os.getenv("ENGAGE_FOLLOW_WINDOW", "45"))
ENGAGE_MAX_TURNS = int(os.getenv("ENGAGE_MAX_TURNS", "2"))
STICKER_COOLDOWN = float(os.getenv("STICKER_COOLDOWN", "3"))
AT_USER = os.getenv("REPLY_AT_USER", "1") == "1"
# 早柚核心的指令前缀，默认值见 persona_rules.DEFAULT_GAME_PREFIXES
GAME_CMD_PREFIXES = tuple(
    p.strip() for p in os.getenv("GAME_CMD_PREFIXES", ",".join(DEFAULT_GAME_PREFIXES)).split(",") if p.strip()
)
PROB_CALLED = float(os.getenv("REPLY_PROB_CALLED", "0.5"))
PROB_FOLLOW = float(os.getenv("REPLY_PROB_FOLLOW", "0.08"))
STICKER_AUTO_PROB = float(os.getenv("STICKER_AUTO_PROB", "0.08"))
STICKER_AUTO_COOLDOWN = float(os.getenv("STICKER_AUTO_COOLDOWN", "600"))
PESTER_WINDOW = float(os.getenv("PESTER_WINDOW", "45"))
PESTER_COUNT = int(os.getenv("PESTER_COUNT", "5"))
SNUB_SECONDS = float(os.getenv("SNUB_SECONDS", "100"))
# 小本本：每人每聊几轮、每群每多少条消息让模型摘一次日记（0 = 关）
DIARY_USER_EVERY = int(os.getenv("DIARY_USER_EVERY", "8"))
DIARY_GROUP_EVERY = int(os.getenv("DIARY_GROUP_EVERY", "60"))
DIARY_GROUP_GAP = float(os.getenv("DIARY_GROUP_GAP", "1800"))
# 看到库里没有的表情时收藏的概率；配图时先从自己收藏的里挑的概率
STICKER_SAVE_PROB = float(os.getenv("STICKER_SAVE_PROB", "0.2"))
STICKER_SAVED_PREFER = float(os.getenv("STICKER_SAVED_PREFER", "0.3"))
# 群里要回话、而且这句话有明显场景（有人抽卡歪了、卧槽、无语…）时，只甩一张对得上的表情不说话的概率；
# 被 @ 和正经求助除外，同一个群至少隔 STICKER_ONLY_COOLDOWN 秒
STICKER_ONLY_PROB = float(os.getenv("STICKER_ONLY_PROB", "0.5"))
STICKER_ONLY_COOLDOWN = float(os.getenv("STICKER_ONLY_COOLDOWN", "900"))
# 没有明显场景时，偶尔随手甩一张无厘头表情的概率（同样受上面的间隔限制）
STICKER_RANDOM_PROB = float(os.getenv("STICKER_RANDOM_PROB", "0.05"))

_data_env = os.getenv("PERSONA_DATA_DIR", "").strip()
_DATA_DIR = Path(_data_env) if _data_env else Path(__file__).resolve().parent.parent / "data"
HISTORY_FILE = _DATA_DIR / "history.json"
MODE_FILE = _DATA_DIR / "reply_modes.json"

# 回复频率档位：/模式 切换；群聊与私聊各自独立保存，互不影响
MODES = {
    "省话": {"called": PROB_CALLED, "follow": PROB_FOLLOW, "cd": FOLLOW_COOLDOWN_SEC, "chime": CHIME_PROB},
    "话痨": {"called": 1.0, "follow": 1.0, "cd": 3.0, "chime": min(1.0, CHIME_PROB * 2)},
    # 静音 = 完全不主动说话（不接续、不插话、不主动配图），只剩命令能叫动它
    "静音": {"called": 0.0, "follow": 0.0, "cd": 10.0, "chime": 0.0},
    # 私聊默认档：每句都回，冷却很短
    "必回": {"called": 1.0, "follow": 0.6, "cd": float(os.getenv("PRIVATE_COOLDOWN", "2")), "chime": 0.0},
    # 抽卡模式：很低的被叫概率，接续为 0；真被触发时发固定长文，不调模型
    "米游抽卡": {
        "called": float(os.getenv("REPLY_PROB_GACHA", "0.018")),
        "follow": 0.0,
        "cd": float(os.getenv("GACHA_CD", "60")),
        "chime": CHIME_PROB,
    },
}
_DEFAULT_MODE = {"group": "省话", "private": "必回"}
_mode_state = dict(_DEFAULT_MODE)
# 按群覆盖：group_<群号> -> 模式名；没单独设过的群用 _mode_state['group']
_group_modes: dict[str, str] = {}
# 按群覆盖插话概率：group_<群号> -> 0~1；没设过就用当前档位的 chime
_chime_override: dict[str, float] = {}


def _chat_kind(event) -> str:
    return "group" if getattr(event, "message_type", "") == "group" else "private"


def _mode_name(kind: str, key: str | None = None) -> str:
    # 群里可以单独设置，没设过的群继承全局默认
    if kind == "group" and key and key in _group_modes:
        name = _group_modes[key]
        if name in MODES:
            return name
    name = _mode_state.get(kind) or _DEFAULT_MODE[kind]
    return name if name in MODES else _DEFAULT_MODE[kind]


def _mode_cfg(kind: str, key: str | None = None) -> dict:
    return MODES[_mode_name(kind, key)]


def _mode_desc(cfg: dict) -> str:
    """把档位参数说清楚：被叫/接续是点名后的概率，插话是没人叫时的概率（静音档为 0）。"""
    return (
        f"被叫 {cfg['called']:.0%} / 接续 {cfg['follow']:.0%} / "
        f"插话 {float(cfg.get('chime', 0)):.0%} / 冷却 {cfg['cd']:.0f}s"
    )


def _chime_prob(key: str, cfg: dict) -> float:
    """当前群实际用的插话概率：群单独设过就用群的，否则跟随档位。"""
    if key in _chime_override:
        return _chime_override[key]
    return float(cfg.get("chime", CHIME_PROB))

# 「二次元圣经」定型文（抽卡版），随机抽一篇。
# 想换文案：GACHA_TEXT_FILE 指向一个 .txt 文件或一个装多份 .txt 的目录。
GACHA_TEXTS = [
    "你这一辈子就是被抽卡害了，没法跟正经人处事。跟朋友吃饭的时候，脑子里算的是这个池子还有几天保底；"
    "地铁上刷到新角色，手比脑子快，支付密码都背熟了。\n"
    "拆开钱包只剩两张月卡，你安慰自己说这是长期投资。抽到金光是命，歪了是税，没出就是缘分未到。\n"
    "别人谈恋爱你在垫池子，别人睡觉你在等维护，别人上班你在算期望。\n"
    "你说你不是赌，你只是相信下一次——下一次一定出。",

    "你以为你在抽卡，其实是卡在抽你。\n"
    "每天上线第一件事是看池子剩几天，第二件事是算这个月还剩多少钱，第三件事是把剩下的钱也充进去。\n"
    "保底向你保证的不是公平，是「再抽一点点」。你信了，因为你每次都信。\n"
    "歪了你说下一个更好，出了你说早该如此。横竖都是赢，只有钱包在输。",

    "有人问抽卡最爽的是哪一刻，你说出金那一下。\n"
    "不是的。最爽的是按下十连之前那三秒——什么都还没发生，一切都有可能。\n"
    "所以你不是在买角色，你是在买那三秒。\n"
    "三秒钟六块钱，其实比电影便宜。这么一算，你又点了一次十连。",

    "月卡党的一天：早上签到，中午领树脂，晚上算距离保底还差多少。\n"
    "别人问你在肝什么，你说在攒。攒什么？攒那份「说不定下个十连就出了」的底气。\n"
    "你的原石从没过万，你的期待也从没归零。\n"
    "这大概就是最省钱的活法——穷，但永远有盼头。",

    "抽卡玄学大全：凌晨三点抽、洗手抽、单抽垫三发再十连、听完角色PV再抽。\n"
    "你全试过，全都没用，但你还在试。\n"
    "因为你心里清楚，概率是冷的，人是热的。你需要一个仪式，好让那次没出看起来像命运，而不是自己手欠。",

    "理智消费的第一步：认识沉没成本。\n"
    "你已经抽了七十发，这七十发不会因为第八十发而出金就变得值得，它们已经没了。\n"
    "第二步：接受自己不会执行第一步。\n"
    "第三步：打开商城，看着那行「限时」，深呼吸，然后点下去。",

    "你不是在抽角色，你是在抽一个愿意为你停留的下午。\n"
    "屏幕亮起来的时候，房间里只有你、耳机和一句台词。\n"
    "现实里没人这么说话，所以你愿意为这句话付费，一次，再一次。\n"
    "他们卖的是数据，你买的是被人认真对待的那十秒。",

    "沉船了。屏幕上是熟悉的紫光，一排蓝色的名字。\n"
    "你盯着看了很久，然后退出，锁屏，把手机扣在桌上。\n"
    "三分钟后你把它翻过来，屏幕还亮着，公告写着「卡池持续至下周三」。\n"
    "你笑了，说好，那就下周三。",

    "领域展开——『十连保底』。\n"
    "在这片领域里，你必定命中的不是当期角色，而是下一页的付款成功。\n"
    "术式效果：所有理性判断无效，所有「再抽最后一发」生效。",

    "「你下一句要说的是——『我再抽最后一发』。」\n"
    "你沉默了两秒，张嘴：「我再抽最后一发。」\n"
    "「……你怎么知道的。」\n"
    "「因为上一次你也是这么说的。」",

    "理智在你耳边说：够了，收手吧。\n"
    "你缓缓抬起手，摆出那个姿势：\n"
    "「但是我拒绝！」\n"
    "然后点下了十连。屏幕亮起的那一刻，你觉得值了。",

    "这不是运气不好，这是替身攻击。\n"
    "替身名：『沉没成本』。\n"
    "能力：让你觉得再来一发就能翻盘。\n"
    "替身使者：你自己的手。",

    "人类的赞歌就是抽卡的赞歌，人类的钱包就是勇气的代价。\n"
    "你明知概率写在那里，还是把硬币投了进去。\n"
    "这不是蠢，这是明知不可为而为之的浪漫。",

    "时间停止吧——\n"
    "在你输完支付密码、还没按下确认的那三秒里，世界真的停了。\n"
    "没有歪，没有保底，没有紫色的光。\n"
    "然后你按了下去。",

    "天上天下，唯我独非。\n"
    "歪了七次，第八次我依然是那个相信奇迹的人。\n"
    "不是因为我乐观，是因为我已经没有别的东西可以相信了。",

    "保底还剩二十发。\n"
    "「会赢的。」\n"
    "你说这话的时候没看钱包，也没看公告。\n"
    "你只是需要有人说一句会赢，哪怕说的人是自己。",

    "抽卡也分级：\n"
    "三级术师看概率，二级术师看玄学，一级术师看预算。\n"
    "特级术师什么都不看——因为你已经超脱了，你只剩下手。",

    "你吞下的不是手指，是十连记录。\n"
    "越吞越强，越强越吞。\n"
    "到最后你成了那个诅咒本身——\n"
    "别人抽卡前会来问你：这次能出吗。你说：能。",
]

# 优先用独立模块里的长文案库（21 篇）；上面的短列表只作为降级兜底
try:
    from gacha_texts import TEXTS as _BUILTIN_TEXTS

    GACHA_TEXTS = list(_BUILTIN_TEXTS)
except Exception as exc:  # noqa: BLE001
    logger.warning(f"persona: 载入 gacha_texts 失败 {type(exc).__name__}: {exc}")
GACHA_TEXT = GACHA_TEXTS[0]
# 没配置就用仓库的 gacha-texts 目录；目录不在时退回上面的内置文案
GACHA_FILE = os.getenv("GACHA_TEXT_FILE", "").strip() or str(Path(__file__).resolve().parents[2] / "gacha-texts")
_last_gacha: list[int] = [-1]


def _load_gacha_texts() -> list[str]:
    """从文件/目录读自定义文案；没有就用内置。"""
    if not GACHA_FILE:
        return GACHA_TEXTS
    try:
        from pathlib import Path as _P

        p = _P(GACHA_FILE)
        files = sorted(p.glob("*.txt")) if p.is_dir() else [p]
        texts = [f.read_text(encoding="utf-8").strip() for f in files if f.is_file()]
        texts = [t for t in texts if t and not t.startswith("#")]
        if texts:
            return texts
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 读 GACHA_TEXT_FILE 失败 {type(exc).__name__}: {exc}")
    return GACHA_TEXTS


def _gacha_text() -> str:
    """随机挑一篇，尽量不连着重复。"""
    texts = _load_gacha_texts()
    if len(texts) == 1:
        return texts[0]
    pool = [i for i in range(len(texts)) if i != _last_gacha[0]]
    idx = random.choice(pool or list(range(len(texts))))
    _last_gacha[0] = idx
    return texts[idx]


def _save_modes() -> None:
    try:
        MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(_mode_state)
        payload["groups"] = dict(_group_modes)
        payload["chime"] = dict(_chime_override)
        MODE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 模式保存失败 {type(exc).__name__}: {exc}")


def _apply_mode(name: str, kind: str = "group", key: str | None = None) -> bool:
    if name not in MODES:
        return False
    if kind == "all":
        # 全局 = 统一所有群：清掉各群单独设置，之后所有群都用这个默认
        cleared = len(_group_modes)
        _group_modes.clear()
        _mode_state["group"] = name
        _save_modes()
        cfg = MODES[name]
        logger.info(
            f"persona: 全局群聊统一切到「{name}」——清掉 {cleared} 个群单独设置，"
            f"被叫 {cfg['called']:.0%} / 接续 {cfg['follow']:.0%} / 冷却 {cfg['cd']:.0f}s"
        )
        return True
    if kind == "group" and key:
        _group_modes[key] = name
        scope = f"本群 {key}"
    else:
        _mode_state[kind] = name
        scope = "群聊默认" if kind == "group" else "私聊"
    _save_modes()
    cfg = _mode_cfg(kind, key)
    logger.info(
        f"persona: {scope}切到「{name}」——"
        f"被叫 {cfg['called']:.0%} / 接续 {cfg['follow']:.0%} / 冷却 {cfg['cd']:.0f}s"
    )
    return True


def _load_mode() -> None:
    try:
        if MODE_FILE.is_file():
            data = json.loads(MODE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for kind in ("group", "private"):
                    name = data.get(kind)
                    if name in MODES:
                        _mode_state[kind] = str(name)
                groups = data.get("groups")
                if isinstance(groups, dict):
                    for gkey, name in groups.items():
                        if isinstance(name, str) and name in MODES:
                            _group_modes[str(gkey)] = name
                chime = data.get("chime")
                if isinstance(chime, dict):
                    for gkey, prob in chime.items():
                        try:
                            _chime_override[str(gkey)] = max(0.0, min(1.0, float(prob)))
                        except (TypeError, ValueError):
                            continue
            return
        legacy = _DATA_DIR / "reply_mode.json"
        if legacy.is_file():
            name = json.loads(legacy.read_text(encoding="utf-8")).get("mode", "")
            if name in MODES:
                _mode_state["group"] = str(name)
                _save_modes()
    except Exception:  # noqa: BLE001
        pass


RECALL_HINTS = ("记得", "上次", "之前", "以前", "那次", "回忆", "白守", "记忆")

_last_sticker: dict[str, float] = defaultdict(float)
_last_auto_sticker: dict[str, float] = defaultdict(float)
_last_sticker_only: dict[str, float] = defaultdict(float)
_recent_user_msgs: dict[str, deque] = defaultdict(lambda: deque(maxlen=12))
_snub_until: dict[str, float] = {}
_last_reply: dict[str, float] = defaultdict(float)
_last_chime: dict[str, float] = defaultdict(float)
_last_message_at: dict[str, float] = {}
# 每个会话最近一张图的 image 段：有人追问「图里写的啥」时现看，不用预先 OCR
_last_image_seg: dict[str, tuple[float, object]] = {}
_recent_reply_times: deque[float] = deque(maxlen=64)
_group_sent: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=128))
_last_casual: dict[str, float] = defaultdict(float)
_history: dict[str, deque[tuple[str, str]]] = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))
_engaged: dict[str, dict] = {}
_last_save = [0.0]
# 小本本计数：距上次摘日记聊了几轮 / 群里过了几条
_diary_user_turns: dict[str, int] = defaultdict(int)
_diary_user_last: dict[str, float] = defaultdict(float)
_diary_group_msgs: dict[str, int] = defaultdict(int)
_diary_group_last: dict[str, float] = defaultdict(float)
# 后台任务要留引用，否则可能被回收（见 AGENTS.md #8）
_bg_tasks: set[asyncio.Task] = set()

persona = on_message(priority=50, block=False)

if not MOCK and not API_KEY:
    logger.warning("persona: 未配置 LLM_API_KEY，插件会保持沉默（可用 LLM_MOCK=1 试跑规则）")
if not DEV_UIN:
    logger.warning("persona: 未配置 DEV_UIN，管理指令全部禁用")


def _load_history() -> None:
    try:
        if not HISTORY_FILE.is_file():
            return
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        for key, items in raw.items():
            dq = deque(maxlen=HISTORY_SIZE)
            for item in items:
                if isinstance(item, list) and len(item) == 2:
                    dq.append((str(item[0]), str(item[1])))
            _history[key] = dq
        logger.info(f"persona: 载入 {len(_history)} 个会话的历史上下文")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 历史载入失败 {type(exc).__name__}: {exc}")


def _save_history(force: bool = False) -> None:
    now = time.time()
    if not force and now - _last_save[0] < 5:
        return
    _last_save[0] = now
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {key: [list(pair) for pair in items] for key, items in _history.items()}
        tmp = HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(HISTORY_FILE)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 历史保存失败 {type(exc).__name__}: {exc}")


_load_history()
_load_mode()

logger.info(
    f"persona: 上下文 {HISTORY_SIZE} 条，插话概率 {CHIME_PROB:.0%}，"
    f"单条上限 {MAX_CHARS} 字，被叫冷却 {FOLLOW_COOLDOWN_SEC:.0f}s / 插话冷却 {COOLDOWN_SEC:.0f}s / 插话间隔 {CHIME_COOLDOWN_SEC:.0f}s"
)
logger.info(
    f"persona: 群聊默认「{_mode_name('group')}」/ 私聊「{_mode_name('private')}」"
    + (f"，另有 {len(_group_modes)} 个群单独设置" if _group_modes else "")
)
logger.info(
    f"persona: 接续窗口 {ENGAGE_TTL:.0f}s（同人）/{ENGAGE_FOLLOW_WINDOW:.0f}s（其他人），"
    f"最多来回 {ENGAGE_MAX_TURNS} 次，冷处理 {SNUB_SECONDS:.0f}s，外号 {'/'.join(NICKNAMES) or '无'}"
)
logger.info(
    f"persona: 表情 自动配图概率 {STICKER_AUTO_PROB:.0%}（炸毛翻倍，上限 90%），"
    f"自动间隔 {STICKER_AUTO_COOLDOWN:.0f}s"
)


_USAGE_FILE = _DATA_DIR / "usage.jsonl"
_usage_lock = threading.Lock()


def _record_usage(usage: dict | None) -> None:
    """把每次调用的 token 用量追加到 data/usage.jsonl，供 /用量 看账。"""
    if not usage:
        return
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        details = usage.get("prompt_tokens_details") or {}
        row = {
            "t": time.time(),
            "p": int(usage.get("prompt_tokens") or 0),
            "c": int(usage.get("completion_tokens") or 0),
            "hit": int(details.get("cached_tokens") or usage.get("prompt_cache_hit_tokens") or 0),
        }
        with _usage_lock:
            with _USAGE_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"persona: 用量记录失败 {type(exc).__name__}: {exc}")


def _usage_today() -> tuple[list[dict], int]:
    today = datetime.now().strftime("%Y-%m-%d")
    rows: list[dict] = []
    try:
        for line in _USAGE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if datetime.fromtimestamp(float(row.get("t", 0))).strftime("%Y-%m-%d") == today:
                rows.append(row)
    except FileNotFoundError:
        pass
    return rows, len(rows)


def _call_llm_sync(messages: list[dict[str, str]], max_tokens: int = 48, temperature: float = 0.95) -> str:
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stop": ["\n"],
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    _record_usage(data.get("usage"))

    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")


async def ask_llm(messages: list[dict[str, str]], max_tokens: int = 48, temperature: float = 0.95) -> str:
    if MOCK:
        return "（笑）这个吧...其实我觉得还行吧 😂 不过说真的你要是非这么想那也没办法啦"
    return await asyncio.to_thread(_call_llm_sync, messages, max_tokens, temperature)


def _background(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


def _bond_touch(user_id: str, name: str, delta: int) -> dict:
    try:
        rec = bonds.touch(user_id, name, delta)
        bonds.save()
        return rec
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 小本本更新失败 {type(exc).__name__}: {exc}")
        return bonds.user(user_id)


async def _diary_user(user_id: str, name: str, lines: list[tuple[str, str]], src: str) -> None:
    """从和这个人最近的几句里摘一两条以后用得上的事。"""
    talk = [f"{'我' if who == '我' else '对方'}：{text}" for who, text in lines if who in ("我", name)][-12:]
    if MOCK or not API_KEY or not any(t.startswith("对方") for t in talk):
        return
    try:
        raw = await ask_llm(
            [{"role": "system", "content": DIARY_USER_PROMPT}, {"role": "user", "content": "\n".join(talk)}],
            60, temperature=0.2,
        )
        notes = parse_notes(raw, 2, bonds.NOTE_MAX_CHARS)
        if notes:
            bonds.add_user_notes(user_id, notes, src)
            bonds.save(force=True)
            logger.info(f"persona: 小本本记下 {name}：{'；'.join(notes)}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 摘个人日记失败 {type(exc).__name__}: {exc}")


async def _diary_group(group_id: str, lines: list[tuple[str, str]]) -> None:
    """从群里最近的聊天里摘群友之间的关系。"""
    talk = [f"{who}：{text}" for who, text in lines][-30:]
    if MOCK or not API_KEY or len(talk) < 10:
        return
    try:
        raw = await ask_llm(
            [{"role": "system", "content": DIARY_GROUP_PROMPT}, {"role": "user", "content": "\n".join(talk)}],
            80, temperature=0.2,
        )
        notes, style = parse_group_diary(raw, bonds.NOTE_MAX_CHARS)
        if notes or style:
            bonds.add_group_notes(group_id, notes)
            bonds.add_group_style(group_id, style)
            bonds.save(force=True)
            logger.info(f"persona: 群日记记下 群{group_id}：关系 {'；'.join(notes) or '无'}｜风格 {'；'.join(style) or '无'}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 摘群日记失败 {type(exc).__name__}: {exc}")


async def _maybe_save_sticker(seg, card: str, user_id: str, context: str = "") -> None:
    """群友发了库里没有的表情，看心情收藏一张；讨厌的人发的不收。用途按发图时的场景记进表情备注。"""
    data = getattr(seg, "data", None) or {}
    is_sticker = str(data.get("sub_type", "")) == "1" or "表情" in str(data.get("summary", ""))
    if not is_sticker or card.startswith("[表情:") or random.random() >= STICKER_SAVE_PROB:
        return
    if int(bonds.user(user_id).get("aff", 0)) <= -30:
        return
    raw = await vision.fetch_seg(seg)
    if not raw:
        return
    text = card.split("｜", 1)[1].rstrip("]") if "｜" in card else ""
    try:
        scene = sticker_scene(context)
        item = await asyncio.to_thread(
            sticker_lib.save_sticker, raw, sticker_category(text), text, scene[0] if scene else "",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 收藏表情失败 {type(exc).__name__}: {exc}")
        return
    if item:
        logger.info(f"persona: 收藏了一张表情 {item['file']}（{item['category']}）")


@nonebot.get_driver().on_shutdown
async def _save_bonds() -> None:
    try:
        bonds.save(force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: 小本本保存失败 {type(exc).__name__}: {exc}")


def _quota_ok(kind: str, key: str | None = None) -> bool:
    """群聊全局每分钟额度 + 本群每小时额度（都按 QUOTA_TIERS 分档）；私聊和被叫触发的抽卡定型文不走这里。"""
    now = time.time()
    while _recent_reply_times and now - _recent_reply_times[0] > 60:
        _recent_reply_times.popleft()
    if not quota_allows(len(_recent_reply_times), GLOBAL_PER_MIN, kind):
        return False
    if key is None or GROUP_PER_HOUR <= 0:
        return True
    sent = _group_sent[key]
    while sent and now - sent[0] > 3600:
        sent.popleft()
    return quota_allows(len(sent), GROUP_PER_HOUR, kind)


def _mark_sent(key: str, now: float, at_reply: bool = False) -> None:
    """群里发了一条（含表情），记进每分钟额度；没被 @ 的还记进本群每小时额度和间隔。"""
    _recent_reply_times.append(now)
    if not at_reply:
        _group_sent[key].append(now)
        _last_casual[key] = now


def _is_target_account(event: MessageEvent) -> bool:
    if not BOT_UIN:
        return True
    return str(getattr(event, "self_id", "")) == BOT_UIN


def _session_key(event: MessageEvent) -> str:
    """群聊按「群」记上下文，而不是按「人」。

    NoneBot 默认的 get_session_id() 是 group_<群号>_<发言人QQ>，
    会把同一个群切成一人一条线，别人接话时接不上。
    """
    if getattr(event, "message_type", "") == "group":
        return f"group_{event.group_id}"
    return f"private_{event.get_user_id()}"


def _should_look_image(event: MessageEvent) -> bool:
    """这张图值不值得在本地识一下。

    只认四种情况：@ 我、私聊、正接续的对话、引用回复我的消息。
    普通群友随手发的图没人问，就不识图——省 CPU 也省 token。
    """
    if not vision.IMG_CARD_ENABLED:
        return False
    if getattr(event, "message_type", "") == "private":
        return True
    if getattr(event, "to_me", False):
        return True
    eng = _engaged.get(_session_key(event))
    if eng and time.time() - eng.get("last", 0) <= ENGAGE_TTL:
        return True
    reply = getattr(event, "reply", None)
    sender = getattr(reply, "sender", None) if reply is not None else None
    if sender is not None and str(getattr(sender, "user_id", "")) == str(event.self_id):
        return True
    return False


# 追问图片内容时会用到的词；命中就拿本会话最近一张图现做图卡
IMAGE_HINTS = ("图", "截图", "表情", "这张", "那张", "图上", "图里", "图片")
IMAGE_RECALL_SEC = float(os.getenv("IMAGE_RECALL_SEC", "600"))


async def _card_of_last_image(key: str) -> str:
    saved = _last_image_seg.get(key)
    if not saved:
        return ""
    at, seg = saved
    if time.time() - at > IMAGE_RECALL_SEC:
        _last_image_seg.pop(key, None)
        return ""
    return await vision.card_for_seg(seg)


@persona.handle()
async def _handle(bot: Bot, event: MessageEvent) -> None:
    if not is_our_bot(event):
        return

    if not _is_target_account(event):
        return

    now = time.time()
    key = _session_key(event)
    seg_now = next((s for s in event.get_message() if s.type == "image"), None)
    if seg_now is not None:
        # 先记着这张图：万一群友下一条才问「图里说的是啥」，可以拿它现看
        _last_image_seg[key] = (now, seg_now)
        if len(_last_image_seg) > 200:
            for old_key in sorted(_last_image_seg, key=lambda k: _last_image_seg[k][0])[:50]:
                _last_image_seg.pop(old_key, None)

    text = event.get_plaintext().strip()
    if is_game_command(text, GAME_CMD_PREFIXES):
        # 游戏指令由早柚核心回，人设不接话，也不进上下文和日记
        return
    if not text:
        # 纯图片：只有「本来就要理这张图」的情况才做本地识图，免得白烧 CPU 和 token
        if not _should_look_image(event):
            return
        card = await vision.image_card(event)
        if not card:
            return
        logger.info(f"persona: 图片图卡 -> {card}")
        text = card
        if str(event.get_user_id()) != str(event.self_id):
            prev = _history[key][-1][1] if _history[key] else ""
            _background(_maybe_save_sticker(seg_now, card, str(event.get_user_id()), prev))
    elif seg_now is None and any(h in text for h in IMAGE_HINTS):
        # 「图片里的话是啥意思」这类追问：把刚才那张图的图卡补进上下文
        card = await _card_of_last_image(key)
        if card:
            logger.info(f"persona: 追问补图卡 -> {card}")
            text = f"{text}\n（刚才那张图：{card}）"

    if str(event.get_user_id()) == str(event.self_id):
        return

    is_group = getattr(event, "message_type", "") == "group"
    chat_kind = "group" if is_group else "private"
    mcfg = _mode_cfg(chat_kind, key)
    mname = _mode_name(chat_kind, key)
    user_id = str(event.get_user_id())

    sender = getattr(event, "sender", None)
    name = (getattr(sender, "card", "") or getattr(sender, "nickname", "") or "群友") if sender else "群友"

    # 身份对齐：开发者统一记成「酱酱鱼」，别人用自己的群名片
    if DEV_UIN and user_id == DEV_UIN:
        name = DEV_NAME or name
    else:
        name = safe_name(name, user_id, (DEV_NAME, *NICKNAMES))

    # 私聊内容同时记进白守日记（形成长期人格的素材）
    if not is_group and PRIVATE_MIRROR:
        try:
            await asyncio.to_thread(memory.remember, f"对方：{text}", f"私聊{user_id}")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"persona: 私聊记录失败 {type(exc).__name__}: {exc}")

    history = _history[key]
    idle = now - _last_message_at.get(key, now)
    started_at = now
    history.append((name, text))
    _my_entry = history[-1]
    _last_message_at[key] = now
    _save_history()
    if is_group and DIARY_GROUP_EVERY > 0:
        _diary_group_msgs[key] += 1
        if _diary_group_msgs[key] >= DIARY_GROUP_EVERY and now - _diary_group_last[key] >= DIARY_GROUP_GAP:
            _diary_group_msgs[key], _diary_group_last[key] = 0, now
            _background(_diary_group(str(event.group_id), list(history)))
    # 快照：模型只能看到「这条消息之前」的上下文，否则它会顺手回答后来插进来的新消息，
    # 结果就变成「@甲 回乙的话」那种错位
    past_snapshot = list(history)
    for _i in range(len(past_snapshot) - 1, -1, -1):
        if past_snapshot[_i] is _my_entry:
            del past_snapshot[_i]
            break

    # 静音 = 完全不出声（不接续、不插话、不主动配图）；/模式、/表情、查询等命令走别的 matcher，照常可用
    if mname == "静音":
        logger.debug("persona: 静音模式，不回话")
        return

    # --- 被追问到烦：先冷淡答题，再主动收尾 ---
    recent = _recent_user_msgs[key]
    recent.append((user_id, text, now))
    while recent and now - recent[0][2] > PESTER_WINDOW:
        recent.popleft()

    if is_group and now < _snub_until.get(key, 0) and user_id != DEV_UIN:
        logger.info("persona: 正在冷处理这段时间，不接话")
        return

    same_user = [t for (uid, t, ts) in recent if uid == user_id]
    annoyed, why = judge_annoyance(same_user, PESTER_WINDOW, PESTER_COUNT)
    if is_group and annoyed and user_id != DEV_UIN:
        _bond_touch(user_id, name, AFF_PESTER)
        _snub_until[key] = now + SNUB_SECONDS
        _engaged.pop(key, None)
        past = past_snapshot
        messages = compose_messages(
            past, name, text, atmosphere="烦", self_names=NICKNAMES,
            mood="不耐烦", dev_name=DEV_NAME or None,
        )
        if not _quota_ok("被叫", key):
            logger.info(f"persona: 嫌烦收尾跳过（全局限流），冷处理照旧（{why}）")
            return
        try:
            raw = await ask_llm(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"persona: 收尾回复失败 {type(exc).__name__}: {exc}")
            return
        reply = humanize(raw, MAX_CHARS, fallback="烦了，不说了")
        if is_offensive(reply):
            reply = "烦了，不说了"
        history.append(("我", reply))
        _save_history(force=True)
        logger.info(f"persona -> {reply}（嫌烦收尾：{why}，冷处理 {SNUB_SECONDS:.0f}s）")
        await bot.send(event, reply)
        _mark_sent(key, now)
        return

    # 收尾的话就散场，不接
    if is_conversation_ending(text):
        _engaged.pop(key, None)
        return

    mode = ""
    addressed = False

    if is_group:
        at_me = bool(getattr(event, "to_me", False))
        if at_me or looks_addressed(text, NICKNAMES):
            addressed = True
            # 只有真的被 @ 才回 @；只喊名字或接着聊都不 @，免得刷屏
            mode = "被叫@" if at_me else "被叫"
            _engaged[key] = {"last": now, "turns": 0, "partner": user_id}
        else:
            ok, why = follow_decision(
                _engaged.get(key), user_id, now, ENGAGE_TTL, ENGAGE_FOLLOW_WINDOW, ENGAGE_MAX_TURNS
            )
            if ok:
                addressed = True
                mode = f"接续·{why}"
            else:
                _engaged.pop(key, None)
                chime_prob = _chime_prob(key, mcfg)
                if chime_prob <= 0 or random.random() >= chime_prob:
                    return
                if now - _last_chime.get(key, 0) < CHIME_COOLDOWN_SEC or not _quota_ok("插话", key):
                    return
                label, allowed, reason = judge_atmosphere(list(history), idle)
                if not allowed:
                    logger.debug(f"persona: 不插话（{label}：{reason}）")
                    return
                mode = f"插话·{label}"
    else:
        addressed = True
        mode = "私聊"

    # 跟她说话才算互动：好感、熟悉度按 QQ 号记，群里私聊是同一份
    bond = _bond_touch(user_id, name, affinity_delta(text)) if addressed else bonds.user(user_id)
    is_dev = bool(DEV_UIN) and user_id == DEV_UIN
    att = None if is_dev else attitude(int(bond.get("aff", 0)), int(bond.get("fam", 0)))

    # 被叫/接续用短冷却（聊天里 2 秒内接着说是常态），主动插话才用长冷却
    label, _, _ = judge_atmosphere(list(history), idle)
    mood, mood_reason = judge_mood(list(history), label)

    # 「发张表情包」这类明确请求：直接给图，和图之外的话分开计时
    if (
        wants_sticker(text)
        and now - _last_sticker.get(key, 0) >= STICKER_COOLDOWN
        and (not is_group or _quota_ok("被叫", key))
    ):
        item = sticker_lib.pick_for_mood(mood, key, STICKER_SAVED_PREFER)
        if item and await sticker_lib.send(bot, event, item):
            _last_sticker[key] = now
            sticker_lib.mark_used(item)
            if is_group:
                _mark_sent(key, now, at_reply=True)
            logger.info(f"persona: 发图 {item['file']}（{item.get('category')}／情绪 {mood}）")

    # 抽卡模式的 @ 照旧按 1.8% 触发定型文，不然每次 @ 都刷一篇长文
    at_reply = mode == "被叫@" and mname != "米游抽卡"
    # 被 @ 或喊名字都算有人找她：不受本群每小时额度和间隔限制（喊名字回不回看态度）
    called = mode.startswith("被叫")
    cd = min(mcfg["cd"], AT_COOLDOWN) if at_reply else mcfg["cd"] if addressed else COOLDOWN_SEC
    elapsed = now - _last_reply.get(key, 0)
    if elapsed < cd:
        logger.info(f"persona: 跳过（冷却中 {elapsed:.1f}s < {cd:.0f}s，模式 {mode or '插话'}）")
        return

    # 不是每条都接：私聊必回，被 @ 就回（静音档前面已经拦了）；喊名字回不回看态度；接续按态度微调，已经是必回的不打折
    if addressed and mode != "私聊" and not at_reply:
        if called:
            prob = name_call_prob("亲近" if is_dev else att, mcfg["called"], PROB_CALLED or 0.5)
        else:
            prob = mcfg["follow"]
            if prob < 1.0:
                prob = min(1.0, prob * ATTITUDE_REPLY_FACTOR.get(att or "普通", 1.0))
        if random.random() > prob:
            logger.info(f"persona: 这次不接（{mode}，概率 {prob:.0%}）")
            return

    # 抽卡模式：命中就发固定长文，不调模型（省 token）
    if mname == "米游抽卡":
        reply = _gacha_text()
        _last_reply[key] = now
        if mode.startswith("插话"):
            _last_chime[key] = now
        history.append(("我", reply[:80]))
        _save_history(force=True)
        logger.info(f"persona: 抽卡模式发定型文（{mode}）")
        if is_group and AT_USER and mode.startswith("被叫@"):
            await bot.send(event, MessageSegment.at(user_id) + "\n" + reply)
        else:
            await bot.send(event, reply)
        # 被叫触发的定型文不拦，但照样占额度，让其它闲聊先让路
        if is_group:
            _mark_sent(key, now)
        return

    if is_group and not called:
        if now - _last_casual[key] < CASUAL_GAP:
            logger.info(f"persona: 跳过（离上次没被 @ 的回话不到 {CASUAL_GAP:.0f}s，{mode}）")
            return
        tier = "被叫" if mode.startswith("被叫") else "接续" if mode.startswith("接续") else "插话"
        if not _quota_ok(tier, key):
            logger.info(f"persona: 跳过（限流：每分钟 {GLOBAL_PER_MIN} 条 / 本群每小时 {GROUP_PER_HOUR} 条，{mode}）")
            return

    past = past_snapshot
    if past:
        logger.debug(f"persona: 上下文 {len(past)} 条，末条 {past[-1][0]}: {past[-1][1][:24]}")

    help_mode = wants_help(text)
    question = is_question(text) and not help_mode
    scene = sticker_scene(text)
    # 群里碰到明显场景时有时只甩一张对得上的表情，偶尔也随手甩张无厘头的：像真人冒个泡，也少说话少露馅
    item = None
    if (
        is_group and not help_mode and not called and not wants_sticker(text)
        and now - _last_sticker_only[key] >= STICKER_ONLY_COOLDOWN
        and now - _last_sticker.get(key, 0) >= STICKER_AUTO_COOLDOWN
    ):
        if scene and random.random() < STICKER_ONLY_PROB:
            item = sticker_lib.pick_for_scene(scene[1], key, STICKER_SAVED_PREFER)
        elif not scene and random.random() < STICKER_RANDOM_PROB:
            item = sticker_lib.pick("", key)
    if item:
        if await sticker_lib.send(bot, event, item):
            sticker_lib.mark_used(item, scene[0] if scene else None)
            _last_reply[key] = _last_sticker[key] = _last_sticker_only[key] = now
            if mode.startswith("插话"):
                _last_chime[key] = now
            history.append(("我", f"[表情:{item.get('category') or '表情'}]"))
            _save_history(force=True)
            _mark_sent(key, now)
            st = _engaged.get(key)
            if st is not None and addressed:
                st["last"], st["turns"] = now, int(st.get("turns", 0)) + 1
            logger.info(f"persona: 只回了张表情 {item['file']}（{mode}，场景 {scene[0] if scene else '无厘头'}）")
            return

    # 问到「记得/上次」这类，翻一下白守里的记忆
    notes = None
    if memory.available() and any(hint in text for hint in RECALL_HINTS):
        # 只带本会话的记录和开发者 /记 的笔记
        scope = f"群{event.group_id}" if is_group else f"私聊{user_id}"
        notes = await asyncio.to_thread(memory.recent, 5, (scope, DEV_NAME))
        if notes:
            logger.info(f"persona: 带上 {len(notes)} 条记忆")

    # 底子是傲：每句按态度抽一次签，抽中才露一点真心
    dere = random.random() < DERE_CHANCE.get("开发者" if is_dev else att or "普通", 0.0)
    # 小本本：跟她说话时才带（插话不带，省 token）
    user_notes = visible_notes(bond.get("notes"), is_group) if addressed else None
    group_rec = bonds.group(str(event.group_id)) if is_group else {}
    group_notes = visible_notes(group_rec.get("notes"), True) if addressed else None
    # 本群风格插话时也带，冒泡才像这个群的人
    group_style = visible_notes(group_rec.get("style"), True, limit=3) if is_group else None

    messages = compose_messages(
        past,
        name,
        text,
        atmosphere=label,
        self_names=NICKNAMES,
        mood=mood,
        dev_name=DEV_NAME or None,
        memory_notes=notes,
        has_memory=memory.available(),
        chime=mode.startswith("插话"),
        # 插话/单发场景只带一半历史，省一半输入 token
        budget=CHIME_HISTORY_BUDGET if mode.startswith("插话") else None,
        help_mode=help_mode,
        hour=datetime.now().hour,
        attitude=att,
        dere=dere,
        user_notes=user_notes,
        group_notes=group_notes,
        group_style=group_style,
        flavor=pick_flavor(),
    )

    try:
        raw = await ask_llm(messages, HELP_MAX_TOKENS if help_mode else 64 if question else 48)
    except urllib.error.HTTPError as exc:
        logger.warning(f"persona: LLM HTTP {exc.code} {exc.reason}")
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"persona: LLM 调用失败 {type(exc).__name__}: {exc}")
        return

    reply = humanize(raw, MAX_CHARS_HELP if help_mode else MAX_CHARS_QUESTION if question else MAX_CHARS)
    if not reply:
        return
    if is_offensive(reply):
        logger.warning(f"persona: 这句带攻击性，不发：{reply}")
        return

    # 接续/插话本来就可有可无：这期间别人已经插了新话，就别补旧的一句，否则看着像答错人
    if is_group and not mode.startswith("被叫") and _last_message_at.get(key, 0.0) > started_at:
        logger.info("persona: 会话已翻篇，这句不补了")
        return

    _last_reply[key] = now
    if mode.startswith("插话"):
        _last_chime[key] = now
    history.append(("我", reply))
    _save_history(force=True)

    st = _engaged.get(key)
    if st is not None and addressed:
        st["last"] = now
        st["turns"] = int(st.get("turns", 0)) + 1

    logger.info(
        f"persona -> {reply}（{mode}，氛围 {label}，情绪 {mood}·{mood_reason}，对象 {name}"
        f"，态度 {'开发者' if is_dev else att}{'·露真心' if dere else ''}）"
    )
    if is_group and AT_USER and mode.startswith("被叫@"):
        await bot.send(event, MessageSegment.at(user_id) + " " + reply)
    else:
        await bot.send(event, reply)
    if is_group:
        _mark_sent(key, now, called)

    # 聊够几轮、或者对方在说自己的事，就摘一次个人日记（同一人至少隔 10 分钟）
    if DIARY_USER_EVERY > 0 and addressed:
        _diary_user_turns[user_id] += 1
        if (
            _diary_user_turns[user_id] >= DIARY_USER_EVERY
            or (looks_self_disclosure(text) and _diary_user_turns[user_id] >= 2)
        ) and now - _diary_user_last[user_id] >= 600:
            _diary_user_turns[user_id], _diary_user_last[user_id] = 0, now
            src = f"g{event.group_id}" if is_group else "p"
            _background(_diary_user(user_id, name, list(history), src))

    if not is_group and PRIVATE_MIRROR:
        try:
            await asyncio.to_thread(memory.remember, f"我：{reply}", f"私聊{user_id}")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"persona: 私聊记录失败 {type(exc).__name__}: {exc}")
    elif is_group and GROUP_MIRROR and mode.startswith(("被叫", "接续")):
        # 群聊里只有真被叫/接续的对话才进记忆，随机插话不记，免得日记变成闲聊流水账
        tag = f"群{event.group_id}"
        try:
            await asyncio.to_thread(memory.remember, f"{name}：{text}", tag)
            await asyncio.to_thread(memory.remember, f"我：{reply}", tag)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"persona: 群聊记录失败 {type(exc).__name__}: {exc}")

    # 偶尔自己配一张图（这一轮已经被要求发过图就不重复）
    if not wants_sticker(text):
        chance = min(0.9, STICKER_AUTO_PROB * (2 if mood == "炸毛" else 1) * (1.5 if att == "亲近" else 1))
        roll = random.random()
        logger.debug(f"persona: 配图判定 chance={chance:.2f} roll={roll:.3f} mood={mood}")
        if (
            roll < chance
            and now - _last_auto_sticker.get(key, 0) >= STICKER_AUTO_COOLDOWN
            and now - _last_sticker.get(key, 0) >= STICKER_COOLDOWN
            and (not is_group or _quota_ok("插话", key))
        ):
            # 有场景就挑对得上的，没有才按情绪挑
            item = (sticker_lib.pick_for_scene(scene[1], key, STICKER_SAVED_PREFER) if scene else None) \
                or sticker_lib.pick_for_mood(mood, key, STICKER_SAVED_PREFER)
            if item and await sticker_lib.send(bot, event, item):
                _last_auto_sticker[key] = now
                _last_sticker[key] = now
                sticker_lib.mark_used(item, scene[0] if scene else None)
                if is_group:
                    _mark_sent(key, now, called)
                logger.info(f"persona: 顺手配图 {item['file']}（{mood}，概率 {chance:.0%}）")
mode_cmd = on_command("模式", priority=16, block=True)


@mode_cmd.handle()
async def _mode_cmd(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return

    """切换回复频率：群里只改本群，加 全局/默认 改所有群的默认（仅开发者可用）。"""
    if not DEV_UIN or str(event.get_user_id()) != DEV_UIN:
        return

    kind = _chat_kind(event)
    key = _session_key(event) if kind == "group" else None
    label = "群聊" if kind == "group" else "私聊"
    options = "、".join(MODES)

    tokens = arg.extract_plain_text().strip().split()
    scope = "local"
    if tokens and tokens[0] in ("全局", "默认"):
        scope = "global"
        tokens = tokens[1:]
    name = tokens[0] if tokens else ""

    cfg = _mode_cfg(kind, key)

    if not name:
        if kind == "group":
            cur = _mode_name(kind, key)
            origin = "（本群单独设置）" if key in _group_modes else f"（继承全局默认「{_mode_name(kind)}」）"
            await mode_cmd.finish(
                f"本群当前「{cur}」{origin}\n"
                f"全局群聊默认「{_mode_name(kind)}」；{_mode_desc(cfg)}\n"
                f"可选：{options}\n"
                f"「静音」= 完全不说话（不插话也不接续）；插话只在省话/话痨档按概率发生\n"
                f"只改本群：/模式 话痨　统一所有群：/模式 全局 话痨（会清掉各群单独设置）"
            )
        await mode_cmd.finish(
            f"{label}当前「{_mode_name(kind, key)}」：{_mode_desc(cfg)}\n"
            f"可选：{options}（例：/模式 话痨）"
        )

    if name not in MODES:
        await mode_cmd.finish(f"没有「{name}」，可选：{options}")

    cleared = len(_group_modes)
    if scope == "global" and kind == "group":
        # 全局 = 所有群统一，同时清掉各群单独设置
        target_kind, target_key = "all", None
        scope_label = "全局群聊默认（所有群统一）"
    else:
        target_kind = kind
        target_key = None if scope == "global" else key
        scope_label = "本群" if target_key else label

    if not _apply_mode(name, target_kind, target_key):
        await mode_cmd.finish(f"没有「{name}」，可选：{options}")

    cfg = MODES[name]
    extra = f"，清掉 {cleared} 个群的单独设置" if target_kind == "all" and cleared else ""
    await mode_cmd.finish(
        f"已把{scope_label}切到「{name}」{extra}：{_mode_desc(cfg)}"
    )


gacha_cmd = on_command("米游抽卡", priority=16, block=True)


@gacha_cmd.handle()
async def _gacha_cmd(bot: Bot, event: MessageEvent) -> None:
    if not is_our_bot(event):
        return

    """把回复频率切到抽卡模式（仅开发者）。"""
    if not DEV_UIN or str(event.get_user_id()) != DEV_UIN:
        return
    kind = _chat_kind(event)
    key = _session_key(event) if kind == "group" else None
    label = "本群" if kind == "group" else "私聊"
    _apply_mode("米游抽卡", kind, key)
    cfg = _mode_cfg(kind, key)
    await gacha_cmd.finish(
        f"已把{label}切到「米游抽卡」：{_mode_desc(cfg)}\n"
        "真触发时发那段定型文，不调模型。"
    )


# 「必定触发」：不管当前什么模式，发一条就出一段定型文
BIBLE_CD = float(os.getenv("BIBLE_COOLDOWN", "5"))
_last_bible: dict[str, float] = {}

bible_cmd = on_command("圣经", aliases={"定型文", "抽卡圣经"}, priority=15, block=True)


@bible_cmd.handle()
async def _bible_cmd(bot: Bot, event: MessageEvent) -> None:
    if not is_our_bot(event):
        return

    if BOT_UIN and str(getattr(event, "self_id", "")) != BOT_UIN:
        return

    # 只允许管理员（开发者）手动触发
    if not DEV_UIN or str(event.get_user_id()) != DEV_UIN:
        logger.debug("persona: /圣经 非管理员，忽略")
        return

    key = str(event.get_session_id())
    now = time.time()
    if now - _last_bible.get(key, 0) < BIBLE_CD:
        return
    _last_bible[key] = now

    text = _gacha_text()
    logger.info(f"persona: /圣经 手动触发（{len(text)} 字）")
    await bot.send(event, text)
    if getattr(event, "message_type", "") == "group":
        _recent_reply_times.append(now)

# 看账：今日 token 用量（管理员）
usage_cmd = on_command("用量", priority=15, block=True)


@usage_cmd.handle()
async def _usage_cmd(bot: Bot, event: MessageEvent) -> None:
    if not is_our_bot(event) or not _is_target_account(event):
        return
    if not DEV_UIN or str(event.get_user_id()) != DEV_UIN:
        return

    rows, calls = _usage_today()
    if not calls:
        await usage_cmd.finish("今天还没调过模型。")
        return
    prompt = sum(r.get("p", 0) for r in rows)
    comp = sum(r.get("c", 0) for r in rows)
    hit = sum(r.get("hit", 0) for r in rows)
    rate = hit / prompt if prompt else 0.0
    await usage_cmd.finish(
        f"今日模型调用 {calls} 次：输入 {prompt} / 输出 {comp} token，"
        f"缓存命中 {rate:.0%}，平均每次输入 {prompt // calls}。"
    )


# 插话开关：单独控制「没人叫时插不插话」，与静音档解耦（管理员）
chime_cmd = on_command("插话", priority=16, block=True)


@chime_cmd.handle()
async def _chime_cmd(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not is_our_bot(event):
        return
    if not DEV_UIN or str(event.get_user_id()) != DEV_UIN:
        return

    kind = _chat_kind(event)
    if kind != "group":
        await chime_cmd.finish("插话只对群聊有意义，私聊是必回的。")
        return

    key = _session_key(event)
    mname = _mode_name(kind, key)
    mcfg = _mode_cfg(kind, key)
    cur = _chime_prob(key, mcfg)
    raw = arg.extract_plain_text().strip()

    if not raw:
        tail = "（本群单独设定）" if key in _chime_override else f"（跟随「{mname}」档）"
        await chime_cmd.finish(
            f"没人叫时插话概率 {cur:.0%}{tail}\n"
            "插话 = 没被点名也凑一句；静音档固定 0，完全不出声。\n"
            "改：/插话 5% 或 /插话 0.05；关：/插话 关；恢复跟档位：/插话 默认"
        )
        return

    if raw in ("关", "关闭", "关掉"):
        _chime_override[key] = 0.0
        _save_modes()
        await chime_cmd.finish(f"本群插话已关（0%）；/插话 默认 可恢复跟「{mname}」档")
        return

    if raw in ("默认", "恢复", "开", "打开"):
        _chime_override.pop(key, None)
        _save_modes()
        default = float(mcfg.get("chime", CHIME_PROB))
        await chime_cmd.finish(f"已恢复跟「{mname}」档的插话概率（{default:.0%}）")
        return

    try:
        val = float(raw.rstrip("%％"))
    except ValueError:
        await chime_cmd.finish("看不懂，用 0.05 / 5% / 关 / 默认")
        return
    if val > 1:
        val /= 100.0
    val = max(0.0, min(1.0, val))
    _chime_override[key] = val
    _save_modes()
    await chime_cmd.finish(f"本群插话概率改成 {val:.0%}（/插话 默认 恢复跟档位）")
