"""ProjectAnalyzer 단위 테스트 (TDD).

시나리오:
1. analyze — 기본 경로 (JVM Spring Boot, forced_stack, auto_detect)
2. UnknownStackError — 빈 디렉토리
3. multi-module — Gradle settings, prompt_callback, auto-select, abort, Maven
4. statefulness — JPA, datasource URL, Kafka, Redis, stateless, 한국어 reasons
5. prompt_callback 테스트 모드 — gaps 기록
6. _detect_stack — 등록 순서대로 시도
7. AnalysisResult 필드 완전성
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts._shared.errors import MultiModuleAbort, UnknownStackError, UnsupportedStackError
from scripts._shared.types import (
    AnalysisResult,
    BuildPlan,
    ModuleInfo,
    ProbeConfig,
    ProbeSpec,
    PromptRequest,
    ResolvedConfig,
    ResourceDefaults,
    StackDecision,
    StackDetectResult,
    StatefulnessSignal,
)
from scripts.config_loader import ConfigLoader
from scripts.project_analyzer import ProjectAnalyzer
from scripts.stacks.jvm import JvmStackModule

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    """부모 디렉토리를 포함해 파일 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_resolved_config(raw: dict[str, Any] | None = None) -> ResolvedConfig:
    """테스트용 최소 ResolvedConfig 생성."""
    if raw is None:
        raw = {"stack": "auto"}
    return ResolvedConfig(
        raw=raw,
        source_map={"stack": "builtin_default"},
        warnings=[],
        layer_raws={},
    )


def _make_config_loader_auto() -> ConfigLoader:
    """stack=auto를 반환하는 ConfigLoader mock."""
    loader = MagicMock(spec=ConfigLoader)
    loader.stack_decision.return_value = StackDecision(forced_stack=None, source="auto")
    return loader


def _make_config_loader_forced(stack: str = "jvm") -> ConfigLoader:
    """forced_stack을 반환하는 ConfigLoader mock."""
    loader = MagicMock(spec=ConfigLoader)
    loader.stack_decision.return_value = StackDecision(
        forced_stack=stack, source="project_config"
    )
    return loader


def _spring_boot3_gradle(tmp_path: Path) -> Path:
    """Gradle KTS + Spring Boot 3 프로젝트 생성."""
    _write(
        tmp_path / "build.gradle.kts",
        """
plugins {
    id("org.springframework.boot") version "3.2.0"
    id("io.spring.dependency-management") version "1.1.4"
    kotlin("jvm") version "1.9.22"
}
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
}
""",
    )
    _write(
        tmp_path / "src/main/resources/application.yml",
        """
server:
  port: 8080
management:
  endpoints:
    web:
      exposure:
        include: health
""",
    )
    return tmp_path


def _spring_boot2_gradle(tmp_path: Path) -> Path:
    """Gradle Groovy + Spring Boot 2 프로젝트 생성."""
    _write(
        tmp_path / "build.gradle",
        """
plugins {
    id 'org.springframework.boot' version '2.7.18'
    id 'io.spring.dependency-management' version '1.1.0'
    id 'java'
}
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-web'
}
""",
    )
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# 1. analyze — 기본 경로
# ──────────────────────────────────────────────────────────────────────────────


class TestAnalyzeBasicPath:
    def test_analyze_jvm_spring_boot_project(self, tmp_path: Path) -> None:
        """단일 모듈 Spring Boot 프로젝트 분석 결과 검증."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert isinstance(result, AnalysisResult)
        assert result.stack == "jvm"
        assert result.detect_result.framework == "spring-boot"
        assert result.detect_result.version == "3.2.0"
        assert result.detect_result.build_system == "gradle"
        assert result.build_plan is not None
        assert result.probe_config is not None
        assert result.defaults is not None
        assert isinstance(result.gaps, list)

    def test_analyze_forced_stack_from_config(self, tmp_path: Path) -> None:
        """config.raw에 stack: jvm 명시 → forced_stack="jvm" 사용."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_forced("jvm"),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config({"stack": "jvm"})
        result = analyzer.analyze(tmp_path, config)

        assert result.stack == "jvm"
        assert result.detect_result.framework == "spring-boot"

    def test_analyze_auto_detects_jvm(self, tmp_path: Path) -> None:
        """config에 stack 없음 (auto) → _detect_stack이 JvmStackModule 선택."""
        _spring_boot2_gradle(tmp_path)

        loader = _make_config_loader_auto()
        analyzer = ProjectAnalyzer(
            config_loader=loader,
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert result.stack == "jvm"
        # auto detect 시 stack_decision은 forced_stack=None으로 호출
        call_args = loader.stack_decision.call_args
        assert call_args is not None
        decision: StackDecision = loader.stack_decision.return_value
        assert decision.forced_stack is None


# ──────────────────────────────────────────────────────────────────────────────
# 2. UnknownStackError
# ──────────────────────────────────────────────────────────────────────────────


class TestUnknownStackError:
    def test_analyze_empty_dir_raises_unknown_stack_error(self, tmp_path: Path) -> None:
        """빈 디렉토리 (감지 불가) → UnknownStackError."""
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        with pytest.raises(UnknownStackError):
            analyzer.analyze(tmp_path, config)

    def test_detect_stack_empty_registry_raises_unknown_stack_error(
        self, tmp_path: Path
    ) -> None:
        """빈 stack_registry → UnknownStackError."""
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={},
        )
        config = _make_resolved_config()
        with pytest.raises(UnknownStackError):
            analyzer.analyze(tmp_path, config)


# ──────────────────────────────────────────────────────────────────────────────
# 3. multi-module
# ──────────────────────────────────────────────────────────────────────────────


