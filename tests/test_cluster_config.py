"""ClusterConfig 타입 + ConfigLoader.resolve_cluster_config() 테스트."""

from __future__ import annotations

import pytest

from scripts._shared.types import ClusterConfig, ResolvedConfig
from scripts.config_loader import ConfigLoader

# ── Step 1: ClusterConfig 타입 ────────────────────────────────────────────────

class TestClusterConfig:
    def test_cluster_config_fields(self) -> None:
        cfg = ClusterConfig(preset="orbstack", storage_class="local-path", network_policy=True)
        assert cfg.preset == "orbstack"
        assert cfg.storage_class == "local-path"
        assert cfg.network_policy is True

    def test_cluster_config_storage_class_none(self) -> None:
        cfg = ClusterConfig(preset="bare", storage_class=None, network_policy=False)
        assert cfg.storage_class is None
        assert cfg.network_policy is False

    def test_cluster_config_frozen(self) -> None:
        from dataclasses import FrozenInstanceError
        cfg = ClusterConfig(preset="orbstack", storage_class="local-path", network_policy=True)
        with pytest.raises(FrozenInstanceError):
            cfg.preset = "other"  # type: ignore[misc]


# ── Step 2: ConfigLoader.resolve_cluster_config() ────────────────────────────

class TestResolveClusterConfig:
    def _make_config(self, raw: dict) -> ResolvedConfig:
        return ResolvedConfig(raw=raw, source_map={})

    def test_resolve_cluster_config_orbstack(self) -> None:
        loader = ConfigLoader()
        config = self._make_config({"cluster": {"preset": "orbstack"}})
        result = loader.resolve_cluster_config(config, prompt_callback=None)
        assert isinstance(result, ClusterConfig)
        assert result.preset == "orbstack"
        assert result.storage_class == "local-path"
        assert result.network_policy is True

    def test_resolve_cluster_config_network_policy_override(self) -> None:
        loader = ConfigLoader()
        config = self._make_config({"cluster": {"preset": "orbstack", "network_policy": False}})
        result = loader.resolve_cluster_config(config, prompt_callback=None)
        assert result.network_policy is False
        assert result.storage_class == "local-path"  # preset 기본값 유지

    def test_resolve_cluster_config_storage_class_override(self) -> None:
        loader = ConfigLoader()
        config = self._make_config({"cluster": {"preset": "orbstack", "storage_class": "my-class"}})
        result = loader.resolve_cluster_config(config, prompt_callback=None)
        assert result.storage_class == "my-class"
        assert result.network_policy is True  # preset 기본값 유지

    def test_resolve_cluster_config_missing_preset_no_prompt_fallback(self) -> None:
        """prompt_callback=None, preset 미설정 → orbstack fallback."""
        loader = ConfigLoader()
        config = self._make_config({})
        result = loader.resolve_cluster_config(config, prompt_callback=None)
        assert result.preset == "orbstack"
        assert result.storage_class == "local-path"
        assert result.network_policy is True

    def test_resolve_cluster_config_unknown_preset_no_preset_values(self) -> None:
        """알 수 없는 preset → storage_class None, network_policy False 기본."""
        loader = ConfigLoader()
        config = self._make_config({"cluster": {"preset": "unknown-env"}})
        result = loader.resolve_cluster_config(config, prompt_callback=None)
        assert result.preset == "unknown-env"
        assert result.storage_class is None
        assert result.network_policy is False

    def test_resolve_cluster_config_scalar_cluster_no_crash(self) -> None:
        """cluster: orbstack (스칼라) — dict 가드 실패 시 AttributeError 발생했던 케이스."""
        loader = ConfigLoader()
        config = self._make_config({"cluster": "orbstack"})
        result = loader.resolve_cluster_config(config, prompt_callback=None)
        assert isinstance(result, ClusterConfig)
        assert result.preset == "orbstack"  # orbstack fallback
