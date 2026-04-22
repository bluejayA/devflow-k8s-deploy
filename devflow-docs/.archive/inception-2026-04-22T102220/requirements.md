# Requirements Analysis

**Depth**: Comprehensive
**Timestamp**: 2026-04-15T15:30:00+09:00
**Source**: `2026-04-15-brainstorming-v0.1.0-scope.md` (13 design axes + 5 extensibility constraints)
**ID 인벤토리** (2026-04-17 자동 집계 정정): F-* **71개** (F-09 reserved, F-46a 포함) / NFR **17개** (NFR-09 제거, NFR-SEC-05 추가) / TR 8개 / Assumption 13개 / Open Question 4개(전부 해결)

> **자동 집계 명령** (Change Log/CI에 사용):
> ```bash
> grep -oE '^\| F-[0-9]+[a-z]?' requirements.md | sort -u | wc -l   # F-*
> grep -oE '^\| NFR-[A-Z0-9-]+' requirements.md | sort -u | wc -l    # NFR
> ```
>
> **F-09 status**: reserved (의도적 미사용 — F-08과 F-10 사이 ID 슬롯 비워둠. v0.2+ 추가 시 F-09 사용 가능).
> **NFR-09 status**: removed (성능 NFR. 운영 데이터 기반 v0.2+ 검토).

---

## User Intent

`bluejayA/devflow-k8s-deploy` 플러그인의 **v0.1.0**을 개발한다. 목표는 **"시니어 엔지니어의 판단력을 인코딩한" Kubernetes 배포 준비 스킬**로, JVM(Kotlin + Java Spring) 백엔드 프로젝트에 대해 프로덕션 보안 체크리스트가 반영된 Dockerfile + Kubernetes manifest를 생성한다.

스킬은 AIDLC 비종속 독립 스킬이며, **생성만 수행하고 실제 배포는 하지 않는다**. 산출물은 인라인 "왜" 주석을 포함하며, validate_k8s.py로 결정론적 정적 검증을 거치고 `kubectl apply --dry-run=client`로 최종 확인한다.

v0.1.0은 **JVM 단일 스택**으로 시작하되, 확장성 제약 5가지를 구조적으로 반영하여 v0.2(Go) / v0.3(Python) / v0.4(React) 확장 비용을 최소화한다.

---

## Functional Requirements

우선순위: **Must** (v0.1.0 출시 필수) / **Should** (출시 권장) / **Could** (여유 시)

### SKILL 파이프라인

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-01 | SKILL.md는 5 STEP 파이프라인 구조를 따른다: (1) 입력 수집 → (2) 코드 분석 → (3) 아티팩트 생성 → (4) 검증 게이트 → (5) 결과 패키징 | Must | L |
| F-02 | STEP 1은 앱명 / 노출 포트 / 노출 방식(ClusterIP\|NodePort\|LoadBalancer) / namespace / 출력 디렉토리 / 리소스 프로파일 힌트를 **구조적으로** 수집한다 | Must | L |
| F-02a | **용어 번역 레이어**: STEP 1의 모든 질문은 K8s/Spring 원어(`ClusterIP`/`NodePort`/`LoadBalancer`/`namespace`/`actuator` 등)를 사용자 의도 기반 한국어 질문으로 번역하여 제시한다. 예: "노출 방식?" → "어디서 접속할 건가요? (a) 사내 네트워크만 (b) 외부 인터넷에서 접속 가능". 내부 매핑은 `rationale.md`에 원어와 함께 기록. **비개발자/AI-assisted 개발자** 사용성 확보 목적. 프리셋(v0.2+)과는 독립 | Must | L |
| F-02b | **"이게 뭐예요?" 도움말**: 각 STEP 1 질문에 "? 도움말" 옵션을 제공. 선택 시 1-2줄 설명 후 원 질문으로 복귀. 도움말 텍스트는 한국어, 용어 원어 병기(예: "네임스페이스(namespace)는 쿠버네티스에서 앱을 분류하는 폴더 같은 개념이에요. 보통 프로젝트명으로 쓰세요"). 도움말 내용은 SKILL.md 본문에 정적 포함 (외부 파일 분리는 v0.2+) | Must | L |
| F-03 | STEP 2는 프로젝트 디렉토리에서 런타임 / 진입점 / 포트 / 상태성을 추론하며, 추론 불가 시 사용자에게 질문한다 | Must | M |
| F-04 | STEP 3은 Dockerfile + Deployment + Service + ServiceAccount를 생성한다. 이 4종 외 리소스(StatefulSet, CronJob, Ingress 등)는 v0.1.0에서 생성하지 않는다 | Must | L |
| F-05 | STEP 4는 validate_k8s.py 실행 → `kubectl apply --dry-run=client` 실행 순서로 검증 게이트를 수행한다 | Must | M |
| F-06 | STEP 5는 생성물과 함께 `rationale.md`와 `summary.json`을 `k8s-output/`에 패키징한다 | Must | L |
| F-07 | SKILL description은 한국어(자연어 트리거용), body는 영어(기술 스펙)로 작성한다 (하이브리드 Progressive Disclosure) | Must | L |
| F-08 | 자연어 트리거 예시를 description에 6개 이상 포함한다: "배포 준비", "Dockerfile 만들어줘", "k8s manifest", "컨테이너화", "deploy this to cluster", "k8s에 올려줘" 등 | Should | L |

