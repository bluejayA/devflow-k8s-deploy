# Requirements Analysis

**Depth**: Standard
**Timestamp**: 2026-04-24T08:50:00+09:00
**Ticket**: BL-001 ([#8](https://github.com/bluejayA/devflow-k8s-deploy/issues/8))
**Follow-ups**: BL-017 ([#27](https://github.com/bluejayA/devflow-k8s-deploy/issues/27)) — Go 프레임워크 probe 자동 감지 (별도 구현)

## User Intent

JVM 단일 지원이었던 devflow-k8s-deploy에 **Go 백엔드 프로젝트 지원을 최소 스코프로 추가**한다. BL-015에서 확장된 `StackModule` Protocol(`template_name` + `dockerfile_context`)의 첫 번째 실전 활용 사례로, JVM 하드코딩 제거의 효과를 검증하는 목적도 겸한다.

스코프 제한:
- `net/http` 표준 패턴만 probe 기본값으로 제공 (gin/echo/fiber 프레임워크 자동 감지는 BL-017/#27에서 별도 구현)
- 엔트리포인트는 루트 `main.go` + 단일 `cmd/<name>/main.go`만 지원 (복수/재귀 탐색은 향후 확장)
- 로컬 artifact 탐색 없음 (Dockerfile 컨테이너 빌드 전용)

## Functional Requirements

### Stack Module 구현

| ID | 요구사항 |
|----|---------|
| F-01 | `scripts/stacks/go.py`에 `GoStackModule` 클래스 구현 — `StackModule` Protocol 7 메서드(`detect`, `build_plan`, `probe_plan`, `defaults`, `artifact_locator`, `dockerfile_context`) + ClassVar(`name="go"`, `template_name="go"`) 전부 구현 |
| F-02 | `GoStackModule.detect(project_dir)` — `go.mod` 존재 확인. 없으면 `None`, 있으면 `StackDetectResult` 반환 |
| F-03 | `detect()` 내부: `go.mod` 파싱으로 `module` path + `go 1.x` 지시어 버전 추출. 파싱 실패 시 `GoDetectionError` raise (ProjectAnalyzer가 catch해 gaps 기록) |
| F-04 | `detect()` 내부: 엔트리포인트 후보 수집만 수행. 최종 엔트리포인트 해결은 `build_plan()`에서(`UserInputs.app_name` 필요). detect 단계 작업: (a) 루트 `main.go` 존재 여부 / (b) `cmd/*/main.go` 후보 디렉토리명 목록 수집 (symlink escape 방어 `is_within` 적용) |
| F-05 | `detect()` 반환값: `StackDetectResult(port=None, entrypoint=<미결정 sentinel 또는 확정 경로>, framework="go-generic", version=<go_version>, build_system=None, actuator_enabled=False, cmd_candidates=<디렉토리명 list>)`. 루트 `main.go` 있으면 `entrypoint="."` + `cmd_candidates=[]`. 루트 없으면 `entrypoint=""`(미결정 sentinel) + `cmd_candidates=<후보 목록>` |
| F-06 | `build_plan(detect_result, *, inputs)` — 입력 가정: `detect_result`는 **`ProjectAnalyzer`가 config override(F-27)를 이미 적용한 상태**로 전달됨(따라서 여기서 config를 읽지 않음 — stateless). 엔트리포인트 resolve 우선순위: (1) `detect_result.entrypoint`가 확정값(`.` 또는 `./cmd/<x>`) → 그대로 사용 / (2) `detect_result.entrypoint == ""`(미결정) 이면 `cmd_candidates` 기반: (2-a) `inputs.app_name`과 일치하는 후보 → `"./cmd/{app_name}"` / (2-b) 단일 원소 → `"./cmd/{그것}"` / (2-c) 복수 + 매칭 실패 → `GoBuildPlanError` raise (F-28 한국어 메시지) / (2-d) 0개 → `"."` fallback + gap 기록. 검증 통과(F-29) `app_name` + 해결된 `entrypoint`로 구성: `builder_image="golang:{go_version}-alpine"`, `runner_image="gcr.io/distroless/static-debian12:nonroot"`, `build_cmd='CGO_ENABLED=0 go build -ldflags="-s -w" -o {app_name} {entrypoint}'`, `artifact_path="{app_name}"` |
| F-07 | `probe_plan(detect_result)` — `ProbeSpec(kind="http", path="/healthz", port=port)` 단일값을 liveness/readiness 양쪽에 사용. port는 `detect_result.port or inputs.port` (최종은 orchestrator에서 결합) |
| F-08 | `defaults(resource_hint)` — Go tier(JVM 대비 낮춤): small=50m/64Mi/250m/128Mi, medium=100m/128Mi/500m/256Mi, large=250m/256Mi/1000m/512Mi. `writable_paths=["/tmp"]`(Go는 구조화 로그를 stdout으로, `/var/log` 불필요). `run_as_user=65532`(distroless nonroot 내장 UID — F-30 필드) |
| F-09 | `artifact_locator(...)` — 최소 스코프: 빈 list `[]` 반환. 로컬 빌드 산출물 탐색 없음 (향후 확장 여지만 유지) |
| F-10 | `dockerfile_context(...)` — 템플릿 렌더용 dict 반환. keys: `builder_image`, `runner_image`, `build_cmd`, `artifact_path`, `port`, `app_name` (ENTRYPOINT에서 `/app/{app_name}` 사용) |

### Dockerfile 템플릿

| ID | 요구사항 |
|----|---------|
| F-11 | `templates/dockerfile/go.tmpl` 신규 작성 — 2-stage multi-stage (builder: `golang:X-alpine`, runner: `gcr.io/distroless/static-debian12:nonroot`) |
| F-12 | builder 스테이지: `WORKDIR /build` → `COPY go.mod go.sum* ./` + `RUN go mod download` (의존성 캐시 레이어) → `COPY . .` → `RUN {{ build_cmd }}` |
| F-13 | runner 스테이지: `COPY --from=builder /build/{{ app_name }} /app/{{ app_name }}` (distroless는 USER/addgroup 불필요 — nonroot 내장 UID 65532), `EXPOSE {{ port }}`, `USER nonroot`, `ENTRYPOINT ["/app/{{ app_name }}"]` |
| F-14 | `.dockerignore` 재사용 — `templates/dockerfile/dockerignore.tmpl` 그대로 사용(stack 무관). Go 특유 제외 항목이 필요하면 별도 확장은 추후 |

### 통합 (orchestrator / registry / analyzer)

| ID | 요구사항 |
|----|---------|
| F-15 | `PipelineDependencies.stack_registry` 초기화 시 `GoStackModule()` 추가 등록 — `{"jvm": JvmStackModule(), "go": GoStackModule()}` |
| F-16 | `ProjectAnalyzer`의 스택 자동 선택 로직: `StackDecision.forced_stack`이 None(auto)이면 `stack_registry` 순회 `detect()` — JVM 우선 시도, 실패 시 Go 시도. 첫 번째 match의 `name`을 `AnalysisResult.stack`에 기록 |
| F-17 | JVM과 Go 모두 detect 실패 시: 기존 에러 플로우(gap 기록 + 사용자 안내) 유지. 새 에러 타입 추가 없음 |

### 사용자 override (선택 사양)

| ID | 요구사항 |
|----|---------|
| F-18 | `.devflow-k8s-deploy.yml`의 `stack.go.entrypoint` 키 지원 — 책임 경계: **(a) ConfigLoader**: YAML 파싱 + 타입 검증(문자열, 존재 시 `./` 접두 허용) 후 구조화 dict 반환 → **(b) ProjectAnalyzer(F-27)**: `stack.go` dict를 detect 결과에 override 적용(detect 후 → build_plan 전) → **(c) StackModule**: config 직접 읽지 않음(stateless, F-06 stateless 입력 가정과 일치) |
| F-19 | `.devflow-k8s-deploy.yml`의 `stack.go.probe.path` 키 지원 — 책임 경계 F-18과 동일. ConfigLoader가 파싱 → Analyzer가 ProbeConfig에 override(probe_plan 호출 결과의 `path` 필드 치환) → StackModule은 기본값만 반환 |

### Go 전용 헬퍼 / 내부 유틸

| ID | 요구사항 |
|----|---------|
| F-20 | `scripts/_shared/errors.py`에 `GoDetectionError` 추가 — `JvmDetectionError`와 동일 패턴 |
| F-21 | `GoStackModule` 내부: `_parse_go_mod(path: Path) -> tuple[str, str \| None]` — (module_path, go_version). 실패 시 `GoDetectionError` raise. `read_text_limited` + `is_within` 재사용 (symlink escape 방어) |
| F-22 | `GoStackModule` 내부: `_collect_cmd_candidates(project_dir: Path) -> list[str]` — F-04 후보 수집. `cmd/` 하위에서 `main.go` 포함 디렉토리 이름 반환 (정렬됨, symlink escape 방어). **대규모 모노레포 대응**: 후보 수집 상한 없음(메모리 영향 미미). 단 에러 메시지(F-28)에서 상위 10개 + 생략 요약 표시 |
| F-23 | `_DEFAULT_GO_VERSION = "1.22"` 모듈 상수 — go.mod 파싱 실패 또는 `go` 지시어 부재 시 fallback |
| F-24 | **Protocol 확장**: `StackModule.build_plan` 시그니처를 `(self, detect_result, *, inputs: UserInputs) -> BuildPlan`으로 변경 (`scripts/stacks/base.py`). `JvmStackModule.build_plan`은 `inputs` 받되 내부 무시 (JVM 골든 스냅샷 유지 — NFR-02). **마이그레이션 체크리스트** (코드+테스트 호출부 전수): (i) `scripts/stacks/base.py` Protocol 시그니처 / (ii) `scripts/stacks/jvm.py` 구현 / (iii) `scripts/project_analyzer.py` — `stack.build_plan(detect_result, inputs=inputs)` 호출로 수정 (현재 line ~220, ~305 2곳) / (iv) `tests/stacks/test_jvm.py:354` 외 `build_plan(` 직접 호출 테스트 전수(`grep -rn "build_plan(" tests/`로 도출) / (v) `tests/test_dockerfile_v0_1_1_patches.py:171` 포함 임시 JVM 인스턴스 호출부 동반 수정 |
| F-25 | `StackDetectResult`에 `cmd_candidates: list[str]` 필드 추가 (`scripts/_shared/types.py`), 기본값 `field(default_factory=list)`. JVM은 기본값 유지 (기존 값 0건 변경) |
| F-26 | `scripts/_shared/errors.py`에 `GoBuildPlanError` 추가 — `GoDetectionError`와 별도 (감지는 성공했으나 엔트리포인트 해결 실패 단계 구분) |

### 오케스트레이션 통합 확장 (Codex P1-1/P1-2/P1-5 반영)

| ID | 요구사항 |
|----|---------|
| F-27 | **`ProjectAnalyzer.analyze()` 시그니처 확장**: `analyze(project_dir: Path, *, inputs: UserInputs) -> AnalysisResult`. 내부 순서: (1) `_detect_stack(project_dir)` → `detect_result` / (2) `_apply_stack_overrides(detect_result, config.raw.get("stack", {}).get(stack_name, {}))` → override된 `detect_result` (F-18: entrypoint 덮어쓰기 등) / (3) `stack.build_plan(detect_result, inputs=inputs)` / (4) `stack.probe_plan(detect_result)` → config의 `probe.path` override 적용(F-19) / (5) AnalysisResult 구성. `SkillPipeline._analyze_project_step2`도 `analyzer.analyze(project_dir, inputs=inputs)`로 호출 수정 |
| F-28 | **한국어 에러 메시지 표준**: `GoBuildPlanError` 메시지 포맷 — `"복수 cmd 엔트리포인트 발견: {top10_list}{ellipsis}. 'app_name={app_name}'을 해당 디렉토리명과 일치시키거나 '.devflow-k8s-deploy.yml'의 'stack.go.entrypoint'를 지정하세요."` (후보 목록이 10개 초과면 정렬 상위 10개 + `"... 외 N개"` 생략). 단일 지점 `_build_multi_cmd_error_message(candidates: list[str], app_name: str) -> str` 헬퍼 함수로 구현 |
| F-29 | **입력 검증 (shell 주입 방어)**: `build_cmd` 문자열에 삽입되기 전 `app_name`/`entrypoint` 정규화: (a) `app_name`: 이미 UserInputs 단계에서 DNS-1123 subset(`^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`)로 검증되나, `build_plan` 시점에 **재검증** 후 통과 실패 시 `GoBuildPlanError` raise / (b) `entrypoint`: `./` 시작 + `^\.(/[a-zA-Z0-9._-]+)*$` 정규식 매칭만 허용 (path traversal/공백/따옴표 금지). `scripts/_shared/text_safety.py`에 `validate_go_entrypoint(s: str) -> None` 헬퍼 추가 |

### Deployment 매니페스트 스택 연동 (Codex P2-4/P2-5 반영)

| ID | 요구사항 |
|----|---------|
| F-30 | **`ResourceDefaults.run_as_user: int` 필드 추가** (`scripts/_shared/types.py`). JVM=1000 (기존 alpine adduser 관례 유지), Go=65532 (distroless nonroot 내장 UID). 기본값 없음(스택별 명시 필수) — 기존 `ResourceDefaults(...)` 직접 생성 테스트가 있으면 파라미터 추가 |
| F-31 | **`ManifestGenerator.generate_deployment()` UID 동적 주입**: 현재 `runAsUser: 1000` 하드코딩(`manifest_generator.py:~202`) → `runAsUser: {defaults.run_as_user}`로 변경. `runAsGroup`, `fsGroup`도 동일 값 사용(distroless는 group 65532도 내장). `generate_statefulset()`도 같은 수정 적용 |
| F-32 | **`ManifestGenerator.generate_deployment()` writable_paths 동적 주입**: 현재 `/tmp`, `/var/log` emptyDir 고정 → `defaults.writable_paths` 기반 volumeMounts 동적 생성. JVM(writable_paths=["/tmp", "/var/log"])은 기존 2개 유지 (골든 스냅샷 byte-identical), Go(writable_paths=["/tmp"])는 1개만 |
| F-33 | **`ConfigLoader` 확장**: `stack.go` 하위 스키마 파싱 (`stack.go.entrypoint: str`, `stack.go.probe.path: str`) — 존재 시 타입 검증 + `ResolvedConfig.raw["stack"]["go"]`로 표준 위치에 노출. 신규 키 추가만, 기존 `stack.forced_stack` 등 JVM 관련 키 변경 없음 |

## Non-Functional Requirements

| ID | 요구사항 |
|----|---------|
| NFR-01 | **NFR-EXT-01 유지**: JVM 하드코딩 0건. scripts/stacks/jvm.py 외부 파일에 `"jvm"` 문자열 리터럴 신규 추가 금지 (stack 키 비교는 모듈 `name` 속성 참조) |
| NFR-02 | **기존 JVM 골든 스냅샷 byte-identical — 명시 범위**: (i) Dockerfile: `templates/dockerfile/jvm.tmpl` 렌더 결과 / (ii) Deployment: `runAsUser=1000` 유지(F-30 JVM 기본값), `writable_paths=["/tmp", "/var/log"]` 유지(F-32) / (iii) Service / (iv) ServiceAccount. 4종 전부 변화 0건. F-24 `build_plan` 시그니처 확장 및 F-31/F-32의 manifest 동적화 이후에도 JVM 출력은 현재 골든과 동일해야 함. 골든 스냅샷 커버리지는 NFR-04 (d-jvm)에서 확장 보장 |
| NFR-03 | **테스트 리그레션 없음**: 기존 695개 테스트 전체 통과 유지 |
| NFR-04 | **신규 테스트 추가** (최소, Codex 리뷰 반영 포함): (a) Go detect happy path / (b) Go detect 실패 (`go.mod` 없음) / (c) 단일 `cmd/<name>/main.go` 엔트리포인트 감지 / (d) Go Dockerfile 골든 스냅샷 (templates/dockerfile/go.tmpl 렌더 결과) / **(d-jvm) JVM deployment/service/serviceaccount 골든 스냅샷 3종 신규 추가 (NFR-02 보장)** / (e) Go build_plan 값 / (f) Go resource tier small/medium/large / (g) 복수 `cmd/*/main.go` + `app_name` 매칭 성공 (app_name="kube-api" → `./cmd/kube-api`) / (h) 복수 `cmd/*/main.go` + app_name 매칭 실패 → `GoBuildPlanError` raise + 한국어 메시지 포맷 검증(F-28) / (i) 루트 `main.go` + `cmd/*/main.go` 공존 시 루트 우선 + rationale gap 기록 확인 / (j) JvmStackModule.build_plan은 `inputs` 키워드 인자를 받아도 기존 골든 스냅샷과 동일 출력 / **(k) `SkillPipeline → ProjectAnalyzer.analyze(inputs=...) → stack.build_plan(inputs=...)` 전체 체인 inputs 전달 검증** / **(l) `stack.go.entrypoint` config override — ConfigLoader 파싱 + Analyzer 적용 + build_plan 결과 경로 일치** / **(m) `stack.go.probe.path` config override** / **(n) `isinstance(GoStackModule(), StackModule)` Protocol 런타임 체크(NFR-08)** / **(o) `StackDetectResult(...)` 기존 호출부 호환성 — `cmd_candidates` 미지정 시 기본값 `[]`** / **(p) 보안 회귀: `app_name`에 `; rm -rf /` 같은 shell 주입 문자열 → `GoBuildPlanError` raise(F-29)** / **(q) 보안 회귀: `entrypoint`에 `../etc/passwd` 같은 path traversal → `GoBuildPlanError` raise(F-29)** / **(r) UID 정합성: 생성된 deployment.yaml의 `runAsUser`가 `defaults.run_as_user`와 일치(JVM=1000, Go=65532)(F-31)** / **(s) writable_paths 정합성: 생성된 deployment.yaml의 volumeMounts가 `defaults.writable_paths`와 일치(F-32)** |
| NFR-05 | **보안 디폴트 + UID 정책 통일**: Go 스택 Dockerfile `USER nonroot` (distroless 내장 UID 65532) ↔ K8s deployment `runAsUser=65532` 일치 (F-30/F-31). JVM 스택은 Dockerfile `adduser -u 1000` ↔ `runAsUser=1000` 기존 일치 유지. readOnlyRootFilesystem 호환 (스택별 `writable_paths`), capabilities.drop=ALL 유지 |
| NFR-06 | **Dockerfile 재현성**: builder/runner 이미지 태그 고정(latest 금지). `golang:1.22-alpine`처럼 minor 버전 명시. distroless는 태그 `nonroot` 고정(distroless는 semver 미사용) |
| NFR-07 | **Go 바이너리 정적 링크**: `CGO_ENABLED=0` 고정. `-ldflags="-s -w"`로 디버그 심볼 제거(이미지 크기 축소). distroless/static은 glibc 없으므로 CGO 허용 불가 |
| NFR-08 | **Protocol 준수 런타임 검증**: `GoStackModule`이 `StackModule` Protocol과 `isinstance` 런타임 체크를 통과해야 함(`@runtime_checkable`) |

## Assumptions

- A-01 **단일 모듈 프로젝트**: go.mod 단일(프로젝트 루트). multi-module workspace(`go.work`) 미지원. 감지되면 루트 go.mod만 사용
- A-02 **HTTP 서버 + /healthz 핸들러**: 사용자가 `net/http`로 `/healthz` 엔드포인트를 직접 구현. Dockerfile/k8s manifest는 경로가 존재한다고 가정
- A-03 **포트 입력 책임**: Go는 코드 정적 분석으로 포트 추론 없음. 사용자가 `inputs.port`로 명시
- A-04 **프레임워크 자동 감지 제외**: gin/echo/fiber/chi 등의 probe 기본값 차별화는 BL-017(#27). 이들 프레임워크도 `/healthz` 핸들러를 직접 구현하면 현 스코프로 동작
- A-05 **go.mod `go` 지시어**: 정상적인 `go 1.x` 형식. 비표준(`go 1.21.0` 등 패치 버전 포함)은 major.minor로 절단. 파싱 실패 시 `_DEFAULT_GO_VERSION = "1.22"` fallback
- A-06 **distroless 이미지 가용성**: `gcr.io/distroless/static-debian12:nonroot` 이미지는 Google 공식 레지스트리 가용 + 사용자 네트워크에서 접근 가능하다고 가정. 사설 레지스트리 미러링은 사용자 책임 (README에 주석 추가)
- A-07 **auto 스택 라우팅 순서**: JVM 우선 → Go 후순위. 동일 디렉토리에 `go.mod` + `build.gradle`이 공존하는 이상 케이스는 현 스코프에서 JVM으로 선택 (경고 없음). 해결은 사용자 config `stack.forced_stack` — 실제 ConfigLoader의 `stack_decision()` 키명과 일치(변경 없음, 기존 관례 유지)
- A-08 **복수 `cmd/*/main.go` 처리 규칙 (kube-style 모노레포)**: Codex P1-4 반영, 우선순위 재정의 — (i) **`stack.go.entrypoint` config 최우선**: 명시되면 Analyzer가 detect 결과를 덮어써 build_plan에 전달(F-27). (ii) 미명시 시 `UserInputs.app_name` ↔ `cmd/<name>/` 디렉토리명 매칭. (iii) 매칭 실패 시 단일 후보 / (iv) 복수 후보 + 매칭 실패 → `GoBuildPlanError` raise + F-28 한국어 메시지(상위 10개 + 생략 요약). **루트 선택 rationale**: 루트 `main.go`와 `cmd/*/main.go`가 공존 시 루트 우선인 이유는 "가장 단순한 Go 프로젝트 관례"이며, 이 선택 근거는 `AnalysisResult.gaps`에 `"루트 main.go 감지 — cmd/*가 있어도 루트 우선 선택됨. 변경하려면 stack.go.entrypoint 지정"` 메시지로 기록. **Go `cmd/*` 레이어 분리**: Go의 `cmd/*`는 multi-binary 레이어로, `ProjectAnalyzer`의 multi-module 처리(JVM Gradle/Maven 서브모듈 전용, `ModuleInfo`)와 **별개**. 서로 간섭하지 않음(혼용 미지원). 즉 Kubernetes 스타일 리포(kube-api / kube-controller / kube-scheduler)에서 app_name을 바이너리 이름과 일치시키는 관례를 전제

## Open Questions

없음 (핵심 질문 2건 해결: Q1 → α distroless/static-debian12:nonroot / Q2 → B 루트+cmd 지원).

## Change Log

- 2026-04-24T08:50:00+09:00 Initial analysis — Q1/Q2 답변 반영
- 2026-04-24T10:05:00+09:00 UPDATE — kube-style 모노레포(복수 `cmd/*/main.go`) 대응:
  - F-04 재정의: detect는 후보 수집만, 엔트리포인트 해결은 build_plan으로 이관
  - F-05: `StackDetectResult.cmd_candidates` 필드 추가
  - F-06: `build_plan(detect_result, *, inputs)` 시그니처, app_name 매칭 + 실패 시 GoBuildPlanError
  - F-10: `dockerfile_context`에 `app_name` 키 추가 (entrypoint 대체)
  - F-13: Dockerfile ENTRYPOINT를 `/app/{{ app_name }}`로 변경 + `go build -o {{ app_name }}`
  - F-22: `_detect_entrypoint` → `_collect_cmd_candidates` (책임 분리)
  - F-24 신규: `StackModule.build_plan` Protocol 시그니처 확장 (`*, inputs: UserInputs`)
  - F-25 신규: `StackDetectResult.cmd_candidates` 타입 추가
  - F-26 신규: `GoBuildPlanError` 예외 추가
  - NFR-02 보강: Protocol 확장에도 JVM 골든 스냅샷 byte-identical 유지
  - NFR-04: 테스트 케이스 (g)/(h)/(i)/(j) 추가
  - A-08 신규: kube-style 복수 cmd/ 처리 규칙 명시
- 2026-04-24T11:15:00+09:00 UPDATE 2 — Codex 리뷰(codex-review-requirements-01.md) P1+P2 반영:
  - F-06: Analyzer가 config override 사전 적용한다는 stateless 가정 명시
  - F-08: `run_as_user=65532` (Go distroless) 반영
  - F-18/F-19: ConfigLoader → Analyzer → StackModule 책임 경계 3단 명시
  - F-22: 에러 메시지 상위 10개 + 생략 요약 규칙
  - F-24: **마이그레이션 체크리스트** (Protocol/구현/호출부/테스트 5단) 추가
  - F-27 신규 **오케스트레이션 통합 확장**: `ProjectAnalyzer.analyze(inputs)` 시그니처 + `_apply_stack_overrides` 흐름 명시 (Codex P1-1)
  - F-28 신규: `GoBuildPlanError` 한국어 메시지 헬퍼 — 상위 10개 + `"... 외 N개"`
  - F-29 신규: **shell 주입 방어** — app_name DNS-1123 재검증, entrypoint 정규식 검증, `validate_go_entrypoint` 헬퍼 (Codex P1-5)
  - F-30 신규 **Deployment 매니페스트 스택 연동**: `ResourceDefaults.run_as_user` 필드 (JVM=1000 / Go=65532) (Codex P2-5 γ)
  - F-31 신규: `generate_deployment()` / `generate_statefulset()` 하드코딩 runAsUser 제거 → `defaults.run_as_user` 동적
  - F-32 신규: `generate_deployment()` writable_paths 동적 (JVM 2개 유지, Go 1개) (Codex P2-4)
  - F-33 신규: `ConfigLoader` `stack.go` 하위 파싱
  - NFR-02 범위 명시화 — 4종 byte-identical + runAsUser 1000 + writable_paths 2개 유지 조건
  - NFR-04 확장: (d-jvm) manifest 3종 골든 신규 / (k)~(s) inputs 체인 / config override / Protocol isinstance / 호환성 / 보안 회귀 / UID 정합 / writable_paths 정합
  - NFR-05 UID 정책 통일 명시화
  - A-07 `stack.forced_stack` 키명 실제와 일치 설명 (Codex P3-1)
  - A-08 우선순위 재정의: **config > app_name > 단일 > 에러** (Codex P1-4), 루트 선택 rationale gap 기록, Go cmd/* ↔ JVM multi-module 레이어 분리
- 2026-04-24T17:30:00+09:00 UPDATE 3 — Phase 4 구현 중 Protocol 의존성 조정:
  - F-24 `StackModule.build_plan` 시그니처를 `inputs: UserInputs` 필수 → `inputs: UserInputs | None = None` Optional로 변경
  - 이유: Phase 5(F-27 Analyzer 시그니처 확장) 완료 전까지 project_analyzer.py 호출부가 깨지지 않도록 점진적 이행
  - Codex Phase 2 리뷰 P2-3 제안(기각했던 "optional 선택 대안")을 실제 구현 단계에서 자연스럽게 수용
  - JVM은 `inputs` 무시 — 기존 골든 byte-identical 유지 (NFR-04 j로 검증)
  - Go는 `inputs.app_name` 필요 시 `None` 체크 후 `GoBuildPlanError` raise
