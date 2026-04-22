# Code Generation Plan: p1-replicas-validation-warn

> **For agentic workers:** REQUIRED: Use `aidlc:aidlc-code-generation` with the
> "GENERATE" signal to execute this plan. Do NOT implement ad-hoc.
> `"code-generation: GENERATE — proceed with the approved plan for p1-replicas-validation-warn"`

## Files to Modify

- [x] `scripts/_shared/defaults.py` — BUILTIN_DEFAULTS에 `app.replicas: 2` 추가
- [x] `scripts/_shared/types.py` — UserInputs에 `replicas: int` 필드 추가
- [x] `scripts/pipeline/orchestrator.py` — app_raw에서 replicas 읽기 + 검증 + UserInputs 전달
- [x] `scripts/manifest_generator.py` — _DEFAULT_REPLICAS 제거, inputs.replicas 사용
- [x] `scripts/validate_k8s.py` — LIFE-W01, IMG-W02 규칙 추가 + dispatch 등록
- [x] `tests/test_manifest_generator.py` — replicas 설정 테스트
- [x] `tests/test_validate_k8s.py` — LIFE-W01, IMG-W02 테스트
- [x] `tests/test_config_loader.py` — app.replicas 기본값 테스트

## Implementation Steps

- [x] Step 1: #18 defaults + UserInputs
  - [x] RED: `test_builtin_defaults_has_app_replicas` 작성
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `defaults.py`에 `app: {replicas: 2}` 추가, `types.py` UserInputs에 `replicas: int` 추가
  - [x] Verify GREEN: 통과 확인 + 전체 회귀

- [x] Step 2: #18 orchestrator config 연결
  - [x] RED: `test_collect_inputs_replicas_from_config`, `test_collect_inputs_replicas_invalid` 작성
  - [x] Verify RED: 실패 확인
  - [x] GREEN: orchestrator `_collect_inputs_step1()`에서 `int(app_raw.get("replicas", 2))` 읽기, `< 1`이면 ValueError, UserInputs에 전달
  - [x] Verify GREEN: 통과 확인 + 전체 회귀

- [x] Step 3: #18 manifest_generator 연결
  - [x] RED: `test_generate_deployment_custom_replicas` 작성
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `_DEFAULT_REPLICAS` 상수 제거, `generate_deployment()`에서 `inputs.replicas` 사용
  - [x] Verify GREEN: 통과 확인 + 전체 회귀

- [x] Step 4: #17 LIFE-W01
  - [x] RED: `test_warn_when_missing`, `test_warn_when_below_threshold`, `test_no_warn_when_at_threshold` 작성
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `_rule_life_w01(pod_spec)` 구현, `_check_pod_spec()`에 dispatch 추가
  - [x] Verify GREEN: 통과 확인 + 전체 회귀

- [x] Step 5: #17 IMG-W02
  - [x] RED: `test_warn_always_no_digest`, `test_no_warn_always_with_digest`, `test_no_warn_not_always` 작성
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `_rule_img_w02(container)` 구현, `_check_container()`에 dispatch 추가
  - [x] Verify GREEN: 통과 확인 + 전체 회귀

## Test Strategy

- [x] `test_builtin_defaults_has_app_replicas`: `BUILTIN_DEFAULTS["app"]["replicas"] == 2`
- [x] `test_collect_inputs_replicas_from_config`: config에 `app.replicas: 3` → UserInputs.replicas == 3
- [x] `test_collect_inputs_replicas_invalid`: replicas 0 → ValueError
- [x] `test_generate_deployment_custom_replicas`: replicas=5 → deployment.yaml에 `replicas: 5`
- [x] `test_warn_when_missing`: terminationGracePeriodSeconds 없음 → WARN
- [x] `test_warn_when_below_threshold`: terminationGracePeriodSeconds=10 → WARN
- [x] `test_no_warn_when_at_threshold`: terminationGracePeriodSeconds=30 → 결과 없음
- [x] `test_warn_always_no_digest`: imagePullPolicy=Always + image에 sha256 없음 → WARN
- [x] `test_no_warn_always_with_digest`: imagePullPolicy=Always + @sha256: → 결과 없음
- [x] `test_no_warn_not_always`: imagePullPolicy=IfNotPresent → 결과 없음

## Verification Contract

### 완료 조건
- [x] `app.replicas` 설정값이 deployment.yaml `spec.replicas`에 반영됨
- [x] replicas < 1 입력 시 ValueError 발생
- [x] terminationGracePeriodSeconds 미설정/30 미만 → LIFE-W01 WARN
- [x] imagePullPolicy: Always + digest 없음 → IMG-W02 WARN
- [x] 기존 631 테스트 모두 통과 (645 통과로 완료)

### 검증 명령
- `uv run pytest --tb=short -q` — 전체 테스트
- `uv tool run ruff check scripts/ tests/` — 린트

### 리스크 태그
없음 (config 연결 + validation 규칙 추가, 보안/DB 변경 없음)
