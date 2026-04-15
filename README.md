# devflow-k8s-deploy

[English](#english) | 한국어

![version](https://img.shields.io/badge/version-0.1.0-orange)
![status](https://img.shields.io/badge/status-INCEPTION-yellow)

**Kubernetes 배포 준비 스킬** — Claude Code를 위한 독립 스킬로, "시니어 엔지니어의 판단력을 인코딩한" Dockerfile + Kubernetes manifest 생성 도구입니다.

## 한 줄 요약

`/devflow-k8s-deploy` 한 번으로 프로젝트에 **프로덕션 보안 체크리스트가 반영된 Dockerfile + k8s manifest**를 생성합니다. 단순 템플릿이 아니라 **왜 이 설정인지** 맥락 주석이 함께 달립니다.

## 설계 원칙

1. **생성만, 실제 배포는 하지 않음** — 보안 경계가 명확한 도구. MVP는 생성·검증까지이며 실제 샌드박스 배포는 향후 확장 범위.
2. **맥락 주석 필수** — 모든 보안 설정(`runAsNonRoot`, `readOnlyRootFilesystem`, digest pinning 등)에 왜 이 선택인지 인라인 주석.
3. **설정 3계층** — 스킬 내장 기본값 → 조직 커스텀(`~/.claude/devflow-k8s-deploy.yml`) → 프로젝트 오버라이드(`.devflow-k8s-deploy.yml`).
4. **AIDLC 비종속** — `aidlc-devflow` 플러그인 설치 없이 단독 사용 가능. 조직 표준 도구로 재활용 전제.

## 현재 상태

- **v0.1.0 — INCEPTION** (2026-04-15 시작)
- 개발 방법론: `aidlc-devflow` 플러그인으로 INCEPTION → CONSTRUCTION 순차 진행
- 관련 이슈: [bluejayA/aidlc-devflow#41 (BL-031)](https://github.com/bluejayA/aidlc-devflow/issues/41)

## MVP 범위 (계획)

- Dockerfile 생성 (멀티스테이지, 비루트 사용자)
- Kubernetes manifest 생성 (`deployment.yaml` + `service.yaml`)
- 프로덕션 보안 체크리스트 반영: `runAsNonRoot` / `readOnlyRootFilesystem` / `allowPrivilegeEscalation: false` / `seccompProfile: RuntimeDefault` / `capabilities.drop: ALL` / `automountServiceAccountToken: false` / CPU·메모리 requests+limits / liveness·readiness probe / digest pinning
- `docker build` 테스트 + `kubectl apply --dry-run=client` 검증
- 이미지 스캐너 안내 (trivy, hadolint)

## MVP 지원 스택

- **백엔드**: Node.js / Python / Kotlin(Java)
- **프론트엔드**: React (멀티스테이지 build → nginx 서빙)

## 향후 확장 범위 (MVP 이후)

- Helm chart 생성
- CI/CD 파이프라인 (GitHub Actions)
- 환경 분리 (dev / staging / prod)
- PodDisruptionBudget, NetworkPolicy 기본 deny 템플릿
- `kubectl apply --dry-run=server` (MCP 서버 연동 시)
- **실제 샌드박스 배포 + smoke test**

## 설치 (예정)

```bash
# Claude Code
/plugin install bluejayA/devflow-k8s-deploy

# 또는 devflow-marketplace 경유 (예정)
/plugin install devflow-k8s-deploy@devflow-marketplace
```

---

<a id="english"></a>
# devflow-k8s-deploy (English)

[한국어](#devflow-k8s-deploy) | English

**Kubernetes deployment preparation skill** — An independent Claude Code skill that encodes senior engineer judgment into Dockerfile + Kubernetes manifest generation.

## TL;DR

Run `/devflow-k8s-deploy` once and get **Dockerfile + k8s manifests with production security checklist applied**, not a plain template — every security setting comes with an inline comment explaining *why*.

## Design Principles

1. **Generate only, never deploy** — Clear security boundary. MVP covers generation and validation; real sandbox deployment is a future extension.
2. **Rationale comments required** — Every security setting (`runAsNonRoot`, `readOnlyRootFilesystem`, digest pinning, etc.) carries an inline comment explaining the choice.
3. **3-layer configuration** — Skill defaults → Organization customization (`~/.claude/devflow-k8s-deploy.yml`) → Project overrides (`.devflow-k8s-deploy.yml`).
4. **AIDLC-independent** — Usable standalone without the `aidlc-devflow` plugin. Designed for reuse as an organizational standard tool.

## Current Status

- **v0.1.0 — INCEPTION** (started 2026-04-15)
- Development methodology: Sequential INCEPTION → CONSTRUCTION via the `aidlc-devflow` plugin
- Related issue: [bluejayA/aidlc-devflow#41 (BL-031)](https://github.com/bluejayA/aidlc-devflow/issues/41)

## MVP Scope (planned)

- Dockerfile generation (multi-stage, non-root user)
- Kubernetes manifests (`deployment.yaml` + `service.yaml`)
- Production security checklist: `runAsNonRoot` / `readOnlyRootFilesystem` / `allowPrivilegeEscalation: false` / `seccompProfile: RuntimeDefault` / `capabilities.drop: ALL` / `automountServiceAccountToken: false` / CPU·memory requests+limits / liveness·readiness probes / digest pinning
- `docker build` test + `kubectl apply --dry-run=client` validation
- Image scanner guidance (trivy, hadolint)

## Supported Stacks (MVP)

- **Backend**: Node.js / Python / Kotlin (Java)
- **Frontend**: React (multi-stage build → nginx serving)

## Future Scope (post-MVP)

- Helm chart generation
- CI/CD pipeline (GitHub Actions)
- Environment separation (dev / staging / prod)
- PodDisruptionBudget, NetworkPolicy default-deny templates
- `kubectl apply --dry-run=server` (when MCP server integration arrives)
- **Real sandbox deployment + smoke test**

## Install (planned)

```bash
# Claude Code
/plugin install bluejayA/devflow-k8s-deploy

# or via devflow-marketplace (planned)
/plugin install devflow-k8s-deploy@devflow-marketplace
```

## License

MIT — see [LICENSE](LICENSE).
