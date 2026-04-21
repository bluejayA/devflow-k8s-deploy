# devflow-k8s-deploy

JVM 프로젝트를 Kubernetes 배포용 Dockerfile + manifest로 자동 생성하는 Claude Code 플러그인.

**v0.1.0** — JVM (Kotlin + Java Spring Boot) 스택 지원.

![version](https://img.shields.io/badge/version-0.1.0-blue)
![tests](https://img.shields.io/badge/tests-559_passed-green)
![status](https://img.shields.io/badge/status-CONSTRUCTION-orange)

---

## 한 줄 요약

Claude에게 "이 JVM 앱 Kubernetes 배포 준비해줘"라고 말하면, `devflow-k8s-deploy`가 **프로덕션 보안 체크리스트가 반영된 Dockerfile + k8s manifest**를 생성합니다. 단순 템플릿이 아니라 **왜 이 설정인지** 근거 주석이 함께 달립니다.

---

## 빠른 시작

### Claude에게 요청

```
이 Spring Boot 프로젝트를 Kubernetes 배포용으로 설정해줘
```

또는:

```
Dockerfile 만들어줘 / k8s manifest 생성 / 컨테이너화해줘
배포 준비해줘 / k8s에 올려줘 / JVM 배포 설정해줘
```

### 5-STEP 파이프라인

Claude가 아래 5단계를 한국어로 안내하며 실행합니다:

| STEP | 내용 |
|------|------|
| **1. 입력 수집** | 한국어로 6개 필드 질문 (각 질문에 "?" 입력 시 도움말) |
| **2. 프로젝트 분석** | build.gradle.kts / pom.xml 자동 분석 + Spring Boot 버전 감지 |
| **3. 파일 생성** | Dockerfile + deployment.yaml + service.yaml + serviceaccount.yaml |
| **4. 검증** | validate_k8s.py 정적 검증 + kubectl dry-run (미설치 시 graceful skip). kubectl dry-run은 `--validate=false`로 cluster 없이 client-side 파싱만 수행. 엄격한 규칙 검증은 `validate_k8s.py` (K8sValidator)가 담당. |
| **5. 패키징** | rationale.md (근거 문서) + summary.json (CI 소비용) |

### STEP 1 입력 항목

| 필드 | 설명 | 예시 |
|------|------|------|
| app_name | 앱 이름 (쿠버네티스 리소스 이름) | `my-api-service` |
| port | 앱 포트 | `8080` (Spring Boot 기본) |
| exposure | 접속 범위 | `ClusterIP` / `NodePort` / `LoadBalancer` |
| namespace | 쿠버네티스 네임스페이스 | `my-team` |
| output_dir | 출력 디렉토리 | `k8s-output` (기본값) |
| resource_hint | 리소스 규모 | `small` / `medium` / `large` |

---

## 지원 스택

| 스택 | 감지 파일 | 상태 |
|------|----------|------|
| JVM — Kotlin + Spring Boot 2.x/3.x | `build.gradle.kts` / `build.gradle` / `pom.xml` | v0.1.0 |
| Go | — | v0.2 예정 |
| Python | — | v0.3 예정 |
| React (nginx) | — | v0.4 예정 |

---

## 보안 기본값 (F-31 / F-32)

### Dockerfile

- multi-stage: `eclipse-temurin:21-jdk-alpine` (builder) → `eclipse-temurin:21-jre-alpine` (runner)
- 비root 사용자: `groupadd/useradd appuser` + `USER appuser`
- `COPY --chown=appuser:appuser`
- `latest` 태그 금지 (F-23) — 명시 버전 또는 digest 필수
- Gradle/Maven 의존성 레이어 최적화 (캐시 레이어 분리)
- 보안 관련 지시어마다 "왜 이 설정인지" 근거 주석 포함

### Kubernetes Manifest

Pod 레벨 `securityContext`:
```yaml
runAsNonRoot: true
runAsUser: 1000
fsGroup: 1000
seccompProfile:
  type: RuntimeDefault
```

Container 레벨 `securityContext`:
```yaml
allowPrivilegeEscalation: false
privileged: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
```

`readOnlyRootFilesystem` 공존을 위한 emptyDir 자동 마운트:
```yaml
volumeMounts:
  - name: tmp-dir
    mountPath: /tmp       # JVM 임시 파일
  - name: log-dir
    mountPath: /var/log   # 로그 출력
```

추가 보안:
- `automountServiceAccountToken: false` (전용 ServiceAccount)
- `serviceAccountName` 명시 (default SA 사용 금지)
- `livenessProbe` + `readinessProbe` 모두 필수

---

## 설정 파일 (선택)

프로젝트 루트에 `.devflow-k8s-deploy.yml`을 두면 STEP 1 질문이 pre-fill됩니다.

```yaml
version: v1
stack: jvm          # or "auto"
app:
  name: my-api
  port: 8080
  module: api       # multi-module 시 대상 모듈명 (예: order-api)

image:
  # 'registry.example.com'은 예시용 도메인입니다 (RFC 2606).
  # 실제 사용 시 자신의 레지스트리 호스트(예: Docker Hub, Harbor, ECR)로 교체하세요.
  repository: registry.example.com/my-api
  tag: 1.0.0        # "latest" 사용 불가

namespace: my-team

output:
  dir: k8s-output
  on_exists: prompt  # prompt (기본) / overwrite / suffix

build:
  engine: skip       # skip (기본, opt-in) / auto / docker / podman / nerdctl
  image_tag: registry.example.com/my-api:1.0.0   # engine != skip 시 필수
  build_timeout_seconds: 600              # 0 = 무제한

resources:
  requests:
    cpu: 100m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi

service:
  type: ClusterIP
  port: 80
  target_port: 8080
```

### 3계층 설정 우선순위 (F-60)

**프로젝트 > 조직 > 내장 기본값** (앞이 우선, 뒤를 덮어씀)

- 프로젝트 `.devflow-k8s-deploy.yml` 값이 존재하면 조직/내장 값을 덮어씁니다.
- 조직 `~/.claude/devflow-k8s-deploy.yml` 값이 존재하면 내장 기본값을 덮어씁니다.
- 내장 기본값은 프로젝트/조직 설정이 없는 항목에만 적용됩니다.

```
프로젝트 .devflow-k8s-deploy.yml   ← 최우선 (프로젝트가 조직을 덮어씀)
  > 조직 ~/.claude/devflow-k8s-deploy.yml  ← (조직이 내장을 덮어씀)
  > 스킬 내장 기본값                ← 최하위 fallback
```

---

## Exit Code 가이드 (F-42)

| Exit Code | 의미 | CI 처리 권장 |
|-----------|------|------------|
| `0` | 모든 검증 PASS | 정상 진행 |
| `1` | FAIL 존재 — 수정 필요 | 빌드 중단 |
| `2` | FAIL 없음 + WARN (soft-success) | 경고 로깅 후 계속 |
| `130+` | SIGINT / 사용자 중단 | 재실행 필요 |

> **중요 (CI 통합 시)**: `set -e` 환경에서 exit code 2는 실패가 아닙니다. 아래와 같이 처리하세요:
> ```bash
> python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/orchestrator.py \
>   --project-dir . --output-dir k8s-output/
> EXIT=$?
> [ $EXIT -le 2 ] || exit $EXIT   # 0, 1, 2만 정상 범위
> ```

---

## CI 통합 패턴

```bash
#!/bin/bash
set -uo pipefail  # -e는 의도적으로 빼서 exit code 2(WARN)를 직접 처리

# 'registry.example.com'은 예시용 도메인입니다 (RFC 2606).
# 실제 사용 시 자신의 레지스트리 호스트(예: Docker Hub, Harbor, ECR)로 교체하세요.
export CLAUDE_PLUGIN_ROOT=/path/to/devflow-k8s-deploy

python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline/orchestrator.py \
  --project-dir . \
  --output-dir k8s-output/
EXIT=$?

# summary.json 존재 확인
if [ ! -f k8s-output/summary.json ]; then
  echo "ERROR: summary.json 미생성. 파이프라인 실패." >&2
  exit 1
fi

# Exit code 처리 (F-42)
case $EXIT in
  0) echo "PASS" ;;
  1) echo "FAIL: summary.json 확인" >&2
     jq '.validation' k8s-output/summary.json
     exit 1 ;;
  2) echo "WARN (soft-success): 검토 권장"
     jq '.validation' k8s-output/summary.json
     ;;
  *) echo "ERROR: 예상치 못한 exit code $EXIT" >&2
     exit $EXIT ;;
esac

# summary.json 파싱 (skipped 검증 확인)
# skipped: ["kubectl_dry_run"] → kubectl 미설치 환경에서 dry-run 생략됨
jq '.validation.skipped' k8s-output/summary.json
```

---

## 한국어 도움말 (F-02b)

각 STEP에서 "?" 입력 시 10개 term의 한국어 설명을 표시합니다:

| term_id | 설명 | step |
|---------|------|------|
| app_name | 앱 이름 (k8s 리소스 식별자) | STEP 1 |
| port | 컨테이너 포트 | STEP 1 |
| exposure | Service type (ClusterIP/NodePort/LoadBalancer) | STEP 1 |
| namespace | 쿠버네티스 네임스페이스 | STEP 1 |
| output_dir | 출력 디렉토리 | STEP 1 |
| resource_hint | CPU/메모리 리소스 규모 | STEP 1 |
| actuator | Spring Boot Actuator 헬스체크 | STEP 2 |
| multi_module | Gradle/Maven 멀티 모듈 | STEP 2 |
| stateful | 상태성 앱 (DB/파일/PVC) | STEP 2 |
| build_engine | 컨테이너 빌드 엔진 | 설정 |

---

## 설치

```bash
# Claude Code 플러그인으로 설치 (예정)
/plugin install bluejayA/devflow-k8s-deploy
```

개발/로컬 사용:
```bash
git clone https://github.com/bluejayA/devflow-k8s-deploy
cd devflow-k8s-deploy

# 의존성 설치 (uv 권장)
uv sync

# 테스트 실행
uv run pytest tests/ -v
```

---

## 개발 상태

- 전체 테스트: **559 통과** (Unit 1~14 완료)
- Unit 15: SKILL.md + README 완료
- Unit 16 (security_tests): 예정
- 개발 방법론: INCEPTION → CONSTRUCTION (aidlc-devflow 플러그인)
- 관련 이슈: [bluejayA/aidlc-devflow#41 (BL-031)](https://github.com/bluejayA/aidlc-devflow/issues/41)

---

## 설계 원칙

1. **생성만, 실제 배포는 하지 않음** — `push` / `apply`(dry-run 외) / cluster API 호출 0건. 생성·검증 경계가 명확.
2. **맥락 주석 필수** — 모든 보안 설정에 "왜 이 선택인지" 인라인 주석.
3. **설정 3계층** — **프로젝트 > 조직 > 내장 기본값** (앞이 우선, 뒤를 덮어씀). 프로젝트 설정이 조직 설정을 덮어쓰고, 조직 설정이 내장 기본값을 덮어씁니다.
4. **AIDLC 비종속** — aidlc-devflow 플러그인 없이 단독 사용 가능.
5. **한국어 우선** — 모든 사용자 대면 메시지 한국어 요약 + 원어 병기 (NFR-17).

---

## v0.1.0 제약

- JVM 스택만 (Kotlin + Java Spring Boot)
- `StatefulSet` 미지원 (Deployment만) — stateful 앱 감지 시 경고
- auto-fix 루프 미지원 (v0.2+) — 검증 실패 시 troubleshoot.md 안내 + 수동 수정
- PVC / NetworkPolicy / PDB 없음

## v0.2+ 로드맵

- Go / Python / React 스택 추가
- auto-fix 루프 (3회 자동 수정)
- StatefulSet + PVC 지원
- NetworkPolicy (zero-trust default deny)
- PodDisruptionBudget / topologySpreadConstraints
- Helm chart 생성

---

## 라이선스

MIT — see [LICENSE](LICENSE).
