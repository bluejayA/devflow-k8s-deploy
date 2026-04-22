"""validators 패키지 구조 및 registry 동작 테스트."""

from __future__ import annotations

import pytest


def _minimal_container(**overrides: object) -> dict:
    base = {
        "name": "app",
        "image": "registry.example.com/app:latest",
        "securityContext": {
            "runAsNonRoot": True,
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "resources": {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "200m", "memory": "256Mi"},
        },
    }
    base.update(overrides)
    return base


def _minimal_pod_spec(**overrides: object) -> dict:
    base = {
        "containers": [_minimal_container()],
        "automountServiceAccountToken": False,
        "serviceAccountName": "default",
        "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
        "terminationGracePeriodSeconds": 60,
    }
    base.update(overrides)
    return base


# ── 임포트 구조 ──────────────────────────────────────────────────────────────


class TestImports:
    def test_import_validators_package(self) -> None:
        from scripts.validators import K8sValidator  # noqa: F401

        assert K8sValidator is not None

    def test_import_registry(self) -> None:
        from scripts.validators.registry import register_rule, run_rules  # noqa: F401

        assert callable(register_rule)
        assert callable(run_rules)

    def test_import_rule_modules(self) -> None:
        from scripts.validators.rules import img, life, prb, res, sa, sec, svc  # noqa: F401

    def test_validate_k8s_reexport(self) -> None:
        """기존 임포트 경로가 깨지지 않는지 확인."""
        from scripts.validate_k8s import K8sValidator, _compute_exit_code  # noqa: F401

        assert K8sValidator is not None
        assert callable(_compute_exit_code)


# ── registry 동작 ─────────────────────────────────────────────────────────────


class TestRunRules:
    def test_run_rules_container_returns_results(self) -> None:
        from scripts.validators.registry import run_rules

        c = _minimal_container()
        results = run_rules("container", c)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_run_rules_container_has_sec_rules(self) -> None:
        from scripts.validators.registry import run_rules

        c = _minimal_container()
        rule_ids = {r.rule_id for r in run_rules("container", c)}
        assert "SEC-001" in rule_ids
        assert "IMG-001" in rule_ids
        assert "RES-001" in rule_ids

    def test_run_rules_pod_spec_returns_results(self) -> None:
        from scripts.validators.registry import run_rules

        pod = _minimal_pod_spec()
        results = run_rules("pod_spec", pod)
        assert isinstance(results, list)
        rule_ids = {r.rule_id for r in results}
        assert "SEC-006" in rule_ids
        assert "SA-001" in rule_ids

    def test_run_rules_service_returns_results(self) -> None:
        from scripts.validators.registry import run_rules

        doc = {
            "kind": "Service",
            "metadata": {"name": "svc"},
            "spec": {"selector": {"app": "app"}, "type": "ClusterIP"},
        }
        results = run_rules("service", doc)
        rule_ids = {r.rule_id for r in results}
        assert "SVC-001" in rule_ids

    def test_run_rules_container_pod_sc_kwarg(self) -> None:
        """SEC-001이 pod_sc kwarg를 통해 pod-level securityContext를 참조."""
        from scripts.validators.registry import run_rules

        c = {"name": "app", "image": "registry.example.com/app:latest"}
        pod_sc = {"runAsNonRoot": True}
        results = run_rules("container", c, pod_sc=pod_sc)
        sec001 = [r for r in results if r.rule_id == "SEC-001"]
        assert sec001, "SEC-001 결과가 있어야 함"
        assert sec001[0].level == "PASS", "pod_sc에 runAsNonRoot=True 이므로 PASS"
