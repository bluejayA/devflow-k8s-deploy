"""NET-W01 규칙 테스트 — manifest 집합에 NetworkPolicy 없으면 WARN."""

from __future__ import annotations

from scripts.validators.core import K8sValidator


def _minimal_deployment() -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "my-app"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "my-app"}},
            "template": {
                "metadata": {"labels": {"app": "my-app"}},
                "spec": {"containers": [{"name": "app", "image": "app:1.0"}]},
            },
        },
    }


def _networkpolicy_doc() -> dict:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "my-app-netpol"},
        "spec": {
            "podSelector": {"matchLabels": {"app": "my-app"}},
            "policyTypes": ["Ingress", "Egress"],
        },
    }


class TestNetW01:
    def _run_docs(self, docs: list[dict]) -> list:
        import tempfile
        from pathlib import Path

        import yaml

        validator = K8sValidator()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump_all(docs, f, default_flow_style=False)
            tmp_path = f.name

        try:
            report = validator.validate([tmp_path])
            return report.results
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_net_w01_no_networkpolicy(self) -> None:
        docs = [_minimal_deployment()]
        results = self._run_docs(docs)
        rule_ids = [r.rule_id for r in results]
        assert "NET-W01" in rule_ids
        net_result = next(r for r in results if r.rule_id == "NET-W01")
        assert net_result.level == "WARN"

    def test_net_w01_with_networkpolicy(self) -> None:
        docs = [_minimal_deployment(), _networkpolicy_doc()]
        results = self._run_docs(docs)
        net_results = [r for r in results if r.rule_id == "NET-W01"]
        assert all(r.level != "WARN" for r in net_results)

    def test_net_w01_empty_manifest_set(self) -> None:
        import tempfile
        from pathlib import Path

        validator = K8sValidator()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("---\n")
            tmp_path = f.name

        try:
            report = validator.validate([tmp_path])
            rule_ids = [r.rule_id for r in report.results]
            assert "NET-W01" in rule_ids
        finally:
            Path(tmp_path).unlink(missing_ok=True)
