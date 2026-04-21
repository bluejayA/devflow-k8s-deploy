# Units

**Timestamp**: 2026-04-17T14:00:00+09:00
**Depth**: Standard
**Source**: `devflow-docs/inception/application-design.md` (12 컴포넌트 + SkillPipeline 3-서브유닛 분해 + `_shared/` 단일 unit 경계)

---

## 분해 전략

1. **`_shared/`는 단일 unit** (application-design §E 확정): `types.py` + `errors.py` + `retry.py` + `defaults.py` 한 묶음
2. **StackModule Interface + JvmStackModule은 1 unit**으로 묶음: v0.1.0 유일 구현체, Protocol 정의 즉시 검증
3. **SkillPipeline은 3 서브유닛으로 분해** (application-design §E 권장): `pipeline/orchestrator.py` / `pipeline/retry_loop.py` / `pipeline/build_runner.py` — 단위 테스트 경계 분리
4. **SKILL.md 본문 + README 갱신**을 별도 unit으로 (Claude 프롬프트 문서 작업, Python code와 성격 다름)
5. **NFR-SEC-05 allowlist 테스트**는 별도 unit (보안 회귀 방지용, kubectl/build 양쪽 commands를 대상으로 CI 감지)
6. 템플릿 파일(`templates/*.tmpl`)은 이를 사용하는 Generator unit에 포함
7. unit 명명: snake_case, 파일/모듈 경로 기준

**총 16개 unit**, 6 phase.

---

## Phase 1: 기반

### Unit: shared
**Responsibility**: 공유 타입/예외/유틸의 단일 정의 소스. `types.py`(ResolvedConfig/AnalysisResult/ValidationReport/DryRunResult/BuildResult/BailOutContext/PromptRequest/HelpEntry/FixOutcome 등 18+ dataclass/Protocol) + `errors.py`(DevflowError 계열: UserAbort/BailOutError/ConfigError/UnsupportedStackError/UnknownStackError/MultiModuleAbort/JvmDetectionError/InvalidImageError/MalformedManifestError/KubectlExecutionError/OutputExistsAbort/TemplateNotFoundError) + `retry.py`(`retry_with_fix` 3회 재시도 유틸 + `FixOutcome`) + `defaults.py`(내장 기본 설정 사전).
**Dependencies**: none
**Interfaces**: `scripts/_shared/{types,errors,retry,defaults}.py` — 모든 후속 unit이 import
**Implementation order**: 1

---

## Phase 2: 독립 컴포넌트 (shared만 의존, 병렬 가능)

### Unit: stack_module
**Responsibility**: StackModule Protocol(5 메서드 계약 `detect/build_plan/probe_plan/defaults/artifact_locator`) 정의 + JvmStackModule 구현(Kotlin/Java Spring Boot 2.x/3.x 감지, Gradle KTS/Groovy/Maven 판별, Boot 버전 + 포트 + actuator 추론, JDK/JRE 2단계 build_plan, writable_paths `/tmp`+`/var/log` 노출).
**Dependencies**: shared
**Interfaces**: `scripts/stacks/base.py` (Protocol) + `scripts/stacks/jvm.py` (JvmStackModule class) — ProjectAnalyzer / DockerfileGenerator / ManifestGenerator가 사용
**Implementation order**: 2

### Unit: template_renderer
**Responsibility**: Jinja2 기반 결정론적 템플릿 렌더링 중심지. 고정 키 순서, 빈 라인 정규화, autoescape=False, finalize(None→''), YAML sort_keys=False + default_flow_style=False.
**Dependencies**: shared
**Interfaces**: `scripts/template_renderer.py` (`TemplateRenderer.render_dockerfile/render_manifest`) + `templates/` 디렉토리 뼈대 — Dockerfile/Manifest Generator가 사용
**Implementation order**: 2

### Unit: config_loader
**Responsibility**: 3계층 설정(프로젝트/조직/내장) YAML 병합 + `stack: auto|jvm|...` 강제/auto 분기(F-62/F-92) + namespace 4단계 조회(F-70/F-71, 'default' 자동 배정 금지) + source_map(rationale용) + YAML 파싱 실패 시 graceful degrade.
**Dependencies**: shared
**Interfaces**: `scripts/config_loader.py` (`ConfigLoader.load/resolve_namespace/stack_decision`) — SkillPipeline / ProjectAnalyzer / OutputPackager가 사용
**Implementation order**: 2

