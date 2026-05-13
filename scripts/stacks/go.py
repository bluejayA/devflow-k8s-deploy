"""GoStackModule — Go 스택 감지 및 계획 생성 (BL-001).

판별 시그널:
  - 루트의 `go.mod` 존재 여부

엔트리포인트 결정 (F-04 ~ F-06, A-08):
  detect 단계에서는 후보 수집만 수행한다.
    - 루트 main.go 존재 → entrypoint="." (확정)
    - 그 외에는 cmd/<name>/main.go 후보 디렉토리명 목록 수집
      → entrypoint="" (미결정 sentinel) + cmd_candidates=<list>

  build_plan 단계에서 UserInputs.app_name과 후보를 매칭해 최종 결정.

이미지 정책:
  - builder: golang:{go_version}-alpine
  - runner:  gcr.io/distroless/static-debian12:nonroot (UID 65532 내장)

보안:
  - app_name / entrypoint는 build_cmd 문자열에 합성되므로 shell 주입 방어 (F-29)
  - 모든 파일 접근은 read_text_limited + is_within (symlink escape 방어)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

from scripts._shared.errors import GoBuildPlanError, GoDetectionError
from scripts._shared.fileio import is_within, read_text_limited
from scripts._shared.text_safety import validate_go_entrypoint
from scripts._shared.types import (
    BuildPlan,
    ProbeConfig,
    ProbeSpec,
    ResourceDefaults,
    StackDetectResult,
    UserInputs,
)
from scripts.stacks.base import ResourceHint

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_GO_VERSION = "1.22"  # F-23: go.mod 파싱 실패 또는 go 지시어 부재 시 fallback
_DEFAULT_PORT = 8080  # F-07: probe 기본 포트

# BL-017 F-07: /health 경로를 채택하는 framework 집합 (version-agnostic, A-07).
# NOTE: 현재 멤버는 `_match_frameworks`가 식별하는 framework 목록과 우연히 일치하나
# 의미가 다르다 — `_HEALTH_FRAMEWORKS`는 probe 경로 정책이고, _match_frameworks는
# 감지 대상이다. 향후 `/healthz`를 쓰는 framework(예: chi)가 감지 대상에 추가되면
# 두 집합이 자연스럽게 갈라진다.
_HEALTH_FRAMEWORKS: frozenset[str] = frozenset({"gin", "echo", "fiber"})

_GO_MODULE_RE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
_GO_VERSION_RE = re.compile(r"^go\s+(\d+(?:\.\d+){0,2})", re.MULTILINE)

# BL-017 F-03: Go HTTP framework 식별 정규식. word boundary(\b) + non-capturing
# major version suffix(?:/v\d+)?로 echo/v3·v4, fiber/v2·v3 등 모든 메이저 호환.
# ReDoS-free: 고정 어절 매칭 + 정량 wildcard 없음.
#
# 후행 ``(?![\w/-])``는 path boundary negative lookahead — framework 본체 또는
# ``/vN`` major version suffix 직후에 word/``/``/``-`` 어느 것도 와선 안 된다.
# 이렇게 하면 ``echo-contrib``, ``gin-extras``(`-` 연결), ``echo/middleware``
# (sub-path)는 매칭에서 제외되어 framework 본체만 정확히 식별.
# (Codex P2-2 회귀 가드)
_GIN_RE = re.compile(r"\bgithub\.com/gin-gonic/gin(?:/v\d+)?(?![\w/-])")
_ECHO_RE = re.compile(r"\bgithub\.com/labstack/echo(?:/v\d+)?(?![\w/-])")
_FIBER_RE = re.compile(r"\bgithub\.com/gofiber/fiber(?:/v\d+)?(?![\w/-])")

# BL-017 F-06a: go.mod `require` 블록 파서 보조 정규식
_REQUIRE_BLOCK_START_RE = re.compile(r"^\s*require\s*\(")
_REQUIRE_BLOCK_END_RE = re.compile(r"^\s*\)")
_REQUIRE_SINGLE_LINE_RE = re.compile(r"^\s*require\s+(\S+)\s+\S+")

# Go 표준 `// indirect` 마커 감지 (transitive 의존성 식별, F-02 direct-only).
_INDIRECT_MARKER_RE = re.compile(r"//\s*indirect\b")

# DNS-1123 subset (UserInputs.app_name 재검증, F-29 (a))
_DNS_1123_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

# Go 리소스 tier (JVM 대비 낮춤, F-08).
_RESOURCE_TIERS: dict[str, dict[str, str]] = {
    "small": {
        "cpu_request": "50m",
        "memory_request": "64Mi",
        "cpu_limit": "250m",
        "memory_limit": "128Mi",
    },
    "medium": {
        "cpu_request": "100m",
        "memory_request": "128Mi",
        "cpu_limit": "500m",
        "memory_limit": "256Mi",
    },
    "large": {
        "cpu_request": "250m",
        "memory_request": "256Mi",
        "cpu_limit": "1000m",
        "memory_limit": "512Mi",
    },
}

_BUILDER_IMAGE_TEMPLATE = "golang:{go_version}-alpine"
_RUNNER_IMAGE = "gcr.io/distroless/static-debian12:nonroot"

# F-28: 모호 cmd 에러 메시지에서 표시할 후보 상한
_MAX_LISTED_CANDIDATES = 10


# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────────────────


def _parse_go_mod(go_mod_path: Path) -> tuple[str, str | None]:
    """go.mod 파싱 — (module_path, go_version) 반환 (F-21).

    Args:
        go_mod_path: go.mod 절대 경로.

    Returns:
        (module_path, go_version) — go_version은 `go 1.x[.y]` 지시어 부재 시 None.

    Raises:
        GoDetectionError: 파일 읽기 실패 또는 module 지시어 부재.
    """
    try:
        content = read_text_limited(go_mod_path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise GoDetectionError(f"go.mod 읽기 실패: {go_mod_path.name}: {exc}") from exc

    module_match = _GO_MODULE_RE.search(content)
    if not module_match:
        raise GoDetectionError(
            f"go.mod에 module 지시어 없음: {go_mod_path.name}"
        )
    module_path = module_match.group(1)

    version_match = _GO_VERSION_RE.search(content)
    go_version = version_match.group(1) if version_match else None

    return module_path, go_version


def _read_go_file_safe(project_dir: Path, filename: str) -> str:
    """프로젝트 루트의 파일을 안전하게 읽어 텍스트 반환 (BL-017, F-04/F-06).

    실패 케이스(없음/권한/디코딩/symlink escape) 모두 빈 문자열로 흡수 — 감지는
    hint(NFR-3)이므로 raise 금지.

    **흡수하지 않는 예외** (시스템 레벨 BaseException):
      - ``MemoryError``: 파일 크기 5MB 제한(`read_text_limited`)을 통과한 뒤에도
        시스템 메모리 부족 시 발생 가능. 정상 종료 신호이므로 흡수하지 않음.
      - ``KeyboardInterrupt`` / ``SystemExit``: 사용자/시스템의 명시적 종료 의도.
    """
    target = project_dir / filename
    if not target.is_file():
        return ""
    if not is_within(project_dir, target):
        return ""
    try:
        return read_text_limited(target)
    except (OSError, UnicodeDecodeError, ValueError):
        return ""


def _looks_like_module_path(value: str) -> bool:
    """Go 모듈 경로 sanity check — host(`.`) + path(`/`) 모두 포함 (BL-017).

    완전한 검증이 아닌 malformed 라인 방어용 휴리스틱. 후속 정규식
    (`_GIN_RE`/`_ECHO_RE`/`_FIBER_RE`) 매칭이 이중 필터 역할을 하므로
    false-positive(예: ``localhost.example/anything``)는 framework 검출
    단계에서 자연스럽게 걸러진다.
    """
    return "/" in value and "." in value


def _is_indirect_line(raw: str) -> bool:
    """`// indirect` 마커가 있는 go.mod require 라인 식별 (F-02, BL-017).

    Go 표준 출력 형식 ``<module> <version> // indirect``를 감지한다.
    F-02 "Direct dependency wins"에 따라 indirect 라인은 direct 집합에서 제외.
    """
    return _INDIRECT_MARKER_RE.search(raw) is not None


def _parse_go_mod_require(content: str) -> set[str]:
    """go.mod `require` 블록과 단일 라인 require에서 **direct** module path 집합 추출 (F-06a).

    지원 형식:
      - 블록:  ``require ( ... )`` — 괄호 내부 라인의 첫 토큰
      - 단일:  ``require <module> <version>``

    규칙:
      - ``//`` 이후는 끝주석으로 제거.
      - ``// indirect`` 마커 라인은 transitive 의존성이므로 skip (F-02 "Direct
        dependency wins"). Codex P2-1 회귀 가드.
      - module path 휴리스틱(`.` + `/` 포함) 미통과 라인은 silent skip.
      - 텍스트 파싱만 수행, 검증/네트워크 호출 없음.

    Args:
        content: go.mod 전체 텍스트.

    Returns:
        direct dependency module path 집합 (예: ``{"github.com/gin-gonic/gin"}``).
    """
    deps: set[str] = set()
    in_block = False
    for raw in content.splitlines():
        indirect = _is_indirect_line(raw)
        line = raw.split("//", 1)[0]
        stripped = line.strip()
        if not stripped:
            continue

        if in_block:
            if _REQUIRE_BLOCK_END_RE.match(line):
                in_block = False
                continue
            if indirect:
                continue
            tokens = stripped.split()
            if len(tokens) >= 2 and _looks_like_module_path(tokens[0]):
                deps.add(tokens[0])
            continue

        if _REQUIRE_BLOCK_START_RE.match(line):
            in_block = True
            continue

        single = _REQUIRE_SINGLE_LINE_RE.match(line)
        if single:
            if indirect:
                continue
            module_path = single.group(1)
            if _looks_like_module_path(module_path):
                deps.add(module_path)

    return deps


def _match_frameworks(text: str) -> list[str]:
    """텍스트에서 매칭되는 framework 이름 목록 반환 (BL-017 헬퍼).

    정규식 매칭 결과를 알파벳 안정 순으로 반환하여 테스트 결정성 보장.
    """
    matches: list[str] = []
    if _GIN_RE.search(text):
        matches.append("gin")
    if _ECHO_RE.search(text):
        matches.append("echo")
    if _FIBER_RE.search(text):
        matches.append("fiber")
    return matches


def _detect_go_framework(project_dir: Path) -> str:
    """Go HTTP framework 식별 — "Direct dependency wins" 4단계 (F-02, BL-017).

    알고리즘:
      1. ``go.mod``의 ``require`` 블록을 파싱하여 direct dependency 집합 구성.
      2. direct에 gin/echo/fiber 정확히 1개 매치 → 해당 framework 채택.
      3. direct 복수 매치 → ``"go-generic"`` 폴백 (고정 순서 억지 선택 금지).
      4. direct 0개 매치 → ``go.sum`` 폴백 (약한 evidence).
         sum 단일 매치 → 해당 framework / sum 복수 또는 0개 → ``"go-generic"``.

    설계 가치:
      - **설명 가능성**: developer가 명시적으로 선언한 의존성을 1순위로 신뢰.
      - **감지는 hint** (NFR-3): 파일 I/O 실패는 raise 금지, ``"go-generic"`` 안전 폴백.
      - **symlink escape 방어** (F-06): ``is_within`` 가드 적용.

    Args:
        project_dir: 프로젝트 루트.

    Returns:
        ``"gin"``, ``"echo"``, ``"fiber"``, 또는 ``"go-generic"``.
    """
    direct_text = _read_go_file_safe(project_dir, "go.mod")
    if direct_text:
        direct_deps = _parse_go_mod_require(direct_text)
        # go.sum과 동일한 텍스트 기반 인터페이스(_match_frameworks)를 재사용하기
        # 위해 direct 집합을 다시 줄단위 텍스트로 합성한다. set 멤버십을 따로
        # 분기하지 않아도 word boundary 정규식이 동일 의미를 보장한다.
        direct_blob = "\n".join(direct_deps)
        matches = _match_frameworks(direct_blob)
        if len(matches) == 1:
            return matches[0]
        if len(matches) >= 2:
            return "go-generic"
        # direct 0개 — go.sum 약한 evidence 폴백으로 진행
    sum_text = _read_go_file_safe(project_dir, "go.sum")
    sum_matches = _match_frameworks(sum_text)
    if len(sum_matches) == 1:
        return sum_matches[0]
    return "go-generic"


def _collect_cmd_candidates(project_dir: Path) -> list[str]:
    """cmd/<name>/main.go 디렉토리명 후보 목록 반환 (F-22).

    - main.go가 없는 디렉토리는 제외
    - symlink escape 방어 (is_within)
    - 결정성을 위해 정렬 후 반환
    """
    cmd_dir = project_dir / "cmd"
    if not cmd_dir.is_dir():
        return []
    if not is_within(project_dir, cmd_dir):
        return []

    candidates: list[str] = []
    for entry in sorted(cmd_dir.iterdir()):
        if not entry.is_dir():
            continue
        main_go = entry / "main.go"
        if not main_go.is_file():
            continue
        if not is_within(project_dir, main_go):
            continue
        candidates.append(entry.name)
    return candidates


def _build_multi_cmd_error_message(
    candidates: list[str], app_name: str
) -> str:
    """복수 cmd 엔트리포인트 모호성 에러 메시지 (F-28).

    상위 10개만 표시하고 초과분은 "... 외 N개"로 요약.
    """
    sorted_candidates = sorted(candidates)
    head = sorted_candidates[:_MAX_LISTED_CANDIDATES]
    listed = ", ".join(head)
    if len(sorted_candidates) > _MAX_LISTED_CANDIDATES:
        omitted = len(sorted_candidates) - _MAX_LISTED_CANDIDATES
        listed = f"{listed} ... 외 {omitted}개"
    return (
        f"복수 cmd 엔트리포인트 발견: [{listed}]. "
        f"'app_name={app_name}'을 해당 디렉토리명과 일치시키거나 "
        f"'.devflow-k8s-deploy.yml'의 'stack.go.entrypoint'를 지정하세요."
    )


def _resolve_entrypoint(
    detect_result: StackDetectResult, app_name: str
) -> str:
    """build_plan용 엔트리포인트 resolve (F-06).

    우선순위:
      1. detect_result.entrypoint가 확정값 → 그대로 사용
      2. 미결정("") + cmd_candidates 기반:
         (2-a) app_name 매칭 → ./cmd/{app_name}
         (2-b) 단일 후보 → ./cmd/{그것}
         (2-c) 복수 + 매칭 실패 → GoBuildPlanError (F-28)
         (2-d) 0개 → "." fallback
    """
    if detect_result.entrypoint:
        return detect_result.entrypoint

    candidates = list(detect_result.cmd_candidates)
    if not candidates:
        return "."
    if app_name in candidates:
        return f"./cmd/{app_name}"
    if len(candidates) == 1:
        return f"./cmd/{candidates[0]}"
    raise GoBuildPlanError(_build_multi_cmd_error_message(candidates, app_name))


# ──────────────────────────────────────────────────────────────────────────────
# GoStackModule
# ──────────────────────────────────────────────────────────────────────────────


class GoStackModule:
    """Go 스택 모듈 (StackModule Protocol 구현체)."""

    name: ClassVar[str] = "go"
    template_name: ClassVar[str] = "go"

    # ── Public: StackModule Protocol ──────────────────────────────────────────

    def detect(self, project_dir: Path) -> StackDetectResult | None:
        """go.mod 기반 Go 프로젝트 감지 (F-02 ~ F-05).

        Returns:
            StackDetectResult — Go 프로젝트인 경우.
            None — go.mod 없음.

        Raises:
            GoDetectionError: go.mod는 있으나 파싱 실패 시.
        """
        go_mod = project_dir / "go.mod"
        if not go_mod.is_file():
            return None
        if not is_within(project_dir, go_mod):
            return None

        _module_path, go_version = _parse_go_mod(go_mod)
        version = go_version or _DEFAULT_GO_VERSION

        # 엔트리포인트 결정 (A-08): 루트 main.go 우선
        root_main = project_dir / "main.go"
        if root_main.is_file() and is_within(project_dir, root_main):
            entrypoint = "."
            cmd_candidates: list[str] = []
        else:
            entrypoint = ""  # 미결정 sentinel
            cmd_candidates = _collect_cmd_candidates(project_dir)

        # BL-017 F-05: framework 식별을 _detect_go_framework에 위임
        framework = _detect_go_framework(project_dir)

        return StackDetectResult(
            port=None,
            entrypoint=entrypoint,
            framework=framework,
            version=version,
            build_system=None,
            actuator_enabled=False,
            cmd_candidates=cmd_candidates,
        )

    def build_plan(
        self,
        detect_result: StackDetectResult,
        *,
        inputs: UserInputs | None = None,
    ) -> BuildPlan:
        """엔트리포인트 resolve + builder/runner 이미지 + build_cmd 구성 (F-06).

        Raises:
            GoBuildPlanError: inputs 미주입 / 모호 cmd / 입력 검증 실패 (F-29).
        """
        if inputs is None:
            raise GoBuildPlanError(
                "Go 스택 build_plan에는 UserInputs가 필요합니다 (app_name 기반 entrypoint resolve)."
            )

        app_name = inputs.app_name
        # F-29 (a): app_name DNS-1123 재검증
        if not _DNS_1123_RE.fullmatch(app_name):
            raise GoBuildPlanError(
                f"app_name이 DNS-1123 subset을 위반합니다: app_name={app_name!r}"
            )

        # 엔트리포인트 resolve (F-06)
        entrypoint = _resolve_entrypoint(detect_result, app_name)

        # F-29 (b): entrypoint 정규식 + path traversal 방어
        try:
            validate_go_entrypoint(entrypoint)
        except ValueError as exc:
            raise GoBuildPlanError(str(exc)) from exc

        go_version = detect_result.version or _DEFAULT_GO_VERSION
        builder_image = _BUILDER_IMAGE_TEMPLATE.format(go_version=go_version)
        build_cmd = (
            f'CGO_ENABLED=0 go build -ldflags="-s -w" -o {app_name} {entrypoint}'
        )

        return BuildPlan(
            builder_image=builder_image,
            runner_image=_RUNNER_IMAGE,
            build_cmd=build_cmd,
            artifact_path=app_name,
        )

    def probe_plan(self, detect_result: StackDetectResult) -> ProbeConfig:
        """Go probe — framework별 헬스 경로 분기 (F-07, BL-017).

        - gin/echo/fiber → ``/health`` (3대 HTTP 프레임워크 관용, version-agnostic)
        - go-generic 및 기타 → ``/healthz`` (BL-001 baseline 불변, NFR-5)
        - liveness/readiness 동일 spec
        - ``.devflow-k8s-deploy.yml::stack.go.probe.path`` override는
          ProjectAnalyzer가 우선 적용 (BL-001 F-19, BL-017 A-04).
        """
        port = detect_result.port or _DEFAULT_PORT
        path = (
            "/health"
            if detect_result.framework in _HEALTH_FRAMEWORKS
            else "/healthz"
        )
        spec = ProbeSpec(kind="http", path=path, port=port)
        return ProbeConfig(liveness=spec, readiness=spec)

    def defaults(self, resource_hint: ResourceHint) -> ResourceDefaults:
        """Go tier별 리소스 기본값 (F-08).

        run_as_user=65532: distroless/static-debian12:nonroot 내장 UID.
        writable_paths=["/tmp"]: Go는 stdout 구조화 로그가 관례, /var/log 불요.
        """
        tier = _RESOURCE_TIERS[resource_hint]
        return ResourceDefaults(
            cpu_request=tier["cpu_request"],
            memory_request=tier["memory_request"],
            cpu_limit=tier["cpu_limit"],
            memory_limit=tier["memory_limit"],
            writable_paths=["/tmp"],
            run_as_user=65532,
        )

    def artifact_locator(
        self, detect_result: StackDetectResult, project_dir: Path
    ) -> list[Path]:
        """v0.1.x 최소 스코프 — 빈 list (F-09).

        Go 빌드는 컨테이너 builder stage 내부에서 수행되므로
        호스트 사이드 산출물 탐색은 의미 없음.
        """
        return []

    def dockerfile_context(
        self,
        *,
        build_plan: BuildPlan,
        detect_result: StackDetectResult,
        inputs: UserInputs,
        project_dir: Path | None,
    ) -> dict[str, object]:
        """Dockerfile 템플릿(`templates/dockerfile/go.tmpl`) 렌더 컨텍스트 (F-10).

        키: builder_image / runner_image / build_cmd / artifact_path / port / app_name.
        ENTRYPOINT는 템플릿에서 ["/app/{app_name}"] 형태로 사용.
        """
        return {
            "builder_image": build_plan.builder_image,
            "runner_image": build_plan.runner_image,
            "build_cmd": build_plan.build_cmd,
            "artifact_path": build_plan.artifact_path,
            "port": inputs.port,
            "app_name": inputs.app_name,
        }
