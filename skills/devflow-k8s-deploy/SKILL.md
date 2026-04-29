---
name: devflow-k8s-deploy
description: |
  Use when a user requests Dockerfile or Kubernetes manifest generation for a JVM(Kotlin/Java Spring) or Go project.
  JVM(Kotlin + Java Spring) / Go 백엔드 프로젝트를 분석하여 Dockerfile + k8s manifest를 자동 생성합니다.
  5-STEP 파이프라인: 입력 수집 → 프로젝트 분석 → 파일 생성 → 검증 → 패키징.
  보안 기본값 자동 적용, 한국어 UX, generate-only (cluster 직접 변경 없음).

  트리거 예시:
  - "Dockerfile 만들어줘" / "k8s manifest 만들어줘" / "컨테이너화해줘"
  - "배포 준비해줘" / "k8s에 올려줘" / "JVM 배포 설정해줘" / "Go 배포해줘"
  - "deploy this to cluster" / "k8s manifest" / "containerize this"

metadata:
  version: 0.5.0
  author: Jay
  category: infrastructure
  stacks: [jvm, go]
---

# devflow-k8s-deploy

JVM(Kotlin + Java Spring) 또는 Go 프로젝트를 Kubernetes 배포용 Dockerfile + manifest로 자동 변환합니다. 시니어 엔지니어 수준의 보안 기본값과 한국어 도움말을 제공합니다.

## 언제 사용하나요? (F-07/F-08 자연어 트리거)

다음 요청이 들어오면 이 스킬을 실행합니다:

- "Dockerfile 만들어줘", "도커파일 만들어줘"
- "k8s manifest 만들어줘", "k8s 배포 파일 생성", "manifest 만들어줘"
- "컨테이너화해줘", "Kubernetes 설정해줘"
- "배포 준비해줘", "k8s에 올려줘", "JVM 배포 설정해줘", "Go 배포해줘"
- "deploy this to cluster", "k8s manifest", "containerize this"

> 현재 JVM(Kotlin + Java Spring Boot)과 Go 스택을 지원합니다. Python / React는 후속 백로그(BL-006, BL-007).

---

## 5-STEP 파이프라인 진행 지시 (F-01)

아래 5단계를 순서대로 실행하십시오. 각 STEP은 이전 STEP이 완료되어야 진행합니다.

---

### STEP 1 — 입력 수집 (F-02 / F-02a / F-02b)

사용자에게 한국어로 아래 6개 필드를 질문합니다. **각 질문마다 "?"를 입력하면 도움말을 표시**합니다. 상세 설명은 [references/help-catalog.md](references/help-catalog.md)를 참조하세요.

#### 질문 순서

**1. 앱 이름 (app_name)**
```
앱 이름을 알려주세요. (예: my-api-service)
영문 소문자/숫자/하이픈만 사용하세요. "?"를 입력하면 도움말을 표시합니다.
```
"?" 입력 시: 도움말 카탈로그 `app_name` 항목 조회 후 표시.

---

**2. 포트 (port)**
```
앱이 사용하는 포트를 알려주세요. (예: 8080)
"?"를 입력하면 도움말을 표시합니다.
```
"?" 입력 시: 도움말 카탈로그 `port` 항목 조회 후 표시.

---

**3. 노출 방식 (exposure)**
```
어디서 접속할 건가요?
  (a) ClusterIP — 사내 네트워크만  (b) LoadBalancer — 외부 공개  (c) NodePort
"?"를 입력하면 도움말을 표시합니다.
```
"?" 입력 시: 도움말 카탈로그 `exposure` 항목 조회 후 표시.

> **NodePort/LoadBalancer 선택 시 확인**: 외부 공개 여부와 클라우드 비용을 사용자에게 재확인 후 진행합니다.

---

**4. 네임스페이스 (namespace)**
```
쿠버네티스 네임스페이스를 알려주세요. (예: my-team)
'default'는 자동 배정하지 않습니다. "?"를 입력하면 도움말을 표시합니다.
```
"?" 입력 시: 도움말 카탈로그 `namespace` 항목 조회 후 표시.

---

**5. 출력 디렉토리 (output_dir)**
```
생성 파일을 어디에 저장할까요? (기본값: k8s-output)
Enter를 누르면 기본값을 사용합니다. "?"를 입력하면 도움말을 표시합니다.
```
"?" 입력 시: 도움말 카탈로그 `output_dir` 항목 조회 후 표시.