class TestMultiModule:
    def test_multi_module_gradle_settings_detected(self, tmp_path: Path) -> None:
        """settings.gradle에 include 'api','core' → 2개 ModuleInfo 감지."""
        _write(
            tmp_path / "settings.gradle",
            "include 'api', 'core'\n",
        )
        _write(tmp_path / "build.gradle", "plugins { id 'java' }\n")
        # api 서브모듈에 빌드 파일 생성
        _write(
            tmp_path / "api/build.gradle",
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        modules = analyzer._detect_multi_modules(tmp_path, "jvm")

        assert len(modules) == 2
        names = [m.name for m in modules]
        assert "api" in names
        assert "core" in names

    def test_multi_module_with_prompt_callback(self, tmp_path: Path) -> None:
        """prompt_callback이 'api' 반환 → api 모듈 선택."""
        _write(
            tmp_path / "settings.gradle",
            "include 'api', 'core'\n",
        )
        _write(
            tmp_path / "build.gradle",
            "plugins { id 'org.springframework.boot' version '3.2.0'; id 'java' }\n",
        )
        _write(
            tmp_path / "api/build.gradle",
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n",
        )
        _write(tmp_path / "core/build.gradle", "plugins { id 'java' }\n")

        callback = MagicMock(return_value="api")
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=callback,
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert result.selected_module is not None
        assert result.selected_module.name == "api"
        # callback이 호출됐는지 확인
        callback.assert_called_once()
        req: PromptRequest = callback.call_args[0][0]
        assert req.kind == "select"
        assert "api" in req.options  # type: ignore[operator]

    def test_multi_module_without_callback_auto_selects_first_with_gap(
        self, tmp_path: Path
    ) -> None:
        """prompt_callback=None → 첫 모듈 자동 선택 + gaps에 기록."""
        _write(
            tmp_path / "settings.gradle",
            "include 'api', 'core'\n",
        )
        _write(
            tmp_path / "build.gradle",
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=None,
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert result.selected_module is not None
        assert result.selected_module.name == "api"  # 첫 번째 모듈
        # gaps에 auto-select 기록 확인
        assert any("auto-selected" in g for g in result.gaps)
        assert any("api" in g for g in result.gaps)

    def test_multi_module_user_abort_raises_multi_module_abort(
        self, tmp_path: Path
    ) -> None:
        """prompt_callback이 '취소' 반환 → MultiModuleAbort."""
        _write(
            tmp_path / "settings.gradle",
            "include 'api', 'core'\n",
        )
        _write(
            tmp_path / "build.gradle",
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n",
        )

        callback = MagicMock(return_value="취소")
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=callback,
        )
        config = _make_resolved_config()
        with pytest.raises(MultiModuleAbort):
            analyzer.analyze(tmp_path, config)

    def test_multi_module_maven_pom_modules_detected(self, tmp_path: Path) -> None:
        """Maven pom.xml <modules> 섹션으로 multi-module 감지."""
        pom_content = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>parent</artifactId>
    <version>1.0.0</version>
    <packaging>pom</packaging>
    <modules>
        <module>api-service</module>
        <module>core-lib</module>
    </modules>
</project>
"""
        _write(tmp_path / "pom.xml", pom_content)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        modules = analyzer._detect_multi_modules(tmp_path, "jvm")

        assert len(modules) == 2
        names = [m.name for m in modules]
        assert "api-service" in names
        assert "core-lib" in names

    def test_multi_module_kotlin_dsl_settings_detected(self, tmp_path: Path) -> None:
        """settings.gradle.kts KTS 형식 include 파싱."""
        _write(
            tmp_path / "settings.gradle.kts",
            'include("api", "core", "common")\n',
        )
        _write(
            tmp_path / "build.gradle.kts",
            'plugins { id("org.springframework.boot") version "3.2.0" }\n',
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        modules = analyzer._detect_multi_modules(tmp_path, "jvm")

        assert len(modules) == 3
        names = [m.name for m in modules]
        assert "api" in names
        assert "core" in names
        assert "common" in names

    def test_multi_module_is_likely_app_flag(self, tmp_path: Path) -> None:
        """api, core 모듈 — is_likely_app 판정 확인."""
        _write(
            tmp_path / "settings.gradle",
            "include 'my-api', 'my-core'\n",
        )
        _write(tmp_path / "build.gradle", "plugins { id 'java' }\n")

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        modules = analyzer._detect_multi_modules(tmp_path, "jvm")

        api_module = next(m for m in modules if m.name == "my-api")
        core_module = next(m for m in modules if m.name == "my-core")
        assert api_module.is_likely_app is True
        assert core_module.is_likely_app is False


# ──────────────────────────────────────────────────────────────────────────────
# 4. statefulness
# ──────────────────────────────────────────────────────────────────────────────


class TestStatefulness:
    def test_statefulness_jpa_dependency_high(self, tmp_path: Path) -> None:
        """spring-boot-starter-data-jpa 포함 → is_stateful=True, confidence='high'."""
        _write(
            tmp_path / "build.gradle.kts",
            """
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-data-jpa")
}
""",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert signal.is_stateful is True
        assert signal.confidence == "high"
        assert len(signal.reasons) > 0

    def test_statefulness_datasource_url_high(self, tmp_path: Path) -> None:
        """application.yml에 spring.datasource.url → is_stateful=True, confidence='high'."""
        _write(tmp_path / "build.gradle.kts", "dependencies {}\n")
        _write(
            tmp_path / "src/main/resources/application.yml",
            """
spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/mydb
    username: user
    password: pass
""",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert signal.is_stateful is True
        assert signal.confidence == "high"

    def test_statefulness_datasource_url_in_properties(self, tmp_path: Path) -> None:
        """application.properties에 spring.datasource.url → is_stateful=True, confidence='high'."""
        _write(tmp_path / "build.gradle.kts", "dependencies {}\n")
        _write(
            tmp_path / "src/main/resources/application.properties",
            "spring.datasource.url=jdbc:h2:mem:testdb\n",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert signal.is_stateful is True
        assert signal.confidence == "high"

    def test_statefulness_kafka_medium(self, tmp_path: Path) -> None:
        """spring-kafka 의존성 → is_stateful=True, confidence='medium'."""
        _write(
            tmp_path / "build.gradle.kts",
            """
