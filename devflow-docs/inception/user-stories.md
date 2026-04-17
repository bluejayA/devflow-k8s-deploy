# User Stories

**Timestamp**: 2026-04-16T10:00:00+09:00
**Source**: devflow-docs/inception/requirements.md

## Actors

- **JVM 개발자**: Kotlin/Java Spring 백엔드 프로젝트를 Kubernetes에 배포하려는 개발자. 스킬의 주 사용자
- **조직 관리자**: 팀/조직 수준의 배포 표준(베이스 이미지, 보안 정책, 리소스 기본값)을 설정하는 엔지니어
- **CI/CD 파이프라인**: summary.json과 exit code를 소비하여 후속 자동화를 수행하는 외부 시스템
- **시스템**: 내부 기술 요구사항의 주체 (검증기, 확장성 구조, atomic write 등)

---

## Stories

### US-001: 배포 정보 구조적 수집
**Actor**: JVM 개발자 / AI-assisted 개발자
**Story**: As a 개발자(JVM 숙련도 무관), I want 앱명·포트·노출 방식·namespace 등 배포 정보를 **K8s 원어 없이 한국어로** 구조적으로 입력하고 싶다 so that 스킬이 정확한 K8s 아티팩트를 생성하면서도 비전문가도 이해할 수 있다
**Acceptance Criteria**:
- Given 스킬이 STEP 1을 시작할 때, When 사용자에게 입력을 요청하면, Then 앱명 / 노출 포트 / 노출 방식(ClusterIP|NodePort|LoadBalancer) / namespace / 출력 디렉토리 / 리소스 프로파일 힌트를 수집한다
- Given NodePort 또는 LoadBalancer를 선택했을 때, When 서비스 타입을 확정하면, Then 해당 타입의 제약사항(nodePort 명시 권장 / 클라우드 프로바이더 전제)을 안내한다
- Given 설정 파일에 값이 이미 있을 때, When STEP 1을 시작하면, Then 설정값을 기본값으로 제안하고 사용자 확인을 받는다
- Given STEP 1 질문 문구를 확인할 때, When K8s/Spring 원어(ClusterIP, namespace 등)가 포함되는 경우, Then 사용자 의도 기반 한국어 질문으로 번역되어 있다 (예: "노출 방식?" → "어디서 접속할 건가요?")
- Given 각 STEP 1 질문에서, When 사용자가 "? 도움말" 옵션을 선택하면, Then 1-2줄 설명(한국어 + 원어 병기)이 표시된 뒤 원 질문으로 복귀한다
- Given 용어 번역 매핑이 적용된 후, When rationale.md를 확인하면, Then 각 결정값의 원어(ClusterIP 등)가 함께 기록되어 감사 추적이 가능하다
**Priority**: Must
**Traces**: F-02, F-02a, F-02b, F-36

### US-002: JVM 프로젝트 자동 분석
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 프로젝트 디렉토리에서 빌드 시스템·런타임·진입점·포트를 자동 추론해주길 원한다 so that 수동 설정 없이 정확한 아티팩트를 생성할 수 있다
**Acceptance Criteria**:
- Given Gradle(KTS/Groovy) 또는 Maven 프로젝트일 때, When STEP 2가 실행되면, Then build.gradle.kts / build.gradle / pom.xml을 통해 빌드 시스템을 판별한다
- Given Spring Boot 프로젝트일 때, When 포트를 추론하면, Then 환경변수 SERVER_PORT → application-{profile}.yml → application.yml → 8080 우선순위로 결정한다
- Given 추론이 불가능한 항목이 있을 때, When STEP 2를 완료하면, Then 해당 항목에 대해 사용자에게 질문한다
- Given multi-module 프로젝트일 때, When settings.gradle(.kts) 또는 <modules> 블록을 감지하면, Then app.module 설정이 있으면 해당 모듈 사용, 없으면 사용자에게 모듈 선택 프롬프트 표시
**Priority**: Must
**Traces**: F-03, F-10, F-11, F-12, F-39

