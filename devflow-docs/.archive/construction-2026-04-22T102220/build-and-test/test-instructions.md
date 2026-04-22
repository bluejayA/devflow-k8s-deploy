# Test Instructions — devflow-k8s-deploy v0.1.0

## Unit Tests + Integration Tests

Run:
```bash
uv run pytest
```

Expected: **607 tests** 통과, 0 실패 (v0.1.0 CONSTRUCTION 완료 기준).

### 세부 테스트 분포

| 범주 | 통과 수 | 위치 |
|------|---------|------|
| shared 모듈 (types/errors/retry/defaults/fileio/image_ref/text_safety) | ~120 | `tests/_shared/` |
| stack_module (Protocol + JvmStackModule) | ~100 | `tests/stacks/` |
| 개별 unit (template_renderer / config_loader / atomic_writer / k8s_validator / kubectl_dry_runner / project_analyzer / dockerfile_generator / manifest_generator / output_packager / build_runner / retry_loop / orchestrator) | ~350 | `tests/test_*.py` |
| NFR-SEC-05 경계 allowlist + E2E smoke | ~35 | `tests/integration/` |

### 범주별 실행

```bash
# 공용 shared만
uv run pytest tests/_shared/

# JVM stack 감지
uv run pytest tests/stacks/

# 개별 컴포넌트
uv run pytest tests/test_validate_k8s.py -v

# 통합 테스트 (경계 allowlist + E2E)
uv run pytest tests/integration/ -v
```

### 커버리지

```bash
uv run pytest --cov=scripts --cov-report=term-missing
```

`validate_k8s.py`: ≥70%, `scripts/stacks/jvm.py`: ≥60% (NFR-TEST-01/02 기준).

## Lint + Type Check

```bash
uv run ruff check scripts/ tests/
uv run mypy scripts/
```

Expected: `All checks passed!` / `Success: no issues found in 25 source files`

## Manual Verification

### CLI Smoke Test (실제 Spring Boot 프로젝트)

```bash
# 1. 샘플 프로젝트 생성
SAMPLE=/tmp/smoke-spring-boot
rm -rf "$SAMPLE" && mkdir -p "$SAMPLE/src/main/resources"
cat > "$SAMPLE/build.gradle.kts" <<'EOF'
plugins {
    id("org.springframework.boot") version "3.2.0"
    kotlin("jvm") version "1.9.0"
}
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-web")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
}
EOF
cat > "$SAMPLE/settings.gradle.kts" <<'EOF'
rootProject.name = "smoke-sample"
EOF
cat > "$SAMPLE/src/main/resources/application.yml" <<'EOF'
server:
  port: 8080
management:
  endpoints:
    web:
      exposure:
        include: health
EOF

# 2. 파이프라인 실행
OUT=/tmp/smoke-output
rm -rf "$OUT"
uv run python -m scripts.pipeline.orchestrator --project-dir "$SAMPLE" --output-dir "$OUT"
echo "EXIT=$?"

# 3. 출력 확인
ls -la "$OUT/"
jq '.validation' "$OUT/summary.json"
```

**예상**:
- `EXIT=0` (모든 PASS) 또는 `EXIT=2` (WARN soft-success)
- `$OUT/`에 `Dockerfile`, `deployment.yaml`, `service.yaml`, `serviceaccount.yaml`, `rationale.md`, `summary.json` 6개 파일
- kubectl 미설치 환경: `summary.json.validation.skipped: ["kubectl_dry_run"]` (F-56 degraded)

### BailOut 시나리오 확인 (수동)

AtomicWriter `bailout_commit()` 동작 확인 — staging_dir가 `{output_dir}-failed-{timestamp}/`로 보존되고 `troubleshoot.md`가 남아야 함.

## CI 통합

```bash
#!/bin/bash
set -uo pipefail

export CLAUDE_PLUGIN_ROOT=$(pwd)

uv run python -m scripts.pipeline.orchestrator --project-dir . --output-dir k8s-output/
EXIT=$?

[ -f k8s-output/summary.json ] || { echo "ERROR: summary.json 미생성"; exit 1; }

case $EXIT in
  0) echo "✅ PASS" ;;
  1) jq '.validation' k8s-output/summary.json; exit 1 ;;
  2) echo "⚠️  WARN (soft-success)"; jq '.validation' k8s-output/summary.json ;;
  *) echo "ERROR: 예상치 못한 exit $EXIT"; exit $EXIT ;;
esac
```

## Change Log

- 2026-04-21 — 16 units + 2 E2E 버그 수정(B: bailout_commit, C: --validate=false + cluster-less skip) 완료. 전체 607 tests pass.
