"""내장 기본 설정 사전 — 3계층 설정의 최하위 기본값.
ConfigLoader가 프로젝트/조직 설정 위에 이 값을 fallback으로 사용한다."""

import copy
from typing import Any

# ─── 내장 기본값 ───
# 주석: namespace=None — 'default' 자동 배정 금지 (F-70/F-71).
#       ConfigLoader.resolve_namespace()에서 프로젝트명 제안.

BUILTIN_DEFAULTS: dict[str, Any] = {
    "stack": "auto",
    "namespace": None,  # resolve_namespace에서 프로젝트명 제안. 'default' 자동 배정 금지
    "output": {
        "dir": "k8s-output",
        "on_exists": "prompt",  # prompt / overwrite / suffix
    },
    "build": {
        "engine": "skip",  # skip / auto / docker / podman / nerdctl
        "timeout_sec": 300,
    },
    "kubectl": {
        "dry_run": True,
    },
    "resource": {
        "hint": "medium",  # small / medium / large
    },
    "validation": {
        "skipped": [],  # --skipped 인자 기본값
    },
    "app": {
        "replicas": 2,  # spec.replicas 기본값 — 1 이상 필수
    },
}


def load_builtin_defaults() -> dict[str, Any]:
    """BUILTIN_DEFAULTS의 깊은 복사본을 반환.
    호출 측이 반환값을 수정해도 원본에 영향 없음."""
    return copy.deepcopy(BUILTIN_DEFAULTS)
