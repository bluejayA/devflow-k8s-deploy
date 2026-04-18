"""K8s manifest 정적 검증기 (stack-agnostic).

CLI:
    validate_k8s.py [--json] [--skipped CHECK [CHECK ...]] PATH

Exit codes (F-42):
    0 — all PASS
    1 — FAIL 존재
    2 — FAIL 없음 + WARN 존재 (soft-success)

Consumer 주의 (F-42):
    set -e 환경에서 exit code 2 (soft-success)를 실패로 오인하지 않도록
    ``&& [ $? -le 2 ]`` 또는 ``|| [ $? -eq 2 ]`` 처리가 필요합니다.
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

# ─── 상수 ─────────────────────────────────────────────────────────────────────

# 유효 seccompProfile type (SEC-006)
_VALID_SECCOMP_TYPES: frozenset[str] = frozenset(["RuntimeDefault", "Localhost"])

# 시크릿 keyword 패턴 (환경변수 이름 기준, case-insensitive) — SEC-009
_SECRET_NAME_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|apikey|auth[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)

# CPU 단위를 millicores(int)로 변환 — RES-W01
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
        2 if no FAIL, any WARN (soft-success)
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
    """stack-agnostic Kubernetes manifest 정적 검증기 (F-43).

    Args:
        skipped: CLI --skipped 로 전달된 식별자 목록 (결과에 영향 없이 pass-through).
    """

    def __init__(self, skipped: list[str] | None = None) -> None:
        self._skipped: list[str] = list(skipped) if skipped else []

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def validate(self, manifests: list[Path | str]) -> ValidationReport:
        """manifests 경로 목록(파일 또는 디렉토리)에 대해 모든 규칙 적용.

        SVC-002 교차 검증을 위해 먼저 전체 document 목록을 수집한 뒤 검증한다.

        Args:
            manifests: YAML 파일 경로 또는 디렉토리 경로 목록.

        Returns:
            ValidationReport (results, counts, exit_code, skipped).
        """
        # 파일/디렉토리별로 document 목록을 수집 (파일 단위 PARSE-ERR 처리 포함)
        all_docs_per_file: list[tuple[Path, list[dict[str, Any]] | None]] = []

        file_paths: list[Path] = []
        for entry in manifests:
            path = Path(entry)
            if path.is_dir():
                yaml_files = sorted(
                    p
                    for p in path.rglob("*")
                    if p.suffix in (".yaml", ".yml") and p.is_file()
                )
                file_paths.extend(yaml_files)
            else:
                file_paths.append(path)

        results: list[CheckResult] = []
        all_valid_docs: list[dict[str, Any]] = []

        for fp in file_paths:
            try:
                docs = _safe_collect_file(fp)
                valid_docs = [d for d in docs if d is not None]
                all_docs_per_file.append((fp, valid_docs))
                all_valid_docs.extend(valid_docs)
            except MalformedManifestError as exc:
                all_docs_per_file.append((fp, None))
                results.append(
                    CheckResult(
                        rule_id="PARSE-ERR",
                        level="FAIL",
                        container="(file)",
                        message_ko=f"YAML 파싱 실패: {exc}",
                        message_en=f"YAML parse error: {exc}",
                        suggestion="YAML 구문을 확인하세요.",
                    )
                )

        # 각 파일의 document를 검증 (SVC-002 교차 검증은 file-scope)
        for _fp, file_docs in all_docs_per_file:
            if file_docs is None:
                continue
            for doc in file_docs:
                results.extend(self._validate_doc(doc, context_docs=file_docs))

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

    # ── document 단위 처리 ────────────────────────────────────────────────────

    def _validate_doc(
        self,
        doc: dict[str, Any],
        context_docs: list[dict[str, Any]] | None = None,
    ) -> list[CheckResult]:
        """단일 YAML document 검증 (kind 기반 분기).

        Args:
            doc: 검증할 document.
            context_docs: SVC-002 교차 검증에 사용할 동일 파일 내 document 목록.
        """
        kind = str(doc.get("kind", ""))
        results: list[CheckResult] = []

        if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
            results.extend(self._check_workload(doc))
        elif kind == "Pod":
            results.extend(self._check_pod_spec(doc.get("spec", {})))
        elif kind == "Service":
            results.extend(self._check_service(doc, context_docs=context_docs))

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
        """Pod spec 레벨 규칙 검증 (F-44: containers + initContainers 모두 순회)."""
        results: list[CheckResult] = []

        # Pod-level 규칙
        results.extend(self._rule_sec006(pod_spec))
        results.extend(self._rule_sec008(pod_spec))
        results.extend(self._rule_sa001(pod_spec))
        results.extend(self._rule_sa002(pod_spec))

        containers: list[dict[str, Any]] = pod_spec.get("containers", [])
        init_containers: list[dict[str, Any]] = pod_spec.get("initContainers", [])

        for container in containers + init_containers:
            results.extend(self._check_container(container, pod_spec=pod_spec))

        return results

    def _check_container(
        self, container: dict[str, Any], pod_spec: dict[str, Any] | None = None
    ) -> list[CheckResult]:
        """컨테이너 레벨 규칙 전체 적용."""
        results: list[CheckResult] = []
        pod_sc = (pod_spec or {}).get("securityContext", {})

        results.extend(self._rule_sec001(container, pod_sc=pod_sc))
        results.extend(self._rule_sec002(container))
        results.extend(self._rule_sec003(container))
        results.extend(self._rule_sec004(container))
        results.extend(self._rule_sec005(container))
        results.extend(self._rule_sec007(container, pod_sc=pod_sc))
        results.extend(self._rule_sec009(container))
        results.extend(self._rule_res001(container))
        results.extend(self._rule_res_w01(container))
        results.extend(self._rule_img001(container))
        results.extend(self._rule_img_w01(container))
        results.extend(self._rule_prb001(container))
        results.extend(self._rule_prb002(container))
        return results

    # ── SEC 규칙 ──────────────────────────────────────────────────────────────

    def _rule_sec001(
        self, c: dict[str, Any], pod_sc: dict[str, Any] | None = None
    ) -> list[CheckResult]:
        """SEC-001: runAsNonRoot: true 필수 (Pod 또는 container securityContext)."""
        name = str(c.get("name", "unknown"))
        container_sc = c.get("securityContext", {})

        # container 레벨 우선, 없으면 pod 레벨 확인
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

    def _rule_sec002(self, c: dict[str, Any]) -> list[CheckResult]:
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
                message_ko=f"allowPrivilegeEscalation 미설정 (현재: {val!r})",
                message_en=f"allowPrivilegeEscalation is not false (current: {val!r}).",
                suggestion=(
                    "securityContext.allowPrivilegeEscalation: false 를 추가하세요. "
                    "setuid 바이너리를 통한 권한 상승이 가능해집니다."
                ),
            )
        ]

    def _rule_sec004(self, c: dict[str, Any]) -> list[CheckResult]:
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

    def _rule_sec005(self, c: dict[str, Any]) -> list[CheckResult]:
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

    def _rule_sec006(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """SEC-006: Pod securityContext.seccompProfile.type 검증 (RuntimeDefault 또는 Localhost)."""
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

    def _rule_sec007(
        self, c: dict[str, Any], pod_sc: dict[str, Any] | None = None
    ) -> list[CheckResult]:
        """SEC-007: runAsUser > 0 필수 (root=0 금지). Pod 또는 container securityContext."""
        name = str(c.get("name", "unknown"))
        container_sc = c.get("securityContext", {})

        # container 레벨 우선, 없으면 pod 레벨 확인
        run_as_user = container_sc.get("runAsUser")
        if run_as_user is None and pod_sc:
            run_as_user = pod_sc.get("runAsUser")

        if run_as_user is not None and int(run_as_user) > 0:
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

    def _rule_sec008(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """SEC-008: fsGroup > 0 필수 (root 그룹 금지). Pod securityContext."""
        pod_sc = pod_spec.get("securityContext", {})
        fs_group = pod_sc.get("fsGroup")

        if fs_group is not None and int(fs_group) > 0:
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

    def _rule_sec009(self, c: dict[str, Any]) -> list[CheckResult]:
        """SEC-009: 환경변수에 평문 시크릿 탐지 (F-46a).

        env[].name이 시크릿 패턴과 일치하고, value 필드가 존재하고 비어있지 않으면 FAIL.
        valueFrom 사용 시 PASS.
        """
        name = str(c.get("name", "unknown"))
        env_list: list[dict[str, Any]] = c.get("env", [])
        results: list[CheckResult] = []

        for env in env_list:
            env_name = str(env.get("name", ""))
            # valueFrom 사용 시 안전
            if "valueFrom" in env:
                continue
            value = env.get("value")
            if value is None:
                continue
            value_str = str(value)
            # 빈 문자열은 제외
            if not value_str:
                continue
            if _SECRET_NAME_RE.search(env_name):
                results.append(
                    CheckResult(
                        rule_id="SEC-009",
                        level="FAIL",
                        container=name,
                        message_ko=(
                            f"환경변수 {env_name!r}에 평문 시크릿 의심"
                        ),
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
                    message_ko=f"리소스 스펙 누락: {', '.join(missing)}",
                    message_en=f"Missing resource specs: {', '.join(missing)}.",
                    suggestion=(
                        "resources.requests 및 resources.limits에 cpu, memory 값을"
                        " 모두 설정하세요. "
                        "미설정 시 OOM 또는 CPU throttling이 예측 불가하게 발생합니다."
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
        """RES-W01: requests:limits 비율 과도 (limit/request > 4배) 경고."""
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

        if (
            req_milli is not None
            and lim_milli is not None
            and req_milli > 0
            and lim_milli / req_milli > 4
        ):
            return [
                CheckResult(
                    rule_id="RES-W01",
                    level="WARN",
                    container=name,
                    message_ko=(
                        f"CPU limit({lim_cpu_str}) / request({req_cpu_str}) 비율이 4배 초과"
                    ),
                    message_en=(
                        f"CPU limit ({lim_cpu_str}) / request ({req_cpu_str}) ratio exceeds 4x."
                    ),
                    suggestion=(
                        "CPU limit은 request의 4배 이하로 설정하세요. "
                        "과도한 비율은 노드 과부하를 유발할 수 있습니다."
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
                    message_ko=f"이미지 태그가 'latest'이거나 태그가 없음: {image!r}",
                    message_en=f"Image tag is 'latest' or missing: {image!r}.",
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
                message_ko=f"이미지 digest pinning 미사용: {image!r}",
                message_en=f"Image digest pinning is not used: {image!r}.",
                suggestion=(
                    "image: myregistry.io/app:v1.2.3@sha256:... 형식으로 "
                    "digest를 고정하면 이미지 교체 공격(supply chain attack)을 방지할 수 있습니다."
                ),
            )
        ]

    # ── SA 규칙 ───────────────────────────────────────────────────────────────

    def _rule_sa001(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """SA-001: automountServiceAccountToken: false 필수."""
        val = pod_spec.get("automountServiceAccountToken")
        if val is False:
            return [
                CheckResult(
                    rule_id="SA-001",
                    level="PASS",
                    container="(pod)",
                    message_ko="automountServiceAccountToken이 false로 설정되어 있습니다.",
                    message_en="automountServiceAccountToken is set to false.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="SA-001",
                level="FAIL",
                container="(pod)",
                message_ko=f"automountServiceAccountToken 미설정 (현재: {val!r})",
                message_en=f"automountServiceAccountToken is not false (current: {val!r}).",
                suggestion=(
                    "spec.automountServiceAccountToken: false 를 설정하세요. "
                    "자동 마운트된 토큰은 API server 접근에 악용될 수 있습니다."
                ),
            )
        ]

    def _rule_sa002(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """SA-002: Pod에 serviceAccountName 명시 (default SA 방지)."""
        sa_name = pod_spec.get("serviceAccountName")
        if sa_name and str(sa_name).strip():
            return [
                CheckResult(
                    rule_id="SA-002",
                    level="PASS",
                    container="(pod)",
                    message_ko=f"serviceAccountName이 명시되어 있습니다: {sa_name!r}.",
                    message_en=f"serviceAccountName is explicitly set: {sa_name!r}.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="SA-002",
                level="FAIL",
                container="(pod)",
                message_ko="spec.serviceAccountName 미설정",
                message_en="spec.serviceAccountName is not set.",
                suggestion=(
                    "spec.serviceAccountName을 명시하세요. 미설정 시 default ServiceAccount가"
                    " 자동 마운트되어 불필요한 권한이 부여될 수 있습니다."
                ),
            )
        ]

    # ── SVC 규칙 ──────────────────────────────────────────────────────────────

    def _check_service(
        self,
        doc: dict[str, Any],
        context_docs: list[dict[str, Any]] | None = None,
    ) -> list[CheckResult]:
        """Service kind 규칙 적용."""
        results: list[CheckResult] = []
        results.extend(self._rule_svc001(doc))
        results.extend(self._rule_svc002(doc, context_docs=context_docs))
        return results

    def _rule_svc001(self, doc: dict[str, Any]) -> list[CheckResult]:
        """SVC-001: Service 리소스가 존재 — kind: Service 자체가 존재하면 PASS.

        이 규칙은 Service document가 처리될 때 호출된다.
        Service가 없으면 _validate_doc에서 이 메서드 자체가 호출되지 않으므로,
        Service document 존재 시 항상 PASS를 반환한다.
        """
        svc_name = str(doc.get("metadata", {}).get("name", "unknown"))
        return [
            CheckResult(
                rule_id="SVC-001",
                level="PASS",
                container=f"svc/{svc_name}",
                message_ko=f"Service 리소스가 존재합니다: {svc_name!r}.",
                message_en=f"Service resource exists: {svc_name!r}.",
                suggestion="",
            )
        ]

    def _rule_svc002(
        self,
        doc: dict[str, Any],
        context_docs: list[dict[str, Any]] | None = None,
    ) -> list[CheckResult]:
        """SVC-002: targetPort ↔ containerPort 교차 검증.

        교차 검증: context_docs에서 Deployment를 찾아 containerPort를 수집.
        매칭되는 Deployment가 없으면 skip (SVC-001로 Service 부재가 이미 처리됨).
        """
        svc_name = str(doc.get("metadata", {}).get("name", "unknown"))
        svc_ports: list[dict[str, Any]] = doc.get("spec", {}).get("ports", [])

        if not context_docs:
            return []

        # context_docs 내 Deployment의 containerPort 목록 수집
        container_ports: set[int] = set()
        named_ports: dict[str, int] = {}  # port name → containerPort

        for ctx_doc in context_docs:
            if ctx_doc.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
                continue
            pod_spec = ctx_doc.get("spec", {}).get("template", {}).get("spec", {})
            containers: list[dict[str, Any]] = pod_spec.get("containers", [])
            init_containers: list[dict[str, Any]] = pod_spec.get("initContainers", [])
            for c in containers + init_containers:
                for p in c.get("ports", []):
                    cp = p.get("containerPort")
                    if cp is not None:
                        container_ports.add(int(cp))
                    port_name = p.get("name")
                    if port_name and cp is not None:
                        named_ports[str(port_name)] = int(cp)

        if not container_ports and not named_ports:
            # Deployment에 ports 정의가 없으면 skip (검증 불가)
            return []

        results: list[CheckResult] = []
        for svc_port in svc_ports:
            target = svc_port.get("targetPort")
            if target is None:
                continue
            if isinstance(target, int):
                if target not in container_ports:
                    results.append(
                        CheckResult(
                            rule_id="SVC-002",
                            level="FAIL",
                            container=f"svc/{svc_name}",
                            message_ko=(
                                f"targetPort {target}가 컨테이너 containerPort 목록과 불일치"
                            ),
                            message_en=(
                                f"targetPort {target} does not match any container containerPort."
                            ),
                            suggestion=(
                                f"Service의 targetPort를 컨테이너의 containerPort 중 하나로 "
                                f"설정하세요. 가용 포트: {sorted(container_ports)}"
                            ),
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            rule_id="SVC-002",
                            level="PASS",
                            container=f"svc/{svc_name}",
                            message_ko=(
                                f"targetPort {target}가 컨테이너 containerPort와 일치합니다."
                            ),
                            message_en=(
                                f"targetPort {target} matches container containerPort."
                            ),
                            suggestion="",
                        )
                    )
            else:
                # 문자열(named port) 매칭
                target_str = str(target)
                if target_str in named_ports:
                    results.append(
                        CheckResult(
                            rule_id="SVC-002",
                            level="PASS",
                            container=f"svc/{svc_name}",
                            message_ko=(
                                f"named targetPort {target_str!r}가 컨테이너 포트와 일치합니다."
                            ),
                            message_en=(
                                f"Named targetPort {target_str!r} matches container port."
                            ),
                            suggestion="",
                        )
                    )
                else:
                    results.append(
                        CheckResult(
                            rule_id="SVC-002",
                            level="FAIL",
                            container=f"svc/{svc_name}",
                            message_ko=(
                                f"named targetPort {target_str!r}가 컨테이너 포트 이름과 불일치"
                            ),
                            message_en=(
                                f"Named targetPort {target_str!r} does not match any port."
                            ),
                            suggestion=(
                                f"컨테이너 ports[].name 중 하나로 targetPort를 설정하세요. "
                                f"등록된 포트 이름: {sorted(named_ports.keys())}"
                            ),
                        )
                    )

        return results

    # ── PRB 규칙 ──────────────────────────────────────────────────────────────

    def _rule_prb001(self, c: dict[str, Any]) -> list[CheckResult]:
        """PRB-001: livenessProbe 존재."""
        name = str(c.get("name", "unknown"))
        if "livenessProbe" in c:
            return [
                CheckResult(
                    rule_id="PRB-001",
                    level="PASS",
                    container=name,
                    message_ko="livenessProbe가 설정되어 있습니다.",
                    message_en="livenessProbe is configured.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="PRB-001",
                level="FAIL",
                container=name,
                message_ko="livenessProbe 미설정",
                message_en="livenessProbe is not configured.",
                suggestion=(
                    "livenessProbe 를 설정하세요. "
                    "미설정 시 비정상 파드가 재시작되지 않아 트래픽을 계속 수신합니다."
                ),
            )
        ]

    def _rule_prb002(self, c: dict[str, Any]) -> list[CheckResult]:
        """PRB-002: readinessProbe 존재."""
        name = str(c.get("name", "unknown"))
        if "readinessProbe" in c:
            return [
                CheckResult(
                    rule_id="PRB-002",
                    level="PASS",
                    container=name,
                    message_ko="readinessProbe가 설정되어 있습니다.",
                    message_en="readinessProbe is configured.",
                    suggestion="",
                )
            ]
        return [
            CheckResult(
                rule_id="PRB-002",
                level="FAIL",
                container=name,
                message_ko="readinessProbe 미설정",
                message_en="readinessProbe is not configured.",
                suggestion=(
                    "readinessProbe 를 설정하세요. "
                    "미설정 시 준비되지 않은 파드에 트래픽이 전달됩니다."
                ),
            )
        ]


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

            주의 (F-42): set -e 환경에서 exit 2를 실패로 오인하지 않으려면
              && [ $? -le 2 ] 또는 || [ $? -eq 2 ] 처리가 필요합니다.
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
    """사람이 읽기 쉬운 형식으로 결과 출력 (F-46 포맷)."""
    print(f"\n{'=' * 60}")
    print("K8s Manifest 검증 결과")
    print(f"{'=' * 60}")

    for r in report.results:
        prefix = r.level
        if r.suggestion and r.level != "PASS":
            print(f"[{prefix}] {r.rule_id} {r.container}: {r.message_ko} → {r.suggestion}")
        else:
            print(f"[{prefix}] {r.rule_id} {r.container}: {r.message_ko}")

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
