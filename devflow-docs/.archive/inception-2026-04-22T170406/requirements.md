# Requirements Analysis

**Depth**: Minimal
**Timestamp**: 2026-04-22T11:50:00+09:00

## User Intent

`scripts/validate_k8s.py` (1,239줄)를 규칙별 모듈로 분리한다. 현재 하나의 파일에 20개+ 규칙 메서드가 집중되어 있어, 파일 하나를 Read할 때 전체 컨텍스트가 로드된다. `scripts/validators/` 패키지로 분리하면 규칙 파일별 Read 단위가 작아져 토큰 효율이 개선된다.

## Functional Requirements

| ID | 요구사항 |
|----|---------|
| F-01 | `scripts/validators/` 패키지 신설: `registry.py`, `core.py`, `rules/__init__.py`, `rules/sec.py`, `rules/res.py`, `rules/img.py`, `rules/life.py`, `rules/sa.py`, `rules/prb.py`, `rules/svc.py` |
| F-02 | `@register_rule(scope)` 데코레이터 패턴: 규칙 함수가 `_registry` dict에 자동 등록 |
| F-03 | `K8sValidator.validate()` 루프가 `run_rules(scope, ...)` 호출로 규칙 실행 (기존 직접 호출 제거) |
| F-04 | `scripts/validate_k8s.py`는 하위 호환 re-export: `from scripts.validators import K8sValidator` |
| F-05 | 기존 테스트 646개 전체 통과 (변경 없이) |

## Non-Functional Requirements

| ID | 요구사항 |
|----|---------|
| NFR-01 | 규칙 파일 하나당 100줄 이하 목표 (토큰 효율) |
| NFR-02 | `ruff` + `uv run pytest` 클린 통과 |
| NFR-03 | `scripts/validate_k8s.py` public API (`K8sValidator`, `CheckResult`, `CheckLevel`) 변경 없음 |

## Assumptions

- `_check_pod_spec()` / `_check_container()` dispatch 로직은 `core.py`에서 관리
- 규칙 함수 시그니처: `fn(pod_spec|container, *, context=None) -> list[CheckResult]` (키워드 전용 `**_` 허용)
- 기존 테스트는 `scripts.validate_k8s.K8sValidator`를 임포트하므로 re-export로 커버

## Open Questions

없음