### JVM 스택 지원 (v0.1.0)

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-10 | Kotlin + Java Spring 프로젝트를 **JVM 단일 스택**으로 지원한다 | Must | L |
| F-11 | 빌드 시스템 인식: Gradle (KTS + Groovy), Maven. 매니페스트 파일(`build.gradle.kts`, `build.gradle`, `pom.xml`)을 통해 판별한다 | Must | M |
| F-12 | Spring Boot 포트 추론 우선순위: (1) 환경변수 `SERVER_PORT` → (2) `application-{profile}.yml` / `application-{profile}.properties` → (3) `application.yml` / `application.properties`의 `server.port` → (4) 기본값 `8080`. 추론 실패 시 사용자에게 질문 | Must | M |
| F-13 | Spring Boot **버전 감지**: `build.gradle(.kts)` 또는 `pom.xml`에서 `spring-boot` 버전 추출. Boot 2.x: `/actuator/health` 단일 엔드포인트. Boot 3.x: `/actuator/health/liveness` + `/actuator/health/readiness` 분리 엔드포인트. actuator 활성화 감지는 `management.endpoints.web.exposure.include` 기반 | Must | M |
| F-14 | actuator 미활성 / Boot 버전 미감지 / 감지 실패 시 probe를 TCP socket (`tcpSocket.port`)으로 폴백한다 | Must | L |
| F-15 | JVM 리소스 기본값: `requests.memory: 512Mi`, `limits.memory: 1Gi` (GC heap 여유 고려) | Should | L |
| F-16 | 비-Spring JVM 앱 (Ktor, Micronaut 등) 감지 시 Spring 특화 probe 미사용, TCP 폴백 + 사용자에게 probe 설정 확인 질문 | Should | M |

### Dockerfile 생성

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-20 | Dockerfile은 multi-stage 구조로 생성한다: builder (JDK + Gradle/Maven) → runner (JRE-alpine) | Must | L |
| F-21 | 기본 베이스 이미지는 `eclipse-temurin:21-jre-alpine` (JRE), `eclipse-temurin:21-jdk-alpine` (JDK 빌더). 설정 파일로 오버라이드 가능 | Must | L |
| F-22 | 비root 사용자 생성 후 `USER appuser` 지시어를 CMD 바로 앞에 배치한다 | Must | L |
| F-23 | `latest` 태그 사용 금지 (경고 → 명시 태그 또는 digest 권장) | Must | L |
| F-24 | 주석 정책: Dockerfile의 보안 관련 지시어(USER, COPY --chown, HEALTHCHECK 등)에 "왜 이 설정인지" 근거 주석 포함. 비-보안 지시어는 선택 | Must | M |
| F-25 | Gradle/Maven 빌드 캐시 최적화: 의존성 다운로드 레이어를 소스 코드 레이어보다 먼저 배치 | Should | M |

### Kubernetes Manifest 생성

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-30 | Deployment는 `spec.replicas`, `spec.selector.matchLabels`, `spec.template.metadata.labels`, `spec.template.spec.containers[0]`, `spec.template.spec.securityContext`, `spec.template.spec.serviceAccountName`, `spec.template.spec.automountServiceAccountToken: false` 필드를 포함한다 | Must | L |
| F-31 | Pod 레벨 securityContext: `runAsNonRoot: true`, `runAsUser: 1000`, `fsGroup: 1000`, `seccompProfile.type: RuntimeDefault` | Must | L |
| F-32 | Container 레벨 securityContext: `allowPrivilegeEscalation: false`, `privileged: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`. **JVM 기본 쓰기 경로 대응 (확장)**: `emptyDir` 볼륨을 (a) `/tmp` (b) `/var/log` (c) Tomcat work dir(`/tmp/tomcat.*`은 (a)에 흡수)에 마운트하여 readOnlyRootFilesystem과 공존. Spring Boot 감지 시 `/tmp` + `/var/log`는 **자동 추가** (감지 결과와 무관하게 기본 적용). 추가 경로(`/var/cache` 등)는 사용자 설정으로 확장. **운영 첫날 503 방지** 목적 — 페르소나 P3-3 리뷰 반영 | Must | L |
| F-33 | 리소스: `requests` + `limits`에 `cpu`와 `memory` 모두 명시 | Must | L |
| F-34 | probes: `livenessProbe`와 `readinessProbe` 모두 명시 (F-13/F-14 규칙 적용) | Must | L |
| F-35 | 전용 ServiceAccount 생성 (default SA 사용 금지), `automountServiceAccountToken: false` 명시 | Must | L |
| F-36 | Service는 `type`, `selector`, `ports[].port`, `ports[].targetPort` 필드를 포함하며 `targetPort`는 container port와 일치해야 한다. **Service type 제약**: ClusterIP 기본. NodePort 또는 LoadBalancer 선택 시 STEP 1에서 사용자에게 확인 질문 (NodePort는 `nodePort` 명시 권장, LoadBalancer는 클라우드 프로바이더 전제 안내) | Must | L |
| F-37 | 주석 정책: 보안(securityContext, SA) + 리소스(requests/limits) + 위험(image tag, probes) 필드에만 근거 주석 필수. selector/labels/metadata 등은 선택 | Must | M |
| F-38 | Stateful 앱 감지 시 (DB 연결 / 파일 쓰기 / PVC 필요 시그널) 경고 출력 + `rationale.md`에 "상태성 미지원 — v0.2+ 대응 예정" 기록. Deployment 그대로 생성 | Should | M |
| F-39 | **Multi-module 프로젝트 처리**: Gradle/Maven 루트에 하위 모듈(`settings.gradle(.kts)`, `<modules>` 블록)이 있으면 감지 → (1) 설정 `app.module`이 명시되어 있으면 해당 모듈 사용 (2) 명시 안 됐으면 사용자에게 모듈 선택 프롬프트 (3) 선택된 모듈의 `build.gradle(.kts)` / `pom.xml` 기준으로 이후 분석 진행. 단일 모듈이면 이 단계 스킵 | Must | M |