dependencies {
    implementation("org.springframework.kafka:spring-kafka")
}
""",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert signal.is_stateful is True
        assert signal.confidence == "medium"

    def test_statefulness_redis_medium(self, tmp_path: Path) -> None:
        """spring-data-redis 의존성 → is_stateful=True, confidence='medium'."""
        _write(
            tmp_path / "build.gradle.kts",
            """
dependencies {
    implementation("org.springframework.data:spring-data-redis")
}
""",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert signal.is_stateful is True
        assert signal.confidence == "medium"

    def test_statefulness_stateless_project(self, tmp_path: Path) -> None:
        """아무 시그널 없음 → is_stateful=False, confidence='high'."""
        _write(
            tmp_path / "build.gradle.kts",
            """
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
}
""",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert signal.is_stateful is False
        assert signal.confidence == "high"
        assert signal.reasons == []

    def test_statefulness_reasons_in_korean(self, tmp_path: Path) -> None:
        """reasons 리스트가 한국어 포함."""
        _write(
            tmp_path / "build.gradle.kts",
            """
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-data-jpa")
}
""",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert len(signal.reasons) > 0
        # 최소 하나의 reason이 한국어 포함 (ASCII 아닌 문자 포함 여부)
        has_korean = any(
            any(ord(c) > 127 for c in reason) for reason in signal.reasons
        )
        assert has_korean, f"reasons에 한국어가 없음: {signal.reasons}"

    def test_statefulness_mybatis_dependency_high(self, tmp_path: Path) -> None:
        """mybatis 의존성 → confidence='high'."""
        _write(
            tmp_path / "build.gradle",
            "implementation 'org.mybatis.spring.boot:mybatis-spring-boot-starter:3.0.0'\n",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert signal.confidence == "high"
        assert signal.is_stateful is True

    def test_statefulness_high_and_medium_combined(self, tmp_path: Path) -> None:
        """JPA + Redis 함께 → is_stateful=True, confidence='high'."""
        _write(
            tmp_path / "build.gradle.kts",
            """
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-data-jpa")
    implementation("org.springframework.boot:spring-boot-starter-data-redis")
}
""",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        signal = analyzer._detect_statefulness(tmp_path, None)

        assert signal.is_stateful is True
        assert signal.confidence == "high"
        assert len(signal.reasons) >= 2  # JPA + Redis 둘 다 포함


# ──────────────────────────────────────────────────────────────────────────────
# 5. prompt_callback 테스트 모드 (gaps 기록)
# ──────────────────────────────────────────────────────────────────────────────


class TestPromptCallbackTestMode:
    def test_analyze_without_prompt_callback_records_gaps(self, tmp_path: Path) -> None:
        """prompt_callback=None + multi-module → gaps에 auto-select 기록."""
        _write(
            tmp_path / "settings.gradle",
            "include 'web-api', 'core'\n",
        )
        _write(
            tmp_path / "build.gradle",
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n",
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=None,
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert len(result.gaps) > 0
        assert any("auto-selected" in g.lower() for g in result.gaps)

    def test_analyze_no_gaps_for_single_module(self, tmp_path: Path) -> None:
        """단일 모듈 프로젝트 → gaps 비어 있음."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        # 단일 모듈이면 auto-select gap 없어야 함
        assert not any("auto-selected" in g for g in result.gaps)


# ──────────────────────────────────────────────────────────────────────────────
# 6. _detect_stack — 등록 순서
# ──────────────────────────────────────────────────────────────────────────────


class TestDetectStack:
    def test_detect_stack_tries_registered_modules_in_order(
        self, tmp_path: Path
    ) -> None:
        """stack_registry에 여러 모듈 있으면 순서대로 시도, 첫 매치 반환."""
        # mock 모듈 두 개 생성
        mock_first = MagicMock(spec=JvmStackModule)
        mock_first.detect.return_value = None  # 첫 번째는 감지 실패

        mock_second = MagicMock(spec=JvmStackModule)
        second_detect = StackDetectResult(
            port=8080,
            entrypoint="",
            framework="spring-boot",
            version="3.2.0",
            build_system="gradle",
            actuator_enabled=False,
        )
        mock_second.detect.return_value = second_detect
        mock_second.build_plan.return_value = BuildPlan(
            builder_image="eclipse-temurin:21-jdk-alpine",
            runner_image="eclipse-temurin:21-jre-alpine",
            build_cmd="gradle bootJar",
            artifact_path="build/libs/*.jar",
        )
        mock_second.probe_plan.return_value = ProbeConfig(
            liveness=ProbeSpec(kind="tcp", path=None, port=8080),
            readiness=ProbeSpec(kind="tcp", path=None, port=8080),
        )
        mock_second.defaults.return_value = ResourceDefaults(
            cpu_request="100m",
            memory_request="512Mi",
            cpu_limit="1000m",
            memory_limit="1Gi",
            writable_paths=["/tmp", "/var/log"],
        )
        mock_second.artifact_locator.return_value = []

        registry = {"first_stack": mock_first, "second_stack": mock_second}
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry=registry,
        )

        gaps: list[str] = []
        bundle = analyzer._detect_stack(tmp_path, gaps)
        assert bundle.stack_name == "second_stack"
        mock_first.detect.assert_called_once_with(tmp_path)
        mock_second.detect.assert_called_once_with(tmp_path)

    def test_detect_stack_no_match_raises_unknown_stack_error(
        self, tmp_path: Path
    ) -> None:
        """모든 모듈이 None 반환 → UnknownStackError."""
        mock_module = MagicMock(spec=JvmStackModule)
        mock_module.detect.return_value = None

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": mock_module},
        )
        gaps: list[str] = []
        with pytest.raises(UnknownStackError):
            analyzer._detect_stack(tmp_path, gaps)


