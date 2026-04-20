"""Unit 14 — SkillPipeline orchestrator TDD 테스트.

테스트 범주:
  - 흐름 테스트 (통합 — 5 STEP 순서): 7건
  - AtomicWriter 통합: 2건
  - 에러 경로 (BailOut/UserAbort/ConfigWarning): 3건
  - HelpCatalog: 5건
  - MessagePolicy: 2건
  - STEP 1 prompt/자동 경로: 3건
  총 22건
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts._shared.errors import BailOutError, UserAbort
from scripts._shared.types import (
    AnalysisResult,
    BuildPlan,
    BuildResult,
    DryRunResult,
    MessagePolicy,
    PackagingResult,
    ProbeConfig,
    ProbeSpec,
    PromptRequest,
    ResolvedConfig,
    ResourceDefaults,
    RetryResult,
    StackDetectResult,
    StatefulnessSignal,
    UserInputs,
    ValidationOutcome,
    ValidationReport,
)
from scripts.pipeline.orchestrator import (
    HelpCatalog,
    PipelineDependencies,
    SkillPipeline,
)

# ─── Fixtures / Helpers ────────────────────────────────────────────────────────


def _make_resolved_config(
    raw: dict[str, Any] | None = None,
    source_map: dict[str, str] | None = None,
    warnings: list[str] | None = None,
) -> ResolvedConfig:
    return ResolvedConfig(
        raw=raw or {},
        source_map=source_map or {},
        warnings=warnings or [],
    )


def _make_user_inputs() -> UserInputs:
    return UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="my-ns",
        output_dir=Path("k8s-output"),
        resource_hint="medium",
    )


def _make_analysis_result() -> AnalysisResult:
    return AnalysisResult(
        stack="jvm",
        detect_result=StackDetectResult(
            port=8080,
            entrypoint="java -jar app.jar",
            framework="spring-boot",
            version="3.2.0",
            build_system="gradle",
            actuator_enabled=True,
        ),
        build_plan=BuildPlan(
            builder_image="eclipse-temurin:21-jdk",
            runner_image="eclipse-temurin:21-jre",
            build_cmd="./gradlew bootJar",
            artifact_path="build/libs/app.jar",
        ),
        probe_config=ProbeConfig(
            liveness=ProbeSpec(kind="http", path="/actuator/health/liveness", port=8080),
            readiness=ProbeSpec(kind="http", path="/actuator/health/readiness", port=8080),
        ),
        defaults=ResourceDefaults(
            cpu_request="250m",
            memory_request="512Mi",
            cpu_limit="1000m",
            memory_limit="1Gi",
            writable_paths=["/tmp", "/var/log"],
        ),
        artifact_paths=[Path("build/libs/app.jar")],
        selected_module=None,
        statefulness=StatefulnessSignal(
            is_stateful=False,
            confidence="high",
            reasons=[],
        ),
        gaps=[],
    )


def _make_validation_report(exit_code: int = 0) -> ValidationReport:
    return ValidationReport(
        results=[],
        counts={"pass": 10, "warn": 0, "fail": 0},
        exit_code=exit_code,
        skipped=[],
    )


def _make_dry_run_result(success: bool = True, skipped: bool = False) -> DryRunResult:
    return DryRunResult(
        success=success,
        stdout=None,
        stderr=None,
        exit_code=0 if success else 1,
        skipped=skipped,
        skip_reason_ko="kubectl 미설치" if skipped else None,
    )


def _make_retry_result(
    success: bool = True,
    final_result: Any = None,
    bailout: bool = False,
) -> RetryResult:
    from scripts._shared.types import RetryAttempt

    attempt = RetryAttempt(
        attempt_number=1,
        result=final_result,
        error=None,
        success=success,
        fix_outcome=None,
    )
    return RetryResult(
        success=success,
        final_result=final_result,
        attempts=[attempt],
        bailout=bailout,
    )


def _make_packaging_result() -> PackagingResult:
    return PackagingResult(
        final_dir=Path("/tmp/staging"),
        files_written=["summary.json", "rationale.md"],
        troubleshoot_written=False,
    )


def _make_validation_outcome(
    k8s_report: ValidationReport | None = None,
) -> ValidationOutcome:
    return ValidationOutcome(
        k8s_report=k8s_report or _make_validation_report(),
        dry_run=_make_dry_run_result(),
        build=None,
        skipped=[],
        skip_reasons={},
        bailed=False,
    )


def _make_deps(
    *,
    config_raw: dict[str, Any] | None = None,
    analysis: AnalysisResult | None = None,
    k8s_exit_code: int = 0,
    dry_run_success: bool = True,
    build_engine: str = "skip",
) -> tuple[PipelineDependencies, dict[str, MagicMock]]:
    """의존성 MagicMock 묶음 생성 헬퍼."""
    mocks: dict[str, MagicMock] = {}

    config_loader = MagicMock(name="config_loader")
    raw = config_raw or {"build": {"engine": build_engine}}
    config = _make_resolved_config(raw=raw)
    config_loader.load.return_value = config
    mocks["config_loader"] = config_loader

    project_analyzer = MagicMock(name="project_analyzer")
    project_analyzer.analyze.return_value = analysis or _make_analysis_result()
    mocks["project_analyzer"] = project_analyzer

    dockerfile_generator = MagicMock(name="dockerfile_generator")
    dockerfile_generator.generate.return_value = "FROM eclipse-temurin:21-jdk\nRUN echo ok"
    mocks["dockerfile_generator"] = dockerfile_generator

    manifest_generator = MagicMock(name="manifest_generator")
    manifest_generator.generate_deployment.return_value = "apiVersion: apps/v1\nkind: Deployment"
    manifest_generator.generate_service.return_value = "apiVersion: v1\nkind: Service"
    manifest_generator.generate_serviceaccount.return_value = "apiVersion: v1\nkind: ServiceAccount"
    mocks["manifest_generator"] = manifest_generator

    k8s_validator = MagicMock(name="k8s_validator")
    report = _make_validation_report(exit_code=k8s_exit_code)
    k8s_validator.validate.return_value = report
    mocks["k8s_validator"] = k8s_validator

    kubectl_dry_runner = MagicMock(name="kubectl_dry_runner")
    dry_result = _make_dry_run_result(success=dry_run_success)
    kubectl_dry_runner.dry_run.return_value = dry_result
    mocks["kubectl_dry_runner"] = kubectl_dry_runner

    build_runner = MagicMock(name="build_runner")
    build_result = BuildResult(
        success=True,
        image_ref=None,
        engine=None,
        skipped=True,
        skip_reason_ko="skip 모드",
    )
    build_runner.build.return_value = build_result
    mocks["build_runner"] = build_runner

    output_packager = MagicMock(name="output_packager")
    output_packager.write.return_value = _make_packaging_result()
    mocks["output_packager"] = output_packager

    deps = PipelineDependencies(
        config_loader=config_loader,
        project_analyzer=project_analyzer,
        dockerfile_generator=dockerfile_generator,
        manifest_generator=manifest_generator,
        k8s_validator=k8s_validator,
        kubectl_dry_runner=kubectl_dry_runner,
        build_runner=build_runner,
        output_packager=output_packager,
    )
    return deps, mocks


# ─── 흐름 테스트 ────────────────────────────────────────────────────────────────


class TestFullPipelineFlow:
    """5-STEP 전체 흐름 — MagicMock 기반 격리 테스트."""

    def test_full_pipeline_success_returns_packaging_result(self, tmp_path: Path) -> None:
        """전체 5-STEP 실행 성공 시 PackagingResult 반환."""
        deps, mocks = _make_deps()
        pipeline = SkillPipeline(deps)

        result = pipeline.run(tmp_path / "project", tmp_path / "output")

        assert isinstance(result, PackagingResult)
        assert result.final_path is not None

    def test_step1_config_loader_called(self, tmp_path: Path) -> None:
        """STEP 1: config_loader.load() 호출 확인."""
        deps, mocks = _make_deps()
        pipeline = SkillPipeline(deps)

        pipeline.run(tmp_path / "project", tmp_path / "output")

        mocks["config_loader"].load.assert_called_once_with(tmp_path / "project")

    def test_step2_project_analyzer_called(self, tmp_path: Path) -> None:
        """STEP 2: project_analyzer.analyze() 호출 확인."""
        deps, mocks = _make_deps()
        pipeline = SkillPipeline(deps)

        pipeline.run(tmp_path / "project", tmp_path / "output")

        mocks["project_analyzer"].analyze.assert_called_once()

    def test_step3_dockerfile_and_manifests_generated(self, tmp_path: Path) -> None:
        """STEP 3: dockerfile_generator.generate() + 3개 manifest_generator 메서드 호출."""
        deps, mocks = _make_deps()
        pipeline = SkillPipeline(deps)

        pipeline.run(tmp_path / "project", tmp_path / "output")

        mocks["dockerfile_generator"].generate.assert_called_once()
        mocks["manifest_generator"].generate_deployment.assert_called_once()
        mocks["manifest_generator"].generate_service.assert_called_once()
        mocks["manifest_generator"].generate_serviceaccount.assert_called_once()

    def test_step4_k8s_validator_and_dry_runner_called_build_skip(self, tmp_path: Path) -> None:
        """STEP 4: k8s_validator.validate + kubectl_dry_runner.dry_run 호출 (build skip)."""
        deps, mocks = _make_deps(build_engine="skip")
        pipeline = SkillPipeline(deps)

        pipeline.run(tmp_path / "project", tmp_path / "output")

        mocks["k8s_validator"].validate.assert_called_once()
        mocks["kubectl_dry_runner"].dry_run.assert_called_once()
        mocks["build_runner"].build.assert_not_called()

    def test_step4_build_runner_called_when_engine_not_skip(self, tmp_path: Path) -> None:
        """STEP 4: build.engine=auto 이면 build_runner.build() 호출."""
        deps, mocks = _make_deps(
            config_raw={"build": {"engine": "auto", "image_tag": "myapp:1.0.0"}},
        )
        pipeline = SkillPipeline(deps)

        pipeline.run(tmp_path / "project", tmp_path / "output")

        mocks["build_runner"].build.assert_called_once()

    def test_step5_output_packager_write_called(self, tmp_path: Path) -> None:
        """STEP 5: output_packager.write() 호출 확인."""
        deps, mocks = _make_deps()
        pipeline = SkillPipeline(deps)

        pipeline.run(tmp_path / "project", tmp_path / "output")

        mocks["output_packager"].write.assert_called_once()

    def test_final_path_set_from_atomic_writer_commit(self, tmp_path: Path) -> None:
        """PackagingResult.final_path가 AtomicWriter.commit() 결과로 채워짐."""
        deps, mocks = _make_deps()
        pipeline = SkillPipeline(deps)

        result = pipeline.run(tmp_path / "project", tmp_path / "output")

        # final_path는 실제 AtomicWriter가 생성한 경로여야 함
        assert result.final_path is not None
        assert isinstance(result.final_path, Path)


# ─── AtomicWriter 통합 ──────────────────────────────────────────────────────────


class TestAtomicWriterIntegration:
    """AtomicWriter 컨텍스트 매니저 통합 검증."""

    def test_atomic_writer_staging_files_are_created(self, tmp_path: Path) -> None:
        """STEP 3에서 생성된 파일이 staging_dir에 실제로 존재해야 함."""
        deps, mocks = _make_deps()
        pipeline = SkillPipeline(deps)

        result = pipeline.run(tmp_path / "project", tmp_path / "output")

        # commit 후 최종 경로에 파일이 있어야 함
        assert result.final_path is not None
        final = result.final_path
        assert (final / "Dockerfile").exists()
        assert (final / "deployment.yaml").exists()
        assert (final / "service.yaml").exists()
        assert (final / "serviceaccount.yaml").exists()

    def test_exception_propagates_and_staging_cleaned(self, tmp_path: Path) -> None:
        """예외 발생 시 AtomicWriter cleanup 후 전파 — staging_dir가 남지 않음."""
        deps, mocks = _make_deps()

        # project_analyzer.analyze()에서 예외 발생 시뮬레이션
        mocks["project_analyzer"].analyze.side_effect = RuntimeError("analyze 실패")
        pipeline = SkillPipeline(deps)

        with pytest.raises(RuntimeError, match="analyze 실패"):
            pipeline.run(tmp_path / "project", tmp_path / "output")

        # staging_dir (.tmp-*)가 남지 않아야 함
        tmp_dirs = list(tmp_path.glob(".tmp-*"))
        assert tmp_dirs == [], f"고아 staging_dir 발견: {tmp_dirs}"


# ─── 에러 경로 ──────────────────────────────────────────────────────────────────


class TestErrorPaths:
    """BailOutError / UserAbort / ConfigWarning 처리."""

    def test_k8s_validation_bailout_raises_bailout_error(self, tmp_path: Path) -> None:
        """K8s 검증 3회 실패 → BailOutError raise + write_troubleshoot 호출."""
        deps, mocks = _make_deps(k8s_exit_code=1)
        # exit_code=1은 FAIL → retry_with_fix가 fix_attempt 호출
        # fix_attempt(스텁)는 applied=False → 즉시 bail-out
        pipeline = SkillPipeline(deps)

        with pytest.raises(BailOutError):
            pipeline.run(tmp_path / "project", tmp_path / "output")

        mocks["output_packager"].write_troubleshoot.assert_called_once()

    def test_user_abort_propagates(self, tmp_path: Path) -> None:
        """prompt_callback이 UserAbort raise → 전파."""
        deps, mocks = _make_deps()
        mocks["project_analyzer"].analyze.side_effect = UserAbort("사용자 취소")
        pipeline = SkillPipeline(deps)

        with pytest.raises(UserAbort):
            pipeline.run(tmp_path / "project", tmp_path / "output")

    def test_config_warnings_do_not_raise(self, tmp_path: Path) -> None:
        """ResolvedConfig.warnings가 있어도 graceful degrade — 예외 없이 완료."""
        deps, mocks = _make_deps(
            config_raw={"build": {"engine": "skip"}},
        )
        # warnings 포함 config 반환
        config_with_warnings = ResolvedConfig(
            raw={"build": {"engine": "skip"}},
            source_map={},
            warnings=["YAML 파싱 경고: 알 수 없는 키 'foo'"],
        )
        mocks["config_loader"].load.return_value = config_with_warnings
        pipeline = SkillPipeline(deps)

        result = pipeline.run(tmp_path / "project", tmp_path / "output")

        # 경고 있어도 정상 완료
        assert isinstance(result, PackagingResult)


# ─── HelpCatalog ────────────────────────────────────────────────────────────────


class TestHelpCatalog:
    """HelpCatalog 10개 term 조회 검증."""

    def setup_method(self) -> None:
        self.catalog = HelpCatalog()

    def test_lookup_app_name_returns_help_entry(self) -> None:
        """lookup('app_name') → HelpEntry 반환 (step=1, ko_short 포함)."""
        entry = self.catalog.lookup("app_name")
        assert entry is not None
        assert entry.term_id == "app_name"
        assert entry.step == 1
        assert entry.ko_short

    def test_lookup_unknown_returns_none(self) -> None:
        """lookup('unknown_term') → None."""
        result = self.catalog.lookup("unknown_term_xyz")
        assert result is None

    def test_for_step1_returns_six_entries(self) -> None:
        """for_step(1) → 6개 (F-02 매핑 6 term)."""
        entries = self.catalog.for_step(1)
        assert len(entries) == 6
        term_ids = {e.term_id for e in entries}
        expected = {"app_name", "port", "exposure", "namespace", "output_dir", "resource_hint"}
        assert term_ids == expected

    def test_for_step2_returns_three_entries(self) -> None:
        """for_step(2) → 3개 (actuator, multi_module, stateful)."""
        entries = self.catalog.for_step(2)
        assert len(entries) == 3
        term_ids = {e.term_id for e in entries}
        assert term_ids == {"actuator", "multi_module", "stateful"}

    def test_for_step_config_returns_one_entry(self) -> None:
        """for_step('config') → 1개 (build_engine)."""
        entries = self.catalog.for_step("config")
        assert len(entries) == 1
        assert entries[0].term_id == "build_engine"


# ─── MessagePolicy ──────────────────────────────────────────────────────────────


class TestMessagePolicy:
    """NFR-17 MessagePolicy 포맷 검증."""

    def test_format_question_with_original(self) -> None:
        """format_question(ko_text, original) → '한국어 (영어)' 형식."""
        result = MessagePolicy.format_question("앱 이름은 뭘로 할까요?", "app name")
        assert result == "앱 이름은 뭘로 할까요? (app name)"

    def test_format_question_without_original(self) -> None:
        """format_question(ko_text) → ko_text만."""
        result = MessagePolicy.format_question("앱 이름은 뭘로 할까요?")
        assert result == "앱 이름은 뭘로 할까요?"

    def test_format_error_with_en_detail(self) -> None:
        """format_error(ko_summary, en_detail) → 한국어 요약 + 영문 상세."""
        result = MessagePolicy.format_error("검증 실패", "Validation failed: rule SEC-001")
        assert "검증 실패" in result
        assert "(영문)" in result
        assert "Validation failed" in result

    def test_format_error_without_en_detail(self) -> None:
        """format_error(ko_summary) → ko_summary만."""
        result = MessagePolicy.format_error("검증 실패")
        assert result == "검증 실패"


# ─── STEP 1 prompt 경로 ─────────────────────────────────────────────────────────


class TestStep1PromptPath:
    """STEP 1 prompt_callback 경로 + 자동 모드 검증."""

    def test_prompt_callback_called_with_correct_help_term_ids(self, tmp_path: Path) -> None:
        """prompt_callback 제공 시 각 prompt가 올바른 help_term_id 포함."""
        deps, mocks = _make_deps()

        collected_term_ids: list[str | None] = []

        def fake_callback(req: PromptRequest) -> str:
            collected_term_ids.append(req.help_term_id)
            # 각 필드별 적절한 기본값 반환
            if req.help_term_id == "app_name":
                return "my-app"
            if req.help_term_id == "port":
                return "8080"
            if req.help_term_id == "exposure":
                return "ClusterIP"
            if req.help_term_id == "namespace":
                return "my-ns"
            if req.help_term_id == "output_dir":
                return "k8s-output"
            if req.help_term_id == "resource_hint":
                return "medium"
            return "default"

        pipeline = SkillPipeline(deps, prompt_callback=fake_callback)
        pipeline.run(tmp_path / "project", tmp_path / "output")

        # 6개 help_term_id가 모두 호출됐는지 확인
        expected_term_ids = {
            "app_name", "port", "exposure", "namespace", "output_dir", "resource_hint"
        }
        called_term_ids = {tid for tid in collected_term_ids if tid is not None}
        assert expected_term_ids.issubset(called_term_ids), (
            f"누락된 term_id: {expected_term_ids - called_term_ids}"
        )

    def test_auto_mode_no_prompt_callback_uses_config_defaults(self, tmp_path: Path) -> None:
        """prompt_callback=None → config.raw 또는 defaults에서 자동 채움."""
        deps, mocks = _make_deps(
            config_raw={
                "build": {"engine": "skip"},
                "app": {"name": "config-app", "port": 9090},
                "namespace": "config-ns",
            }
        )
        pipeline = SkillPipeline(deps)  # prompt_callback=None (자동 모드)
        pipeline.run(tmp_path / "project", tmp_path / "output")

        # project_analyzer.analyze가 호출됐다는 것 자체가 STEP 1 완료를 의미
        mocks["project_analyzer"].analyze.assert_called_once()

    def test_prompt_callback_none_does_not_call_prompt(self, tmp_path: Path) -> None:
        """prompt_callback=None이면 어떠한 prompt도 호출되지 않음."""
        deps, mocks = _make_deps()
        prompt_spy = MagicMock(name="prompt_callback")

        # prompt_callback 없이 실행 — 실제로 아무 콜백도 없어야 함
        pipeline = SkillPipeline(deps, prompt_callback=None)
        pipeline.run(tmp_path / "project", tmp_path / "output")

        # prompt_spy는 절대 호출되지 않음 (전달되지 않으므로)
        prompt_spy.assert_not_called()
