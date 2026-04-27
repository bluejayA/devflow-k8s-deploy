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


# ---------------------------------------------------------------------------
# 4. Important 2: OSError 구분 — PermissionError는 warnings로
# ---------------------------------------------------------------------------


class TestOSErrorHandling:
    def test_permission_error_records_warning(self, tmp_path: Path) -> None:
        """PermissionError → warnings에 한국어 메시지 기록 (파일명 포함, 절대경로 비포함)."""
        import unittest.mock as mock

        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        config_path = proj_dir / ".devflow-k8s-deploy.yml"
        config_path.write_text("namespace: proj-ns\n", encoding="utf-8")

        loader = _loader_with_org(None)

        def raise_permission(*args: Any, **kwargs: Any) -> str:
            raise PermissionError("Permission denied")

        # config_loader는 `from scripts._shared.fileio import read_text_limited`로 임포트
        # 하므로 패치 대상은 config_loader 모듈 내 이름
        with mock.patch("scripts.config_loader.read_text_limited", side_effect=raise_permission):
            result = loader.load(proj_dir)

        # PermissionError는 warnings에 기록됨
        assert len(result.warnings) >= 1
        assert any("프로젝트" in w for w in result.warnings)
        # 절대 경로 미포함, 파일명만
        assert any(".devflow-k8s-deploy.yml" in w for w in result.warnings)
        assert not any(str(tmp_path) in w for w in result.warnings)

    def test_file_not_found_is_silent(self, tmp_path: Path) -> None:
        """FileNotFoundError(파일 없음)는 warnings 없이 조용히 처리."""
        proj_dir = tmp_path / "proj-absent"
        # config 파일 없이 디렉토리만 존재
        proj_dir.mkdir()

        loader = _loader_with_org(None)
        result = loader.load(proj_dir)

        assert result.warnings == []
        assert result.raw["stack"] == "auto"


# ---------------------------------------------------------------------------
# 5. Important 3: layer_raws 필드 — resolve_namespace 재파싱 제거 검증
# ---------------------------------------------------------------------------


class TestLayerRaws:
    def test_load_returns_layer_raws(self, tmp_path: Path) -> None:
        """load() 결과에 layer_raws가 계층별 원본 dict를 담는다."""
        org_path = _make_org_config(tmp_path / "org", {"stack": "jvm", "namespace": "org-ns"})
        proj_dir = _make_project_config(tmp_path / "proj", {"namespace": "proj-ns"})

        loader = _loader_with_org(org_path)
        result = loader.load(proj_dir)

        assert "project_config" in result.layer_raws
        assert "org_config" in result.layer_raws
        assert "builtin_default" in result.layer_raws
        assert result.layer_raws["project_config"]["namespace"] == "proj-ns"
        assert result.layer_raws["org_config"]["stack"] == "jvm"

    def test_resolve_namespace_uses_layer_raws_no_reparse(self, tmp_path: Path) -> None:
        """resolve_namespace가 layer_raws를 사용 — 파일 삭제 후에도 올바른 값 반환."""
        proj_dir = _make_project_config(tmp_path / "proj", {"namespace": "cached-ns"})

        loader = _loader_with_org(None)
        config = loader.load(proj_dir)

        # 파일 삭제 후 resolve_namespace 호출 → layer_raws에서 조회하므로 성공
        (proj_dir / ".devflow-k8s-deploy.yml").unlink()
        result = loader.resolve_namespace(config, user_input=None, project_dir=proj_dir)

        assert result.value == "cached-ns"
        assert result.source == "project_config"


# ---------------------------------------------------------------------------
# 6. Important 4: YAML bomb 방어
# ---------------------------------------------------------------------------


