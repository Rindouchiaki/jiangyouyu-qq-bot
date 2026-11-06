"""给 APScheduler 里的几个任务放宽参数，免得「一次推送跑太久」把整轮调度挤掉。

两个警告的来源不同：

1. `Scheduler.exec_fetch ... skipped: maximum number of running instances reached (1)`
   Bison 的每个调度器都只注册一个 `exec_fetch`，默认 `max_instances=1`。
   番剧调度器是 30 秒一轮，而我们推送时要下载视频、截图、上传，
   一次发送偶尔超过 30 秒，下一轮就被判定「上一个还没跑完」直接跳过 ——
   那一轮的那条动态就晚一分钟才推。
   这里把 `max_instances` 放到 3，并开 `coalesce`，让下一轮能正常开工；
   轮转取任务用的是权重指针，两轮并发取到的不是同一个 target，不会重复推。

2. `Run time of job "repeat_connect" was missed by 0:00:01.7`
   早柚核心的重连任务每 10 秒一次，默认 `misfire_grace_time` 只有 1 秒，
   事件循环偶尔被同步 IO 卡一下（截图、PIL、写文件）就报「错过」。
   放宽到 60 秒 + `coalesce`，只补一次，不刷警告。

参数可用环境变量覆盖：
`BISON_MAX_INSTANCES`（默认 3）、`BISON_MISFIRE_GRACE`（默认 120）、
`JOB_MISFIRE_GRACE`（默认 60）。
"""

import os

from nonebot import get_driver
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

BISON_MAX_INSTANCES = int(os.getenv("BISON_MAX_INSTANCES", "3"))
BISON_MISFIRE_GRACE = int(os.getenv("BISON_MISFIRE_GRACE", "120"))
JOB_MISFIRE_GRACE = int(os.getenv("JOB_MISFIRE_GRACE", "60"))

driver = get_driver()


def _job_names(job) -> str:
    """把 id / name / 函数名拼起来，方便按函数名匹配（不同 APScheduler 版本 id 规则不一样）。"""
    func_name = getattr(getattr(job, "func", None), "__qualname__", "") or ""
    return " ".join(filter(None, [job.id or "", job.name or "", func_name]))


@driver.on_startup
async def _tune_jobs() -> None:
    bison_jobs = 0
    other_jobs = 0
    for job in scheduler.get_jobs():
        names = _job_names(job)
        if "exec_fetch" in names:
            job.max_instances = BISON_MAX_INSTANCES
            job.coalesce = True
            job.misfire_grace_time = BISON_MISFIRE_GRACE
            bison_jobs += 1
            logger.debug(f"scheduler_tuning: {names} → max_instances={BISON_MAX_INSTANCES} grace={BISON_MISFIRE_GRACE}s")
        elif "repeat_connect" in names:
            job.misfire_grace_time = JOB_MISFIRE_GRACE
            job.coalesce = True
            other_jobs += 1
            logger.debug(f"scheduler_tuning: {names} → grace={JOB_MISFIRE_GRACE}s")
    if bison_jobs or other_jobs:
        logger.info(
            f"scheduler_tuning: 已放宽 {bison_jobs} 个 Bison 调度（max_instances={BISON_MAX_INSTANCES}）"
            f"、{other_jobs} 个重连任务（grace={JOB_MISFIRE_GRACE}s）"
        )
    else:
        logger.debug("scheduler_tuning: 没有匹配到需要调整的任务")