---

**6. 리소스 힌트 (resource_hint)**
```
메모리/CPU는 어느 정도 필요해요?
  (a) small  (b) medium ← 권장  (c) large
"?"를 입력하면 도움말을 표시합니다.
```
"?" 입력 시: 도움말 카탈로그 `resource_hint` 항목 조회 후 표시.

---

#### 프로젝트 루트 `.devflow-k8s-deploy.yml`이 있는 경우

설정 파일의 값이 STEP 1 질문 기본값으로 pre-fill됩니다. 사용자는 확인만 하면 됩니다.

---

### STEP 2 — 프로젝트 분석 (F-03 / F-38 / F-39)

`${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/orchestrator.py` 의 `ProjectAnalyzer`를 통해 프로젝트 디렉토리를 자동 분석합니다.

#### 분석 항목

1. **스택 감지**:
   - JVM: `build.gradle.kts` / `build.gradle` / `pom.xml` 존재 여부
   - Go: `go.mod` 존재 여부
   - mixed repo: `stack.forced_stack: go` 또는 `jvm`으로 명시 가능
2. **빌드 메타** (JVM): Gradle KTS / Gradle Groovy / Maven 판별
3. **Spring Boot 버전** (JVM): `spring-boot` 버전 추출 (2.x / 3.x)
4. **포트 추론**:
   - JVM: `SERVER_PORT` → `application-{profile}.yml` → `application.yml` → 기본 8080
   - Go: `UserInputs.port` 또는 기본 8080
5. **actuator 감지** (JVM 한정): `spring-boot-starter-actuator` 의존성 여부 → `/actuator/health` HTTP probe vs TCP probe 분기
6. **multi-module 감지** (JVM 한정): `settings.gradle(.kts)` 또는 Maven `<modules>` 블록
7. **entrypoint 감지** (Go 한정): 루트 `main.go` 또는 단일 `cmd/<name>/main.go`. 모호 시 `stack.go.entrypoint` config 필수
8. **상태성 감지**: DB 연결 / 파일 쓰기 / PVC 시그널 감지

#### 추론 실패 시

분석 중 추론이 불가능한 항목은 **한국어로 재질문**합니다.

예시 — actuator 미감지:
```
actuator를 쓰고 있나요? (도움말: "?")
build.gradle에 'spring-boot-starter-actuator'가 보이지 않아서 확인드려요.
  (a) 네, actuator를 씁니다 → /actuator/health HTTP probe 사용
  (b) 아니요, 없습니다 → TCP socket probe 사용
```

도움말("?" 입력 시):
> actuator는 Spring Boot의 헬스체크/메트릭 기능이에요. `build.gradle`에 `spring-boot-starter-actuator`가 있으면 활성화된 거예요. 없으면 TCP로 헬스체크합니다.
> 원어: `Spring Boot Actuator — /actuator/health 엔드포인트`
> 예시: Boot 2.x: `/actuator/health` 단일 / Boot 3.x: `/liveness` + `/readiness` 분리

예시 — multi-module 감지:
```
여러 모듈이 감지되었어요. 어떤 모듈을 배포할까요? (도움말: "?")
감지된 모듈:
  - order-api ← (API 서버는 보통 -api 또는 -web 모듈)
  - order-core (라이브러리 — 배포 대상 아님)
  - order-infra
배포할 모듈 이름을 입력하세요:
```

도움말("?" 입력 시):
> Gradle/Maven multi-module 프로젝트예요. 보통 API 서버는 '-api', '-web', '-server'로 끝나는 모듈이에요. 라이브러리(-core, -common)는 배포 대상이 아닙니다.
> 원어: `Gradle settings.gradle(.kts) / Maven <modules>`
> 예시: `order-api` (○) / `order-core` (×, 라이브러리)

예시 — 상태성 감지:
```
[경고] 상태성 앱 시그널이 감지되었어요.
v0.1.0은 Deployment만 생성합니다. Pod 재시작 시 데이터가 사라질 수 있어요.
StatefulSet/PVC 지원은 v0.2+에서 제공 예정입니다.
계속 Deployment로 생성할까요? (y/n)
```

도움말("?" 입력 시):
> DB 연결이나 파일 저장이 필요한 앱이에요. v0.1.0은 Deployment만 만들기 때문에, Pod 재시작 시 데이터가 사라질 수 있어요. v0.2부터 StatefulSet/PVC를 지원합니다.
> 원어: `StatefulSet vs Deployment — Pod 재시작 시 데이터 보존`
> 예시: stateless: 일반 API 서버 / stateful: DB, 메시지 큐, 파일 업로드 앱