### US-003: Spring Boot 버전 기반 probe 자동 설정
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want Spring Boot 버전에 맞는 health probe가 자동으로 설정되길 원한다 so that 프로덕션에서 올바른 헬스체크가 동작한다
**Acceptance Criteria**:
- Given Spring Boot 3.x 프로젝트이고 actuator가 활성화되어 있을 때, When probe를 설정하면, Then /actuator/health/liveness + /actuator/health/readiness 분리 엔드포인트를 사용한다
- Given Spring Boot 2.x 프로젝트이고 actuator가 활성화되어 있을 때, When probe를 설정하면, Then /actuator/health 단일 엔드포인트를 사용한다
- Given actuator 미활성 또는 Boot 버전 미감지일 때, When probe를 설정하면, Then tcpSocket.port로 폴백한다
**Priority**: Must
**Traces**: F-13, F-14

### US-004: 보안 강화 multi-stage Dockerfile 생성
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 프로덕션 보안 체크리스트가 반영된 multi-stage Dockerfile을 자동 생성하고 싶다 so that 보안 취약점 없는 컨테이너 이미지를 빌드할 수 있다
**Acceptance Criteria**:
- Given JVM 프로젝트 분석이 완료되었을 때, When Dockerfile을 생성하면, Then builder(JDK) → runner(JRE-alpine) multi-stage 구조로 생성한다
- Given Dockerfile이 생성되었을 때, When 보안 지시어를 확인하면, Then 비root 사용자(USER appuser) + 명시적 태그(latest 금지) + "왜" 근거 주석이 포함되어 있다
- Given 기본 베이스 이미지를 사용할 때, When 설정 파일에 오버라이드가 없으면, Then eclipse-temurin:21-jre-alpine / eclipse-temurin:21-jdk-alpine을 사용한다
- Given 설정 파일에 base_images.jdk / base_images.jre가 지정되어 있을 때, When Dockerfile을 생성하면, Then 설정값으로 오버라이드한다
**Priority**: Must
**Traces**: F-20, F-21, F-22, F-23, F-24

### US-005: 보안 정책 적용 Deployment manifest 생성
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 프로덕션 보안 정책이 적용된 Deployment manifest를 자동 생성하고 싶다 so that 보안 감사를 통과하는 배포 설정을 얻을 수 있다
**Acceptance Criteria**:
- Given 아티팩트 생성 단계(STEP 3)에서, When Deployment를 생성하면, Then Pod securityContext(runAsNonRoot, runAsUser:1000, fsGroup:1000, seccompProfile:RuntimeDefault) + Container securityContext(allowPrivilegeEscalation:false, privileged:false, readOnlyRootFilesystem:true, capabilities.drop:[ALL])가 포함된다
- Given readOnlyRootFilesystem이 true일 때, When JVM 앱의 /tmp 쓰기가 필요하면, Then emptyDir 볼륨을 /tmp에 마운트한다
- Given 리소스를 설정할 때, When 기본값을 사용하면, Then requests.memory:512Mi, limits.memory:1Gi 등 cpu/memory 모두 명시한다
- Given Deployment가 생성되었을 때, When 보안·리소스·위험 필드를 확인하면, Then 해당 필드에 근거 주석이 포함되어 있다
- Given automountServiceAccountToken 설정 시, When Deployment를 확인하면, Then automountServiceAccountToken: false가 명시되어 있다
**Priority**: Must
**Traces**: F-30, F-31, F-32, F-33, F-34, F-37

### US-006: Service 및 ServiceAccount 생성
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 앱에 맞는 Service와 전용 ServiceAccount를 자동 생성하고 싶다 so that 최소 권한 원칙으로 네트워크를 노출할 수 있다
**Acceptance Criteria**:
- Given Service를 생성할 때, When type/selector/ports를 설정하면, Then targetPort는 container port와 일치하고, type은 STEP 1에서 수집한 값(기본 ClusterIP)을 따른다
- Given ServiceAccount를 생성할 때, When 전용 SA를 만들면, Then default SA를 사용하지 않고, automountServiceAccountToken: false를 명시한다
- Given Deployment가 SA를 참조할 때, When serviceAccountName 필드를 확인하면, Then 생성된 전용 SA 이름과 일치한다
**Priority**: Must
**Traces**: F-35, F-36

