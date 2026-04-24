# User Stories

**Timestamp**: 2026-04-22T17:20:00+09:00
**Source**: devflow-docs/inception/requirements.md

## Actors

- **개발자**: JVM 앱을 K8s에 배포하는 devflow 스킬 사용자. stateful/stateless 여부와 네트워크 정책을 자동으로 처리받길 원함.
- **운영자**: K8s 클러스터 환경을 관리하며 cluster.preset을 설정하는 담당자. 팀 전체에 일관된 인프라 기본값을 제공하는 역할.
- **주니어 엔지니어**: K8s 개념(StatefulSet, NetworkPolicy 등)에 익숙하지 않은 엔지니어. devflow가 제시하는 선택지와 경고의 의미를 이해하고 올바른 조치를 취하기 원함.

---

## Stories

### US-001: StatefulSet 자동 선택
**Actor**: 개발자
**Story**: As a 개발자, I want stateful 앱 감지 시 StatefulSet이 자동으로 생성되기를 원한다. so that 영구 스토리지가 필요한 앱에 Deployment 대신 올바른 워크로드 타입이 설정된다.
**Acceptance Criteria**:
- Given statefulness confidence가 `high`일 때, When devflow를 실행하면, Then Deployment 대신 StatefulSet 매니페스트가 생성된다
- Given statefulness confidence가 `medium`일 때, When devflow를 실행하면, Then StatefulSet vs Deployment 선택을 사용자에게 확인하는 질문이 나온다
- Given statefulness confidence가 `low`일 때, When devflow를 실행하면, Then 기존과 동일하게 Deployment가 생성된다
**Priority**: Must

---

### US-002: PVC 스토리지 설정
**Actor**: 개발자
**Story**: As a 개발자, I want 스토리지 크기와 StorageClass를 config로 지정하기를 원한다. so that 환경별로 올바른 PVC가 프로비저닝된다.
**Acceptance Criteria**:
- Given orbstack preset이 설정된 경우, When StatefulSet이 생성되면, Then storageClassName이 `local-path`로 설정된다
- Given config에 `storage.size`가 설정된 경우, When PVC가 생성되면, Then PVC capacity가 설정값과 일치한다
- Given `storage.size`가 미설정인 경우, When PVC가 생성되면, Then 기본값 `1Gi`가 사용된다
- Given storage_size에 잘못된 K8s quantity 형식이 입력된 경우, When 생성을 시도하면, Then 오류 메시지와 함께 실패한다 (예: "1Gi", "500Mi" 형식 필요)
**Priority**: Should

---

### US-003: zero-trust NetworkPolicy 자동 생성
**Actor**: 개발자
**Story**: As a 개발자, I want zero-trust NetworkPolicy가 자동으로 생성되기를 원한다. so that 수동 정책 작성 없이 앱이 허가되지 않은 네트워크 접근으로부터 보호된다.
**Acceptance Criteria**:
- Given `cluster.network_policy: true`인 경우, When devflow를 실행하면, Then ingress/egress deny-all NetworkPolicy 매니페스트가 생성된다
- Given NetworkPolicy가 생성된 경우, Then CoreDNS egress(kube-system:53 UDP+TCP)가 항상 허용 규칙으로 포함된다
- Given `cluster.network_policy: false`인 경우, When devflow를 실행하면, Then NetworkPolicy 생성이 스킵되고 `NET-W01` WARN이 출력된다
**Priority**: Must

---

### US-004: 로컬 테스트용 NetworkPolicy 스킵
**Actor**: 개발자
**Story**: As a 개발자, I want 로컬 테스트 시 NetworkPolicy를 쉽게 비활성화하기를 원한다. so that 네트워크 제한 없이 앱을 테스트할 수 있다.
**Acceptance Criteria**:
- Given config에 `cluster.network_policy: false`가 설정된 경우, When devflow를 실행하면, Then NetworkPolicy가 생성되지 않는다
- Given NetworkPolicy가 스킵된 경우, Then 검증 결과에 `NET-W01` WARN이 표시된다
- Given `NET-W01` WARN이 표시된 경우, Then suggestion에 활성화 방법(`cluster.network_policy: true`)이 안내된다
**Priority**: Must

---

### US-005: NetworkPolicy 허용 규칙 추가
**Actor**: 개발자
**Story**: As a 개발자, I want 필요한 서비스와의 통신을 위한 ingress/egress 허용 규칙을 config로 지정하기를 원한다. so that deny-all 기본값 위에서 필요한 통신만 명시적으로 허용할 수 있다.
**Acceptance Criteria**:
- Given config에 `network.allow_ingress_from` 라벨셀렉터가 설정된 경우, When NetworkPolicy가 생성되면, Then deny-all baseline에 허용 ingress 규칙이 추가된다
- Given config에 `network.allow_egress_to`가 설정된 경우, When NetworkPolicy가 생성되면, Then egress 허용 규칙이 추가된다
- Given 허용 규칙이 미설정인 경우, When NetworkPolicy가 생성되면, Then CoreDNS 예외만 포함한 순수 deny-all이 유지된다
**Priority**: Should