# ──────────────────────────────────────────────────────────────────────────────
# 7. AnalysisResult 필드 완전성
# ──────────────────────────────────────────────────────────────────────────────


class TestAnalysisResultCompleteness:
    def test_analysis_result_contains_stack_detect_result(
        self, tmp_path: Path
    ) -> None:
        """AnalysisResult에 detect_result, build_plan, probe_config, defaults 모두 채워짐."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert isinstance(result.detect_result, StackDetectResult)
        assert isinstance(result.build_plan, BuildPlan)
        assert isinstance(result.probe_config, ProbeConfig)
        assert isinstance(result.defaults, ResourceDefaults)
        assert result.detect_result.framework == "spring-boot"
        assert result.build_plan.builder_image != ""
        assert result.build_plan.runner_image != ""

    def test_analysis_result_statefulness_signal_attached(
        self, tmp_path: Path
    ) -> None:
        """AnalysisResult에 statefulness 필드가 StatefulnessSignal 타입으로 포함."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert isinstance(result.statefulness, StatefulnessSignal)
        assert result.statefulness.confidence in ("high", "medium", "low")
        assert isinstance(result.statefulness.is_stateful, bool)
        assert isinstance(result.statefulness.reasons, list)

    def test_analysis_result_gaps_is_list_even_when_empty(
        self, tmp_path: Path
    ) -> None:
        """gaps는 항상 list 타입 (단일 모듈이어도 빈 list)."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert isinstance(result.gaps, list)

    def test_analysis_result_selected_module_none_for_single(
        self, tmp_path: Path
    ) -> None:
        """단일 모듈 프로젝트 → selected_module=None."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert result.selected_module is None

    def test_analysis_result_artifact_paths_is_list(self, tmp_path: Path) -> None:
        """artifact_paths는 list 타입 (빌드 전이면 빈 list)."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        result = analyzer.analyze(tmp_path, config)

        assert isinstance(result.artifact_paths, list)


# ──────────────────────────────────────────────────────────────────────────────
# 8. multi-module 힌트 검증
# ──────────────────────────────────────────────────────────────────────────────


class TestMultiModuleHint:
    def test_prompt_request_contains_korean_hint(self, tmp_path: Path) -> None:
        """multi-module 선택 프롬프트에 한국어 힌트 포함."""
        _write(
            tmp_path / "settings.gradle",
            "include 'api', 'core'\n",
        )
        _write(
            tmp_path / "build.gradle",
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n",
        )

        received_requests: list[PromptRequest] = []

        def callback(req: PromptRequest) -> str:
            received_requests.append(req)
            return "api"

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=callback,
        )
        config = _make_resolved_config()
        analyzer.analyze(tmp_path, config)

        assert len(received_requests) == 1
        req = received_requests[0]
        # 한국어 힌트 포함 확인
        assert any(ord(c) > 127 for c in req.ko_text)
        # 모듈 옵션 포함 확인
        assert req.options is not None
        assert "api" in req.options

    def test_select_module_cancel_keywords(self, tmp_path: Path) -> None:
        """cancel / q 등 취소 키워드 → MultiModuleAbort."""
        modules = [
            ModuleInfo(name="api", path=tmp_path / "api", is_likely_app=True),
            ModuleInfo(name="core", path=tmp_path / "core", is_likely_app=False),
        ]
        gaps: list[str] = []

        for keyword in ["cancel", "q", "quit", "exit"]:
            analyzer = ProjectAnalyzer(
                config_loader=_make_config_loader_auto(),
                stack_registry={"jvm": JvmStackModule()},
                prompt_callback=MagicMock(return_value=keyword),
            )
            with pytest.raises(MultiModuleAbort):
                analyzer._select_module(modules, gaps)


# ──────────────────────────────────────────────────────────────────────────────
# 9. Critical: Path Traversal 방어
# ──────────────────────────────────────────────────────────────────────────────


class TestPathTraversalDefense:
    def test_path_traversal_dotdot_in_module_name_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """'../secrets' 같은 모듈 이름은 skip — project_root 밖 경로 방어."""
        _write(
            tmp_path / "settings.gradle",
            "include '..', '../secrets'\n",
        )
        _write(tmp_path / "build.gradle", "plugins { id 'java' }\n")

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        # _project_root 설정을 위해 analyze() 대신 직접 _build_module_info_list 호출
        # (analyze()는 UnknownStack 등으로 중단될 수 있으므로)
        analyzer._project_root = tmp_path.resolve()
        result = analyzer._build_module_info_list(tmp_path, ["../secrets", ".."])
        analyzer._project_root = None

        # 경로 탈출 모듈은 모두 제거됨
        assert result == []

    def test_path_traversal_absolute_path_module_name_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """/etc/passwd 같은 절대경로 모듈 이름은 skip."""
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        analyzer._project_root = tmp_path.resolve()
        result = analyzer._build_module_info_list(tmp_path, ["/etc/passwd", "/tmp"])
        analyzer._project_root = None

        assert result == []

    def test_path_traversal_nul_char_module_name_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """NUL 문자 포함 모듈 이름은 skip."""
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        analyzer._project_root = tmp_path.resolve()
        result = analyzer._build_module_info_list(tmp_path, ["api\x00evil", "core"])
        analyzer._project_root = None

        # NUL 포함 이름은 skip, 유효한 'core'는 유지
        names = [m.name for m in result]
        assert "api\x00evil" not in names
        assert "core" in names

    def test_path_traversal_max_modules_truncated(self, tmp_path: Path) -> None:
        """모듈 수가 _MAX_MODULES 초과 시 truncate."""
        from scripts.project_analyzer import _MAX_MODULES

        many_names = [f"module-{i}" for i in range(_MAX_MODULES + 10)]
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        analyzer._project_root = tmp_path.resolve()
        result = analyzer._build_module_info_list(tmp_path, many_names)
        analyzer._project_root = None

        assert len(result) <= _MAX_MODULES

    def test_valid_module_names_are_accepted(self, tmp_path: Path) -> None:
        """정상 모듈 이름(api, my-module, sub/module 등)은 통과."""
        valid_names = ["api", "my-module", "sub.module", "module_a"]
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        analyzer._project_root = tmp_path.resolve()
        result = analyzer._build_module_info_list(tmp_path, valid_names)
        analyzer._project_root = None

        assert len(result) == len(valid_names)


# ──────────────────────────────────────────────────────────────────────────────
# 9-b. Kotlin DSL colon-prefix 모듈 이름 지원
# ──────────────────────────────────────────────────────────────────────────────


class TestColonPrefixModuleNames:
    def test_multi_module_kotlin_dsl_colon_prefix_detected(
        self, tmp_path: Path
    ) -> None:
        """settings.gradle.kts include(":api", ":core", ":common") → 3개 감지, 이름은 콜론 없이."""
        _write(
            tmp_path / "settings.gradle.kts",
            'include(":api", ":core", ":common")\n',
        )
        _write(
            tmp_path / "build.gradle.kts",
            'plugins { id("org.springframework.boot") version "3.2.0" }\n',
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        modules = analyzer._detect_multi_modules(tmp_path, "jvm")

        assert len(modules) == 3
        names = [m.name for m in modules]
        assert "api" in names
        assert "core" in names
        assert "common" in names
        # 콜론이 이름에 남으면 안 됨
        for name in names:
            assert not name.startswith(":")

    def test_multi_module_groovy_colon_prefix_detected(
        self, tmp_path: Path
    ) -> None:
        """settings.gradle Groovy 에 include ':api', ':core' → 2개 감지, 이름은 콜론 없이."""
        _write(
            tmp_path / "settings.gradle",
            "include ':api', ':core'\n",
        )
        _write(tmp_path / "build.gradle", "plugins { id 'java' }\n")

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        modules = analyzer._detect_multi_modules(tmp_path, "jvm")

        assert len(modules) == 2
        names = [m.name for m in modules]
        assert "api" in names
        assert "core" in names
        for name in names:
            assert not name.startswith(":")

    def test_nested_colon_module_name_rejected(
        self, tmp_path: Path
    ) -> None:
        """include(":foo:bar") — 중첩 모듈은 v0.1.0 미지원 → 거부(빈 결과)."""
        _write(
            tmp_path / "settings.gradle.kts",
            'include(":foo:bar")\n',
        )
        _write(
            tmp_path / "build.gradle.kts",
            'plugins { id("org.springframework.boot") version "3.2.0" }\n',
        )

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        modules = analyzer._detect_multi_modules(tmp_path, "jvm")

        # 중첩 모듈은 거부 → 빈 결과
        assert modules == []


# ──────────────────────────────────────────────────────────────────────────────
# 10. UnsupportedStackError for forced_stack not in registry
# ──────────────────────────────────────────────────────────────────────────────


class TestUnsupportedStackError:
    def test_analyze_forced_stack_not_in_registry_raises_unsupported_stack_error(
        self, tmp_path: Path
    ) -> None:
        """forced_stack이 registry에 없으면 UnsupportedStackError."""
        _write(tmp_path / "build.gradle.kts", "plugins {}\n")

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_forced("python"),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config({"stack": "python"})

        with pytest.raises(UnsupportedStackError, match="python"):
            analyzer.analyze(tmp_path, config)


# ──────────────────────────────────────────────────────────────────────────────
# 11. prompt_callback 응답 검증
# ──────────────────────────────────────────────────────────────────────────────


class TestPromptCallbackValidation:
    def _make_modules(self, tmp_path: Path) -> list[ModuleInfo]:
        return [
            ModuleInfo(name="api", path=tmp_path / "api", is_likely_app=True),
            ModuleInfo(name="core", path=tmp_path / "core", is_likely_app=False),
        ]

    def test_non_string_answer_raises_multi_module_abort(self, tmp_path: Path) -> None:
        """callback이 str이 아닌 값 반환 → MultiModuleAbort."""
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=MagicMock(return_value=123),
        )
        with pytest.raises(MultiModuleAbort, match="문자열이 아님"):
            analyzer._select_module(self._make_modules(tmp_path), [])

    def test_too_long_answer_raises_multi_module_abort(self, tmp_path: Path) -> None:
        """256자 초과 응답 → MultiModuleAbort."""
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=MagicMock(return_value="a" * 300),
        )
        with pytest.raises(MultiModuleAbort, match="너무 김"):
            analyzer._select_module(self._make_modules(tmp_path), [])

    def test_control_chars_stripped_from_answer(self, tmp_path: Path) -> None:
        """ANSI escape 등 제어문자가 포함된 응답에서 모듈명 추출."""
        # 제어문자 제거 후 'api' 남음 → api 모듈 선택
        answer_with_ctrl = "ap\x1b[0mi"  # 'api' + ANSI reset
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
            prompt_callback=MagicMock(return_value=answer_with_ctrl),
        )
        # 제어문자 제거 후 'api' 남음 → api 선택
        result = analyzer._select_module(self._make_modules(tmp_path), [])
        assert result.name == "api"


# ──────────────────────────────────────────────────────────────────────────────
# 12. multi-module statefulness — 루트 + 선택 모듈 양쪽 스캔
# ──────────────────────────────────────────────────────────────────────────────


class TestStatefulnessMultiModule:
    def test_statefulness_multi_module_jpa_in_root_detected(
        self, tmp_path: Path
    ) -> None:
        """루트 build.gradle에 JPA, 모듈 디렉토리는 깨끗 → stateful(high) 감지."""
        # 루트 빌드 파일: JPA 의존성
        _write(
            tmp_path / "build.gradle.kts",
            """
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-data-jpa")
}
""",
        )
        # 모듈 디렉토리: 빌드 파일 없음 (깨끗)
        module_dir = tmp_path / "api-server"
        module_dir.mkdir()

        module_info = ModuleInfo(name="api-server", path=module_dir, is_likely_app=True)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        # _project_root 설정 (analyze() 경유 없이 직접 호출)
        analyzer._project_root = tmp_path.resolve()
        signal = analyzer._detect_statefulness(tmp_path, module_info)
        analyzer._project_root = None

        assert signal.is_stateful is True
        assert signal.confidence == "high"
        assert any("jpa" in r.lower() or "JPA" in r for r in signal.reasons)

    def test_statefulness_multi_module_yml_in_module_takes_priority(
        self, tmp_path: Path
    ) -> None:
        """모듈에 application.yml(datasource 있음), 루트에 없음 → stateful(high)."""
        _write(tmp_path / "build.gradle.kts", "dependencies {}\n")

        module_dir = tmp_path / "web-api"
        _write(
            module_dir / "src/main/resources/application.yml",
            """
