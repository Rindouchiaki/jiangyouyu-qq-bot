"""bison_guard 的离线测试：412 / 网络抖动判定 + 冷却窗口。"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
guard = importlib.import_module("bison_guard")


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeHTTPStatusError(Exception):
    def __init__(self, status_code):
        self.response = FakeResponse(status_code)


class ConnectError(Exception):
    pass


class _Opaque(Exception):
    pass


def main() -> int:
    assert guard.exc_status(FakeHTTPStatusError(412)) == 412
    assert guard.exc_status(_Opaque()) == 0
    assert guard.is_rate_limited(FakeHTTPStatusError(412)) is True
    assert guard.is_rate_limited(FakeHTTPStatusError(403)) is False
    assert guard.is_transient(FakeHTTPStatusError(412)) is True
    assert guard.is_transient(ConnectError()) is True
    assert guard.is_transient(_Opaque()) is False
    assert guard.is_transient(FakeHTTPStatusError(500)) is False
    assert guard.retry_once(ConnectError()) is True
    assert guard.retry_once(FakeHTTPStatusError(412)) is False
    assert guard.retry_once(FakeHTTPStatusError(500)) is False

    cd = guard.Cooldown(300)
    assert cd.active(1000.0) is False
    cd.trip(1000.0)
    assert cd.active(1000.0) is True
    assert cd.active(1299.0) is True
    assert cd.active(1300.0) is False
    assert cd.remaining(1000.0) == 300
    assert cd.remaining(1250.5) == 49
    assert cd.remaining(1500.0) == 0
    cd.reset()
    assert cd.active(1000.0) is False

    print("test_bison_guard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
