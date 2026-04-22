# 도움말 카탈로그 (F-02b, HelpCatalog)

"?" 입력 시 해당 term_id의 `ko_detail`을 표시합니다. SKILL.md의 단일 출처입니다.

| term_id | ko_short | ko_detail | 원어 | 예시 | step |
|---------|---------|-----------|------|------|------|
| app_name | 앱 이름은 뭘로 할까요? | 앱 이름은 쿠버네티스에서 이 앱을 식별하는 라벨이에요. 보통 프로젝트 이름과 같게 짓고, 영문 소문자/숫자/하이픈만 사용합니다. | `Deployment.metadata.name` + `Service.metadata.name` + `ServiceAccount.metadata.name` | `my-api-service` / `order-backend` | 1 |
| port | 앱이 어떤 포트를 쓰나요? | 앱이 요청을 받는 네트워크 포트예요. Spring Boot는 보통 8080입니다. `application.yml`에 `server.port`가 적혀 있으면 그 값을 쓰세요. | `Container port + Service.spec.ports[].targetPort` | `8080` (Spring Boot 기본) / `9000` (커스텀) | 1 |
| exposure | 어디서 접속할 건가요? | 앱을 어떤 범위에서 접속 가능하게 할지 결정해요. (a) ClusterIP: 사내 전용 (b) LoadBalancer: 외부 인터넷, 클라우드 비용 월 $20+ (c) NodePort: 노드 포트 직접 노출 | `Service.spec.type — ClusterIP / NodePort / LoadBalancer` | `백엔드 API: ClusterIP` / `모바일 공개: LoadBalancer` | 1 |
| namespace | 네임스페이스는 뭘로 할까요? | 네임스페이스는 쿠버네티스에서 앱들을 분류하는 폴더 같은 개념이에요. 보통 프로젝트나 팀 이름을 씁니다. 'default'는 사고 방지를 위해 자동 배정되지 않아요. | `Kubernetes Namespace — 리소스 격리 + RBAC 경계` | `my-team` / `payment-svc` / `dev-jay` | 1 |
| output_dir | 생성 파일을 어디에 둘까요? | Dockerfile과 yaml 파일이 만들어질 폴더예요. 기본은 `k8s-output/`이고, 이미 있으면 덮어쓸지 다시 물어봅니다. | `Output directory (config: output.dir)` | `k8s-output` (기본) / `deploy/k8s` | 1 |
| resource_hint | 메모리/CPU는 어느 정도 필요해요? | 앱이 사용할 자원을 추정해주세요. JVM은 기본 메모리 512Mi~1Gi를 추천합니다. 잘 모르겠으면 'medium'을 고르세요. | `spec.containers[].resources.{requests,limits}.{cpu,memory}` | `small (256Mi/0.5CPU)` / `medium (512Mi/1CPU)` / `large (1Gi/2CPU)` | 1 |
| actuator | actuator를 쓰고 있나요? | actuator는 Spring Boot의 헬스체크/메트릭 기능이에요. `build.gradle`에 `spring-boot-starter-actuator`가 있으면 활성화된 거예요. 없으면 TCP로 헬스체크합니다. | `Spring Boot Actuator — /actuator/health 엔드포인트` | Boot 2.x: `/actuator/health` 단일 / Boot 3.x: `/liveness` + `/readiness` 분리 | 2 |
| multi_module | 여러 모듈 중 어느 걸 배포할까요? | Gradle/Maven multi-module 프로젝트예요. 보통 API 서버는 '-api', '-web', '-server'로 끝나는 모듈이에요. 라이브러리(-core, -common)는 배포 대상이 아닙니다. | `Gradle settings.gradle(.kts) / Maven <modules>` | `order-api` (○) / `order-core` (×, 라이브러리) | 2 |
| stateful | 상태성 앱이라는 게 뭐예요? | DB 연결이나 파일 저장이 필요한 앱이에요. stateful HIGH이면 StatefulSet + PVC를 생성합니다. MEDIUM이면 확인 질문 후 진행합니다. | `StatefulSet vs Deployment — Pod 재시작 시 데이터 보존` | stateless: 일반 API 서버 / stateful: DB, 메시지 큐, 파일 업로드 앱 | 2 |
| build_engine | 이미지를 직접 빌드할까요? | 기본은 Dockerfile만 만들고 빌드는 안 해요. 빌드도 하고 싶으면 'auto'를 고르세요 (docker/podman/nerdctl 자동 감지). CI에서는 보통 별도 단계에서 빌드합니다. | `build.engine config — auto / docker / podman / nerdctl / skip(default)` | 로컬 테스트: `auto` / CI 파이프라인: `skip` | config |
