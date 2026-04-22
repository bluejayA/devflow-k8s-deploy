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
        # Important 6: sorted 적용 — 알파벳 순 정렬
        assert data["validation"]["skipped"] == sorted(["kubectl_dry_run", "container_build"])

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

    def test_write_statefulset_manifest_filenames_in_summary(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
        validation_outcome: ValidationOutcome,
    ) -> None:
        """manifest_filenames 전달 시 summary.json files에 statefulset.yaml 포함."""
        with patch("scripts.output_packager._utc_now_iso", return_value=FIXED_UTC):
            packager.write(
                staging_dir=staging_dir,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                image_reference="eclipse-temurin:21-jre-alpine",
                validation_outcome=validation_outcome,
                manifest_filenames=["statefulset.yaml", "service.yaml",
                                    "serviceaccount.yaml", "networkpolicy.yaml"],
            )
        data = json.loads((staging_dir / "summary.json").read_text())
        files = data["files"]
        assert "statefulset.yaml" in files
        assert "deployment.yaml" not in files


# ---------------------------------------------------------------------------
# Critical 1: troubleshoot redact 테스트
# ---------------------------------------------------------------------------


class TestTroubleshootRedact:
    """write_troubleshoot — 민감정보 redact 테스트 (Critical 1)."""

    @pytest.fixture()
    def staging_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "staging"
        d.mkdir()
        return d

    # 20. en_detail Bearer 토큰 → [REDACTED]
    def test_troubleshoot_redacts_bearer_token(
        self,
        packager: OutputPackager,
        staging_dir: Path,
    ) -> None:
        bailout = BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s 검증기",
            ko_summary="검증 실패",
            en_detail="error: Bearer ABCDEFGHIJKLMNOPQRSTUVWXYZ12345 unauthorized",
            attempts_log=[],
        )
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "[REDACTED]" in content
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ12345" not in content

    # 21. en_detail kubeconfig 경로 → [REDACTED]
    def test_troubleshoot_redacts_kubeconfig_path(
        self,
        packager: OutputPackager,
        staging_dir: Path,
    ) -> None:
        bailout = BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s 검증기",
            ko_summary="검증 실패",
            en_detail="kubectl --kubeconfig=/home/user/.kube/config apply failed",
            attempts_log=[],
        )
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "[REDACTED]" in content
        assert "/home/user/.kube/config" not in content

    # 22. en_detail JWT → [REDACTED]
    def test_troubleshoot_redacts_jwt(
        self,
        packager: OutputPackager,
        staging_dir: Path,
    ) -> None:
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature_token"
        bailout = BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s 검증기",
            ko_summary="검증 실패",
            en_detail=f"token={jwt} rejected by server",
            attempts_log=[],
        )
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "[REDACTED]" in content
        assert jwt not in content

    # 23. attempts_log fix_outcome.summary_ko 민감정보 redact
    def test_troubleshoot_redacts_fix_outcome_summary(
        self,
        packager: OutputPackager,
        staging_dir: Path,
    ) -> None:
        from scripts._shared.types import FixOutcome

        bailout = BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s 검증기",
            ko_summary="검증 실패",
            en_detail="validation error",
            attempts_log=[
                RetryAttempt(
                    attempt_number=1,
                    result=None,
                    error=None,
                    success=False,
                    fix_outcome=FixOutcome(
                        applied=True,
                        summary_ko="수정 시도: secret=my-secret-value 제거",
                    ),
                ),
            ],
        )
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "[REDACTED]" in content
        assert "my-secret-value" not in content

    # 24. 민감정보 없는 en_detail → 원문 그대로
    def test_troubleshoot_clean_detail_unchanged(
        self,
        packager: OutputPackager,
        staging_dir: Path,
    ) -> None:
        bailout = BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s 검증기",
            ko_summary="검증 실패",
            en_detail="Container securityContext is missing readOnlyRootFilesystem",
            attempts_log=[],
        )
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "Container securityContext is missing readOnlyRootFilesystem" in content
        assert "[REDACTED]" not in content


# ---------------------------------------------------------------------------
# Important 3: skip_reasons pass-through 테스트
# ---------------------------------------------------------------------------