### US-007: validate_k8s.py 정적 검증
**Actor**: 시스템
**Story**: As a 시스템, I want 생성된 manifest를 Rule ID 기반으로 정적 검증하고 싶다 so that 보안·리소스·서비스 규칙 위반을 배포 전에 잡을 수 있다
**Acceptance Criteria**:
- Given validate_k8s.py가 실행될 때, When manifest YAML을 검사하면, Then SEC-001~SEC-009 / RES-001 / IMG-001 / SA-001~SA-002 / SVC-001~SVC-002 / PRB-001~PRB-002 전체 규칙을 체크한다
- Given 검증 결과에 따라, When exit code를 반환하면, Then 0(all PASS) / 1(FAIL 존재) / 2(WARN만 = soft-success)를 사용한다
- Given containers와 initContainers가 있을 때, When 체크 함수를 실행하면, Then 두 리스트 모두 순회한다
- Given 실패 메시지를 출력할 때, When 포맷을 확인하면, Then "[LEVEL] rule_id container_name: 설명 → 수정 제안" 형식이다
- Given env[].value에 시크릿 패턴(password, secret, token 등)이 있을 때, When SEC-009를 체크하면, Then FAIL + valueFrom.secretKeyRef 사용 권장 안내를 출력한다
**Priority**: Must
**Traces**: F-40, F-41, F-42, F-43, F-44, F-46, F-46a

### US-008: kubectl dry-run 검증
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 생성된 manifest가 kubectl dry-run으로 검증되길 원한다 so that K8s API 서버 구문 오류를 사전에 확인할 수 있다
**Acceptance Criteria**:
- Given validate_k8s.py가 통과한 후, When kubectl이 설치되어 있으면, Then kubectl apply --dry-run=client -f k8s-output/를 실행한다
- Given kubectl이 미설치일 때, When dry-run 단계에 도달하면, Then 경고 출력 + rationale.md에 "kubectl 미감지 — dry-run 생략" 기록 후 계속 진행한다
**Priority**: Must
**Traces**: F-05, F-51, F-56

### US-009: 검증 실패 자동 수정 루프 + 비개발자 친화 bail-out
**Actor**: 시스템 / JVM 개발자 / AI-assisted 개발자
**Story**: As a 시스템 + 사용자, I want 검증 실패 시 자동으로 수정을 시도하고, 실패하면 비개발자도 다음 행동을 알 수 있는 한국어 요약을 받고 싶다 so that 대부분의 문제는 자동 해결되고, 막히는 경우에도 원어 로그를 읽지 않아도 된다
**Acceptance Criteria**:
- Given validate_k8s.py 또는 kubectl dry-run이 실패할 때, When 자동 수정 루프에 진입하면, Then 수정안 생성 → 재검증을 최대 3회 반복한다
- Given 3회 시도 후에도 실패할 때, When bail-out하면, Then 현재 상태 보존 + k8s-output/troubleshoot.md에 전체 시도 로그 저장 + 사용자에게 수동 개입 요청
- Given troubleshoot.md를 생성할 때, When 상단 섹션을 확인하면, Then "어느 STEP / 어느 컴포넌트 / 무슨 이유로 실패" 한국어 1-2줄 요약이 포함되어 있다
- Given 실패 메시지를 출력할 때, When 사용자 대면 텍스트를 확인하면, Then 한국어 요약 + 원문(영문) 병기 형식이다 (NFR-17 정책)
**Priority**: Must
**Traces**: F-50, F-51, F-52, NFR-17

### US-010: 3계층 설정 관리
**Actor**: 조직 관리자
**Story**: As a 조직 관리자, I want 조직 수준의 배포 표준(베이스 이미지, 보안 정책, 리소스)을 설정하고 싶다 so that 팀 전체가 일관된 배포 기준을 따를 수 있다
**Acceptance Criteria**:
- Given 설정을 로드할 때, When 프로젝트(.devflow-k8s-deploy.yml) + 조직(~/.claude/devflow-k8s-deploy.yml) + 기본값이 존재하면, Then 프로젝트 > 조직 > 기본값 우선순위로 병합한다
- Given 설정 스키마를 확인할 때, When 필수 필드를 검증하면, Then version, stack, app.name, app.port, image.*, service.*, resources.*, security.*, namespace, output.*, build.*, base_images.* 필드가 지원된다
- Given rationale.md를 생성할 때, When 각 최종값을 기록하면, Then 어느 계층에서 온 값인지 명시한다 (예: namespace: prod-svc (source: project config))
- Given YAML 파싱이 실패할 때, When 설정을 로드하면, Then 상세 에러 메시지 출력 + rationale.md에 기록 + 기본값으로 진행한다
**Priority**: Must
**Traces**: F-60, F-61, F-62, F-63

