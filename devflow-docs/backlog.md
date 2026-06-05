# Backlog

_Last updated: 2026-06-05 — BL-006 머지 완료 (PR #40, Codex 2 라운드 — R1 P1x2+P2x2 → fix → R2 P2x2 → fix)_

---

## Next

BL-006 (Python 스택 지원) 완료 — JVM + Go + Python **3-stack** 전환. django/flask/fastapi 자동 감지 + multi-stage uv Dockerfile.
다음 권장 순서: **BL-002(auto-fix 루프)** 또는 **BL-007(React 스택)**.

| ID | 제목 | 이슈 | 분류 |
|----|------|------|------|
| **BL-002** | auto-fix 루프 (검증 실패 시 자동 수정 3회) | [#12](https://github.com/bluejayA/devflow-k8s-deploy/issues/12) | DX |
| **BL-005** | PodDisruptionBudget / topologySpreadConstraints | [#14](https://github.com/bluejayA/devflow-k8s-deploy/issues/14) | 고가용성 |
| **BL-007** | React(nginx) 스택 지원 | [#10](https://github.com/bluejayA/devflow-k8s-deploy/issues/10) | 스택 확장 |

---

## Open

### 스택 확장 / 정확도

| ID | 제목 | 이슈 | 목표 버전 |
|----|------|------|---------|
| **BL-023** | Python `auto_install_server=true` opt-in (SD-2) — 추론 서버 패키지(gunicorn/uvicorn) 자동 설치 옵션. 기본 비활성 유지 | (미생성) | v0.6 |

> BL-023 근거: BL-006 Sub-OQ SD-2. 기본 dependency-conservative(자동 install 금지) 정책은 BL-006에서 확정. opt-in 플래그는 별도 ticket으로 분리.

### 개발자 경험 (DX)

| ID | 제목 | 이슈 | 목표 버전 |
|----|------|------|---------|
| **BL-008** | Helm chart 생성 지원 | [#15](https://github.com/bluejayA/devflow-k8s-deploy/issues/15) | v0.4 |
| **BL-009** | 프리셋/프로파일 (웹 API / 내부 서비스 / 데모) | [#16](https://github.com/bluejayA/devflow-k8s-deploy/issues/16) | v0.4 |

### 검증 강화

| ID | 제목 | 이슈 | 목표 버전 |
|----|------|------|---------|
| **BL-010** | CIS Kubernetes Benchmark 매핑 | [#19](https://github.com/bluejayA/devflow-k8s-deploy/issues/19) | v0.4 |

### 문서 / 일관성

| ID | 제목 | 이슈 | 우선순위 |
|----|------|------|---------|
| **BL-016** | SKILL.md STEP 4-1 ↔ orchestrator 검증 경로 drift | [#25](https://github.com/bluejayA/devflow-k8s-deploy/issues/25) | low-medium |

### JVM 제약 / 정확도

| ID | 제목 | 이슈 | 우선순위 |
|----|------|------|---------|
| **BL-011** | 중첩 모듈(multi-level) 지원 | [#4](https://github.com/bluejayA/devflow-k8s-deploy/issues/4) | medium |
| **BL-012** | stateful 감지 AST 파싱으로 정확도 개선 | [#5](https://github.com/bluejayA/devflow-k8s-deploy/issues/5) | medium |
| **BL-013** | runAsUser / fsGroup 커스터마이징 지원 | [#6](https://github.com/bluejayA/devflow-k8s-deploy/issues/6) | low |
| **BL-014** | Ktor / Micronaut HTTP probe 자동 감지 | [#7](https://github.com/bluejayA/devflow-k8s-deploy/issues/7) | low |


---

## 완료

| 이슈 | 제목 | PR | 완료일 |
|------|------|-----|--------|
| [#18](https://github.com/bluejayA/devflow-k8s-deploy/issues/18) | replicas 설정화 | [#20](https://github.com/bluejayA/devflow-k8s-deploy/pull/20) | 2026-04-22 |
| [#17](https://github.com/bluejayA/devflow-k8s-deploy/issues/17) | validate_k8s WARN 확장 (LIFE-W01, IMG-W02) | [#20](https://github.com/bluejayA/devflow-k8s-deploy/pull/20) | 2026-04-22 |
| [#21](https://github.com/bluejayA/devflow-k8s-deploy/issues/21) | validate_k8s.py 규칙별 모듈 분리 | [#22](https://github.com/bluejayA/devflow-k8s-deploy/pull/22) | 2026-04-22 |
| [#11](https://github.com/bluejayA/devflow-k8s-deploy/issues/11) | StatefulSet + PVC 지원 (BL-003) | [#23](https://github.com/bluejayA/devflow-k8s-deploy/pull/23) | 2026-04-22 |
| [#13](https://github.com/bluejayA/devflow-k8s-deploy/issues/13) | NetworkPolicy zero-trust default deny (BL-004) | [#23](https://github.com/bluejayA/devflow-k8s-deploy/pull/23) | 2026-04-22 |
| [#24](https://github.com/bluejayA/devflow-k8s-deploy/issues/24) | StackModule Protocol 확장 — Dockerfile 책임 이관 (BL-015) | [#26](https://github.com/bluejayA/devflow-k8s-deploy/pull/26) | 2026-04-23 |
| [#8](https://github.com/bluejayA/devflow-k8s-deploy/issues/8) | Go 스택 지원 — 최소 스코프 (BL-001, Phase 1-9 + Codex R2) | [#29](https://github.com/bluejayA/devflow-k8s-deploy/pull/29) + [#30](https://github.com/bluejayA/devflow-k8s-deploy/pull/30) | 2026-04-28 |
| [#32](https://github.com/bluejayA/devflow-k8s-deploy/issues/32) | SKILL.md description Go 지원 반영 (BL-020) | [#35](https://github.com/bluejayA/devflow-k8s-deploy/pull/35) | 2026-04-29 |
| [#33](https://github.com/bluejayA/devflow-k8s-deploy/issues/33) | manifest/rationale 주석 stack-aware (BL-021) | [#35](https://github.com/bluejayA/devflow-k8s-deploy/pull/35) | 2026-04-29 |
| [#34](https://github.com/bluejayA/devflow-k8s-deploy/issues/34) | k8s-output 디렉토리 구조 — manifests/ 분리 (BL-022) | [#36](https://github.com/bluejayA/devflow-k8s-deploy/pull/36) | 2026-04-29 |
| [#31](https://github.com/bluejayA/devflow-k8s-deploy/issues/31) | entrypoint 검증 정책 일원화 (BL-019) | [#37](https://github.com/bluejayA/devflow-k8s-deploy/pull/37) | 2026-05-06 |
| [#28](https://github.com/bluejayA/devflow-k8s-deploy/issues/28) | manifest 렌더링 Jinja2 일원화 + ADR-0001 (BL-018, Codex adversarial 3 라운드 통과) | [#38](https://github.com/bluejayA/devflow-k8s-deploy/pull/38) | 2026-05-11 |
| [#27](https://github.com/bluejayA/devflow-k8s-deploy/issues/27) | Go 프레임워크 probe 자동 감지 — gin/echo/fiber (BL-017, "Direct dependency wins" + version-agnostic, Codex R1 P2x2 fix → R2 PASS) | [#39](https://github.com/bluejayA/devflow-k8s-deploy/pull/39) | 2026-05-13 |
| [#9](https://github.com/bluejayA/devflow-k8s-deploy/issues/9) | Python 스택 지원 — django/flask/fastapi 자동 감지 + multi-stage uv Dockerfile (BL-006, 3-stack 전환, Codex R1 P1x2+P2x2 → R2 P2x2 → fix, +119 tests) | [#40](https://github.com/bluejayA/devflow-k8s-deploy/pull/40) | 2026-06-05 |
