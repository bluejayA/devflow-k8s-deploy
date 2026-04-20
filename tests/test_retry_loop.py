"""Unit 13 — retry_loop TDD 테스트.

테스트 범주:
  - run_validation_loop: 성공/재시도 성공/3회 실패/exit_code=2/applied=False (5건)
  - run_dry_run_loop: 성공/degraded skip/3회 실패 (3건)
  - run_build_loop: 성공/skip/재시도 성공 (3건)
  - collect_validation_outcome F-56 pass-through: 6건
  총 17건
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from scripts._shared.types import (
    BuildResult,
    DryRunResult,
    FixOutcome,
    RetryResult,
    ValidationOutcome,
    ValidationReport,
)
from scripts.pipeline.retry_loop import (
    collect_validation_outcome,
    run_build_loop,
    run_dry_run_loop,
    run_validation_loop,
)

# ─── 헬퍼 ──────────────────────────────────────────────────────────────────────


def _make_validation_report(exit_code: int) -> ValidationReport:
    return ValidationReport(
        results=[],
        counts={"pass": 0, "warn": 0, "fail": 0},
        exit_code=exit_code,
        skipped=[],
    )


def _make_dry_run_result(
    success: bool,
    skipped: bool = False,
    skip_reason_ko: str | None = None,
) -> DryRunResult:
    return DryRunResult(
        success=success,
        stdout=None,
        stderr=None,
        exit_code=0 if success else 1,
        skipped=skipped,
        skip_reason_ko=skip_reason_ko,
    )


def _make_build_result(
    success: bool,
    skipped: bool = False,
    skip_reason_ko: str | None = None,
) -> BuildResult:
    return BuildResult(
        success=success,
        image_ref="repo:tag" if success else None,
        engine="docker" if (success and not skipped) else None,
        skipped=skipped,
        skip_reason_ko=skip_reason_ko,
    )


def _fix_applied() -> FixOutcome:
    return FixOutcome(applied=True, summary_ko="수정 적용됨")


def _fix_not_applied() -> FixOutcome:
    return FixOutcome(applied=False, summary_ko="수정 불가")


def _make_retry_result(
    success: bool,
    final_result: object,
    bailout: bool = False,
) -> RetryResult:
    return RetryResult(
        success=success,
        final_result=final_result,
        attempts=[],
        bailout=bailout,
    )


# ─── run_validation_loop ───────────────────────────────────────────────────────


class TestRunValidationLoop:
    """run_validation_loop 5건."""

    def test_first_attempt_success(self) -> None:
        """케이스 1: 첫 시도 성공 (exit_code=0) — operation 1회, fix_attempt 0회."""
        validator = MagicMock()
        report = _make_validation_report(exit_code=0)
        validator.validate.return_value = report
        fix = MagicMock(return_value=_fix_applied())

        result = run_validation_loop(validator, [Path("a.yaml")], fix, max_attempts=3)

        assert result.success is True
        assert result.final_result is report
        assert result.bailout is False
        assert validator.validate.call_count == 1
        fix.assert_not_called()

    def test_second_attempt_success(self) -> None:
        """케이스 2: 2번째 시도 성공 — fix_attempt 1회 applied=True."""
        validator = MagicMock()
        fail_report = _make_validation_report(exit_code=1)
        pass_report = _make_validation_report(exit_code=0)
        validator.validate.side_effect = [fail_report, pass_report]
        fix = MagicMock(return_value=_fix_applied())

        result = run_validation_loop(validator, [Path("a.yaml")], fix, max_attempts=3)

        assert result.success is True
        assert result.final_result is pass_report
        assert validator.validate.call_count == 2
        assert fix.call_count == 1

    def test_all_attempts_fail_bailout(self) -> None:
        """케이스 3: 3회 모두 실패 — bailout=True."""
        validator = MagicMock()
        fail_report = _make_validation_report(exit_code=1)
        validator.validate.return_value = fail_report
        fix = MagicMock(return_value=_fix_applied())

        result = run_validation_loop(validator, [Path("a.yaml")], fix, max_attempts=3)

        assert result.success is False
        assert result.bailout is True
        assert validator.validate.call_count == 3

    def test_exit_code_2_is_success(self) -> None:
        """케이스 4: exit_code=2 (WARN) → success_predicate True (F-42 soft-success)."""
        validator = MagicMock()
        warn_report = _make_validation_report(exit_code=2)
        validator.validate.return_value = warn_report
        fix = MagicMock(return_value=_fix_applied())

        result = run_validation_loop(validator, [Path("a.yaml")], fix, max_attempts=3)

        assert result.success is True
        assert result.final_result is warn_report
        assert result.bailout is False
        assert validator.validate.call_count == 1
        fix.assert_not_called()

    def test_fix_not_applied_immediate_bailout(self) -> None:
        """케이스 5: FixOutcome.applied=False → 즉시 bail-out."""
        validator = MagicMock()
        fail_report = _make_validation_report(exit_code=1)
        validator.validate.return_value = fail_report
        fix = MagicMock(return_value=_fix_not_applied())

        result = run_validation_loop(validator, [Path("a.yaml")], fix, max_attempts=3)

        assert result.success is False
        assert result.bailout is True
        # 첫 실패 + fix applied=False → 즉시 종료 (2번째 validate 없음)
        assert validator.validate.call_count == 1
        assert fix.call_count == 1


# ─── run_dry_run_loop ──────────────────────────────────────────────────────────


class TestRunDryRunLoop:
    """run_dry_run_loop 3건."""

    def test_first_attempt_success(self) -> None:
        """케이스 6: 첫 시도 성공 — fix_attempt 0회."""
        dry_runner = MagicMock()
        ok_result = _make_dry_run_result(success=True)
        dry_runner.dry_run.return_value = ok_result
        fix = MagicMock(return_value=_fix_applied())

        result = run_dry_run_loop(dry_runner, Path("/manifests"), fix, max_attempts=3)

        assert result.success is True
        assert result.final_result is ok_result
        assert dry_runner.dry_run.call_count == 1
        fix.assert_not_called()

    def test_kubectl_not_installed_degraded_success(self) -> None:
        """케이스 7: kubectl 미설치 degraded (success=True, skipped=True) → 즉시 종료."""
        dry_runner = MagicMock()
        degraded = _make_dry_run_result(
            success=True,
            skipped=True,
            skip_reason_ko="쿠버네티스 CLI(kubectl)가 설치되어 있지 않아 dry-run 검증을 건너뜀",
        )
        dry_runner.dry_run.return_value = degraded
        fix = MagicMock(return_value=_fix_applied())

        result = run_dry_run_loop(dry_runner, Path("/manifests"), fix, max_attempts=3)

        assert result.success is True
        assert result.final_result.skipped is True
        assert dry_runner.dry_run.call_count == 1
        fix.assert_not_called()

    def test_all_attempts_fail_bailout(self) -> None:
        """케이스 8: 3회 실패 → bailout."""
        dry_runner = MagicMock()
        fail_result = _make_dry_run_result(success=False)
        dry_runner.dry_run.return_value = fail_result
        fix = MagicMock(return_value=_fix_applied())

        result = run_dry_run_loop(dry_runner, Path("/manifests"), fix, max_attempts=3)

        assert result.success is False
        assert result.bailout is True
        assert dry_runner.dry_run.call_count == 3


# ─── run_build_loop ────────────────────────────────────────────────────────────


class TestRunBuildLoop:
    """run_build_loop 3건."""

    def test_first_attempt_success(self) -> None:
        """케이스 9: 첫 시도 성공 — fix_attempt 0회."""
        build_runner = MagicMock()
        ok_result = _make_build_result(success=True)
        build_runner.build.return_value = ok_result
        fix = MagicMock(return_value=_fix_applied())

        result = run_build_loop(
            build_runner,
            Path("/app"),
            "repo:latest",
            fix,
            max_attempts=3,
        )

        assert result.success is True
        assert result.final_result is ok_result
        assert build_runner.build.call_count == 1
        fix.assert_not_called()

    def test_skip_mode_immediate_success(self) -> None:
        """케이스 10: skip 모드 (skipped=True, success=True) → 즉시 종료."""
        build_runner = MagicMock()
        skipped_result = _make_build_result(
            success=True,
            skipped=True,
            skip_reason_ko="컨테이너 빌드가 skip 모드로 설정되어 있음 (build.engine=skip)",
        )
        build_runner.build.return_value = skipped_result
        fix = MagicMock(return_value=_fix_applied())

        result = run_build_loop(
            build_runner,
            Path("/app"),
            "repo:latest",
            fix,
            max_attempts=3,
        )

        assert result.success is True
        assert result.final_result.skipped is True
        assert build_runner.build.call_count == 1
        fix.assert_not_called()

    def test_retry_on_failure_then_success(self) -> None:
        """케이스 11: 빌드 실패 후 재시도 → 성공."""
        build_runner = MagicMock()
        fail_result = _make_build_result(success=False)
        ok_result = _make_build_result(success=True)
        build_runner.build.side_effect = [fail_result, ok_result]
        fix = MagicMock(return_value=_fix_applied())

        result = run_build_loop(
            build_runner,
            Path("/app"),
            "repo:latest",
            fix,
            max_attempts=3,
        )

        assert result.success is True
        assert result.final_result is ok_result
        assert build_runner.build.call_count == 2
        assert fix.call_count == 1


# ─── collect_validation_outcome (F-56 pass-through) ───────────────────────────


class TestCollectValidationOutcome:
    """collect_validation_outcome 6건."""

    def _ok_validation(self) -> RetryResult[ValidationReport]:
        return _make_retry_result(
            success=True,
            final_result=_make_validation_report(exit_code=0),
        )

    def _ok_dry_run(self) -> RetryResult[DryRunResult]:
        return _make_retry_result(
            success=True,
            final_result=_make_dry_run_result(success=True),
        )

    def _ok_build(self) -> RetryResult[BuildResult]:
        return _make_retry_result(
            success=True,
            final_result=_make_build_result(success=True),
        )

    def test_all_success_no_skipped(self) -> None:
        """케이스 12: 모든 성공 → skipped=[], skip_reasons={}, bailed=False."""
        outcome = collect_validation_outcome(
            self._ok_validation(),
            self._ok_dry_run(),
            self._ok_build(),
        )

        assert isinstance(outcome, ValidationOutcome)
        assert outcome.skipped == []
        assert outcome.skip_reasons == {}
        assert outcome.bailed is False

    def test_dry_run_not_installed_skipped(self) -> None:
        """케이스 13: dry_run 미설치 → skipped=['kubectl_dry_run'], skip_reasons 포함."""
        dry_run_degraded = _make_retry_result(
            success=True,
            final_result=_make_dry_run_result(
                success=True,
                skipped=True,
                skip_reason_ko="쿠버네티스 CLI(kubectl)가 설치되어 있지 않아 dry-run 검증을 건너뜀",
            ),
        )

        outcome = collect_validation_outcome(
            self._ok_validation(),
            dry_run_degraded,
        )

        assert "kubectl_dry_run" in outcome.skipped
        assert "kubectl_dry_run" in outcome.skip_reasons
        assert outcome.skip_reasons["kubectl_dry_run"] != ""
        assert outcome.bailed is False

    def test_build_skipped(self) -> None:
        """케이스 14: build skip → skipped=['container_build']."""
        build_skipped = _make_retry_result(
            success=True,
            final_result=_make_build_result(
                success=True,
                skipped=True,
                skip_reason_ko="컨테이너 빌드가 skip 모드로 설정되어 있음 (build.engine=skip)",
            ),
        )

        outcome = collect_validation_outcome(
            self._ok_validation(),
            self._ok_dry_run(),
            build_skipped,
        )

        assert "container_build" in outcome.skipped
        assert "container_build" in outcome.skip_reasons
        assert "kubectl_dry_run" not in outcome.skipped
        assert outcome.bailed is False

    def test_both_skipped(self) -> None:
        """케이스 15: dry_run + build 둘 다 skipped → list에 둘 다."""
        dry_run_degraded = _make_retry_result(
            success=True,
            final_result=_make_dry_run_result(
                success=True,
                skipped=True,
                skip_reason_ko="kubectl 없음",
            ),
        )
        build_skipped = _make_retry_result(
            success=True,
            final_result=_make_build_result(
                success=True,
                skipped=True,
                skip_reason_ko="엔진 없음",
            ),
        )

        outcome = collect_validation_outcome(
            self._ok_validation(),
            dry_run_degraded,
            build_skipped,
        )

        assert "kubectl_dry_run" in outcome.skipped
        assert "container_build" in outcome.skipped
        assert len(outcome.skipped) == 2
        assert outcome.bailed is False

    def test_skipped_still_not_bailed(self) -> None:
        """케이스 16: 성공 + skipped 조합 → bailed=False (F-56: skipped도 success로 간주)."""
        dry_run_degraded = _make_retry_result(
            success=True,
            final_result=_make_dry_run_result(success=True, skipped=True),
        )
        build_skipped = _make_retry_result(
            success=True,
            final_result=_make_build_result(success=True, skipped=True),
        )

        outcome = collect_validation_outcome(
            self._ok_validation(),
            dry_run_degraded,
            build_skipped,
        )

        # F-56: 모두 success이면 bailed=False
        assert outcome.bailed is False

    def test_bailed_when_validation_bailout(self) -> None:
        """케이스 17: validation.bailout=True → bailed=True."""
        validation_bailed = _make_retry_result(
            success=False,
            final_result=_make_validation_report(exit_code=1),
            bailout=True,
        )

        outcome = collect_validation_outcome(
            validation_bailed,
            self._ok_dry_run(),
        )

        assert outcome.bailed is True
