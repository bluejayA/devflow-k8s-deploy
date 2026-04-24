# Requirements Analysis

**Depth**: Standard
**Timestamp**: 2026-04-22T17:10:00+09:00

## User Intent

BL-003 (StatefulSet + PVC 지원, #11) + BL-004 (NetworkPolicy zero-trust, #13) 동시 구현.

현재 stateful 앱 감지 시 경고만 출력하고 Deployment를 생성하는 한계를 해소하여 StatefulSet + PVC 매니페스트를 생성하고, 운영 환경에서 Pod 간 통신 제한 없이 배포되는 문제를 해소하기 위해 zero-trust NetworkPolicy를 생성한다.

환경별 차이(StorageClass, CNI 지원)를 추상화하는 `cluster.preset` 구조를 도입한다. MVP는 `orbstack` preset 1개 + 직접입력으로 시작한다.

## Functional Requirements

### BL-003: StatefulSet + PVC

| ID | 요구사항 |
|----|---------|
| F-01 | `ClusterConfig` 타입 신규 (`scripts/_shared/types.py`) — preset, storage_class, network_policy 필드 (allow_ingress/egress는 별도 config 섹션) |
| F-02 | `ConfigLoader.resolve_cluster_config()` 메서드 추가 — `cluster.preset` 키 로드, preset 기본값 적용, 필드 override 처리 |
| F-03 | `orbstack` 내장 preset: `storageClassName=local-path`, `volumeBindingMode=WaitForFirstConsumer`, `network_policy=true` |
| F-04 | `cluster.preset` 미설정 시 `PromptCallback`으로 인터랙티브 질문 (선택지: `orbstack` / `직접입력`) |
| F-05 | `templates/manifest/statefulset.tmpl` 신규 — deployment.tmpl 기반에 `volumeClaimTemplates` 추가 |
| F-06 | `ManifestGenerator.generate_statefulset()` 추가 — ClusterConfig의 storage_class + storage_size 파라미터 수용 |
| F-07 | `analysis.statefulness.confidence == 'high'` → StatefulSet 자동 선택, `'medium'` → PromptCallback 확인 후 선택 |
| F-08 | STS-W01 규칙 신규 (`scripts/validators/rules/sts.py`): StatefulSet에 `volumeClaimTemplates` 미설정 시 WARN |

### BL-004: NetworkPolicy

| ID | 요구사항 |
|----|---------|
| F-09 | `templates/manifest/networkpolicy.tmpl` 신규 — ingress/egress deny-all 기본, CoreDNS egress 예외(kube-system:53 UDP+TCP) 포함 |
| F-10 | `ManifestGenerator.generate_networkpolicy()` 추가 — `allow_ingress_from: list[dict] \| None`, `allow_egress_to: list[dict] \| None` 파라미터, `ResolvedConfig.raw['network']`에서 값 주입 |
| F-11 | `ClusterConfig.network_policy == False` → NetworkPolicy 생성 스킵 + `NET-W01` WARN (로컬/테스트 all-allow 시나리오 — 예: `cluster.network_policy: false` override) |
| F-12 | NET-W01 규칙 신규 (`scripts/validators/rules/net.py`): manifest 집합에 NetworkPolicy 없으면 WARN |
| F-13 | config `network.allow_ingress_from` / `network.allow_egress_to` — 라벨셀렉터 기반 허용 규칙 (선택, 미설정 시 deny-all 유지). `ClusterConfig`와 분리, `SkillPipeline`이 `ResolvedConfig.raw`에서 직접 읽어 `generate_networkpolicy()`에 주입 |

### 공통 Config

| ID | 요구사항 |
|----|---------|
| F-14 | `.devflow-k8s-deploy.yml` 샘플에 `cluster:` 섹션 예시 추가 |

## Non-Functional Requirements

| ID | 요구사항 |
|----|---------|
| NFR-01 | 기존 655개 테스트 전체 통과 (리그레션 없음) |
| NFR-02 | 신규 기능 단위 테스트 — happy path + edge cases (최소 StatefulSet/NetworkPolicy/ClusterConfig 각 1개 파일) |
| NFR-03 | `ruff` 린트 클린 패스 |
| NFR-04 | YAML injection 방어 — 신규 템플릿 필드(storage_class, storage_size)에 `_validate_manifest_field` 적용 |
| NFR-05 | `storage_size` Kubernetes quantity 형식 검증 (`[0-9]+[KMGTPE]i?` 패턴, 예: `1Gi`, `500Mi`) |

## Technology Stack

| 계층 | 선택 | 소스 |
|------|------|------|
| Language | Python 3.11+ | Brownfield 감지 |
| Package Manager | uv | CLAUDE.md |
| Test | pytest | CLAUDE.md |
| Linter | ruff | CLAUDE.md |
| Template | Jinja2 | Brownfield 감지 |
| YAML | PyYAML | Brownfield 감지 |

## Assumptions

- StatefulSet `volumeClaimTemplates`에 RWO PVC 1개만 포함 (MVP 범위)
- `allow_ingress_from` / `allow_egress_to` 미설정 시 deny-all 유지. all-allow 로컬 테스트는 `cluster.network_policy: false`로 NetworkPolicy 자체를 스킵하는 방식 사용
- `cluster.preset` 미설정 + PromptCallback 없음(자동 모드) → `orbstack` 기본값으로 fallback
- StatefulSet과 Deployment는 동시 생성하지 않음 — statefulness 결과에 따라 둘 중 하나만 선택
- `storageClassName: local-path` omit 없이 명시 — orbstack에서 실제 값이 확인됨

## Open Questions

없음
