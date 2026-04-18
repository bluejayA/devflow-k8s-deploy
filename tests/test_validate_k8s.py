"""K8sValidator (validate_k8s.py) 단위 테스트.

TDD: 이 파일의 모든 테스트가 먼저 실패한 뒤 구현으로 통과시킨다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts._shared.types import CheckResult, ValidationReport  # noqa: F401
from scripts.validate_k8s import K8sValidator, _compute_exit_code

# ─── 픽스처 헬퍼 ────────────────────────────────────────────────────────────


def _minimal_deployment(
    *,
    container_name: str = "app",
    image: str = "myregistry.io/app:v1.0.0",
    run_as_non_root: bool = True,
    readonly_root: bool = True,
    allow_priv_esc: bool = False,
    capabilities_drop: list[str] | None = None,
    capabilities_add: list[str] | None = None,
    seccomp_type: str | None = "RuntimeDefault",
    privileged: bool | None = None,
    host_pid: bool = False,
    host_network: bool = False,
    host_ipc: bool = False,
    env_vars: list[dict] | None = None,
    resources: dict | None = None,
    service_account_name: str | None = "myapp-sa",
    automount_sa_token: bool = False,
    liveness_probe: dict | None = None,
    readiness_probe: dict | None = None,
) -> dict:
    """모든 검증을 통과하는 최소 Deployment dict 반환.

    개별 파라미터를 오버라이드하여 특정 규칙만 위반시킬 수 있다.
    """
    if capabilities_drop is None:
        capabilities_drop = ["ALL"]

    container_sc: dict = {
        "runAsNonRoot": run_as_non_root,
        "readOnlyRootFilesystem": readonly_root,
        "allowPrivilegeEscalation": allow_priv_esc,
        "capabilities": {
            "drop": capabilities_drop,
        },
    }
    if capabilities_add is not None:
        container_sc["capabilities"]["add"] = capabilities_add
    if privileged is not None:
        container_sc["privileged"] = privileged

    default_res: dict = {
        "requests": {"cpu": "100m", "memory": "128Mi"},
        "limits": {"cpu": "500m", "memory": "512Mi"},
    }

    default_liveness: dict = {
        "httpGet": {"path": "/healthz", "port": 8080},
        "initialDelaySeconds": 10,
    }
    default_readiness: dict = {
        "httpGet": {"path": "/ready", "port": 8080},
        "initialDelaySeconds": 5,
    }

    pod_sc: dict = {}
    if seccomp_type is not None:
        pod_sc["seccompProfile"] = {"type": seccomp_type}

    spec_extra: dict = {}
    if host_pid:
        spec_extra["hostPID"] = True
    if host_network:
        spec_extra["hostNetwork"] = True
    if host_ipc:
        spec_extra["hostIPC"] = True

    container: dict = {
        "name": container_name,
        "image": image,
        "securityContext": container_sc,
        "resources": resources if resources is not None else default_res,
        "livenessProbe": liveness_probe if liveness_probe is not None else default_liveness,
        "readinessProbe": readiness_probe if readiness_probe is not None else default_readiness,
    }
    if env_vars is not None:
        container["env"] = env_vars

    pod_spec: dict = {
        "serviceAccountName": service_account_name,
        "automountServiceAccountToken": automount_sa_token,
        "securityContext": pod_sc,
        "containers": [container],
        **spec_extra,
    }

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "myapp"},
        "spec": {
            "template": {
                "spec": pod_spec,
            }
        },
    }


def _manifest_yaml(*docs: dict, extra_yaml: str = "") -> str:
    """다수의 dict를 multi-document YAML 문자열로 직렬화."""
    parts = [yaml.dump(d, default_flow_style=False) for d in docs]
    result = "---\n".join(parts)
    if extra_yaml:
        result += f"\n---\n{extra_yaml}"
    return result


def _validator(skipped: list[str] | None = None) -> K8sValidator:
    return K8sValidator(skipped=skipped or [])


# ─── SEC-001: runAsNonRoot ───────────────────────────────────────────────────


class TestSEC001:
    def test_sec001_runasnonroot_missing_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        # securityContext 자체에서 runAsNonRoot 제거
        doc["spec"]["template"]["spec"]["containers"][0]["securityContext"].pop(
            "runAsNonRoot", None
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-001" in fail_ids

    def test_sec001_runasnonroot_false_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-001" in fail_ids

    def test_sec001_runasnotroot_true_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=True)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-001" not in fail_ids


# ─── SEC-002: readOnlyRootFilesystem ────────────────────────────────────────


class TestSEC002:
    def test_sec002_readonlyrootfilesystem_false_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(readonly_root=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-002" in fail_ids

    def test_sec002_readonlyrootfilesystem_true_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(readonly_root=True)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-002" not in fail_ids


# ─── SEC-003: allowPrivilegeEscalation ──────────────────────────────────────


class TestSEC003:
    def test_sec003_allow_priv_esc_true_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(allow_priv_esc=True)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-003" in fail_ids

    def test_sec003_allow_priv_esc_false_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(allow_priv_esc=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-003" not in fail_ids


# ─── SEC-004: capabilities.drop ALL ─────────────────────────────────────────


class TestSEC004:
    def test_sec004_capabilities_drop_all_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(capabilities_drop=["ALL"])
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-004" not in fail_ids

    def test_sec004_capabilities_drop_missing_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(capabilities_drop=[])
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-004" in fail_ids


# ─── SEC-005: dangerous capabilities ────────────────────────────────────────


class TestSEC005:
    def test_sec005_dangerous_capability_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(capabilities_add=["SYS_ADMIN"])
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-005" in fail_ids

    def test_sec005_net_admin_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(capabilities_add=["NET_ADMIN"])
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-005" in fail_ids

    def test_sec005_safe_capability_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(capabilities_add=["NET_BIND_SERVICE"])
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-005" not in fail_ids


# ─── SEC-006: seccompProfile ─────────────────────────────────────────────────


class TestSEC006:
    def test_sec006_seccomp_missing_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(seccomp_type=None)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-006" in fail_ids

    def test_sec006_seccomp_runtime_default_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(seccomp_type="RuntimeDefault")
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-006" not in fail_ids

    def test_sec006_seccomp_localhost_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(seccomp_type="Localhost")
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-006" not in fail_ids

    def test_sec006_seccomp_unconfined_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(seccomp_type="Unconfined")
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-006" in fail_ids


# ─── SEC-007: privileged ─────────────────────────────────────────────────────


class TestSEC007:
    def test_sec007_privileged_true_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(privileged=True)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-007" in fail_ids

    def test_sec007_privileged_false_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(privileged=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-007" not in fail_ids


# ─── SEC-008: hostPID / hostNetwork / hostIPC ────────────────────────────────


class TestSEC008:
    def test_sec008_hostnetwork_true_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(host_network=True)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-008" in fail_ids

    def test_sec008_hostpid_true_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(host_pid=True)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-008" in fail_ids

    def test_sec008_hostipc_true_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(host_ipc=True)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-008" in fail_ids

    def test_sec008_no_host_flags_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-008" not in fail_ids


# ─── SEC-009: plaintext secret detection ────────────────────────────────────


class TestSEC009:
    def test_sec009_plaintext_secret_detected(self, tmp_path: Path) -> None:
        env_vars = [
            {"name": "DB_PASSWORD", "value": "mysupersecretpassword123"},
        ]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-009" in fail_ids

    def test_sec009_api_key_detected(self, tmp_path: Path) -> None:
        env_vars = [
            {"name": "API_KEY", "value": "sk-abcdefghijklmnopqrstuvwxyz1234"},
        ]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-009" in fail_ids

    def test_sec009_secretref_passes(self, tmp_path: Path) -> None:
        env_vars = [
            {
                "name": "DB_PASSWORD",
                "valueFrom": {
                    "secretKeyRef": {"name": "db-secret", "key": "password"}
                },
            }
        ]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-009" not in fail_ids

    def test_sec009_empty_value_passes(self, tmp_path: Path) -> None:
        env_vars = [{"name": "APP_ENV", "value": "production"}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SEC-009" not in fail_ids


# ─── RES-001: resources ──────────────────────────────────────────────────────


class TestRES001:
    def test_res001_missing_resources_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(resources={})
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "RES-001" in fail_ids

    def test_res001_partial_resources_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(
            resources={"requests": {"cpu": "100m"}, "limits": {"memory": "256Mi"}}
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "RES-001" in fail_ids

    def test_res001_complete_resources_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "RES-001" not in fail_ids


# ─── IMG-001 + IMG-W01 ────────────────────────────────────────────────────────


class TestIMG001:
    def test_img001_latest_tag_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app:latest")
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "IMG-001" in fail_ids

    def test_img001_no_tag_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app")
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "IMG-001" in fail_ids

    def test_img001_versioned_tag_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app:v1.2.3")
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "IMG-001" not in fail_ids

    def test_img_w01_no_digest_warns(self, tmp_path: Path) -> None:
        # 태그는 있지만 digest(@sha256:...) 없으면 WARN
        doc = _minimal_deployment(image="myregistry.io/app:v1.2.3")
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        warn_ids = [r.rule_id for r in report.results if r.level == "WARN"]
        assert "IMG-W01" in warn_ids

    def test_img_w01_digest_no_warn(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(
            image="myregistry.io/app:v1.2.3@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        warn_ids = [r.rule_id for r in report.results if r.level == "WARN"]
        assert "IMG-W01" not in warn_ids


# ─── SA-001 + SA-002 ─────────────────────────────────────────────────────────


class TestSA:
    def test_sa001_no_serviceaccount_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(service_account_name=None)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SA-001" in fail_ids

    def test_sa001_with_serviceaccount_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(service_account_name="myapp-sa")
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SA-001" not in fail_ids

    def test_sa002_automount_true_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(automount_sa_token=True)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SA-002" in fail_ids

    def test_sa002_automount_false_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(automount_sa_token=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SA-002" not in fail_ids


# ─── SVC-001 + SVC-002 ───────────────────────────────────────────────────────


def _service_yaml(*, svc_type: str | None = "ClusterIP") -> dict:
    svc: dict = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "myapp-svc"},
        "spec": {
            "selector": {"app": "myapp"},
            "ports": [{"port": 80, "targetPort": 8080}],
        },
    }
    if svc_type is not None:
        svc["spec"]["type"] = svc_type
    return svc


class TestSVC:
    def test_svc001_no_type_fails(self, tmp_path: Path) -> None:
        svc = _service_yaml(svc_type=None)
        mf = tmp_path / "svc.yaml"
        mf.write_text(_manifest_yaml(svc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SVC-001" in fail_ids

    def test_svc001_clusterip_passes(self, tmp_path: Path) -> None:
        svc = _service_yaml(svc_type="ClusterIP")
        mf = tmp_path / "svc.yaml"
        mf.write_text(_manifest_yaml(svc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "SVC-001" not in fail_ids

    def test_svc002_loadbalancer_warns(self, tmp_path: Path) -> None:
        svc = _service_yaml(svc_type="LoadBalancer")
        mf = tmp_path / "svc.yaml"
        mf.write_text(_manifest_yaml(svc))

        report = _validator().validate([mf])
        warn_ids = [r.rule_id for r in report.results if r.level == "WARN"]
        assert "SVC-002" in warn_ids

    def test_svc002_nodeport_no_warn(self, tmp_path: Path) -> None:
        svc = _service_yaml(svc_type="NodePort")
        mf = tmp_path / "svc.yaml"
        mf.write_text(_manifest_yaml(svc))

        report = _validator().validate([mf])
        warn_ids = [r.rule_id for r in report.results if r.level == "WARN"]
        assert "SVC-002" not in warn_ids


# ─── PRB-001 + PRB-002 ───────────────────────────────────────────────────────


class TestPRB:
    def test_prb001_no_probes_fails(self, tmp_path: Path) -> None:
        # liveness/readiness 모두 제거
        doc = _minimal_deployment(
            liveness_probe=None,  # type: ignore[arg-type]
            readiness_probe=None,  # type: ignore[arg-type]
        )
        # _minimal_deployment 는 None 이면 기본값을 사용하므로 직접 제거
        container = doc["spec"]["template"]["spec"]["containers"][0]
        container.pop("livenessProbe", None)
        container.pop("readinessProbe", None)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "PRB-001" in fail_ids

    def test_prb001_only_liveness_fails(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        container = doc["spec"]["template"]["spec"]["containers"][0]
        container.pop("readinessProbe", None)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "PRB-001" in fail_ids

    def test_prb001_both_probes_passes(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fail_ids = [r.rule_id for r in report.results if r.level == "FAIL"]
        assert "PRB-001" not in fail_ids

    def test_prb002_initialdelay_zero_warns(self, tmp_path: Path) -> None:
        probe_zero = {"httpGet": {"path": "/healthz", "port": 8080}, "initialDelaySeconds": 0}
        doc = _minimal_deployment(liveness_probe=probe_zero)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        warn_ids = [r.rule_id for r in report.results if r.level == "WARN"]
        assert "PRB-002" in warn_ids

    def test_prb002_positive_delay_no_warn(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()  # 기본값 initialDelaySeconds=10
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        warn_ids = [r.rule_id for r in report.results if r.level == "WARN"]
        assert "PRB-002" not in warn_ids


# ─── RES-W01: CPU limit < request ────────────────────────────────────────────


class TestRESW01:
    def test_res_w01_cpu_limit_less_than_request_warns(self, tmp_path: Path) -> None:
        # cpu request=500m, limit=100m → limit < request
        res = {
            "requests": {"cpu": "500m", "memory": "128Mi"},
            "limits": {"cpu": "100m", "memory": "512Mi"},
        }
        doc = _minimal_deployment(resources=res)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        warn_ids = [r.rule_id for r in report.results if r.level == "WARN"]
        assert "RES-W01" in warn_ids

    def test_res_w01_sane_cpu_no_warn(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        warn_ids = [r.rule_id for r in report.results if r.level == "WARN"]
        assert "RES-W01" not in warn_ids


# ─── YAML 파싱 / 멀티문서 / 디렉토리 탐색 ──────────────────────────────────────


class TestYAMLHandling:
    def test_malformed_yaml_reports_fail(self, tmp_path: Path) -> None:
        mf = tmp_path / "bad.yaml"
        mf.write_text("key: [unclosed bracket\n")

        report = _validator().validate([mf])
        assert report.exit_code == 1
        assert any(r.level == "FAIL" for r in report.results)

    def test_multi_document_yaml(self, tmp_path: Path) -> None:
        dep = _minimal_deployment()
        svc = _service_yaml(svc_type="ClusterIP")
        mf = tmp_path / "manifests.yaml"
        mf.write_text(_manifest_yaml(dep, svc))

        report = _validator().validate([mf])
        rule_ids = {r.rule_id for r in report.results}
        # Deployment 규칙과 Service 규칙이 모두 체크됨
        assert any(rid.startswith("SEC-") for rid in rule_ids)
        assert any(rid.startswith("SVC-") for rid in rule_ids)

    def test_directory_walks_yaml_files(self, tmp_path: Path) -> None:
        sub = tmp_path / "k8s"
        sub.mkdir()
        dep = _minimal_deployment()
        (sub / "deployment.yaml").write_text(_manifest_yaml(dep))
        svc = _service_yaml()
        (sub / "service.yaml").write_text(_manifest_yaml(svc))

        report = _validator().validate([sub])
        rule_ids = {r.rule_id for r in report.results}
        assert any(rid.startswith("SEC-") for rid in rule_ids)
        assert any(rid.startswith("SVC-") for rid in rule_ids)

    def test_empty_yaml_document_skipped(self, tmp_path: Path) -> None:
        mf = tmp_path / "empty.yaml"
        mf.write_text("---\n---\n")

        # 빈 document 처리 시 예외 발생하지 않음
        report = _validator().validate([mf])
        assert isinstance(report, ValidationReport)


# ─── Exit code ───────────────────────────────────────────────────────────────


class TestExitCode:
    def test_exit_code_0_all_pass(self, tmp_path: Path) -> None:
        # 완전히 올바른 manifest → exit_code 0
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        report = _validator().validate([mf])
        assert report.exit_code == 0

    def test_exit_code_1_any_fail(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        assert report.exit_code == 1

    def test_exit_code_2_warn_only(self, tmp_path: Path) -> None:
        # LoadBalancer Service → SVC-002 WARN, FAIL 없음
        svc = _service_yaml(svc_type="LoadBalancer")
        mf = tmp_path / "svc.yaml"
        mf.write_text(_manifest_yaml(svc))

        report = _validator().validate([mf])
        assert report.exit_code == 2

    def test_compute_exit_code_logic(self) -> None:
        assert _compute_exit_code({"pass": 5, "warn": 0, "fail": 0}) == 0
        assert _compute_exit_code({"pass": 3, "warn": 2, "fail": 1}) == 1
        assert _compute_exit_code({"pass": 3, "warn": 2, "fail": 0}) == 2
        assert _compute_exit_code({"pass": 0, "warn": 0, "fail": 0}) == 0


# ─── JSON 출력 ───────────────────────────────────────────────────────────────


class TestJSONOutput:
    def test_json_output_contains_all_fields(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        v = K8sValidator(skipped=["kubectl_dry_run"])
        report = v.validate([mf])
        output = v.to_json(report, skipped=["kubectl_dry_run"])

        data = json.loads(output)
        assert "results" in data
        assert "counts" in data
        assert "exit_code" in data
        assert "skipped" in data

    def test_skipped_field_passed_through_to_json(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        v = K8sValidator(skipped=["kubectl_dry_run", "container_build"])
        report = v.validate([mf])
        output = v.to_json(report, skipped=["kubectl_dry_run", "container_build"])

        data = json.loads(output)
        assert "kubectl_dry_run" in data["skipped"]
        assert "container_build" in data["skipped"]

    def test_json_results_have_required_keys(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(run_as_non_root=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        v = K8sValidator()
        report = v.validate([mf])
        data = json.loads(v.to_json(report))

        for item in data["results"]:
            assert "rule_id" in item
            assert "level" in item
            assert "container" in item
            assert "message_ko" in item
            assert "message_en" in item
            assert "suggestion" in item

    def test_skipped_in_report_without_extra_arg(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        v = K8sValidator(skipped=["kubectl_dry_run"])
        report = v.validate([mf])

        assert "kubectl_dry_run" in report.skipped

    def test_counts_accurate(self, tmp_path: Path) -> None:
        # FAIL + WARN 모두 발생하는 케이스에서 counts 검증
        dep = _minimal_deployment(run_as_non_root=False)  # SEC-001 FAIL
        svc = _service_yaml(svc_type="LoadBalancer")  # SVC-002 WARN
        mf = tmp_path / "multi.yaml"
        mf.write_text(_manifest_yaml(dep, svc))

        report = _validator().validate([mf])
        assert report.counts["fail"] >= 1
        assert report.counts["warn"] >= 1


# ─── CheckResult 메시지 품질 ─────────────────────────────────────────────────


class TestMessageQuality:
    def test_checkresult_has_korean_and_english_messages(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        fails = [r for r in report.results if r.rule_id == "SEC-001" and r.level == "FAIL"]
        assert len(fails) >= 1
        cr = fails[0]
        assert cr.message_ko, "message_ko 비어있음"
        assert cr.message_en, "message_en 비어있음"
        assert cr.suggestion, "suggestion 비어있음"

    def test_checkresult_rule_id_format(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(doc))

        report = _validator().validate([mf])
        for r in report.results:
            # rule_id는 PREFIX-NNN 형식
            parts = r.rule_id.split("-")
            assert len(parts) >= 2, f"잘못된 rule_id 형식: {r.rule_id}"


# ─── CLI 통합 (argparse + main) ───────────────────────────────────────────────


class TestCLI:
    def test_cli_exit_0_on_clean_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        from scripts.validate_k8s import main

        monkeypatch.setattr(sys, "argv", ["validate_k8s.py", str(mf)])
        code = main()
        assert code == 0

    def test_cli_exit_1_on_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        dep = _minimal_deployment(run_as_non_root=False)
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        from scripts.validate_k8s import main

        monkeypatch.setattr(sys, "argv", ["validate_k8s.py", str(mf)])
        code = main()
        assert code == 1

    def test_cli_json_flag_outputs_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import sys

        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        from scripts.validate_k8s import main

        monkeypatch.setattr(sys, "argv", ["validate_k8s.py", "--json", str(mf)])
        main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "results" in data

    def test_cli_skipped_flag_passed_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import sys

        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = tmp_path / "dep.yaml"
        mf.write_text(_manifest_yaml(dep))

        from scripts.validate_k8s import main

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "validate_k8s.py",
                "--json",
                "--skipped",
                "kubectl_dry_run",
                "container_build",
                "--",
                str(mf),
            ],
        )
        main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "kubectl_dry_run" in data["skipped"]
        assert "container_build" in data["skipped"]
