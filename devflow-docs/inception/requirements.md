# Requirements Analysis

**Depth**: Minimal
**Timestamp**: 2026-04-22T10:30:00+09:00

## User Intent

백로그 P1 두 항목을 구현한다.
- **#18** `app.replicas` 설정 필드를 추가하여 현재 하드코딩된 `_DEFAULT_REPLICAS = 2`를 사용자 설정 가능하게 한다.
- **#17** `validate_k8s.py`에 WARN 규칙 2개를 추가한다: `LIFE-W01`(terminationGracePeriodSeconds 미설정/부족) 및 `IMG-W02`(imagePullPolicy: Always + digest 없음).

## Functional Requirements

### #18 replicas 설정화

| ID | 요구사항 | 비고 |
|----|---------|------|
| F-R01 | `BUILTIN_DEFAULTS`에 `app.replicas: 2` 추가 | `scripts/_shared/defaults.py` |
| F-R02 | orchestrator가 `config.raw["app"]["replicas"]`를 읽어 `ManifestGenerator`에 전달 | `scripts/pipeline/orchestrator.py` |
| F-R03 | `ManifestGenerator`가 config 값을 사용, `_DEFAULT_REPLICAS` 상수 제거 | `scripts/manifest_generator.py` |
| F-R04 | `replicas < 1` 입력 시 `ValueError` 발생 (orchestrator 또는 manifest_generator 중 한 곳) | 0/음수 방어 |

### #17 validate_k8s WARN 확장

| ID | 요구사항 | 비고 |
|----|---------|------|
| F-R05 | `LIFE-W01`: pod_spec에 `terminationGracePeriodSeconds`가 없거나 30 미만이면 WARN | pod 레벨 체크 |
| F-R06 | `IMG-W02`: container의 `imagePullPolicy: Always` + image에 `@sha256:` 없으면 WARN | container 레벨 체크 |
| F-R07 | 두 규칙 모두 기존 `_rule_*` 패턴을 따라 구현 | `validate_k8s.py` |
| F-R08 | `validation.skipped` 목록에 `LIFE-W01`, `IMG-W02` 추가 가능 | 기존 skip 메커니즘 재사용 |

## Non-Functional Requirements

| ID | 요구사항 |
|----|---------|
| NFR-01 | 기존 631 테스트 모두 통과 유지 |
| NFR-02 | 각 신규 요구사항에 대해 pytest 테스트 추가 (TDD) |
| NFR-03 | `LIFE-W01`, `IMG-W02` 메시지는 한국어(`message_ko`) + 영어(`message_en`) 병기 |

## Assumptions

- `terminationGracePeriodSeconds` 기준값은 30초 (Kubernetes 기본값과 동일, 부족하면 graceful shutdown 실패 위험)
- `imagePullPolicy` 필드 미설정 시 IMG-W02 미발동 (Always 명시 시만)
- replicas 상한선 검증은 이 이슈 범위 밖 (자유 입력)

## Open Questions

없음
