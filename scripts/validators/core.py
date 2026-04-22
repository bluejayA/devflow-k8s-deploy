"""K8sValidator 핵심 클래스 및 관련 유틸리티."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

# 규칙 모듈 임포트 — 데코레이터 등록 트리거
import scripts.validators.rules  # noqa: F401
from scripts._shared.errors import MalformedManifestError
from scripts._shared.fileio import check_yaml_refs, read_text_limited
from scripts._shared.types import CheckResult, ValidationReport
from scripts.validators.helpers import _as_dict
from scripts.validators.registry import run_rules


def _compute_exit_code(counts: dict[str, int]) -> int:
    """counts 기반 exit code 산출 (F-42).

    Returns:
        0 — FAIL/WARN 없음, 1 — FAIL 존재, 2 — FAIL 없음 + WARN 존재
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
    except FileNotFoundError as exc:
        raise MalformedManifestError(f"파일 없음: {path.name}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise MalformedManifestError(
            f"파일 읽기 실패: {path.name} ({type(exc).__name__})"
        ) from exc
    except ValueError as exc:
        raise MalformedManifestError(f"파일 크기 초과: {path.name}") from exc

    try:
        check_yaml_refs(raw)
        return list(yaml.safe_load_all(raw))
    except yaml.YAMLError as exc:
        raise MalformedManifestError(f"YAML 파싱 실패: {path.name}") from exc


class K8sValidator:
    """stack-agnostic Kubernetes manifest 정적 검증기 (F-43).

    Args:
        skipped: CLI --skipped 로 전달된 식별자 목록 (결과에 영향 없이 pass-through).
    """

    def __init__(self, skipped: list[str] | None = None) -> None:
        self._skipped: list[str] = list(skipped) if skipped else []

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def validate(self, manifests: list[Path | str]) -> ValidationReport:
        """manifests 경로 목록(파일 또는 디렉토리)에 대해 모든 규칙 적용."""
        all_docs_per_file: list[tuple[Path, list[dict[str, Any]] | None]] = []
        file_paths: list[Path] = []
        for entry in manifests:
            path = Path(entry)
            if path.is_dir():
                yaml_files = sorted(
                    p for p in path.rglob("*")
                    if p.suffix in (".yaml", ".yml") and p.is_file()
                )
                file_paths.extend(yaml_files)
            else:
                file_paths.append(path)

        results: list[CheckResult] = []
        for fp in file_paths:
            try:
                docs = _safe_collect_file(fp)
                valid_docs = [d for d in docs if d is not None]
                all_docs_per_file.append((fp, valid_docs))
            except MalformedManifestError as exc:
                all_docs_per_file.append((fp, None))
                results.append(CheckResult(
                    rule_id="PARSE-ERR", level="FAIL", container="(file)",
                    message_ko=f"YAML 파싱 실패: {exc}",
                    message_en=f"YAML parse error: {exc}",
                    suggestion="YAML 구문을 확인하세요.",
                ))

        all_valid_docs: list[dict[str, Any]] = []
        for _fp, file_docs in all_docs_per_file:
            if file_docs is None:
                continue
            for doc in file_docs:
                results.extend(self._validate_doc(doc, context_docs=file_docs))
            all_valid_docs.extend(file_docs)

        # manifest_set 후처리 (NET-W01 등 집합 수준 규칙)
        results.extend(run_rules("manifest_set", {}, docs=all_valid_docs))

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

    def to_json(self, report: ValidationReport, skipped: list[str] | None = None) -> str:
        """summary.json validation 객체 호환 JSON 직렬화."""
        effective_skipped = skipped if skipped is not None else report.skipped
        return json.dumps(
            {
                "results": [
                    {"rule_id": r.rule_id, "level": r.level, "container": r.container,
                     "message_ko": r.message_ko, "message_en": r.message_en,
                     "suggestion": r.suggestion}
                    for r in report.results
                ],
                "counts": report.counts,
                "exit_code": report.exit_code,
                "skipped": effective_skipped,
            },
            ensure_ascii=False, indent=2,
        )

    # ── document 단위 처리 ────────────────────────────────────────────────────

    def _validate_doc(
        self,
        doc: dict[str, Any],
        context_docs: list[dict[str, Any]] | None = None,
    ) -> list[CheckResult]:
        """단일 YAML document 검증 (kind 기반 분기)."""
        kind = str(doc.get("kind", ""))
        results: list[CheckResult] = []
        if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
            results.extend(self._check_workload(doc))
            if kind == "StatefulSet":
                results.extend(run_rules("statefulset", doc))
        elif kind == "Pod":
            results.extend(self._check_pod_spec(_as_dict(doc.get("spec"))))
        elif kind == "Service":
            results.extend(self._check_service(doc, context_docs=context_docs))
        return results

    def _check_workload(self, doc: dict[str, Any]) -> list[CheckResult]:
        """Deployment / StatefulSet / DaemonSet 등 workload 규칙 전체 적용."""
        kind = str(doc.get("kind", ""))
        if kind == "CronJob":
            pod_spec: dict[str, Any] = _as_dict(
                _as_dict(_as_dict(_as_dict(_as_dict(doc.get("spec")).get("jobTemplate")).get("spec")).get("template")).get("spec")
            )
        else:
            pod_spec = _as_dict(_as_dict(_as_dict(doc.get("spec")).get("template")).get("spec"))
        return self._check_pod_spec(pod_spec)

    def _check_pod_spec(self, pod_spec: dict[str, Any]) -> list[CheckResult]:
        """Pod spec 레벨 규칙 검증 (F-44: containers + initContainers 모두 순회)."""
        results: list[CheckResult] = []
        results.extend(run_rules("pod_spec", pod_spec))

        containers: list[dict[str, Any]] = pod_spec.get("containers", [])
        init_containers: list[dict[str, Any]] = pod_spec.get("initContainers", [])
        pod_sc = pod_spec.get("securityContext", {})
        for container in containers + init_containers:
            results.extend(run_rules("container", container, pod_sc=pod_sc))
        return results

    def _check_service(
        self,
        doc: dict[str, Any],
        context_docs: list[dict[str, Any]] | None = None,
    ) -> list[CheckResult]:
        """Service kind 규칙 적용."""
        return run_rules("service", doc, context_docs=context_docs)
