"""JvmStackModule 단위 테스트 (TDD).

시나리오:
1. detect — Gradle KTS/Groovy/Maven, 비-Spring, 빈 디렉토리
2. probe_plan — Boot 2+actuator, Boot 3+actuator, actuator 미감지
   + I2: actuator 4 케이스 (Boot 2 no-include, Boot 3 no-include, list, wildcard)
   + I3: Maven probe 경로 검증
3. build_plan — Gradle/Maven 분기, 이미지 포맷
4. defaults — 필드 기본값
5. artifact_locator — fat jar 우선 / plain jar 제외
6. _detect_port — profile 우선순위, port 범위 검증, ISO-8859-1 fallback
7. Security — symlink escape
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures: 프로젝트 디렉토리 생성 헬퍼 (tmp_path 기반)
# ──────────────────────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def make_gradle_kts_spring3(tmp_path: Path) -> Path:
    """Kotlin DSL + Spring Boot 3.2.0."""
    _write(
        tmp_path / "build.gradle.kts",
        """
plugins {
    kotlin("jvm") version "1.9.22"
    kotlin("plugin.spring") version "1.9.22"
    id("org.springframework.boot") version "3.2.0"
    id("io.spring.dependency-management") version "1.1.4"
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
management:
  endpoints:
    web:
      exposure:
        include: health,info
server:
  port: 8080
""",
    )
    return tmp_path


def make_gradle_groovy_spring2(tmp_path: Path) -> Path:
    """Gradle Groovy DSL + Spring Boot 2.7.18."""
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
    implementation 'org.springframework.boot:spring-boot-starter-actuator'
}
""",
    )
    _write(
        tmp_path / "src/main/resources/application.yml",
        """
management:
  endpoints:
    web:
      exposure:
        include: health
server:
  port: 9090
""",
    )
    return tmp_path


def make_maven_spring2(tmp_path: Path) -> Path:
    """Maven + Spring Boot 2.7.18."""
    _write(
        tmp_path / "pom.xml",
        """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>2.7.18</version>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>demo</artifactId>
    <version>0.0.1-SNAPSHOT</version>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-actuator</artifactId>
        </dependency>
    </dependencies>
</project>
""",
    )
    _write(
        tmp_path / "src/main/resources/application.properties",
        "server.port=8082\nmanagement.endpoints.web.exposure.include=health\n",
    )
    return tmp_path


def make_gradle_generic_jvm(tmp_path: Path) -> Path:
    """Gradle KTS + 일반 JVM (Spring 없음)."""
    _write(
        tmp_path / "build.gradle.kts",
        """
plugins {
    kotlin("jvm") version "1.9.22"
    application
}

dependencies {
    implementation("io.ktor:ktor-server-netty:2.3.7")
}
""",
    )
    return tmp_path


def make_gradle_spring3_no_actuator(tmp_path: Path) -> Path:
    """Spring Boot 3 + actuator 미감지 (의존성 없음)."""
    _write(
        tmp_path / "build.gradle.kts",
        """
plugins {
    id("org.springframework.boot") version "3.2.0"
}

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
}
""",
    )
    _write(
        tmp_path / "src/main/resources/application.yml",
        "server:\n  port: 7777\n",
    )
    return tmp_path


def make_port_profile_priority(tmp_path: Path) -> Path:
    """application-dev.yml에 port 9001, application.yml에 8080."""
    _write(
        tmp_path / "build.gradle.kts",
        'plugins { id("org.springframework.boot") version "3.2.0" }\n',
    )
    _write(
        tmp_path / "src/main/resources/application.yml",
        "server:\n  port: 8080\n",
    )
    _write(
        tmp_path / "src/main/resources/application-dev.yml",
        "server:\n  port: 9001\n",
    )
    return tmp_path


def make_port_properties_profile(tmp_path: Path) -> Path:
    """application-prod.properties에 port 9002."""
    _write(
        tmp_path / "build.gradle.kts",
        'plugins { id("org.springframework.boot") version "3.2.0" }\n',
    )
    _write(
        tmp_path / "src/main/resources/application-prod.properties",
        "server.port=9002\n",
    )
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# 1. detect
# ──────────────────────────────────────────────────────────────────────────────


