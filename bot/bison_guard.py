"""B 站动态列表被风控时的判定，纯逻辑，方便离线测试（不 import nonebot）。"""

# 冷却时长（秒）：命中后这段时间内不再请求，免得把短风控撞成长风控
COOLDOWN_DEFAULT = 300.0

# httpx 里「这一轮没结果、下一轮自然好」的异常名
TRANSIENT_NAMES = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "TimeoutException",
        "RemoteProtocolError",
        "ReadError",
        "WriteError",
        "NetworkError",
    }
)


def exc_status(exc: BaseException) -> int:
    """取异常的 HTTP 状态码，没有就 0。"""
    response = getattr(exc, "response", None)
    try:
        return int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def is_rate_limited(exc: BaseException) -> bool:
    """b 站风控：HTTP 412。"""
    return exc_status(exc) == 412


def is_transient(exc: BaseException) -> bool:
    """这一轮跳过就行：412 风控，或者连接/超时这类网络抖动。"""
    if is_rate_limited(exc):
        return True
    name = type(exc).__name__
    return name in TRANSIENT_NAMES or "Timeout" in name


def retry_once(exc: BaseException) -> bool:
    """网络抖动值得马上再试一次；412 是风控，重试只会撞得更狠。"""
    return is_transient(exc) and not is_rate_limited(exc)


class Cooldown:
    """命中后暂停一小会儿；冷却期内直接跳过，不去硬撞。"""

    def __init__(self, seconds: float = COOLDOWN_DEFAULT) -> None:
        self.seconds = float(seconds)
        self.until = 0.0

    def remaining(self, now: float) -> int:
        return max(0, int(self.until - now))

    def active(self, now: float) -> bool:
        return now < self.until

    def trip(self, now: float) -> None:
        self.until = now + self.seconds

    def reset(self) -> None:
        self.until = 0.0
