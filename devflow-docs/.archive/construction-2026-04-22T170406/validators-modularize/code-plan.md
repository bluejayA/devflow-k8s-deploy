# Code Generation Plan: validators-modularize

> **For agentic workers:** REQUIRED: Use `aidlc:aidlc-code-generation` with the
> "GENERATE" signal to execute this plan. Do NOT implement ad-hoc.
> `"code-generation: GENERATE — proceed with the approved plan for validators-modularize"`

## Files to Create

- [ ] `scripts/validators/__init__.py` — `K8sValidator` re-export
- [ ] `scripts/validators/registry.py` — `@register_rule(scope)` 데코레이터 + `run_rules()` + `_registry`
- [ ] `scripts/validators/helpers.py` — `_as_dict()` 헬퍼
- [ ] `scripts/validators/core.py` — `K8sValidator` 클래스 + `_compute_exit_code` + `_safe_collect_file` + `_check_*` dispatch
- [ ] `scripts/validators/rules/__init__.py` — 규칙 모듈 import (등록 트리거)
- [ ] `scripts/validators/rules/sec.py` — SEC-001~009 (규칙 9개)
- [ ] `scripts/validators/rules/res.py` — RES-001, RES-W01 (규칙 2개)
- [ ] `scripts/validators/rules/img.py` — IMG-001, IMG-W01, IMG-W02 (규칙 3개)
- [ ] `scripts/validators/rules/sa.py` — SA-001, SA-002 (규칙 2개)
- [ ] `scripts/validators/rules/life.py` — LIFE-W01 (규칙 1개)
- [ ] `scripts/validators/rules/prb.py` — PRB-001, PRB-002 (규칙 2개)
- [ ] `scripts/validators/rules/svc.py` — SVC-001, SVC-002 (규칙 2개)
- [ ] `tests/test_validators_structure.py` — 패키지 구조 임포트 테스트

## Files to Modify

- [ ] `scripts/validate_k8s.py` — 규칙 메서드 제거, `K8sValidator`/`_compute_exit_code` re-export로 전환

## Implementation Steps

### Step 1: 구조 테스트 작성 + 패키지 스켈레톤

- [ ] RED: `test_validators_structure.py` 작성 — `from scripts.validators import K8sValidator` 등 구조 임포트 테스트
- [ ] Verify RED: `uv run pytest tests/test_validators_structure.py` 실패 확인
- [ ] GREEN: `scripts/validators/__init__.py`, `registry.py`, `helpers.py`, `rules/__init__.py`, 빈 규칙 파일들 생성
- [ ] GREEN: `scripts/validators/core.py` — 기존 `K8sValidator`를 `core.py`로 이동, `_rule_*` 메서드 유지 (임시)
- [ ] Verify GREEN: 구조 테스트 통과 + 기존 646 테스트 통과 확인

### Step 2: 규칙 함수 추출 + `@register_rule` 연결

- [ ] RED: 추가 테스트 — `run_rules("container", c)` 호출 시 SEC/RES/IMG/PRB 결과 반환 확인
- [ ] Verify RED: 새 테스트 실패 확인
- [ ] GREEN: `registry.py` 구현 (`_registry`, `register_rule`, `run_rules`)
- [ ] GREEN: `sec.py` — `_rule_sec001~009` 를 `rule_sec001~009` 독립 함수로, `@register_rule` 적용
  - `rule_sec001(c, *, pod_sc=None, **_)`, `rule_sec007(c, *, pod_sc=None, **_)`, 나머지 `(c, **_)` / `(pod_spec, **_)`
- [ ] GREEN: `res.py`, `img.py`, `sa.py`, `life.py`, `prb.py`, `svc.py` — 동일 패턴
- [ ] GREEN: `rules/__init__.py` — `from . import sec, res, img, sa, life, prb, svc` (등록 순서 고정)
- [ ] GREEN: `core.py` `_check_pod_spec` / `_check_container` / `_check_service` → `run_rules()` 호출로 교체, `_rule_*` 메서드 제거
- [ ] Verify GREEN: 모든 테스트 통과

### Step 3: `validate_k8s.py` thin re-export 전환

- [ ] GREEN: `scripts/validate_k8s.py` — `K8sValidator`, `_compute_exit_code` re-import, 규칙 메서드 코드 제거, `main()` + CLI 상수 유지
- [ ] Verify GREEN: 전체 646 + 신규 테스트 통과

## Test Strategy

- [ ] `test_import_validators_package`: `from scripts.validators import K8sValidator` 성공
- [ ] `test_import_registry`: `from scripts.validators.registry import register_rule, run_rules` 성공
- [ ] `test_import_rule_modules`: 각 규칙 모듈 임포트 성공 (sec/res/img/sa/life/prb/svc)
- [ ] `test_run_rules_container`: `run_rules("container", sample_c)` 호출 → SEC/RES/IMG 규칙 결과 포함
- [ ] `test_run_rules_pod_spec`: `run_rules("pod_spec", sample_pod)` 호출 → SA/LIFE/SEC006/SEC008 결과 포함
- [ ] `test_run_rules_service`: `run_rules("service", sample_svc)` 호출 → SVC001 결과 포함
- [ ] `test_validate_k8s_reexport`: `from scripts.validate_k8s import K8sValidator, _compute_exit_code` 성공 (기존 임포트 경로 보존)

## Verification Contract

### 완료 조건
- [ ] `scripts/validate_k8s.py`의 `K8sValidator`, `_rule_*` 메서드 코드 제거됨
- [ ] `scripts/validators/rules/` 7개 파일에 20개 규칙 분산됨
- [ ] 기존 646 테스트 전체 통과
- [ ] `ruff check scripts/validators/` 클린

### 검증 명령
- `uv run pytest tests/test_validate_k8s.py tests/test_validators_structure.py -q` — 기존+신규 테스트
- `uv run pytest --tb=short -q` — 전체 회귀
- `ruff check scripts/validators/` — 린트

### 리스크 태그
- 없음 (순수 리팩토링, 신규 기능 없음)

## 구현 세부사항

### registry.py 스펙
```python
RuleScope = Literal["container", "pod_spec", "service"]
_registry: dict[str, list[Callable[..., list[CheckResult]]]] = {
    "container": [], "pod_spec": [], "service": []
}
def register_rule(scope: RuleScope): ...  # decorator factory
def run_rules(scope: RuleScope, target: dict, **kwargs) -> list[CheckResult]: ...
```

### rules/__init__.py import 순서 (실행 순서 고정)
```python
from scripts.validators.rules import sec, res, img, sa, life, prb, svc
```
결과 순서: pod_spec=[SEC-006, SEC-008, SA-001, SA-002, LIFE-W01], container=[SEC-001~009, RES-001/W01, IMG-001/W01/W02, PRB-001/002], service=[SVC-001, SVC-002]

### validate_k8s.py 최종 형태
```python
# re-exports (기존 임포트 경로 유지)
from scripts.validators.core import K8sValidator, _compute_exit_code  # noqa: F401

# CLI 상수 + main() 유지
def main() -> None: ...
```