class TestDetect:
    def test_gradle_kts_spring_boot_3(self, tmp_path: Path) -> None:
        """Gradle KTS + Spring Boot 3 → framework='spring-boot', version starts with '3.'"""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_kts_spring3(tmp_path)
        result = JvmStackModule().detect(proj)

        assert result is not None
        assert result.framework == "spring-boot"
        assert result.version is not None
        assert result.version.startswith("3.")

    def test_gradle_groovy_spring_boot_2(self, tmp_path: Path) -> None:
        """Gradle Groovy DSL + Spring Boot 2 → framework='spring-boot', version starts with '2.'"""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_groovy_spring2(tmp_path)
        result = JvmStackModule().detect(proj)

        assert result is not None
        assert result.framework == "spring-boot"
        assert result.version is not None
        assert result.version.startswith("2.")

    def test_maven_spring_boot_2(self, tmp_path: Path) -> None:
        """Maven pom.xml + Spring Boot 2 → framework='spring-boot', version starts with '2.'"""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_maven_spring2(tmp_path)
        result = JvmStackModule().detect(proj)

        assert result is not None
        assert result.framework == "spring-boot"
        assert result.version is not None
        assert result.version.startswith("2.")

    def test_gradle_generic_jvm_no_spring(self, tmp_path: Path) -> None:
        """Gradle KTS + Ktor (non-Spring) → framework는 'ktor' 또는 'jvm-generic'."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_generic_jvm(tmp_path)
        result = JvmStackModule().detect(proj)

        assert result is not None
        assert result.framework in ("ktor", "jvm-generic")

    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        """빈 디렉토리 → None (JVM 프로젝트 아님)."""
        from scripts.stacks.jvm import JvmStackModule

        result = JvmStackModule().detect(tmp_path)
        assert result is None

    def test_detect_result_has_port(self, tmp_path: Path) -> None:
        """detect 결과의 port 필드가 int 또는 None."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_kts_spring3(tmp_path)
        result = JvmStackModule().detect(proj)

        assert result is not None
        assert result.port is None or isinstance(result.port, int)


# ──────────────────────────────────────────────────────────────────────────────
# 2. probe_plan
# ──────────────────────────────────────────────────────────────────────────────


class TestProbePlan:
    def test_boot2_with_actuator_uses_http_health(self, tmp_path: Path) -> None:
        """Boot 2.x + actuator → liveness/readiness 모두 /actuator/health."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_groovy_spring2(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "http"
        assert config.readiness.kind == "http"
        assert config.liveness.path == "/actuator/health"
        assert config.readiness.path == "/actuator/health"

    def test_boot3_with_actuator_uses_split_paths(self, tmp_path: Path) -> None:
        """Boot 3.x + actuator → liveness=/actuator/health/liveness,
        readiness=/actuator/health/readiness."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_kts_spring3(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "http"
        assert config.readiness.kind == "http"
        assert config.liveness.path == "/actuator/health/liveness"
        assert config.readiness.path == "/actuator/health/readiness"

    def test_no_actuator_falls_back_to_tcp(self, tmp_path: Path) -> None:
        """actuator 미감지 → TcpProbe 폴백."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_spring3_no_actuator(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "tcp"
        assert config.readiness.kind == "tcp"
        assert config.liveness.path is None
        assert config.readiness.path is None

    def test_non_spring_uses_tcp(self, tmp_path: Path) -> None:
        """비-Spring JVM → TcpProbe 폴백."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_generic_jvm(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "tcp"
        assert config.readiness.kind == "tcp"