---

### US-006: 클러스터 환경 preset 설정
**Actor**: 운영자
**Story**: As a 운영자, I want cluster.preset 하나로 팀 전체의 StorageClass/NetworkPolicy 기본값을 설정하기를 원한다. so that 개발자가 클러스터 내부 구조를 몰라도 올바른 매니페스트가 생성된다.
**Acceptance Criteria**:
- Given `cluster.preset: orbstack`이 config에 설정된 경우, When devflow를 실행하면, Then `storageClassName=local-path`, `network_policy=true` 기본값이 자동 적용된다
- Given `cluster.preset`이 미설정인 경우, When devflow를 실행하면, Then 인터랙티브 질문(`orbstack` / 직접입력)이 표시된다
- Given preset 기본값과 다른 override 필드가 config에 있는 경우, When devflow를 실행하면, Then override 값이 preset 기본값보다 우선 적용된다
**Priority**: Must

---

### US-007: StatefulSet 검증
**Actor**: 운영자
**Story**: As a 운영자, I want StatefulSet 매니페스트에 모범 사례 검증이 적용되기를 원한다. so that 배포 전에 스토리지 설정 누락을 발견할 수 있다.
**Acceptance Criteria**:
- Given `volumeClaimTemplates`가 없는 StatefulSet인 경우, When 검증을 실행하면, Then `STS-W01` WARN이 출력된다
- Given `volumeClaimTemplates`가 있는 StatefulSet인 경우, When 검증을 실행하면, Then `STS-W01` PASS가 출력된다
**Priority**: Should

---

### US-009: 클러스터 환경 선택 안내
**Actor**: 주니어 엔지니어
**Story**: As a 주니어 엔지니어, I want 클러스터 환경 선택 질문에 각 옵션에 대한 간단한 설명이 포함되기를 원한다. so that K8s 환경 종류를 몰라도 올바른 선택을 할 수 있다.
**Acceptance Criteria**:
- Given `cluster.preset`이 미설정인 경우, When 인터랙티브 질문이 표시되면, Then 각 옵션에 한 줄 설명이 함께 표시된다 (예: `orbstack — OrbStack 로컬 K8s 환경 (Cilium CNI, local-path 스토리지)`)
- Given `직접입력`을 선택한 경우, When 입력 안내가 표시되면, Then 어떤 값을 입력해야 하는지 예시가 제공된다
**Priority**: Should

---

### US-010: StatefulSet vs Deployment 선택 도움말
**Actor**: 주니어 엔지니어
**Story**: As a 주니어 엔지니어, I want stateful 감지 시 StatefulSet과 Deployment의 차이를 이해하고 선택하기를 원한다. so that 앱의 특성에 맞는 워크로드 타입을 알고 선택할 수 있다.
**Acceptance Criteria**:
- Given statefulness confidence가 `medium`인 경우, When 선택 질문이 표시되면, Then StatefulSet과 Deployment의 차이를 한 줄로 설명하는 안내가 포함된다 (예: "StatefulSet — DB/파일 저장처럼 데이터 유지가 필요한 앱, Deployment — 상태 없이 재시작해도 되는 앱")
- Given 감지 근거(reasons)가 있는 경우, When 질문이 표시되면, Then 왜 stateful로 감지됐는지 이유가 함께 표시된다
**Priority**: Should

---

### US-011: 검증 경고 조치 안내
**Actor**: 주니어 엔지니어
**Story**: As a 주니어 엔지니어, I want 검증 WARN/FAIL 발생 시 구체적인 조치 방법을 안내받기를 원한다. so that K8s 전문 지식 없이도 문제를 스스로 해결할 수 있다.
**Acceptance Criteria**:
- Given `NET-W01` WARN이 발생한 경우, When suggestion이 표시되면, Then config에서 `cluster.network_policy: true`로 변경하는 방법이 구체적으로 안내된다
- Given `STS-W01` WARN이 발생한 경우, When suggestion이 표시되면, Then volumeClaimTemplates 추가 방법이 안내된다
- Given 어떤 WARN/FAIL이든, When suggestion이 표시되면, Then "무엇을", "어디서", "어떻게" 세 가지가 포함된다
**Priority**: Should

---

### US-008: NetworkPolicy 부재 감지
**Actor**: 운영자
**Story**: As a 운영자, I want 배포 매니페스트 집합에 NetworkPolicy가 없을 때 경고를 받기를 원한다. so that 모든 앱에 네트워크 격리가 적용됐는지 확인할 수 있다.
**Acceptance Criteria**:
- Given 매니페스트 집합에 NetworkPolicy 문서가 없는 경우, When 검증을 실행하면, Then `NET-W01` WARN이 출력된다
- Given 매니페스트 집합에 NetworkPolicy가 있는 경우, When 검증을 실행하면, Then `NET-W01` PASS가 출력된다
**Priority**: Should
