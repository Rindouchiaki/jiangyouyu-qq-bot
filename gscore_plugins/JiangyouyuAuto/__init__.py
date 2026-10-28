"""酱油鱼自用的早柚核心插件：在机器人登记过账号（登录过）的人，每天自动在社区领签到奖励。

- 鸣潮（RoverSign）、终末地（EndUID）自带「全部开启签到」SigninMaster：启动时打开，有登录的账号都签；
- 米哈游系（原神 / 星铁 / 绝区零 / 崩坏3）的插件只签订阅了「[游戏] 自动签到」的 UID：
  每小时给有 Cookie 的 UID 补上订阅（按私聊记、不往群里发），新登录的人当晚就能签上。
- 各插件的定时签到打开、私聊签到报告关掉：SnowLuma 主动私聊没加好友的人发不出去，静默领取就好，
  想看结果的人自己发「gs签到」等。
- 登录态自动续：米哈游系每天 0:13（签到前）用扫码存下的 Stoken 换新 Cookie（等于每人自动发一次「刷新CK」）；
  终末地每天 2:43 给凭证失效的账号用扫码存下的登录 token 重新换 cred。鸣潮的短期令牌插件自己会续。

一键部署把本目录拷进核心的 plugins；本目录按 GPL-3.0 发布（运行在 GPL-3.0 的早柚核心里），见 LICENSE。
"""

from __future__ import annotations

import asyncio
import random
import sys
from typing import Any, Dict, Optional

from gsuid_core.aps import scheduler
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.server import on_core_start_before
from gsuid_core.subscribe import gs_subscribe
from gsuid_core.utils.cookie_manager.add_ck import refresh_ck_by_uid_list
from gsuid_core.utils.database.models import GsUser
from gsuid_core.utils.plugins_config.gs_config import all_config_list

# 插件配置名 -> 要设的值；插件没装就跳过
CONFIGS: Dict[str, Dict[str, Any]] = {
    "GenshinUID": {"SchedSignin": True, "PrivateSignReport": False},
    "StarRailUID": {"SchedSignin": True, "PrivateSignReport": False},
    "ZZZeroUID": {"SchedSignin": True, "PrivateSignReport": False},
    "BBBUID": {"SchedSignin": True, "PrivateSignReport": False},
    "RoverSign": {
        "SigninMaster": True,
        "SchedSignin": True,
        "PrivateSignReport": False,
        # 别只签最近用过机器人的人
        "SignActiveUserOnly": False,
        "SigninMasterSkipInactive": False,
    },
    "EndUID": {"SigninMaster": True, "SchedSignin": True, "PrivateSignReport": False},
}
# 米哈游系：GsUser 上的 UID 字段 -> 插件签到用的订阅名（字段顺序也是刷新 Cookie 时挑 UID 的顺序）
MIHOYO_SIGN = {
    "uid": "[原神] 自动签到",
    "sr_uid": "[星铁] 自动签到",
    "zzz_uid": "[绝区零] 自动签到",
    "bbb_uid": "[崩坏3] 自动签到",
}


def apply_configs() -> list[str]:
    changed = []
    for name, values in CONFIGS.items():
        config = all_config_list.get(name)
        if config is None:
            continue
        for key, value in values.items():
            try:
                if config.get_config(key).data != value and config.set_config(key, value):
                    changed.append(f"{name}.{key}={value}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[酱油鱼·自动签到] 设置 {name}.{key} 失败：{exc}")
    return changed


def patch_loaded_report_flags() -> None:
    """米哈游系插件在导入时就把 PrivateSignReport 读进模块变量，改配置要重启才生效；
    刚装好的第一晚（崩坏3 默认开）会私聊每个人，所以把已加载模块里的值也改掉。"""
    for module in list(sys.modules.values()):
        # 核心按 plugins.BBBUID.BBBUID.bbb_sign 这样的名字导入插件
        parts = (getattr(module, "__name__", "") or "").split(".")
        package = next((p for p in parts if p in CONFIGS), "")
        if CONFIGS.get(package, {}).get("PrivateSignReport") is not False:
            continue
        for attr in ("IS_REPORT", "IS_REPORT_PRIVATE"):
            if getattr(module, attr, False) is True:
                setattr(module, attr, False)
                logger.info(f"[酱油鱼·自动签到] 已关掉 {module.__name__}.{attr}")


def ensure_end_job() -> None:
    """终末地导入时 SchedSignin 还没开就不注册定时签到，刚装好要补注册一次。"""
    if scheduler.get_job("end_sign_0") is not None:
        return
    for name, module in list(sys.modules.items()):
        if name.endswith("EndUID.end_sign") and hasattr(module, "setup_scheduler"):
            module.setup_scheduler()
            return