### US-011: 안전한 namespace 결정
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want namespace가 안전하게 결정되길 원한다 so that 실수로 default namespace에 배포하는 것을 방지할 수 있다
**Acceptance Criteria**:
- Given namespace를 결정할 때, When 조회 순서를 따르면, Then 프로젝트 설정 → 조직 설정 → STEP 1 사용자 입력 → 프로젝트 디렉토리명 기반 기본값 제안 순서로 적용한다
- Given namespace가 명시되지 않았을 때, When 기본값을 제안하면, Then "default"를 자동 배정하지 않고 사용자가 명시적으로 선택해야만 허용한다
**Priority**: Must
**Traces**: F-70, F-71

### US-012: 출력 패키징 및 리포트 생성
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 생성물과 판단 근거가 단일 디렉토리에 패키징되길 원한다 so that 팀 리뷰와 감사 추적이 용이하다
**Acceptance Criteria**:
- Given STEP 5가 실행될 때, When 출력 파일을 패키징하면, Then k8s-output/에 Dockerfile, deployment.yaml, service.yaml, serviceaccount.yaml, rationale.md, summary.json이 생성된다
- Given summary.json을 생성할 때, When 스키마를 따르면, Then version/generated_at(UTC)/stack/app/images/namespace/validation/files 필드가 포함되며, **validation 객체에 `skipped: [string]` 필드를 포함하여 스킵된 검증(예: kubectl_dry_run, container_build)을 기계 판독 가능 형태로 노출**한다
- Given rationale.md를 생성할 때, When 섹션을 구성하면, Then 감지 스택 / 진입점 / 포트 / 상태성 / 베이스 이미지 / 리소스 / namespace / probe / 검증 결과 / 경고 목록 / **스킵된 검증 목록과 사유** 섹션이 포함된다
**Priority**: Must
**Traces**: F-06, F-80, F-81, F-82, F-83

### US-013: 스택 확장성 구조
**Actor**: 시스템
**Story**: As a 시스템, I want JVM 전용 로직이 구조적으로 분리되어 있길 원한다 so that v0.2(Go) / v0.3(Python) 추가 시 최소 비용으로 확장할 수 있다
**Acceptance Criteria**:
- Given Dockerfile 템플릿을 관리할 때, When 파일 위치를 확인하면, Then ${CLAUDE_PLUGIN_ROOT}/templates/dockerfile/{stack}.tmpl에 외부 파일로 존재한다 (v0.1.0은 jvm.tmpl)
- Given 스택별 추론 로직을 확인할 때, When 모듈 구조를 보면, Then ${CLAUDE_PLUGIN_ROOT}/scripts/stacks/{stack}.py로 분리되어 있고, StackModule 인터페이스 5 메서드(detect/build_plan/probe_plan/defaults/artifact_locator)를 구현한다
- Given SKILL.md 본문에서, When JVM 관련 로직을 검색하면, Then 하드코딩된 JVM 전용 로직이 0건이고 "scripts/stacks/{stack}.py 결과를 따른다"는 계약으로 서술되어 있다
- Given validate_k8s.py에서, When 스택 관련 판단을 검색하면, Then stack-agnostic으로 유지되어 있다 (스택 특화 로직 0건)
**Priority**: Must
**Traces**: F-90, F-91, F-92, F-93, F-94

### US-014: Atomic write로 출력 일관성 보장
**Actor**: 시스템
**Story**: As a 시스템, I want 파일 쓰기가 atomic하게 수행되길 원한다 so that 실패/중단 시에도 k8s-output/이 항상 일관된 완전한 세트를 유지한다
**Acceptance Criteria**:
- Given STEP 3~5에서 파일을 생성할 때, When 쓰기 작업을 수행하면, Then 임시 디렉토리(k8s-output/.tmp-{uuid}/)에 먼저 생성한다
- Given STEP 4 검증도 임시 디렉토리 대상으로 실행되고, When 전 단계가 통과하면, Then 임시 → k8s-output/으로 atomic rename한다
- Given 실패 또는 Ctrl+C가 발생할 때, When 정리 작업을 수행하면, Then 임시 디렉토리 삭제 + k8s-output/은 이전 상태 보존
**Priority**: Must
**Traces**: F-103