### 검증기 (validate_k8s.py)

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-40 | 검증기는 manifest YAML만 검사하며 스택 판단을 하지 않는다 (stack-agnostic) | Must | L |
| F-41 | Rule ID 체계: `SEC-NNN` (보안), `RES-NNN` (리소스), `SVC-NNN` (Service), `SA-NNN` (ServiceAccount), `IMG-NNN` (이미지). 각 규칙 고정 ID 유지 | Must | L |
| F-42 | 3단계 exit code: `0` (all PASS), `1` (FAIL 존재), `2` (FAIL 없음 + WARN 존재 = **soft-success**). `2`는 생성 성공 취급 — 소비자(CI/orchestrator)는 `2`를 continue로 처리해야 함. **소비자 가이드 명시 의무 (확장)**: README와 `summary.json` 스펙 문서에 "쉘 호출 시 `&& [ $? -le 2 ]` 또는 `\|\| [ $? -eq 2 ]` 처리 필수" 경고를 명시. 이 경고가 없으면 `set -e` CI에서 soft-success가 실패로 오인됨 — 페르소나 P2-2 리뷰 반영 | Must | L |
| F-43 | 필수 체크 목록: `SEC-001` runAsNonRoot / `SEC-002` privileged / `SEC-003` allowPrivilegeEscalation / `SEC-004` readOnlyRootFilesystem / `SEC-005` capabilities.drop=[ALL] / `SEC-006` seccompProfile / `SEC-007` runAsUser>0 / `SEC-008` fsGroup / `RES-001` cpu/memory requests + limits / `IMG-001` no latest tag / `SA-001` automountServiceAccountToken=false / `SA-002` serviceAccountName 명시 / `SVC-001` Service 존재 / `SVC-002` targetPort ↔ container port 일치 / `PRB-001` livenessProbe / `PRB-002` readinessProbe | Must | M |
| F-44 | 모든 체크 함수는 `containers` + `initContainers` 모두 순회한다 (샘플의 initContainer drift 제거) | Must | L |
| F-45 | WARN 레벨 예시: `RES-W01` requests:limits 비율 과도 (>4배), `IMG-W01` digest pinning 미사용 | Could | L |
| F-46 | 실패 메시지 포맷: `[LEVEL] rule_id container_name: 설명 → 수정 제안`. 예: `[FAIL] SEC-001 app: runAsNonRoot 미설정 → spec.securityContext.runAsNonRoot: true 추가. 미설정 시 컨테이너 탈출 공격 시 호스트 root 권한 획득 가능` | Must | L |
| F-46a | `SEC-009` 평문 시크릿 검출: `env[].value` 필드에서 시크릿 패턴(`password`, `secret`, `token`, `api_key`, `apikey` 등 대소문자 무시) 감지 시 FAIL. → `valueFrom.secretKeyRef` 사용 권장 안내 | Must | M |
| F-47 | 검증 결과 JSON 출력 모드 (`--json`): `summary.json`에 포함될 수 있는 형태로 stdout에 출력 | Should | L |

