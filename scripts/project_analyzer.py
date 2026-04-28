"""ProjectAnalyzer — STEP 2 분석 오케스트레이터.

ConfigLoader.stack_decision() 결과로 StackModule 라우팅.
multi-module 감지 + 비개발자 한국어 힌트 (F-39).
상태성 감지 + 신뢰도 (F-38).
추론 실패 시 AnalysisResult.gaps 기록 (NFR-17).
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
import xml.etree.ElementTree as StdET
from pathlib import Path
from typing import Any, Literal

import yaml
from defusedxml import ElementTree as ET

from scripts._shared.errors import (
    GoDetectionError,
    JvmDetectionError,
    MultiModuleAbort,
    UnknownStackError,
    UnsupportedStackError,
)
from scripts._shared.fileio import check_yaml_refs, is_within, read_text_limited
from scripts._shared.text_safety import reject_unsafe_chars
from scripts._shared.types import (
    AnalysisResult,
    ModuleInfo,
    ProbeConfig,
    ProbeSpec,
    PromptCallback,
    PromptRequest,
    ResolvedConfig,
    StackDetectResult,
    StatefulnessSignal,
    UserInputs,
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

# BL-001 Phase 5 보안 가드 — Codex/security-reviewer P1 대응.
# entrypoint: 영숫자 + `_./-`만 허용, 길이 ≤ 256, `..` segment 금지(path traversal),
# 선행 공백/세미콜론/$/백틱/개행 등 shell metachar 차단.
# Phase 6의 F-29 `validate_go_entrypoint`와 동일 정책 (정식 헬퍼는 Phase 6에서 분리).
_GO_ENTRYPOINT_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_MAX_ENTRYPOINT_LEN = 256

# probe.path: HTTP path 화이트리스트. 슬래시 시작 + 안전 문자만 + 길이 ≤ 512.
# manifest YAML 무검증 삽입 차단(개행/제어문자/`<>` 등).
_PROBE_PATH_RE = re.compile(r"^/[A-Za-z0-9._\-/?=&%]{0,512}$")

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

# Path traversal 방어 — 모듈 이름 허용 문자셋 (NUL/제어문자/경로 탈출 차단)
_MODULE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-./]+$")
# 모듈 수 상한 (ReDoS 방어 보조)
_MAX_MODULES = 500

# prompt_callback 응답 최대 길이
_MAX_ANSWER_LEN = 256


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


def _validate_module_name(name: str) -> str | None:
    """모듈 이름 유효성 검사 + Gradle Kotlin DSL 콜론 prefix 정규화.

    Gradle Kotlin DSL 관례: ":api" → "api" (선행 콜론 제거).
    중첩 모듈 ("foo:bar") 은 v0.1.0 미지원 → None 반환.

    Returns:
        정규화된 이름 (str) 이면 유효, None 이면 거부.
    """
    # NUL 또는 제어문자 포함 거부
    if any(ord(c) < 0x20 for c in name):
        return None

    # 절대경로 거부 (Unix '/')
    if name.startswith("/"):
        return None

    # Gradle Kotlin DSL 관례: 선행 ':' 제거 (":api" → "api")
    normalized = name.lstrip(":")

    # lstrip 후 빈 문자열이면 거부 (예: ":::")
    if not normalized:
        return None

    # 중첩 모듈 거부 — 앞 콜론 제거 후에도 ':'가 남아있으면 v0.1.0 미지원
    # 예: ":foo:bar" → "foo:bar" → 콜론 포함 → 거부
    if ":" in normalized:
        return None

    # Windows 드라이브 문자 거부 ('C:' 형태)
    # 이 시점엔 콜론은 없으므로, ':' 로 시작하는 케이스는 이미 위에서 처리됨
    # 하지만 normalize 전 원본이 "C:" 형태일 수 있으므로 확인
    if len(name.lstrip(":")) >= 2 and name.lstrip(":")[1] == ":":
        return None

    # '..' 세그먼트 거부
    segments = re.split(r"[/\\]", normalized)
    if any(seg.strip() == ".." for seg in segments):
        return None

    # 허용 문자셋 검사
    if not _MODULE_NAME_RE.fullmatch(normalized):
        return None

    return normalized


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
        # analyze() 실행 중 설정되는 project_root (재사용 안전을 위해 종료 시 None 리셋)
        self._project_root: Path | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_stack_overrides(
        detect_result: StackDetectResult, stack_config: dict[str, Any]
    ) -> StackDetectResult:
        """F-27/A-08: config의 `stack.<name>.entrypoint`를 detect_result에 반영.

        A-08 우선순위 1단계: config entrypoint > app_name 매칭 > 단일 후보.
        config_loader.resolve_stack_config 결과(빈 dict 가능)를 받아 frozen dataclass replace.

        보안 가드 (Codex/security-reviewer P1, Phase 6 F-29 사전 격리):
          - 화이트리스트 정규식 `^[A-Za-z0-9_./-]+$` (shell metachar 차단)
          - 길이 ≤ 256
          - `..` segment 금지 (path traversal 차단)
          - 위반 시 `ValueError` raise — Phase 6 `go build` 합성 전 trust boundary 닫음.
        """
        entrypoint = stack_config.get("entrypoint")
        if isinstance(entrypoint, str) and entrypoint:
            if (
                len(entrypoint) > _MAX_ENTRYPOINT_LEN
                or not _GO_ENTRYPOINT_RE.match(entrypoint)
                or ".." in entrypoint
            ):
                raise ValueError(
                    f"stack.<name>.entrypoint 형식이 올바르지 않음: {entrypoint!r}. "
                    f"허용: ^[A-Za-z0-9_./-]+$, 길이 ≤ {_MAX_ENTRYPOINT_LEN}, "
                    f"'..' segment 금지"
                )
            return dataclasses.replace(detect_result, entrypoint=entrypoint)
        return detect_result

    @staticmethod
    def _apply_probe_overrides(
        probe_config: ProbeConfig, stack_config: dict[str, Any]
    ) -> ProbeConfig:
        """F-19/F-27: config의 `stack.<name>.probe.path`로 ProbeConfig HTTP path를 override.

        TCP probe는 path 무관으로 영향 없음.

        보안 가드 (Codex/security-reviewer P1):
          - 개행/NUL/제어문자 차단 (`reject_unsafe_chars` — manifest YAML 오염 방지)
          - 화이트리스트 정규식 `^/[A-Za-z0-9._\\-/?=&%]{0,512}$`
          - 위반 시 `ValueError` raise.
        """
        probe_section = stack_config.get("probe")
        if not isinstance(probe_section, dict):
            return probe_config
        path_override = probe_section.get("path")
        if not isinstance(path_override, str) or not path_override:
            return probe_config

        # 1차 가드: 개행/NUL/제어문자
        reject_unsafe_chars(path_override, "stack.<name>.probe.path")
        # 2차 가드: 화이트리스트 정규식
        if not _PROBE_PATH_RE.match(path_override):
            raise ValueError(
                f"stack.<name>.probe.path 형식이 올바르지 않음: {path_override!r}. "
                f"허용: ^/[A-Za-z0-9._\\-/?=&%]{{0,512}}$"
            )

        def _override(spec: ProbeSpec) -> ProbeSpec:
            if spec.kind == "http":
                return dataclasses.replace(spec, path=path_override)
            return spec

        return ProbeConfig(
            liveness=_override(probe_config.liveness),
            readiness=_override(probe_config.readiness),
        )

    def analyze(
        self,
        project_dir: Path,
        config: ResolvedConfig,
        resource_hint: Literal["small", "medium", "large"] = "medium",
        *,
        inputs: UserInputs | None = None,
    ) -> AnalysisResult:
        """전체 분석 흐름.

        1. config_loader.stack_decision(config, project_dir) → StackDecision
        2. forced_stack 있으면 해당 모듈, 없으면 _detect_stack() 자동 감지
        3. multi-module이면 _select_module() (prompt_callback 호출, 한국어 힌트)
        4. 선택된 module의 detect/build_plan/probe_plan/defaults/artifact_locator 호출
        5. _detect_statefulness() — 신뢰도 점수와 함께
        6. AnalysisResult 반환 (gaps 포함)

        Args:
            resource_hint: v0.2.0+ — tier별 defaults 차등 반영 (small/medium/large).
                           미지정 시 medium 유지 (back-compat 기본값).

        Returns:
            AnalysisResult — 분석 결과 + gaps(추론 실패)

        Raises:
            UnknownStackError: 어떤 StackModule도 감지하지 못함.
            MultiModuleAbort: 사용자가 모듈 선택 취소.
            UnsupportedStackError: forced_stack이 지원되지 않는 스택.
        """
        # is_within 검사에 사용할 project_root 저장
        self._project_root = project_dir.resolve()
        try:
            return self._analyze_impl(project_dir, config, resource_hint, inputs)
        finally:
            self._project_root = None

    def _analyze_impl(
        self,
        project_dir: Path,
        config: ResolvedConfig,
        resource_hint: Literal["small", "medium", "large"],
        inputs: UserInputs | None,
    ) -> AnalysisResult:
        """analyze() 실제 구현 (project_root 설정 후 호출)."""
        gaps: list[str] = []

        # 1. stack 분기 결정
        stack_decision = self._config_loader.stack_decision(config, project_dir)

        # 2. StackModule 선택
        if stack_decision.forced_stack is not None:
            stack_name = stack_decision.forced_stack
            try:
                module = self._stack_registry[stack_name]
            except KeyError:
                raise UnsupportedStackError(
                    f"지원하지 않는 stack: '{stack_name}' (v0.1.0은 jvm만)"
                ) from None
            detect_result = module.detect(project_dir)
            if detect_result is None:
                # forced_stack이지만 감지 실패 → UnknownStackError
                raise UnknownStackError(
                    f"강제 지정된 stack '{stack_name}'을 프로젝트에서 감지할 수 없습니다. "
                    f"프로젝트 디렉토리를 확인하세요: {project_dir}"
                )
        else:
            stack_detect = self._detect_stack(project_dir, gaps)
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

        # 4. config override 추출 (F-33) + detect_result에 stack.<name>.entrypoint 적용 (F-27)
        stack_config = self._config_loader.resolve_stack_config(config, stack_name)
        detect_result = self._apply_stack_overrides(detect_result, stack_config)

        # Codex P1: detect_result.port가 None이면 inputs.port로 채워 plan 단계 정합성 보장.
        # Go는 detect 단계에서 port 추론 불가(소스 정적 분석 한계) — inputs가 진실의 출처.
        # JVM은 application.yml 추론 성공 시 detect_result.port가 채워져 영향 없음.
        if detect_result.port is None and inputs is not None:
            detect_result = dataclasses.replace(detect_result, port=inputs.port)

        # 5. 선택된 module의 plan 생성
        # 분석 대상 디렉토리: multi-module이면 모듈 디렉토리, 아니면 project_dir
        analysis_dir = selected_module.path if selected_module else project_dir

        # F-24: build_plan에 inputs 전달 (Optional). Phase 5 이후 명시 전달.
        build_plan = module.build_plan(detect_result, inputs=inputs)
        probe_config = module.probe_plan(detect_result)
        # F-19: probe_config에 stack.<name>.probe.path override 적용
        probe_config = self._apply_probe_overrides(probe_config, stack_config)
        resource_defaults = module.defaults(resource_hint)
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

    def _detect_stack(
        self, project_dir: Path, gaps: list[str]
    ) -> _StackDetectBundle:
        """v0.1.0: 등록된 stack 모듈 중 detect()가 성공하는 것 중 첫 매치.

        BL-001 Phase 9 Round 2 (Codex P1): `StackModule.detect`가 detect 단계
        예외(`JvmDetectionError` / `GoDetectionError`)를 던지면 catch하여 gaps에
        기록하고 다음 스택으로 폴백한다 (base.py:35 Strangler 계약).

        Returns:
            _StackDetectBundle — (stack_name, module, detect_result)

        Raises:
            UnknownStackError: 모든 스택이 None 반환 또는 detect 예외라 매치 없으면 raise.
        """
        for stack_name, module in self._stack_registry.items():
            try:
                result = module.detect(project_dir)
            except (JvmDetectionError, GoDetectionError) as exc:
                gaps.append(
                    f"stack '{stack_name}' detect 실패 — 다음 스택으로 폴백: {exc}"
                )
                continue
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

        # ── 응답 검증 ──────────────────────────────────────────────────────
        if not isinstance(answer, str):
            raise MultiModuleAbort("사용자 응답이 문자열이 아님")
        if len(answer) > _MAX_ANSWER_LEN:
            raise MultiModuleAbort(f"사용자 응답이 너무 김 ({_MAX_ANSWER_LEN}자 초과)")
        # BIDI/NUL/ANSI escape 등 제어문자 제거
        answer = "".join(
            c for c in answer
            if c.isprintable() and not unicodedata.category(c).startswith("C")
        )

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

        ## 휴리스틱 한계
        이 메서드는 빌드 파일 텍스트 **전체**에서 의존성 패턴을 단순 문자열 검색한다.
        따라서 다음 false positive가 가능:
        - 주석 처리된 의존성 (`// implementation("spring-boot-starter-data-jpa")`)
        - 변수명/문자열 리터럴에 키워드 포함 (`description = "not using mybatis"`)
        - 파생 artifact 이름 (`mybatis-generator`, `not-hibernate`)

        v0.1.0은 **보수적 과탐지**를 허용한다 — 실제 stateful인데 stateless로 판정되는
        false negative보다 그 반대가 안전하기 때문(사용자에게 경고 + rationale 기록).
        v0.2+에서 AST 파싱 기반 정밀화 예정.

        Returns:
            StatefulnessSignal(is_stateful, confidence, reasons)
        """
        high_reasons: list[str] = []
        medium_reasons: list[str] = []

        if module is not None:
            # multi-module: project_root와 module.path 양쪽에서 빌드 파일 수집
            root_build_text = self._read_build_file_text(project_dir)
            module_build_text = self._read_build_file_text(module.path)
            build_text = root_build_text + "\n" + module_build_text
        else:
            # single-module: project_dir만
            build_text = self._read_build_file_text(project_dir)

        # HIGH 시그널: 빌드 파일 의존성
        for pattern, reason_ko in _HIGH_STATEFUL_PATTERNS:
            if pattern.lower() in build_text.lower():
                high_reasons.append(reason_ko)

        # MEDIUM 시그널: 빌드 파일 의존성
        for pattern, reason_ko in _MEDIUM_STATEFUL_PATTERNS:
            if pattern.lower() in build_text.lower():
                medium_reasons.append(reason_ko)

        # HIGH 시그널: application.yml/properties datasource URL
        # multi-module: module.path 우선, 없으면 project_dir 확인
        if module is not None:
            datasource_reasons = self._check_datasource_url(module.path)
            if not datasource_reasons:
                datasource_reasons = self._check_datasource_url(project_dir)
        else:
            datasource_reasons = self._check_datasource_url(project_dir)
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

        2단계 파싱:
        1. include 구문 라인/블록 범위를 찾음
        2. 범위 내에서 제한된 문자셋으로 이름만 추출 (NUL/제어문자/경로 구분자 일부 차단)

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
            # 허용 문자셋 제한: NUL/제어문자 차단, 경로 구분자(백슬래시) 차단
            # ':'는 허용 — Kotlin DSL ":api" 패턴 지원 (_validate_module_name에서 처리)
            names = re.findall(r"""["']([^"'\\/\x00-\x1f]+)["']""", args_str)
            for name in names:
                clean_name = name.strip()
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
            # <module>텍스트</module> 태그만 처리 — namespace 무관
            if not child.tag.endswith("}module") and child.tag != "module":
                continue
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

        보안:
        - 모듈 수 상한 (_MAX_MODULES) 초과 시 truncate + gap 기록 (ReDoS 방어)
        - 각 이름에 대해 path traversal / 제어문자 / 절대경로 검증
        - 검증 실패 시 해당 모듈 skip (gaps는 호출부에서 관리하지 않으므로 무시)
        - module_path가 project_dir 밖을 가리키면 skip
        """
        result: list[ModuleInfo] = []

        # 모듈 수 상한 적용
        names_to_process = module_names[:_MAX_MODULES]

        for raw_name in names_to_process:
            # 이름 유효성 검사 + Kotlin DSL 콜론 prefix 정규화
            normalized_name = _validate_module_name(raw_name)
            if normalized_name is None:
                continue

            # 경로 구분자로 슬래시 허용 (Gradle path → 디렉토리 경로)
            path_parts = normalized_name.split("/")
            module_path = project_dir
            for part in path_parts:
                module_path = module_path / part

            # project_root 밖을 가리키면 skip (path traversal 방어)
            # self._project_root가 None인 경우 (직접 호출 등) project_dir 기준 사용
            root_for_check = self._project_root if self._project_root is not None else project_dir
            if not is_within(root_for_check, module_path):
                continue

            result.append(
                ModuleInfo(
                    name=normalized_name,
                    path=module_path,
                    is_likely_app=_is_likely_app_module(normalized_name.split("/")[-1]),
                )
            )
        return result

    # ── 내부 헬퍼: 상태성 감지 ────────────────────────────────────────────────

    def _read_build_file_text(self, scan_dir: Path) -> str:
        """build.gradle(.kts) 또는 pom.xml 텍스트 읽기.

        여러 빌드 파일이 있으면 모두 합쳐서 반환.
        is_within 검사는 self._project_root 기준으로 수행 (Important 1 수정).
        """
        build_file_names = [
            "build.gradle.kts",
            "build.gradle",
            "pom.xml",
        ]
        # project_root가 설정되지 않은 경우 scan_dir 자체를 root로 fallback
        root_for_check = self._project_root if self._project_root is not None else scan_dir
        texts: list[str] = []
        for name in build_file_names:
            path = scan_dir / name
            if path.exists() and is_within(root_for_check, path):
                try:
                    text = read_text_limited(path)
                    texts.append(text)
                except (OSError, ValueError, UnicodeDecodeError):
                    pass
        return "\n".join(texts)

    def _check_datasource_url(self, scan_dir: Path) -> list[str]:
        """application.yml/properties에서 datasource URL 시그널 확인.

        is_within 검사는 self._project_root 기준으로 수행.

        Returns:
            HIGH 시그널 사유 목록 (한국어).
        """
        root_for_check = self._project_root if self._project_root is not None else scan_dir
        reasons: list[str] = []
        resources_dir = scan_dir / "src" / "main" / "resources"
        if not resources_dir.exists():
            return []

        # YAML 파일 검사
        for yml_file in [
            resources_dir / "application.yml",
            resources_dir / "application.yaml",
        ]:
            if yml_file.exists() and is_within(root_for_check, yml_file):
                found = self._yaml_has_datasource(yml_file)
                if found:
                    reasons.append(f"application YAML에 datasource URL 설정 감지 ({yml_file.name})")
                    break

        if not reasons:
            # profile 파일도 검사
            for yml_file in sorted(resources_dir.glob("application-*.yml")):
                if not is_within(root_for_check, yml_file):
                    continue
                if self._yaml_has_datasource(yml_file):
                    reasons.append(f"application YAML에 datasource URL 설정 감지 ({yml_file.name})")
                    break

        # properties 파일 검사
        if not reasons:
            props_file = resources_dir / "application.properties"
            if props_file.exists() and is_within(root_for_check, props_file):
                if self._properties_has_datasource(props_file):
                    reasons.append("application.properties에 datasource URL 설정 감지")

        return reasons

    def _yaml_has_datasource(self, yml_file: Path) -> bool:
        """YAML 파일에서 datasource URL 존재 여부.

        YAML bomb 방어: check_yaml_refs()로 anchor/alias 개수 사전 검사.
        """
        try:
            content = read_text_limited(yml_file)
            check_yaml_refs(content)  # YAML bomb 방어
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
