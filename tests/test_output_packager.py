"""TDD: OutputPackager — summary.json v1 + rationale.md + troubleshoot.md.

RED → GREEN → REFACTOR 순서.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts._shared.types import (
    AnalysisResult,
    BailOutContext,
    BuildPlan,
    CheckResult,
    PackagingResult,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    RetryAttempt,
    StackDetectResult,
    StatefulnessSignal,
    UserInputs,
    ValidationOutcome,
    ValidationReport,
)
from scripts.output_packager import OutputPackager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXED_UTC = "2026-04-19T12:34:56Z"


@pytest.fixture()
def packager() -> OutputPackager:
    return OutputPackager()


@pytest.fixture()
def staging_dir(tmp_path: Path) -> Path:
    d = tmp_path / "staging"
    d.mkdir()
    return d


@pytest.fixture()
def user_inputs() -> UserInputs:
    return UserInputs(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="my-team",
        output_dir=Path("/tmp/k8s-output"),
        resource_hint="medium",
    )


@pytest.fixture()
def analysis_result() -> AnalysisResult:
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
            builder_image="eclipse-temurin:21-jdk-alpine",
            runner_image="eclipse-temurin:21-jre-alpine",
            build_cmd="./gradlew bootJar --no-daemon",
            artifact_path="build/libs/app.jar",
        ),
        probe_config=ProbeConfig(
            liveness=ProbeSpec(
                kind="http",
                path="/actuator/health/liveness",
                port=8080,
            ),
            readiness=ProbeSpec(
                kind="http",
                path="/actuator/health/readiness",
                port=8080,
            ),
        ),
        defaults=ResourceDefaults(
            cpu_request="100m",
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
            reasons=["DB/캐시 의존성 미감지"],
        ),
        gaps=[],
    )


@pytest.fixture()
def validation_report() -> ValidationReport:
    return ValidationReport(
        results=[
            CheckResult(
                rule_id="SEC-001",
                level="PASS",
                container="app",
                message_ko="보안 컨텍스트 OK",
                message_en="Security context OK",
                suggestion="",
            ),
            CheckResult(
                rule_id="SEC-002",
                level="PASS",
                container="app",
                message_ko="비루트 사용자 OK",
                message_en="Non-root user OK",
                suggestion="",
            ),
            CheckResult(
                rule_id="IMG-W01",
                level="WARN",
                container="app",
                message_ko="digest pinning 미사용",
                message_en="Digest pinning not used",
                suggestion="digest pinning 사용 권장",
            ),
        ],
        counts={"pass": 2, "warn": 1, "fail": 0},
        exit_code=1,
        skipped=[],
    )


@pytest.fixture()
def validation_report_with_skip() -> ValidationReport:
    return ValidationReport(
        results=[
            CheckResult(
                rule_id="SEC-001",
                level="PASS",
                container="app",
                message_ko="보안 컨텍스트 OK",
                message_en="Security context OK",
                suggestion="",
            ),
        ],
        counts={"pass": 1, "warn": 0, "fail": 0},
        exit_code=0,
        skipped=["kubectl_dry_run"],
    )


@pytest.fixture()
def config_source_map() -> dict[str, str]:
    return {
        "namespace": "project_config",
        "base_image": "builtin_default",
        "resources": "builtin_default",
        "stack": "auto-detect",
    }


# ---------------------------------------------------------------------------
# write_summary_json テスト
# ---------------------------------------------------------------------------


class TestWriteSummaryJson:
    """write_summary_json 단위 테스트."""

    # 1. v1 스키마 전체 필드 검증
    def test_v1_schema_all_fields(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=[],
                files=["Dockerfile", "deployment.yaml"],
            )
        data = json.loads(path.read_text())
        assert data["version"] == "v1"
        assert "generated_at" in data
        assert "stack" in data
        assert "app" in data
        assert "images" in data
        assert "namespace" in data
        assert "validation" in data
        assert "files" in data

    # 2. UTC ISO 8601 형식 (Z suffix, T 구분)
    def test_utc_iso8601_format(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=[],
                files=[],
            )
        data = json.loads(path.read_text())
        generated_at = data["generated_at"]
        assert generated_at == FIXED_UTC
        assert "T" in generated_at
        assert generated_at.endswith("Z")

    # 3. validation counts 정확
    def test_validation_counts(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=[],
                files=[],
            )
        data = json.loads(path.read_text())
        assert data["validation"]["pass"] == 2
        assert data["validation"]["warn"] == 1
        assert data["validation"]["fail"] == 0

    # 4. skipped 리스트 pass-through
    def test_skipped_list_passthrough(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=["kubectl_dry_run", "container_build"],
                files=[],
            )
        data = json.loads(path.read_text())
        assert data["validation"]["skipped"] == ["kubectl_dry_run", "container_build"]

    # 5. image digest pinning 분리 (repo:tag@sha256:... → digest 필드)
    def test_image_digest_pinning_parsed(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        digest = "a" * 64
        image_ref = f"eclipse-temurin:21-jre-alpine@sha256:{digest}"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference=image_ref,
                skipped=[],
                files=[],
            )
        data = json.loads(path.read_text())
        img = data["images"][0]
        assert img["repository"] == "eclipse-temurin"
        assert img["tag"] == "21-jre-alpine"
        assert img["digest"] == f"sha256:{digest}"

    # 6. image digest-only (repo@sha256:... → tag: null)
    def test_image_digest_only(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        digest = "b" * 64
        image_ref = f"eclipse-temurin@sha256:{digest}"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference=image_ref,
                skipped=[],
                files=[],
            )
        data = json.loads(path.read_text())
        img = data["images"][0]
        assert img["repository"] == "eclipse-temurin"
        assert img["tag"] is None
        assert img["digest"] == f"sha256:{digest}"

    # 7. files 리스트 정확 반영
    def test_files_list_accurate(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        files = ["Dockerfile", "deployment.yaml", "service.yaml", "serviceaccount.yaml"]
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=[],
                files=files,
            )
        data = json.loads(path.read_text())
        assert data["files"] == files

    # 8. JSON 유효성 (json.loads 파싱 가능)
    def test_json_parseable(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=[],
                files=["Dockerfile"],
            )
        raw = path.read_text()
        data = json.loads(raw)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# write_rationale_md テスト
# ---------------------------------------------------------------------------


class TestWriteRationaleMd:
    """write_rationale_md 단위 테스트."""

    # 9. 섹션 전수 존재 (헤더 ## ...)
    def test_all_sections_present(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        path = staging_dir / "rationale.md"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_rationale_md(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                skipped=[],
            )
        content = path.read_text()
        expected_sections = [
            "## 감지된 스택",
            "## 포트",
            "## 상태성",
            "## 네임스페이스",
            "## 베이스 이미지",
            "## 리소스",
            "## 프로브",
            "## 검증 결과 요약",
            "## 경고",
        ]
        for section in expected_sections:
            assert section in content, f"섹션 없음: {section}"

    # 10. 한국어 메시지 포함
    def test_korean_messages(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        path = staging_dir / "rationale.md"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_rationale_md(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                skipped=[],
            )
        content = path.read_text()
        # 한국어 키워드 포함 여부
        assert "스택" in content
        assert "포트" in content
        assert "상태성" in content

    # 11. NamespaceResolution.source 반영
    def test_namespace_source_reflected(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "rationale.md"
        source_map = {"namespace": "project_config"}
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_rationale_md(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=source_map,
                skipped=[],
            )
        content = path.read_text()
        assert "project_config" in content

    # 12. config_source_map 값 반영
    def test_config_source_map_reflected(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        path = staging_dir / "rationale.md"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_rationale_md(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                skipped=[],
            )
        content = path.read_text()
        assert "builtin_default" in content

    # 13. skipped 섹션 (F-56)
    def test_skipped_section_present(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report_with_skip: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        path = staging_dir / "rationale.md"
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write_rationale_md(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report_with_skip,
                config_source_map=config_source_map,
                skipped=["kubectl_dry_run"],
            )
        content = path.read_text()
        assert "## 스킵된 검증" in content
        assert "kubectl_dry_run" in content


# ---------------------------------------------------------------------------
# write_troubleshoot テスト
# ---------------------------------------------------------------------------


class TestWriteTroubleshoot:
    """write_troubleshoot 단위 테스트."""

    @pytest.fixture()
    def bailout_context(self) -> BailOutContext:
        return BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s 검증기",
            ko_summary="readOnlyRootFilesystem 누락으로 보안 검증 실패",
            en_detail="Container securityContext is missing readOnlyRootFilesystem: true",
            attempts_log=[
                RetryAttempt(
                    attempt_number=1,
                    result=None,
                    error=None,
                    success=False,
                    fix_outcome=None,
                ),
                RetryAttempt(
                    attempt_number=2,
                    result=None,
                    error=None,
                    success=False,
                    fix_outcome=None,
                ),
                RetryAttempt(
                    attempt_number=3,
                    result=None,
                    error=None,
                    success=False,
                    fix_outcome=None,
                ),
            ],
        )

    # 14. 상단 한국어 1-2줄 요약 (F-52)
    def test_korean_summary_at_top(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        bailout_context: BailOutContext,
    ) -> None:
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout_context)
        content = (staging_dir / "troubleshoot.md").read_text()
        # 상단에 한국어 요약 헤더
        assert content.startswith("# 막힌 지점")
        # 한국어 요약 포함
        assert "readOnlyRootFilesystem 누락으로 보안 검증 실패" in content
        # 한국어 단계명 포함
        assert "검증" in content
        assert "K8s 검증기" in content

    # 15. 시도 로그 전수 포함
    def test_all_attempts_in_log(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        bailout_context: BailOutContext,
    ) -> None:
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout_context)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "시도 1/3" in content or "1/3" in content
        assert "시도 2/3" in content or "2/3" in content
        assert "시도 3/3" in content or "3/3" in content

    # 16. BailOutContext.ko_summary + en_detail 구분
    def test_ko_summary_and_en_detail_separated(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        bailout_context: BailOutContext,
    ) -> None:
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout_context)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "readOnlyRootFilesystem 누락으로 보안 검증 실패" in content
        assert "Container securityContext is missing readOnlyRootFilesystem: true" in content


# ---------------------------------------------------------------------------
# write (통합) テスト
# ---------------------------------------------------------------------------


class TestWrite:
    """write 통합 테스트."""

    @pytest.fixture()
    def validation_outcome(
        self, validation_report: ValidationReport
    ) -> ValidationOutcome:
        return ValidationOutcome(
            k8s_report=validation_report,
            dry_run=None,
            build=None,
            skipped=[],
            skip_reasons={},
            bailed=False,
        )

    # 17. staging_dir에 summary.json + rationale.md 생성
    def test_write_creates_files(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
        validation_outcome: ValidationOutcome,
    ) -> None:
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            result = packager.write(
                staging_dir=staging_dir,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                image_reference="eclipse-temurin:21-jre-alpine",
                validation_outcome=validation_outcome,
            )
        assert (staging_dir / "summary.json").exists()
        assert (staging_dir / "rationale.md").exists()
        assert isinstance(result, PackagingResult)

    # 18. PackagingResult의 files 리스트 정확
    def test_packaging_result_files(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
        validation_outcome: ValidationOutcome,
    ) -> None:
        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            result = packager.write(
                staging_dir=staging_dir,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                image_reference="eclipse-temurin:21-jre-alpine",
                validation_outcome=validation_outcome,
            )
        assert "summary.json" in result.files_written
        assert "rationale.md" in result.files_written

    # 19. 결정론 (같은 입력 → summary.json 바이트 동일, generated_at은 monkeypatch 고정)
    def test_determinism(
        self,
        packager: OutputPackager,
        tmp_path: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
        validation_outcome: ValidationOutcome,
    ) -> None:
        staging1 = tmp_path / "run1"
        staging1.mkdir()
        staging2 = tmp_path / "run2"
        staging2.mkdir()

        with patch(
            "scripts.output_packager._utc_now_iso", return_value=FIXED_UTC
        ):
            packager.write(
                staging_dir=staging1,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                image_reference="eclipse-temurin:21-jre-alpine",
                validation_outcome=validation_outcome,
            )
            packager.write(
                staging_dir=staging2,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                image_reference="eclipse-temurin:21-jre-alpine",
                validation_outcome=validation_outcome,
            )

        data1 = (staging1 / "summary.json").read_bytes()
        data2 = (staging2 / "summary.json").read_bytes()
        assert data1 == data2