### 검증 흐름

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-50 | STEP 4 자동 수정 루프: validate_k8s.py 실패 시 수정안 생성 → 재검증. 최대 3회 시도 | Must | M |
| F-51 | `kubectl apply --dry-run=client -f k8s-output/` 실행. 실패 시 동일한 3회 자동 수정 루프 | Must | M |
| F-52 | 3회 초과 시 bail-out: 현재 상태 보존 + `k8s-output/troubleshoot.md`에 전체 시도 로그 저장 + 사용자에게 수동 개입 요청. **한국어 요약 의무 (확장)**: troubleshoot.md 상단에 "어느 STEP / 어느 컴포넌트 / 무슨 이유로 실패" 한국어 1-2줄 요약을 필수 포함. 비개발자/AI-assisted 사용자가 원어 로그를 읽지 않아도 다음 행동을 판단할 수 있어야 함 — 페르소나 P1-3 리뷰 반영 | Must | L |
| F-53 | **Container image build** 옵션 실행: `build.engine` 설정이 `skip`(기본값)이면 빌드 단계 전체 생략. `auto` 또는 특정 엔진 지정 시에만 실행 (**opt-in 방식**). 엔진 미감지 시 경고 후 스킵 | Should | L |
| F-54 | Container image build 실패 시 3회 자동 수정 루프 + bail-out (F-50~F-52와 동일 패턴) | Should | M |
| F-55 | trivy / hadolint 실행 **안내**만 포함. 자동 실행 금지 (경계 유지) | Should | L |
| F-56 | kubectl 미설치 환경에서 `--dry-run=client` 불가능 시: 경고 출력 + `rationale.md`에 "kubectl 미감지 — dry-run 생략" 기록 후 계속 진행 | Must | L |
| F-57 | Container 빌드 엔진 자동 감지 순서: (1) `docker` → (2) `podman` → (3) `nerdctl`. 세 엔진 모두 `build`/`images`/`tag` CLI 인자 호환으로 동일 로직 재사용. 설정 `build.engine`이 `auto`가 아니면 해당 엔진만 시도 | Must | M |
| F-58 | 세 엔진 모두 미감지 시: 경고 출력 + `rationale.md`에 "빌드 엔진 미감지 — build 단계 생략" 기록 + 생성·검증 단계만 수행 (graceful degrade, F-56과 동일 패턴) | Must | L |
| F-59 | `buildah` / `kaniko` / standalone `buildctl`은 v0.1.0에서 미지원. 설정 `build.engine: buildah` 등은 v0.2+로 연기하고 v0.1.0에서 명시 시 에러 안내 | Could | L |

### 설정 파일 (3계층)

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-60 | 설정 우선순위: 프로젝트 `.devflow-k8s-deploy.yml` > 조직 `~/.claude/devflow-k8s-deploy.yml` > 스킬 내장 기본값 | Must | L |
| F-61 | 설정 스키마 최소 필드: `version`, `stack` (auto\|jvm\|go\|python\|react), `app.name`, `app.port`, `app.module` (multi-module 시 대상 모듈명), `image.repository`, `image.tag`, `service.type`, `service.port`, `service.targetPort`, `resources.requests.{cpu,memory}`, `resources.limits.{cpu,memory}`, `security.runAsUser`, `security.fsGroup`, `namespace`, `output.dir`, `output.on_exists` (prompt\|overwrite\|suffix, 기본 prompt), `build.engine` (auto\|docker\|podman\|nerdctl\|skip, 기본 **skip** — opt-in), `build.build_timeout_seconds` (int, 기본 600, `0`이면 무제한), `base_images.jdk`, `base_images.jre` | Must | M |
| F-62 | `stack: auto`면 STEP 2에서 자동 감지, 명시되면 강제 (감지 실패 대비 탈출구) | Must | L |
| F-63 | `rationale.md`는 각 최종값이 **어느 계층**에서 왔는지 명시한다 (예: `namespace: prod-svc (source: project config)`) | Must | L |

### Namespace

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-70 | namespace 조회 순서: (1) 프로젝트 설정 `.devflow-k8s-deploy.yml` → (2) 조직 설정 `~/.claude/devflow-k8s-deploy.yml` → (3) STEP 1 사용자 입력 → (4) 프로젝트 디렉토리명 기반 기본값 제안 | Must | L |
| F-71 | `default` namespace로의 자동 배정 금지. 사용자가 명시적으로 `default`를 선택해야만 허용 | Must | L |

### 출력 디렉토리 / 리포트

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-80 | 출력은 단일 디렉토리 `k8s-output/` (프로젝트 루트 기준, `output.dir` 설정으로 오버라이드) | Must | L |
| F-81 | 출력 파일: `Dockerfile`, `deployment.yaml`, `service.yaml`, `serviceaccount.yaml`, `rationale.md`, `summary.json`. bail-out 시 `troubleshoot.md` 추가 | Must | L |
| F-82 | `rationale.md` 섹션: 감지된 스택 / 진입점 / 포트 / 상태성 / 베이스 이미지 선택 근거 / 리소스 기본값 근거 / namespace 결정 근거 / probe 선택 근거 / 검증 결과 요약 / 경고 목록 | Must | L |
| F-83 | `summary.json` 스키마 (고정, 하위 호환): `{"version": "v1", "generated_at": ISO8601, "stack": string, "app": {"name": string, "ports": [int]}, "images": [{"repository": string, "tag": string}], "namespace": string, "validation": {"pass": int, "warn": int, "fail": int, "skipped": [string]}, "files": [string]}`. **`validation.skipped` 필드 추가 (확장)**: kubectl/빌드엔진 미감지로 스킵된 검증을 기계 판독 가능 형태로 기록 (예: `["kubectl_dry_run", "container_build"]`). CI가 exit code 0/2만 보고 "전부 통과"로 오인하지 못하도록 안전 계약 — 페르소나 P2-1 + Codex Must-fix 반영 | Must | M |

