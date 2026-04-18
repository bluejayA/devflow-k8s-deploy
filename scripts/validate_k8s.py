"""K8s manifest 정적 검증기 (stack-agnostic).

CLI:
    validate_k8s.py [--json] [--skipped CHECK [CHECK ...]] PATH

Exit codes (F-42):
    0 — all PASS
    1 — FAIL 존재
    2 — FAIL 없음 + WARN 존재 (soft-success)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

import yaml

from scripts._shared.errors import MalformedManifestError
from scripts._shared.fileio import read_text_limited
from scripts._shared.types import CheckResult, ValidationReport

# ─── 위험 Capability 목록 (SEC-005) ──────────────────────────────────────────

_DANGEROUS_CAPS: frozenset[str] = frozenset(
    [
        "SYS_ADMIN",
        "NET_ADMIN",
        "SYS_PTRACE",
        "SYS_MODULE",
        "SYS_RAWIO",
        "SYS_BOOT",
        "SYS_TIME",
        "SYS_TTY_CONFIG",
        "NET_RAW",
        "IPC_LOCK",
        "LINUX_IMMUTABLE",
        "SYS_CHROOT",
        "MKNOD",
        "SETPCAP",
        "AUDIT_WRITE",
        "AUDIT_CONTROL",
        "MAC_OVERRIDE",
        "MAC_ADMIN",
        "SYSLOG",
        "WAKE_ALARM",
        "BLOCK_SUSPEND",
        "AUDIT_READ",
        "PERFMON",
        "BPF",
        "CHECKPOINT_RESTORE",
    ]
)

# 유효 seccompProfile type
_VALID_SECCOMP_TYPES: frozenset[str] = frozenset(["RuntimeDefault", "Localhost"])

# 시크릿 keyword 패턴 (환경변수 이름 기준, case-insensitive)
_SECRET_NAME_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|auth[_-]?key"
    r"|private[_-]?key|credential|apikey)",
    re.IGNORECASE,
)

# CPU 단위를 millicores(int)로 변환하기 위한 패턴
_CPU_MILLI_RE = re.compile(r"^(\d+(?:\.\d+)?)(m?)$")


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


def _compute_exit_code(counts: dict[str, int]) -> int:
    """counts 기반 exit code 산출 (F-42).

    Args:
        counts: {"pass": int, "warn": int, "fail": int}

    Returns:
        0 if no FAIL, no WARN  (all pass)
        1 if any FAIL
        2 if no FAIL, any WARN
    """
    if counts.get("fail", 0) > 0:
        return 1
    if counts.get("warn", 0) > 0:
        return 2
    return 0


def _safe_collect_file(path: Path) -> list[dict[str, Any]]:
    """파일에서 YAML document 목록을 안전하게 읽기. 실패 시 MalformedManifestError raise."""
    try:
        raw = read_text_limited(path)
        return list(yaml.safe_load_all(raw))
    except yaml.YAMLError as exc:
        raise MalformedManifestError(f"YAML 파싱 실패: {path}") from exc
    except Exception as exc:  # noqa: BLE001
        raise MalformedManifestError(f"파일 읽기 실패: {path}") from exc


# ─── K8sValidator ─────────────────────────────────────────────────────────────


class K8sValidator:
    """stack-agnostic Kubernetes manifest 정적 검증기.

    Args:
        skipped: CLI --skipped 로 전달된 식별자 목록 (결과에 영향 없이 pass-through).
    """

    def __init__(self, skipped: list[str] | None = None) -> None:
        self._skipped: list[str] = list(skipped) if skipped else []

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def validate(self, manifests: list[Path | str]) -> ValidationReport:
        """manifests 경로 목록(파일 또는 디렉토리)에 대해 모든 규칙 적용.

        Args:
            manifests: YAML 파일 경로 또는 디렉토리 경로 목록.

        Returns:
            ValidationReport (results, counts, exit_code, skipped).
        """
        results: list[CheckResult] = []

        for entry in manifests:
            path = Path(entry)
            if path.is_dir():
                yaml_files = sorted(
                    p
                    for p in path.rglob("*")
                    if p.suffix in (".yaml", ".yml") and p.is_file()
                )
                for yf in yaml_files:
                    results.extend(self._validate_file_safe(yf))
            else:
                results.extend(self._validate_file_safe(path))

        counts: dict[str, int] = {
            "pass": sum(1 for r in results if r.level == "PASS"),
            "warn": sum(1 for r in results if r.level == "WARN"),
            "fail": sum(1 for r in results if r.level == "FAIL"),
        }
        exit_code = _compute_exit_code(counts)

        return ValidationReport(
            results=results,
            counts=counts,  # type: ignore[arg-type]
            exit_code=exit_code,
            skipped=list(self._skipped),
        )

    def to_json(
        self,
        report: ValidationReport,
        skipped: list[str] | None = None,
    ) -> str:
        """summary.json validation 객체 호환 JSON 직렬화.

        Args:
            report: validate() 반환값.
            skipped: 추가 skipped 식별자. None이면 report.skipped 사용.

        Returns:
            JSON 문자열.
        """
        effective_skipped = skipped if skipped is not None else report.skipped

        return json.dumps(
            {
                "results": [
                    {
                        "rule_id": r.rule_id,
                        "level": r.level,
                        "container": r.container,
                        "message_ko": r.message_ko,
                        "message_en": r.message_en,
                        "suggestion": r.suggestion,
                    }
                    for r in report.results
                ],
                "counts": report.counts,
                "exit_code": report.exit_code,
                "skipped": effective_skipped,
            },
            ensure_ascii=False,
            indent=2,
        )

    # ── 파일 단위 처리 ────────────────────────────────────────────────────────

    def _validate_file_safe(self, path: Path) -> list[CheckResult]:
        """MalformedManifestError를 단일 FAIL CheckResult 로 변환하여 반환."""
        try:
            return self._validate_file(path)
        except MalformedManifestError as exc:
            return [
                CheckResult(
                    rule_id="PARSE-ERR",
                    level="FAIL",
                    container="(file)",
                    message_ko=f"YAML 파싱 실패: {exc}",
                    message_en=f"YAML parse error: {exc}",
                    suggestion="YAML 구문을 확인하세요.",
                )
            ]

    def _validate_file(self, path: Path) -> list[CheckResult]:
        """단일 YAML 파일 검증. 파싱 실패 시 MalformedManifestError raise."""
        docs = _safe_collect_file(path)
        results: list[CheckResult] = []
        for doc in docs:
            if doc is None:
                continue
            results.extend(self._validate_doc(doc))
        return results

    def _validate_doc(self, doc: dict[str, Any]) -> list[CheckResult]:
        """단일 YAML document 검증 (kind 기반 분기)."""
        kind = str(doc.get("kind", ""))
        results: list[CheckResult] = []

        if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
            results.extend(self._check_workload(doc))
        elif kind == "Pod":
            results.extend(self._check_pod_spec(doc.get("spec", {})))
        elif kind == "Service":
            results.extend(self._check_service(doc))

        return results

    # ── Workload 규칙 ──────────────────────────────────────────────────────────

    def _check_workload(self, doc: dict[str, Any]) -> list[CheckResult]:
        """Deployment / StatefulSet / DaemonSet 등 workload 규칙 전체 적용."""
        kind = str(doc.get("kind", ""))
        if kind == "CronJob":
            pod_spec: dict[str, Any] = (
                doc.get("spec", {})
                .get("jobTemplate", {})
                .get("spec", {})
                .get("template", {})
                .get("spec", {})
            )
        else:
            pod_spec = doc.get("spec", {}).get("template", {}).get("spec", {})

        return self._check_pod_spec(pod_spec)

    def _check_pod_spec(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """Pod spec 레벨 규칙 검증."""
        results: list[CheckResult] = []

        # Pod-level 규칙
        results.extend(self._rule_sec006(pod_spec))
        results.extend(self._rule_sec008(pod_spec))
        results.extend(self._rule_sa001(pod_spec))
        results.extend(self._rule_sa002(pod_spec))

        containers: list[dict[str, Any]] = pod_spec.get("containers", [])
        init_containers: list[dict[str, Any]] = pod_spec.get("initContainers", [])

        for container in containers + init_containers:
            results.extend(self._check_container(container))

        return results

    def _check_container(self, container: dict[str, Any]) -> list[CheckResult]:
        """컨테이너 레벨 규칙 전체 적용."""
        results: list[CheckResult] = []
        results.extend(self._rule_sec001(container))
        results.extend(self._rule_sec002(container))
        results.extend(self._rule_sec003(container))
        results.extend(self._rule_sec004(container))
        results.extend(self._rule_sec005(container))
        results.extend(self._rule_sec007(container))
        results.extend(self._rule_sec009(container))
        results.extend(self._rule_res001(container))
        results.extend(self._rule_res_w01(container))
        results.extend(self._rule_img001(container))
        results.extend(self._rule_img_w01(container))
        results.extend(self._rule_prb001(container))
        results.extend(self._rule_prb002(container))
        return results

    # ── SEC 규칙 ──────────────────────────────────────────────────────────────

    def _rule_sec001(self, c: dict[str, Any]) -> list[CheckResult]:
        """SEC-001: runAsNonRoot: true 필수."""
        name = str(c.get("name", "unknown"))
        sc = c.get("securityContext", {})
        if sc.get("runAsNonRoot") is True:
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
                message_ko=f"[{name}] runAsNonRoot가 설정되지 않았거나 false입니다.",
                message_en=f"[{name}] runAsNonRoot is not set or is false.",
                suggestion=(
                    "spec.securityContext.runAsNonRoot: true 를 추가하세요. "
                    "미설정 시 컨테이너 탈출 공격에서 호스트 root 권한 획득이 가능합니다."
                ),
            )
        ]

    def _rule_sec002(self, c: dict[str, Any]) -> list[CheckResult]:
        """SEC-002: readOnlyRootFilesystem: true 필수."""
        name = str(c.get("name", "unknown"))
        sc = c.get("securityContext", {})
        if sc.get("readOnlyRootFilesystem") is True:
            return [
                CheckResult(
                    rule_id="SEC-002",
                    level="PASS",
                    container=name,
                    message_ko="readOnlyRootFilesystem이 true로 설정되어 있습니다.",
                    message_en="readOnlyRootFilesystem is set to true.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="SEC-002",
                level="FAIL",
                container=name,
                message_ko=f"[{name}] readOnlyRootFilesystem이 true가 아닙니다.",
                message_en=f"[{name}] readOnlyRootFilesystem is not true.",
                suggestion=(
                    "securityContext.readOnlyRootFilesystem: true 를 추가하세요. "
                    "쓰기 가능한 루트 파일시스템은 악성코드 주입 경로가 됩니다."
                ),
            )
        ]

    def _rule_sec003(self, c: dict[str, Any]) -> list[CheckResult]:
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
                message_ko=f"[{name}] allowPrivilegeEscalation이 false가 아닙니다 (현재: {val!r}).",
                message_en=f"[{name}] allowPrivilegeEscalation is not false (current: {val!r}).",
                suggestion=(
                    "securityContext.allowPrivilegeEscalation: false 를 추가하세요. "
                    "setuid 바이너리를 통한 권한 상승이 가능해집니다."
                ),
            )
        ]

    def _rule_sec004(self, c: dict[str, Any]) -> list[CheckResult]:
        """SEC-004: capabilities.drop에 ALL 포함 필수."""
        name = str(c.get("name", "unknown"))
        sc = c.get("securityContext", {})
        caps = sc.get("capabilities", {})
        drop = [str(x).upper() for x in caps.get("drop", [])]
        if "ALL" in drop:
            return [
                CheckResult(
                    rule_id="SEC-004",
                    level="PASS",
                    container=name,
                    message_ko="capabilities.drop에 ALL이 포함되어 있습니다.",
                    message_en="capabilities.drop includes ALL.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="SEC-004",
                level="FAIL",
                container=name,
                message_ko=f"[{name}] capabilities.drop에 ALL이 없습니다.",
                message_en=f"[{name}] capabilities.drop does not include ALL.",
                suggestion=(
                    "securityContext.capabilities.drop: [ALL] 을 추가하세요. "
                    "불필요한 Linux capability를 모두 제거해야 공격 표면이 최소화됩니다."
                ),
            )
        ]

    def _rule_sec005(self, c: dict[str, Any]) -> list[CheckResult]:
        """SEC-005: capabilities.add에 위험 capability 없음."""
        name = str(c.get("name", "unknown"))
        sc = c.get("securityContext", {})
        caps = sc.get("capabilities", {})
        add = [str(x).upper() for x in caps.get("add", [])]
        dangerous = [cap for cap in add if cap in _DANGEROUS_CAPS]
        if dangerous:
            return [
                CheckResult(
                    rule_id="SEC-005",
                    level="FAIL",
                    container=name,
                    message_ko=f"[{name}] 위험한 capability가 추가되었습니다: {dangerous}.",
                    message_en=f"[{name}] Dangerous capabilities added: {dangerous}.",
                    suggestion=(
                        f"capabilities.add에서 {dangerous}를 제거하세요. "
                        "이 capability들은 호스트 커널에 대한 광범위한 접근을 허용합니다."
                    ),
                )
            ]
        return [
            CheckResult(
                rule_id="SEC-005",
                level="PASS",
                container=name,
                message_ko="위험한 capability가 없습니다.",
                message_en="No dangerous capabilities found.",
                suggestion="",
            )
        ]

    def _rule_sec006(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
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
                    f"Pod securityContext.seccompProfile.type이 올바르지 않습니다 "
                    f"(현재: {seccomp_type!r})."
                ),
                message_en=(
                    f"Pod securityContext.seccompProfile.type is invalid "
                    f"(current: {seccomp_type!r})."
                ),
                suggestion=(
                    "spec.securityContext.seccompProfile.type: RuntimeDefault"
                    " 또는 Localhost 를 설정하세요."
                    " seccomp 프로파일 없이는 컨테이너가 모든 syscall을 호출할 수 있습니다."
                ),
            )
        ]

    def _rule_sec007(self, c: dict[str, Any]) -> list[CheckResult]:
        """SEC-007: privileged: true 금지."""
        name = str(c.get("name", "unknown"))
        sc = c.get("securityContext", {})
        if sc.get("privileged") is True:
            return [
                CheckResult(
                    rule_id="SEC-007",
                    level="FAIL",
                    container=name,
                    message_ko=f"[{name}] privileged: true 설정은 금지됩니다.",
                    message_en=f"[{name}] privileged: true is not allowed.",
                    suggestion=(
                        "securityContext.privileged: true 를 제거하세요. "
                        "privileged 컨테이너는 호스트 커널에 무제한 접근이 가능합니다."
                    ),
                )
            ]
        return [
            CheckResult(
                rule_id="SEC-007",
                level="PASS",
                container=name,
                message_ko="privileged 모드가 비활성화되어 있습니다.",
                message_en="privileged mode is disabled.",
                suggestion="",
            )
        ]

    def _rule_sec008(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """SEC-008: hostPID / hostNetwork / hostIPC 금지."""
        results: list[CheckResult] = []
        for field_name in ("hostPID", "hostNetwork", "hostIPC"):
            if pod_spec.get(field_name) is True:
                results.append(
                    CheckResult(
                        rule_id="SEC-008",
                        level="FAIL",
                        container="(pod)",
                        message_ko=f"Pod spec.{field_name}: true 는 금지됩니다.",
                        message_en=f"Pod spec.{field_name}: true is not allowed.",
                        suggestion=(
                            f"spec.{field_name} 를 제거하거나 false로 설정하세요. "
                            "호스트 네임스페이스 공유는 컨테이너 격리를 무력화합니다."
                        ),
                    )
                )
        if not results:
            results.append(
                CheckResult(
                    rule_id="SEC-008",
                    level="PASS",
                    container="(pod)",
                    message_ko="hostPID/hostNetwork/hostIPC 모두 비활성화되어 있습니다.",
                    message_en="hostPID/hostNetwork/hostIPC are all disabled.",
                    suggestion="",
                )
            )
        return results

    def _rule_sec009(self, c: dict[str, Any]) -> list[CheckResult]:
        """SEC-009: 환경변수에 평문 시크릿 탐지."""
        name = str(c.get("name", "unknown"))
        env_list: list[dict[str, Any]] = c.get("env", [])
        results: list[CheckResult] = []

        for env in env_list:
            env_name = str(env.get("name", ""))
            value = env.get("value")
            if "valueFrom" in env:
                continue
            if value is None:
                continue
            value_str = str(value)
            if _SECRET_NAME_RE.search(env_name) and len(value_str) >= 8:
                results.append(
                    CheckResult(
                        rule_id="SEC-009",
                        level="FAIL",
                        container=name,
                        message_ko=(
                            f"[{name}] 환경변수 {env_name!r}에"
                            " 평문 시크릿이 포함된 것으로 의심됩니다."
                        ),
                        message_en=(
                            f"[{name}] Env var {env_name!r} appears to contain a plaintext secret."
                        ),
                        suggestion=(
                            f"env[{env_name!r}].valueFrom.secretKeyRef 를 사용하여 "
                            "Kubernetes Secret에서 값을 참조하세요."
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

    # ── RES 규칙 ──────────────────────────────────────────────────────────────

    def _rule_res001(self, c: dict[str, Any]) -> list[CheckResult]:
        """RES-001: resources.requests.{cpu,memory} + limits.{cpu,memory} 모두 존재."""
        name = str(c.get("name", "unknown"))
        resources = c.get("resources", {})
        requests = resources.get("requests", {})
        limits = resources.get("limits", {})

        missing: list[str] = []
        if "cpu" not in requests:
            missing.append("requests.cpu")
        if "memory" not in requests:
            missing.append("requests.memory")
        if "cpu" not in limits:
            missing.append("limits.cpu")
        if "memory" not in limits:
            missing.append("limits.memory")

        if missing:
            return [
                CheckResult(
                    rule_id="RES-001",
                    level="FAIL",
                    container=name,
                    message_ko=f"[{name}] 리소스 스펙 누락: {', '.join(missing)}.",
                    message_en=f"[{name}] Missing resource specs: {', '.join(missing)}.",
                    suggestion=(
                        "resources.requests 및 resources.limits에 cpu, memory 값을"
                        " 모두 설정하세요."
                        " 미설정 시 OOM 또는 CPU throttling이 예측 불가하게 발생합니다."
                    ),
                )
            ]
        return [
            CheckResult(
                rule_id="RES-001",
                level="PASS",
                container=name,
                message_ko="resources.requests/limits이 모두 설정되어 있습니다.",
                message_en="resources.requests/limits are fully specified.",
                suggestion="",
            )
        ]

    def _rule_res_w01(self, c: dict[str, Any]) -> list[CheckResult]:
        """RES-W01: CPU limit < request 경고."""
        name = str(c.get("name", "unknown"))
        resources = c.get("resources", {})
        requests = resources.get("requests", {})
        limits = resources.get("limits", {})

        req_cpu_str = requests.get("cpu")
        lim_cpu_str = limits.get("cpu")
        if req_cpu_str is None or lim_cpu_str is None:
            return []

        req_milli = _cpu_to_milli(str(req_cpu_str))
        lim_milli = _cpu_to_milli(str(lim_cpu_str))

        if req_milli is not None and lim_milli is not None and lim_milli < req_milli:
            return [
                CheckResult(
                    rule_id="RES-W01",
                    level="WARN",
                    container=name,
                    message_ko=(
                        f"[{name}] CPU limit({lim_cpu_str})이 request({req_cpu_str})보다 작습니다."
                    ),
                    message_en=(
                        f"[{name}] CPU limit ({lim_cpu_str}) is less than request ({req_cpu_str})."
                    ),
                    suggestion=(
                        "CPU limit은 request 이상으로 설정하세요. "
                        "limit < request 는 스케줄러 예측 불가를 유발합니다."
                    ),
                )
            ]
        return []

    # ── IMG 규칙 ──────────────────────────────────────────────────────────────

    def _rule_img001(self, c: dict[str, Any]) -> list[CheckResult]:
        """IMG-001: latest 태그 또는 태그 누락 금지."""
        name = str(c.get("name", "unknown"))
        image = str(c.get("image", ""))

        # digest 부분 제거 후 태그 검사
        image_no_digest = image.split("@")[0]
        has_tag = ":" in image_no_digest.split("/")[-1]
        is_latest = image_no_digest.endswith(":latest")

        if is_latest or not has_tag:
            return [
                CheckResult(
                    rule_id="IMG-001",
                    level="FAIL",
                    container=name,
                    message_ko=f"[{name}] 이미지 태그가 'latest'이거나 태그가 없습니다: {image!r}.",
                    message_en=f"[{name}] Image tag is 'latest' or missing: {image!r}.",
                    suggestion=(
                        "myregistry.io/app:v1.2.3 형식으로 명시적 버전 태그를 사용하세요. "
                        "latest 또는 무태그 이미지는 재현 불가 배포를 유발합니다."
                    ),
                )
            ]
        return [
            CheckResult(
                rule_id="IMG-001",
                level="PASS",
                container=name,
                message_ko=f"이미지 태그가 명시되어 있습니다: {image!r}.",
                message_en=f"Image tag is explicitly set: {image!r}.",
                suggestion="",
            )
        ]

    def _rule_img_w01(self, c: dict[str, Any]) -> list[CheckResult]:
        """IMG-W01: digest pinning(@sha256:...) 미사용 시 WARN."""
        name = str(c.get("name", "unknown"))
        image = str(c.get("image", ""))

        if "@sha256:" in image:
            return []

        # IMG-001 FAIL 케이스(latest/no-tag)는 WARN 중복 방지
        image_no_digest = image.split("@")[0]
        has_tag = ":" in image_no_digest.split("/")[-1]
        is_latest = image_no_digest.endswith(":latest")
        if is_latest or not has_tag:
            return []

        return [
            CheckResult(
                rule_id="IMG-W01",
                level="WARN",
                container=name,
                message_ko=f"[{name}] 이미지 digest pinning이 사용되지 않습니다: {image!r}.",
                message_en=f"[{name}] Image digest pinning is not used: {image!r}.",
                suggestion=(
                    "image: myregistry.io/app:v1.2.3@sha256:... 형식으로 "
                    "digest를 고정하면 이미지 교체 공격(supply chain attack)을 방지할 수 있습니다."
                ),
            )
        ]

    # ── SA 규칙 ───────────────────────────────────────────────────────────────

    def _rule_sa001(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """SA-001: serviceAccountName 명시 필수."""
        sa_name = pod_spec.get("serviceAccountName")
        if sa_name and str(sa_name).strip():
            return [
                CheckResult(
                    rule_id="SA-001",
                    level="PASS",
                    container="(pod)",
                    message_ko=f"serviceAccountName이 명시되어 있습니다: {sa_name!r}.",
                    message_en=f"serviceAccountName is explicitly set: {sa_name!r}.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="SA-001",
                level="FAIL",
                container="(pod)",
                message_ko="spec.serviceAccountName이 설정되지 않았습니다.",
                message_en="spec.serviceAccountName is not set.",
                suggestion=(
                    "spec.serviceAccountName을 명시하세요. 미설정 시 default ServiceAccount가"
                    " 자동 마운트되어 불필요한 권한이 부여될 수 있습니다."
                ),
            )
        ]

    def _rule_sa002(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """SA-002: automountServiceAccountToken: false 필수."""
        val = pod_spec.get("automountServiceAccountToken")
        if val is False:
            return [
                CheckResult(
                    rule_id="SA-002",
                    level="PASS",
                    container="(pod)",
                    message_ko="automountServiceAccountToken이 false로 설정되어 있습니다.",
                    message_en="automountServiceAccountToken is set to false.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="SA-002",
                level="FAIL",
                container="(pod)",
                message_ko=f"automountServiceAccountToken이 false가 아닙니다 (현재: {val!r}).",
                message_en=f"automountServiceAccountToken is not false (current: {val!r}).",
                suggestion=(
                    "spec.automountServiceAccountToken: false 를 설정하세요. "
                    "자동 마운트된 토큰은 API server 접근에 악용될 수 있습니다."
                ),
            )
        ]

    # ── SVC 규칙 ──────────────────────────────────────────────────────────────

    def _check_service(self, doc: dict[str, Any]) -> list[CheckResult]:
        """Service kind 규칙 적용."""
        results: list[CheckResult] = []
        results.extend(self._rule_svc001(doc))
        results.extend(self._rule_svc002(doc))
        return results

    def _rule_svc001(self, doc: dict[str, Any]) -> list[CheckResult]:
        """SVC-001: Service.spec.type 명시 필수."""
        svc_name = str(doc.get("metadata", {}).get("name", "unknown"))
        svc_type = doc.get("spec", {}).get("type")
        if svc_type:
            return [
                CheckResult(
                    rule_id="SVC-001",
                    level="PASS",
                    container=f"svc/{svc_name}",
                    message_ko=f"Service.spec.type이 명시되어 있습니다: {svc_type!r}.",
                    message_en=f"Service.spec.type is set: {svc_type!r}.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="SVC-001",
                level="FAIL",
                container=f"svc/{svc_name}",
                message_ko=f"Service '{svc_name}'.spec.type이 설정되지 않았습니다.",
                message_en=f"Service '{svc_name}'.spec.type is not set.",
                suggestion=(
                    "spec.type: ClusterIP 또는 NodePort 를 명시하세요. "
                    "type 미설정 시 기본값(ClusterIP)이 적용되지만 의도가 불명확합니다."
                ),
            )
        ]

    def _rule_svc002(self, doc: dict[str, Any]) -> list[CheckResult]:
        """SVC-002: LoadBalancer 사용 시 WARN."""
        svc_name = str(doc.get("metadata", {}).get("name", "unknown"))
        svc_type = doc.get("spec", {}).get("type")
        if svc_type == "LoadBalancer":
            return [
                CheckResult(
                    rule_id="SVC-002",
                    level="WARN",
                    container=f"svc/{svc_name}",
                    message_ko=(
                        f"Service '{svc_name}'가 LoadBalancer 타입을 사용합니다 "
                        "— 클라우드 비용이 발생합니다."
                    ),
                    message_en=(
                        f"Service '{svc_name}' uses LoadBalancer type — incurs cloud costs."
                    ),
                    suggestion=(
                        "내부 서비스라면 ClusterIP 또는 NodePort 를 사용하세요. "
                        "LoadBalancer는 클라우드 공급자의 외부 로드밸런서를 프로비저닝합니다."
                    ),
                )
            ]
        return []

    # ── PRB 규칙 ──────────────────────────────────────────────────────────────

    def _rule_prb001(self, c: dict[str, Any]) -> list[CheckResult]:
        """PRB-001: livenessProbe + readinessProbe 모두 존재."""
        name = str(c.get("name", "unknown"))
        has_liveness = "livenessProbe" in c
        has_readiness = "readinessProbe" in c

        if has_liveness and has_readiness:
            return [
                CheckResult(
                    rule_id="PRB-001",
                    level="PASS",
                    container=name,
                    message_ko="livenessProbe와 readinessProbe가 모두 설정되어 있습니다.",
                    message_en="Both livenessProbe and readinessProbe are configured.",
                    suggestion="",
                )
            ]

        missing: list[str] = []
        if not has_liveness:
            missing.append("livenessProbe")
        if not has_readiness:
            missing.append("readinessProbe")

        return [
            CheckResult(
                rule_id="PRB-001",
                level="FAIL",
                container=name,
                message_ko=f"[{name}] 프로브 미설정: {', '.join(missing)}.",
                message_en=f"[{name}] Missing probes: {', '.join(missing)}.",
                suggestion=(
                    f"{', '.join(missing)} 를 설정하세요. "
                    "프로브 미설정 시 비정상 파드가 트래픽을 계속 수신합니다."
                ),
            )
        ]

    def _rule_prb002(self, c: dict[str, Any]) -> list[CheckResult]:
        """PRB-002: initialDelaySeconds가 0이면 WARN."""
        name = str(c.get("name", "unknown"))
        results: list[CheckResult] = []

        for probe_key in ("livenessProbe", "readinessProbe"):
            probe = c.get(probe_key)
            if probe is None:
                continue
            delay = probe.get("initialDelaySeconds", None)
            if delay is not None and int(delay) == 0:
                results.append(
                    CheckResult(
                        rule_id="PRB-002",
                        level="WARN",
                        container=name,
                        message_ko=f"[{name}] {probe_key}.initialDelaySeconds가 0입니다.",
                        message_en=f"[{name}] {probe_key}.initialDelaySeconds is 0.",
                        suggestion=(
                            f"{probe_key}.initialDelaySeconds 를 애플리케이션 기동 시간보다"
                            " 큰 값으로 설정하세요."
                            " 0이면 기동 전에 probe가 실행되어 불필요한 재시작이 발생합니다."
                        ),
                    )
                )

        return results


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kubernetes manifest 정적 검증기 (stack-agnostic)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Exit codes:
              0 — PASS만 존재 (경고 없음)
              1 — FAIL 1건 이상
              2 — FAIL 없음 + WARN 1건 이상 (soft-success)
            """
        ),
    )
    parser.add_argument(
        "path",
        metavar="PATH",
        help="검증할 YAML 파일 또는 디렉토리 경로",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 형식으로 출력 (summary.json validation 필드 호환)",
    )
    parser.add_argument(
        "--skipped",
        nargs="+",
        metavar="CHECK",
        default=[],
        help="스킵된 검증 식별자 (예: kubectl_dry_run container_build)",
    )
    return parser