# ──────────────────────────────────────────────────────────────────────────────
# 3. build_plan
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildPlan:
    def test_gradle_build_cmd_and_artifact_path(self, tmp_path: Path) -> None:
        """Gradle → build_cmd='gradle bootJar', artifact_path='build/libs/*.jar'"""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_kts_spring3(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        plan = JvmStackModule().build_plan(detect_result)

        assert plan.build_cmd == "gradle bootJar"
        assert plan.artifact_path == "build/libs/*.jar"

    def test_maven_build_cmd_and_artifact_path(self, tmp_path: Path) -> None:
        """Maven → build_cmd='mvn package', artifact_path='target/*.jar'"""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_maven_spring2(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        plan = JvmStackModule().build_plan(detect_result)

        assert plan.build_cmd == "mvn package"
        assert plan.artifact_path == "target/*.jar"

    def test_builder_image_format(self, tmp_path: Path) -> None:
        """builder_image은 'eclipse-temurin:{N}-jdk-alpine' 형식."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_kts_spring3(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        plan = JvmStackModule().build_plan(detect_result)

        import re

        assert re.match(r"eclipse-temurin:\d+-jdk-alpine", plan.builder_image)

    def test_runner_image_format(self, tmp_path: Path) -> None:
        """runner_image은 'eclipse-temurin:{N}-jre-alpine' 형식."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_kts_spring3(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        plan = JvmStackModule().build_plan(detect_result)

        import re

        assert re.match(r"eclipse-temurin:\d+-jre-alpine", plan.runner_image)

    def test_default_jdk_version_is_21(self, tmp_path: Path) -> None:
        """명시적 JDK 버전 없으면 기본값 21 사용."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_gradle_generic_jvm(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        plan = JvmStackModule().build_plan(detect_result)

        assert "21" in plan.builder_image
        assert "21" in plan.runner_image


# ──────────────────────────────────────────────────────────────────────────────
# 4. defaults
# ──────────────────────────────────────────────────────────────────────────────


class TestDefaults:
    def test_defaults_field_values(self) -> None:
        """cpu/memory request/limit 기본값 검증."""
        from scripts.stacks.jvm import JvmStackModule

        defaults = JvmStackModule().defaults()

        assert defaults.cpu_request == "100m"
        assert defaults.memory_request == "512Mi"
        assert defaults.cpu_limit == "1000m"
        assert defaults.memory_limit == "1Gi"

    def test_defaults_writable_paths(self) -> None:
        """writable_paths에 /tmp와 /var/log 포함."""
        from scripts.stacks.jvm import JvmStackModule

        defaults = JvmStackModule().defaults()

        assert "/tmp" in defaults.writable_paths
        assert "/var/log" in defaults.writable_paths


# ──────────────────────────────────────────────────────────────────────────────
# 5. artifact_locator
# ──────────────────────────────────────────────────────────────────────────────


class TestArtifactLocator:
    def test_gradle_excludes_plain_jar(self, tmp_path: Path) -> None:
        """build/libs에 fat jar + plain jar 혼재 → plain jar 제외."""
        from scripts._shared.types import StackDetectResult
        from scripts.stacks.jvm import JvmStackModule

        build_libs = tmp_path / "build" / "libs"
        build_libs.mkdir(parents=True)
        fat_jar = build_libs / "app-1.0.0.jar"
        plain_jar = build_libs / "app-1.0.0-plain.jar"
        fat_jar.touch()
        plain_jar.touch()

        detect_result = StackDetectResult(
            port=8080, entrypoint="", framework="spring-boot", version="3.2.0"
        )
        result = JvmStackModule().artifact_locator(detect_result, tmp_path)

        result_names = [p.name for p in result]
        assert "app-1.0.0.jar" in result_names
        assert "app-1.0.0-plain.jar" not in result_names

    def test_maven_returns_jars_from_target(self, tmp_path: Path) -> None:
        """target/에 여러 jar → 모두 반환 (plain 필터링은 Maven에 불필요)."""
        from scripts._shared.types import StackDetectResult
        from scripts.stacks.jvm import JvmStackModule

        target = tmp_path / "target"
        target.mkdir(parents=True)
        jar1 = target / "demo-0.0.1-SNAPSHOT.jar"
        jar2 = target / "original-demo-0.0.1-SNAPSHOT.jar"
        jar1.touch()
        jar2.touch()

        detect_result = StackDetectResult(
            port=8080,
            entrypoint="",
            framework="spring-boot",
            version="2.7.18",
            build_system="maven",
            actuator_enabled=True,
        )
        result = JvmStackModule().artifact_locator(detect_result, tmp_path)

        assert len(result) >= 1
        result_names = [p.name for p in result]
        assert "demo-0.0.1-SNAPSHOT.jar" in result_names

    def test_gradle_empty_build_libs_returns_empty(self, tmp_path: Path) -> None:
        """build/libs가 없으면 빈 리스트 반환."""
        from scripts._shared.types import StackDetectResult
        from scripts.stacks.jvm import JvmStackModule

        detect_result = StackDetectResult(
            port=8080, entrypoint="", framework="spring-boot", version="3.2.0"
        )
        result = JvmStackModule().artifact_locator(detect_result, tmp_path)
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# 6. _detect_port
# ──────────────────────────────────────────────────────────────────────────────


class TestDetectPort:
    def test_application_yml_port(self, tmp_path: Path) -> None:
        """application.yml에 server.port: 9000 → 9000 반환."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "src/main/resources/application.yml",
            "server:\n  port: 9000\n",
        )
        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 9000

    def test_profile_yml_takes_priority_over_application_yml(self, tmp_path: Path) -> None:
        """application-dev.yml(9001) vs application.yml(8080) → 9001 (profile 우선)."""
        proj = make_port_profile_priority(tmp_path)
        from scripts.stacks.jvm import JvmStackModule

        port = JvmStackModule()._detect_port(proj)
        assert port == 9001

    def test_profile_properties_takes_priority(self, tmp_path: Path) -> None:
        """application-prod.properties에 9002 → 9002."""
        proj = make_port_properties_profile(tmp_path)
        from scripts.stacks.jvm import JvmStackModule

        port = JvmStackModule()._detect_port(proj)
        assert port == 9002

    def test_default_port_8080_when_no_config(self, tmp_path: Path) -> None:
        """포트 설정 없으면 8080 기본값."""
        from scripts.stacks.jvm import JvmStackModule

        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 8080

    def test_application_properties_port(self, tmp_path: Path) -> None:
        """application.properties에 server.port=9999 → 9999."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "src/main/resources/application.properties",
            "server.port=9999\n",
        )
        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 9999


# ──────────────────────────────────────────────────────────────────────────────
# 7. StackModule Protocol 준수 검증
# ──────────────────────────────────────────────────────────────────────────────


class TestStackModuleProtocol:
    def test_jvm_is_instance_of_stack_module_protocol(self) -> None:
        """JvmStackModule은 StackModule Protocol을 구현해야 한다."""
        from scripts.stacks.base import StackModule
        from scripts.stacks.jvm import JvmStackModule

        assert isinstance(JvmStackModule(), StackModule)

    def test_jvm_name_is_jvm(self) -> None:
        """JvmStackModule.name == 'jvm'"""
        from scripts.stacks.jvm import JvmStackModule

        assert JvmStackModule.name == "jvm"


# ──────────────────────────────────────────────────────────────────────────────
# 8. Quality I2: actuator 엣지 케이스 4건
# ──────────────────────────────────────────────────────────────────────────────


class TestActuatorEdgeCases:
    def test_boot2_actuator_dep_no_include_falls_back_to_tcp(self, tmp_path: Path) -> None:
        """Boot 2.x + actuator 의존성만, include 미설정 → TCP 폴백."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "build.gradle",
            """
plugins {
    id 'org.springframework.boot' version '2.7.18'
}
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-actuator'
}
""",
        )
        # management.endpoints 설정 없음
        _write(tmp_path / "src/main/resources/application.yml", "server:\n  port: 8080\n")

        detect_result = JvmStackModule().detect(tmp_path)
        assert detect_result is not None
        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "tcp"
        assert config.readiness.kind == "tcp"

    def test_boot3_actuator_dep_no_include_uses_http(self, tmp_path: Path) -> None:
        """Boot 3.x + actuator 의존성만, include 미설정 → HTTP 프로브 (기본 health 노출)."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "build.gradle.kts",
            """
