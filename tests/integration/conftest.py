"""NFR-SEC-05 경계 allowlist 테스트 — autouse 가드.

tests/integration/ 하위 모든 테스트에서 subprocess.run을 자동 패치.
회귀 방지가 목적이므로 명시적 opt-in 대신 전역 autouse.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


class SubprocessSpy:
    """subprocess.run spy — argv/kwargs를 기록.

    conftest autouse 픽스처가 반환하는 공개 타입.
    테스트 파일에서 `from tests.integration.conftest import SubprocessSpy`로 import 가능.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> MagicMock:
        cmd = args[0] if args else kwargs.get("args")
        self.calls.append(
            {
                "cmd": cmd,
                "shell": kwargs.get("shell", False),
                "kwargs": kwargs,
            }
        )
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result


@pytest.fixture(autouse=True)
def subprocess_spy(monkeypatch: pytest.MonkeyPatch) -> SubprocessSpy:
    """subprocess.run 글로벌 패치 (모든 import 경로 커버)."""
    spy = SubprocessSpy()
    # Important 4: 글로벌 패치 — 모듈별 패치 불필요
    monkeypatch.setattr("subprocess.run", spy)
    return spy