def main() -> int:
    """CLI 진입점. sys.exit()에 넘길 exit code를 반환."""
    parser = _build_parser()
    args = parser.parse_args()

    path = Path(args.path)
    skipped: list[str] = args.skipped or []

    validator = K8sValidator(skipped=skipped)
    report = validator.validate([path])

    if args.json_output:
        print(validator.to_json(report, skipped=skipped))
    else:
        _print_human(report)

    return report.exit_code


def _print_human(report: ValidationReport) -> None:
    """사람이 읽기 쉬운 형식으로 결과 출력."""
    print(f"\n{'=' * 60}")
    print("K8s Manifest 검증 결과")
    print(f"{'=' * 60}")

    for r in report.results:
        prefix = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}.get(r.level, r.level)
        print(f"[{prefix}] {r.rule_id} / {r.container}: {r.message_ko}")
        if r.suggestion and r.level != "PASS":
            print(f"      → {r.suggestion}")

    c = report.counts
    print(f"\n결과: PASS {c['pass']}건 / WARN {c['warn']}건 / FAIL {c['fail']}건")
    if report.skipped:
        print(f"스킵됨: {', '.join(report.skipped)}")

    if report.exit_code == 0:
        print("상태: 모든 검증 통과")
    elif report.exit_code == 1:
        print(f"상태: FAIL {c['fail']}건 수정 필요")
    else:
        print(f"상태: soft-success (WARN {c['warn']}건)")


if __name__ == "__main__":
    sys.exit(main())