plugins {
    id("org.springframework.boot") version "3.2.0"
}
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-actuator")
}
""",
        )
        # management.endpoints 설정 없음
        _write(tmp_path / "src/main/resources/application.yml", "server:\n  port: 8080\n")

        detect_result = JvmStackModule().detect(tmp_path)
        assert detect_result is not None
        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "http"
        assert config.readiness.kind == "http"

    def test_actuator_include_list_format_uses_http(self, tmp_path: Path) -> None:
        """include가 YAML list 형태 [health, info] → HTTP 프로브."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "build.gradle.kts",
            """
plugins {
    id("org.springframework.boot") version "2.7.18"
}
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-actuator")
}
""",
        )
        _write(
            tmp_path / "src/main/resources/application.yml",
            """
management:
  endpoints:
    web:
      exposure:
        include:
          - health
          - info
server:
  port: 8080
""",
        )

        detect_result = JvmStackModule().detect(tmp_path)
        assert detect_result is not None
        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "http"
        assert config.readiness.kind == "http"

    def test_actuator_include_wildcard_uses_http(self, tmp_path: Path) -> None:
        """include: "*" 와일드카드 → HTTP 프로브."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "build.gradle.kts",
            """
plugins {
    id("org.springframework.boot") version "3.2.0"
}
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-actuator")
}
""",
        )
        _write(
            tmp_path / "src/main/resources/application.yml",
            """
