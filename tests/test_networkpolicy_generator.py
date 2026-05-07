"""ManifestGenerator.generate_networkpolicy() 테스트."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts._shared.types import ClusterConfig, UserInputs
from scripts.manifest_generator import ManifestGenerator
from scripts.template_renderer import TemplateRenderer

PROJECT_ROOT = Path(__file__).parent.parent


def _make_inputs(**kwargs: object) -> UserInputs:
    defaults = dict(
        app_name="my-app",
        port=8080,
        exposure="ClusterIP",
        namespace="default",
        output_dir=Path("/tmp/out"),
        resource_hint="small",
        replicas=1,
    )
    defaults.update(kwargs)
    return UserInputs(**defaults)


def _make_cluster_config(**kwargs: object) -> ClusterConfig:
    defaults = dict(preset="orbstack", storage_class="local-path", network_policy=True)
    defaults.update(kwargs)
    return ClusterConfig(**defaults)


def _make_generator() -> ManifestGenerator:
    renderer = TemplateRenderer(PROJECT_ROOT / "templates")
    return ManifestGenerator(renderer)


class TestGenerateNetworkpolicy:
    def test_generate_networkpolicy_deny_all(self) -> None:
        gen = _make_generator()
        inputs = _make_inputs()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_networkpolicy(inputs, cluster)
        assert yaml_str is not None
        doc = yaml.safe_load(yaml_str)

        assert doc["kind"] == "NetworkPolicy"
        assert doc["apiVersion"] == "networking.k8s.io/v1"
        # deny-all ingress: spec.ingress 없거나 빈 리스트
        spec = doc["spec"]
        assert spec.get("ingress") in (None, []) or spec.get("policyTypes", []) == [
            "Ingress",
            "Egress",
        ]

    def test_generate_networkpolicy_coredns_always_present(self) -> None:
        gen = _make_generator()
        inputs = _make_inputs()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_networkpolicy(
            inputs,
            cluster,
            allow_egress_to=[{"namespace": "monitoring", "port": 9090}],
        )
        assert yaml_str is not None
        doc = yaml.safe_load(yaml_str)

        # egress 규칙에 CoreDNS(kube-system:53) 포함 확인
        egress_rules = doc["spec"]["egress"]
        coredns_found = False
        for rule in egress_rules:
            for to in rule.get("to", []):
                ns_sel = to.get("namespaceSelector", {})
                if ns_sel.get("matchLabels", {}).get(
                    "kubernetes.io/metadata.name"
                ) == "kube-system":
                    ports = rule.get("ports", [])
                    port_numbers = {p["port"] for p in ports}
                    if 53 in port_numbers:
                        coredns_found = True
        assert coredns_found, "CoreDNS egress(kube-system:53) 누락"

    def test_generate_networkpolicy_allow_ingress(self) -> None:
        gen = _make_generator()
        inputs = _make_inputs()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_networkpolicy(
            inputs,
            cluster,
            allow_ingress_from=[{"namespace": "frontend", "port": 8080}],
        )
        assert yaml_str is not None
        doc = yaml.safe_load(yaml_str)

        ingress_rules = doc["spec"]["ingress"]
        assert isinstance(ingress_rules, list)
        assert len(ingress_rules) >= 1

    def test_generate_networkpolicy_allow_egress(self) -> None:
        gen = _make_generator()
        inputs = _make_inputs()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_networkpolicy(
            inputs,
            cluster,
            allow_egress_to=[{"namespace": "db", "port": 5432}],
        )
        assert yaml_str is not None
        doc = yaml.safe_load(yaml_str)

        egress_rules = doc["spec"]["egress"]
        # CoreDNS + 추가 규칙
        assert len(egress_rules) >= 2

    def test_generate_networkpolicy_none_when_disabled(self) -> None:
        gen = _make_generator()
        inputs = _make_inputs()
        cluster = _make_cluster_config(network_policy=False)

        result = gen.generate_networkpolicy(inputs, cluster)
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# BL-018: parsed YAML deep-equality baseline (Jinja2 전환 안전망)
# ──────────────────────────────────────────────────────────────────────────────


_BL018_NETWORKPOLICY_DENY_ALL_BASELINE: dict[str, object] = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "my-app-netpol", "namespace": "default"},
    "spec": {
        "podSelector": {"matchLabels": {"app": "my-app"}},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [],
        "egress": [
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                        }
                    }
                ],
                "ports": [
                    {"port": 53, "protocol": "UDP"},
                    {"port": 53, "protocol": "TCP"},
                ],
            }
        ],
    },
}


_BL018_NETWORKPOLICY_FULL_BASELINE: dict[str, object] = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "my-app-netpol", "namespace": "default"},
    "spec": {
        "podSelector": {"matchLabels": {"app": "my-app"}},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [
            {
                "from": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "frontend"}
                        }
                    }
                ],
                "ports": [{"port": 8080, "protocol": "TCP"}],
            }
        ],
        "egress": [
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                        }
                    }
                ],
                "ports": [
                    {"port": 53, "protocol": "UDP"},
                    {"port": 53, "protocol": "TCP"},
                ],
            },
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": "db"}
                        }
                    }
                ],
                "ports": [{"port": 5432, "protocol": "TCP"}],
            },
        ],
    },
}


class TestBL018NetworkpolicyParsedEquivalence:
    """BL-018: dict+yaml.dump → Jinja2 전환 시 parsed dict 의미 보존 가드.

    deny-all (CoreDNS만 허용) + ingress/egress 모두 추가된 케이스 양쪽 baseline lock down.
    """

    def test_networkpolicy_deny_all_parsed_equivalent_to_baseline(self) -> None:
        gen = _make_generator()
        inputs = _make_inputs()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_networkpolicy(inputs, cluster)
        assert yaml_str is not None
        doc = yaml.safe_load(yaml_str)

        assert doc == _BL018_NETWORKPOLICY_DENY_ALL_BASELINE

    def test_networkpolicy_full_parsed_equivalent_to_baseline(self) -> None:
        gen = _make_generator()
        inputs = _make_inputs()
        cluster = _make_cluster_config()

        yaml_str = gen.generate_networkpolicy(
            inputs,
            cluster,
            allow_ingress_from=[{"namespace": "frontend", "port": 8080}],
            allow_egress_to=[{"namespace": "db", "port": 5432}],
        )
        assert yaml_str is not None
        doc = yaml.safe_load(yaml_str)

        assert doc == _BL018_NETWORKPOLICY_FULL_BASELINE
