# Brainstorming — v0.1.0 Scope

**Date**: 2026-04-15
**Phase**: INCEPTION
**Complexity**: Standard
**Project**: bluejayA/devflow-k8s-deploy
**Related**: GitHub issue #1 (backlog)

---

## 목적

v0.1.0 출시 범위 및 설계 축을 확정한다. 이 문서는 브레인스토밍 결정 이력 + 대안 + 근거를 담아 이후 requirements-analysis / application-design / CONSTRUCTION의 기준점이 된다.

## 인풋

1. **백로그 (GitHub issue #1)** — MVP 범위, 설계 원칙 5가지, 3계층 설정, 지원 스택(Node/Python/Kotlin + React), 보안 체크리스트, 검증(dry-run + docker build), trivy/hadolint 안내
2. **제3자 초기 구현 샘플**
   - `devflow-docs/inception/references/SKILL.md` — 8 STEP 파이프라인 (배포까지 포함 — 백로그 원칙 1 위반)
   - `devflow-docs/inception/references/validate_k8s.py` — 5개 결정론적 체크 (initContainer·readOnlyRootFilesystem·capabilities·Service 등 drift 존재)
3. **Codex 독립 리뷰** — 위 샘플을 기반으로 독립적으로 v0.1.0 설계안 작성

---

## 설계 원칙 (백로그에서 유지)

1. **생성만, 배포는 하지 않음** — 보안 경계 명확
2. **인라인 "왜" 주석** — 모든 보안 설정에 근거 주석 (구체 정책은 축 10에서 정제)
3. **3계층 설정** — 스킬 기본값 → `~/.claude/devflow-k8s-deploy.yml` → `.devflow-k8s-deploy.yml`
4. **AIDLC 비종속** — 독립 스킬, 조직 표준 도구 재활용 전제
5. **단일 SKILL.md 시작** — semver + 출력 계약 고정 → 승격 시 호환성 비용 최소화

---

## 축별 결정

### 축 1. 구조 — 단일 스킬 + 내부 5 STEP

**결정**: 단일 SKILL.md로 시작. 내부적으로 5 STEP의 경계 명시하여 v0.2+ 분리 시 비용 최소화.

**STEP 구조 (Codex 안 수용)**:
1. 입력 수집 — 앱명/포트/노출 방식/namespace/출력 경로 (축 12)
2. 코드 분석 — 런타임/진입점/포트/상태성 추론, 불확실 시 질문
3. 아티팩트 생성 — Dockerfile + Deployment + Service
4. 검증 게이트 — validate_k8s.py + `kubectl apply --dry-run=client`, 실패 시 자동 수정 루프
5. 결과 패키징 — `k8s-output/`에 파일 + 근거 리포트 (축 11·13)

**대안 (각각 기각)**:
- 3-tier 분리 (`containerize` / `k8s-manifest` / `k8s-deploy`): 방향성은 타당하나 v0.1.0 범위 과대. 플러그인 3개·설정 파일 3개·출력 계약 3개가 생김.
- 단일 스킬 + 내부 분기 없음: 나중에 분리할 때 리팩토링 비용 큼.

### 축 2. 경계 — 생성 + 검증 + dry-run=client + docker build(옵션)

**결정**: v0.1.0은 아래까지만 수행.
- Dockerfile + Deployment + Service 생성
- validate_k8s.py 정적 검증
- `kubectl apply --dry-run=client` (kubectl 바이너리만 있으면 됨, 클러스터 연결 불필요)
- `docker build` **옵션 실행** — Docker 데몬 감지 시만, 없으면 경고 후 스킵

**제외**: `docker push`, 실제 `kubectl apply`, rollout 확인 → v0.2+ 또는 별도 스킬

**대안**:
- 샘플 그대로 (push + 실제 apply까지): 백로그 원칙 1 위반 → 기각
- Codex 안 (docker build·dry-run=client 모두 제외): 백로그 MVP 4번에 `docker build 테스트` 명시됨. `--dry-run=client`는 클러스터 의존 없음 (Codex가 `--dry-run=server`와 혼동한 듯) → 둘 다 포함 유지

### 축 3. 검증기 — Rule ID 표준화 + SKILL.md와 1:1 매핑

**결정**: `validate_k8s.py`를 SKILL.md의 모든 "필수" 규칙과 1:1 매핑하여 보강.

**추가 체크 항목**:
- initContainers 전체 함수 적용 (현재는 `check_no_latest_tag`만)
- `readOnlyRootFilesystem`, `capabilities.drop: [ALL]`
- `seccompProfile: RuntimeDefault`
- `automountServiceAccountToken: false` + 전용 ServiceAccount
- `runAsUser > 0`, `fsGroup` 확인
- liveness·readiness probe 존재
- Service 존재 + `targetPort` ↔ container port 일치
- `runAsNonRoot` (기존 유지)

**개선**:
- **Rule ID 표준화** (Codex 안 수용): `SEC-001`, `SEC-002`, `RES-001`, `SVC-001` 같은 고정 ID. 변경 추적·CI 리포트·드리프트 감지 가능.
- **3단계 exit code**: PASS / WARN / FAIL (기존은 binary). WARN 예: requests:limits 비율 과도 등.
- **경로**: `${CLAUDE_PLUGIN_ROOT}/scripts/validate_k8s.py` — 샘플의 하드코딩 `~/skills/k8s-deploy/` 제거.

### 축 4. 리소스 타입 — Deployment + Service만

**결정**: v0.1.0은 Deployment + Service만. StatefulSet / CronJob / DaemonSet는 v0.2+.

**이유**: Stateful 앱은 PVC·헤드리스 Service·볼륨 등 완전히 다른 설계 축이 필요. MVP에 끼우면 범위 2배.

**v0.1.0 행동**: Stateful 앱 감지(STEP 2) 시 경고 출력 + 향후 지원 예정 안내. Deployment는 그대로 생성하되 **"상태성 미지원 경고"를 근거 리포트에 명시**.

### 축 5. Namespace

**결정**: `default` 하드코딩 금지. 조회 순서:
1. 프로젝트 설정 `.devflow-k8s-deploy.yml`의 `namespace`
2. 조직 설정 `~/.claude/devflow-k8s-deploy.yml`의 `namespace`
3. 사용자 입력 (STEP 1)
4. 기본값: 프로젝트 디렉토리명 기반 제안 (예: `devflow-k8s-deploy-dev`)

### 축 6. Helm/Kustomize — raw YAML만

**결정**: v0.1.0은 raw YAML. Kustomize base/overlay는 v0.2+, Helm은 v0.3+.

**이유**: 환경 분리(dev/staging/prod)는 백로그 "향후 확장"에 명시. MVP는 단일 환경 manifest에 집중.

### 축 7. 지원 스택 — JVM 단독 (Kotlin + Java Spring)

**결정**: v0.1.0은 JVM 스택 단독. Kotlin과 Java Spring을 **한 스택**으로 다룸.

**Jay 실사용 우선순위**: Kotlin > Java Spring > Go > Python (프론트: React). **긴급성: 백엔드.**

**Kotlin + Java Spring을 "1 스택"으로 묶을 수 있는 근거**:
- 베이스 이미지 동일 (`eclipse-temurin:21-jre-alpine` 계열)
- 패키징 동일 (Executable JAR)
- 빌드 시스템: Gradle KTS(Kotlin) + Maven/Gradle(Java) — 둘 다 지원
- Spring Boot는 두 언어 공통 프레임워크
- probe 매핑 동일 (`/actuator/health/liveness`·`/readiness`)
- 포트 추론 동일 (`application.yml`의 `server.port`)

**Spring Boot 특화**:
- `application.yml`/`application.properties`에서 `server.port` 추출
- actuator 활성화 감지 → `/actuator/health/liveness`·`/readiness` probe 자동 매핑
- actuator 미활성 시 TCP socket probe로 폴백
- `application-{profile}.yml` 감지 → namespace·환경 힌트
- 리소스 기본값: `requests.memory: 512Mi` (JVM GC heap 고려)

**롤아웃 플랜**:
- v0.2: Go 추가 (scratch/distroless 런타임, 단일 바이너리)
- v0.3: Python 추가 (프레임워크 파편화 대응 필요)
- v0.4: React 추가 (프론트엔드 패턴 — multi-stage build → nginx)

**대안 기각 이유**:
- 안 A (Node.js + React): 긴급성이 백엔드 배포라는 Jay 발언과 불일치
- 안 B (Python 단독): 샘플 재활용은 쉬우나 실사용 4순위
- 안 C (4개 다): 개발 기간·검증 부담 과대, v0.1.0 품질 허들 못 넘음
- 안 D' (JVM + Go): 범위 1.5~2배. v0.1.0에 Go를 넣는 가치가 v0.2로 미루는 비용 대비 낮음

### 축 8. 에러 복구 — 3회 + bail-out

**결정**: STEP 3·4·5의 자동 수정 루프는 **최대 3회**. 초과 시 bail-out.

**Bail-out 동작**:
- 현재 상태(`k8s-output/`)를 그대로 보존
- 전체 시도 로그를 `k8s-output/troubleshoot.md`에 저장 (각 시도의 에러 메시지·수정안·검증 결과)
- 사용자에게 수동 개입 요청 메시지 출력

**이유**: 에이전트 무한 루프 방지 (Codex·제3자 분석 공통 지적).

### 축 9. Trigger — 한/영 하이브리드

**결정**: 
- SKILL.md `description`: 한국어 (넓은 자연어 매칭)
- SKILL.md 본문: 영어 (기술 스펙)
- 자연어 트리거 예시 확대: "배포 준비", "Dockerfile 만들어줘", "k8s manifest", "컨테이너화", "deploy this to cluster", "k8s에 올려줘", "Spring 앱 k8s로 띄워줘"

**근거**: 제3자 분석 — Progressive Disclosure 패턴. description은 LLM이 기본 트리거 판단하는 필드, body는 기술적으로 정확한 지침이 필요한 필드.

### 축 10. 주석 정책 — 위험 필드만 필수, 나머지 선택

**결정**: "모든 필드에 한국어 주석" 방침은 **노이즈**를 만듦. 개선:

**필수 "왜" 주석 대상**:
- securityContext 전체 (Pod + Container)
- resources (requests + limits)
- image (latest 금지 / digest 권장)
- ServiceAccount (automountServiceAccountToken 등)
- probes (liveness / readiness)

**선택 주석 대상**: selector, labels, ports 등 관례적 필드

**주석 내용 가이드**:
- 형식: "이 설정이 없으면 어떤 위험이 있는지"
- 구체성: "컨테이너 탈출 시 호스트 root 권한 획득 가능" 같은 실제 공격 벡터 명시

**근거**: Codex 독립 리뷰 — "모든 필드 주석 → 핵심 위험 필드만 근거 주석". 샘플 검증 실패 메시지의 "왜 위험한지" 포맷을 그대로 주석에 사용하여 일관성 확보.

### 축 11. 근거 리포트 — 산출물에 `rationale.md`·`summary.json` 포함

**결정**: `k8s-output/`에 manifest와 함께 2가지 리포트 산출:

**`rationale.md`** (사람용):
- 감지된 스택·진입점·포트·상태성
- 선택된 베이스 이미지 + 버전 + 근거
- 리소스 기본값 선택 근거 (Spring Boot GC heap 등)
- namespace 선택 근거 (설정 파일 / 사용자 입력 / 디렉토리명 기반)
- probe 선택 근거 (actuator 감지 / TCP 폴백)
- 검증 결과 요약 (PASS/WARN/FAIL 개수)
- 감지된 경고 (stateful 앱 등)

**`summary.json`** (프로그램용):
- 백로그의 "얇은 인터페이스" 충족
- 스키마: `version`, `stack`, `ports[]`, `images[]`, `namespace`, `validation: {pass, warn, fail}`, `files[]`
- AIDLC construction-orchestrator 연동 / CI 파이프라인 소비 목적

**근거**: Codex 독립 리뷰 — "변경/근거 요약 함께 저장". 감사·디버깅·사용자 검토 품질 향상.

### 축 12. 입력 수집 STEP 1 명시

**결정**: STEP 1에서 아래 항목을 **구조적으로 수집**:
- 앱 이름
- 노출 포트 (코드에서 추론 가능하면 추론, 아니면 질문)
- 노출 방식 (ClusterIP / NodePort / LoadBalancer)
- namespace (축 5 조회 순서 적용)
- 출력 디렉토리 (기본 `k8s-output/`)
- 리소스 프로파일 힌트 (일반 웹 / ML 추론 / 배치)

**근거**: Codex 독립 리뷰 — 샘플 SKILL.md는 STEP 1에 "코드베이스 분석"만 있고 입력 수집이 분산됨. 명시적 수집 STEP을 두면 사용자 개입 시점이 예측 가능.

### 축 13. 출력 디렉토리 — `k8s-output/` 단일

**결정**: 출력은 **단일 디렉토리** `k8s-output/` (프로젝트 루트 기준).

**샘플의 3단계(`/tmp → output_candidate → output`) 폐기**:
- v0.1.0은 배포 안 함 → "최종 배포됨" 상태 구분(`output/`) 불필요
- `/tmp` 경유는 사용자가 결과 보려면 복사 필요 → 바로 프로젝트 디렉토리에 생성
- 검증 실패 시 롤백은 git 또는 파일 교체로 처리

**`k8s-output/` 내부 구조**:
```
k8s-output/
├── Dockerfile
├── deployment.yaml
├── service.yaml
├── rationale.md         # 축 11
├── summary.json         # 축 11
└── troubleshoot.md      # 축 8 bail-out 시만
```

**`.devflow-k8s-deploy.yml`의 `output.dir` 설정으로 오버라이드 가능.**

---

## 확장성 제약 (v0.1.0 설계 시 필수 포함)

v0.2·v0.3·v0.4에서 스택 추가 비용을 낮추기 위해 v0.1.0에 아래 5가지를 **반드시** 반영:

1. **Dockerfile 템플릿은 외부 파일로 분리**
   - 경로: `${CLAUDE_PLUGIN_ROOT}/templates/dockerfile/jvm.tmpl`
   - v0.2에서 `go.tmpl`, v0.3에서 `python.tmpl` 추가만으로 확장 가능

2. **포트·probe·의존성 추론은 스택별 모듈로 분리**
   - 경로: `${CLAUDE_PLUGIN_ROOT}/scripts/stacks/jvm.py` (또는 동등 구조)
   - 라우터(`scripts/stacks/__init__.py`) + 스택별 구현 파일 N개
   - 입력: 프로젝트 디렉토리. 출력: 포트·진입점·프레임워크 힌트·리소스 프로파일 힌트

3. **설정 파일에 `stack` 필드 명시**
   - 값: `auto | jvm | go | python | react`
   - `auto`면 자동 감지, 명시면 강제 (감지 실패 대비책)

4. **SKILL.md 분기 지점 명시**
   - STEP 2 코드 분석은 `scripts/stacks/{stack}.py` 결과를 따른다 — 하드코딩 금지
   - JVM 전용 로직이 SKILL.md 본문에 섞이지 않도록 계약 유지

5. **검증기(`validate_k8s.py`)는 stack-agnostic 유지**
   - manifest 검사만 수행, 스택 판단 없음
   - 새 스택 추가 시 검증기 수정 불필요

**미준수 시 비용**: v0.2·v0.3에서 스택 추가 작업량이 신규 + 리팩토링으로 2배 가중.

---

## v0.1.0 범위 요약

### 포함

- JVM 단일 스택 (Kotlin + Java Spring)
- Spring Boot 특화 (actuator probe, application.yml 포트 추론)
- SKILL.md 5 STEP 구조 + hybrid description/body 언어
- Dockerfile (multi-stage: JDK+gradle/maven → JRE-alpine + 비root)
- Deployment + Service manifest
- 보안 체크리스트 전부 (securityContext + SA + probes + no-latest)
- validate_k8s.py (Rule ID 표준화, SKILL.md 1:1 매핑, 3단계 exit code)
- `kubectl apply --dry-run=client` 검증
- `docker build` 옵션 실행 (Docker 데몬 감지 시)
- 3계층 설정 파일 (스킬 기본값 → `~/.claude/` → 프로젝트 `.yml`)
- `k8s-output/` 단일 출력 + `rationale.md` + `summary.json`
- 에러 복구 3회 + bail-out + `troubleshoot.md`
- 확장성 제약 5가지 구조적으로 반영
- trivy/hadolint 안내 (실행 명령 안내만, 자동 실행 없음)

### 제외 (향후 버전)

| 항목 | 버전 | 비고 |
|---|---|---|
| docker push / 실제 kubectl apply | v0.2 또는 별도 스킬 | 백로그 원칙 1 유지 |
| Go 백엔드 | v0.2 | 단일 바이너리, scratch/distroless |
| StatefulSet / CronJob / DaemonSet | v0.2 | 새 리소스 유형 |
| Kustomize base/overlay | v0.2 | 환경 분리 |
| Python 백엔드 | v0.3 | 프레임워크 파편화 |
| Helm chart | v0.3 | 패키징 전환 |
| React 프론트엔드 | v0.4 | multi-stage build → nginx |
| CI/CD 파이프라인 생성 | v0.4+ | GitHub Actions |
| HPA, Ingress, NetworkPolicy, Secret | v0.5+ | 추가 리소스 |
| PodDisruptionBudget | v0.5+ | 가용성 |
| `kubectl apply --dry-run=server` | MCP 서버 연동 시 | 클러스터 의존 |
| 실제 샌드박스 배포 + smoke test | 승격 후 별도 스킬 | 보안 경계 분리 |

---

## 리스크 Top 3 (출시 후 후회 가능성)

1. **정책-검증 drift**: SKILL.md가 요구하는 규칙과 validate_k8s.py 체크 범위 불일치. 문서엔 필수인데 검증이 안 잡아 "통과했는데 취약" 상태. → **축 3 Rule ID + 1:1 매핑 강제**로 대응.

2. **설정 스키마·우선순위 불명확**: 팀/프로젝트마다 서로 다른 결과가 재현되어 디버깅 비용 급증. → **축 5·13 조회 순서 명시 + `rationale.md`에 "어느 계층에서 어떤 값이 적용됐는지" 기록**으로 대응.

3. **확장성 미준수로 v0.2가 리팩토링 지옥**: v0.1.0이 JVM 하드코딩되면 Go 추가 시 신규 + 리팩토링이 맞물려 v0.2 기간 2배. → **확장성 제약 5가지를 requirements.md·application-design.md에 Acceptance Criteria로 승격**하여 구현 시 강제.

---

## Codex 독립 리뷰 원문 요약

Codex는 위 인풋 3종 중 2종(샘플 2파일)만 기반으로 독립 설계 작성 (GitHub API 접근 실패로 백로그는 미반영). 그럼에도 주요 결론이 수렴:

- **경계**: "생성 + 검증기 + output_candidate"만 (apply/push/dry-run 모두 제외) — dry-run=client는 포함 재논의 후 유지로 결정
- **STEP 구조**: 5 STEP (입력 수집 / 분석 / 생성 / 검증 / 패키징) — 채택
- **검증기 보강**: Rule ID, Service 검증, runAsUser/fsGroup 추가 — 채택
- **설정 스키마 초안**: version/app/image/service/resources/security/output 필드 — requirements-analysis에서 구체화
- **주석 정책**: 위험 필드만 근거 주석 — 채택 (축 10)
- **근거 리포트**: `output_candidate/`에 변경·근거 요약 저장 — 채택 (축 11)
- **리스크 Top 3**: 정책-검증 drift / 과도한 실행 범위 / 설정 우선순위 불명확 — 반영

Codex 독립 안 전문은 세션 기록에 보존. 이 문서의 축별 결정에 직·간접 반영됨.

---

## 다음 단계

1. 이 문서를 인풋으로 **requirements-analysis** 스테이지 진입
2. 위 결정을 사용자 중심 요구사항·Acceptance Criteria로 변환
3. 확장성 제약 5가지를 명시적 요구사항으로 승격
4. 3계층 설정 YAML 스키마를 정식 문서화 대상으로 지정