### Unit: atomic_writer
**Responsibility**: 임시 디렉토리(`.tmp-{uuid}/`) 쓰기 → atomic rename(F-103). SIGINT/SIGTERM 핸들러로 임시 정리. 시작 시 7일 이상 고아 `.tmp-*` 자동 회수. `output.on_exists`(prompt/overwrite/suffix) 분기. prompt_callback DI(F 패턴).
**Dependencies**: shared
**Interfaces**: `scripts/atomic_writer.py` (`AtomicWriter` context manager + `commit/cleanup`) — SkillPipeline이 `with`로 사용
**Implementation order**: 2

### Unit: k8s_validator
**Responsibility**: stack-agnostic 정적 검증기(`validate_k8s.py`). 규칙 셋 SEC-001~009 / RES-001 / IMG-001 / SA-001~002 / SVC-001~002 / PRB-001~002 + WARN. 3단계 exit code(F-42: 0/1/2) + `--json` 모드(F-47) + `--skipped` 전달 + 한국어+영문 메시지(NFR-17) + `validation.skipped[]` 메타 출력(F-83).
**Dependencies**: shared
**Interfaces**: `scripts/validate_k8s.py` (CLI + `K8sValidator.validate/to_json` Python API) — SkillPipeline(retry_loop)이 호출
**Implementation order**: 2

### Unit: kubectl_dry_runner
**Responsibility**: `kubectl apply --dry-run=client` 실행 어댑터. 미설치 시 degraded success(skipped=True, skip_reason_ko 한국어 사유 기록). 경계 allowlist 준수 — `--dry-run=client` 외 인자 금지(NFR-SEC-05).
**Dependencies**: shared
**Interfaces**: `scripts/kubectl_dry_runner.py` (`KubectlDryRunner.is_available/dry_run`) — SkillPipeline(retry_loop)이 호출
**Implementation order**: 2

---

## Phase 3: 통합 컴포넌트 (Phase 2 의존)

### Unit: project_analyzer
**Responsibility**: STEP 2 분석 오케스트레이션. ConfigLoader.stack_decision() 결과로 StackModule 라우팅. multi-module 감지 + 비개발자 한국어 힌트(F-39). 상태성 감지 + 신뢰도(high/medium/low) 점수(F-38). 추론 실패 시 prompt_callback 호출(NFR-17).
**Dependencies**: shared, stack_module, config_loader
**Interfaces**: `scripts/project_analyzer.py` (`ProjectAnalyzer.analyze` + DI `__init__(config_loader, stack_registry, prompt_callback)`) — SkillPipeline이 사용
**Implementation order**: 3

### Unit: dockerfile_generator
**Responsibility**: multi-stage Dockerfile 생성(JDK builder → JRE runner). 비root 사용자(groupadd/useradd + USER). `latest` 금지 검증(InvalidImageError). Gradle/Maven 캐시 레이어 최적화(F-25). 보안 근거 주석 주입(F-37). JVM dockerfile 템플릿(`templates/dockerfile/jvm.tmpl`) 포함.
**Dependencies**: shared, template_renderer, stack_module (BuildPlan 타입)
**Interfaces**: `scripts/dockerfile_generator.py` (`DockerfileGenerator.generate`) + `templates/dockerfile/jvm.tmpl` — SkillPipeline이 사용
**Implementation order**: 3

### Unit: manifest_generator
**Responsibility**: Deployment/Service/ServiceAccount YAML 생성. Pod/Container securityContext(runAsNonRoot + readOnlyRootFilesystem + allowPrivilegeEscalation + seccompProfile + capabilities.drop). emptyDir 기본 마운트(`/tmp` + `/var/log`, F-32). probes(F-34). `automountServiceAccountToken: false`. 보안 근거 주석(F-37). Manifest 템플릿 3종 포함.
**Dependencies**: shared, template_renderer, stack_module (ProbeConfig 타입)
**Interfaces**: `scripts/manifest_generator.py` (`ManifestGenerator.generate_deployment/generate_service/generate_serviceaccount`) + `templates/manifest/{deployment,service,serviceaccount}.tmpl` — SkillPipeline이 사용
**Implementation order**: 3

### Unit: output_packager
**Responsibility**: STEP 5 최종 패키징. `rationale.md`(결정 소스 매핑 + 스킵 검증 섹션 신규) + `summary.json`(v1 스키마, UTC ISO8601, `validation.skipped[]` 포함, AIDLC 비종속 계약) + `troubleshoot.md`(bail-out 시, 상단 한국어 1-2줄 요약 의무).
**Dependencies**: shared (타입)
**Interfaces**: `scripts/output_packager.py` (`OutputPackager.write/write_troubleshoot/write_summary_json/write_rationale_md`) — SkillPipeline이 호출
**Implementation order**: 3

