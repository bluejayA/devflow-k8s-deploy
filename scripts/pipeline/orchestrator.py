"""Skill Pipeline Orchestrator — 5-STEP 전체 진행.

STEP 1: 입력 수집 + 도움말 흐름 (F-02a/b)
STEP 2: 코드 분석 (ProjectAnalyzer)
STEP 3: 아티팩트 생성 (DockerfileGenerator + ManifestGenerator) with AtomicWriter
STEP 4: 검증 게이트 (K8sValidator + KubectlDryRunner + optional BuildRunner) with retry_loop
STEP 5: 패키징 + skipped 기록 (OutputPackager) with AtomicWriter commit

메시지 정책 (NFR-17): 모든 사용자 대면 메시지 한국어 우선 + 원어 병기.
도움말 카탈로그: 10개 term (F-02b) — HelpCatalog.
"""

from __future__ import annotations

import dataclasses
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from scripts._shared.errors import BailOutError, InvalidImageError, UserAbort
from scripts._shared.image_ref import validate_image_reference
from scripts._shared.text_safety import reject_unsafe_chars
from scripts._shared.types import (
    AnalysisResult,
    BailOutContext,
    ClusterConfig,
    FixOutcome,
    GeneratedArtifacts,
    HelpEntry,
    MessagePolicy,
    PackagingResult,
    PromptCallback,
    PromptRequest,
    ResolvedConfig,
    RetryAttempt,
    UserInputs,
    ValidationOutcome,
)
from scripts.atomic_writer import AtomicWriter
from scripts.pipeline.retry_loop import (
    collect_validation_outcome,
    run_build_loop,
    run_dry_run_loop,
    run_validation_loop,
)

if TYPE_CHECKING:
    from scripts.config_loader import ConfigLoader
    from scripts.dockerfile_generator import DockerfileGenerator
    from scripts.kubectl_dry_runner import KubectlDryRunner
    from scripts.manifest_generator import ManifestGenerator
    from scripts.output_packager import OutputPackager
    from scripts.pipeline.build_runner import BuildRunner
    from scripts.project_analyzer import ProjectAnalyzer
    from scripts.stacks.base import StackModule
    from scripts.validate_k8s import K8sValidator


# ─── HelpCatalog ───────────────────────────────────────────────────────────────


