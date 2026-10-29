r"""SnowLuma -> NoneBot2 最小入口（反向 WebSocket 模式）。

NoneBot2 在这里作为 WS 服务端，监听 HOST:PORT，路径 /onebot/v11/ws；
SnowLuma 通过 config/onebot_<uin>.json 的 wsClients 主动连过来。

后台运行：scripts\启动全部.ps1；前台调试：scripts\run-nonebot.ps1（端口 18080）
SnowLuma 连的 URL：ws://127.0.0.1:18080/onebot/v11/ws

人设插件的配置（BOT_UIN / LLM_* / REPLY_*）和反向 WS 的 ONEBOT_ACCESS_TOKEN 放在同目录的 persona.env，
必须在加载插件之前读进环境变量，否则插件导入时就取不到值。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).with_name("persona.env"))
# 自己长期要保留的调参写 persona.local.env：后读、盖过 persona.env（一键更新会按样例重写 persona.env，不碰它）
load_dotenv(dotenv_path=Path(__file__).with_name("persona.local.env"), override=True)

# 插件数据（Bison 的订阅库、B 站 cookie 都在 data.db 里）默认写在 %LOCALAPPDATA%\nonebot2，
# 换机器或备份仓库时会漏掉。统一挪到仓库的 bot/data/localstore 下，跟着仓库走。
os.environ.setdefault("LOCALSTORE_DATA_DIR", str(Path(__file__).resolve().parent / "data" / "localstore"))
_LOCALSTORE_DATA = Path(os.environ["LOCALSTORE_DATA_DIR"])
_OLD_LOCALSTORE = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "nonebot2"
# htmlrender 的浏览器（一百多兆）继续放旧位置当缓存，不塞进仓库、也不用重下
os.environ.setdefault("RENDER_STORAGE_PATH", str(_OLD_LOCALSTORE / "nonebot_plugin_htmlrender"))
# 第一次套用这个改动时，把旧位置的数据搬过来（只搬数据，缓存和浏览器不动）；出错等 nonebot 起来再记日志
_MIGRATE_ERRORS: list[str] = []
if _OLD_LOCALSTORE.is_dir() and not (_LOCALSTORE_DATA / "data.db").exists():
    import shutil

    _LOCALSTORE_DATA.mkdir(parents=True, exist_ok=True)
    for _item in _OLD_LOCALSTORE.iterdir():
        if _item.name in ("Cache", "nonebot_plugin_parser", "nonebot_plugin_htmlrender"):
            continue
        _dst = _LOCALSTORE_DATA / _item.name
        try:
            if _item.is_dir():
                shutil.copytree(_item, _dst, dirs_exist_ok=True)
            else:
                # 先拷成临时名再改名：拷到一半失败不会留下半截 data.db，下次启动还会重搬
                _tmp = _dst.with_name(_dst.name + ".part")
                shutil.copy2(_item, _tmp)
                os.replace(_tmp, _dst)
        except Exception as _exc:  # noqa: BLE001
            _MIGRATE_ERRORS.append(f"{_item.name}（{type(_exc).__name__}: {_exc}）")
# NoneBot 按当前工作目录找 .env 和 load_plugins 的目录：切到本文件所在目录，
# 和 run-nonebot.ps1 的 Set-Location 一致，从仓库根目录直接启动也能加载插件
os.chdir(Path(__file__).resolve().parent)

from devs import DEVS  # noqa: E402

import nonebot  # noqa: E402
from nonebot.adapters.onebot.v11 import Adapter  # noqa: E402

nonebot.init(
    host=os.getenv("HOST", "127.0.0.1"),
    port=int(os.getenv("PORT", "18080")),
    # NoneBot 只从自己的 .env 读插件自定义配置，persona.env 里的早柚核心连接项要显式传进去
    **{k.lower(): v for k, v in os.environ.items() if k.upper().startswith("GSUID_CORE_")},
    # Bison（B 站订阅）：卡片图要浏览器渲染；群里必须 @ 它才认指令，免得被闲聊词误触
    bison_use_browser=True,
    bison_to_me=True,
    # 一条推送拆成好几条（文字 + 几张图）时合并转发成一条，群里和私聊都是；视频、直播本来就一条（bili_push.py）
    bison_use_pic_merge=2,
    # htmlrender 0.7 起渲染后端要显式选，不配只警告、卡片图全出不来
    render_backend="playwright",
    # 开发者才能加/删 cookie、用 /群管理、/后台管理
    superusers=set(DEVS),
)

driver = nonebot.get_driver()
driver.register_adapter(Adapter)

if _MIGRATE_ERRORS:
    nonebot.logger.warning(f"旧插件数据没搬全，订阅库可能是空的，请手动从 {_OLD_LOCALSTORE} 拷到 {_LOCALSTORE_DATA}：" + "；".join(_MIGRATE_ERRORS))

# 账号守卫：SnowLuma 可能同时登录多个 QQ 账号（实测 100000002 与 100000001 同时在线），
# 只有 BOT_UIN 这个号的事件才往下走。用全局 event_preprocessor，在任何 matcher（含解析插件）之前拦截。
from nonebot.exception import IgnoredException  # noqa: E402
from nonebot.message import event_preprocessor  # noqa: E402

_BOT_UIN = os.getenv("BOT_UIN", "").strip()
if not _BOT_UIN:
    nonebot.logger.warning("未配置 BOT_UIN：所有连上来的 QQ 账号都会回话")


@event_preprocessor
async def _only_bot_account(bot, event, state) -> None:
    if _BOT_UIN and str(getattr(event, "self_id", "")) != _BOT_UIN:
        raise IgnoredException(f"非机器人账号 {getattr(event, 'self_id', '?')} 的事件")


# 第三方解析插件要先加载，后面的 plugins 里有针对它的行为调优（只发视频不发封面）
try:
    nonebot.load_plugin("nonebot_plugin_parser")
except Exception as exc:  # noqa: BLE001
    nonebot.logger.warning(f"B站解析插件加载失败 {type(exc).__name__}: {exc}")

# B 站动态/直播/番剧订阅推送（Bison）：自带 /添加订阅、/查询订阅、/群管理 等指令和卡片主题；
# 它 import 期就依赖 playwright，没装会抛 ModuleNotFoundError，这里降级成只记一条警告
try:
    nonebot.load_plugin("nonebot_bison")
except Exception as exc:  # noqa: BLE001
    nonebot.logger.warning(f"Bison 订阅插件加载失败 {type(exc).__name__}: {exc}")

# Bison 默认查开播比查动态勤（开播 5 秒、动态 60 秒）。开播提醒和动态一起推的时候，
# 5 秒一查既浪费请求、又容易和动态那条前后脚重复；统一成跟动态一样的间隔，
# 想改就用 BISON_LIVE_INTERVAL_SECONDS（秒）覆盖。
try:
    from nonebot_bison.platform.bilibili.scheduler import BililiveSite

    _live_interval = int(os.getenv("BISON_LIVE_INTERVAL_SECONDS", "60"))
    BililiveSite.schedule_setting = {"seconds": _live_interval}
    nonebot.logger.info(f"Bison 开播轮询间隔改成 {_live_interval} 秒（与动态一致）")
except Exception as exc:  # noqa: BLE001
    nonebot.logger.warning(f"Bison 开播轮询间隔没改成 {type(exc).__name__}: {exc}")

# Bison 的推送走 send-anything-anywhere 的「自动挑一个 bot」：SnowLuma 同时挂着两个号时，
# 它可能挑到开发者自己的号发出去。这里把非 BOT_UIN 的号从它的候选缓存里挡掉，
# 保证推送只用机器人本号发。
if _BOT_UIN:
    try:
        import nonebot_plugin_saa.auto_select_bot as _saa_auto

        # 改的是 saa 的内部函数（requirements.txt 钉了 0.7.x）；升级后没了这个名字就大声报错，别悄悄失效
        _saa_refresh = _saa_auto._refresh_bot

        async def _only_bot_refresh(bot):
            if str(getattr(bot, "self_id", "")) != _BOT_UIN:
                return
            await _saa_refresh(bot)

        _saa_auto._refresh_bot = _only_bot_refresh
    except Exception as exc:  # noqa: BLE001
        nonebot.logger.error(f"固定推送账号失败，推送可能从别的号发出去 {type(exc).__name__}: {exc}")

# 早柚核心连接插件：把消息转给另起的核心进程（游戏查询，插件列表见 external.lock.json），核心没开也不影响人设
try:
    nonebot.load_plugin("GenshinUID")
except Exception as exc:  # noqa: BLE001
    nonebot.logger.warning(f"早柚核心连接插件加载失败 {type(exc).__name__}: {exc}")

# 插件目录：bot/plugins（上面已切到 bot/）
nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run()