class TestSkipReasonsPassthrough:
    """write_rationale_md — skip_reasons 런타임 사유 pass-through 테스트 (F-56, Important 3)."""

    @pytest.fixture()
    def staging_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "staging"
        d.mkdir()
        return d

    # 25. 런타임 skip_reasons 제공 시 rationale.md에 해당 값 포함
    def test_runtime_skip_reason_used_over_default(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        custom_reason = "kubectl v1.28 미설치: PATH에 kubectl 없음 (런타임 감지)"
        with patch("scripts.output_packager._utc_now_iso", return_value=FIXED_UTC):
            packager.write_rationale_md(
                path=staging_dir / "rationale.md",
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                skipped=["kubectl_dry_run"],
                skip_reasons={"kubectl_dry_run": custom_reason},
            )
        content = (staging_dir / "rationale.md").read_text()
        assert custom_reason in content
        # 기본 사유는 사용되지 않아야 함
        assert "설치되어 있지 않아" not in content

    # 26. skip_reasons 없는 키 → 기본값 fallback
    def test_default_reason_fallback_when_no_runtime_reason(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        with patch("scripts.output_packager._utc_now_iso", return_value=FIXED_UTC):
            packager.write_rationale_md(
                path=staging_dir / "rationale.md",
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                skipped=["kubectl_dry_run"],
                skip_reasons={},
            )
        content = (staging_dir / "rationale.md").read_text()
        assert "kubectl_dry_run" in content
        # 기본 사유가 포함되어야 함
        assert "설치되어 있지 않아" in content

    # 27. write()에서 validation_outcome.skip_reasons가 rationale.md에 반영
    def test_write_passes_skip_reasons_to_rationale(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        custom_reason = "빌드 엔진 도커 미설치: 런타임 감지"
        outcome = ValidationOutcome(
            k8s_report=validation_report,
            dry_run=None,
            build=None,
            skipped=["container_build"],
            skip_reasons={"container_build": custom_reason},
            bailed=False,
        )
        with patch("scripts.output_packager._utc_now_iso", return_value=FIXED_UTC):
            packager.write(
                staging_dir=staging_dir,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                image_reference="eclipse-temurin:21-jre-alpine",
                validation_outcome=outcome,
            )
        content = (staging_dir / "rationale.md").read_text()
        assert custom_reason in content


# ---------------------------------------------------------------------------
# Important 4: Markdown injection defense 테스트
# ---------------------------------------------------------------------------


class TestMarkdownInjectionDefense:
    """write_rationale_md — 구조화 필드 개행 차단 테스트 (Important 4)."""

    @pytest.fixture()
    def staging_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "staging"
        d.mkdir()
        return d

    # 28. inputs.app_name 개행 → ValueError
    def test_app_name_newline_raises(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        malicious_inputs = UserInputs(
            app_name="my-app\nevil: injected",
            port=8080,
            exposure="ClusterIP",
            namespace="my-team",
            output_dir=Path("/tmp/k8s-output"),
            resource_hint="medium",
        )
        with pytest.raises(ValueError, match="inputs.app_name"):
            packager.write_rationale_md(
                path=staging_dir / "rationale.md",
                inputs=malicious_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                skipped=[],
            )

    # 29. inputs.namespace 개행 → ValueError
    def test_namespace_newline_raises(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
        config_source_map: dict[str, str],
    ) -> None:
        malicious_inputs = UserInputs(
            app_name="my-app",
            port=8080,
            exposure="ClusterIP",
            namespace="my-team\nevil: injected",
            output_dir=Path("/tmp/k8s-output"),
            resource_hint="medium",
        )
        with pytest.raises(ValueError, match="inputs.namespace"):
            packager.write_rationale_md(
                path=staging_dir / "rationale.md",
                inputs=malicious_inputs,
                analysis=analysis_result,
                validation=validation_report,
                config_source_map=config_source_map,
                skipped=[],
            )

    # 30. write_troubleshoot — component_ko 개행 → ValueError
    def test_troubleshoot_component_ko_newline_raises(
        self,
        packager: OutputPackager,
        staging_dir: Path,
    ) -> None:
        bailout = BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s 검증기\nevil: injected",
            ko_summary="검증 실패",
            en_detail="some error",
            attempts_log=[],
        )
        with pytest.raises(ValueError, match="component_ko"):
            packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout)


# ---------------------------------------------------------------------------
# Important 5: image_reference 방어 검증 테스트
# ---------------------------------------------------------------------------


class TestImageReferenceValidation:
    """write_summary_json — validate_image_reference 진입부 호출 테스트 (Important 5)."""

    @pytest.fixture()
    def staging_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "staging"
        d.mkdir()
        return d

    # 31. latest 태그 → InvalidImageError
    def test_latest_image_raises_invalid_image_error(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        from scripts._shared.errors import InvalidImageError

        with pytest.raises(InvalidImageError, match="latest"):
            packager.write_summary_json(
                path=staging_dir / "summary.json",
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:latest",
                skipped=[],
                files=[],
            )

    # 32. 태그 누락 이미지 → InvalidImageError
    def test_image_without_tag_raises_invalid_image_error(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        from scripts._shared.errors import InvalidImageError

        with pytest.raises(InvalidImageError):
            packager.write_summary_json(
                path=staging_dir / "summary.json",
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin",
                skipped=[],
                files=[],
            )


# ---------------------------------------------------------------------------
# Important 6: JSON 결정성 테스트
# ---------------------------------------------------------------------------


class TestJsonDeterminism:
    """write_summary_json — JSON 결정성 테스트 (Important 6)."""

    @pytest.fixture()
    def staging_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "staging"
        d.mkdir()
        return d

    # 33. skipped 순서 다른 입력 → sorted 출력으로 동일
    def test_skipped_sorted_regardless_of_input_order(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path1 = staging_dir / "summary1.json"
        path2 = staging_dir / "summary2.json"
        with patch("scripts.output_packager._utc_now_iso", return_value=FIXED_UTC):
            packager.write_summary_json(
                path=path1,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=["z_last", "a_first", "m_middle"],
                files=["Dockerfile"],
            )
            packager.write_summary_json(
                path=path2,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=["m_middle", "z_last", "a_first"],
                files=["Dockerfile"],
            )
        data1 = json.loads(path1.read_text())
        data2 = json.loads(path2.read_text())
        assert data1["validation"]["skipped"] == data2["validation"]["skipped"]
        assert data1["validation"]["skipped"] == ["a_first", "m_middle", "z_last"]

    # 34. files 순서 다른 입력 → sorted 출력으로 동일
    def test_files_sorted_regardless_of_input_order(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        files_shuffled = ["service.yaml", "Dockerfile", "deployment.yaml"]
        files_sorted = sorted(files_shuffled)
        with patch("scripts.output_packager._utc_now_iso", return_value=FIXED_UTC):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=[],
                files=files_shuffled,
            )
        data = json.loads(path.read_text())
        assert data["files"] == files_sorted

    # 35. trailing newline 존재
    def test_trailing_newline_present(
        self,
        packager: OutputPackager,
        staging_dir: Path,
        user_inputs: UserInputs,
        analysis_result: AnalysisResult,
        validation_report: ValidationReport,
    ) -> None:
        path = staging_dir / "summary.json"
        with patch("scripts.output_packager._utc_now_iso", return_value=FIXED_UTC):
            packager.write_summary_json(
                path=path,
                inputs=user_inputs,
                analysis=analysis_result,
                validation=validation_report,
                image_reference="eclipse-temurin:21-jre-alpine",
                skipped=[],
                files=[],
            )
        raw = path.read_text()
        assert raw.endswith("\n")


# ---------------------------------------------------------------------------
# Important 7: troubleshoot 권장 조치 간소화 테스트
# ---------------------------------------------------------------------------


class TestTroubleshootGuidanceSimplified:
    """write_troubleshoot — 하드코딩 권장 조치 제거, 컴포넌트 힌트만 유지 테스트 (Important 7)."""

    @pytest.fixture()
    def staging_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "staging"
        d.mkdir()
        return d

    # 36. 하드코딩 "application-design.md §8" 문구 미존재
    def test_hardcoded_guidance_removed(
        self,
        packager: OutputPackager,
        staging_dir: Path,
    ) -> None:
        bailout = BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s 검증기",
            ko_summary="검증 실패",
            en_detail="validation error",
            attempts_log=[],
        )
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "application-design.md §8" not in content
        assert "수동 manifest 편집 후 재시도" not in content

    # 37. component_ko 힌트가 권장 조치 섹션에 포함
    def test_component_ko_hint_in_guidance(
        self,
        packager: OutputPackager,
        staging_dir: Path,
    ) -> None:
        bailout = BailOutContext(
            step_number=4,
            step_name_ko="검증",
            component_ko="K8s Dry-Run 검증기",
            ko_summary="검증 실패",
            en_detail="validation error",
            attempts_log=[],
        )
        packager.write_troubleshoot(staging_dir=staging_dir, bailout=bailout)
        content = (staging_dir / "troubleshoot.md").read_text()
        assert "K8s Dry-Run 검증기" in content
        assert "수동 개입 후 재실행 필요" in content