class HelpCatalog:
    """F-02b 도움말 사전. application-design §A의 10개 term을 정적 포함."""

    _ENTRIES: dict[str, HelpEntry] = {
        # ── STEP 1: 입력 수집 (F-02 매핑 6개) ──
        "app_name": HelpEntry(
            term_id="app_name",
            ko_short="앱 이름은 뭘로 할까요?",
            ko_detail=(
                "앱 이름은 쿠버네티스에서 이 앱을 식별하는 라벨이에요. "
                "보통 프로젝트 이름과 같게 짓고, 영문 소문자/숫자/하이픈만 사용합니다."
            ),
            original=(
                "Deployment.metadata.name + Service.metadata.name "
                "+ ServiceAccount.metadata.name"
            ),
            example="my-api-service / order-backend",
            step=1,
        ),
        "port": HelpEntry(
            term_id="port",
            ko_short="앱이 어떤 포트를 쓰나요?",
            ko_detail=(
                "앱이 요청을 받는 네트워크 포트예요. "
                "Spring Boot는 보통 8080입니다. "
                "application.yml에 server.port가 적혀 있으면 그 값을 쓰세요."
            ),
            original="Container port + Service.spec.ports[].targetPort",
            example="8080 (Spring Boot 기본) / 9000 (커스텀)",
            step=1,
        ),
        "exposure": HelpEntry(
            term_id="exposure",
            ko_short="어디서 접속할 건가요?",
            ko_detail=(
                "앱을 어떤 범위에서 접속 가능하게 할지 결정해요. "
                "(a) 사내 네트워크만(다른 앱끼리만 호출) "
                "(b) 외부 인터넷(클라우드 비용 발생, 월 $20+)"
            ),
            original=(
                "Service.spec.type — ClusterIP(사내) / NodePort(노드 포트) / LoadBalancer(외부)"
            ),
            example="백엔드 API: ClusterIP / 모바일/웹 공개: LoadBalancer",
            step=1,
        ),
        "namespace": HelpEntry(
            term_id="namespace",
            ko_short="네임스페이스는 뭘로 할까요?",
            ko_detail=(
                "네임스페이스(namespace)는 쿠버네티스에서 앱들을 분류하는 폴더 같은 개념이에요. "
                "보통 프로젝트나 팀 이름을 씁니다. "
                "'default'는 사고 방지를 위해 자동 배정되지 않아요."
            ),
            original="Kubernetes Namespace — 리소스 격리 + RBAC 경계",
            example="my-team / payment-svc / dev-jay",
            step=1,
        ),
        "output_dir": HelpEntry(
            term_id="output_dir",
            ko_short="생성 파일을 어디에 둘까요?",
            ko_detail=(
                "Dockerfile과 yaml 파일이 만들어질 폴더예요. "
                "기본은 'k8s-output/'이고, 이미 있으면 덮어쓸지 다시 물어봅니다."
            ),
            original="Output directory (config: output.dir)",
            example="k8s-output (기본) / deploy/k8s",
            step=1,
        ),
        "resource_hint": HelpEntry(
            term_id="resource_hint",
            ko_short="메모리/CPU는 어느 정도 필요해요?",
            ko_detail=(
                "앱이 사용할 자원을 추정해주세요. "
                "JVM은 기본 메모리 512Mi~1Gi를 추천합니다. "
                "잘 모르겠으면 'medium'을 고르세요."
            ),
            original="spec.containers[].resources.{requests,limits}.{cpu,memory}",
            example="small (256Mi/0.5CPU) / medium (512Mi/1CPU) / large (1Gi/2CPU)",
            step=1,
        ),
        # ── STEP 2: 추론 실패 보충 / 경고 (F-03/F-38/F-39 매핑 3개) ──
        "actuator": HelpEntry(
            term_id="actuator",
            ko_short="actuator를 쓰고 있나요?",
            ko_detail=(
                "actuator는 Spring Boot의 헬스체크/메트릭 기능이에요. "
                "build.gradle에 'spring-boot-starter-actuator'가 있으면 활성화된 거예요. "
                "없으면 TCP로 헬스체크합니다."
            ),
            original="Spring Boot Actuator — /actuator/health 엔드포인트",
            example="Boot 2.x: /actuator/health 단일 / Boot 3.x: /liveness + /readiness 분리",
            step=2,
        ),
        "multi_module": HelpEntry(
            term_id="multi_module",
            ko_short="여러 모듈 중 어느 걸 배포할까요?",
            ko_detail=(
                "Gradle/Maven multi-module 프로젝트예요. "
                "보통 API 서버는 '-api', '-web', '-server'로 끝나는 모듈이에요. "
                "라이브러리(-core, -common)는 배포 대상이 아닙니다."
            ),
            original="Gradle settings.gradle(.kts) / Maven <modules>",
            example="order-api (○) / order-core (×, 라이브러리)",
            step=2,
        ),
        "stateful": HelpEntry(
            term_id="stateful",
            ko_short="상태성 앱이라는 게 뭐예요? (경고 발생 시)",
            ko_detail=(
                "DB 연결이나 파일 저장이 필요한 앱이에요. "
                "v0.1.0은 Deployment만 만들기 때문에, Pod 재시작 시 데이터가 사라질 수 있어요. "
                "v0.2부터 StatefulSet/PVC를 지원합니다."
            ),
            original="StatefulSet vs Deployment — Pod 재시작 시 데이터 보존",
            example="stateless: 일반 API 서버 / stateful: DB, 메시지 큐, 파일 업로드 앱",
            step=2,
        ),
        # ── 설정 파일 옵션 (F-61 매핑 1개) ──
        "build_engine": HelpEntry(
            term_id="build_engine",
            ko_short="이미지를 직접 빌드할까요?",
            ko_detail=(
                "기본은 Dockerfile만 만들고 빌드는 안 해요. "
                "빌드도 하고 싶으면 'auto'를 고르세요 (docker/podman/nerdctl 자동 감지). "
                "CI에서는 보통 별도 단계에서 빌드합니다."
            ),
            original="build.engine config — auto / docker / podman / nerdctl / skip(default)",
            example="로컬 테스트: auto / CI 파이프라인: skip",
            step="config",
        ),
    }

    def lookup(self, term_id: str) -> HelpEntry | None:
        """term_id로 HelpEntry 조회. 없으면 None."""
        return self._ENTRIES.get(term_id)

    def for_step(self, step: Literal[1, 2, "config"]) -> list[HelpEntry]:
        """STEP 1 입력용 / STEP 2 추론 실패용 / 설정용 분류."""
        return [e for e in self._ENTRIES.values() if e.step == step]


# ─── PipelineDependencies ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineDependencies:
    """SkillPipeline이 주입받는 컴포넌트 묶음.

    테스트에서 MagicMock으로 쉽게 교체 가능하도록 DI.
    stack_registry는 DockerfileGenerator 호출 시 현재 스택 모듈을 룩업하는 데 사용.
    """

    config_loader: ConfigLoader
    project_analyzer: ProjectAnalyzer
    dockerfile_generator: DockerfileGenerator
    manifest_generator: ManifestGenerator
    k8s_validator: K8sValidator
    kubectl_dry_runner: KubectlDryRunner
    build_runner: BuildRunner
    output_packager: OutputPackager
    stack_registry: dict[str, StackModule]


# ─── Module-level helpers ─────────────────────────────────────────────────────


