# devflow-k8s-deploy

JVM 프로젝트를 Kubernetes 배포용 Dockerfile + manifest로 자동 생성하는 Claude Code 플러그인.

**v0.4.0** — StatefulSet/PVC + NetworkPolicy zero-trust 지원. 클러스터 preset 구조 도입.

![version](https://img.shields.io/badge/version-0.4.0-blue)
![release](https://img.shields.io/badge/release-v0.4.0-success)
![tests](https://img.shields.io/badge/tests-688_passed-green)
![status](https://img.shields.io/badge/status-released-success)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

> **⚠️ v0.1.0 사용자**: v0.1.0은 Dockerfile alpine 런타임 빌드 실패 + deployment.yaml **CrashLoopBackOff** 확정 결함이 있습니다. **v0.4.0 업그레이드 필수**. 아래 [v0.2.0 변경사항](#v020-변경사항) 참조.

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
| **3. 파일 생성** | Dockerfile + Dockerfile.dockerignore + deployment.yaml (또는 statefulset.yaml) + service.yaml + serviceaccount.yaml + networkpolicy.yaml (클러스터 설정 시) |
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
| JVM — Kotlin + Spring Boot 2.x/3.x | `build.gradle.kts` / `build.gradle` / `pom.xml` | v0.2.0 |
| Go | — | v0.3 예정 |
| Python | — | v0.4 예정 |
| React (nginx) | — | v0.5 예정 |

---

## 보안 기본값 (F-31 / F-32)

### Dockerfile

- multi-stage: 빌드 시스템별 도구 포함 builder → slim JRE runner
  - Gradle: `gradle:jdk21-alpine` (builder) → `eclipse-temurin:21-jre-alpine` (runner)
  - Maven: `maven:3.9-eclipse-temurin-21-alpine` (builder) → `eclipse-temurin:21-jre-alpine` (runner)
- 비root 사용자: busybox 호환 `addgroup/adduser appuser` + `USER appuser` (alpine 런타임 대응)
- `COPY --chown=appuser:appuser`
- `latest` 태그 금지 (F-23) — 명시 버전 또는 digest 필수. OCI regex allowlist로 개행/인젝션 방어
- Gradle/Maven 의존성 레이어 최적화 (캐시 레이어 분리)
- Gradle Version Catalog(`gradle/libs.versions.toml`) + convention plugins 자동 감지 (v0.2.0)
- `Dockerfile.dockerignore` 동반 생성 — `.git`, `build/`, `k8s-output/`, `.env*` 등 context pollution 방어
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

cluster:
  preset: orbstack       # orbstack: local-path StorageClass + Cilium NetworkPolicy
  # storage_class: my-custom-storage  # preset 기본값 override
  # network_policy: false              # NetworkPolicy 생성 스킵 (+ NET-W01 WARN)
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

### GitHub Release (권장)
```bash
# 특정 버전 체크아웃
git clone --branch v0.4.0 https://github.com/bluejayA/devflow-k8s-deploy.git
cd devflow-k8s-deploy
uv sync

# 또는 GitHub Release에서 source 다운로드
gh release download v0.4.0 -R bluejayA/devflow-k8s-deploy
```

### Claude Code 플러그인 (devflow-marketplace)
```bash
/plugin marketplace add bluejayA/devflow-marketplace
/plugin install devflow-k8s-deploy@devflow-marketplace
```

### 개발/로컬 사용
```bash
git clone https://github.com/bluejayA/devflow-k8s-deploy
cd devflow-k8s-deploy
uv sync --all-extras
uv run pytest -v              # 688 tests
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

---

## 개발 상태

**v0.4.0 Released (2026-04-22)** 🎉 · [v0.2.0](https://github.com/bluejayA/devflow-k8s-deploy/releases/tag/v0.2.0) · [v0.1.0](https://github.com/bluejayA/devflow-k8s-deploy/releases/tag/v0.1.0)

- 전체 테스트: **688 통과** / ruff / mypy strict clean
- v0.4.0: StatefulSet/PVC + NetworkPolicy zero-trust + ClusterConfig preset (Codex 외부 리뷰 3건 반영)
- v0.3.0: replicas 설정화 + LIFE-W01/IMG-W02 WARN 규칙 + validators 패키지 모듈화
- v0.2.0: v0.1.0의 런타임 배포 결함 6건 수정 + Codex 외부 리뷰 P1/P2 반영
- v0.1.0: 16 units × 3-Stage 리뷰 + E2E CLI smoke 통과 ([여정 요약](devflow-docs/release/v0.1.0-release-notes.md))
- 개발 방법론: INCEPTION → CONSTRUCTION (aidlc-devflow 플러그인)

---

## 설계 원칙

1. **생성만, 실제 배포는 하지 않음** — `push` / `apply`(dry-run 외) / cluster API 호출 0건. 생성·검증 경계가 명확.
2. **맥락 주석 필수** — 모든 보안 설정에 "왜 이 선택인지" 인라인 주석.
3. **설정 3계층** — **프로젝트 > 조직 > 내장 기본값** (앞이 우선, 뒤를 덮어씀). 프로젝트 설정이 조직 설정을 덮어쓰고, 조직 설정이 내장 기본값을 덮어씁니다.
4. **AIDLC 비종속** — aidlc-devflow 플러그인 없이 단독 사용 가능.
5. **한국어 우선** — 모든 사용자 대면 메시지 한국어 요약 + 원어 병기 (NFR-17).

---

## v0.4.0 변경사항

### 신규 기능

- **StatefulSet + PVC 지원** (BL-003): `stateful: high` 감지 시 `statefulset.yaml` 자동 생성
  - `volumeClaimTemplates` 포함 PVC 설정 — StorageClass는 cluster preset 기반
  - liveness/readinessProbe 자동 포함
  - STS-W01: volumeClaimTemplates 미설정 시 WARN
- **NetworkPolicy zero-trust** (BL-004): `networkpolicy.yaml` 자동 생성
  - default deny-all ingress/egress + CoreDNS egress(kube-system:53) 자동 허용
  - `cluster.network_policy: false` 시 생성 스킵 + NET-W01 WARN (로컬 테스트용)
- **ClusterConfig / preset 구조** 도입
  - `cluster.preset: orbstack` → `storageClassName: local-path`, NetworkPolicy 활성
  - preset 미설정 시 orbstack fallback 또는 인터랙티브 선택
  - `storage_class`, `network_policy` 직접 override 가능

### Codex 외부 리뷰 반영 (P1/P2)

- `generate_statefulset()` placeholder 이미지 제거 — `build.image_tag` 연결
- `cluster: <string>` scalar 설정 AttributeError 방어 (`isinstance(dict)` guard)
- `summary.json` generated_files 동적 생성 — statefulset.yaml/networkpolicy.yaml 반영

---

## v0.3.0 변경사항

- **replicas 설정화**: `.devflow-k8s-deploy.yml`의 `replicas` 필드로 제어 가능
- **LIFE-W01**: liveness probe 미설정 시 WARN
- **IMG-W02**: image digest pinning 미설정 시 WARN
- **validators 패키지 모듈화**: `validate_k8s.py` 단일 파일 → `validators/rules/` 규칙별 분리

---

## v0.2.0 변경사항

v0.1.0 샘플 배포 검증 중 발견된 **6건의 런타임 결함**을 수정. v0.1.0 Dockerfile은 `docker build` 시점에, 생성된 deployment.yaml은 `kubectl apply` 시점에 실패했기에 **긴급 패치**.

### Critical fixes (docker build + k8s apply 시점 실패)
- **Dockerfile alpine 호환**: `groupadd`/`useradd` → `addgroup`/`adduser` (v0.1.0은 `groupadd: not found`로 즉시 실패)
- **Dockerfile wrapper 의존 제거**: 시스템 gradle 사용 (v0.1.0은 `gradle/` dir + `gradlew` 강제)
- **Dockerfile Version Catalog 지원**: `gradle/libs.versions.toml` 있으면 조건부 COPY (Codex P1-a)
- **Dockerfile multi-module 지원**: `COPY src ./src` 하드코딩 제거 → `COPY . .` + `Dockerfile.dockerignore` 동반 생성 (Codex P1-b)
- **deployment.yaml 앱 이미지 wiring**: `build.image_tag` 사용 (v0.1.0은 베이스 runner 이미지를 그대로 넣어 CrashLoopBackOff 확정)
- **deployment.yaml `imagePullPolicy: IfNotPresent`** 명시 + non-mutable tag 전제 주석 (Codex P2)

### UX / 정책 fixes
- **`resource_hint` 실반영**: `StackModule.defaults(resource_hint)` tier 매핑 — small(50m-500m, 256-512Mi) / medium(100m-1000m, 512Mi-1Gi) / large(250m-2000m, 1-2Gi). v0.1.0은 사용자 응답이 silent discard.
- **gradle `--no-daemon` + maven `-B`**: 컨테이너 빌드 효율/안전성

### Breaking changes (플러그인 API 직접 import 시)
- `StackModule.defaults()` → `defaults(resource_hint)` — 호출부에 인자 필요
- `ProjectAnalyzer.analyze(project_dir, config)` → `analyze(project_dir, config, resource_hint="medium")` — 기본값 있어 기존 호출 무변경도 OK

플러그인 최종 사용자(SKILL 호출)는 변경 불필요 — orchestrator가 자동 처리.

---

## v0.4.0 제약

- JVM 스택만 (Kotlin + Java Spring Boot)
- auto-fix 루프 미지원 (v0.5+) — 검증 실패 시 troubleshoot.md 안내 + 수동 수정
- PDB / topologySpreadConstraints 없음
- cluster preset: `orbstack`만 내장 (커스텀은 `storage_class` / `network_policy` 직접 지정)

## v0.5+ 로드맵

- Go / Python / React 스택 추가
- auto-fix 루프 (3회 자동 수정)
- PodDisruptionBudget / topologySpreadConstraints
- Helm chart 생성
- cluster preset 확장 (EKS, GKE, kind)

---

## 라이선스

MIT — see [LICENSE](LICENSE).