spring:
  datasource:
    url: jdbc:mysql://localhost:3306/mydb
""",
        )
        module_info = ModuleInfo(name="web-api", path=module_dir, is_likely_app=True)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        analyzer._project_root = tmp_path.resolve()
        signal = analyzer._detect_statefulness(tmp_path, module_info)
        analyzer._project_root = None

        assert signal.is_stateful is True
        assert signal.confidence == "high"

    def test_statefulness_multi_module_stateless_when_no_signals_anywhere(
        self, tmp_path: Path
    ) -> None:
        """루트 + 모듈 모두 시그널 없음 → stateless."""
        _write(
            tmp_path / "build.gradle.kts",
            "dependencies { implementation('org.springframework.boot:spring-boot-starter-web') }\n",
        )
        module_dir = tmp_path / "web-api"
        module_dir.mkdir()

        module_info = ModuleInfo(name="web-api", path=module_dir, is_likely_app=True)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        analyzer._project_root = tmp_path.resolve()
        signal = analyzer._detect_statefulness(tmp_path, module_info)
        analyzer._project_root = None

        assert signal.is_stateful is False
        assert signal.confidence == "high"


# ──────────────────────────────────────────────────────────────────────────────
# 13. is_within root 정정 — _read_build_file_text / _check_datasource_url
# ──────────────────────────────────────────────────────────────────────────────


class TestIsWithinRootCorrection:
    def test_read_build_file_text_uses_project_root_not_scan_dir(
        self, tmp_path: Path
    ) -> None:
        """_read_build_file_text가 project_root 기준 is_within 검사를 수행한다."""
        _write(
            tmp_path / "build.gradle.kts",
            "dependencies { implementation('spring-boot-starter-data-jpa') }\n",
        )
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        analyzer._project_root = tmp_path.resolve()
        text = analyzer._read_build_file_text(tmp_path)
        analyzer._project_root = None

        # 빌드 파일이 정상적으로 읽혔는지 확인
        assert "spring-boot-starter-data-jpa" in text

    def test_project_root_reset_after_analyze(self, tmp_path: Path) -> None:
        """analyze() 완료 후 _project_root가 None으로 리셋된다."""
        _spring_boot3_gradle(tmp_path)

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        analyzer.analyze(tmp_path, config)

        assert analyzer._project_root is None

    def test_project_root_reset_after_analyze_exception(self, tmp_path: Path) -> None:
        """analyze()가 예외로 종료되어도 _project_root가 None으로 리셋된다."""
        # 빈 디렉토리 → UnknownStackError 발생
        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"jvm": JvmStackModule()},
        )
        config = _make_resolved_config()
        with pytest.raises(UnknownStackError):
            analyzer.analyze(tmp_path, config)

        assert analyzer._project_root is None


# ---------------------------------------------------------------------------
# BL-001 Phase 5: Analyzer/Pipeline 통합 + ConfigLoader stack overrides
# ---------------------------------------------------------------------------


class TestPhase5InputsChainAndOverrides:
    """F-27 / F-19 / F-33 통합 검증."""

    def test_analyze_passes_inputs_to_build_plan(self, tmp_path: Path) -> None:
        """NFR-04 (k): analyze(inputs=...)이 stack.build_plan(inputs=...)으로 전달."""
        from scripts._shared.types import UserInputs

        mock_module = MagicMock()
        mock_module.detect.return_value = StackDetectResult(
            port=8080, entrypoint="", framework="go-generic", version="1.22"
        )
        mock_module.build_plan.return_value = BuildPlan(
            builder_image="b", runner_image="r", build_cmd="c", artifact_path="a",
        )
        mock_module.probe_plan.return_value = ProbeConfig(
            liveness=ProbeSpec(kind="tcp", path=None, port=8080),
            readiness=ProbeSpec(kind="tcp", path=None, port=8080),
        )
        mock_module.defaults.return_value = ResourceDefaults(
            cpu_request="50m",
            memory_request="64Mi",
            cpu_limit="250m",
            memory_limit="128Mi",
            writable_paths=["/tmp"],
            run_as_user=65532,
        )
        mock_module.artifact_locator.return_value = []

        analyzer = ProjectAnalyzer(
            config_loader=_make_config_loader_auto(),
            stack_registry={"go": mock_module},
        )
        config = _make_resolved_config()
        inputs = UserInputs(
            app_name="kube-api",
            port=8080,
            exposure="ClusterIP",
            namespace="default",
            output_dir=Path("/tmp/out"),
            resource_hint="medium",
        )

        analyzer.analyze(tmp_path, config, inputs=inputs)

        mock_module.build_plan.assert_called_once()
        call_args = mock_module.build_plan.call_args
        assert call_args.kwargs.get("inputs") is inputs

    def test_apply_stack_overrides_entrypoint(self) -> None:
        """F-27/A-08: config의 stack.<name>.entrypoint가 detect_result.entrypoint를 override."""
        detect_before = StackDetectResult(
            port=None,
            entrypoint="",
            framework="go-generic",
            version="1.22",
            cmd_candidates=["api", "scheduler"],
        )
        detect_after = ProjectAnalyzer._apply_stack_overrides(
            detect_before, {"entrypoint": "./cmd/api"}
        )

        assert detect_after.entrypoint == "./cmd/api"
        assert detect_after.cmd_candidates == ["api", "scheduler"]  # 다른 필드 보존
        # 원본 불변 (frozen)
        assert detect_before.entrypoint == ""

    def test_apply_stack_overrides_no_entrypoint_passthrough(self) -> None:
        """stack_config에 entrypoint 키 없으면 detect_result 그대로 통과."""
        detect_before = StackDetectResult(
            port=8080, entrypoint=".", framework="go-generic", version="1.22"
        )
        detect_after = ProjectAnalyzer._apply_stack_overrides(detect_before, {})

        assert detect_after is detect_before  # 동일 인스턴스 반환

    def test_apply_probe_overrides_path(self) -> None:
        """F-19/F-27: config의 stack.<name>.probe.path가 ProbeConfig 양쪽 path를 override."""
        probe_before = ProbeConfig(
            liveness=ProbeSpec(kind="http", path="/healthz", port=8080),
            readiness=ProbeSpec(kind="http", path="/healthz", port=8080),
        )
        probe_after = ProjectAnalyzer._apply_probe_overrides(
            probe_before, {"probe": {"path": "/custom-health"}}
        )

        assert probe_after.liveness.path == "/custom-health"
        assert probe_after.readiness.path == "/custom-health"
        # port 보존
        assert probe_after.liveness.port == 8080
        assert probe_after.readiness.port == 8080

    def test_apply_probe_overrides_skips_tcp(self) -> None:
        """TCP probe는 path 무관 — override 영향 없음."""
        probe_before = ProbeConfig(
            liveness=ProbeSpec(kind="tcp", path=None, port=8080),
            readiness=ProbeSpec(kind="tcp", path=None, port=8080),
        )
        probe_after = ProjectAnalyzer._apply_probe_overrides(
            probe_before, {"probe": {"path": "/custom-health"}}
        )
        assert probe_after.liveness.path is None
        assert probe_after.readiness.path is None


class TestPhase5SecurityGuards:
    """BL-001 Phase 5 보안 보강 — Codex/security-reviewer P1 대응.

    Phase 6 validate_go_entrypoint(F-29) 도입 전 trust boundary 닫는 선제 가드.
    """

    @pytest.mark.parametrize(
        "bad_entrypoint",
        [
            "; rm -rf /",
            "$(echo)",
            "`whoami`",
            "./cmd/api\nFROM scratch",
            "../etc/passwd",
            "./cmd/../../etc",
            "x" * 300,  # 길이 초과
            " ./cmd/api",  # 선행 공백
            "./cmd/api;",  # 세미콜론
        ],
    )
    def test_apply_stack_overrides_rejects_unsafe_entrypoint(self, bad_entrypoint: str) -> None:
        """entrypoint shell injection / path traversal / 길이 초과 거부."""
        detect = StackDetectResult(
            port=None, entrypoint="", framework="go-generic", version="1.22"
        )
        with pytest.raises(ValueError, match="entrypoint"):
            ProjectAnalyzer._apply_stack_overrides(detect, {"entrypoint": bad_entrypoint})

    def test_apply_stack_overrides_accepts_safe_entrypoint(self) -> None:
        """정상 entrypoint는 통과."""
        detect = StackDetectResult(
            port=None, entrypoint="", framework="go-generic", version="1.22"
        )
        for safe in [".", "./cmd/api", "./cmd/kube-controller-manager", "./bin/x_y"]:
            result = ProjectAnalyzer._apply_stack_overrides(detect, {"entrypoint": safe})
            assert result.entrypoint == safe

    @pytest.mark.parametrize(
        "bad_path",
        [
            "/h\nbody: pwn",  # 개행
            "/h\x00\x01",  # 제어문자
            "no-leading-slash",
            "/" + ("a" * 600),  # 길이 초과
            "/h<script>",  # 비허용 문자
        ],
    )
    def test_apply_probe_overrides_rejects_unsafe_path(self, bad_path: str) -> None:
        """probe.path YAML/HTTP path injection 거부."""
        probe = ProbeConfig(
            liveness=ProbeSpec(kind="http", path="/healthz", port=8080),
            readiness=ProbeSpec(kind="http", path="/healthz", port=8080),
        )
        with pytest.raises(ValueError, match="probe"):
            ProjectAnalyzer._apply_probe_overrides(probe, {"probe": {"path": bad_path}})

    def test_apply_probe_overrides_accepts_safe_path(self) -> None:
        """정상 probe.path 통과."""
        probe = ProbeConfig(
            liveness=ProbeSpec(kind="http", path="/healthz", port=8080),
            readiness=ProbeSpec(kind="http", path="/healthz", port=8080),
        )
        for safe in ["/healthz", "/api/v1/health", "/health?ready=true"]:
            result = ProjectAnalyzer._apply_probe_overrides(probe, {"probe": {"path": safe}})
            assert result.liveness.path == safe


# ──────────────────────────────────────────────────────────────────────────────
# BL-019: entrypoint / probe.path 정책 일원화 가드
# ──────────────────────────────────────────────────────────────────────────────


class TestBL019PolicyConsistency:
    """BL-019: text_safety의 단일 정책을 ProjectAnalyzer 호출부가 위임하는지 가드.

    이전 상태: ProjectAnalyzer 자체 정규식 + go.py validate_go_entrypoint 이원화.
    `cmd/api`(./ 누락)는 Analyzer 통과 → build_plan 지연 실패.
    BL-019: text_safety로 일원화 → fail-fast.

    4분기 시나리오:
      1. text_safety 직접 호출 — 거부
      2. text_safety 직접 호출 — 허용
      3. Analyzer override — 거부 (text_safety와 동일 결과)
      4. Analyzer override — 허용 (text_safety와 동일 결과)
    """

    @pytest.mark.parametrize(
        "invalid",
        [
            "cmd/api",  # BL-001 회귀: ./ 누락
            "../etc/passwd",
            "./cmd/../../etc",
            "./cmd/$(whoami)",
            "./cmd/`id`",
            "./cmd/foo;bar",
            "./cmd/foo bar",
            "./cmd/foo\nbar",
            " ./cmd/api",
            "./cmd/" + ("x" * 260),  # 길이 초과
        ],
    )
    def test_entrypoint_invalid_rejected_by_both_layers(self, invalid: str) -> None:
        """동일 invalid 입력을 text_safety와 Analyzer 모두 거부."""
        from scripts._shared.text_safety import validate_go_entrypoint

        with pytest.raises(ValueError):
            validate_go_entrypoint(invalid)

        detect = StackDetectResult(
            port=None, entrypoint="", framework="go-generic", version="1.22"
        )
        with pytest.raises(ValueError):
            ProjectAnalyzer._apply_stack_overrides(detect, {"entrypoint": invalid})

    @pytest.mark.parametrize(
        "valid",
        [
            ".",
            "./cmd/api",
            "./cmd/kube-controller-manager",
            "./bin/x_y",
            "./cmd/v1.beta",
        ],
    )
    def test_entrypoint_valid_accepted_by_both_layers(self, valid: str) -> None:
        """동일 valid 입력을 text_safety와 Analyzer 모두 허용."""
        from scripts._shared.text_safety import validate_go_entrypoint

        validate_go_entrypoint(valid)  # 예외 없음

        detect = StackDetectResult(
            port=None, entrypoint="", framework="go-generic", version="1.22"
        )
        result = ProjectAnalyzer._apply_stack_overrides(detect, {"entrypoint": valid})
        assert result.entrypoint == valid

    @pytest.mark.parametrize(
        "invalid",
        [
            "no-leading-slash",
            "/h\nbody: pwn",
            "/h\x00\x01",
            "/" + ("a" * 600),
            "/h<script>",
        ],
    )
    def test_probe_path_invalid_rejected_by_both_layers(self, invalid: str) -> None:
        """동일 invalid probe.path를 text_safety와 Analyzer 모두 거부."""
        from scripts._shared.text_safety import validate_probe_path

        with pytest.raises(ValueError):
            validate_probe_path(invalid)

        probe = ProbeConfig(
            liveness=ProbeSpec(kind="http", path="/healthz", port=8080),
            readiness=ProbeSpec(kind="http", path="/healthz", port=8080),
        )
        with pytest.raises(ValueError):
            ProjectAnalyzer._apply_probe_overrides(probe, {"probe": {"path": invalid}})

    @pytest.mark.parametrize(
        "valid",
        ["/healthz", "/api/v1/health", "/health?ready=true"],
    )
    def test_probe_path_valid_accepted_by_both_layers(self, valid: str) -> None:
        """동일 valid probe.path를 text_safety와 Analyzer 모두 허용."""
        from scripts._shared.text_safety import validate_probe_path

        validate_probe_path(valid)  # 예외 없음

        probe = ProbeConfig(
            liveness=ProbeSpec(kind="http", path="/healthz", port=8080),
            readiness=ProbeSpec(kind="http", path="/healthz", port=8080),
        )
        result = ProjectAnalyzer._apply_probe_overrides(probe, {"probe": {"path": valid}})
        assert result.liveness.path == valid

    def test_cmd_api_regression_fail_fast(self) -> None:
        """BL-001 회귀: 'cmd/api' (./ 없음)는 Analyzer 단계에서 즉시 거부.

        이전: Analyzer 통과 → go.py:270 build_plan 지연 실패.
        BL-019: 정책 일원화로 _apply_stack_overrides에서 fail-fast.
        """
        detect = StackDetectResult(
            port=None, entrypoint="", framework="go-generic", version="1.22"
        )
        with pytest.raises(ValueError, match="entrypoint"):
            ProjectAnalyzer._apply_stack_overrides(detect, {"entrypoint": "cmd/api"})

    def test_empty_entrypoint_config_is_passthrough(self) -> None:
        """빈 문자열 entrypoint config는 'no override' 의미로 passthrough.

        text_safety.validate_go_entrypoint('')은 직접 호출시 raise (정책 일관성).
        Analyzer는 user config 미설정으로 해석하여 검증 트리거 없이 detect 결과 유지.
        두 의미는 호환됨: Analyzer가 검증을 우회하는 게 아니라, 검증 대상 자체가 없음.
        """
        detect = StackDetectResult(
            port=None, entrypoint="./auto", framework="go-generic", version="1.22"
        )
        result = ProjectAnalyzer._apply_stack_overrides(detect, {"entrypoint": ""})
        assert result == detect  # passthrough, 검증 미트리거

    def test_empty_probe_path_config_is_passthrough(self) -> None:
        """빈 문자열 probe.path config도 passthrough."""
        probe = ProbeConfig(
            liveness=ProbeSpec(kind="http", path="/healthz", port=8080),
            readiness=ProbeSpec(kind="http", path="/healthz", port=8080),
        )
        result = ProjectAnalyzer._apply_probe_overrides(probe, {"probe": {"path": ""}})
        assert result == probe  # passthrough