---

### STEP 3 — 파일 생성 (F-04 / F-20~F-37)

다음 4개 파일을 `output_dir`에 생성합니다. 임시 디렉토리(`.tmp-{uuid}/`)에 먼저 쓰고 atomic rename으로 확정합니다.

#### 생성 파일

| 파일 | 설명 |
|------|------|
| `Dockerfile` | multi-stage: JDK builder → JRE runner, 비root, 캐시 레이어 최적화 |
| `deployment.yaml` | securityContext + probes + emptyDir + 리소스 + 근거 주석 |
| `service.yaml` | targetPort ↔ container port 일치, Service type 설정 |
| `serviceaccount.yaml` | 전용 SA, `automountServiceAccountToken: false` |

#### Dockerfile 보안 기본값 (F-20~F-25)

- multi-stage: `eclipse-temurin:21-jdk-alpine` → `eclipse-temurin:21-jre-alpine`
- `groupadd/useradd appuser` + `USER appuser` (비root)
- `COPY --chown=appuser:appuser`
- Gradle/Maven 의존성 레이어를 소스 코드 레이어보다 앞에 배치 (캐시 최적화)
- `latest` 태그 금지 — 명시 버전 또는 digest 사용
- 보안 관련 지시어마다 "왜 이 설정인지" 근거 주석 포함

#### Deployment 보안 기본값 (F-30~F-37)

Pod 레벨 securityContext:
```yaml
runAsNonRoot: true
runAsUser: 1000
fsGroup: 1000
seccompProfile:
  type: RuntimeDefault
```

Container 레벨 securityContext:
```yaml
allowPrivilegeEscalation: false
privileged: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
```

emptyDir 자동 마운트 (readOnlyRootFilesystem 공존용):
```yaml
volumeMounts:
  - name: tmp-dir
    mountPath: /tmp
  - name: log-dir
    mountPath: /var/log
volumes:
  - name: tmp-dir
    emptyDir: {}
  - name: log-dir
    emptyDir: {}
```

#### 진행 상황 알림

각 파일 생성 시 사용자에게 한국어로 진행 상황을 알립니다:
```
[STEP 3] Dockerfile 생성 중...
[STEP 3] deployment.yaml 생성 중...
[STEP 3] service.yaml 생성 중...
[STEP 3] serviceaccount.yaml 생성 중...
[STEP 3] 파일 생성 완료 → k8s-output/
```

---

### STEP 4 — 검증 게이트 (F-05 / F-40~F-52)

#### 4-1. K8s 정적 검증

`${CLAUDE_PLUGIN_ROOT}/scripts/validate_k8s.py`를 실행합니다:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_k8s.py" \
  --manifests {output_dir}/deployment.yaml {output_dir}/service.yaml {output_dir}/serviceaccount.yaml \
  --json
```

검증 규칙: SEC-001~009 / RES-001 / IMG-001 / SA-001~002 / SVC-001~002 / PRB-001~002

exit code 해석:
- `0`: 모든 검증 PASS → 다음 단계 진행
- `1`: FAIL 존재 → 자동 수정 시도 (최대 3회)
- `2`: FAIL 없음 + WARN 존재 (soft-success) → 경고 표시 후 다음 단계 진행

> **CI 통합 시 주의**: `set -e` 환경에서 exit code 2는 실패가 아닙니다. `|| [ $? -eq 2 ]` 또는 `[ $? -le 2 ]` 처리가 필요합니다.

#### 4-2. kubectl dry-run

```bash
kubectl apply --dry-run=client --validate=false -f {output_dir}/
```

`--validate=false`: cluster 없이 client-side 파싱만 수행. 엄격한 규칙 검증은 `validate_k8s.py` (K8sValidator)가 담당.

kubectl 미설치 시: 경고 메시지 출력 후 스킵 (graceful degrade). `summary.json`에 `skipped: ["kubectl_dry_run"]` 기록.

#### 4-3. 자동 수정 루프 (F-50~F-52)

검증/dry-run 실패 시 최대 3회 자동 수정 시도합니다. v0.1.0은 auto-fix 미지원이므로 1회 실패 시 즉시 bail-out 후 `troubleshoot.md`를 생성합니다.

bail-out 시:
```
[STEP 4] 검증 실패 — troubleshoot.md를 확인하세요.
위치: {output_dir}/troubleshoot.md
한국어 요약과 전체 로그가 포함되어 있습니다.
```

#### 4-4. opt-in 컨테이너 빌드 (F-53~F-58)

`build.engine`이 `skip`(기본값)이면 빌드 단계를 생략합니다.  
`auto` 또는 특정 엔진(`docker`/`podman`/`nerdctl`) 지정 시:

```bash
# 엔진 자동 감지 순서: docker → podman → nerdctl
{engine} build -t {image_tag} -f {output_dir}/Dockerfile {project_dir}
```

도움말("?" 입력 시):
> 기본은 Dockerfile만 만들고 빌드는 안 해요. 빌드도 하고 싶으면 'auto'를 고르세요 (docker/podman/nerdctl 자동 감지). CI에서는 보통 별도 단계에서 빌드합니다.
> 원어: `build.engine config — auto / docker / podman / nerdctl / skip(default)`
> 예시: 로컬 테스트: auto / CI 파이프라인: skip

trivy / hadolint 실행은 **안내만** 합니다. 자동 실행하지 않습니다:
```
[참고] 보안 스캔 권장:
  hadolint {output_dir}/Dockerfile
  trivy image {image_tag}
