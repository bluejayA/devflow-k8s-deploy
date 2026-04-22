"""STS-W01 규칙 테스트 — StatefulSet volumeClaimTemplates 존재 여부."""

from __future__ import annotations

from scripts.validators.core import K8sValidator


def _sts_doc(with_vct: bool = True) -> dict:
    doc = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {"name": "my-app", "namespace": "default"},
        "spec": {
            "replicas": 1,
            "serviceName": "my-app",
            "selector": {"matchLabels": {"app": "my-app"}},
            "template": {
                "metadata": {"labels": {"app": "my-app"}},
                "spec": {
                    "containers": [
                        {
                            "name": "app",
                            "image": "app:1.0.0",
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "512Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "automountServiceAccountToken": False,
                },
            },
        },
    }
    if with_vct:
        doc["spec"]["volumeClaimTemplates"] = [
            {
                "metadata": {"name": "data"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": "1Gi"}},
                },
            }
        ]
    return doc


def _deployment_doc() -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "my-app", "namespace": "default"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "my-app"}},
            "template": {
                "metadata": {"labels": {"app": "my-app"}},
                "spec": {
                    "containers": [
                        {
                            "name": "app",
                            "image": "app:1.0.0",
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "512Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "automountServiceAccountToken": False,
                },
            },
        },
    }


class TestStsW01:
    def _run_doc(self, doc: dict) -> list:
        validator = K8sValidator()
        return validator._validate_doc(doc)

    def test_sts_w01_no_vct(self) -> None:
        doc = _sts_doc(with_vct=False)
        results = self._run_doc(doc)
        rule_ids = [r.rule_id for r in results]
        assert "STS-W01" in rule_ids
        sts_result = next(r for r in results if r.rule_id == "STS-W01")
        assert sts_result.level == "WARN"

    def test_sts_w01_with_vct(self) -> None:
        doc = _sts_doc(with_vct=True)
        results = self._run_doc(doc)
        rule_ids = [r.rule_id for r in results]
        assert "STS-W01" not in rule_ids or all(
            r.level == "PASS" for r in results if r.rule_id == "STS-W01"
        )

    def test_sts_w01_deployment_not_triggered(self) -> None:
        doc = _deployment_doc()
        results = self._run_doc(doc)
        rule_ids = [r.rule_id for r in results]
        assert "STS-W01" not in rule_ids
