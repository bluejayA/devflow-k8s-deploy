"""SEC 규칙 — SEC-001~009."""

from __future__ import annotations

import re
from typing import Any

from scripts._shared.types import CheckResult
from scripts.validators.registry import register_rule

_VALID_SECCOMP_TYPES: frozenset[str] = frozenset(["RuntimeDefault", "Localhost"])
_SECRET_NAME_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|apikey|auth[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)


@register_rule("container")
def rule_sec001(
    c: dict[str, Any], *, pod_sc: dict[str, Any] | None = None, **_: Any
) -> list[CheckResult]:
    """SEC-001: runAsNonRoot: true 필수 (Pod 또는 container securityContext)."""
    name = str(c.get("name", "unknown"))
    container_sc = c.get("securityContext", {})
    value = container_sc.get("runAsNonRoot")
    if value is None and pod_sc:
        value = pod_sc.get("runAsNonRoot")
    if value is True:
        return [
            CheckResult(
                rule_id="SEC-001",
                level="PASS",
                container=name,
                message_ko="runAsNonRoot가 true로 설정되어 있습니다.",
                message_en="runAsNonRoot is set to true.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="SEC-001",
            level="FAIL",
            container=name,
            message_ko="runAsNonRoot 미설정",
            message_en="runAsNonRoot is not set or is false.",
            suggestion=(
                "spec.securityContext.runAsNonRoot: true 추가. "
                "미설정 시 컨테이너 탈출 공격 시 호스트 root 권한 획득 가능"
            ),
        )
    ]