### 확장성 제약 (5가지) — v0.2+ 스택 추가 비용 최소화 목적으로 승격

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-90 | Dockerfile 템플릿은 `${CLAUDE_PLUGIN_ROOT}/templates/dockerfile/{stack}.tmpl`로 외부 파일 분리. v0.1.0은 `jvm.tmpl` 존재 | Must | M |
| F-91 | 스택별 추론 로직은 `${CLAUDE_PLUGIN_ROOT}/scripts/stacks/{stack}.py`로 분리. 공통 `StackModule` 인터페이스 5 메서드: `detect(project_dir) -> StackDetectResult(port, entrypoint, framework, version)` / `build_plan() -> BuildPlan(base_image, build_cmd, artifact_path)` / `probe_plan(framework, version) -> ProbeConfig(liveness, readiness)` / `defaults() -> ResourceDefaults(cpu, memory)` / `artifact_locator() -> list[str]` (생성 대상 jar/binary 경로). v0.1.0은 `stacks/jvm.py` 구현 | Must | M |
| F-92 | 설정 파일에 `stack: auto\|jvm\|go\|python\|react` 필드 필수 | Must | L |
| F-93 | SKILL.md 본문에 JVM 전용 로직 하드코딩 금지. STEP 2는 "`scripts/stacks/{stack}.py` 결과를 따른다"는 계약으로 서술 | Must | M |
| F-94 | validate_k8s.py는 stack-agnostic 유지 (F-40과 동일, 재확인) | Must | L |

### 실패·예외 처리

| ID | 설명 | 우선순위 | 리스크 |
|---|---|---|---|
| F-100 | 재실행 시 `k8s-output/` 기존 파일 처리: `output.on_exists` 설정에 따라 분기. `prompt` (기본) — 사용자에게 덮어쓰기 여부 질문 / `overwrite` — 조용히 덮어쓰기 (CI-friendly) / `suffix` — 타임스탬프 접미사 새 디렉토리 (`k8s-output-YYYY-MM-DDTHH-MM/`) | Must | M |
| F-101 | AIDLC construction-orchestrator 연동: v0.1.0은 `summary.json` 스키마(F-83) + 3단계 exit code(F-42)만 **계약**으로 공개. 실연동(orchestrator 쪽 호출 로직)은 v0.2+로 연기. v0.1.0 플러그인은 AIDLC를 인지하지 않음 (백로그 원칙 4 "AIDLC 비종속" 유지) | Must | L |
| F-102 | Container image build 타임아웃: `build.build_timeout_seconds` 설정, 기본 600초(10분). `0`이면 무제한 (사용자 Ctrl+C에 맡김). 타임아웃 초과 시 build 실패로 처리 → F-54 자동 수정 루프 진입 | Should | L |
| F-103 | **Atomic write 전략**: STEP 3~5의 파일 쓰기는 임시 디렉토리(`k8s-output/.tmp-{uuid}/`)에 먼저 수행. STEP 4 검증도 임시 대상으로 실행. 전 단계 통과 후 임시 → `k8s-output/`으로 atomic rename. 실패/Ctrl+C 시 임시 디렉토리 삭제, `k8s-output/`은 이전 상태 보존. `k8s-output/`은 항상 **일관된 완전한 세트**를 유지. **Signal handler 명시 (확장)**: SIGINT/SIGTERM에 대해 finally 블록 또는 `signal.signal()` 핸들러로 임시 디렉토리 청소 보장. 시작 시 `.tmp-*` 고아 디렉토리(7일 이상) 자동 정리. Ctrl+C에 의존하지 않는 결정론적 정리 — 페르소나 Must-fix 반영 | Must | L |

---

## Non-Functional Requirements

