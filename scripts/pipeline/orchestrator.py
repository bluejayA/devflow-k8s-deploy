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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from scripts._shared.errors import BailOutError
from scripts._shared.types import (
    AnalysisResult,
    BailOutContext,
    FixOutcome,
    GeneratedArtifacts,
    HelpEntry,
    MessagePolicy,
    PackagingResult,
    PromptCallback,
    PromptRequest,
    ResolvedConfig,
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
    """

    config_loader: ConfigLoader
    project_analyzer: ProjectAnalyzer
    dockerfile_generator: DockerfileGenerator
    manifest_generator: ManifestGenerator
    k8s_validator: K8sValidator
    kubectl_dry_runner: KubectlDryRunner
    build_runner: BuildRunner
    output_packager: OutputPackager


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
        on_exists_raw = config.raw.get("output", {}).get("on_exists", "prompt")
        on_exists: Literal["prompt", "overwrite", "suffix"]
        if on_exists_raw in ("prompt", "overwrite", "suffix"):
            on_exists = on_exists_raw
        else:
            on_exists = "prompt"

        # STEP 3 + 4 + 5 (AtomicWriter 컨텍스트)
        with AtomicWriter(
            output_dir=output_dir,
            on_exists=on_exists,
            prompt_callback=self._prompt_callback,
        ) as writer:
            # STEP 3
            artifacts = self._generate_artifacts_step3(
                writer.staging_dir, inputs, analysis, config
            )

            # STEP 4
            validation_outcome = self._validate_gate_step4(
                writer.staging_dir, artifacts, analysis, config
            )

            # STEP 5
            result = self._package_step5(
                writer.staging_dir, inputs, analysis, validation_outcome, config
            )

            final_path = writer.commit()
            return dataclasses.replace(result, final_path=final_path)

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
        output_raw = raw.get("output", {})
        app_raw = raw.get("app", {})

        if self._prompt_callback is None:
            # 자동 모드 — config/defaults에서 채움
            app_name = str(app_raw.get("name", project_dir.name))
            port = int(app_raw.get("port", 8080))
            exposure_val = str(app_raw.get("exposure", "ClusterIP"))
            if exposure_val not in ("ClusterIP", "NodePort", "LoadBalancer"):
                exposure_val = "ClusterIP"
            exposure: Literal["ClusterIP", "NodePort", "LoadBalancer"] = exposure_val  # type: ignore[assignment]
            namespace = str(raw.get("namespace", project_dir.name))
            output_dir_str = str(output_raw.get("dir", "k8s-output"))
            resource_hint_val = str(app_raw.get("resource_hint", "medium"))
            if resource_hint_val not in ("small", "medium", "large"):
                resource_hint_val = "medium"
            resource_hint: Literal["small", "medium", "large"] = resource_hint_val  # type: ignore[assignment]
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

            exposure_answer = self._prompt_field(
                "exposure",
                self._msg_policy.format_question("어디서 접속할 건가요?", "service type"),
                default=str(app_raw.get("exposure", "ClusterIP")),
            )
            if exposure_answer not in ("ClusterIP", "NodePort", "LoadBalancer"):
                exposure_answer = "ClusterIP"
            exposure = exposure_answer  # type: ignore[assignment]

            namespace = self._prompt_field(
                "namespace",
                self._msg_policy.format_question("네임스페이스는 뭘로 할까요?", "namespace"),
                default=str(raw.get("namespace", project_dir.name)),
            )
            output_dir_str = self._prompt_field(
                "output_dir",
                self._msg_policy.format_question("생성 파일을 어디에 둘까요?", "output dir"),
                default=str(output_raw.get("dir", "k8s-output")),
            )
            resource_hint_answer = self._prompt_field(
                "resource_hint",
                self._msg_policy.format_question(
                    "메모리/CPU는 어느 정도 필요해요?", "resource hint"
                ),
                default=str(app_raw.get("resource_hint", "medium")),
            )
            if resource_hint_answer not in ("small", "medium", "large"):
                resource_hint_answer = "medium"
            resource_hint = resource_hint_answer  # type: ignore[assignment]

        return UserInputs(
            app_name=app_name,
            port=port,
            exposure=exposure,
            namespace=namespace,
            output_dir=Path(output_dir_str),
            resource_hint=resource_hint,
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
            else:
                # 도움말 없으면 다시 물어봄
                answer = self._prompt_callback(req)

        return answer if answer else default

    # ─── STEP 2: 프로젝트 분석 ───────────────────────────────────────────────

    def _analyze_project_step2(
        self,
        project_dir: Path,
        config: ResolvedConfig,
        inputs: UserInputs,
    ) -> AnalysisResult:
        """STEP 2: ProjectAnalyzer.analyze() 호출."""
        return self._deps.project_analyzer.analyze(project_dir, config)

    # ─── STEP 3: 아티팩트 생성 ───────────────────────────────────────────────

    def _generate_artifacts_step3(
        self,
        staging_dir: Path,
        inputs: UserInputs,
        analysis: AnalysisResult,
        config: ResolvedConfig,
    ) -> GeneratedArtifacts:
        """STEP 3: Dockerfile + 3 manifest 생성 → staging_dir에 저장."""
        # Dockerfile 생성
        dockerfile_content = self._deps.dockerfile_generator.generate(
            analysis.build_plan,
            inputs,
            analysis.defaults,
        )
        dockerfile_path = staging_dir / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")

        # Deployment YAML — runner_image를 컨테이너 이미지로 사용
        deployment_content = self._deps.manifest_generator.generate_deployment(
            inputs,
            analysis,
            analysis.defaults,
            analysis.probe_config,
            image=analysis.build_plan.runner_image,
        )
        deployment_path = staging_dir / "deployment.yaml"
        deployment_path.write_text(deployment_content, encoding="utf-8")

        # Service YAML
        service_content = self._deps.manifest_generator.generate_service(inputs)
        service_path = staging_dir / "service.yaml"
        service_path.write_text(service_content, encoding="utf-8")

        # ServiceAccount YAML
        sa_content = self._deps.manifest_generator.generate_serviceaccount(inputs)
        sa_path = staging_dir / "serviceaccount.yaml"
        sa_path.write_text(sa_content, encoding="utf-8")

        return GeneratedArtifacts(
            dockerfile_path=dockerfile_path,
            manifest_paths=[deployment_path, service_path, sa_path],
        )

    # ─── STEP 4: 검증 게이트 ─────────────────────────────────────────────────

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
            ctx = BailOutContext(
                step_number=4,
                step_name_ko="STEP 4 정적 검증",
                component_ko="K8s 검증기",
                ko_summary="K8s 매니페스트 검증 3회 실패 — 수동 수정 필요",
                en_detail="K8s manifest validation failed after 3 attempts",
                attempts_log=k8s_result.attempts,
            )
            self._deps.output_packager.write_troubleshoot(staging_dir, ctx)
            raise BailOutError("K8s manifest validation bailed out")

        # kubectl dry-run
        dry_run_result = run_dry_run_loop(
            self._deps.kubectl_dry_runner,
            staging_dir,
            _fix_dry_run_failures,
        )

        if dry_run_result.bailout:
            ctx = BailOutContext(
                step_number=4,
                step_name_ko="STEP 4 dry-run 검증",
                component_ko="kubectl 어댑터",
                ko_summary="kubectl dry-run 3회 실패 — 수동 수정 필요",
                en_detail="kubectl dry-run failed after 3 attempts",
                attempts_log=dry_run_result.attempts,
            )
            self._deps.output_packager.write_troubleshoot(staging_dir, ctx)
            raise BailOutError("kubectl dry-run bailed out")

        # opt-in 빌드
        build_engine = config.raw.get("build", {}).get("engine", "skip")
        build_result = None
        if build_engine != "skip":
            # 기본 이미지 태그 — config에서 조회
            image_tag = config.raw.get("build", {}).get("image_tag", "app:0.1.0")
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
                ctx = BailOutContext(
                    step_number=4,
                    step_name_ko="STEP 4 컨테이너 빌드",
                    component_ko="빌드 러너",
                    ko_summary="컨테이너 빌드 3회 실패 — 수동 수정 필요",
                    en_detail="Container build failed after 3 attempts",
                    attempts_log=build_result.attempts,
                )
                self._deps.output_packager.write_troubleshoot(staging_dir, ctx)
                raise BailOutError("Container build bailed out")

        return collect_validation_outcome(k8s_result, dry_run_result, build_result)

    # ─── STEP 5: 패키징 ──────────────────────────────────────────────────────

    def _package_step5(
        self,
        staging_dir: Path,
        inputs: UserInputs,
        analysis: AnalysisResult,
        validation_outcome: ValidationOutcome,
        config: ResolvedConfig,
    ) -> PackagingResult:
        """STEP 5: OutputPackager.write() 호출."""
        image_reference = analysis.build_plan.runner_image
        return self._deps.output_packager.write(
            staging_dir,
            inputs,
            analysis,
            validation_outcome.k8s_report,
            config.source_map,
            image_reference=image_reference,
            validation_outcome=validation_outcome,
        )
