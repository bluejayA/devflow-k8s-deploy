"""규칙 레지스트리 — @register_rule 데코레이터 + run_rules() 디스패처."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from scripts._shared.types import CheckResult

RuleScope = Literal["container", "pod_spec", "service", "statefulset", "manifest_set"]

_registry: dict[str, list[Callable[..., list[CheckResult]]]] = {
    "container": [],
    "pod_spec": [],
    "service": [],
    "statefulset": [],
    "manifest_set": [],
}


def register_rule(scope: RuleScope) -> Callable:
    """규칙 함수를 scope 레지스트리에 등록하는 데코레이터 팩토리."""

    def decorator(fn: Callable[..., list[CheckResult]]) -> Callable[..., list[CheckResult]]:
        _registry[scope].append(fn)
        return fn

    return decorator


def run_rules(scope: RuleScope, target: dict[str, Any], **kwargs: Any) -> list[CheckResult]:
    """등록된 모든 규칙을 순서대로 실행하고 결과를 합산."""
    results: list[CheckResult] = []
    for fn in _registry[scope]:
        results.extend(fn(target, **kwargs))
    return results
