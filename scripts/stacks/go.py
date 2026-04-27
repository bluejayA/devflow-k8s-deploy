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

_GO_MODULE_RE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
_GO_VERSION_RE = re.compile(r"^go\s+(\d+(?:\.\d+){0,2})", re.MULTILINE)

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

        return StackDetectResult(
            port=None,
            entrypoint=entrypoint,
            framework="go-generic",
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
        """Go 기본 probe — http /healthz, liveness=readiness 동일 (F-07).

        config의 stack.go.probe.path override는 ProjectAnalyzer에서 적용.
        """
        port = detect_result.port or _DEFAULT_PORT
        spec = ProbeSpec(kind="http", path="/healthz", port=port)
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
