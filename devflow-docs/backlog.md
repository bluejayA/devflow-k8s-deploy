# Backlog

_Last updated: 2026-04-24 — BL-018 신규 생성 (manifest 생성 방식 일관성 복원)_

---

## Next

BL-015 완료로 다국어 스택 확장 Protocol 경계 정리됨. BL-001 Go 스택 착수.

| ID | 제목 | 이슈 | 분류 |
|----|------|------|------|
| **BL-001** | Go 스택 지원 (최소 스코프: net/http + go.mod + Dockerfile + tier 기본값) | [#8](https://github.com/bluejayA/devflow-k8s-deploy/issues/8) | 스택 확장 |
| **BL-002** | auto-fix 루프 (검증 실패 시 자동 수정 3회) | [#12](https://github.com/bluejayA/devflow-k8s-deploy/issues/12) | DX |
| **BL-005** | PodDisruptionBudget / topologySpreadConstraints | [#14](https://github.com/bluejayA/devflow-k8s-deploy/issues/14) | 고가용성 |

---

## Open

### 스택 확장

| ID | 제목 | 이슈 | 목표 버전 |
|----|------|------|---------|
| **BL-006** | Python 스택 지원 | [#9](https://github.com/bluejayA/devflow-k8s-deploy/issues/9) | v0.4 |
| **BL-007** | React(nginx) 스택 지원 | [#10](https://github.com/bluejayA/devflow-k8s-deploy/issues/10) | v0.5 |

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
| **BL-018** | manifest 생성 방식 일관성 복원 (Jinja2 vs dict+yaml.dump 혼용 해소) | [#28](https://github.com/bluejayA/devflow-k8s-deploy/issues/28) | medium |

### JVM 제약 / 정확도

| ID | 제목 | 이슈 | 우선순위 |
|----|------|------|---------|
| **BL-011** | 중첩 모듈(multi-level) 지원 | [#4](https://github.com/bluejayA/devflow-k8s-deploy/issues/4) | medium |
| **BL-012** | stateful 감지 AST 파싱으로 정확도 개선 | [#5](https://github.com/bluejayA/devflow-k8s-deploy/issues/5) | medium |
| **BL-013** | runAsUser / fsGroup 커스터마이징 지원 | [#6](https://github.com/bluejayA/devflow-k8s-deploy/issues/6) | low |
| **BL-014** | Ktor / Micronaut HTTP probe 자동 감지 | [#7](https://github.com/bluejayA/devflow-k8s-deploy/issues/7) | low |

### Go 스택 확장

| ID | 제목 | 이슈 | 우선순위 | 의존 |
|----|------|------|---------|------|
| **BL-017** | Go 프레임워크 probe 자동 감지 — gin/echo/fiber | [#27](https://github.com/bluejayA/devflow-k8s-deploy/issues/27) | low | BL-001 |

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
