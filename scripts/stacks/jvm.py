"""JvmStackModule — Kotlin/Java Spring Boot / 일반 JVM 스택 감지 및 계획 생성.

판별 우선순위:
  1. build.gradle.kts  (Kotlin DSL)
  2. build.gradle      (Groovy DSL)
  3. pom.xml           (Maven)
  4. settings.gradle(.kts) — multi-module 시그널만, detect는 root 기준

Spring Boot 버전 추출:
  - Gradle: `org.springframework.boot` plugin 버전 또는 starter 의존성 버전
  - Maven: spring-boot-starter-parent <version>

포트 추론 우선순위 (F-12):
  application-{profile}.yml/properties → application.yml/properties → 8080

actuator 감지:
  - spring-boot-starter-actuator 의존성 존재
  - AND (
      application(-{profile}).yml/properties에 management.endpoints.web.exposure.include에
      'health' 포함 (또는 '*' 와일드카드)
      OR Boot 3.x는 include 미설정 시에도 기본 health 노출로 활성화
    )

빌드 시스템/actuator:
  detect()에서 StackDetectResult.build_system / .actuator_enabled 필드에 직접 저장.
  probe_plan / build_plan / artifact_locator에서 이 필드를 직접 참조한다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as StdET
from pathlib import Path
from typing import ClassVar, Literal

import yaml
from defusedxml import ElementTree as ET

from scripts._shared.errors import JvmDetectionError
from scripts._shared.fileio import is_within, read_text_limited
from scripts._shared.types import (
    BuildPlan,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    StackDetectResult,
)

# ──────────────────────────────────────────────────────────────────────────────
# 내부 상수
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_JDK_VERSION = 21
_DEFAULT_PORT = 8080

# Spring Boot Gradle plugin ID (KTS + Groovy 양쪽)
_SPRING_BOOT_PLUGIN_RE = re.compile(
    r"""id\s*\(?\s*["']org\.springframework\.boot["']\s*\)?\s*version\s*["']([^"']+)["']"""
)

# Spring Boot starter 버전 명시 (Groovy: 'group:artifact:version')
_SPRING_BOOT_DEP_VERSION_RE = re.compile(
    r"""spring-boot-starter[^"']*:([2-9]\.[0-9]+\.[0-9]+(?:\.[A-Z0-9]+)?)"""
)

# Ktor 감지
_KTOR_RE = re.compile(r"""io\.ktor""", re.IGNORECASE)

# Micronaut 감지
_MICRONAUT_RE = re.compile(r"""io\.micronaut""", re.IGNORECASE)

# actuator 의존성 (Gradle 문자열 일치)
_ACTUATOR_RE = re.compile(r"spring-boot-starter-actuator")

# Maven XML 네임스페이스
_MVN_NS = "http://maven.apache.org/POM/4.0.0"


def _mvn_find(element: StdET.Element, tag: str) -> StdET.Element | None:
    """ET.Element에서 namespace 포함/미포함 두 가지 방식으로 child 탐색.

    ET.Element의 bool()은 자식 유무 기반이므로 'or' 연산자 대신 이 함수 사용.
    """
    result = element.find(f"{{{_MVN_NS}}}{tag}")
    if result is not None:
        return result
    return element.find(tag)


# ──────────────────────────────────────────────────────────────────────────────
# JvmStackModule
# ──────────────────────────────────────────────────────────────────────────────


class JvmStackModule:
    """JVM 스택 모듈 (StackModule Protocol 구현체).

    detect() 결과의 build_system / actuator_enabled 필드를
    probe_plan / build_plan / artifact_locator에서 직접 참조한다.
    """

    name: ClassVar[str] = "jvm"

    # ── Public: StackModule Protocol ──────────────────────────────────────────

    def detect(self, project_dir: Path) -> StackDetectResult | None:
        """JVM 프로젝트 감지 + 프레임워크/버전/포트/빌드시스템/actuator 추론.

        Returns:
            StackDetectResult — JVM 프로젝트인 경우.
            None — JVM 프로젝트가 아닌 경우.

        Raises:
            JvmDetectionError — 빌드 파일 존재하나 파싱 불가 시.
        """
        build_files = self._find_build_files(project_dir)
        if not build_files:
            return None

        framework, version = self._detect_framework_and_version(build_files)
        port = self._detect_port(project_dir)
        build_system: Literal["gradle", "maven"] = self._detect_build_system(build_files)

        # actuator 감지 (Spring Boot 프로젝트일 때만)
        actuator_enabled = False
        if framework == "spring-boot":
            actuator_enabled = self._detect_actuator(project_dir, version)

        return StackDetectResult(
            port=port,
            entrypoint="",
            framework=framework,
            version=version,
            build_system=build_system,
            actuator_enabled=actuator_enabled,
        )

    def build_plan(self, detect_result: StackDetectResult) -> BuildPlan:
        """detect_result 기반 BuildPlan 생성.

        build_cmd:
          - Maven: "mvn package"
          - Gradle: "gradle bootJar"
        """
        maven = detect_result.build_system == "maven"
        jdk_version = _DEFAULT_JDK_VERSION

        return BuildPlan(
            builder_image=f"eclipse-temurin:{jdk_version}-jdk-alpine",
            runner_image=f"eclipse-temurin:{jdk_version}-jre-alpine",
            build_cmd="mvn package" if maven else "gradle bootJar",
            artifact_path="target/*.jar" if maven else "build/libs/*.jar",
        )

    def probe_plan(self, detect_result: StackDetectResult) -> ProbeConfig:
        """liveness/readiness ProbeConfig 생성.

        Boot 2.x + actuator   → /actuator/health (liveness = readiness)
        Boot 3.x + actuator   → /actuator/health/liveness + /actuator/health/readiness
        actuator 미감지 / 비-Spring → TcpProbe(port)
        """
        port = detect_result.port or _DEFAULT_PORT

        if detect_result.framework != "spring-boot":
            return self._tcp_probe_config(port)

        if not detect_result.actuator_enabled:
            return self._tcp_probe_config(port)

        version = detect_result.version or ""
        major = self._parse_major_version(version)

        if major >= 3:
            return ProbeConfig(
                liveness=ProbeSpec(
                    kind="http", path="/actuator/health/liveness", port=port
                ),
                readiness=ProbeSpec(
                    kind="http", path="/actuator/health/readiness", port=port
                ),
            )
        else:
            # Boot 2.x
            return ProbeConfig(
                liveness=ProbeSpec(kind="http", path="/actuator/health", port=port),
                readiness=ProbeSpec(kind="http", path="/actuator/health", port=port),
            )

    def defaults(self) -> ResourceDefaults:
        """JVM 스택 기본 리소스 설정."""
        return ResourceDefaults(
            cpu_request="100m",
            memory_request="512Mi",
            cpu_limit="1000m",
            memory_limit="1Gi",
            writable_paths=["/tmp", "/var/log"],
        )

    def artifact_locator(
        self, detect_result: StackDetectResult, project_dir: Path
    ) -> list[Path]:
        """빌드 산출물 jar 경로 목록.

        Gradle: build/libs/*.jar — plain jar 제외, fat jar 우선
        Maven:  target/*.jar — original- prefix 제외 시 spring-boot 산출물 우선
        """
        if detect_result.build_system == "maven":
            return self._locate_maven_jars(project_dir)
        return self._locate_gradle_jars(project_dir)

    # ── 내부 헬퍼: 빌드 파일 탐색 ─────────────────────────────────────────────

    def _find_build_files(self, project_dir: Path) -> list[Path]:
        """판별 우선순위에 따라 존재하는 빌드 파일 반환 (symlink escape 방어)."""
        candidates = [
            project_dir / "build.gradle.kts",
            project_dir / "build.gradle",
            project_dir / "pom.xml",
        ]
        return [
            f for f in candidates if f.exists() and is_within(project_dir, f)
        ]

    @staticmethod
    def _detect_build_system(build_files: list[Path]) -> Literal["gradle", "maven"]:
        """빌드 파일 목록에서 gradle 또는 maven 판별.

        _find_build_files가 이미 우선순위대로 정렬(build.gradle.kts → build.gradle → pom.xml)
        하므로 첫 번째 파일 이름으로 판단한다.
        """
        if not build_files:
            return "gradle"
        first = build_files[0]
        if first.name.startswith("build.gradle"):
            return "gradle"
        if first.name == "pom.xml":
            return "maven"
        return "gradle"

    # ── 내부 헬퍼: 프레임워크/버전 감지 ──────────────────────────────────────

    def _detect_framework_and_version(
        self, build_files: list[Path]
    ) -> tuple[str, str | None]:
        """build 파일들로부터 framework + version 반환.

        각 빌드 파일을 한 번만 읽어 Spring Boot / Ktor / Micronaut 순서로 검사한다.
        Ktor는 pom.xml 기반 빌드 파일에서 탐색하지 않는다 (Gradle 기반 프레임워크).

        Raises:
            JvmDetectionError: Gradle 빌드 파일 읽기 실패 시.
        """
        # Spring Boot 우선 (버전 추출 포함)
        boot_version = self._detect_boot_version(build_files)
        if boot_version:
            return ("spring-boot", boot_version)

        # 각 파일을 한 번만 읽어 spring-boot / ktor / micronaut 체크
        for build_file in build_files:
            is_pom = build_file.name == "pom.xml"
            try:
                content = read_text_limited(build_file)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                if not is_pom:
                    raise JvmDetectionError(
                        f"Gradle 빌드 파일 파싱 실패: {build_file.name}: {exc}"
                    ) from exc
                continue

            # Spring Boot (버전 없이 문자열만 존재)
            if "spring-boot" in content.lower() or "springframework.boot" in content:
                return ("spring-boot", None)

            # Ktor (pom.xml은 skip — Gradle 기반 프레임워크)
            if not is_pom and _KTOR_RE.search(content):
                return ("ktor", None)

            # Micronaut
            if _MICRONAUT_RE.search(content):
                return ("micronaut", None)

        return ("jvm-generic", None)

    def _detect_boot_version(self, build_files: list[Path]) -> str | None:
        """Spring Boot 버전 추출.

        Gradle: spring-boot plugin 버전 또는 starter 의존성 버전
        Maven:  spring-boot-starter-parent <version>

        Raises:
            JvmDetectionError: Gradle 빌드 파일 읽기 실패 시 (ValueError 포함).
        """
        for build_file in build_files:
            try:
                content = read_text_limited(build_file)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                if build_file.name != "pom.xml":
                    raise JvmDetectionError(
                        f"Gradle 빌드 파일 파싱 실패: {build_file.name}: {exc}"
                    ) from exc
                continue

            if build_file.name == "pom.xml":
                version = self._extract_maven_boot_version(content)
                if version:
                    return version
            else:
                # Gradle (.kts or .gradle)
                m = _SPRING_BOOT_PLUGIN_RE.search(content)
                if m:
                    return m.group(1)
                m2 = _SPRING_BOOT_DEP_VERSION_RE.search(content)
                if m2:
                    return m2.group(1)

        return None

    def _detect_actuator(self, project_dir: Path, version: str | None) -> bool:
        """actuator 활성화 여부.

        조건:
          1. build 파일에 spring-boot-starter-actuator 의존성 존재
          2-a. application(-{profile}).yml/properties에
               management.endpoints.web.exposure.include에 'health' 또는 '*' 포함
          2-b. 또는 Boot 3.x인 경우 include 미설정이어도 기본 health 노출 (Minor 9)
        """
        build_files = self._find_build_files(project_dir)
        has_actuator_dep = False

        for build_file in build_files:
            try:
                content = read_text_limited(build_file)
            except (OSError, UnicodeDecodeError):
                continue
            if build_file.name == "pom.xml":
                if self._maven_has_actuator(content):
                    has_actuator_dep = True
                    break
            elif _ACTUATOR_RE.search(content):
                has_actuator_dep = True
                break

        if not has_actuator_dep:
            return False

        # management.endpoints.web.exposure.include 에 health 포함 여부
        if self._check_management_exposure(project_dir):
            return True

        # Minor 9: Boot 3.x는 include 미설정이어도 기본 health 노출
        major = self._parse_major_version(version or "")
        return major >= 3

    def _detect_port(self, project_dir: Path) -> int:
        """포트 추론 (F-12 우선순위).

        우선순위:
          1. application-{profile}.yml/properties (profile 파일 먼저)
          2. application.yml/properties
          3. 8080 기본값
        """
        resources_dir = project_dir / "src" / "main" / "resources"
        if not resources_dir.exists():
            return _DEFAULT_PORT

        # 1. profile 파일 먼저 검색 (application-*.yml / application-*.properties)
        for yml_file in sorted(resources_dir.glob("application-*.yml")):
            if not is_within(project_dir, yml_file):
                continue
            port = self._read_port_from_yaml(yml_file)
            if port is not None:
                return port

        for props_file in sorted(resources_dir.glob("application-*.properties")):
            if not is_within(project_dir, props_file):
                continue
            port = self._read_port_from_properties(props_file)
            if port is not None:
                return port

        # 2. application.yml / application.yaml / application.properties
        for yml_file in [
            resources_dir / "application.yml",
            resources_dir / "application.yaml",
        ]:
            if yml_file.exists() and is_within(project_dir, yml_file):
                port = self._read_port_from_yaml(yml_file)
                if port is not None:
                    return port

        props_file = resources_dir / "application.properties"
        if props_file.exists() and is_within(project_dir, props_file):
            port = self._read_port_from_properties(props_file)
            if port is not None:
                return port

        return _DEFAULT_PORT

    # ── 내부 헬퍼: Maven XML ──────────────────────────────────────────────────

    def _extract_maven_boot_version(self, pom_content: str) -> str | None:
        """pom.xml에서 spring-boot-starter-parent 버전 추출."""
        try:
            root = ET.fromstring(pom_content)
        except ET.ParseError as exc:
            raise JvmDetectionError(f"pom.xml 파싱 실패: {exc}") from exc

        parent = _mvn_find(root, "parent")
        if parent is not None:
            gid_elem = _mvn_find(parent, "groupId")
            aid_elem = _mvn_find(parent, "artifactId")
            ver_elem = _mvn_find(parent, "version")

            gid = gid_elem.text if gid_elem is not None else ""
            aid = aid_elem.text if aid_elem is not None else ""
            ver = ver_elem.text if ver_elem is not None else ""

            if "springframework.boot" in (gid or "") and "spring-boot-starter-parent" in (
                aid or ""
            ):
                return ver or None

        return None

    def _maven_has_actuator(self, pom_content: str) -> bool:
        """pom.xml에 spring-boot-starter-actuator 의존성 존재 여부."""
        try:
            root = ET.fromstring(pom_content)
        except ET.ParseError:
            return False

        # namespace 있는 경우
        for aid_elem in root.iter(f"{{{_MVN_NS}}}artifactId"):
            if aid_elem.text and "spring-boot-starter-actuator" in aid_elem.text:
                return True
        # namespace 없는 경우
        for aid_elem in root.iter("artifactId"):
            if aid_elem.text and "spring-boot-starter-actuator" in aid_elem.text:
                return True
        return False

    # ── 내부 헬퍼: management exposure ────────────────────────────────────────

    def _check_management_exposure(self, project_dir: Path) -> bool:
        """application(-{profile}).yml/properties에서 health exposure 확인."""
        resources_dir = project_dir / "src" / "main" / "resources"
        if not resources_dir.exists():
            return False

        config_files: list[Path] = []
        config_files.extend(
            f for f in sorted(resources_dir.glob("application-*.yml"))
            if is_within(project_dir, f)
        )
        config_files.extend(
            f for f in sorted(resources_dir.glob("application-*.yaml"))
            if is_within(project_dir, f)
        )
        config_files.extend(
            f for f in sorted(resources_dir.glob("application-*.properties"))
            if is_within(project_dir, f)
        )

        for base_name in ("application.yml", "application.yaml", "application.properties"):
            base_file = resources_dir / base_name
            if base_file.exists() and is_within(project_dir, base_file):
                config_files.append(base_file)

        for cfg_file in config_files:
            if self._file_exposes_health(cfg_file):
                return True
        return False

    def _file_exposes_health(self, config_file: Path) -> bool:
        """단일 설정 파일에서 management.endpoints.web.exposure.include에 health/* 포함.

        .properties 파일은 UTF-8 읽기 실패 시 ISO-8859-1로 재시도한다
        (Spring Boot 관례, _read_port_from_properties와 동일 패턴).
        """
        suffix = config_file.suffix.lower()

        if suffix in (".yml", ".yaml"):
            try:
                content = read_text_limited(config_file)
            except (OSError, UnicodeDecodeError, ValueError):
                return False
            return self._yaml_exposes_health(content)

        if suffix == ".properties":
            try:
                content = read_text_limited(config_file)
            except UnicodeDecodeError:
                try:
                    content = read_text_limited(config_file, encoding="iso-8859-1")
                except (OSError, UnicodeDecodeError, ValueError):
                    return False
            except (OSError, ValueError):
                return False
            return self._properties_exposes_health(content)

        return False

    @staticmethod
    def _yaml_exposes_health(content: str) -> bool:
        """YAML 파일에서 management.endpoints.web.exposure.include 검사."""
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            return False

        if not isinstance(data, dict):
            return False

        try:
            include = (
                data.get("management", {})
                .get("endpoints", {})
                .get("web", {})
                .get("exposure", {})
                .get("include", "")
            )
        except AttributeError:
            return False

        return JvmStackModule._include_has_health(include)

    @staticmethod
    def _properties_exposes_health(content: str) -> bool:
        """properties 파일에서 management.endpoints.web.exposure.include 검사."""
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("management.endpoints.web.exposure.include"):
                _, _, value = line.partition("=")
                return JvmStackModule._include_has_health(value.strip())
        return False

    @staticmethod
    def _include_has_health(include: object) -> bool:
        """include 값에 'health', '*' 중 하나가 있는지 확인.

        list 원소 및 문자열 토큰 모두 strip().lower()로 정규화하여
        'HEALTH', ' Health ' 등의 대소문자/공백 변형도 인식한다.
        """
        if include is None:
            return False
        if isinstance(include, list):
            return any(str(v).strip().lower() in ("health", "*") for v in include)
        text = str(include)
        tokens = [t.strip().lower() for t in text.split(",")]
        return "health" in tokens or "*" in tokens

    # ── 내부 헬퍼: probe_plan 보조 ────────────────────────────────────────────

    @staticmethod
    def _parse_major_version(version: str) -> int:
        """'3.2.0' → 3. 파싱 실패 시 2 반환."""
        m = re.match(r"(\d+)\.", version)
        return int(m.group(1)) if m else 2

    @staticmethod
    def _tcp_probe_config(port: int) -> ProbeConfig:
        """TcpProbe 기반 ProbeConfig 생성."""
        probe = ProbeSpec(kind="tcp", path=None, port=port)
        return ProbeConfig(liveness=probe, readiness=probe)

    # ── 내부 헬퍼: artifact 탐색 ──────────────────────────────────────────────

    @staticmethod
    def _locate_gradle_jars(project_dir: Path) -> list[Path]:
        """build/libs/*.jar — plain jar 제외, fat jar 우선."""
        build_libs = project_dir / "build" / "libs"
        if not build_libs.exists():
            return []

        all_jars = list(build_libs.glob("*.jar"))
        fat_jars = [j for j in all_jars if not j.name.endswith("-plain.jar")]

        if fat_jars:
            return sorted(fat_jars)
        return sorted(all_jars)

    @staticmethod
    def _locate_maven_jars(project_dir: Path) -> list[Path]:
        """target/*.jar — original- prefix 없는 것 우선 (spring-boot-maven-plugin 산출물)."""
        target_dir = project_dir / "target"
        if not target_dir.exists():
            return []

        all_jars = list(target_dir.glob("*.jar"))
        preferred = [j for j in all_jars if not j.name.startswith("original-")]

        if preferred:
            return sorted(preferred)
        return sorted(all_jars)

    # ── 내부 헬퍼: 포트 읽기 ──────────────────────────────────────────────────

    @staticmethod
    def _read_port_from_yaml(yml_file: Path) -> int | None:
        """YAML 파일에서 server.port 값 추출."""
        try:
            content = read_text_limited(yml_file)
            data = yaml.safe_load(content)
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return None

        if not isinstance(data, dict):
            return None

        try:
            port_val = data.get("server", {}).get("port")
        except AttributeError:
            return None

        if port_val is not None:
            try:
                port = int(port_val)
            except (ValueError, TypeError):
                return None
            if not 1 <= port <= 65535:
                return None
            return port
        return None

    @staticmethod
    def _read_port_from_properties(props_file: Path) -> int | None:
        """properties 파일에서 server.port 값 추출.

        UTF-8 읽기 실패 시 ISO-8859-1로 재시도 (Spring Boot 관례).
        """
        content: str
        try:
            content = read_text_limited(props_file)
        except UnicodeDecodeError:
            try:
                content = read_text_limited(props_file, encoding="iso-8859-1")
            except (OSError, UnicodeDecodeError):
                return None
        except OSError:
            return None

        for line in content.splitlines():
            line = line.strip()
            if line.startswith("server.port"):
                _, _, value = line.partition("=")
                value = value.strip()
                try:
                    port = int(value)
                except ValueError:
                    return None
                if not 1 <= port <= 65535:
                    return None
                return port
        return None