```

---

### STEP 5 — 결과 패키징 (F-06 / F-80~F-83)

#### 생성 파일

| 파일 | 설명 |
|------|------|
| `rationale.md` | 모든 설정 결정의 한국어 근거 (소스 매핑 + 스킵 검증 섹션) |
| `summary.json` | 기계 판독용 결과 요약 (v1 스키마, UTC ISO8601, `validation.skipped[]` 포함) |
| `troubleshoot.md` | bail-out 시만 생성. **상단에 한국어 1-2줄 요약 필수** + 전체 시도 로그 |

#### summary.json 스키마 (v1, F-83 실제 필드)

```json
{
  "version": "v1",
  "generated_at": "2026-04-19T12:34:56Z",
  "stack": "jvm",
  "app": {
    "name": "my-api",
    "ports": [8080]
  },
  "images": [
    {
      "repository": "registry.example.com/my-api",
      "tag": "1.0.0",
      "digest": null
    }
  ],
  "namespace": "my-team",
  "validation": {
    "pass": 15,
    "warn": 1,
    "fail": 0,
    "skipped": []
  },
  "files": [
    "Dockerfile",
    "deployment.yaml",
    "rationale.md",
    "service.yaml",
    "serviceaccount.yaml",
    "summary.json"
  ]
}
```

#### 완료 메시지

```
[완료] devflow-k8s-deploy v0.1.0

생성된 파일:
  {output_dir}/Dockerfile
  {output_dir}/deployment.yaml
  {output_dir}/service.yaml
  {output_dir}/serviceaccount.yaml
  {output_dir}/rationale.md
  {output_dir}/summary.json

검증 결과: PASS (exit code: 0)

다음 단계:
  kubectl apply -f {output_dir}/
  # 또는 CI 파이프라인에 통합 (summary.json 소비)
```

---

## 오케스트레이터 실행 방법

### Claude 내부 호출 방식

Claude는 다음을 실행합니다. `${CLAUDE_PLUGIN_ROOT}`는 플러그인 루트 절대 경로로 치환됩니다 (NFR-05).

```bash
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/orchestrator.py \
  --project-dir ${user_project_dir} \
  --output-dir ${user_output_dir}
```

> **주의**: `cd project_dir && python -m scripts.pipeline.orchestrator` 방식은 사용하지 않습니다.
> 사용자 프로젝트 디렉토리에 `scripts/` 패키지가 없으므로 실행 불가합니다.

또는 Python API로 직접 호출 (테스트/통합 목적):

```python
from pathlib import Path
from scripts.pipeline.orchestrator import SkillPipeline, PipelineDependencies

# deps 구성 후
pipeline = SkillPipeline(deps)
result = pipeline.run(
    project_dir=Path("/path/to/project"),
    output_dir=Path("k8s-output/"),
)
```

---

## 도움말 카탈로그 (F-02b)

"?" 입력 시 해당 term_id의 `ko_detail`을 표시합니다.
→ 전체 카탈로그: [references/help-catalog.md](references/help-catalog.md)

---

## 제약 및 로드맵

→ [references/roadmap.md](references/roadmap.md)
