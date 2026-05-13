# Code Generation Plan: go-framework-probe-detection (BL-017)

**Ticket**: BL-017 ([#27](https://github.com/bluejayA/devflow-k8s-deploy/issues/27))
**Branch**: feature/go-framework-probe-detection
**Approval**: 2026-05-13 (사용자 승인)

> **For agentic workers:** REQUIRED — `aidlc:aidlc-code-generation` with "GENERATE" signal.

## Files to Modify
- [x] `scripts/stacks/go.py`
- [x] `tests/stacks/test_go.py`

## Implementation Steps

### Phase 1 — 정규식 + go.mod 파서 (P1)
- [x] Step 1: `_GIN_RE`/`_ECHO_RE`/`_FIBER_RE` (root + major version + false-positive 가드, 6 tests)
- [x] Step 2: `_parse_go_mod_require` (블록/단일/주석/malformed, 4 tests)

### Phase 2 — `_detect_go_framework` 4단계 (P2)
- [x] Step 3: direct 단일 매치 (gin/echo/fiber 각 1건, 3 tests)
- [x] Step 4: direct 복수 → go-generic (1 test)
- [x] Step 5: direct 없음 + sum 단일 → 약한 evidence (1 test)
- [x] Step 6: sum 복수 → go-generic (1 test)
- [x] Step 7: 안전 폴백 (파일 없음 + symlink, 3 tests)

### Phase 3 — `GoStackModule` 통합 (P3)
- [x] Step 8: `detect()` framework 위임 (1 test)
- [x] Step 9: `probe_plan()` framework 분기 (gin/echo/fiber/generic, 4 tests)

### Phase 4 — 회귀 검증 (P4)
- [x] Step 10: JVM 골든 + Go-generic E2E + 전체 회귀 + ruff

## Verification Contract

### 완료 조건
- 신규 단위 테스트 22건 통과 (NFR-6 ≥13건의 169%)
- JVM 골든 byte-identical (NFR-4)
- Go-generic 골든/E2E byte-identical (NFR-5)
- 전체 회귀 ≥ 919 tests passing (897 + 22)
- ruff clean

### 검증 명령
- `uv run pytest tests/stacks/test_go.py -v`
- `uv run pytest tests/test_manifest_jvm_golden.py -v`
- `uv run pytest tests/test_e2e_go_smoke.py tests/test_e2e_go_mixed_repo.py tests/test_dockerfile_go_golden.py -v`
- `uv run pytest -q`
- `uv run ruff check scripts/stacks/go.py tests/stacks/test_go.py`

### 리스크 태그
- [x] regex safety (ReDoS) — NFR-1
- [x] regression — JVM/Go-generic byte-identical (NFR-4/NFR-5)
