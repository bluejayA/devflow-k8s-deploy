"""STEP 4 재시도 오케스트레이션.

_shared.retry.retry_with_fix를 K8sValidator / KubectlDryRunner / BuildRunner 각각에
대해 호출하는 lambda 래퍼 + fix_attempt 헬퍼.

F-50: 3회 자동 수정 루프. F-51: 실패 시 bail-out.
F-56: degraded success pass-through (skipped 필드 → ValidationOutcome.skipped).
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from scripts._shared.retry import retry_with_fix
from scripts._shared.types import (
    BuildResult,
    DryRunResult,
    FixOutcome,
    RetryResult,
    ValidationOutcome,
    ValidationReport,
)

# bail-out 시 final_result=None인 경우 대신 쓸 빈 ValidationReport
_EMPTY_REPORT = ValidationReport(
    results=[],
    counts={"pass": 0, "warn": 0, "fail": 0},
    exit_code=1,
    skipped=[],
)

if TYPE_CHECKING:
    from scripts.kubectl_dry_runner import KubectlDryRunner
    from scripts.pipeline.build_runner import BuildRunner
    from scripts.validate_k8s import K8sValidator


def run_validation_loop(
    validator: "K8sValidator",
    manifest_paths: Sequence[Path | str],
    fix_attempt: Callable[[ValidationReport | Exception | None], FixOutcome],
    *,
    max_attempts: int = 3,
) -> RetryResult[ValidationReport]:
    """K8sValidator.validate를 3회 재시도.

    success_predicate: exit_code != 1 (PASS=0/WARN=2 성공, FAIL=1만 재시도, F-42 soft-success)
    retry_with_fix를 lambda로 래핑 — manifest_paths 인자 캡처.
    """
    paths: list[Path | str] = list(manifest_paths)
    return retry_with_fix(
        operation=lambda: validator.validate(paths),
        fix_attempt=fix_attempt,
        success_predicate=lambda report: report.exit_code != 1,
        max_attempts=max_attempts,
    )


def run_dry_run_loop(
    dry_runner: "KubectlDryRunner",
    manifest_dir: Path,
    fix_attempt: Callable[[DryRunResult | Exception | None], FixOutcome],
    *,
    max_attempts: int = 3,
) -> RetryResult[DryRunResult]:
    """KubectlDryRunner.dry_run을 3회 재시도.

    success_predicate: result.success (미설치 degraded 시에도 success=True라 종료)
    """
    return retry_with_fix(
        operation=lambda: dry_runner.dry_run(manifest_dir),
        fix_attempt=fix_attempt,
        success_predicate=lambda result: result.success,
        max_attempts=max_attempts,
    )


def run_build_loop(
    build_runner: "BuildRunner",
    context_dir: Path,
    image_tag: str,
    fix_attempt: Callable[[BuildResult | Exception | None], FixOutcome],
    *,
    dockerfile: Path | None = None,
    max_attempts: int = 3,
) -> RetryResult[BuildResult]:
    """BuildRunner.build를 3회 재시도.

    success_predicate: result.success
    """
    return retry_with_fix(
        operation=lambda: build_runner.build(
            context_dir, image_tag, dockerfile=dockerfile
        ),
        fix_attempt=fix_attempt,
        success_predicate=lambda result: result.success,
        max_attempts=max_attempts,
    )


def collect_validation_outcome(
    validation: RetryResult[ValidationReport],
    dry_run: RetryResult[DryRunResult],
    build: RetryResult[BuildResult] | None = None,
) -> ValidationOutcome:
    """F-56 pass-through: 각 결과의 skipped 정보를 ValidationOutcome으로 병합.

    - dry_run.final_result.skipped=True → skipped에 'kubectl_dry_run' 추가 + skip_reason_ko 수집
    - build.final_result.skipped=True → skipped에 'container_build' 추가 + skip_reason_ko 수집
    - validation.exit_code=2 (WARN) → success_predicate True로 취급하되 warnings 유지
    - ValidationOutcome.bailed: 어느 하나라도 bailout=True이면 True
    """
    skipped: list[str] = []
    skip_reasons: dict[str, str] = {}

    dry_run_result = dry_run.final_result
    if dry_run_result is not None and dry_run_result.skipped:
        skipped.append("kubectl_dry_run")
        if dry_run_result.skip_reason_ko:
            skip_reasons["kubectl_dry_run"] = dry_run_result.skip_reason_ko

    if build is not None:
        build_result = build.final_result
        if build_result is not None and build_result.skipped:
            skipped.append("container_build")
            if build_result.skip_reason_ko:
                skip_reasons["container_build"] = build_result.skip_reason_ko

    bailed = (
        validation.bailout
        or dry_run.bailout
        or (build.bailout if build is not None else False)
    )

    k8s_report: ValidationReport = (
        validation.final_result if validation.final_result is not None else _EMPTY_REPORT
    )

    return ValidationOutcome(
        k8s_report=k8s_report,
        dry_run=dry_run_result,
        build=build.final_result if build is not None else None,
        skipped=skipped,
        skip_reasons=skip_reasons,
        bailed=bailed,
    )