### Unit: pipeline_build_runner
**Responsibility**: opt-in 컨테이너 빌드 인라인(F-53~F-58). build.engine `auto|docker|podman|nerdctl|skip` 분기 + 엔진 자동 감지 + build CLI 호출 + 타임아웃(F-102) + 미감지 시 degraded(skipped=['container_build'], 한국어 사유). 경계 allowlist 준수.
**Dependencies**: shared
**Interfaces**: `scripts/pipeline/build_runner.py` (`BuildRunner.detect_engine/build`) — pipeline_orchestrator가 호출
**Implementation order**: 3

### Unit: pipeline_retry_loop
**Responsibility**: STEP 4 재시도 오케스트레이션. K8sValidator / KubectlDryRunner / (opt-in) 빌드에 대한 `retry_with_fix` 호출 래퍼 + `_fix_k8s_failures` / `_fix_dry_run_failures` 헬퍼. 3회 자동 수정 루프 + bail-out(F-50/F-51). `ValidationOutcome.skipped` pass-through(F-56).
**Dependencies**: shared (retry.py), k8s_validator, kubectl_dry_runner
**Interfaces**: `scripts/pipeline/retry_loop.py` (`run_validation_loop`, `run_dry_run_loop`, `run_build_loop` — lambda operation + FixOutcome 수용) — pipeline_orchestrator가 호출
**Implementation order**: 3

---

## Phase 4: 오케스트레이터

### Unit: pipeline_orchestrator
**Responsibility**: 5-STEP 진행 의사결정 + STEP 1 입력 수집(한국어 의도 질문 F-02a + "? 도움말" F-02b) + HelpCatalog(10개 용어, step: 1|2|config 라벨) + MessagePolicy(한국어+원어 병기 포맷터, NFR-17) + AtomicWriter 컨텍스트로 STEP 3~5 감싸기. retry_loop / build_runner 호출. 사용자 대면 메시지 중앙화.
**Dependencies**: shared, config_loader, project_analyzer, atomic_writer, dockerfile_generator, manifest_generator, output_packager, pipeline_retry_loop, pipeline_build_runner
**Interfaces**: `scripts/pipeline/orchestrator.py` (`run_pipeline(project_dir)` + `HelpCatalog.lookup/for_step` + `MessagePolicy.format`) — SKILL.md 프롬프트가 이 함수들을 단계별 호출
**Implementation order**: 4

---

## Phase 5: SKILL 본문 + 문서

### Unit: skill_md_and_readme
**Responsibility**: `skills/devflow-k8s-deploy/SKILL.md` 본문 작성 — Claude가 5-STEP을 따르게 하는 프롬프트(한국어 description + 자연어 트리거 F-07/F-08, 5-STEP 진행, HelpCatalog 호출 시점, pipeline_orchestrator 연동, 메시지 정책, `${CLAUDE_PLUGIN_ROOT}` 경로 규약 NFR-05). README.md 갱신 — v0.1.0 사용법/설정 예시/exit code 가이드.
**Dependencies**: pipeline_orchestrator (동작 확인된 API 기준으로 프롬프트 작성)
**Interfaces**: `skills/devflow-k8s-deploy/SKILL.md` + `README.md` — Claude Code 플러그인 본체
**Implementation order**: 5

---

## Phase 6: 보안 회귀 방지 테스트

