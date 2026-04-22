"""검증 헬퍼 유틸리티."""

from __future__ import annotations

import re
from typing import Any

_CPU_MILLI_RE = re.compile(r"^(\d+(?:\.\d+)?)(m?)$")


def _as_dict(value: object) -> dict[str, Any]:
    """dict이면 반환, 아니면(None/list/str 등) 빈 dict.

    .get() None-chain 방어: YAML spec: null처럼 명시적 null이 오면
    None이 반환되어 AttributeError 발생. 이를 빈 dict로 안전하게 처리.
    """
    return value if isinstance(value, dict) else {}


def _cpu_to_milli(value: str) -> int | None:
    """CPU 문자열을 millicores 정수로 변환. 파싱 불가 시 None."""
    m = _CPU_MILLI_RE.match(str(value).strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return int(num)
    return int(num * 1000)