async def ensure_mihoyo_subscriptions() -> int:
    """给每个有 Cookie 的米哈游系 UID 补上自动签到订阅，返回新加的条数。"""
    added = 0
    for user in await GsUser.get_all_user():
        for field, task in MIHOYO_SIGN.items():
            uid = getattr(user, field, None)
            if not uid or await gs_subscribe.get_subscribe(task, uid=uid):
                continue
            # 按私聊记：签到不看订阅里的会话，私聊报告又关了，所以不会往哪里发消息
            event = Event(bot_id=user.bot_id, user_id=user.user_id, user_type="direct")
            await gs_subscribe.add_subscribe("single", task, event, uid=uid)
            added += 1
    return added


def loaded_module(suffix: str) -> Optional[Any]:
    """按名字结尾找已加载的插件模块（核心按 plugins.EndUID.EndUID.xxx 导入）；插件没装返回 None。"""
    return next((m for n, m in list(sys.modules.items()) if n.endswith(suffix)), None)


async def refresh_mihoyo_cookies() -> None:
    """用 Stoken 给每个米游社账号换新 Cookie；Stoken 也失效的只能重新扫码。"""
    ok = failed = 0
    for user in await GsUser.get_all_user():
        if not user.stoken:
            continue
        # 同一个米游社账号的 UID 共用 Stoken，挑一个就行；game_name 对应核心的列名前缀，原神是 None
        field = next((f for f in MIHOYO_SIGN if getattr(user, f, None)), None)
        if field is None:
            continue
        game = None if field == "uid" else field.split("_")[0]
        try:
            im = await refresh_ck_by_uid_list(user.bot_id, {getattr(user, field): user.user_id}, game)
        except Exception as exc:  # noqa: BLE001
            im = str(exc)
        if "成功刷新CK1" in im:
            ok += 1
        else:
            failed += 1
            logger.warning(f"[酱油鱼·续登录] 米游社 {user.user_id} 刷新 Cookie 失败：{im}")
        await asyncio.sleep(random.uniform(1, 3))
    logger.info(f"[酱油鱼·续登录] 米游社 Cookie 刷新完成：成功 {ok}，失败 {failed}")


async def refresh_end_creds() -> None:
    """终末地 cred 失效后插件只标「无效」，这里用扫码时存的登录 token 重新换一个。"""
    models, api = loaded_module("EndUID.utils.database.models"), loaded_module("EndUID.utils.api.requests")
    if models is None or api is None:
        return
    ok = failed = 0
    for user in await models.EndUser.get_all_data() or []:
        if user.cookie_status != "无效" or not user.hg_token:
            continue
        info = await api.end_api.get_cred_info_by_token(user.hg_token)
        cred = info.get("cred") if isinstance(info, dict) else None
        if cred:
            await models.EndUser.update_data_by_uid(user.uid, user.bot_id, cookie=cred, cookie_status="")
            ok += 1
        else:
            failed += 1
        await asyncio.sleep(random.uniform(1, 3))
    if ok or failed:
        logger.info(f"[酱油鱼·续登录] 终末地重新换 cred：成功 {ok}，失败 {failed}（失败的要重新 zmd扫码登录）")


async def sync() -> None:
    try:
        changed = apply_configs()
        patch_loaded_report_flags()
        ensure_end_job()
        added = await ensure_mihoyo_subscriptions()
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[酱油鱼·自动签到] 同步失败：{exc}")
        return
    if changed or added:
        logger.info(f"[酱油鱼·自动签到] 配置 {'、'.join(changed) or '无变化'}；新开自动签到 {added} 个 UID")


# 放在「启动前」：普通启动钩子按优先级排队，前面的资源下载慢或报错会把这里拖晚甚至跳过
@on_core_start_before(priority=90)
async def _on_start() -> None:
    await sync()


@scheduler.scheduled_job("cron", minute=7, id="jiangyouyu_auto_sign_sync")
async def _hourly() -> None:
    await sync()


# 米哈游系最早 0:38 签到
@scheduler.scheduled_job("cron", hour=0, minute=13, id="jiangyouyu_refresh_mihoyo")
async def _refresh_mihoyo() -> None:
    try:
        await refresh_mihoyo_cookies()
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[酱油鱼·续登录] 米游社刷新 Cookie 失败：{exc}")


# 终末地 3:00 签到
@scheduler.scheduled_job("cron", hour=2, minute=43, id="jiangyouyu_refresh_end")
async def _refresh_end() -> None:
    try:
        await refresh_end_creds()
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[酱油鱼·续登录] 终末地换 cred 失败：{exc}")
