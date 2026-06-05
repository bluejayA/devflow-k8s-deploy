# Session Summary — BL-006 Python 스택 지원

**Ticket**: BL-006 ([#9](https://github.com/bluejayA/devflow-k8s-deploy/issues/9))
**Started**: 2026-05-13T22:51:34Z
**Predecessor Patterns**: BL-001 (Go 스택 최소 스코프) + BL-017 (Go gin/echo/fiber framework 자동 감지)

## Current State

- **Phase**: CONSTRUCTION 완료 — 외부 리뷰 통과, PR 게이트 대기
- **Stage**: Codex R1→R2 (P1 전부 해소, P2 전부 반영), 1047 passed (119 신규)
- **Commit**: 95241b2 (R2 fix). 7 commit: Phase α/β/γ/δ + R1 fix + R2 fix
- **Branch**: feature/python-stack-support (worktree=.worktrees/feature-python-stack-support)

## Completed Work

### INCEPTION
- [x] workspace-detection — brownfield, v0.5.0, 928 tests, BL-017 패턴 재활용 전제로 변경 대상 파일 식별 완료
- [x] complexity-declaration — Standard 확정 (BL-017 미러링이지만 Python 매니페스트 양분 + Dockerfile 빌드 정책 OQ 다수 예상)
- [x] requirements-analysis — Q1(Dockerfile=uv multi-stage + lockfile 분기)/Q2(서버=framework별 분기, fastapi=uvicorn) 사용자 확정 + 사용자 보정 2건 반영 (F-06-1 requirements 스코프 제한, F-20-1 CMD 생성 3조건 통합). 31 functional + 7 NFR + 6 assumptions + 2 sub-OQ + Final Policy Summary. open questions = 0.
- [x] workflow-planning — A안(단일 PR + 내부 3-Phase α/β/γ/δ) 확정. application-design included / units-generation skipped / user-stories+nfr-requirements skipped. worktree=feature/python-stack-support (baseline 928 passed).
- [x] application-design — LIST 14 컴포넌트 (12a/12b/12c 외부 통합 분할) + DETAIL (Public interface 실제 Protocol 정합 / SD-1 알고리즘 확정 / F-20-1 6 케이스 매트릭스 / python.tmpl 13 keys Jinja2 분기 / Phase α/β/γ/δ → 컴포넌트 매핑). R1 spec-reviewer 1차 FAIL(P0×4) → 정정 → 2차 PASS-with-notes (P1-new typo + P2-new 2건 모두 반영).

### CONSTRUCTION
(pending)

## Key Decisions

- **2026-05-13** — workspace-gate C 선택: reverse-engineering 스킵. 이유: BL-017 INCEPTION 자료(`devflow-docs/.archive/inception-2026-05-13T225108Z/`)에 동일 영역(scripts/stacks/, templates/) 심층 분석이 이미 존재 → 중복 분석 불필요.
- **2026-05-13** — Q1 Dockerfile 빌드 패턴: **multi-stage uv** 확정 (옵션 1). 이유: "쿠버네티스 대상 배포 자동화 = 작고/재현가능/런타임 깨끗" + devflow-k8s-deploy 자체가 uv 사용. lockfile 분기 정책(uv.lock→frozen / pyproject만→non-frozen+warning / requirements.txt only→uv pip install) 명시. pip multi-stage는 backlog(conservative mode), single-stage는 비추천.
- **2026-05-13** — Q2 서버 자동 선택: **framework별 분기 + fastapi=uvicorn** 확정 (codex 권장). 이유: k8s replica/HPA로 수평 확장 ≫ 컨테이너 내 multi-worker. dependency-conservative — 추론 서버 패키지가 매니페스트에 없으면 자동 install 금지(gap 기록 + override 안내). generic은 CMD 자동 생성 없음.
- **2026-05-13** — **사용자 보정 #1 (requirements 스코프 제한)**: 인식 대상 = `pyproject.toml [project.dependencies]` + `[tool.poetry.dependencies]` + **root `requirements.txt`만**. `requirements-dev.txt`, `requirements/*.txt`, `constraints.txt`, `-r`/`-c` 참조 모두 범위 밖 (F-06-1). 이유: 매니페스트 fan-out으로 인한 정책 번짐 차단. 추후 명시 config 옵션 도입은 후속 backlog.
- **2026-05-13** — **사용자 보정 #2 (CMD 생성 3조건)**: framework 감지 + server pkg in direct deps + entrypoint 추론 — 3조건 모두 통과 시에만 framework별 default CMD 생성, 하나라도 실패 시 generic 폴백 + gap 기록 + override 안내 (F-20-1). 이유: 복수 프레임워크/패키지 누락/entrypoint 실패를 단일 원칙으로 통합 → 책임 분리 3-layer(감지/설치/실행) 선명화.

## Next Steps (재개 시작점 — 2026-05-18 mid-cycle stop)

**INCEPTION 완료 직후, CONSTRUCTION 시작 직전 상태**.

재개 시 흐름:
1. `aidlc-using-devflow` 자동 진입 → `devflow-state.md::Current Phase=INCEPTION` + `Current Stage=inception-complete-checkpoint` 인식 → resume gate A/B 제시
2. A 선택 → INCEPTION → CONSTRUCTION 전환 (`Current Phase=CONSTRUCTION`) + `aidlc-construction-orchestrator` 호출
3. CONSTRUCTION 분기: workflow-plan.md `## Approved Stages` 기준 = units-generation skipped → **code-generation 직행** (TDD Standard depth)
4. **Phase α 시작** (감지 layer): `scripts/stacks/python.py` 신규 + L1 컴포넌트 6개 (정규식 상수 + 매니페스트 파서 + framework/version 감지 + 안전 IO). 워크트리=`.worktrees/feature-python-stack-support` (base 45b0a72, baseline 928 passed)

재개 시 즉시 작업할 파일:
- 코드 작성: `.worktrees/feature-python-stack-support/scripts/stacks/python.py` (신규)
- 테스트 작성: `.worktrees/feature-python-stack-support/tests/stacks/test_python.py` (신규)
- 참조 미러링 source: `scripts/stacks/go.py` (BL-017 패턴)

재개 명령 예시: "devflow 재개" 또는 "BL-006 이어서"

## Traps to Avoid

- **단일 stage Dockerfile**: BL-006 Q1에서 옵션 3(uv single-stage)로 폐기. 이유: 최종 이미지에 uv/build deps 포함 → k8s 배포 자동화 기본값으로 부적합. 재시도 금지.
- **모든 framework uvicorn 통일**: BL-006 Q2에서 폐기. 이유: django 관용 이탈 + WSGI 워커 제어 한계. framework별 분기가 맞음. 재시도 금지.
- **서버 dependency 자동 주입**: 기본 비활성(F-22-1)으로 고정. 이유: 사용자 매니페스트가 진실 — 추론으로 dep 추가 금지. opt-in 플래그(`auto_install_server=true`)는 별도 backlog(SD-2). 재시도 금지.
- **"락 없으면 fail"**: F-14에서 폐기. 이유: 기존 Python 프로젝트 상당수가 lockfile 부재 → 첫 배포 차단되면 zero-config 가치 훼손. non-frozen + warning 정책 채택. 재시도 금지.
- **requirements 파일 fan-out (`requirements-dev.txt`, `requirements/*.txt`, `constraints.txt`, `-r`/`-c` 참조)**: F-06-1에서 차단. 이유: 어디까지 따라가야 하나에 대한 정책 번짐 → root `requirements.txt`로 한정. 명시 config 옵션 도입 전에는 재시도 금지.
- **framework 단독 감지만으로 CMD 생성**: F-20-1에서 차단. server pkg + entrypoint 추론까지 모두 통과해야만 CMD 생성. 한 조건이라도 실패 시 generic 폴백. "감지했으니 일단 만들고 본다" 패턴 재시도 금지.

## Reference Artifacts

- BL-001 (Go 스택 최소 스코프): `devflow-docs/.archive/inception-2026-05-13T225108Z/` 참조 가능
- BL-017 (Go framework 감지): `devflow-docs/.archive/inception-2026-05-13T225108Z/{requirements,application-design,workflow-plan}.md` ← BL-006 미러링 source
- BL-017 construction: `devflow-docs/.archive/construction-2026-05-13T225108Z/go-framework-probe-detection/` ← 패턴 참조
- 미러링 타겟 코드: `scripts/stacks/go.py` (framework 감지 헬퍼), `templates/dockerfile/go.tmpl`

## Traps to Avoid

(없음 — 신규 세션)

## Reference Artifacts

- BL-001 (Go 스택 최소 스코프): `devflow-docs/.archive/inception-2026-04-23T233550/` (있다면)
- BL-017 (Go framework 감지): `devflow-docs/.archive/inception-2026-05-13T225108Z/{requirements,application-design,workflow-plan}.md`
- BL-017 construction: `devflow-docs/.archive/construction-2026-05-13T225108Z/go-framework-probe-detection/`
- 미러링 타겟 코드: `scripts/stacks/go.py` (framework 감지 헬퍼), `templates/dockerfile/go.tmpl`
