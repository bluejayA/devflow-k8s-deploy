"""ProjectAnalyzer — STEP 2 분석 오케스트레이터.

ConfigLoader.stack_decision() 결과로 StackModule 라우팅.
multi-module 감지 + 비개발자 한국어 힌트 (F-39).
상태성 감지 + 신뢰도 (F-38).
추론 실패 시 AnalysisResult.gaps 기록 (NFR-17).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as StdET
from pathlib import Path

import yaml
from defusedxml import ElementTree as ET

from scripts._shared.errors import MultiModuleAbort, UnknownStackError
from scripts._shared.fileio import is_within, read_text_limited
from scripts._shared.types import (
    AnalysisResult,
    ModuleInfo,
    PromptCallback,
    PromptRequest,
    ResolvedConfig,
    StackDetectResult,
    StatefulnessSignal,
)
from scripts.config_loader import ConfigLoader
from scripts.stacks.base import StackModule

# ──────────────────────────────────────────────────────────────────────────────
# 내부 상수
# ──────────────────────────────────────────────────────────────────────────────

# Maven XML 네임스페이스
_MVN_NS = "http://maven.apache.org/POM/4.0.0"

# multi-module 힌트 (한국어)
_MULTI_MODULE_HINT = (
    "여러 모듈이 있어요. API 서버는 보통 -api/-web/-server로 끝나요. "
    "라이브러리(-core, -common)는 배포 대상이 아닙니다."
)

# 취소 키워드
_CANCEL_KEYWORDS = {"취소", "cancel", "q", "quit", "exit", "없음", "아니요"}

# 상태성 — HIGH 시그널 패턴 (Gradle/Maven 텍스트 검색)
_HIGH_STATEFUL_PATTERNS: list[tuple[str, str]] = [
    ("spring-boot-starter-data-jpa", "JPA (spring-boot-starter-data-jpa) 의존성 감지"),
    ("hibernate-core", "Hibernate Core 의존성 감지"),
    ("mybatis", "MyBatis 의존성 감지"),
    ("spring-data-jdbc", "Spring Data JDBC 의존성 감지"),
    ("spring-boot-starter-jdbc", "Spring Boot JDBC Starter 의존성 감지"),
    ("r2dbc", "R2DBC (반응형 DB) 의존성 감지"),
    ("jooq", "jOOQ 의존성 감지"),
]

# 상태성 — MEDIUM 시그널 패턴
_MEDIUM_STATEFUL_PATTERNS: list[tuple[str, str]] = [
    ("spring-kafka", "Kafka 의존성 감지"),
    ("spring-boot-starter-amqp", "RabbitMQ 의존성 감지"),
    ("spring-data-redis", "Redis 의존성 감지"),
    ("spring-boot-starter-data-redis", "Redis (spring-boot-starter-data-redis) 의존성 감지"),
    ("hazelcast", "Hazelcast 캐시 의존성 감지"),
    ("caffeine", "Caffeine 캐시 의존성 감지"),
    ("ehcache", "EhCache 의존성 감지"),
    ("spring-boot-starter-data-mongodb", "MongoDB 의존성 감지"),
    ("spring-boot-starter-data-cassandra", "Cassandra 의존성 감지"),
    ("spring-boot-starter-data-elasticsearch", "Elasticsearch 의존성 감지"),
]

# application.yml datasource 시그널 (HIGH)
_DATASOURCE_URL_PATTERNS = [
    "spring.datasource.url",
    "datasource.url",
    "r2dbc.url",
    "spring.r2dbc.url",
]

# 앱 모듈 판별 패턴 (-api, -web, -server 등 → is_likely_app=True)
_LIKELY_APP_SUFFIXES = ("-api", "-web", "-server", "-app", "-service", "-gateway")
_UNLIKELY_APP_SUFFIXES = ("-core", "-common", "-shared", "-lib", "-util", "-utils", "-model")


def _mvn_find(element: StdET.Element, tag: str) -> StdET.Element | None:
    """ET.Element에서 namespace 포함/미포함 두 가지 방식으로 child 탐색."""
    result = element.find(f"{{{_MVN_NS}}}{tag}")
    if result is not None:
        return result
    return element.find(tag)


def _is_likely_app_module(name: str) -> bool:
    """모듈명으로 앱 서버 여부 추론."""
    name_lower = name.lower()
    # 명확한 라이브러리 패턴이 있으면 False
    for suffix in _UNLIKELY_APP_SUFFIXES:
        if name_lower.endswith(suffix):
            return False
    # 앱 패턴이 있으면 True
    for suffix in _LIKELY_APP_SUFFIXES:
        if name_lower.endswith(suffix):
            return True
    # 기본: True (단일 이름이거나 패턴 불명확)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# 내부 데이터 클래스 (모듈 스코프 — ProjectAnalyzer 앞에 정의)
# ──────────────────────────────────────────────────────────────────────────────


class _StackDetectBundle:
    """_detect_stack 결과 묶음 (내부 전용)."""

    __slots__ = ("stack_name", "module", "detect_result")

    def __init__(
        self,
        stack_name: str,
        module: StackModule,
        detect_result: StackDetectResult,
    ) -> None:
        self.stack_name = stack_name
        self.module = module
        self.detect_result = detect_result


# ──────────────────────────────────────────────────────────────────────────────
# ProjectAnalyzer
# ──────────────────────────────────────────────────────────────────────────────


class ProjectAnalyzer:
    """STEP 2 분석 오케스트레이터.

    config_loader, stack_registry, prompt_callback 3가지 의존성을 DI로 주입받는다.
    prompt_callback이 None이면 자동 추론 + gaps 기록만 (테스트 모드).
    """

    def __init__(
        self,
        config_loader: ConfigLoader,
        stack_registry: dict[str, StackModule],
        prompt_callback: PromptCallback | None = None,
    ) -> None:
        """
        Args:
            config_loader: stack_decision() 호출용 의존성.
            stack_registry: v0.1.0 = {"jvm": JvmStackModule()}.
            prompt_callback: SkillPipeline에서 주입 (multi-module 선택, gaps 보충 질문).
                             None이면 자동 추론 + AnalysisResult.gaps만 채움 (테스트 모드).
        """
        self._config_loader = config_loader
        self._stack_registry = stack_registry
        self._prompt_callback = prompt_callback

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self, project_dir: Path, config: ResolvedConfig) -> AnalysisResult:
        """전체 분석 흐름.

        1. config_loader.stack_decision(config, project_dir) → StackDecision
        2. forced_stack 있으면 해당 모듈, 없으면 _detect_stack() 자동 감지
        3. multi-module이면 _select_module() (prompt_callback 호출, 한국어 힌트)
        4. 선택된 module의 detect/build_plan/probe_plan/defaults/artifact_locator 호출
        5. _detect_statefulness() — 신뢰도 점수와 함께
        6. AnalysisResult 반환 (gaps 포함)

        Returns:
            AnalysisResult — 분석 결과 + gaps(추론 실패)

        Raises:
            UnknownStackError: 어떤 StackModule도 감지하지 못함.
            MultiModuleAbort: 사용자가 모듈 선택 취소.
            UnsupportedStackError: forced_stack이 지원되지 않는 스택.
        """
        gaps: list[str] = []

        # 1. stack 분기 결정
        stack_decision = self._config_loader.stack_decision(config, project_dir)

        # 2. StackModule 선택
        if stack_decision.forced_stack is not None:
            stack_name = stack_decision.forced_stack
            module = self._stack_registry[stack_name]
            detect_result = module.detect(project_dir)
            if detect_result is None:
                # forced_stack이지만 감지 실패 → UnknownStackError
                raise UnknownStackError(
                    f"강제 지정된 stack '{stack_name}'을 프로젝트에서 감지할 수 없습니다. "
                    f"프로젝트 디렉토리를 확인하세요: {project_dir}"
                )
        else:
            stack_detect = self._detect_stack(project_dir)
            stack_name = stack_detect.stack_name
            module = stack_detect.module
            detect_result = stack_detect.detect_result

        # 3. multi-module 감지 및 모듈 선택
        selected_module: ModuleInfo | None = None
        multi_modules = self._detect_multi_modules(project_dir, stack_name)

        if multi_modules:
            selected_module = self._select_module(multi_modules, gaps)
            # 선택된 모듈 디렉토리 기준으로 detect 재실행
            module_dir = selected_module.path
            re_detected = module.detect(module_dir)
            if re_detected is not None:
                detect_result = re_detected
            # else: 모듈 디렉토리에 빌드 파일 없으면 상위 detect_result 유지

        # 4. 선택된 module의 plan 생성
        # 분석 대상 디렉토리: multi-module이면 모듈 디렉토리, 아니면 project_dir
        analysis_dir = selected_module.path if selected_module else project_dir

        build_plan = module.build_plan(detect_result)
        probe_config = module.probe_plan(detect_result)
        resource_defaults = module.defaults()
        artifact_paths = module.artifact_locator(detect_result, analysis_dir)

        # 5. 상태성 감지
        statefulness = self._detect_statefulness(project_dir, selected_module)

        return AnalysisResult(
            stack=stack_name,
            detect_result=detect_result,
            build_plan=build_plan,
            probe_config=probe_config,
            defaults=resource_defaults,
            artifact_paths=artifact_paths,
            selected_module=selected_module,
            statefulness=statefulness,
            gaps=gaps,
        )

    def _detect_stack(self, project_dir: Path) -> _StackDetectBundle:
        """v0.1.0: 등록된 stack 모듈 중 detect()가 성공하는 것 중 첫 매치.

        Returns:
            _StackDetectBundle — (stack_name, module, detect_result)

        Raises:
            UnknownStackError: 아무 것도 감지 못하면 raise.
        """
        for stack_name, module in self._stack_registry.items():
            result = module.detect(project_dir)
            if result is not None:
                return _StackDetectBundle(
                    stack_name=stack_name,
                    module=module,
                    detect_result=result,
                )
        raise UnknownStackError(
            f"프로젝트 스택을 자동 감지할 수 없습니다: {project_dir}. "
            "'.devflow-k8s-deploy.yml'에 'stack: jvm'을 명시하거나 "
            "지원되는 프로젝트 구조인지 확인하세요."
        )

    def _select_module(
        self, modules: list[ModuleInfo], gaps: list[str]
    ) -> ModuleInfo:
        """multi-module 프로젝트에서 모듈 선택.

        prompt_callback이 없으면 첫 모듈 자동 선택 + gap 기록 (테스트 모드).
        있으면 한국어 힌트 포함 PromptRequest로 질문.
        사용자가 취소하면 MultiModuleAbort raise.

        Args:
            modules: 감지된 ModuleInfo 리스트.
            gaps: AnalysisResult.gaps에 기록할 리스트 (in-place 수정).

        Returns:
            선택된 ModuleInfo.

        Raises:
            MultiModuleAbort: 사용자 취소 시.
        """
        if not self._prompt_callback:
            # 테스트 모드 / 자동 모드: 첫 모듈 자동 선택
            first = modules[0]
            gaps.append(f"multi-module auto-selected: {first.name}")
            return first

        # prompt_callback 있음: 사용자에게 선택 요청
        module_names = [m.name for m in modules]
        request = PromptRequest(
            kind="select",
            ko_text=_MULTI_MODULE_HINT,
            options=module_names,
            help_term_id=None,
        )
        answer = self._prompt_callback(request)

        # 취소 확인
        if answer.strip().lower() in _CANCEL_KEYWORDS:
            raise MultiModuleAbort(
                f"사용자가 모듈 선택을 취소했습니다. "
                f"선택 가능한 모듈: {', '.join(module_names)}"
            )

        # 응답에서 모듈 찾기
        answer_stripped = answer.strip()
        for m in modules:
            if m.name == answer_stripped:
                return m

        # 정확히 일치하는 것 없으면 첫 모듈 (fallback)
        gaps.append(
            f"multi-module 선택 응답 '{answer_stripped}'이 모듈 목록과 불일치. "
            f"첫 모듈 '{modules[0].name}' 자동 선택."
        )
        return modules[0]

    def _detect_statefulness(
        self, project_dir: Path, module: ModuleInfo | None
    ) -> StatefulnessSignal:
        """build.gradle/pom.xml 의존성 + application.yml의 datasource 시그널 검사.

        시그널 종류:
        - HIGH: JPA/Hibernate/MyBatis/Spring Data JDBC 의존성
        - HIGH: application.yml/properties에 spring.datasource.url 존재
        - MEDIUM: 메시지 브로커 (Kafka, RabbitMQ)
        - MEDIUM: 캐시 (Redis, Hazelcast, Caffeine)

        판정 기준:
        - HIGH 시그널 1개+ → is_stateful=True, confidence='high'
        - MEDIUM만 있음 → is_stateful=True, confidence='medium'
        - 시그널 없음 → is_stateful=False, confidence='high'

        Returns:
            StatefulnessSignal(is_stateful, confidence, reasons)
        """
        # 분석 대상 디렉토리: 모듈 경로 또는 project_dir
        target_dir = module.path if module is not None else project_dir

        high_reasons: list[str] = []
        medium_reasons: list[str] = []

        # 빌드 파일 텍스트 수집
        build_text = self._read_build_file_text(target_dir)

        # HIGH 시그널: 빌드 파일 의존성
        for pattern, reason_ko in _HIGH_STATEFUL_PATTERNS:
            if pattern.lower() in build_text.lower():
                high_reasons.append(reason_ko)

        # MEDIUM 시그널: 빌드 파일 의존성
        for pattern, reason_ko in _MEDIUM_STATEFUL_PATTERNS:
            if pattern.lower() in build_text.lower():
                medium_reasons.append(reason_ko)

        # HIGH 시그널: application.yml/properties datasource URL
        datasource_reasons = self._check_datasource_url(target_dir)
        high_reasons.extend(datasource_reasons)

        # 판정
        if high_reasons:
            all_reasons = high_reasons + medium_reasons
            return StatefulnessSignal(
                is_stateful=True,
                confidence="high",
                reasons=all_reasons,
            )
        if medium_reasons:
            return StatefulnessSignal(
                is_stateful=True,
                confidence="medium",
                reasons=medium_reasons,
            )
        return StatefulnessSignal(
            is_stateful=False,
            confidence="high",
            reasons=[],
        )

    # ── 내부 헬퍼: multi-module 감지 ──────────────────────────────────────────

    def _detect_multi_modules(
        self, project_dir: Path, stack_name: str
    ) -> list[ModuleInfo]:
        """프로젝트 디렉토리에서 multi-module 구조 감지.

        v0.1.0 JVM 전용:
        - Gradle: settings.gradle(.kts)에 include(...) 발견 시 multi-module
        - Maven: root pom.xml에 <modules> 섹션 존재 시

        Returns:
            ModuleInfo 리스트. 단일 모듈이면 빈 리스트.
        """
        if stack_name != "jvm":
            return []

        # Gradle settings 파일 우선
        for settings_file in [
            project_dir / "settings.gradle.kts",
            project_dir / "settings.gradle",
        ]:
            if settings_file.exists() and is_within(project_dir, settings_file):
                modules = self._parse_gradle_settings(project_dir, settings_file)
                if modules:
                    return modules

        # Maven pom.xml <modules> 섹션
        pom_file = project_dir / "pom.xml"
        if pom_file.exists() and is_within(project_dir, pom_file):
            modules = self._parse_maven_modules(project_dir, pom_file)
            if modules:
                return modules

        return []

    def _parse_gradle_settings(
        self, project_dir: Path, settings_file: Path
    ) -> list[ModuleInfo]:
        """settings.gradle(.kts)에서 include 구문 파싱.

        Gradle Groovy: include 'api', 'core'
        Gradle KTS:   include("api", "core")

        Returns:
            ModuleInfo 리스트.
        """
        try:
            content = read_text_limited(settings_file)
        except (OSError, ValueError, UnicodeDecodeError):
            return []

        # include('a', 'b', ...) 또는 include("a", "b", ...)
        # 여러 라인에 걸친 include도 처리
        include_pattern = re.compile(
            r"""include\s*\(?\s*((?:["'][^"']+["']\s*,?\s*)+)\s*\)?""",
            re.MULTILINE,
        )

        module_names: list[str] = []
        for match in include_pattern.finditer(content):
            args_str = match.group(1)
            # 각 인용된 이름 추출
            names = re.findall(r"""["']([^"']+)["']""", args_str)
            for name in names:
                # ':' prefix 제거 (Kotlin DSL: include(":api"))
                clean_name = name.lstrip(":")
                if clean_name:
                    module_names.append(clean_name)

        if not module_names:
            return []

        return self._build_module_info_list(project_dir, module_names)

    def _parse_maven_modules(
        self, project_dir: Path, pom_file: Path
    ) -> list[ModuleInfo]:
        """root pom.xml에서 <modules> 섹션 파싱.

        Returns:
            ModuleInfo 리스트.
        """
        try:
            content = read_text_limited(pom_file)
            root = ET.fromstring(content)
        except (OSError, ValueError, UnicodeDecodeError, ET.ParseError):
            return []

        # <modules> 요소 탐색 (namespace 있음/없음 양쪽)
        modules_elem = _mvn_find(root, "modules")
        if modules_elem is None:
            return []

        module_names: list[str] = []
        for child in modules_elem:
            # <module>텍스트</module> — namespace 무관
            if child.text:
                name = child.text.strip()
                if name:
                    module_names.append(name)

        if not module_names:
            return []

        return self._build_module_info_list(project_dir, module_names)

    def _build_module_info_list(
        self, project_dir: Path, module_names: list[str]
    ) -> list[ModuleInfo]:
        """모듈 이름 리스트 → ModuleInfo 리스트 생성.

        모듈 디렉토리가 없는 경우에도 경로를 포함해 반환 (가상 모듈 지원).
        """
        result: list[ModuleInfo] = []
        for name in module_names:
            # 경로 구분자로 슬래시 허용 (Gradle: ':api:sub' → 'api/sub')
            path_parts = name.replace(":", "/").split("/")
            module_path = project_dir
            for part in path_parts:
                module_path = module_path / part

            result.append(
                ModuleInfo(
                    name=name,
                    path=module_path,
                    is_likely_app=_is_likely_app_module(name.split("/")[-1]),
                )
            )
        return result

    # ── 내부 헬퍼: 상태성 감지 ────────────────────────────────────────────────

    def _read_build_file_text(self, project_dir: Path) -> str:
        """build.gradle(.kts) 또는 pom.xml 텍스트 읽기.

        여러 빌드 파일이 있으면 모두 합쳐서 반환.
        """
        build_file_names = [
            "build.gradle.kts",
            "build.gradle",
            "pom.xml",
        ]
        texts: list[str] = []
        for name in build_file_names:
            path = project_dir / name
            if path.exists() and is_within(project_dir, path):
                try:
                    text = read_text_limited(path)
                    texts.append(text)
                except (OSError, ValueError, UnicodeDecodeError):
                    pass
        return "\n".join(texts)

    def _check_datasource_url(self, project_dir: Path) -> list[str]:
        """application.yml/properties에서 datasource URL 시그널 확인.

        Returns:
            HIGH 시그널 사유 목록 (한국어).
        """
        reasons: list[str] = []
        resources_dir = project_dir / "src" / "main" / "resources"
        if not resources_dir.exists():
            return []

        # YAML 파일 검사
        for yml_file in [
            resources_dir / "application.yml",
            resources_dir / "application.yaml",
        ]:
            if yml_file.exists() and is_within(project_dir, yml_file):
                found = self._yaml_has_datasource(yml_file)
                if found:
                    reasons.append(f"application YAML에 datasource URL 설정 감지 ({yml_file.name})")
                    break

        if not reasons:
            # profile 파일도 검사
            for yml_file in sorted(resources_dir.glob("application-*.yml")):
                if not is_within(project_dir, yml_file):
                    continue
                if self._yaml_has_datasource(yml_file):
                    reasons.append(f"application YAML에 datasource URL 설정 감지 ({yml_file.name})")
                    break

        # properties 파일 검사
        if not reasons:
            props_file = resources_dir / "application.properties"
            if props_file.exists() and is_within(project_dir, props_file):
                if self._properties_has_datasource(props_file):
                    reasons.append("application.properties에 datasource URL 설정 감지")

        return reasons

    def _yaml_has_datasource(self, yml_file: Path) -> bool:
        """YAML 파일에서 datasource URL 존재 여부."""
        try:
            content = read_text_limited(yml_file)
            data = yaml.safe_load(content)
        except (OSError, ValueError, UnicodeDecodeError, yaml.YAMLError):
            return False

        if not isinstance(data, dict):
            return False

        # spring.datasource.url 체크
        try:
            datasource = data.get("spring", {}).get("datasource", {})
            if isinstance(datasource, dict) and datasource.get("url"):
                return True
        except AttributeError:
            pass

        # r2dbc
        try:
            r2dbc = data.get("spring", {}).get("r2dbc", {})
            if isinstance(r2dbc, dict) and r2dbc.get("url"):
                return True
        except AttributeError:
            pass

        # 평탄화된 형태: datasource.url
        try:
            flat_ds = data.get("datasource", {})
            if isinstance(flat_ds, dict) and flat_ds.get("url"):
                return True
        except AttributeError:
            pass

        return False

    def _properties_has_datasource(self, props_file: Path) -> bool:
        """properties 파일에서 datasource URL 존재 여부."""
        try:
            content = read_text_limited(props_file)
        except (OSError, ValueError, UnicodeDecodeError):
            return False

        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            for ds_pattern in _DATASOURCE_URL_PATTERNS:
                if line.startswith(ds_pattern) and "=" in line:
                    _, _, value = line.partition("=")
                    if value.strip():
                        return True
        return False