class TestYamlBombDefense:
    def test_yaml_bomb_rejected_with_warning(self, tmp_path: Path) -> None:
        """17개 anchor/alias 포함 YAML → warnings에 한국어 메시지 + 해당 계층 무시."""
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        # 17개 anchor 포함 YAML (bomb 방어 임계값 16 초과)
        anchors = "\n".join(f"anchor_{i}: &anchor_{i} value_{i}" for i in range(17))
        yaml_content = f"{anchors}\nnamespace: bomb-ns\n"
        (proj_dir / ".devflow-k8s-deploy.yml").write_text(yaml_content, encoding="utf-8")

        loader = _loader_with_org(None)
        result = loader.load(proj_dir)

        # bomb 감지 → warnings에 기록
        assert len(result.warnings) >= 1
        assert any(
            "anchor" in w.lower() or "bomb" in w.lower() or "과다" in w
            for w in result.warnings
        )
        # 해당 계층 무시 → builtin 기본값 사용
        assert result.raw["namespace"] is None or result.raw.get("namespace") != "bomb-ns"

    def test_yaml_within_limit_not_rejected(self, tmp_path: Path) -> None:
        """16개 이하 anchor → 정상 파싱."""
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        anchors = "\n".join(f"anchor_{i}: &anchor_{i} value_{i}" for i in range(16))
        yaml_content = f"{anchors}\nnamespace: safe-ns\n"
        (proj_dir / ".devflow-k8s-deploy.yml").write_text(yaml_content, encoding="utf-8")

        loader = _loader_with_org(None)
        result = loader.load(proj_dir)

        assert result.raw.get("namespace") == "safe-ns"
        # bomb 관련 경고 없음
        assert not any("과다" in w or "bomb" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# 7. Important 5: Symlink escape 방어
# ---------------------------------------------------------------------------


class TestSymlinkDefense:
    def test_project_config_symlink_outside_rejected(self, tmp_path: Path) -> None:
        """project config symlink가 project_dir 외부를 가리키면 거부 + 한국어 warning."""
        # 외부 파일 생성
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_file = external_dir / "secret.yml"
        external_file.write_text("namespace: leaked-ns\n", encoding="utf-8")

        # project_dir에 symlink 생성
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        symlink_path = proj_dir / ".devflow-k8s-deploy.yml"
        symlink_path.symlink_to(external_file)

        loader = _loader_with_org(None)
        result = loader.load(proj_dir)

        # symlink escape → 거부, builtin 기본값 사용
        assert result.raw.get("namespace") != "leaked-ns"
        # warnings에 기록
        assert len(result.warnings) >= 1
        assert any(
            "프로젝트" in w and ("밖" in w or "symlink" in w.lower() or "심볼릭" in w)
            for w in result.warnings
        )

    def test_org_config_symlink_recorded_only(self, tmp_path: Path) -> None:
        """org config symlink는 로드 성공, warnings에만 기록."""
        # 실제 config 파일 생성
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        real_file = real_dir / "org.yml"
        real_file.write_text("namespace: org-symlink-ns\n", encoding="utf-8")

        # org config를 symlink로 설정
        symlink_org = tmp_path / "org-link.yml"
        symlink_org.symlink_to(real_file)

        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        loader = ConfigLoader(org_config_path=symlink_org)
        result = loader.load(proj_dir)

        # 로드 성공 — namespace 반영됨
        assert result.raw.get("namespace") == "org-symlink-ns"
        # 심볼릭 링크 경고 기록
        assert len(result.warnings) >= 1
        assert any("심볼릭" in w or "symlink" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# #18 replicas 기본값 테스트
# ---------------------------------------------------------------------------

def test_builtin_defaults_has_app_replicas() -> None:
    """BUILTIN_DEFAULTS에 app.replicas: 2 기본값이 존재해야 한다."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS

    assert "app" in BUILTIN_DEFAULTS
    assert BUILTIN_DEFAULTS["app"]["replicas"] == 2


def test_config_loader_app_replicas_default(tmp_path: Path) -> None:
    """설정 파일에 app.replicas 없으면 기본값 2가 병합된다."""
    loader = ConfigLoader(org_config_path=tmp_path / "no_org.yml")
    result = loader.load(tmp_path)
    assert result.raw.get("app", {}).get("replicas") == 2


def test_config_loader_app_replicas_override(tmp_path: Path) -> None:
    """프로젝트 설정의 app.replicas가 기본값을 덮어쓴다."""
    proj_cfg = tmp_path / ".devflow-k8s-deploy.yml"
    proj_cfg.write_text("app:\n  replicas: 5\n", encoding="utf-8")
    loader = ConfigLoader(org_config_path=tmp_path / "no_org.yml")
    result = loader.load(tmp_path)
    assert result.raw["app"]["replicas"] == 5


class TestResolveStackConfig:
    """BL-001 F-33 — quality-reviewer P2-3 대응."""

    def test_string_stack_returns_empty_dict(self) -> None:
        """`stack: auto` 같은 string 형태는 stack overrides 없음 → 빈 dict."""
        from scripts._shared.types import ResolvedConfig

        loader = ConfigLoader(org_config_path=Path("/no_org.yml"))
        config = ResolvedConfig(raw={"stack": "auto"}, source_map={})
        result = loader.resolve_stack_config(config, "go")

        assert result == {}

    def test_dict_stack_with_substack_returns_subdict(self) -> None:
        """`stack.go: {entrypoint: ./cmd/api}` → {"entrypoint": "./cmd/api"}."""
        from scripts._shared.types import ResolvedConfig

        loader = ConfigLoader(org_config_path=Path("/no_org.yml"))
        config = ResolvedConfig(
            raw={
                "stack": {
                    "forced_stack": "auto",
                    "go": {"entrypoint": "./cmd/api"},
                }
            },
            source_map={},
        )
        result = loader.resolve_stack_config(config, "go")

        assert result == {"entrypoint": "./cmd/api"}

    def test_dict_stack_without_substack_returns_empty_dict(self) -> None:
        """`stack.go`가 dict가 아닌 경우(예: string scalar) → 빈 dict."""
        from scripts._shared.types import ResolvedConfig

        loader = ConfigLoader(org_config_path=Path("/no_org.yml"))
        config = ResolvedConfig(
            raw={"stack": {"go": "string-not-dict"}}, source_map={}
        )
        result = loader.resolve_stack_config(config, "go")

        assert result == {}

    def test_missing_stack_key_returns_empty_dict(self) -> None:
        """`stack` 키 자체가 없으면 빈 dict."""
        from scripts._shared.types import ResolvedConfig

        loader = ConfigLoader(org_config_path=Path("/no_org.yml"))
        config = ResolvedConfig(raw={}, source_map={})
        result = loader.resolve_stack_config(config, "go")

        assert result == {}