def _safe_section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    """config.raw의 지정 섹션이 dict가 아니면 빈 dict 반환.

    악성/오타 YAML에서 `output: foo` 같은 scalar 값이 들어와도
    `.get().get()` chain이 AttributeError로 crash하지 않도록 방어.
    """
    val = raw.get(key)
    return val if isinstance(val, dict) else {}


def _coerce_literal_or_default(
    value: str,
    allowed: tuple[str, ...],
    default: str,
) -> str:
    """화이트리스트 매칭 — 미매치 시 default.

    개행/제어문자는 이미 caller가 검증했다고 가정.
    """
    return value if value in allowed else default


def _sanitize_dns1123_label(name: str) -> str:
    """임의 문자열 → DNS-1123 label 안전 변환.

    변환 규칙:
      1. 소문자 변환
      2. 언더스코어(_) → 하이픈(-)
      3. 영숫자/하이픈 외 문자 제거
      4. 앞뒤 하이픈 제거
      5. 63자 이하로 절단 (절단 후 하이픈 제거)
      6. 빈 문자열이거나 시작/끝이 알파뉴메릭이 아니면 'devflow-app' fallback

    project_dir.name 등을 DNS-1123 label로 정규화할 때 사용.
    """
    lowered = name.lower().replace("_", "-")
    filtered = re.sub(r"[^a-z0-9-]", "", lowered)
    stripped = filtered.strip("-")
    cut = stripped[:63].rstrip("-")
    if not cut or not cut[0].isalnum() or not cut[-1].isalnum():
        return "devflow-app"
    return cut


# ─── _fix stubs (v0.1.0 — auto-fix는 v0.2+) ──────────────────────────────────


def _fix_k8s_failures(
    result_or_err: object,
) -> FixOutcome:
    """v0.1.0 K8s 검증 실패 fix 스텁 — 항상 FixOutcome(applied=False) 반환.

    auto-fix는 v0.2+ 예정. 즉시 bail-out으로 이어짐.
    """
    return FixOutcome(
        applied=False,
        summary_ko="K8s 검증 실패 — 수동 수정 필요 (v0.1.0은 auto-fix 미지원)",
    )


def _fix_dry_run_failures(
    result_or_err: object,
) -> FixOutcome:
    """v0.1.0 dry-run 실패 fix 스텁 — 항상 FixOutcome(applied=False) 반환.

    auto-fix는 v0.2+ 예정. 즉시 bail-out으로 이어짐.
    """
    return FixOutcome(
        applied=False,
        summary_ko="kubectl dry-run 실패 — 수동 수정 필요 (v0.1.0은 auto-fix 미지원)",
    )


# v0.2.0 — 앱 이미지 태그 기본값. config.build.image_tag 미지정 시 사용.
_DEFAULT_APP_IMAGE_TAG = "app:0.2.0"


def _resolve_app_image_tag(config: ResolvedConfig) -> str:
    """앱 배포 이미지 태그 결정 (v0.2.0).

    우선순위:
      1) config.build.image_tag (사용자 명시)
      2) _DEFAULT_APP_IMAGE_TAG (`app:0.2.0`)

    base runner image(`eclipse-temurin:*-jre-alpine` 등)를 반환하지 않음 —
    v0.1.0의 CrashLoopBackOff 회귀 방지.

    유효하지 않은 이미지 참조 시 InvalidImageError는 상위 검증에서 처리 (build step).
    여기서는 순수 조회만 수행.
    """
    build_section = _safe_section(config.raw, "build")
    tag = build_section.get("image_tag", _DEFAULT_APP_IMAGE_TAG)
    return str(tag) if tag else _DEFAULT_APP_IMAGE_TAG


# ─── SkillPipeline ─────────────────────────────────────────────────────────────


