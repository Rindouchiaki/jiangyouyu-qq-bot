"""知识库指令：开发者让她去弄懂一个话题，她自己查、自己整理；每周自己看一眼有没有新东西。

- /学习 话题 [指引]              让她去学（指引只是参考，比如「看 B 站星野饼美的动态刷新影之诗饼图和卡组」）
- /知识库                        懂哪些话题、各多少条、多久前更新，和待审区（聊天时她常查的词）
- /知识库 更新 话题|全部 [指引]  马上看一眼有没有新东西，有就补
- /知识库 收录 词                把待审区的词收进来（等于 /学习 这个词）
- /知识库 删除 话题

都只在开发者私聊或全是开发者的群里能用；结果她先用人设说两句再给摘要（backstage.present）。
"""

from __future__ import annotations

import asyncio
import time

import backstage
import devs
import knowledge
import nonebot
from bot_guard import is_our_bot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.log import logger
from nonebot.params import CommandArg
from persona_rules import fuzzy_when

learn_cmd = on_command("学习", priority=17, block=True)
kb_cmd = on_command("知识库", priority=17, block=True)

_tasks: set[asyncio.Task] = set()


def _keep(coro) -> None:
    # 留引用，免得任务被回收
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _allowed(bot: Bot, event: MessageEvent) -> bool:
    return is_our_bot(event) and devs.is_dev(event.get_user_id()) and await backstage.devs_only(bot, event)


def _summary(name: str, done: dict) -> str:
    if done.get("error"):
        return f"「{name}」没学成：{done['error']}"
    if done.get("changed") is False:
        return f"「{name}」看了一眼最新消息，没什么新东西"
    lines = [f"话题：{name}"]
    if done.get("items"):
        lines.append("查了这些：" + "、".join(done["items"]))
    lines.append(f"新记 {done.get('add', 0)} 条、更新 {done.get('update', 0)} 条、重复 {done.get('dup', 0)} 条，"
                 f"现在一共 {done.get('cards', 0)} 条")
    if done.get("short"):
        lines.append("今天的搜索额度用完了，没查全，明天再更新一次")
    return "\n".join(lines)


async def _run(bot: Bot, event: MessageEvent, name: str, job) -> None:
    try:
        done = await job
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"knowledge: 学「{name}」出错 {type(exc).__name__}: {exc}")
        done = {"error": f"{type(exc).__name__}"}
    logger.info(f"knowledge: 「{name}」{done}")
    await backstage.present(bot, event, f"学「{name}」的结果", _summary(name, done))


def _start(bot: Bot, event: MessageEvent, name: str, job) -> str:
    if knowledge.busy():
        job.close()
        return "还在学上一个，等我弄完"
    _keep(_run(bot, event, name, job))
    return f"好，我去弄懂「{name}」，弄完跟你说"


@learn_cmd.handle()
async def _learn(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not await _allowed(bot, event):
        return
    text = arg.extract_plain_text().strip()
    if not text:
        await learn_cmd.finish("用法：/学习 话题 [指引]，比如 /学习 影之诗 看看最新环境和主流卡组")
    name, _, hint = text.partition(" ")
    await learn_cmd.finish(_start(bot, event, name, knowledge.learn(name, hint.strip())))


@kb_cmd.handle()
async def _kb(bot: Bot, event: MessageEvent, arg=CommandArg()) -> None:
    if not await _allowed(bot, event):
        return
    words = arg.extract_plain_text().strip().split(maxsplit=2)
    sub = words[0] if words else ""
    target = words[1] if len(words) > 1 else ""
    if sub == "删除" and target:
        await kb_cmd.finish(f"「{target}」忘掉了" if knowledge.delete(target) else f"本来就不懂「{target}」")
    if sub == "收录" and target:
        knowledge.drop_query(target)
        await kb_cmd.finish(_start(bot, event, target, knowledge.learn(target)))
    if sub == "更新" and target:
        hint = words[2] if len(words) > 2 else ""
        names = [t["name"] for t in knowledge.topics()] if target == "全部" else [target]
        if not names or (target != "全部" and not knowledge.topic(target)):
            await kb_cmd.finish(f"还不懂「{target}」，先 /学习 {target}")

        async def _all():
            done: dict = {"add": 0, "update": 0, "dup": 0, "items": []}
            for n in names:
                one = await knowledge.learn(n, hint) if hint else await knowledge.check(n)
                for k in ("add", "update", "dup"):
                    done[k] += one.get(k, 0)
                done["items"] += [f"{n}·{i}" for i in one.get("items", [])]
                done["cards"] = sum(t["cards"] for t in knowledge.topics() if t["name"] in names)
                done["short"] = done.get("short") or one.get("short")
            if not done["items"] and not hint:
                done["changed"] = False
            return done

        await kb_cmd.finish(_start(bot, event, target, _all()))
    now = time.time()
    rows = knowledge.topics()
    lines = [f"{t['name']}：{t['cards']} 条，{fuzzy_when(now - t['updated'])}更新，{fuzzy_when(now - t['checked'])}检查过"
             for t in rows] or ["还没学过什么"]
    waiting = knowledge.waiting()
    if waiting:
        lines.append("待审（聊天时常查的，/知识库 收录 词）：" + "、".join(f"{q}（{n} 次）" for q, n in waiting))
    lines.append(f"今天录入用了 {knowledge.spent_today()} / {knowledge.DAILY_MAX} 次搜索")
    await backstage.present(bot, event, "知识库", "\n".join(lines))


async def _weekly() -> None:
    """每小时看一下有没有该检查的话题，一次只查一个，免得一下子把额度用光。"""
    await asyncio.sleep(300)
    while True:
        try:
            names = knowledge.due_checks()
            if names and not knowledge.busy():
                done = await knowledge.check(names[0])
                logger.info(f"knowledge: 每周检查「{names[0]}」{done}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"knowledge: 每周检查出错 {type(exc).__name__}: {exc}")
        await asyncio.sleep(3600)


@nonebot.get_driver().on_startup
async def _start_weekly() -> None:
    _keep(_weekly())