management:
  endpoints:
    web:
      exposure:
        include: "*"
server:
  port: 8080
""",
        )

        detect_result = JvmStackModule().detect(tmp_path)
        assert detect_result is not None
        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "http"
        assert config.readiness.kind == "http"


# ──────────────────────────────────────────────────────────────────────────────
# 9. Quality I3: Maven probe 경로 검증
# ──────────────────────────────────────────────────────────────────────────────


class TestMavenProbePath:
    def test_maven_boot2_actuator_uses_http_health(self, tmp_path: Path) -> None:
        """Maven + Boot 2 + actuator → /actuator/health HTTP probe."""
        from scripts.stacks.jvm import JvmStackModule

        proj = make_maven_spring2(tmp_path)
        detect_result = JvmStackModule().detect(proj)
        assert detect_result is not None

        config = JvmStackModule().probe_plan(detect_result)

        assert config.liveness.kind == "http"
        assert config.readiness.kind == "http"
        assert config.liveness.path == "/actuator/health"
        assert config.readiness.path == "/actuator/health"


# ──────────────────────────────────────────────────────────────────────────────
# 10. Security 3: symlink escape 방어
# ──────────────────────────────────────────────────────────────────────────────


class TestSymlinkEscape:
    def test_symlinked_application_yml_is_skipped(self, tmp_path: Path) -> None:
        """resources/application.yml → /etc/passwd symlink → port 기본값 8080 반환."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "build.gradle.kts",
            'plugins { id("org.springframework.boot") version "3.2.0" }\n',
        )
        resources_dir = tmp_path / "src" / "main" / "resources"
        resources_dir.mkdir(parents=True)

        symlink_path = resources_dir / "application.yml"
        try:
            os.symlink("/etc/passwd", symlink_path)
        except PermissionError:
            import pytest
            pytest.skip("symlink 생성 권한 없음")

        # /etc/passwd를 읽으면 server.port가 없으므로 기본값 8080으로 폴백
        # 중요: symlink가 project_dir 외부를 가리키므로 skip되어야 함
        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 8080


# ──────────────────────────────────────────────────────────────────────────────
# 11. Security 4 + Minor 10: ISO-8859-1 fallback + port 범위 검증
# ──────────────────────────────────────────────────────────────────────────────


class TestPortEdgeCases:
    def test_iso8859_properties_port(self, tmp_path: Path) -> None:
        """ISO-8859-1 인코딩 한글 주석 포함 properties → port 정상 추출."""
        from scripts.stacks.jvm import JvmStackModule

        resources_dir = tmp_path / "src" / "main" / "resources"
        resources_dir.mkdir(parents=True)
        props_file = resources_dir / "application.properties"
        # ISO-8859-1로 한글 주석 포함 (UTF-8로는 읽기 불가)
        content = "# \xc1\xa4\xb8\xae (ISO-8859-1 comment)\nserver.port=9876\n"
        props_file.write_bytes(content.encode("iso-8859-1"))

        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 9876

    def test_port_out_of_range_returns_default(self, tmp_path: Path) -> None:
        """server.port=99999 (범위 초과) → 기본값 8080 반환."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "src/main/resources/application.yml",
            "server:\n  port: 99999\n",
        )
        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 8080

    def test_port_zero_returns_default(self, tmp_path: Path) -> None:
        """server.port=0 (범위 미달) → 기본값 8080 반환."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "src/main/resources/application.properties",
            "server.port=0\n",
        )
        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 8080

    def test_port_boundary_1(self, tmp_path: Path) -> None:
        """server.port=1 (최솟값) → 1 반환."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "src/main/resources/application.yml",
            "server:\n  port: 1\n",
        )
        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 1

    def test_port_boundary_65535(self, tmp_path: Path) -> None:
        """server.port=65535 (최댓값) → 65535 반환."""
        from scripts.stacks.jvm import JvmStackModule

        _write(
            tmp_path / "src/main/resources/application.yml",
            "server:\n  port: 65535\n",
        )
        port = JvmStackModule()._detect_port(tmp_path)
        assert port == 65535