class SkillPipeline:
    """5-STEP 파이프라인 오케스트레이터.

    STEP 1: 입력 수집 (HelpCatalog 도움말)
    STEP 2: 프로젝트 분석 (ProjectAnalyzer)
    STEP 3: 아티팩트 생성 (DockerfileGenerator + ManifestGenerator)
    STEP 4: 검증 게이트 (K8sValidator + KubectlDryRunner + opt-in BuildRunner)
    STEP 5: 패키징 (OutputPackager + AtomicWriter commit)
    """

    def __init__(
        self,
        deps: PipelineDependencies,
        *,
        prompt_callback: PromptCallback | None = None,
    ) -> None:
        self._deps = deps
        self._prompt_callback = prompt_callback
        self._help_catalog = HelpCatalog()
        self._msg_policy = MessagePolicy()

    # ─── Public entry point ───────────────────────────────────────────────────

    def run(
        self,
        project_dir: Path,
        output_dir: Path,
    ) -> PackagingResult:
        """5-STEP 실행.

        흐름:
          1. config_loader.load(project_dir) → ResolvedConfig
          2. STEP 1: collect inputs (prompt_callback + HelpCatalog)
          3. STEP 2: project_analyzer.analyze() → AnalysisResult
          4. STEP 3: AtomicWriter 컨텍스트 내에서 dockerfile/manifest 생성
          5. STEP 4: retry_loop (validation + dry_run + optional build)
          6. STEP 5: output_packager.write() + atomic commit

        예외:
          - UserAbort (사용자 Ctrl+C / 거부): staging_dir cleanup 후 전파
          - BailOutError (3회 재시도 실패): troubleshoot.md 작성 후 exit code 1
          - ConfigError: 기본값 + warnings로 graceful degrade (ConfigLoader 영역)
        """
        # STEP 1
        config = self._deps.config_loader.load(project_dir)
        inputs = self._collect_inputs_step1(config, project_dir)

        # STEP 2
        analysis = self._analyze_project_step2(project_dir, config, inputs)

        # on_exists 설정 조회 (없으면 'prompt' 기본값)
        on_exists_raw = _safe_section(config.raw, "output").get("on_exists", "prompt")
        on_exists: Literal["prompt", "overwrite", "suffix"] = cast(
            Literal["prompt", "overwrite", "suffix"],
            _coerce_literal_or_default(
                str(on_exists_raw),
                ("prompt", "overwrite", "suffix"),
                "prompt",
            ),
        )

        # effective_output_dir 결정:
        #   prompt 모드 (prompt_callback 있음): 사용자가 직접 입력한 output_dir 우선.
        #     inputs.output_dir가 non-empty이면 그 값 사용, 아니면 method arg fallback.
        #   자동 모드 (prompt_callback=None): method arg (CLI --output-dir) 사용.
        #     config의 output.dir는 이미 inputs.output_dir에 반영되나, CLI 인자가 최종 경로임.
        if self._prompt_callback is not None and inputs.output_dir and str(inputs.output_dir):
            effective_output_dir = inputs.output_dir
        else:
            effective_output_dir = output_dir

        # ClusterConfig 해석
        cluster_config = self._deps.config_loader.resolve_cluster_config(
            config, prompt_callback=self._prompt_callback
        )

        # STEP 3 + 4 + 5 (AtomicWriter 컨텍스트)
        with AtomicWriter(
            output_dir=effective_output_dir,
            on_exists=on_exists,
            prompt_callback=self._prompt_callback,
        ) as writer:
            try:
                # STEP 3
                artifacts = self._generate_artifacts_step3(
                    writer.staging_dir, inputs, analysis, config,
                    cluster_config=cluster_config, project_dir=project_dir
                )

                # STEP 4
                validation_outcome = self._validate_gate_step4(
                    writer.staging_dir, artifacts, analysis, config
                )

                # STEP 5
                result = self._package_step5(
                    writer.staging_dir, inputs, analysis, validation_outcome, config,
                    manifest_filenames=[p.name for p in artifacts.manifest_paths],
                )

                final_path = writer.commit()
                # F-42: validation exit code를 PackagingResult에 전파
                validation_exit_code = validation_outcome.k8s_report.exit_code
                return dataclasses.replace(
                    result,
                    final_path=final_path,
                    validation_exit_code=validation_exit_code,
                )
            except BailOutError as exc:
                # F-52: BailOut 시 staging_dir을 {output_dir}-failed-timestamp/ 로 보존
                failed_path = writer.bailout_commit()
                raise BailOutError(
                    f"{exc}. 실패 결과 보존: {failed_path} (troubleshoot.md 확인)"
                ) from exc

    # ─── STEP 1: 입력 수집 ───────────────────────────────────────────────────

    def _collect_inputs_step1(
        self,
        config: ResolvedConfig,
        project_dir: Path,
    ) -> UserInputs:
        """STEP 1: 사용자 입력 수집.

        prompt_callback=None (자동 모드): config.raw 또는 defaults에서 채움.
        prompt_callback 있음: 각 필드마다 PromptRequest 호출 + "?" 도움말 분기.

        6개 term (F-02 매핑): app_name, port, exposure, namespace, output_dir, resource_hint
        """
        raw = config.raw
        output_raw = _safe_section(raw, "output")
        app_raw = _safe_section(raw, "app")

        if self._prompt_callback is None:
            # 자동 모드 — config/defaults에서 채움

            # app_name: None 방어 — app.name이 None이면 project_dir.name을 DNS-1123 정규화
            app_name_raw = app_raw.get("name")
            if not app_name_raw:
                app_name = _sanitize_dns1123_label(project_dir.name)
            else:
                app_name = str(app_name_raw)

            port = int(app_raw.get("port", 8080))
            exposure_val = _coerce_literal_or_default(
                str(app_raw.get("exposure", "ClusterIP")),
                ("ClusterIP", "NodePort", "LoadBalancer"),
                "ClusterIP",
            )
            exposure: Literal["ClusterIP", "NodePort", "LoadBalancer"] = cast(
                Literal["ClusterIP", "NodePort", "LoadBalancer"], exposure_val
            )

            # namespace: resolve_namespace() 4단계 조회 — str(None)='None' 버그 방어
            ns_result = self._deps.config_loader.resolve_namespace(
                config, user_input=None, project_dir=project_dir
            )
            namespace = ns_result.value

            output_dir_str = str(output_raw.get("dir", "k8s-output"))
            resource_hint_val = _coerce_literal_or_default(
                str(app_raw.get("resource_hint", "medium")),
                ("small", "medium", "large"),
                "medium",
            )
            resource_hint: Literal["small", "medium", "large"] = cast(
                Literal["small", "medium", "large"], resource_hint_val
            )
        else:
            # prompt 모드 — 사용자에게 물어봄
            app_name = self._prompt_field(
                "app_name",
                self._msg_policy.format_question("앱 이름은 뭘로 할까요?", "app name"),
                default=str(app_raw.get("name", project_dir.name)),
            )
            port_str = self._prompt_field(
                "port",
                self._msg_policy.format_question("앱이 어떤 포트를 쓰나요?", "port"),
                default=str(app_raw.get("port", 8080)),
            )
            try:
                port = int(port_str)
            except ValueError:
                port = 8080

            exposure_answer = _coerce_literal_or_default(
                self._prompt_field(
                    "exposure",
                    self._msg_policy.format_question("어디서 접속할 건가요?", "service type"),
                    default=str(app_raw.get("exposure", "ClusterIP")),
                ),
                ("ClusterIP", "NodePort", "LoadBalancer"),
                "ClusterIP",
            )
            exposure = cast(Literal["ClusterIP", "NodePort", "LoadBalancer"], exposure_answer)

            # namespace prompt: 기본값도 resolve_namespace() 4단계 조회 경유
            _ns_default = self._deps.config_loader.resolve_namespace(
                config, user_input=None, project_dir=project_dir
            ).value
            ns_answer = self._prompt_field(
                "namespace",
                self._msg_policy.format_question("네임스페이스는 뭘로 할까요?", "namespace"),
                default=_ns_default,
            )
            # user_input을 resolve_namespace에 전달해 4단계 로직 완성
            namespace = self._deps.config_loader.resolve_namespace(
                config, user_input=ns_answer or None, project_dir=project_dir
            ).value
            output_dir_str = self._prompt_field(
                "output_dir",
                self._msg_policy.format_question("생성 파일을 어디에 둘까요?", "output dir"),
                default=str(output_raw.get("dir", "k8s-output")),
            )
            resource_hint_answer = _coerce_literal_or_default(
                self._prompt_field(
                    "resource_hint",
                    self._msg_policy.format_question(
                        "메모리/CPU는 어느 정도 필요해요?", "resource hint"
                    ),
                    default=str(app_raw.get("resource_hint", "medium")),
                ),
                ("small", "medium", "large"),
                "medium",
            )
            resource_hint = cast(Literal["small", "medium", "large"], resource_hint_answer)

        replicas = int(app_raw.get("replicas", 2))
        if replicas < 1:
            raise ValueError(f"app.replicas는 1 이상이어야 합니다: {replicas}")

        return UserInputs(
            app_name=app_name,
            port=port,
            exposure=exposure,
            namespace=namespace,
            output_dir=Path(output_dir_str),
            resource_hint=resource_hint,
            replicas=replicas,
        )

    def _prompt_field(
        self,
        help_term_id: str,
        ko_text: str,
        *,
        default: str,
    ) -> str:
        """단일 필드 prompt. prompt_callback이 None이면 default 반환.

        help_term_id 포함 — 사용자가 "?"로 요청 시 HelpCatalog.lookup(term_id).ko_detail 반환.
        """
        if self._prompt_callback is None:
            return default

        req = PromptRequest(
            kind="question",
            ko_text=ko_text,
            options=None,
            help_term_id=help_term_id,
        )
        answer = self._prompt_callback(req)

        # 타입 검증 — callback 구현 버그로 None/int 반환 시 안전 기본값
        if not isinstance(answer, str):
            return default
        # 길이 상한 (DoS 방어)
        if len(answer) > 256:
            return default
        # 제어문자 검증 — 개행/NUL 포함 시 거부 후 default
        try:
            reject_unsafe_chars(answer, f"prompt response for {help_term_id}")
        except ValueError:
            return default

        # "?" 도움말 분기 (F-02b)
        if answer == "?":
            entry = self._help_catalog.lookup(help_term_id)
            if entry is not None:
                help_req = PromptRequest(
                    kind="question",
                    ko_text=entry.ko_detail,
                    options=None,
                    help_term_id=help_term_id,
                )
                answer = self._prompt_callback(help_req)
                # 도움말 응답도 동일하게 검증
                if not isinstance(answer, str):
                    return default
                if len(answer) > 256:
                    return default
                try:
                    reject_unsafe_chars(answer, f"help response for {help_term_id}")
                except ValueError:
                    return default
            else:
                # 도움말 없으면 다시 물어봄
                answer = self._prompt_callback(req)
                if not isinstance(answer, str):
                    return default
                if len(answer) > 256:
                    return default
                try:
                    reject_unsafe_chars(answer, f"retry response for {help_term_id}")
                except ValueError:
                    return default

        return answer if answer else default

    # ─── STEP 2: 프로젝트 분석 ───────────────────────────────────────────────

    def _analyze_project_step2(
        self,
        project_dir: Path,
        config: ResolvedConfig,
        inputs: UserInputs,
    ) -> AnalysisResult:
        """STEP 2: ProjectAnalyzer.analyze() 호출. resource_hint + inputs(F-27) 전달."""
        return self._deps.project_analyzer.analyze(
            project_dir, config, resource_hint=inputs.resource_hint, inputs=inputs
        )

    # ─── STEP 3: 아티팩트 생성 ───────────────────────────────────────────────

    def _generate_artifacts_step3(
        self,
        staging_dir: Path,
        inputs: UserInputs,
        analysis: AnalysisResult,
        config: ResolvedConfig,
        *,
        cluster_config: ClusterConfig | None = None,
        project_dir: Path | None = None,
    ) -> GeneratedArtifacts:
        """STEP 3: Dockerfile + manifest 생성 → staging_dir에 저장.

        v0.2.0 P1-a/P1-b: project_dir로 gradle/ 존재 감지 + `Dockerfile.dockerignore`
        동반 생성 (context pollution 방어).
        statefulness.is_stateful=True, confidence=high → StatefulSet, 그 외 → Deployment.
        cluster_config.network_policy=True → networkpolicy.yaml 추가.
        """
        # Dockerfile 생성 — stack_registry에서 현재 스택 모듈 룩업
        stack_module = self._deps.stack_registry[analysis.stack]
        dockerfile_content = self._deps.dockerfile_generator.generate(
            analysis.build_plan,
            inputs,
            analysis.defaults,
            stack_module=stack_module,
            detect_result=analysis.detect_result,
            project_dir=project_dir,
        )
        dockerfile_path = staging_dir / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")

        # Dockerfile.dockerignore — `docker build -f k8s-output/Dockerfile` 시 자동 적용
        ignore_content = self._deps.dockerfile_generator.generate_dockerignore()
        (staging_dir / "Dockerfile.dockerignore").write_text(ignore_content, encoding="utf-8")

        manifest_paths: list[Path] = []

        # Workload YAML — statefulness HIGH → StatefulSet, 그 외 → Deployment
        app_image = _resolve_app_image_tag(config)
        is_stateful_high = (
            analysis.statefulness.is_stateful
            and analysis.statefulness.confidence == "high"
        )
        if is_stateful_high and cluster_config is not None:
            workload_content = self._deps.manifest_generator.generate_statefulset(
                inputs, analysis, cluster_config, image=app_image
            )
            workload_path = staging_dir / "statefulset.yaml"
        else:
            workload_content = self._deps.manifest_generator.generate_deployment(
                inputs,
                analysis,
                analysis.defaults,
                analysis.probe_config,
                image=app_image,
            )
            workload_path = staging_dir / "deployment.yaml"
        workload_path.write_text(workload_content, encoding="utf-8")
        manifest_paths.append(workload_path)

        # Service YAML
        service_content = self._deps.manifest_generator.generate_service(inputs)
        service_path = staging_dir / "service.yaml"
        service_path.write_text(service_content, encoding="utf-8")
        manifest_paths.append(service_path)

        # ServiceAccount YAML
        sa_content = self._deps.manifest_generator.generate_serviceaccount(inputs)
        sa_path = staging_dir / "serviceaccount.yaml"
        sa_path.write_text(sa_content, encoding="utf-8")
        manifest_paths.append(sa_path)

        # NetworkPolicy YAML (cluster_config.network_policy=True 시 생성)
        if cluster_config is not None and cluster_config.network_policy:
            network_raw = _safe_section(config.raw, "network")
            allow_ingress = network_raw.get("allow_ingress_from") or None
            allow_egress = network_raw.get("allow_egress_to") or None
            np_content = self._deps.manifest_generator.generate_networkpolicy(
                inputs,
                cluster_config,
                allow_ingress_from=allow_ingress,
                allow_egress_to=allow_egress,
            )
            if np_content is not None:
                np_path = staging_dir / "networkpolicy.yaml"
                np_path.write_text(np_content, encoding="utf-8")
                manifest_paths.append(np_path)

        return GeneratedArtifacts(
            dockerfile_path=dockerfile_path,
            manifest_paths=manifest_paths,
        )

    # ─── STEP 4: 검증 게이트 ─────────────────────────────────────────────────

    def _raise_bailout(
        self,
        staging_dir: Path,
        *,
        step_name_ko: str,
        component_ko: str,
        ko_summary: str,
        en_detail: str,
        attempts_log: list[RetryAttempt[Any]],
        message: str,
    ) -> NoReturn:
        """BailOutContext 구성 → troubleshoot.md 작성 → BailOutError 전파."""
        ctx = BailOutContext(
            step_number=4,
            step_name_ko=step_name_ko,
            component_ko=component_ko,
            ko_summary=ko_summary,
            en_detail=en_detail,
            attempts_log=attempts_log,
        )
        self._deps.output_packager.write_troubleshoot(staging_dir, ctx)
        raise BailOutError(message)

    def _validate_gate_step4(
        self,
        staging_dir: Path,
        artifacts: GeneratedArtifacts,
        analysis: AnalysisResult,
        config: ResolvedConfig,
    ) -> ValidationOutcome:
        """STEP 4: retry_loop 기반 검증.

        - K8sValidator → run_validation_loop
        - KubectlDryRunner → run_dry_run_loop
        - opt-in: build.engine != 'skip' → run_build_loop
        - bail-out 시: BailOutContext 구성 → write_troubleshoot → BailOutError raise
        """
        # K8s 정적 검증
        k8s_result = run_validation_loop(
            self._deps.k8s_validator,
            artifacts.manifest_paths,
            _fix_k8s_failures,
        )

        if k8s_result.bailout:
            self._raise_bailout(
                staging_dir,
                step_name_ko="STEP 4 정적 검증",
                component_ko="K8s 검증기",
                ko_summary="K8s 매니페스트 검증 3회 실패 — 수동 수정 필요",
                en_detail="K8s manifest validation failed after 3 attempts",
                attempts_log=k8s_result.attempts,
                message="K8s manifest validation bailed out",
            )

        # kubectl dry-run
        dry_run_result = run_dry_run_loop(
            self._deps.kubectl_dry_runner,
            staging_dir,
            _fix_dry_run_failures,
        )

        if dry_run_result.bailout:
            self._raise_bailout(
                staging_dir,
                step_name_ko="STEP 4 dry-run 검증",
                component_ko="kubectl 어댑터",
                ko_summary="kubectl dry-run 3회 실패 — 수동 수정 필요",
                en_detail="kubectl dry-run failed after 3 attempts",
                attempts_log=dry_run_result.attempts,
                message="kubectl dry-run bailed out",
            )

        # opt-in 빌드
        build_section = _safe_section(config.raw, "build")
        build_engine = build_section.get("engine", "skip")
        build_result = None
        if build_engine != "skip":
            # 기본 이미지 태그 — _resolve_app_image_tag로 deployment와 단일 출처 공유
            image_tag = _resolve_app_image_tag(config)
            try:
                validate_image_reference(image_tag)
            except InvalidImageError:
                # 유효하지 않은 image_tag → build skip + warning
                config.warnings.append(
                    f"build.image_tag 검증 실패: {image_tag!r} — 빌드 건너뜀"
                )
                build_engine = "skip"

        if build_engine != "skip":
            image_tag = _resolve_app_image_tag(config)
            build_result = run_build_loop(
                self._deps.build_runner,
                staging_dir,
                image_tag,
                lambda r: FixOutcome(
                    applied=False,
                    summary_ko="빌드 실패 — 수동 수정 필요 (v0.1.0은 auto-fix 미지원)",
                ),
            )

            if build_result.bailout:
                self._raise_bailout(
                    staging_dir,
                    step_name_ko="STEP 4 컨테이너 빌드",
                    component_ko="빌드 러너",
                    ko_summary="컨테이너 빌드 3회 실패 — 수동 수정 필요",
                    en_detail="Container build failed after 3 attempts",
                    attempts_log=build_result.attempts,
                    message="Container build bailed out",
                )

        return collect_validation_outcome(k8s_result, dry_run_result, build_result)

    # ─── STEP 5: 패키징 ──────────────────────────────────────────────────────

    def _package_step5(
        self,
        staging_dir: Path,
        inputs: UserInputs,
        analysis: AnalysisResult,
        validation_outcome: ValidationOutcome,
        config: ResolvedConfig,
        *,
        manifest_filenames: list[str] | None = None,
    ) -> PackagingResult:
        """STEP 5: OutputPackager.write() 호출.

        v0.2.0: summary.json/rationale.md의 image_reference도 앱 이미지 태그로 일치시킴
        (이전 버그: runner_image → CrashLoop 재현).
        """
        image_reference = _resolve_app_image_tag(config)
        return self._deps.output_packager.write(
            staging_dir,
            inputs,
            analysis,
            validation_outcome.k8s_report,
            config.source_map,
            image_reference=image_reference,
            validation_outcome=validation_outcome,
            manifest_filenames=manifest_filenames,
        )


