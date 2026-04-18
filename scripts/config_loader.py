"""3계층 설정 로더 — 프로젝트 / 조직 / 내장 기본값 YAML 병합.

F-60~F-63, F-70, F-71, F-92 구현.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scripts._shared.defaults import load_builtin_defaults
from scripts._shared.errors import UnsupportedStackError
from scripts._shared.fileio import read_text_limited
from scripts._shared.types import NamespaceResolution, ResolvedConfig, StackDecision

# v0.1.0에서 지원하는 stack 목록
_SUPPORTED_STACKS: frozenset[str] = frozenset({"auto", "jvm"})
# v0.1.0에서 명시하면 UnsupportedStackError를 발생시킬 stack
_KNOWN_UNSUPPORTED_STACKS: frozenset[str] = frozenset({"go", "python", "react"})

# 조직 설정 기본 경로
_DEFAULT_ORG_CONFIG_PATH = Path.home() / ".claude" / "devflow-k8s-deploy.yml"
# 프로젝트 설정 파일명
_PROJECT_CONFIG_FILENAME = ".devflow-k8s-deploy.yml"

# source 레이어 상수
_SRC_PROJECT = "project_config"
_SRC_ORG = "org_config"
_SRC_BUILTIN = "builtin_default"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """override를 base에 deep merge하여 새 dict 반환.

    - dict 값은 재귀적으로 merge (하위 키 우선순위 유지)
    - scalar / list는 overwrite (override 값 우선)
    """
    result = dict(base)
    for key, override_val in override.items():
        base_val = result.get(key)
        if isinstance(base_val, dict) and isinstance(override_val, dict):
            result[key] = _deep_merge(base_val, override_val)
        else:
            result[key] = override_val
    return result


class ConfigLoader:
    """3계층 설정 로더.

    DI 패턴으로 org_config_path를 주입받아 테스트 시 monkeypatch 없이 교체 가능.
    """

    def __init__(self, org_config_path: Path | None = None) -> None:
        """
        Args:
            org_config_path: 조직 설정 파일 경로.
                None이면 Path.home() / ".claude" / "devflow-k8s-deploy.yml" 기본.
        """
        self._org_config_path: Path = (
            org_config_path if org_config_path is not None else _DEFAULT_ORG_CONFIG_PATH
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, project_dir: Path) -> ResolvedConfig:
        """3계층 병합 결과 반환.

        우선순위 (높음 → 낮음):
          1. project_dir/.devflow-k8s-deploy.yml (프로젝트 계층)
          2. org_config_path (조직 계층)
          3. BUILTIN_DEFAULTS (내장 기본값)

        병합 규칙:
          - dict는 deep merge (하위 키 우선순위 그대로)
          - scalar/list는 overwrite (상위 계층이 승)

        YAML 파싱/크기 초과 실패:
          - 예외 throw 안 함
          - ResolvedConfig.warnings에 한국어 경고 기록
          - 해당 계층 무시 후 나머지 계층으로 진행

        Returns:
            ResolvedConfig — raw(병합 결과), source_map(최상위 키 출처), warnings
        """
        warnings: list[str] = []

        # 1. 내장 기본값 로드
        builtin = load_builtin_defaults()

        # 2. 조직 설정 로드
        org_data, org_warning = self._load_layer(self._org_config_path, "조직")
        if org_warning:
            warnings.append(org_warning)

        # 3. 프로젝트 설정 로드
        project_path = project_dir / _PROJECT_CONFIG_FILENAME
        project_data, project_warning = self._load_layer(project_path, "프로젝트")
        if project_warning:
            warnings.append(project_warning)

        # 4. 3계층 병합: builtin ← org ← project
        merged = _deep_merge(builtin, org_data)
        merged = _deep_merge(merged, project_data)

        # 5. source_map 계산 (최상위 키 기준)
        source_map = self._build_source_map(builtin, org_data, project_data)

        return ResolvedConfig(raw=merged, source_map=source_map, warnings=warnings)

    def resolve_namespace(
        self,
        config: ResolvedConfig,
        user_input: str | None,
        project_dir: Path,
    ) -> NamespaceResolution:
        """4단계 namespace 조회.

        조회 순서:
          1. project config의 namespace 값 (각 계층 원본 파일에서 직접 조회)
          2. org config의 namespace 값
          3. user_input 인자
          4. project_dir.name (자동 제안)

        'default' 자동 배정 금지:
          - 어느 단계든 값이 'default'이면 requires_confirmation=True
          - None / '' 은 다음 단계로 진행

        Returns:
            NamespaceResolution(value, source, requires_confirmation)

        Note:
            각 계층의 원본 YAML에서 namespace를 직접 읽어야 올바른 우선순위를 보장한다.
            merged raw를 사용하면 빈 문자열 오버라이드 케이스에서 계층이 무너진다.
        """
        # 단계 1: project config 원본
        project_path = project_dir / _PROJECT_CONFIG_FILENAME
        project_data, _ = self._load_layer(project_path, "프로젝트")
        proj_ns = project_data.get("namespace")
        if _is_present(proj_ns):
            return _make_namespace_result(str(proj_ns), _SRC_PROJECT)

        # 단계 2: org config 원본
        org_data, _ = self._load_layer(self._org_config_path, "조직")
        org_ns = org_data.get("namespace")
        if _is_present(org_ns):
            return _make_namespace_result(str(org_ns), _SRC_ORG)

        # 단계 3: user_input
        if _is_present(user_input):
            return _make_namespace_result(str(user_input), "user_input")

        # 단계 4: project_dir.name
        return _make_namespace_result(project_dir.name, "project_dir")

    def stack_decision(self, config: ResolvedConfig, project_dir: Path) -> StackDecision:
        """stack 분기 결정 (F-62/F-92).

        - auto: forced_stack=None (ProjectAnalyzer가 감지)
        - jvm: forced_stack="jvm"
        - go/python/react: UnsupportedStackError raise (v0.1.0 미지원)
        - 알 수 없는 값: UnsupportedStackError

        source는 config.source_map["stack"] 반영.
        """
        stack_val = config.raw.get("stack", "auto")
        source = config.source_map.get("stack", _SRC_BUILTIN)

        if stack_val == "auto":
            return StackDecision(forced_stack=None, source=source)

        if stack_val == "jvm":
            return StackDecision(forced_stack="jvm", source=source)

        # 알려진 미지원 스택 또는 완전히 알 수 없는 값 모두 UnsupportedStackError
        raise UnsupportedStackError(
            f"v0.1.0에서 지원하지 않는 stack: '{stack_val}'. "
            f"지원 스택: auto, jvm. "
            f"({', '.join(sorted(_KNOWN_UNSUPPORTED_STACKS))} 등은 v0.2+ 예정)"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_yaml_file(self, path: Path) -> dict[str, Any]:
        """경로의 YAML 파일을 읽어 dict 반환.

        파일이 없으면 빈 dict 반환.

        Raises:
            ValueError: 파일 크기 5MB 초과 (read_text_limited)
            yaml.YAMLError: YAML 파싱 실패
        """
        if not path.exists():
            return {}
        text = read_text_limited(path)
        result = yaml.safe_load(text)
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise yaml.YAMLError(f"YAML 최상위가 dict가 아님: {type(result).__name__}")
        return result

    def _load_layer(
        self,
        path: Path,
        layer_name_ko: str,
    ) -> tuple[dict[str, Any], str | None]:
        """한 계층의 YAML 파일을 읽어 (data, warning_or_None) 반환.

        - 파일 없음 → ({}, None)
        - 파싱 실패 / 크기 초과 → ({}, 한국어 경고 메시지)
        """
        try:
            data = self._read_yaml_file(path)
            return data, None
        except ValueError as exc:
            msg = f"{layer_name_ko} 설정 크기 초과: {exc}"
            return {}, msg
        except yaml.YAMLError as exc:
            msg = f"{layer_name_ko} 설정 파싱 실패: {exc}"
            return {}, msg
        except OSError:
            # 파일 없음 또는 권한 부족 → 조용히 무시
            return {}, None

    @staticmethod
    def _build_source_map(
        builtin: dict[str, Any],
        org: dict[str, Any],
        project: dict[str, Any],
    ) -> dict[str, str]:
        """최상위 키별 출처 계층 dict 반환.

        우선순위: project > org > builtin
        """
        source_map: dict[str, str] = {}

        # builtin 키 먼저 (가장 낮은 우선순위)
        for key in builtin:
            source_map[key] = _SRC_BUILTIN

        # org로 덮어쓰기
        for key in org:
            source_map[key] = _SRC_ORG

        # project로 덮어쓰기 (가장 높은 우선순위)
        for key in project:
            source_map[key] = _SRC_PROJECT

        return source_map


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _is_present(value: Any) -> bool:
    """값이 None도 아니고 빈 문자열도 아니면 True."""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def _make_namespace_result(value: str, source: str) -> NamespaceResolution:
    """value와 source를 받아 NamespaceResolution 반환.

    value가 'default'이면 requires_confirmation=True.
    """
    requires_confirmation = value == "default"
    # source Literal 타입 캐스팅 — runtime에서는 str로 처리
    from typing import Literal, cast

    valid_source = cast(
        Literal["project_config", "org_config", "user_input", "project_dir", "default"],
        source,
    )
    return NamespaceResolution(
        value=value,
        source=valid_source,
        requires_confirmation=requires_confirmation,
    )