| ID | 항목 | 기준 (측정 가능) | 우선순위 |
|---|---|---|---|
| NFR-01 | 보안 | 생성된 모든 manifest는 validate_k8s.py에서 `FAIL: 0`. 보안 체크리스트 100% 커버 (SEC-* 전체 규칙) | Must |
| NFR-02 | 결정론성 | 동일 프로젝트 + 동일 설정으로 재실행 시 **Dockerfile + manifest YAML** (`deployment.yaml`, `service.yaml`, `serviceaccount.yaml`)이 byte-identical (cksum 테스트 통과). `summary.json`의 `generated_at`, `rationale.md`의 타임스탬프, `k8s-output/` 디렉토리명(suffix 모드)은 **예외** | Must |
| NFR-03 | 경계 준수 | 생성 전용. 컨테이너 이미지 push (`docker push` / `podman push` / `nerdctl push`) / `kubectl apply` (dry-run 외) / cluster API 호출 0건. 통합 테스트로 검증 | Must |
| NFR-04 | 네트워크 독립성 | **허용 외부 호출**: (1) 컨테이너 베이스 이미지 레지스트리 (2) `build.gradle(.kts)` / `pom.xml`에 선언된 의존성 레포지토리 (Maven Central, Gradle Plugin Portal 등). 이 외 외부 네트워크 호출 없음. 캐시된 베이스 이미지 + 로컬 Gradle/Maven 캐시가 있으면 오프라인 동작 | Must |
| NFR-05 | 플러그인 규약 준수 | 하드코딩 경로 0건. `${CLAUDE_PLUGIN_ROOT}` 사용. SKILL.md에 `version: 0.1.0` semver 헤더 | Must |
| NFR-06 | 출력 계약 안정성 | `summary.json` 스키마는 v0.1.x 패치에서 하위호환 유지. 필드 제거/타입 변경은 minor 업. 계약 문서를 repo에 저장 | Must |
| NFR-07 | 에러 복구 | 각 STEP 최대 3회 자동 수정. bail-out 시 상태 100% 보존 (부분 파일 삭제 금지). `troubleshoot.md`에 전체 시도 로그 | Must |
| NFR-08 | 확장성 검증 가능 | F-90~F-94 준수 여부를 CI에서 자동 확인 (JVM 하드코딩 grep, 템플릿 파일 존재, 스택 모듈 인터페이스) | Must |
| ~~NFR-09~~ | ~~성능~~ | ~~제거됨 — 운영 데이터 기반으로 향후 추가~~ | — |
| NFR-10 | 관찰성 | `rationale.md`는 최종 결정값의 소스(config layer / 추론 / 기본값)를 1:1 매핑하여 보여준다 | Should |
| NFR-11 | UX — 트리거 | description의 한국어 자연어 매칭으로 6가지 이상 발화 패턴에서 스킬 활성화 (수동 테스트 기준) | Should |
| NFR-12 | 주석 품질 | 주석 정책(F-24, F-37) 준수 여부를 CI에서 grep-friendly 패턴으로 점검 (예: securityContext 내 `#` 주석 존재) | Must |
| NFR-13 | 테스트 | pytest 커버리지: validate_k8s.py ≥ 85%, 스택 추론 모듈 ≥ 75% | Must |
| NFR-14 | 재현성 | 동일 환경에서 CI 실행 10회 연속 성공률 100% (flaky 테스트 0) | Should |
| NFR-15 | 보안 — 시크릿 | 생성된 manifest에 평문 시크릿 포함 금지. Secret 참조(`valueFrom.secretKeyRef`)만 허용하되 Secret 자체는 v0.1.0에서 생성하지 않음 | Must |
| NFR-SEC-05 | **경계 엔포스먼트 — CI 감지 테스트** | 통합 테스트가 금지 CLI 호출(`docker push` / `podman push` / `nerdctl push` / `kubectl apply`(`--dry-run=client` 외) / `kubectl create` / `kubectl delete` / `kubectl rollout` 등)을 호출하면 **테스트 실패**. `subprocess.Popen`/`subprocess.run` 패치로 호출 인자를 검사하는 allowlist 테스트 픽스처를 제공. 런타임 가드는 추가하지 않음 (오버엔지니어링 + 우회 가능). 회귀 방지가 목적 — Codex Must-fix #2 반영 | Must |
| NFR-16 | 호환성 | **권장 런타임**: kubectl 1.25+ / 빌드 엔진(Docker 20.10+ / Podman 4.0+ / nerdctl 1.0+). kubectl·빌드 엔진 부재 시 **degraded success** (해당 검증 스킵, rationale.md에 기록). **필수**: Python 3.11+ / Java Temurin 17 또는 21 / Gradle 7+ / Maven 3.8+ | Must |
| NFR-17 | 국제화 — 전 스테이지 메시지 정책 | SKILL description 및 사용자 대화는 한국어, 생성 파일 내 주석은 한국어, **에러 메시지는 한국어 우선 + 원문(영문) 병기 — 전 STEP 적용 (확장)**. STEP 1 입력(F-02a/F-02b)뿐 아니라 STEP 2 추론 실패 질문(F-03/F-39), STEP 4 검증 실패 메시지(F-46), bail-out 메시지(F-52), `troubleshoot.md`까지 동일 정책 적용. 컴포넌트별 책임으로는 `SkillPipeline`/`ProjectAnalyzer`/`K8sValidator`/`OutputPackager`가 사용자 대면 출력 시 한국어 + 원어 병기 의무. **Timezone**: `summary.json`의 `generated_at`은 **UTC (Z 접미사)** 고정. `rationale.md` 타임스탬프도 UTC. locale은 `ko-KR` 기본 — Codex Must-fix #4 + 페르소나 P1-3 반영 | Must |

---

## Technology Stack