# ─── CLI 진입점 ────────────────────────────────────────────────────────────────


def _build_default_dependencies(project_dir: Path) -> PipelineDependencies:
    """실제 컴포넌트 인스턴스를 조립.

    CLI에서 호출. 테스트에서는 MagicMock으로 교체.
    """
    from scripts._shared.defaults import load_builtin_defaults  # noqa: F401 — 사이드이펙트 없음
    from scripts.config_loader import ConfigLoader
    from scripts.dockerfile_generator import DockerfileGenerator
    from scripts.kubectl_dry_runner import KubectlDryRunner
    from scripts.manifest_generator import ManifestGenerator
    from scripts.output_packager import OutputPackager
    from scripts.pipeline.build_runner import BuildRunner
    from scripts.project_analyzer import ProjectAnalyzer
    from scripts.stacks.go import GoStackModule
    from scripts.stacks.jvm import JvmStackModule
    from scripts.template_renderer import TemplateRenderer
    from scripts.validate_k8s import K8sValidator

    config_loader = ConfigLoader()

    # 플러그인 루트 기준 템플릿 루트 결정
    plugin_root = Path(
        os.environ.get("CLAUDE_PLUGIN_ROOT", str(Path(__file__).parent.parent.parent))
    )
    template_root = plugin_root / "templates"
    template_renderer = TemplateRenderer(template_root)

    # StackRegistry: 자동 감지 시 등록 순서대로 시도 — JVM 우선 → Go (F-16)
    stack_registry: dict[str, StackModule] = {
        "jvm": JvmStackModule(),
        "go": GoStackModule(),
    }

    # config 미리 로드하여 build engine/timeout 추출
    config = config_loader.load(project_dir)
    build_section = _safe_section(config.raw, "build")
    build_engine = build_section.get("engine", "skip")
    build_timeout = int(build_section.get("build_timeout_seconds", 600))

    project_analyzer = ProjectAnalyzer(
        config_loader=config_loader,
        stack_registry=stack_registry,
        prompt_callback=None,  # CLI는 자동 모드
    )
    dockerfile_generator = DockerfileGenerator(template_renderer)
    manifest_generator = ManifestGenerator(template_renderer)
    k8s_validator = K8sValidator()
    kubectl_dry_runner = KubectlDryRunner()
    # build_engine 화이트리스트 적용 — config validation이 없는 CLI 경로의 안전망
    _allowed_engines = ("skip", "auto", "docker", "podman", "nerdctl")
    safe_engine = build_engine if build_engine in _allowed_engines else "skip"
    build_runner = BuildRunner(
        build_engine=cast(
            Literal["skip", "auto", "docker", "podman", "nerdctl"],
            safe_engine,
        ),
        build_timeout_seconds=build_timeout,
    )
    output_packager = OutputPackager()

    return PipelineDependencies(
        config_loader=config_loader,
        project_analyzer=project_analyzer,
        dockerfile_generator=dockerfile_generator,
        manifest_generator=manifest_generator,
        k8s_validator=k8s_validator,
        kubectl_dry_runner=kubectl_dry_runner,
        build_runner=build_runner,
        output_packager=output_packager,
        stack_registry=stack_registry,
    )


