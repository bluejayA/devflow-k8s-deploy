"""DETAIL 단계의 모든 컴포넌트가 공유하는 데이터 모델.
모두 frozen dataclass 또는 Protocol. 변경은 INCEPTION 후속 변경관리 절차로."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

T = TypeVar("T")

# ─── 설정 / 입력 ───


@dataclass(frozen=True)
class ResolvedConfig:
    """ConfigLoader.load() 결과.

    Attributes:
        raw: 병합된 dict (3계층 deep merge 결과)
        source_map: 최상위 키 → 출처 레이어 ('project_config'/'org_config'/'builtin_default')
        warnings: 로드/파싱 과정의 한국어 경고 목록
        layer_raws: 각 계층의 병합 전 원본 dict.
            키: 'project_config' / 'org_config' / 'builtin_default'.
            resolve_namespace 등 계층별 우선순위 조회에 사용.
            v0.1.0 private 성격 — 외부 소비 시 구조 변경될 수 있음.
    """

    raw: dict[str, Any]  # 병합된 dict
    source_map: dict[str, str]  # 키 경로 → 출처 레이어
    warnings: list[str] = field(default_factory=list)
    layer_raws: dict[str, dict[str, Any]] = field(default_factory=dict)  # 계층별 원본 dict


@dataclass(frozen=True)
class NamespaceResolution:
    """ConfigLoader.resolve_namespace() 결과."""

    value: str
    source: Literal["project_config", "org_config", "user_input", "project_dir", "default"]
    requires_confirmation: bool  # 'default' 명시 선택 시 True


@dataclass(frozen=True)
class StackDecision:
    """ConfigLoader.stack_decision() 결과."""

    forced_stack: str | None  # 'jvm' / 'go' / None (auto)
    source: str  # 'project_config' / 'org_config' / 'auto'


@dataclass(frozen=True)
class UserInputs:
    """STEP 1에서 수집한 사용자 입력."""

    app_name: str
    port: int
    exposure: Literal["ClusterIP", "NodePort", "LoadBalancer"]
    namespace: str
    output_dir: Path
    resource_hint: Literal["small", "medium", "large"]
    replicas: int = 2


# ─── 분석 ───


@dataclass(frozen=True)
class StackDetectResult:
    """StackModule.detect() 결과."""

    port: int | None
    # 컨테이너 진입점 힌트. 감지기는 빈 문자열 또는 "java -jar {artifact}" 형태.
    # DockerfileGenerator가 채워도 됨.
    # Go 스택: "."(루트 main.go 확정) 또는 ""(미결정 sentinel — build_plan에서 해결).
    entrypoint: str
    framework: str  # 'spring-boot' / 'ktor' / 'micronaut' / 'jvm-generic' / 'go-generic'
    version: str | None  # Spring Boot 버전 또는 Go 버전 등
    build_system: Literal["gradle", "maven"] | None = None  # JVM 빌드 시스템
    actuator_enabled: bool = False  # Spring Boot Actuator 활성화 여부
    # Go multi-binary 모노레포(kube-style) 후보 디렉토리명 목록 (F-25).
    # 루트 main.go 확정 또는 JVM 등 다른 스택은 기본값 빈 list.
    cmd_candidates: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BuildPlan:
    """StackModule.build_plan() 결과."""

    builder_image: str
    runner_image: str
    build_cmd: str
    artifact_path: str
    # v0.2+ 일반화 예정: stages: list[Stage]


@dataclass(frozen=True)
class ProbeSpec:
    """단일 probe 스펙 (http 또는 tcp)."""

    kind: Literal["http", "tcp"]
    path: str | None  # http일 때만
    port: int


@dataclass(frozen=True)
class ProbeConfig:
    """liveness/readiness probe 쌍."""

    liveness: ProbeSpec
    readiness: ProbeSpec


@dataclass(frozen=True)
class ResourceDefaults:
    """StackModule.defaults() 결과 — 리소스 기본값."""

    cpu_request: str
    memory_request: str
    cpu_limit: str
    memory_limit: str
    writable_paths: list[str]  # ['/tmp', '/var/log']
    # 컨테이너 런타임 UID (F-30). JVM 관례 1000(alpine adduser -u 1000) 기본값.
    # Go 스택은 distroless nonroot 내장 UID 65532 명시 필수 —
    # 누락 시 NFR-04 (r) UID 정합성 테스트 실패로 감지.
    run_as_user: int = 1000


@dataclass(frozen=True)
class ModuleInfo:
    """multi-module 프로젝트의 개별 모듈 정보."""

    name: str
    path: Path
    is_likely_app: bool  # '-api', '-web', '-server' 패턴 매칭


@dataclass(frozen=True)
class StatefulnessSignal:
    """상태성 감지 결과 + 신뢰도."""

    is_stateful: bool
    confidence: Literal["high", "medium", "low"]
    reasons: list[str]  # 한국어 사유


@dataclass(frozen=True)
class ClusterConfig:
    """cluster.preset 기반 환경 설정."""

    preset: str
    storage_class: str | None  # None = 클러스터 기본값 사용
    network_policy: bool


@dataclass(frozen=True)
class AnalysisResult:
    """ProjectAnalyzer.analyze() 최종 결과."""

    stack: str  # 'jvm'
    detect_result: StackDetectResult
    build_plan: BuildPlan
    probe_config: ProbeConfig
    defaults: ResourceDefaults
    artifact_paths: list[Path]
    selected_module: ModuleInfo | None
    statefulness: StatefulnessSignal
    gaps: list[str]  # 추론 실패 항목


# ─── 도움말 ───


@dataclass(frozen=True)
class HelpEntry:
    """HelpCatalog 항목 — 비개발자 한국어 설명."""

    term_id: str
    ko_short: str
    ko_detail: str
    original: str
    example: str
    step: Literal[1, 2, "config"]


# ─── 생성 ───


@dataclass(frozen=True)
class GeneratedArtifacts:
    """STEP 3 생성 결과물 경로."""

    dockerfile_path: Path
    manifest_paths: list[Path]  # deployment/service/serviceaccount


# ─── 검증 ───


@dataclass(frozen=True)
class CheckResult:
    """K8sValidator 단일 규칙 결과."""

    rule_id: str  # 'SEC-001' 등
    level: Literal["PASS", "WARN", "FAIL"]
    container: str
    message_ko: str
    message_en: str
    suggestion: str


@dataclass(frozen=True)
class ValidationReport:
    """K8sValidator.validate() 결과."""

    results: list[CheckResult]
    counts: dict[Literal["pass", "warn", "fail"], int]
    exit_code: int  # 0 / 1 / 2
    skipped: list[str]  # CLI --skipped 인자 통과값


@dataclass(frozen=True)
class DryRunResult:
    """KubectlDryRunner.dry_run() 결과. F-56 degraded 시 None 필드."""

    success: bool
    stdout: str | None
    stderr: str | None
    exit_code: int | None
    skipped: bool  # True면 미설치
    skip_reason_ko: str | None


@dataclass(frozen=True)
class BuildResult:
    """ContainerBuildRunner.build() 결과."""

    success: bool
    image_ref: str | None  # repository:tag (성공 시)
    engine: Literal["docker", "podman", "nerdctl"] | None
    skipped: bool
    skip_reason_ko: str | None
    stdout: str | None = None  # 빌드 표준 출력 — Unit 13 retry_loop fix 근거
    stderr: str | None = None  # 빌드 표준 에러 — OutputPackager troubleshoot
    exit_code: int | None = None  # 프로세스 종료 코드 — auto-fix 조건 판단


@dataclass
class ValidationOutcome:
    """SkillPipeline.step4_validate_gate() 결과 — STEP 5로 pass-through."""

    k8s_report: ValidationReport
    dry_run: DryRunResult | None
    build: BuildResult | None
    skipped: list[str]  # ['kubectl_dry_run', 'container_build']
    skip_reasons: dict[str, str]  # 식별자 → 한국어 사유
    bailed: bool


# ─── 재시도 ───


@dataclass(frozen=True)
class FixOutcome:
    """fix_attempt() 반환 구조체.

    applied: 이번 attempt 이전에 수정이 실제로 적용됐는가
             (False면 다음 attempt 안 함 — 즉시 bailout)
    summary_ko: 수정 내용 한국어 요약. troubleshoot.md attempts 로그에 사용.
                applied=False여도 사유를 한국어로 기록 (예: '수정안 생성 실패')
    """

    applied: bool
    summary_ko: str | None


@dataclass
class RetryAttempt(Generic[T]):
    """단일 재시도 attempt 기록."""

    attempt_number: int  # 1-based
    result: T | None  # operation 반환값 (예외 시 None)
    error: Exception | None  # operation 예외 (성공 시 None)
    success: bool  # success_predicate 결과
    fix_outcome: FixOutcome | None  # 이 attempt 직후 fix_attempt 결과 (마지막 attempt면 None)


@dataclass
class RetryResult(Generic[T]):
    """retry_with_fix() 반환 구조체."""

    success: bool  # 마지막 attempt가 success_predicate True
    final_result: T | None  # 마지막 성공 결과 (실패 시 마지막 attempt의 result)
    attempts: list[RetryAttempt[T]]  # 전체 시도 로그 (troubleshoot.md 입력)
    bailout: bool  # True면 max_attempts 초과 또는 fix_outcome.applied=False


# ─── 패키징 ───


@dataclass(frozen=True)
class PackagingResult:
    """OutputPackager.write() 결과."""

    final_dir: Path
    files_written: list[str]
    troubleshoot_written: bool
    final_path: Path | None = None  # AtomicWriter.commit() 결과 — SkillPipeline이 채움
    validation_exit_code: int | None = None  # F-42 exit code (0/1/2). None이면 0으로 처리


@dataclass(frozen=True)
class BailOutContext:
    """OutputPackager.write_troubleshoot() 입력.

    주의: `en_detail`과 `attempts_log[*].error`는 subprocess stderr 원문을 담을 수 있어
    민감정보(kubeconfig 경로, 토큰)가 흘러갈 위험이 있다.
    troubleshoot.md로 직렬화하는 책임은 OutputPackager unit에 있으며,
    그 시점에 redact를 반드시 적용한다.
    """

    step_number: int  # 4 (검증 게이트에서 bail)
    step_name_ko: str  # 'STEP 4 정적 검증'
    component_ko: str  # 'K8s 검증기'
    ko_summary: str  # 한국어 1-2줄
    en_detail: str
    attempts_log: list[RetryAttempt[Any]]  # _shared/types.RetryAttempt 리스트


# ─── 프롬프트 콜백 (UI 추상화) ───


@dataclass(frozen=True)
class PromptRequest:
    """prompt_callback에 전달되는 요청 구조체."""

    kind: Literal["question", "confirm", "select"]
    ko_text: str  # 한국어 질문
    options: list[str] | None  # select일 때
    help_term_id: str | None  # "? 도움말" 옵션 활성화 시 HelpCatalog 키


PromptCallback = Callable[["PromptRequest"], str]
"""SkillPipeline에서 ProjectAnalyzer/AtomicWriter에 주입.
None이면 자동 모드 (테스트성)."""


# ─── 메시지 정책 (NFR-17) ───


class MessagePolicy:
    """NFR-17 한국어+원어 병기 포맷터."""

    @staticmethod
    def format_question(ko_text: str, original: str | None = None) -> str:
        """사용자 질문 메시지. 한국어 우선, 원어 괄호."""
        if original:
            return f"{ko_text} ({original})"
        return ko_text

    @staticmethod
    def format_error(ko_summary: str, en_detail: str | None = None) -> str:
        """에러 메시지. 한국어 요약 + 영문 상세."""
        if en_detail:
            return f"{ko_summary}\n(영문) {en_detail}"
        return ko_summary