| 계층 | 선택 | 소스 | 비고 |
|------|------|------|------|
| 플러그인 언어 | Python 3.11+ | 가정 (샘플 상속) | validate_k8s.py 기준 |
| 의존성 관리 | uv | CLAUDE.md | pip 사용 금지 |
| 린터/포매터 | ruff | CLAUDE.md | |
| 테스트 | pytest | CLAUDE.md | |
| YAML 파서 | PyYAML | 샘플 상속 | |
| 템플릿 엔진 | Jinja2 | OQ-04 해결 | v0.2+ 스택 추가 시 조건 분기 대비 |
| 패키지 형식 | Claude Code plugin | 스캐폴딩 | plugin.json / SKILL.md |
| 지원 타깃 - 빌드 도구 | Gradle 7+ (KTS / Groovy), Maven 3.8+ | 백로그 + Jay 선호 | |
| 지원 타깃 - JVM | Java Temurin 17 / 21 | 가정 + 업계 표준 | |
| 지원 타깃 - kubectl | 1.25+ | 가정 (보안 기능 성숙) | |
| 지원 타깃 - Docker | 20.10+ | 가정 | |

---

## Assumptions

| ID | 가정 | 근거 |
|---|---|---|
| A-01 | Python 3.11+ 사용 | 샘플 validate_k8s.py가 dataclass with defaults 등 3.7+ 기능 사용. 3.11+는 성능 개선 + 표준 |
| A-02 | uv / ruff / pytest 사용 | Jay CLAUDE.md 컨벤션 |
| A-03 | PyYAML 사용 | 샘플 상속. alternative는 ruamel.yaml이지만 검증만 하므로 필요 없음 |
| A-04 | Single-environment manifest (dev/staging/prod 분리 없음) | 브레인스토밍 축 6 — Kustomize는 v0.2+ |
| A-05 | TLS / HTTPS 스킬 범위 외 | Service type ClusterIP 기본. Ingress는 v0.5+ |
| A-06 | 프로젝트 설정 우선 > 조직 설정 | 표준 컨벤션. 팀마다 세부 다를 수 있음을 허용 |
| A-07 | JVM 기본 베이스 이미지 `eclipse-temurin:21-jre-alpine` / JDK 빌더 `eclipse-temurin:21-jdk-alpine` | Temurin이 Eclipse Foundation 공식, Alpine은 크기 최소 |
| A-08 | v0.1.0은 kubeconfig 불필요 (`--dry-run=client`는 클러스터 연결 없음) | kubectl 내부 로직 기반 |
| A-09 | kubectl 미설치 환경 = 경고 + dry-run 생략 + 계속 진행 (hard-block 아님) | UX: 생성물은 여전히 유효하므로 차단 과함 (F-56) |
| A-10 | `rationale.md` = Markdown 평문 (YAML frontmatter 불필요) | 사람용 문서 — 프런트매터는 overengineering |
| A-11 | Container 빌드 엔진은 Docker CLI 호환 3종(Docker / Podman / nerdctl)만 v0.1.0 지원. buildah / kaniko / buildctl 등은 v0.2+ | CLI 인자 차이로 분기 코드 복잡. v0.1.0은 "바로 동작"에 집중 |
| A-12 | macOS 사용자가 OrbStack / Colima / Rancher Desktop / Finch를 쓰더라도 `docker` CLI를 노출하므로 Docker로 감지됨 | 이들은 내부 구현만 다름. 플러그인 관점에서는 Docker로 취급 |
| A-13 | Jinja2를 템플릿 엔진으로 사용 (런타임 의존성 +1). `uv`로 관리. 설정 파일·manifest·Dockerfile 모두 Jinja2로 렌더링 | OQ-04 해결 결과 |

---

## Open Questions

| ID | 질문 | 영향 | 우선순위 | 상태 |
|---|---|---|---|---|
| OQ-01 | `k8s-output/` 재실행 시 기존 파일 처리 정책 | F-100 / UX | High | ✅ 해결: (d) 설정 기반, 기본 `prompt` |
| OQ-02 | AIDLC construction-orchestrator 연동 인터페이스 범위 | F-101 스코프 | Medium | ✅ 해결: (a) `summary.json` + exit code만, 실연동 v0.2+ |
| OQ-03 | Container image build 타임아웃 기본값 (+ 빌드 엔진 일반화) | F-102, F-53/F-54/F-57 | Low | ✅ 해결: (d) 설정 기반, 기본 600초. 빌드 엔진은 Docker/Podman/nerdctl 자동 감지 |
| OQ-04 | 템플릿 엔진 선택 | 템플릿 구현 방식 | Medium | ✅ 해결: (a) Jinja2 — v0.2+ 스택별 조건 분기 대비 |

---

## Risk Assessment