def _compute_cli_exit_code(result: PackagingResult) -> int:
    """PackagingResult → F-42 exit code 변환.

    우선순위: result.validation_exit_code → 0 (기본 성공).
    """
    if result.validation_exit_code is not None:
        return result.validation_exit_code
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리포인트.

    사용:
      python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/orchestrator.py \
        --project-dir . --output-dir k8s-output/

    Exit code (F-42):
      0: 모든 검증 PASS
      1: FAIL 존재 또는 BailOutError
      2: FAIL 없음 + WARN (soft-success)
      130: SIGINT / 사용자 중단
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="devflow-k8s-deploy",
        description="devflow-k8s-deploy v0.2.0 — JVM 프로젝트를 k8s 배포 파일로 변환",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/orchestrator.py \\
    --project-dir . --output-dir k8s-output/
  python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/orchestrator.py \\
    --project-dir /path/to/spring-boot-app --output-dir deploy/

Exit code:
  0: PASS  /  1: FAIL  /  2: WARN (soft-success)
  CI: if [ $? -le 2 ]; then continue; fi
""",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help="분석할 JVM 프로젝트 루트 디렉토리",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="생성된 Dockerfile + manifest 출력 디렉토리",
    )
    args = parser.parse_args(argv)

    try:
        deps = _build_default_dependencies(args.project_dir)
        pipeline = SkillPipeline(deps)
        result = pipeline.run(args.project_dir, args.output_dir)
        return _compute_cli_exit_code(result)
    except BailOutError as exc:
        print(f"\n[BAIL-OUT] {exc}", file=sys.stderr)
        return 1
    except UserAbort as exc:
        print(f"\n[사용자 중단] {exc}", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 — 최상위 CLI 경계
        print(f"\n[오류] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
