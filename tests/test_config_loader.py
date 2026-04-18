"""TDD: ConfigLoader — 3계층 YAML 병합 + namespace 4단계 조회 + stack_decision.

RED → GREEN → REFACTOR 순서.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts._shared.errors import UnsupportedStackError
from scripts.config_loader import ConfigLoader

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_project_config(tmp_path: Path, data: dict[str, Any]) -> Path:
    """tmp_path 아래에 .devflow-k8s-deploy.yml 생성."""
    import yaml

    tmp_path.mkdir(parents=True, exist_ok=True)
    config_file = tmp_path / ".devflow-k8s-deploy.yml"
    config_file.write_text(yaml.dump(data), encoding="utf-8")
    return tmp_path


def _make_org_config(tmp_path: Path, data: dict[str, Any]) -> Path:
    """tmp_path 아래에 org config 파일 생성. ConfigLoader에 DI로 주입."""
    import yaml

    tmp_path.mkdir(parents=True, exist_ok=True)
    org_file = tmp_path / "org-config.yml"
    org_file.write_text(yaml.dump(data), encoding="utf-8")
    return org_file


def _loader_with_org(org_config_path: Path | None = None) -> ConfigLoader:
    """org_config_path를 DI로 주입한 ConfigLoader 생성."""
    return ConfigLoader(org_config_path=org_config_path)


# ---------------------------------------------------------------------------
# 1. load() — 3계층 병합
# ---------------------------------------------------------------------------


class TestLoad:
    def test_three_layer_merge_scalar_priority(self, tmp_path: Path) -> None:
        """프로젝트 > 조직 > 기본 scalar overwrite 확인."""
        # 조직: stack=jvm, namespace=org-ns
        org_path = _make_org_config(tmp_path / "org", {"stack": "jvm", "namespace": "org-ns"})
        # 프로젝트: namespace=proj-ns (stack은 조직 값 유지)
        proj_dir = _make_project_config(tmp_path / "proj", {"namespace": "proj-ns"})

        loader = _loader_with_org(org_path)
        result = loader.load(proj_dir)

        # 프로젝트 우선: namespace=proj-ns
        assert result.raw["namespace"] == "proj-ns"
        # 조직 우선 (프로젝트에 없음): stack=jvm
        assert result.raw["stack"] == "jvm"
        assert len(result.warnings) == 0

    def test_dict_deep_merge(self, tmp_path: Path) -> None:
        """dict deep merge — build.engine은 프로젝트, build.timeout_sec는 조직 값."""
        org_path = _make_org_config(
            tmp_path / "org",
            {"build": {"engine": "docker", "timeout_sec": 600}},
        )
        # 프로젝트: build.engine만 podman으로 오버라이드
        proj_dir = _make_project_config(tmp_path / "proj", {"build": {"engine": "podman"}})

        loader = _loader_with_org(org_path)
        result = loader.load(proj_dir)

        # 프로젝트 > 조직: engine=podman
        assert result.raw["build"]["engine"] == "podman"
        # 조직 > builtin: timeout_sec=600
        assert result.raw["build"]["timeout_sec"] == 600

    def test_no_project_config_uses_org_plus_builtin(self, tmp_path: Path) -> None:
        """프로젝트 config 없음 → 조직 + 기본 병합."""
        org_path = _make_org_config(tmp_path / "org", {"namespace": "team-ns"})
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        loader = _loader_with_org(org_path)
        result = loader.load(proj_dir)

        assert result.raw["namespace"] == "team-ns"
        # builtin 기본값 유지
        assert result.raw["stack"] == "auto"
        assert result.raw["build"]["engine"] == "skip"

    def test_no_org_config_uses_project_plus_builtin(self, tmp_path: Path) -> None:
        """조직 config 없음 → 프로젝트 + 기본 병합."""
        proj_dir = _make_project_config(tmp_path / "proj", {"stack": "jvm"})

        loader = _loader_with_org(None)  # org 없음
        result = loader.load(proj_dir)

        assert result.raw["stack"] == "jvm"
        # builtin 기본값 유지
        assert result.raw["build"]["timeout_sec"] == 300

    def test_no_configs_uses_builtin_only_no_warnings(self, tmp_path: Path) -> None:
        """프로젝트/조직 config 모두 없음 → 기본값만, warnings 없음."""
        proj_dir = tmp_path / "empty-proj"
        proj_dir.mkdir()

        loader = _loader_with_org(None)
        result = loader.load(proj_dir)

        assert result.raw["stack"] == "auto"
        assert result.raw["namespace"] is None
        assert result.warnings == []

    def test_invalid_yaml_records_korean_warning_and_keeps_remaining_layers(
        self, tmp_path: Path
    ) -> None:
        """YAML 파싱 실패 → warnings에 한국어 메시지 기록 + 나머지 계층 유지."""
        org_path = _make_org_config(tmp_path / "org", {"namespace": "org-ns"})

        # 잘못된 YAML (탭 들여쓰기 등)
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        bad_yaml = "key: [invalid: yaml: here\n  indented: wrong\n bad\n"
        (proj_dir / ".devflow-k8s-deploy.yml").write_text(bad_yaml, encoding="utf-8")

        loader = _loader_with_org(org_path)
        result = loader.load(proj_dir)

        # 파싱 실패 → 경고 기록
        assert len(result.warnings) >= 1
        assert any("프로젝트" in w and "파싱" in w for w in result.warnings)
        # 나머지 계층(조직) 유지
        assert result.raw["namespace"] == "org-ns"

    def test_source_map_records_layer_for_top_level_keys(self, tmp_path: Path) -> None:
        """source_map에 최상위 키별 출처 기록 확인."""
        org_path = _make_org_config(tmp_path / "org", {"stack": "jvm"})
        proj_dir = _make_project_config(tmp_path / "proj", {"namespace": "proj-ns"})

        loader = _loader_with_org(org_path)
        result = loader.load(proj_dir)

        # 프로젝트에서 온 키
        assert result.source_map.get("namespace") == "project_config"
        # 조직에서 온 키
        assert result.source_map.get("stack") == "org_config"
        # builtin에서 온 키 (build는 프로젝트/조직 모두 없음)
        assert result.source_map.get("build") == "builtin_default"

    def test_oversized_file_records_warning_and_ignores_layer(self, tmp_path: Path) -> None:
        """파일 크기 초과 (read_text_limited → ValueError) → warnings 기록 + 해당 계층 무시."""
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        # 정상적인 내용의 파일을 만들고 크기를 초과하게 패치
        (proj_dir / ".devflow-k8s-deploy.yml").write_text(
            "namespace: large-proj\n", encoding="utf-8"
        )

        loader = _loader_with_org(None)
        # read_text_limited를 monkeypatch로 크기 초과 상황 시뮬레이션
        import unittest.mock as mock

        original_read = loader._read_yaml_file

        def patched_read(path: Path) -> dict[str, Any]:
            if path == proj_dir / ".devflow-k8s-deploy.yml":
                raise ValueError(f"파일이 5MB 초과: {path} (99999999 bytes)")
            return original_read(path)

        with mock.patch.object(loader, "_read_yaml_file", side_effect=patched_read):
            result = loader.load(proj_dir)

        assert len(result.warnings) >= 1
        assert any("파싱" in w or "크기" in w or "초과" in w for w in result.warnings)
        # 해당 계층 무시 → builtin 기본값 유지
        assert result.raw["stack"] == "auto"


# ---------------------------------------------------------------------------
# 2. resolve_namespace() — 4단계 조회
# ---------------------------------------------------------------------------


class TestResolveNamespace:
    def test_project_config_namespace_wins(self, tmp_path: Path) -> None:
        """project config에 namespace 있음 → source=project_config, requires_confirmation=False."""
        proj_dir = _make_project_config(tmp_path / "proj", {"namespace": "my-app"})
        org_path = _make_org_config(tmp_path / "org", {"namespace": "org-ns"})

        loader = _loader_with_org(org_path)
        config = loader.load(proj_dir)
        result = loader.resolve_namespace(config, user_input=None, project_dir=proj_dir)

        assert result.value == "my-app"
        assert result.source == "project_config"
        assert result.requires_confirmation is False

    def test_org_config_namespace_when_project_absent(self, tmp_path: Path) -> None:
        """project 없음, org 있음 → source=org_config."""
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        org_path = _make_org_config(tmp_path / "org", {"namespace": "org-ns"})

        loader = _loader_with_org(org_path)
        config = loader.load(proj_dir)
        result = loader.resolve_namespace(config, user_input=None, project_dir=proj_dir)

        assert result.value == "org-ns"
        assert result.source == "org_config"
        assert result.requires_confirmation is False

    def test_user_input_when_both_configs_absent(self, tmp_path: Path) -> None:
        """project/org 모두 없음, user_input 제공 → source=user_input."""
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)
        result = loader.resolve_namespace(config, user_input="user-ns", project_dir=proj_dir)

        assert result.value == "user-ns"
        assert result.source == "user_input"
        assert result.requires_confirmation is False

    def test_project_dir_name_as_fallback(self, tmp_path: Path) -> None:
        """모두 없음 + user_input 없음 → source=project_dir, value=project_dir.name."""
        proj_dir = tmp_path / "my-service"
        proj_dir.mkdir()

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)
        result = loader.resolve_namespace(config, user_input=None, project_dir=proj_dir)

        assert result.value == "my-service"
        assert result.source == "project_dir"
        assert result.requires_confirmation is False

    def test_default_namespace_requires_confirmation(self, tmp_path: Path) -> None:
        """'default' 값 → requires_confirmation=True (어느 계층이든)."""
        proj_dir = _make_project_config(tmp_path / "proj", {"namespace": "default"})

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)
        result = loader.resolve_namespace(config, user_input=None, project_dir=proj_dir)

        assert result.value == "default"
        assert result.requires_confirmation is True

    def test_default_in_user_input_requires_confirmation(self, tmp_path: Path) -> None:
        """user_input이 'default'인 경우 → requires_confirmation=True."""
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)
        result = loader.resolve_namespace(config, user_input="default", project_dir=proj_dir)

        assert result.value == "default"
        assert result.requires_confirmation is True

    def test_empty_string_or_none_skips_to_next_stage(self, tmp_path: Path) -> None:
        """빈 문자열/None은 '값 없음'으로 다음 단계로 진행."""
        # 프로젝트에 namespace="" (빈 문자열) → 다음 단계로
        proj_dir = _make_project_config(tmp_path / "proj", {"namespace": ""})
        org_path = _make_org_config(tmp_path / "org", {"namespace": "org-ns"})

        loader = _loader_with_org(org_path)
        config = loader.load(proj_dir)
        result = loader.resolve_namespace(config, user_input=None, project_dir=proj_dir)

        # 빈 문자열 → 다음 단계(org) 진행
        assert result.value == "org-ns"
        assert result.source == "org_config"

    def test_default_in_org_config_requires_confirmation(self, tmp_path: Path) -> None:
        """org config의 namespace가 'default' → requires_confirmation=True."""
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        org_path = _make_org_config(tmp_path / "org", {"namespace": "default"})

        loader = _loader_with_org(org_path)
        config = loader.load(proj_dir)
        result = loader.resolve_namespace(config, user_input=None, project_dir=proj_dir)

        assert result.value == "default"
        assert result.source == "org_config"
        assert result.requires_confirmation is True


# ---------------------------------------------------------------------------
# 3. stack_decision() — stack 분기
# ---------------------------------------------------------------------------


class TestStackDecision:
    def test_stack_auto_returns_none_forced_stack(self, tmp_path: Path) -> None:
        """`stack: auto` → forced_stack=None, source=project_config."""
        proj_dir = _make_project_config(tmp_path / "proj", {"stack": "auto"})

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)
        result = loader.stack_decision(config, proj_dir)

        assert result.forced_stack is None
        assert result.source == "project_config"

    def test_stack_jvm_returns_forced_jvm(self, tmp_path: Path) -> None:
        """`stack: jvm` → forced_stack='jvm'."""
        proj_dir = _make_project_config(tmp_path / "proj", {"stack": "jvm"})

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)
        result = loader.stack_decision(config, proj_dir)

        assert result.forced_stack == "jvm"

    def test_stack_go_raises_unsupported_error(self, tmp_path: Path) -> None:
        """`stack: go` → UnsupportedStackError raise."""
        proj_dir = _make_project_config(tmp_path / "proj", {"stack": "go"})

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)

        with pytest.raises(UnsupportedStackError):
            loader.stack_decision(config, proj_dir)

    def test_stack_python_raises_unsupported_error(self, tmp_path: Path) -> None:
        """`stack: python` → UnsupportedStackError raise."""
        proj_dir = _make_project_config(tmp_path / "proj", {"stack": "python"})

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)

        with pytest.raises(UnsupportedStackError):
            loader.stack_decision(config, proj_dir)

    def test_stack_react_raises_unsupported_error(self, tmp_path: Path) -> None:
        """`stack: react` → UnsupportedStackError raise."""
        proj_dir = _make_project_config(tmp_path / "proj", {"stack": "react"})

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)

        with pytest.raises(UnsupportedStackError):
            loader.stack_decision(config, proj_dir)

    def test_unknown_stack_value_raises_unsupported_error(self, tmp_path: Path) -> None:
        """`stack: unknown_value` → UnsupportedStackError raise."""
        proj_dir = _make_project_config(tmp_path / "proj", {"stack": "ruby"})

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)

        with pytest.raises(UnsupportedStackError):
            loader.stack_decision(config, proj_dir)

    def test_stack_unset_uses_builtin_auto(self, tmp_path: Path) -> None:
        """stack 미지정 → BUILTIN_DEFAULTS 'auto' → forced_stack=None, source=builtin_default."""
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)
        result = loader.stack_decision(config, proj_dir)

        assert result.forced_stack is None
        assert result.source == "builtin_default"

    def test_stack_source_reflects_source_map(self, tmp_path: Path) -> None:
        """stack_decision의 source가 source_map['stack']을 반영."""
        org_path = _make_org_config(tmp_path / "org", {"stack": "jvm"})
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        loader = _loader_with_org(org_path)
        config = loader.load(proj_dir)
        result = loader.stack_decision(config, proj_dir)

        assert result.source == "org_config"
        assert result.forced_stack == "jvm"