### Unit: security_tests
**Responsibility**: NFR-SEC-05 경계 allowlist CI 감지 테스트. `subprocess` 호출 픽스처로 kubectl_dry_runner / pipeline_build_runner가 생성하는 command argv를 검사 — shell=True 차단, argv 리스트 강제, 인젝션 토큰(`;`, `&&`, `|`, `` ` ``, `$(` 등) 차단, 정확한 토큰 위치 매칭, 허용 인자만 통과. 픽스처 자체 검증 테스트 의무화(픽스처가 실제로 금지 케이스를 잡는지).
**Dependencies**: kubectl_dry_runner, pipeline_build_runner (대상 command builder)
**Interfaces**: `tests/integration/test_boundary_allowlist.py` + 픽스처 모듈
**Implementation order**: 6

---

## Implementation Order (의존성 그래프)

```
Phase 1 (기반)
  1. shared

Phase 2 (shared만 의존 — 병렬 가능)
  2. stack_module
  3. template_renderer
  4. config_loader
  5. atomic_writer
  6. k8s_validator
  7. kubectl_dry_runner

Phase 3 (Phase 2 의존 — 병렬 가능)
  8.  project_analyzer        ← shared, stack_module, config_loader
  9.  dockerfile_generator    ← shared, template_renderer, stack_module
  10. manifest_generator      ← shared, template_renderer, stack_module
  11. output_packager         ← shared
  12. pipeline_build_runner   ← shared
  13. pipeline_retry_loop     ← shared, k8s_validator, kubectl_dry_runner

Phase 4 (통합)
  14. pipeline_orchestrator   ← (8~13 전체 + config_loader + atomic_writer)

Phase 5 (SKILL 프롬프트 + 문서)
  15. skill_md_and_readme     ← pipeline_orchestrator

Phase 6 (보안 CI)
  16. security_tests          ← kubectl_dry_runner, pipeline_build_runner
```

**구현 순서 (단일 실행 기준):**
1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16

**병렬 실행 기회 (SDD 모드):**
- Phase 2: 2~7 병렬 가능 (6개 동시)
- Phase 3: 8~13 병렬 가능 (6개 동시, Phase 2 완료 후)
- Phase 4/5/6: 순차

---

## 테스트 경계 요약 (application-design §G 근거)

| Unit | 단위 테스트 핵심 | 통합 테스트 |
|------|---------------|----------|
| shared | retry.FixOutcome / success_predicate 필수 / 3회 종료 조건 | — |
| stack_module | Boot 2/3 + actuator + multi-module 감지 (시나리오 5+) | 실제 build.gradle.kts / pom.xml 샘플 |
| template_renderer | 결정론(cksum 동일), 빈 라인 정규화, None→'' | (Generator 통해 간접) |
| config_loader | YAML 우선순위 병합, namespace 4단계, 'default' 차단 | ~/.claude + project dir 양쪽 fixture |
| atomic_writer | rename + cleanup + signal handler + 7일 GC | 실제 파일시스템 + SIGTERM |
| k8s_validator | 규칙별 PASS/WARN/FAIL 케이스, exit code 0/1/2, `--skipped` 전달 | 실제 manifest 파일들 e2e |
| kubectl_dry_runner | `_build_command` allowlist, degraded(skipped=True) 분기 | monkeypatch kubectl |
| project_analyzer | gaps 식별, multi-module 선택, StatefulnessSignal 신뢰도 | Gradle/Maven 샘플 |
| dockerfile_generator | latest 차단, 보안 주석 포함, --chown, USER appuser | TemplateRenderer 실제 호출 |
| manifest_generator | securityContext 모든 필드, emptyDir 자동 마운트, automountSA false | TemplateRenderer + YAML 파싱 검증 |
| output_packager | summary.json 스키마(jsonschema), UTC, skipped, troubleshoot 한국어 요약 | 전체 STEP 5 e2e |
| pipeline_build_runner | 엔진 감지 분기, skipped=['container_build'], 타임아웃 | monkeypatch subprocess |
| pipeline_retry_loop | lambda operation 인자 캡처, 3회 종료, FixOutcome.applied=False 즉시 bail-out | k8s_validator + kubectl_dry_runner 실제 호출 |
| pipeline_orchestrator | 5-STEP 순서, HelpCatalog step 라벨 분기, MessagePolicy 포맷 | 전체 e2e (가짜 Spring Boot fixture) |
| skill_md_and_readme | SKILL.md frontmatter + description 한국어 + trigger phrase | Claude Code 플러그인 로드 |
| security_tests | argv allowlist, 인젝션 토큰 차단, 픽스처 자체 검증 | 실제 command builder들 |

**커버리지 목표 (NFR-TEST-01/02):**
- `validate_k8s.py` (k8s_validator): ≥ 70%
- `scripts/stacks/jvm.py` (stack_module 중 JvmStackModule): ≥ 60%
- 그 외: CI 전체 ≥ 60% 유지 권장

---

## 요구사항 커버리지 확인

- **71 F-***: 모두 unit에 매핑됨 (application-design.md §요구사항 추적 매트릭스 기준)
- **17 NFR**: 모두 매핑됨 (NFR-SEC-05는 security_tests unit + 각 Adapter 내부 검증으로 커버)
- **22 US**: 모두 매핑됨

---

## Change Log

- 2026-04-17T14:00:00+09:00 — units-generation Standard depth 최초 생성. 16 units / 6 phases. application-design §E (SkillPipeline 서브유닛 매핑) + §G (테스트 경계 매트릭스) 근거.
