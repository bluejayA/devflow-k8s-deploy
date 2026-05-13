# Application Design

**Mode**: LIST (목록 단계)
**Depth**: Minimal
**Timestamp**: 2026-05-12T19:00:00+09:00
**Ticket**: BL-017 ([#27](https://github.com/bluejayA/devflow-k8s-deploy/issues/27))
**Unit**: 단일 unit — `scripts/stacks/go.py`

## 컴포넌트 목록

| 컴포넌트 | 책임 | 타입 |
|---------|------|------|
| `_parse_go_mod_require` | `go.mod` content를 받아 `require` 블록의 direct dependency 모듈 경로 집합을 반환. 라인 단위 텍스트 파싱(`(...)` 블록 + 단일 라인 두 형식), `//` 주석 제거, 파싱 실패 라인 skip. 검증/네트워크 호출 없음. | Util |
| `_GIN_RE` / `_ECHO_RE` / `_FIBER_RE` | 프레임워크별 모듈 경로 정규식 단일 출처. word boundary(`\b`) + non-capturing major version(`(?:/v\d+)?`). ReDoS-free. | Util (모듈 상수) |
| `_detect_go_framework` | "Direct dependency wins" 4단계 감지 알고리즘 실행. `go.mod` direct evidence → `go.sum` 약한 evidence → 복수 매치 시 `go-generic` fallback. 파일 I/O는 hint level(에러 raise 금지). symlink escape 가드. | Util |
| `GoStackModule.detect` (수정) | 기존 `StackDetectResult` 생성 책임 유지. `framework` 필드 결정 로직만 `_detect_go_framework` 위임으로 전환 (하드코딩 `"go-generic"` 제거). | Service (StackModule Protocol) |
| `GoStackModule.probe_plan` (수정) | `detect_result.framework` 값으로 분기: gin/echo/fiber → `/health`, go-generic(기타) → `/healthz` (BL-001 기본값 유지). port 결정 경로 변경 없음. | Service (StackModule Protocol) |

총 **5개 컴포넌트** (3 Util 신규 + 2 Service 수정)

## 책임 경계 (Boundaries)

- **Util 계층 (stateless)**: 정규식 + 파서 + 감지 알고리즘. 외부 I/O는 `_detect_go_framework`만 수행하며 파일 읽기 실패를 모두 흡수. 다른 Util 모듈은 순수 함수.
- **Service 계층 (StackModule Protocol)**: `GoStackModule.detect/probe_plan`은 Util을 호출해 `StackDetectResult.framework` 값으로 분기. Protocol 시그니처/dataclass 변경 없음 (F-10/F-11).
- **변경 없는 경계**: `StackModule` Protocol(base.py), `ProjectAnalyzer`, `ConfigLoader`, `text_safety`(BL-019) — 모두 BL-001/BL-018/BL-019 인터페이스 그대로 사용.

## 단일 모듈 정합성

모든 신규 컴포넌트는 `scripts/stacks/go.py` 한 파일 내부에 위치한다 (모듈 헬퍼 + 상수 + Service 메서드). 외부 파일/Protocol/dataclass 확장 없음. 이는:

1. **scope 보호** — BL-017 low priority 작업이 외부 컴포넌트로 누수되지 않음
2. **회귀 표면 최소** — JVM/Go-generic byte-identical 회귀 가드(NFR-4/NFR-5)가 단일 파일 변경에만 집중
3. **BL-006 Python 후속 재활용** — 동일한 "Util 헬퍼 + Service 분기" 패턴을 `scripts/stacks/python.py`에서 미러링 가능 (`_detect_python_framework`, `_parse_pyproject_toml` 등)

## DETAIL 단계 진입 여부

**Minimal depth → DETAIL 호출 없음**. 본 LIST가 application-design의 최종 산출물.

상세 인터페이스 명세(`_detect_go_framework`의 4단계 알고리즘, 정규식 패턴, `_parse_go_mod_require`의 라인 형식 처리)는 이미 `requirements.md` F-02 / F-03 / F-06a에 코드 수준으로 기술되어 있어 별도 DETAIL 산출물 불필요.