@register_rule("container")
def rule_sec002(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SEC-002: privileged: true 금지 (false 또는 미설정)."""
    name = str(c.get("name", "unknown"))
    sc = c.get("securityContext", {})
    if sc.get("privileged") is True:
        return [
            CheckResult(
                rule_id="SEC-002",
                level="FAIL",
                container=name,
                message_ko="privileged: true 설정 금지",
                message_en="privileged: true is not allowed.",
                suggestion=(
                    "securityContext.privileged: true 를 제거하세요. "
                    "privileged 컨테이너는 호스트 커널에 무제한 접근이 가능합니다."
                ),
            )
        ]
    return [
        CheckResult(
            rule_id="SEC-002",
            level="PASS",
            container=name,
            message_ko="privileged 모드가 비활성화되어 있습니다.",
            message_en="privileged mode is disabled.",
            suggestion="",
        )
    ]


@register_rule("container")
def rule_sec003(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SEC-003: allowPrivilegeEscalation: false 필수."""
    name = str(c.get("name", "unknown"))
    sc = c.get("securityContext", {})
    val = sc.get("allowPrivilegeEscalation")
    if val is False:
        return [
            CheckResult(
                rule_id="SEC-003",
                level="PASS",
                container=name,
                message_ko="allowPrivilegeEscalation이 false로 설정되어 있습니다.",
                message_en="allowPrivilegeEscalation is set to false.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="SEC-003",
            level="FAIL",
            container=name,
            message_ko=f"allowPrivilegeEscalation 미설정 (현재: {val!r})",
            message_en=f"allowPrivilegeEscalation is not false (current: {val!r}).",
            suggestion=(
                "securityContext.allowPrivilegeEscalation: false 를 추가하세요. "
                "setuid 바이너리를 통한 권한 상승이 가능해집니다."
            ),
        )
    ]


@register_rule("container")
def rule_sec004(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SEC-004: readOnlyRootFilesystem: true 필수."""
    name = str(c.get("name", "unknown"))
    sc = c.get("securityContext", {})
    if sc.get("readOnlyRootFilesystem") is True:
        return [
            CheckResult(
                rule_id="SEC-004",
                level="PASS",
                container=name,
                message_ko="readOnlyRootFilesystem이 true로 설정되어 있습니다.",
                message_en="readOnlyRootFilesystem is set to true.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="SEC-004",
            level="FAIL",
            container=name,
            message_ko="readOnlyRootFilesystem 미설정",
            message_en="readOnlyRootFilesystem is not set to true.",
            suggestion=(
                "securityContext.readOnlyRootFilesystem: true 를 추가하세요. "
                "쓰기 가능한 루트 파일시스템은 악성코드 주입 경로가 됩니다."
            ),
        )
    ]


@register_rule("container")
def rule_sec005(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SEC-005: capabilities.drop에 ALL 포함 필수."""
    name = str(c.get("name", "unknown"))
    sc = c.get("securityContext", {})
    caps = sc.get("capabilities", {})
    drop = [str(x).upper() for x in caps.get("drop", [])]
    if "ALL" in drop:
        return [
            CheckResult(
                rule_id="SEC-005",
                level="PASS",
                container=name,
                message_ko="capabilities.drop에 ALL이 포함되어 있습니다.",
                message_en="capabilities.drop includes ALL.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="SEC-005",
            level="FAIL",
            container=name,
            message_ko="capabilities.drop에 ALL 미포함",
            message_en="capabilities.drop does not include ALL.",
            suggestion=(
                "securityContext.capabilities.drop: [ALL] 을 추가하세요. "
                "불필요한 Linux capability를 모두 제거해야 공격 표면이 최소화됩니다."
            ),
        )
    ]


@register_rule("pod_spec")
def rule_sec006(pod_spec: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SEC-006: Pod securityContext.seccompProfile.type 검증."""
    pod_sc = pod_spec.get("securityContext", {})
    seccomp = pod_sc.get("seccompProfile", {})
    seccomp_type = seccomp.get("type")
    if seccomp_type in _VALID_SECCOMP_TYPES:
        return [
            CheckResult(
                rule_id="SEC-006",
                level="PASS",
                container="(pod)",
                message_ko=f"seccompProfile.type이 {seccomp_type!r}으로 설정되어 있습니다.",
                message_en=f"seccompProfile.type is set to {seccomp_type!r}.",
                suggestion="",
            )
        ]
    return [
        CheckResult(
            rule_id="SEC-006",
            level="FAIL",
            container="(pod)",
            message_ko=(
                f"seccompProfile.type 미설정 또는 잘못된 값 (현재: {seccomp_type!r})"
            ),
            message_en=(
                f"seccompProfile.type is invalid (current: {seccomp_type!r})."
            ),
            suggestion=(
                "spec.securityContext.seccompProfile.type: RuntimeDefault"
                " 또는 Localhost 를 설정하세요. "
                "seccomp 프로파일 없이는 컨테이너가 모든 syscall을 호출할 수 있습니다."
            ),
        )
    ]


@register_rule("container")
def rule_sec007(
    c: dict[str, Any], *, pod_sc: dict[str, Any] | None = None, **_: Any
) -> list[CheckResult]:
    """SEC-007: runAsUser > 0 필수 (root=0 금지). Pod 또는 container securityContext."""
    name = str(c.get("name", "unknown"))
    container_sc = c.get("securityContext", {})
    run_as_user = container_sc.get("runAsUser")
    if run_as_user is None and pod_sc:
        run_as_user = pod_sc.get("runAsUser")
    if run_as_user is not None:
        try:
            run_as_user_int = int(run_as_user)
        except (ValueError, TypeError):
            return [
                CheckResult(
                    rule_id="SEC-007",
                    level="FAIL",
                    container=name,
                    message_ko=f"runAsUser 값이 정수가 아님: {run_as_user!r}",
                    message_en=f"runAsUser is not a valid integer: {run_as_user!r}",
                    suggestion="runAsUser: 1000 같은 양의 정수를 지정하세요.",
                )
            ]
        if run_as_user_int > 0:
            return [
                CheckResult(
                    rule_id="SEC-007",
                    level="PASS",
                    container=name,
                    message_ko=f"runAsUser가 {run_as_user}으로 설정되어 있습니다.",
                    message_en=f"runAsUser is set to {run_as_user}.",
                    suggestion="",
                )
            ]
    return [
        CheckResult(
            rule_id="SEC-007",
            level="FAIL",
            container=name,
            message_ko=(
                f"runAsUser 미설정 또는 root(0) (현재: {run_as_user!r})"
            ),
            message_en=(
                f"runAsUser is not set or is 0 (root) (current: {run_as_user!r})."
            ),
            suggestion=(
                "securityContext.runAsUser 를 1 이상으로 설정하세요. "
                "runAsUser=0은 root 실행이며 컨테이너 탈출 시 호스트 침해 위험이 있습니다."
            ),
        )
    ]


@register_rule("pod_spec")
def rule_sec008(pod_spec: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SEC-008: fsGroup > 0 필수 (root 그룹 금지). Pod securityContext."""
    pod_sc = pod_spec.get("securityContext", {})
    fs_group = pod_sc.get("fsGroup")
    if fs_group is not None:
        try:
            fs_group_int = int(fs_group)
        except (ValueError, TypeError):
            return [
                CheckResult(
                    rule_id="SEC-008",
                    level="FAIL",
                    container="(pod)",
                    message_ko=f"fsGroup 값이 정수가 아님: {fs_group!r}",
                    message_en=f"fsGroup is not a valid integer: {fs_group!r}",
                    suggestion="fsGroup: 1000 같은 양의 정수를 지정하세요.",
                )
            ]
        if fs_group_int > 0:
            return [
                CheckResult(
                    rule_id="SEC-008",
                    level="PASS",
                    container="(pod)",
                    message_ko=f"fsGroup이 {fs_group}으로 설정되어 있습니다.",
                    message_en=f"fsGroup is set to {fs_group}.",
                    suggestion="",
                )
            ]
    return [
        CheckResult(
            rule_id="SEC-008",
            level="FAIL",
            container="(pod)",
            message_ko=(
                f"fsGroup 미설정 또는 root(0) (현재: {fs_group!r})"
            ),
            message_en=(
                f"fsGroup is not set or is 0 (root group) (current: {fs_group!r})."
            ),
            suggestion=(
                "spec.securityContext.fsGroup 을 1 이상의 값으로 설정하세요. "
                "fsGroup=0은 root 그룹으로 볼륨에 접근함을 의미합니다."
            ),
        )
    ]


@register_rule("container")
def rule_sec009(c: dict[str, Any], **_: Any) -> list[CheckResult]:
    """SEC-009: 환경변수에 평문 시크릿 탐지 (F-46a)."""
    name = str(c.get("name", "unknown"))
    env_list: list[dict[str, Any]] = c.get("env", [])
    results: list[CheckResult] = []
    for env in env_list:
        env_name = str(env.get("name", ""))
        if "valueFrom" in env:
            continue
        value = env.get("value")
        if value is None or not str(value):
            continue
        if _SECRET_NAME_RE.search(env_name):
            results.append(
                CheckResult(
                    rule_id="SEC-009",
                    level="FAIL",
                    container=name,
                    message_ko=(f"환경변수 {env_name!r}에 평문 시크릿 의심"),
                    message_en=(
                        f"Env var {env_name!r} may contain a plaintext secret."
                    ),
                    suggestion=(
                        f"env[{env_name!r}]에 valueFrom.secretKeyRef 사용 권장. "
                        "Kubernetes Secret 오브젝트에서 값을 참조하세요."
                    ),
                )
            )
    if not results:
        results.append(
            CheckResult(
                rule_id="SEC-009",
                level="PASS",
                container=name,
                message_ko="평문 시크릿이 감지되지 않았습니다.",
                message_en="No plaintext secrets detected.",
                suggestion="",
            )
        )
    return results
