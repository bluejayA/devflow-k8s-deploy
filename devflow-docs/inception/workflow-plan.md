# Workflow Plan

**Timestamp**: 2026-04-22T17:30:00+09:00
**Selected Approach**: A안 — 직행 구현 (application-design/units-generation 스킵, TDD 직행)

## Approaches Considered
- A안) 직행 구현 — application-design/units-generation 스킵, 설계 확정 상태에서 TDD 직행 (권장)
- B안) 설계 후 구현 — application-design + units-generation 포함, 4개 레이어 인터페이스 공식 문서화

## Approved Stages

### PRE-PLANNING
- user-stories: included — 3 actors, 11 stories 생성 완료
- nfr-requirements: skipped — 사용자 선택 (Standard complexity, 기존 NFR 패턴 재사용)

### CONSTRUCTION
- application-design: skipped — 설계 결정이 대화에서 이미 확정됨 (ClusterConfig 구조, 템플릿 형태, validator 패턴)
- units-generation: skipped — 컴포넌트 범위가 명확, TDD로 직접 진행
- code-generation: included — always
- build-and-test: included — always

## Stage Depths
- application-design: Standard (스킵)
- units-generation: Standard (스킵)
- code-generation: Standard (TDD protocol 적용)
- build-and-test: Standard

## Implementation Scope (code-generation 참조용)

### 신규 파일
| 파일 | 내용 |
|------|------|
| `scripts/_shared/types.py` | `ClusterConfig` frozen dataclass 추가 |
| `templates/manifest/statefulset.tmpl` | StatefulSet + volumeClaimTemplates |
| `templates/manifest/networkpolicy.tmpl` | deny-all + CoreDNS 예외 |
| `scripts/validators/rules/sts.py` | STS-W01 규칙 |
| `scripts/validators/rules/net.py` | NET-W01 규칙 |

### 수정 파일
| 파일 | 변경 내용 |
|------|---------|
| `scripts/config_loader.py` | `resolve_cluster_config()` 메서드 추가 |
| `scripts/manifest_generator.py` | `generate_statefulset()`, `generate_networkpolicy()` 추가 |
| `scripts/validators/rules/__init__.py` | sts, net 모듈 import 추가 |
| `scripts/pipeline/orchestrator.py` | ClusterConfig 통합, StatefulSet/NetworkPolicy 분기 |
| `.devflow-k8s-deploy.yml.sample` | `cluster:` 섹션 예시 추가 |