### US-015: 재실행 시 기존 출력 처리
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 재실행 시 기존 출력 파일의 처리 방식을 제어하고 싶다 so that 의도치 않은 덮어쓰기를 방지하거나 CI에서 자동 덮어쓰기를 할 수 있다
**Acceptance Criteria**:
- Given output.on_exists가 "prompt"(기본)일 때, When k8s-output/이 이미 존재하면, Then 사용자에게 덮어쓰기 여부를 질문한다
- Given output.on_exists가 "overwrite"일 때, When k8s-output/이 이미 존재하면, Then 조용히 덮어쓰기한다
- Given output.on_exists가 "suffix"일 때, When k8s-output/이 이미 존재하면, Then 타임스탬프 접미사 새 디렉토리(k8s-output-YYYY-MM-DDTHH-MM/)를 생성한다
**Priority**: Must
**Traces**: F-100

### US-016: SKILL.md 5-STEP 파이프라인 구조
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 스킬이 명확한 5단계 파이프라인으로 실행되길 원한다 so that 각 단계의 진행 상황과 결과를 이해할 수 있다
**Acceptance Criteria**:
- Given 스킬을 실행할 때, When 파이프라인을 따르면, Then (1)입력 수집 → (2)코드 분석 → (3)아티팩트 생성 → (4)검증 게이트 → (5)결과 패키징 순서로 진행한다
- Given SKILL description을 확인할 때, When 언어를 검증하면, Then description은 한국어, body는 영어로 작성되어 있다
- Given 자연어 트리거를 테스트할 때, When 다양한 발화를 시도하면, Then "배포 준비", "Dockerfile 만들어줘", "k8s manifest", "컨테이너화", "deploy this to cluster", "k8s에 올려줘" 등 6가지 이상 패턴에서 활성화된다
**Priority**: Must
**Traces**: F-01, F-07, F-08

### US-017: CI/CD 파이프라인 연동 계약
**Actor**: CI/CD 파이프라인 / CI 엔지니어
**Story**: As a CI/CD 파이프라인 + CI 엔지니어, I want summary.json 스키마와 exit code 계약이 안정적이고, set -e 환경에서도 안전하게 호출 가능하길 원한다 so that 자동화 파이프라인이 깨지지 않고 degraded success를 "전부 통과"로 오인하지 않는다
**Acceptance Criteria**:
- Given summary.json 스키마를 확인할 때, When v0.1.x 패치에서 변경이 있으면, Then 필드 제거/타입 변경 없이 하위호환을 유지한다
- Given exit code를 소비할 때, When 결과를 판단하면, Then 0=성공, 1=실패, 2=경고만(soft-success, continue 처리)으로 해석한다
- Given README와 summary.json 스펙 문서를 확인할 때, When exit code 2 처리 가이드를 찾으면, Then 쉘 호출 예제(`&& [ $? -le 2 ]` 또는 `\|\| [ $? -eq 2 ]`)와 set -e 호환 경고가 명시되어 있다
- Given --json 플래그로 실행할 때, When validate_k8s.py 결과를 확인하면, Then summary.json에 포함 가능한 JSON 형태로 stdout에 출력한다
- Given degraded success(kubectl 또는 빌드 엔진 미감지)가 발생할 때, When summary.json을 확인하면, Then validation.skipped 배열에 스킵된 검증 식별자가 기록되어 CI가 "전부 통과"로 오인하지 못한다
**Priority**: Must
**Traces**: F-42, F-47, F-56, F-58, F-83, F-101, NFR-06, NFR-PLG-02

### US-018: Container image build (opt-in)
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want 생성된 Dockerfile로 컨테이너 이미지를 빌드할 수 있는 옵션을 원한다 so that 로컬에서 이미지를 확인할 수 있다
**Acceptance Criteria**:
- Given build.engine가 "skip"(기본)일 때, When STEP 4를 실행하면, Then 빌드 단계 전체를 생략한다
- Given build.engine가 "auto"일 때, When 빌드 엔진을 감지하면, Then docker → podman → nerdctl 순서로 시도한다
- Given 세 엔진 모두 미감지일 때, When 빌드를 시도하면, Then 경고 출력 + rationale.md에 기록 + 빌드 단계 생략 (graceful degrade)
- Given build.build_timeout_seconds(기본 600)가 초과될 때, When 빌드가 타임아웃하면, Then 빌드 실패로 처리 → 자동 수정 루프 진입
**Priority**: Should
**Traces**: F-53, F-54, F-57, F-58, F-102

