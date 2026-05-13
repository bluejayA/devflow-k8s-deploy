# Requirements Analysis

**Depth**: Standard
**Timestamp**: 2026-05-12T18:00:00+09:00
**Ticket**: BL-017 ([#27](https://github.com/bluejayA/devflow-k8s-deploy/issues/27))
**Predecessor**: BL-001 (#8 — Go 스택 최소 스코프, 머지 완료)
**Sibling Pattern**: BL-014 (#7 — JVM Ktor/Micronaut probe 자동 감지, 동일 카테고리)

## User Intent

BL-001(Go 스택 지원)은 최소 스코프로 `net/http` 표준 패턴 + 사용자 override만 지원했다. **gin/echo/fiber 3대 Go HTTP 프레임워크의 의존성을 build metadata로 자동 감지**하여, framework별 관용 헬스 경로(`/health`)를 `GoStackModule.probe_plan()` 기본값으로 반환하도록 확장한다. 감지 실패 시 BL-001의 기본값(`net/http` + `/healthz`)으로 안전 폴백한다. 이 작업은 BL-014(JVM Ktor/Micronaut probe)와 동일한 "framework 감지 헬퍼 → probe_plan 분기" 패턴을 Go 쪽에 미러링하는 것이며, BL-006(Python 스택) 시 동일 패턴 재활용 목적도 겸한다.

**스코프 제한 (사용자 확정):**
- **감지 소스는 build metadata 한정** — `go.mod`의 `require` 블록(direct dependency)을 1순위 evidence로 사용. direct에서 미발견 시 `go.sum`을 약한 evidence로 폴백. **`*.go` 소스 import 라인 스캔은 하지 않음** (비용/symlink 보안/감지는 deployment hint에 불과).
- **"Direct dependency wins" 정책** (OQ-1 확정) — direct 단일 매치 → 해당 framework 채택 / direct 복수 매치 → 고정 순서 억지 선택 금지, `go-generic` 폴백 + rationale 기록 / direct 없음 + sum 단일 매치 → 약한 evidence로 해당 framework 채택 / direct 없음 + sum 복수 매치 → `go-generic` 폴백. **설명 가능성**(developer가 명시 선언한 의존성 우선) 핵심 가치.
- **3개 프레임워크 모두 `/health` 통일 (version-agnostic)** — gin/echo/fiber 일관성. echo/v2~v4, fiber/v1~v3 모두 동일 정책. 메이저 버전 분기는 BL-017 범위 밖 (OQ-2 확정). `/livez` `/readyz` 등 k8s 관용 경로는 기존 `.devflow-k8s-deploy.yml::stack.go.probe.path` override(BL-001 F-19)로 처리.
- **포트 자동화 없음** — framework별 기본 포트(gin=8080, echo=1323, fiber=3000) 자동 설정은 BL-017 범위 밖. 기존 port 결정 경로(detect_result.port → inputs.port) 그대로 유지.

## Functional Requirements

### Framework 감지 (build metadata 기반)

| ID | 요구사항 |
|----|---------|
| F-01 | `scripts/stacks/go.py`에 `_detect_go_framework(project_dir: Path) -> str` 모듈 레벨 헬퍼 추가 — 반환값: `"gin"`, `"echo"`, `"fiber"`, `"go-generic"` 중 하나 (literal string) |
| F-02 | **"Direct dependency wins"** 감지 알고리즘:<br>1. `go.mod`의 `require` 블록을 파싱하여 direct dependency 집합 구성. `require ( ... )` 블록 또는 단일 라인 `require <module> <ver>` 형식 모두 지원. **`// indirect` 마커가 있는 라인은 transitive 의존성이므로 direct 집합에서 제외** (Codex P2-1 회귀 가드).<br>2. direct 집합에 gin/echo/fiber 정규식이 매칭되는 framework가 **정확히 1개** → 해당 framework 채택<br>3. direct 집합에 매칭이 **2개 이상** → `"go-generic"` + rationale `"ambiguous: gin+echo direct deps"` 기록 (manifest 주석/로그 활용, 본 작업은 string 반환만)<br>4. direct 집합에 매칭이 **0개** → `go.sum` 라인 정규식 매칭으로 폴백. sum에서도 정확히 1개 매칭 → 해당 framework 채택 (약한 evidence). 2개 이상 또는 0개 → `"go-generic"`<br>5. **`*.go` import 라인 스캔 안 함** |
| F-03 | 정규식 (`re.compile` 모듈 상수, non-capturing version suffix + path boundary negative lookahead):<br>• `_GIN_RE = re.compile(r"\bgithub\.com/gin-gonic/gin(?:/v\d+)?(?![\w/-])")`<br>• `_ECHO_RE = re.compile(r"\bgithub\.com/labstack/echo(?:/v\d+)?(?![\w/-])")` (v3/v4 등 모든 메이저)<br>• `_FIBER_RE = re.compile(r"\bgithub\.com/gofiber/fiber(?:/v\d+)?(?![\w/-])")` (v2/v3 등 모든 메이저)<br>경계(`\b`) + non-capturing group + 후행 `(?![\w/-])` negative lookahead로 framework 본체만 정확히 식별. 후행 lookahead가 없으면 `echo-contrib`/`gin-extras`(hyphen 연결), `echo/middleware`(sub-path) 등이 false-match (Codex P2-2 회귀 가드). 메이저 버전 capture 안 함 — OQ-2 결정에 따라 |
| F-04 | 파일 I/O: `go.mod` 또는 `go.sum` 읽기 실패(없음/권한 오류/UnicodeDecodeError) 시 **에러 raise 금지** — 해당 소스를 빈 문자열로 간주하고 다음 우선순위로 진행. 감지는 hint(NFR-3) |
| F-05 | `GoStackModule.detect(project_dir)` 내부에서 `_detect_go_framework` 호출 후 `StackDetectResult.framework` 필드에 결과 기록 — 기존 `framework="go-generic"` 하드코딩 제거 |
| F-06 | symlink escape 방어: `_detect_go_framework`가 `go.mod`/`go.sum` 경로를 읽기 전에 BL-001에서 사용한 `is_within(project_dir, target)` 가드 적용. 가드 실패 시 해당 파일은 미존재로 간주 |
| F-06a | `go.mod` `require` 블록 파서: 단순 텍스트 파싱(라인 단위), `//` 주석 제거, `(...)` 블록 안의 라인을 module path로 추출. `// indirect` 마커가 있는 라인은 direct 집합에서 제외(F-02 정합). **go 컴파일러 호출 안 함** (NFR-1, NFR-6 A-06 일관). 파싱 실패 라인은 skip (에러 raise 금지) |

### probe_plan() framework별 분기

| ID | 요구사항 |
|----|---------|
| F-07 | `GoStackModule.probe_plan(detect_result)` 확장 — `detect_result.framework`로 분기: <br>• `"gin"`/`"echo"`/`"fiber"` → `ProbeSpec(kind="http", path="/health", port=port)` <br>• `"go-generic"`(또는 기타) → `ProbeSpec(kind="http", path="/healthz", port=port)` (BL-001 기본값 유지) |
| F-08 | port 결정 경로 변경 없음: `detect_result.port or inputs.port` 그대로. framework별 기본 포트 자동화는 본 작업 범위 밖 |
| F-09 | 사용자 override(`stack.go.probe.path`) 우선순위 변경 없음: ConfigLoader 파싱 → Analyzer `_apply_probe_overrides`로 ProbeConfig.path 치환 → probe_plan 반환값보다 우선 (BL-001 F-19 정책 유지) |

### 기존 시스템과의 통합 (변경 최소화)

| ID | 요구사항 |
|----|---------|
| F-10 | `StackModule` Protocol(`scripts/stacks/base.py`) 변경 없음 — `probe_plan` 시그니처 유지 |
| F-11 | `StackDetectResult.framework` 필드 변경 없음 — 기존 string 타입에 새 enum 값(`"gin"`, `"echo"`, `"fiber"`) 추가만. dataclass 확장 불필요 |
| F-12 | `ProjectAnalyzer` 변경 없음 — framework 결정은 StackModule 내부 책임 |
| F-13 | `text_safety` 위임(BL-019) 일관성 유지 — `probe.path` config override 검증 경로 그대로. 본 작업은 검증 로직 추가/변경 없음 |

### 관찰성 / 디버깅

| ID | 요구사항 |
|----|---------|
| F-14 | `AnalysisResult` 로깅(또는 rationale 주석) 시 `framework` 값이 노출되도록 기존 경로 그대로 사용. BL-021(manifest rationale stack-aware)이 framework까지 자연스럽게 표시할지 별도 검증은 본 작업 회귀 테스트 1건으로 확인 (변경 없으면 통과) |

## Non-Functional Requirements

| ID | 요구사항 | 측정 가능 기준 |
|----|---------|---------------|
| NFR-1 | **성능** — 감지 추가 비용 미미 | `_detect_go_framework` 단일 호출 ≤ 5ms (1000줄 미만 go.sum 기준). 측정 강제 안 함 |
| NFR-2 | **ReDoS 방어** | 모든 정규식은 catastrophic backtracking 패턴 회피 (`\b...\b` 고정 어절 매칭, 임의 wildcards 금지) |
| NFR-3 | **신뢰성 — 감지는 deployment hint** | 감지 실패(파일 없음/파싱 오류)가 빌드 파이프라인 실패를 유발하지 않음. 항상 안전한 fallback (`"go-generic"` + `/healthz`)으로 작동 |
| NFR-4 | **JVM 회귀 0** | BL-001 Phase 1의 JVM manifest 4종 골든 스냅샷 byte-identical 유지 (Go 변경이 JVM 출력에 영향 없음을 보장) |
| NFR-5 | **Go-generic 회귀 0** | BL-001 net/http 케이스(go.sum 없거나 framework 미감지) 동작 byte-identical 유지 — 기존 E2E 통과 |
| NFR-6 | **테스트 가드** | 신규 단위 테스트 ≥ 13건 (실측 31건):<br>• `_detect_go_framework` direct 단일 매치: gin/echo/fiber 각 1건 (3건)<br>• direct 복수 매치 → `go-generic` 폴백 1건<br>• direct 없음 + sum 단일 매치 → 약한 evidence 채택 1건<br>• direct 없음 + sum 복수 매치 → `go-generic` 폴백 1건<br>• 파일 없음 (go.mod/go.sum 모두) → `go-generic` 1건<br>• symlink escape 가드 1건<br>• 메이저 버전 호환: `echo/v4`, `fiber/v2` 매칭 확인 2건<br>• `probe_plan` 분기 4건 (gin/echo/fiber/generic)<br>• **indirect 마커 처리**: 블록/단일 라인에서 indirect skip + gin direct + echo indirect 회귀 가드 3건 (Codex P2-1)<br>• **prefix 모듈 false-positive 방어**: `echo-contrib`/`gin-extras`/`fiber-utils` regex 비매칭 + sub-path `echo/middleware` 비매칭 + detect-level 회귀 가드 3건 (Codex P2-2) |
| NFR-7 | **외부 리뷰 게이트** | CONSTRUCTION 완료 후 `/codex:review` 1차 + (필요 시) agent-council 단독 deep. BL-001 선례에 따라. low-priority 작업이므로 council 1라운드면 충분 |

## Technology Stack

| 계층 | 선택 | 소스 | 비고 |
|------|------|------|------|
| Language | Python 3.11+ | Pre-specified Tech Stack (CLAUDE.md) + Brownfield 감지 | 변경 없음 |
| Package Manager | uv | CLAUDE.md | 변경 없음 |
| Test Framework | pytest | Brownfield 감지 | 변경 없음 |
| Linter | ruff | CLAUDE.md | 변경 없음 |
| Build Targets | go.sum / go.mod 텍스트 파싱 | F-02 (감지 정책) | 신규 (Python 측에서 텍스트 정규식만, Go 컴파일 의존성 없음) |

→ **사전 지정 (질문 스킵)**.

## Assumptions

- **A-01 (Direct dependency wins)** — 한 프로젝트가 gin/echo/fiber 중 하나를 **명시적 direct dependency**로 사용한다고 가정. 복수 의존성 동시 존재 시: **go.mod direct 단일 매치 → 채택 / direct 복수 또는 sum 복수 → `"go-generic"` 폴백** (F-02 알고리즘). 설명 가능성(developer 명시 선언 우선) 핵심 가치 (OQ-1 확정).
- **A-02 (Detection is hint, not gate)** — framework 미감지가 빌드 실패를 유발하지 않음. 항상 `"go-generic"` + `/healthz` 안전 폴백.
- **A-03 (Net/http baseline 불변)** — BL-001의 `/healthz` 기본값은 BL-017에서 변경하지 않음. framework 감지 성공 시에만 `/health`로 전환.
- **A-04 (Config override 최우선)** — `.devflow-k8s-deploy.yml::stack.go.probe.path`는 framework 감지보다 우선. 기존 ConfigLoader → Analyzer `_apply_probe_overrides` 경로(BL-001 F-19) 그대로.
- **A-05 (Port 자동화 없음)** — framework별 기본 포트(gin=8080, echo=1323, fiber=3000) 자동 설정은 본 작업 범위 밖. 기존 port 결정 경로 유지.
- **A-06 (Test stub 우선)** — 테스트는 임시 디렉토리에 go.sum/go.mod 텍스트 파일을 생성하는 fixture로 작성 (real `go` 바이너리 의존성 없음).
- **A-07 (Version-agnostic policy)** — echo/fiber 모든 지원 메이저 버전(echo/v2~v4, fiber/v1~v3)에 동일한 기본 probe path 적용. 메이저 버전별 분기는 BL-017 범위 밖, 필요해질 때 별도 backlog 신설 (OQ-2 확정).

## Open Questions

_(없음 — 모든 미해결 항목이 사용자 결정으로 해소됨)_

### Resolved Questions (이력)

- **OQ-1 (복수 프레임워크 동시 감지 시 동작) — RESOLVED 2026-05-12**
  - 결정: **"Direct dependency wins"** — go.mod `require` 블록을 1순위 evidence, go.sum을 약한 evidence 폴백. direct 또는 sum 복수 매치 시 `"go-generic"` 폴백 (고정 순서 억지 선택 금지). 설명 가능성(developer 명시 선언 우선) 핵심 가치.
  - 반영 위치: F-02 알고리즘 + A-01 가정 + NFR-6 테스트 가드 (복수 매치 fallback 2건 추가).

- **OQ-2 (Echo/Fiber 메이저 버전 분리) — RESOLVED 2026-05-12**
  - 결정: **버전 무관 단일 정책 (version-agnostic)** — echo/v2~v4, fiber/v1~v3 모두 `/health`. 메이저 버전 분기는 BL-017 범위 밖, 실제 필요 발생 시 별도 backlog 신설.
  - 반영 위치: F-03 정규식(`(?:/v\d+)?` non-capturing) + A-07 가정 + NFR-6 테스트 가드 (메이저 버전 호환 매칭 2건).

## Change Log

- 2026-05-12T18:00:00+09:00 INITIAL: BL-017 첫 분석. Standard depth. 핵심 질문 2개(감지 소스 정책 / fiber probe path) 사용자 답변 반영.
- 2026-05-12T18:30:00+09:00 UPDATE (QUESTIONS): OQ-1 "Direct dependency wins" 정책 확정 → F-02 알고리즘 재정의 + A-01 갱신 + F-06a `go.mod require` 파서 신규 + NFR-6 테스트 13건으로 확장. OQ-2 version-agnostic 단일 정책 확정 → F-03 정규식 non-capturing + A-07 신규.
- 2026-05-13T20:30:00+09:00 UPDATE (Codex P2 회귀 fix): Codex review에서 두 가지 functional regression 발견 → 명세 정밀화. (1) F-02 step 1 + F-06a: `// indirect` 마커 라인은 direct 집합에서 제외 (transitive는 direct가 아님). 미반영 시 gin direct + echo indirect 일반 구성이 오분류. (2) F-03 정규식: 후행 `(?![\w/-])` negative lookahead 추가. 미반영 시 `echo-contrib`/`gin-extras`/`echo/middleware` 등이 framework로 false-match. NFR-6 테스트 가드 13 → 31건으로 확장.