| 리스크 | 확률 | 영향 | 대응 |
|---|---|---|---|
| 정책-검증 drift (SKILL이 요구하는 규칙과 validate_k8s가 체크하는 규칙이 불일치) | M | H | F-41/F-43 Rule ID 표준화. CI에서 SKILL.md 규칙 선언부 ↔ validate_k8s 체크 함수 ↔ Rule ID 매트릭스 정합 검사 (NFR-08) |
| 설정 스키마·우선순위 불명확으로 재현 실패 | L | H | F-63 `rationale.md`에 소스 명시. NFR-10 관찰성 |
| 확장성 미준수로 v0.2에서 리팩토링 지옥 | M | H | F-90~F-94 Must로 승격. NFR-08 CI 강제 |
| Spring actuator 감지 실패 → 잘못된 probe | M | M | F-14 TCP 폴백. 감지 로직 단위 테스트 (actuator 설정 6가지 경우) |
| multi-module Gradle/Maven 프로젝트 | M | M | **F-39로 승격**: 모듈 자동 감지 + 사용자 선택 프롬프트 + `app.module` 설정키. 리스크에서 요구사항으로 전환 |
| Kotlin 2.0 vs Java Spring의 Gradle 스크립트 차이 (KTS vs Groovy) | M | L | F-11에서 둘 다 지원. 단위 테스트 포함 |
| kubectl/Docker 버전 불일치로 dry-run 실패 | L | M | NFR-16 최소 버전 명시. 감지 시 경고 |
| 사용자가 `.devflow-k8s-deploy.yml`에 잘못된 YAML 작성 | M | L | YAML 파싱 실패 시 상세 에러 메시지 + rationale.md에 "config 무시 — 파싱 실패" 기록 후 기본값으로 진행 |

---

## Change Log

- 2026-04-15T15:30:00+09:00 — 최초 작성. 브레인스토밍 축 1~13 + 확장성 5가지 제약을 F-*·NFR-* 형태로 변환.
- 2026-04-15T15:45:00+09:00 — OQ-01/02/03 해결: F-100(`output.on_exists`), F-101(AIDLC 계약만), F-102(타임아웃 설정). 빌드 엔진 일반화 — F-53/F-54 명칭 변경, F-57 자동 감지 순서 추가, F-58 graceful degrade, F-59 미지원 엔진 명시. F-61 설정 스키마 확장 (`output.on_exists`, `build.engine`, `build.build_timeout_seconds`). NFR-03/NFR-16 보완. A-11/A-12 가정 추가.
- 2026-04-15T15:50:00+09:00 — OQ-04 해결: 템플릿 엔진 = Jinja2. Technology Stack 표 확정. A-13 가정 추가.
- 2026-04-16T00:10:00+09:00 — Codex adversarial review 반영 (15건 즉시 수정 + 1건 제거 + 6건 v0.2 연기): F-04 SA 포함, F-12 포트 우선순위, F-13 Boot 2.x/3.x, F-32 emptyDir, F-36 Service type 제약, F-39 multi-module 승격, F-42 exit code 2 의미, F-46a SEC-009, F-53 build opt-in, F-81 SA 파일, F-91 StackModule 확장, F-103 atomic write, NFR-02/NFR-04/NFR-16/NFR-17 보완, NFR-09 제거. v0.2 연기: JSON Schema 배포/발화 패턴 자동 테스트/주석 파서/degraded_checks[]/확장성 CI/SBOM+멀티아키텍처.
- 2026-04-17 — application-design LIST 검토 중 **비개발자/AI-assisted 개발자 사용성** 갭 식별. F-02a(용어 번역 레이어), F-02b("이게 뭐예요?" 도움말) 추가. 프리셋(웹 API/내부 서비스/데모)은 v0.2+ 백로그로 연기 — MVP 피드백 후 결정.
- 2026-04-17 (3-페르소나 + Codex 리뷰 반영) — Must-fix 5건 + 추가 의견 반영:
  - F-32 확장: `/tmp` + `/var/log` 자동 emptyDir, Tomcat work dir 흡수 (운영 503 방지)
  - F-42 확장: exit code 2 소비자 가이드 README/문서 명시 의무 (set -e 호환)
  - F-52 확장: troubleshoot.md 한국어 1-2줄 요약 의무
  - F-83 확장: `validation.skipped[]` 필드 추가 (CI 안전 계약)
  - F-103 확장: SIGINT/SIGTERM 핸들러 + 고아 .tmp-* 자동 정리
  - **신규 NFR-SEC-05**: 경계 엔포스먼트 CI 감지 테스트 (런타임 가드 아님)
  - NFR-17(I18N) 확장: 전 STEP 한국어 우선 + 원어 병기 정책 (STEP 1 한정 → 전체)
  - 요구사항 ID 카운트 정정: 헤더 "60 F-*" → 자동 집계 결과 **71개** (F-09 reserved + F-46a 포함). NFR 17개 (NFR-09 제거 + NFR-SEC-05 추가, 순증감 0)
  - v0.2+ 백로그 추가: NetworkPolicy / PodDisruptionBudget / Stateful 신뢰도 점수 / LoadBalancer 비용 경고 / StackModule BuildPlan 일반화(stages: list) / validate_k8s WARN 확장(terminationGracePeriodSeconds, imagePullPolicy) / 도움말 카탈로그 외부 파일 분리