### US-019: 비-Spring JVM 앱 지원
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want Ktor/Micronaut 등 비-Spring JVM 앱도 지원되길 원한다 so that Spring 이외 프레임워크에서도 스킬을 사용할 수 있다
**Acceptance Criteria**:
- Given 비-Spring JVM 앱을 감지했을 때, When probe를 설정하면, Then Spring 특화 probe를 사용하지 않고 TCP socket 폴백을 적용한다
- Given 비-Spring 앱의 probe를 설정한 후, When 사용자에게 알리면, Then probe 설정 확인 질문을 표시한다
**Priority**: Should
**Traces**: F-16

### US-020: Gradle/Maven 빌드 캐시 최적화
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want Dockerfile의 빌드 캐시가 최적화되길 원한다 so that 재빌드 시간을 단축할 수 있다
**Acceptance Criteria**:
- Given multi-stage Dockerfile을 생성할 때, When 레이어 순서를 확인하면, Then 의존성 다운로드 레이어가 소스 코드 레이어보다 먼저 배치되어 있다
**Priority**: Should
**Traces**: F-25

### US-021: Stateful 앱 감지 경고
**Actor**: JVM 개발자
**Story**: As a JVM 개발자, I want Stateful 앱 시그널이 감지되면 경고를 받고 싶다 so that 잘못된 Deployment 사용을 인지할 수 있다
**Acceptance Criteria**:
- Given DB 연결 / 파일 쓰기 / PVC 필요 시그널을 감지했을 때, When 경고를 출력하면, Then rationale.md에 "상태성 미지원 — v0.2+ 대응 예정" 기록 + Deployment는 그대로 생성한다
**Priority**: Should
**Traces**: F-38

### US-022: WARN 레벨 검증 규칙
**Actor**: 시스템
**Story**: As a 시스템, I want FAIL 외에 WARN 수준의 검증 규칙도 제공하고 싶다 so that 권장 사항을 안내할 수 있다
**Acceptance Criteria**:
- Given manifest를 검증할 때, When requests:limits 비율이 4배를 초과하면, Then RES-W01 WARN을 출력한다
- Given 이미지 태그를 검증할 때, When digest pinning이 미사용이면, Then IMG-W01 WARN을 출력한다
**Priority**: Could
**Traces**: F-45

---

## Technical Requirements (스토리 미변환)

다음 요구사항은 사용자 가치보다 기술 제약에 가까워 별도 기록한다:

| ID | 설명 | Traces |
|---|---|---|
| TR-01 | 하드코딩 경로 0건, ${CLAUDE_PLUGIN_ROOT} 사용, SKILL.md에 version: 0.1.0 semver 헤더 | NFR-05 |
| TR-02 | pytest 커버리지: validate_k8s.py ≥ 85%, 스택 추론 모듈 ≥ 75% | NFR-13 |
| TR-03 | 동일 프로젝트+동일 설정 재실행 시 Dockerfile + manifest YAML byte-identical (타임스탬프 제외) | NFR-02 |
| TR-04 | 컨테이너 push / kubectl apply(dry-run 외) / cluster API 호출 0건 | NFR-03 |
| TR-05 | 허용 외부 호출: 컨테이너 레지스트리 + 선언된 의존성 레포지토리만. 그 외 네트워크 호출 없음 | NFR-04 |
| TR-06 | 생성 파일 주석 한국어, 에러 메시지 한국어 우선 + 영문 병기, summary.json generated_at UTC 고정 | NFR-17 |
| TR-07 | CI 실행 10회 연속 성공률 100% (flaky 0) | NFR-14 |
| TR-08 | 생성된 manifest에 평문 시크릿 포함 금지 | NFR-15 |

---

## Change Log

- 2026-04-16T10:00:00+09:00 — 최초 생성. 22개 스토리 (Must: 17, Should: 4, Could: 1) + 기술 요구사항 8건
- 2026-04-17 — US-001 확장: 비개발자/AI-assisted 개발자 사용성 반영 (F-02a 용어 번역 + F-02b 도움말). Actor 범위 확장 "JVM 개발자 / AI-assisted 개발자".
- 2026-04-17 (3-페르소나 + Codex 리뷰 반영) — US-009 확장(troubleshoot.md 한국어 요약, NFR-17 메시지 정책 트레이스), US-012 확장(summary.json validation.skipped 필드 + rationale.md 스킵 섹션), US-017 확장(exit code 2 소비자 가이드 + degraded skipped 계약, Actor에 CI 엔지니어 추가).
