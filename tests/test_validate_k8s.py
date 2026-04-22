"""K8sValidator (validate_k8s.py) 단위 테스트.

F-43 Rule 매트릭스 기준으로 전면 재작성.
TDD: 이 파일의 모든 테스트가 먼저 실패한 뒤 구현으로 통과시킨다.

규칙 매트릭스 (F-43):
  SEC-001: runAsNonRoot: true (Pod or container securityContext)
  SEC-002: privileged: true 금지
  SEC-003: allowPrivilegeEscalation: false 필수
  SEC-004: readOnlyRootFilesystem: true 필수
  SEC-005: capabilities.drop=[ALL] 필수
  SEC-006: seccompProfile.type=RuntimeDefault|Localhost (Pod)
  SEC-007: runAsUser > 0 (Pod or container)
  SEC-008: fsGroup > 0 (Pod)
  SEC-009: 평문 시크릿 금지 (env[].value)
  RES-001: resources.requests/limits cpu+memory 완비
  IMG-001: latest 태그 또는 태그 누락 금지
  SA-001:  automountServiceAccountToken: false
  SA-002:  serviceAccountName 명시
  SVC-001: Service 리소스 존재
  SVC-002: targetPort ↔ containerPort 일치
  PRB-001: livenessProbe 존재
  PRB-002: readinessProbe 존재
  RES-W01: CPU limit/request > 4배 WARN
  IMG-W01: digest pinning 미사용 WARN
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
    # SEC-001: runAsNonRoot
    run_as_non_root: bool = True,
    # SEC-002: privileged
    privileged: bool | None = None,
    # SEC-003: allowPrivilegeEscalation
    allow_priv_esc: bool = False,
    # SEC-004: readOnlyRootFilesystem
    readonly_root: bool = True,
    # SEC-005: capabilities.drop
    capabilities_drop: list[str] | None = None,
    # SEC-006: seccompProfile (Pod level)
    seccomp_type: str | None = "RuntimeDefault",
    # SEC-007: runAsUser (container level, overrides pod)
    run_as_user: int | None = 1000,
    # SEC-008: fsGroup (Pod level)
    fs_group: int | None = 1000,
    # SEC-009: env vars
    env_vars: list[dict] | None = None,
    # RES-001
    resources: dict | None = None,
    # SA-001: automountServiceAccountToken
    automount_sa_token: bool = False,
    # SA-002: serviceAccountName
    service_account_name: str | None = "myapp-sa",
    # PRB-001/002
    liveness_probe: dict | None = None,
    readiness_probe: dict | None = None,
    # container ports (for SVC-002 cross-check)
    container_ports: list[dict] | None = None,
    # LIFE-W01: terminationGracePeriodSeconds (pod level)
    termination_grace_period: int | None = 30,
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
    if privileged is not None:
        container_sc["privileged"] = privileged
    if run_as_user is not None:
        container_sc["runAsUser"] = run_as_user

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
    if fs_group is not None:
        pod_sc["fsGroup"] = fs_group

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
    if container_ports is not None:
        container["ports"] = container_ports

    pod_spec: dict = {
        "automountServiceAccountToken": automount_sa_token,
        "securityContext": pod_sc,
        "containers": [container],
    }
    if service_account_name is not None:
        pod_spec["serviceAccountName"] = service_account_name
    if termination_grace_period is not None:
        pod_spec["terminationGracePeriodSeconds"] = termination_grace_period

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


def _minimal_service(
    *,
    svc_name: str = "myapp-svc",
    svc_type: str | None = "ClusterIP",
    target_port: int | str = 8080,
    port: int = 80,
) -> dict:
    """Service document 생성 헬퍼."""
    svc: dict = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": svc_name},
        "spec": {
            "selector": {"app": "myapp"},
            "ports": [{"port": port, "targetPort": target_port}],
        },
    }
    if svc_type is not None:
        svc["spec"]["type"] = svc_type
    return svc


def _manifest_yaml(*docs: dict, extra_yaml: str = "") -> str:
    """다수의 dict를 multi-document YAML 문자열로 직렬화."""
    parts = [yaml.dump(d, default_flow_style=False) for d in docs]
    result = "---\n".join(parts)
    if extra_yaml:
        result += f"\n---\n{extra_yaml}"
    return result


def _validator(skipped: list[str] | None = None) -> K8sValidator:
    return K8sValidator(skipped=skipped or [])


def _write_file(tmp_path: Path, *docs: dict, filename: str = "manifest.yaml") -> Path:
    """tmp_path에 YAML 파일을 작성하고 경로를 반환."""
    mf = tmp_path / filename
    mf.write_text(_manifest_yaml(*docs))
    return mf


# ─── SEC-001: runAsNonRoot ───────────────────────────────────────────────────


class TestSEC001:
    """SEC-001: runAsNonRoot: true 필수 (Pod 또는 container securityContext)."""

    def test_fail_when_run_as_non_root_missing(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        doc["spec"]["template"]["spec"]["containers"][0]["securityContext"].pop(
            "runAsNonRoot", None
        )
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_run_as_non_root_false(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_run_as_non_root_true(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=True)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-001" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_pod_level_run_as_non_root_true(self, tmp_path: Path) -> None:
        """Pod securityContext에서 runAsNonRoot=true 이면 container PASS."""
        doc = _minimal_deployment(run_as_non_root=False)
        # container 레벨에서 제거하고 pod 레벨에 설정
        container_sc = doc["spec"]["template"]["spec"]["containers"][0]["securityContext"]
        container_sc.pop("runAsNonRoot", None)
        doc["spec"]["template"]["spec"]["securityContext"]["runAsNonRoot"] = True
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-001" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SEC-002: privileged 금지 ────────────────────────────────────────────────


class TestSEC002:
    """SEC-002: privileged: true 금지."""

    def test_fail_when_privileged_true(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(privileged=True)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-002" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_privileged_false(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(privileged=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-002" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_privileged_not_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()  # privileged 미설정
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-002" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SEC-003: allowPrivilegeEscalation ──────────────────────────────────────


class TestSEC003:
    """SEC-003: allowPrivilegeEscalation: false 필수."""

    def test_fail_when_allow_priv_esc_true(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(allow_priv_esc=True)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-003" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_allow_priv_esc_not_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(allow_priv_esc=False)
        doc["spec"]["template"]["spec"]["containers"][0]["securityContext"].pop(
            "allowPrivilegeEscalation", None
        )
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-003" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_allow_priv_esc_false(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(allow_priv_esc=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-003" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SEC-004: readOnlyRootFilesystem ────────────────────────────────────────


class TestSEC004:
    """SEC-004: readOnlyRootFilesystem: true 필수."""

    def test_fail_when_readonly_root_false(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(readonly_root=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-004" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_readonly_root_not_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        doc["spec"]["template"]["spec"]["containers"][0]["securityContext"].pop(
            "readOnlyRootFilesystem", None
        )
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-004" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_readonly_root_true(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(readonly_root=True)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-004" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SEC-005: capabilities.drop=[ALL] ───────────────────────────────────────


class TestSEC005:
    """SEC-005: capabilities.drop에 ALL 포함 필수."""

    def test_pass_when_drop_all(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(capabilities_drop=["ALL"])
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-005" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_drop_empty(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(capabilities_drop=[])
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-005" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_drop_partial_no_all(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(capabilities_drop=["NET_RAW", "SYS_ADMIN"])
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-005" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_capabilities_not_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        doc["spec"]["template"]["spec"]["containers"][0]["securityContext"].pop(
            "capabilities", None
        )
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-005" in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SEC-006: seccompProfile ─────────────────────────────────────────────────


class TestSEC006:
    """SEC-006: Pod seccompProfile.type=RuntimeDefault|Localhost."""

    def test_fail_when_seccomp_missing(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(seccomp_type=None)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-006" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_seccomp_runtime_default(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(seccomp_type="RuntimeDefault")
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-006" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_seccomp_localhost(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(seccomp_type="Localhost")
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-006" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_seccomp_unconfined(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(seccomp_type="Unconfined")
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-006" in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SEC-007: runAsUser > 0 ──────────────────────────────────────────────────


class TestSEC007:
    """SEC-007: runAsUser > 0 필수 (root=0 금지)."""

    def test_fail_when_run_as_user_zero(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_user=0)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-007" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_run_as_user_not_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_user=None)
        # pod level에도 없는지 확인
        pod_sc = doc["spec"]["template"]["spec"]["securityContext"]
        pod_sc.pop("runAsUser", None)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-007" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_run_as_user_nonzero(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_user=1000)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-007" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_pod_level_run_as_user(self, tmp_path: Path) -> None:
        """Pod securityContext에 runAsUser가 있으면 container에서 미설정이어도 PASS."""
        doc = _minimal_deployment(run_as_user=None)
        pod_sc = doc["spec"]["template"]["spec"]["securityContext"]
        pod_sc["runAsUser"] = 1000
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-007" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SEC-008: fsGroup > 0 ────────────────────────────────────────────────────


class TestSEC008:
    """SEC-008: fsGroup > 0 필수 (Pod securityContext)."""

    def test_fail_when_fs_group_zero(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(fs_group=0)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-008" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_fs_group_not_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(fs_group=None)
        pod_sc = doc["spec"]["template"]["spec"]["securityContext"]
        pod_sc.pop("fsGroup", None)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-008" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_fs_group_nonzero(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(fs_group=1000)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-008" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SEC-009: 평문 시크릿 ───────────────────────────────────────────────────


class TestSEC009:
    """SEC-009: env[].value에 평문 시크릿 금지."""

    def test_fail_when_db_password_plaintext(self, tmp_path: Path) -> None:
        env_vars = [{"name": "DB_PASSWORD", "value": "mysupersecret"}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-009" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_api_key_plaintext(self, tmp_path: Path) -> None:
        env_vars = [{"name": "API_KEY", "value": "sk-abc"}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-009" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_token_plaintext(self, tmp_path: Path) -> None:
        env_vars = [{"name": "AUTH_TOKEN", "value": "t"}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-009" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_secret_ref_used(self, tmp_path: Path) -> None:
        env_vars = [
            {
                "name": "DB_PASSWORD",
                "valueFrom": {
                    "secretKeyRef": {"name": "db-secret", "key": "password"}
                },
            }
        ]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-009" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_non_secret_env_var(self, tmp_path: Path) -> None:
        env_vars = [{"name": "APP_ENV", "value": "production"}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-009" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_password_short_value(self, tmp_path: Path) -> None:
        """길이 조건 없음 — 짧은 값도 FAIL."""
        env_vars = [{"name": "SECRET", "value": "x"}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-009" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_value_is_empty_string(self, tmp_path: Path) -> None:
        """빈 문자열 value는 PASS."""
        env_vars = [{"name": "SECRET_KEY", "value": ""}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-009" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_case_insensitive_secret_name(self, tmp_path: Path) -> None:
        """대소문자 무관 패턴 매치."""
        env_vars = [{"name": "Db_PassWord", "value": "plainvalue"}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-009" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_suggestion_contains_secret_key_ref(self, tmp_path: Path) -> None:
        """제안 메시지에 valueFrom.secretKeyRef 포함 (F-46a)."""
        env_vars = [{"name": "DB_PASSWORD", "value": "mysupersecret"}]
        doc = _minimal_deployment(env_vars=env_vars)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        fail_results = [r for r in report.results if r.rule_id == "SEC-009" and r.level == "FAIL"]
        assert fail_results
        assert "secretKeyRef" in fail_results[0].suggestion


# ─── RES-001: resources ──────────────────────────────────────────────────────


class TestRES001:
    """RES-001: cpu+memory requests/limits 완비."""

    def test_fail_when_resources_empty(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(resources={})
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "RES-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_partial_resources(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(
            resources={"requests": {"cpu": "100m"}, "limits": {"memory": "256Mi"}}
        )
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "RES-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_all_resources_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "RES-001" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── IMG-001 ─────────────────────────────────────────────────────────────────


class TestIMG001:
    """IMG-001: latest 태그 또는 태그 누락 금지."""

    def test_fail_when_latest_tag(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app:latest")
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "IMG-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_no_tag(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app")
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "IMG-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_versioned_tag(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app:v1.2.3")
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "IMG-001" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SA-001 ───────────────────────────────────────────────────────────────────


class TestSA001:
    """SA-001: automountServiceAccountToken: false 필수."""

    def test_fail_when_automount_true(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(automount_sa_token=True)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SA-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_automount_not_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(automount_sa_token=False)
        doc["spec"]["template"]["spec"].pop("automountServiceAccountToken", None)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SA-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_automount_false(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(automount_sa_token=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SA-001" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SA-002 ───────────────────────────────────────────────────────────────────


class TestSA002:
    """SA-002: serviceAccountName 명시."""

    def test_fail_when_sa_name_missing(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(service_account_name=None)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SA-002" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_sa_name_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(service_account_name="myapp-sa")
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SA-002" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── SVC-001 ─────────────────────────────────────────────────────────────────


class TestSVC001:
    """SVC-001: Service 리소스 존재."""

    def test_pass_when_service_exists(self, tmp_path: Path) -> None:
        """Service document가 있으면 SVC-001 PASS."""
        svc = _minimal_service()
        mf = _write_file(tmp_path, svc)
        report = _validator().validate([mf])
        pass_ids = [r.rule_id for r in report.results if r.level == "PASS"]
        assert "SVC-001" in pass_ids

    def test_svc001_not_triggered_for_deployment(self, tmp_path: Path) -> None:
        """Deployment만 있으면 SVC-001이 체크되지 않음 (Service 없음)."""
        dep = _minimal_deployment()
        mf = _write_file(tmp_path, dep)
        report = _validator().validate([mf])
        svc001_results = [r for r in report.results if r.rule_id == "SVC-001"]
        assert len(svc001_results) == 0


# ─── SVC-002 ─────────────────────────────────────────────────────────────────


class TestSVC002:
    """SVC-002: targetPort ↔ containerPort 일치 (교차 검증)."""

    def test_pass_when_target_port_matches_container_port(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(container_ports=[{"containerPort": 8080}])
        svc = _minimal_service(target_port=8080)
        mf = _write_file(tmp_path, dep, svc)
        report = _validator().validate([mf])
        assert "SVC-002" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_target_port_mismatch(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(container_ports=[{"containerPort": 8080}])
        svc = _minimal_service(target_port=9999)
        mf = _write_file(tmp_path, dep, svc)
        report = _validator().validate([mf])
        assert "SVC-002" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_named_port_matches(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            container_ports=[{"name": "http", "containerPort": 8080}]
        )
        svc = _minimal_service(target_port="http")
        mf = _write_file(tmp_path, dep, svc)
        report = _validator().validate([mf])
        assert "SVC-002" not in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_fail_when_named_port_mismatch(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            container_ports=[{"name": "http", "containerPort": 8080}]
        )
        svc = _minimal_service(target_port="grpc")
        mf = _write_file(tmp_path, dep, svc)
        report = _validator().validate([mf])
        assert "SVC-002" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_skip_when_no_deployment_in_context(self, tmp_path: Path) -> None:
        """Deployment가 없으면 SVC-002 skip (컨테이너 포트 불명)."""
        svc = _minimal_service(target_port=8080)
        mf = _write_file(tmp_path, svc)
        report = _validator().validate([mf])
        svc002_results = [r for r in report.results if r.rule_id == "SVC-002"]
        # containerPort 없으면 skip → 결과 없음
        assert len(svc002_results) == 0


# ─── PRB-001 ─────────────────────────────────────────────────────────────────


class TestPRB001:
    """PRB-001: livenessProbe 존재."""

    def test_fail_when_liveness_probe_missing(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        doc["spec"]["template"]["spec"]["containers"][0].pop("livenessProbe", None)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "PRB-001" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_liveness_probe_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "PRB-001" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── PRB-002 ─────────────────────────────────────────────────────────────────


class TestPRB002:
    """PRB-002: readinessProbe 존재."""

    def test_fail_when_readiness_probe_missing(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        doc["spec"]["template"]["spec"]["containers"][0].pop("readinessProbe", None)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "PRB-002" in [r.rule_id for r in report.results if r.level == "FAIL"]

    def test_pass_when_readiness_probe_set(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "PRB-002" not in [r.rule_id for r in report.results if r.level == "FAIL"]


# ─── RES-W01: CPU limit/request > 4배 ───────────────────────────────────────


class TestRESW01:
    """RES-W01: limit/request > 4배 WARN."""

    def test_warn_when_ratio_exceeds_4x(self, tmp_path: Path) -> None:
        res = {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        }
        doc = _minimal_deployment(resources=res)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "RES-W01" in [r.rule_id for r in report.results if r.level == "WARN"]

    def test_no_warn_when_ratio_exactly_4x(self, tmp_path: Path) -> None:
        res = {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "400m", "memory": "512Mi"},
        }
        doc = _minimal_deployment(resources=res)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "RES-W01" not in [r.rule_id for r in report.results if r.level == "WARN"]

    def test_no_warn_when_sane_ratio(self, tmp_path: Path) -> None:
        doc = _minimal_deployment()  # 100m / 500m = 5x → WARN
        # 기본값은 5배이므로 4배 이하로 변경
        doc["spec"]["template"]["spec"]["containers"][0]["resources"] = {
            "requests": {"cpu": "200m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        }
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "RES-W01" not in [r.rule_id for r in report.results if r.level == "WARN"]


# ─── IMG-W01: digest pinning ─────────────────────────────────────────────────


class TestIMGW01:
    """IMG-W01: digest pinning 미사용 WARN."""

    def test_warn_when_no_digest(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app:v1.2.3")
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "IMG-W01" in [r.rule_id for r in report.results if r.level == "WARN"]

    def test_no_warn_when_digest_pinned(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(
            image="myregistry.io/app:v1.2.3@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "IMG-W01" not in [r.rule_id for r in report.results if r.level == "WARN"]


# ─── LIFE-W01: terminationGracePeriodSeconds ──────────────────────────────────


class TestLIFEW01:
    """LIFE-W01: terminationGracePeriodSeconds 미설정 또는 30 미만 WARN."""

    def test_warn_when_missing(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(termination_grace_period=None)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "LIFE-W01" in [r.rule_id for r in report.results if r.level == "WARN"]

    def test_warn_when_below_threshold(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(termination_grace_period=10)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "LIFE-W01" in [r.rule_id for r in report.results if r.level == "WARN"]

    def test_no_warn_when_at_threshold(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(termination_grace_period=30)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "LIFE-W01" not in [r.rule_id for r in report.results if r.level == "WARN"]

    def test_warn_when_non_numeric(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(termination_grace_period=None)
        doc["spec"]["template"]["spec"]["terminationGracePeriodSeconds"] = "30s"
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "LIFE-W01" in [r.rule_id for r in report.results if r.level == "WARN"]


# ─── IMG-W02: imagePullPolicy Always + digest 없음 ────────────────────────────


class TestIMGW02:
    """IMG-W02: imagePullPolicy=Always + digest 미사용 WARN."""

    def test_warn_always_no_digest(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app:v1.2.3")
        doc["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] = "Always"
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "IMG-W02" in [r.rule_id for r in report.results if r.level == "WARN"]

    def test_no_warn_always_with_digest(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(
            image="myregistry.io/app:v1.2.3@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
        )
        doc["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] = "Always"
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "IMG-W02" not in [r.rule_id for r in report.results if r.level == "WARN"]

    def test_no_warn_not_always(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(image="myregistry.io/app:v1.2.3")
        doc["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] = "IfNotPresent"
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "IMG-W02" not in [r.rule_id for r in report.results if r.level == "WARN"]


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
        svc = _minimal_service()
        mf = _write_file(tmp_path, dep, svc)
        report = _validator().validate([mf])
        rule_ids = {r.rule_id for r in report.results}
        assert any(rid.startswith("SEC-") for rid in rule_ids)
        assert any(rid.startswith("SVC-") for rid in rule_ids)

    def test_directory_walks_yaml_files(self, tmp_path: Path) -> None:
        sub = tmp_path / "k8s"
        sub.mkdir()
        dep = _minimal_deployment()
        (sub / "deployment.yaml").write_text(_manifest_yaml(dep))
        svc = _minimal_service()
        (sub / "service.yaml").write_text(_manifest_yaml(svc))
        report = _validator().validate([sub])
        rule_ids = {r.rule_id for r in report.results}
        assert any(rid.startswith("SEC-") for rid in rule_ids)
        assert any(rid.startswith("SVC-") for rid in rule_ids)

    def test_empty_yaml_document_skipped(self, tmp_path: Path) -> None:
        mf = tmp_path / "empty.yaml"
        mf.write_text("---\n---\n")
        report = _validator().validate([mf])
        assert isinstance(report, ValidationReport)


# ─── Exit code ───────────────────────────────────────────────────────────────


class TestExitCode:
    def test_exit_code_0_all_pass(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        netpol = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "myapp-netpol"},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        }
        mf = _write_file(tmp_path, dep, netpol)
        report = _validator().validate([mf])
        assert report.exit_code == 0

    def test_exit_code_1_any_fail(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert report.exit_code == 1

    def test_exit_code_2_warn_only(self, tmp_path: Path) -> None:
        # IMG-W01 WARN만 발생하도록: 완전히 올바른 manifest + digest 없음
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        mf = _write_file(tmp_path, dep)
        report = _validator().validate([mf])
        assert report.exit_code == 2

    def test_compute_exit_code_logic(self) -> None:
        assert _compute_exit_code({"pass": 5, "warn": 0, "fail": 0}) == 0
        assert _compute_exit_code({"pass": 3, "warn": 2, "fail": 1}) == 1
        assert _compute_exit_code({"pass": 3, "warn": 2, "fail": 0}) == 2
        assert _compute_exit_code({"pass": 0, "warn": 0, "fail": 0}) == 0


# ─── JSON 출력 ───────────────────────────────────────────────────────────────


class TestJSONOutput:
    def test_json_output_contains_all_top_level_fields(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        mf = _write_file(tmp_path, dep)
        v = K8sValidator(skipped=["kubectl_dry_run"])
        report = v.validate([mf])
        data = json.loads(v.to_json(report, skipped=["kubectl_dry_run"]))
        assert "results" in data
        assert "counts" in data
        assert "exit_code" in data
        assert "skipped" in data

    def test_skipped_field_passed_through(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        mf = _write_file(tmp_path, dep)
        v = K8sValidator(skipped=["kubectl_dry_run", "container_build"])
        report = v.validate([mf])
        data = json.loads(v.to_json(report, skipped=["kubectl_dry_run", "container_build"]))
        assert "kubectl_dry_run" in data["skipped"]
        assert "container_build" in data["skipped"]

    def test_json_results_have_required_keys(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(run_as_non_root=False)
        mf = _write_file(tmp_path, dep)
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

    def test_skipped_in_report_object(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        mf = _write_file(tmp_path, dep)
        v = K8sValidator(skipped=["kubectl_dry_run"])
        report = v.validate([mf])
        assert "kubectl_dry_run" in report.skipped

    def test_counts_accurate(self, tmp_path: Path) -> None:
        dep = _minimal_deployment(run_as_non_root=False)
        mf = _write_file(tmp_path, dep)
        report = _validator().validate([mf])
        assert report.counts["fail"] >= 1


# ─── CheckResult 메시지 품질 (F-46) ─────────────────────────────────────────


class TestMessageQuality:
    def test_fail_result_has_korean_and_english_messages(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        fails = [r for r in report.results if r.rule_id == "SEC-001" and r.level == "FAIL"]
        assert len(fails) >= 1
        cr = fails[0]
        assert cr.message_ko, "message_ko 비어있음"
        assert cr.message_en, "message_en 비어있음"
        assert cr.suggestion, "suggestion 비어있음"

    def test_rule_id_format(self, tmp_path: Path) -> None:
        doc = _minimal_deployment(run_as_non_root=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        for r in report.results:
            parts = r.rule_id.split("-")
            assert len(parts) >= 2, f"잘못된 rule_id 형식: {r.rule_id}"

    def test_f46_message_format_structure(self, tmp_path: Path) -> None:
        """F-46: FAIL result는 message_ko와 suggestion이 각각 분리되어 있어야 함."""
        doc = _minimal_deployment(run_as_non_root=False)
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        sec001_fails = [
            r for r in report.results if r.rule_id == "SEC-001" and r.level == "FAIL"
        ]
        assert sec001_fails
        cr = sec001_fails[0]
        # message_ko는 설명만 (제안 없음)
        assert cr.message_ko
        # suggestion은 수정 제안만
        assert cr.suggestion
        # 두 필드가 분리되어 있음
        assert cr.message_ko != cr.suggestion


# ─── CLI 통합 (argparse + main) ───────────────────────────────────────────────


class TestCLI:
    def test_cli_exit_0_on_clean_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        netpol = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "myapp-netpol"},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        }
        mf = _write_file(tmp_path, dep, netpol)
        from scripts.validate_k8s import main
        monkeypatch.setattr(sys, "argv", ["validate_k8s.py", str(mf)])
        code = main()
        assert code == 0

    def test_cli_exit_1_on_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        dep = _minimal_deployment(run_as_non_root=False)
        mf = _write_file(tmp_path, dep)
        from scripts.validate_k8s import main
        monkeypatch.setattr(sys, "argv", ["validate_k8s.py", str(mf)])
        code = main()
        assert code == 1

    def test_cli_json_flag_outputs_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import sys

        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        mf = _write_file(tmp_path, dep)
        from scripts.validate_k8s import main
        monkeypatch.setattr(sys, "argv", ["validate_k8s.py", "--json", str(mf)])
        main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "results" in data

    def test_cli_skipped_flag_passed_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CSV 형식으로 --skipped 전달."""
        import sys

        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        mf = _write_file(tmp_path, dep)
        from scripts.validate_k8s import main
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "validate_k8s.py",
                "--json",
                "--skipped",
                "kubectl_dry_run,container_build",
                str(mf),
            ],
        )
        main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "kubectl_dry_run" in data["skipped"]
        assert "container_build" in data["skipped"]

    def test_cli_skipped_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--skipped "" (빈 문자열) → skipped 목록이 비어있어야 함."""
        import sys

        dep = _minimal_deployment(
            image="myregistry.io/app:v1.0.0@sha256:abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
            resources={
                "requests": {"cpu": "200m", "memory": "128Mi"},
                "limits": {"cpu": "500m", "memory": "512Mi"},
            },
        )
        mf = _write_file(tmp_path, dep)
        from scripts.validate_k8s import main
        monkeypatch.setattr(
            sys,
            "argv",
            ["validate_k8s.py", "--json", "--skipped", "", str(mf)],
        )
        main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["skipped"] == []


# ─── Important 2: int() 캐스팅 예외 방어 ────────────────────────────────────


class TestIntCastDefense:
    """SEC-007/SEC-008: 비정수 runAsUser/fsGroup 입력 → FAIL 반환."""

    def test_rule_sec007_string_runasuser_returns_fail(self, tmp_path: Path) -> None:
        """runAsUser에 문자열 → FAIL (ValueError 전파 금지)."""
        doc = _minimal_deployment(run_as_user=None)
        # container securityContext에 문자열 값 삽입
        doc["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsUser"] = "abc"
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-007" in [r.rule_id for r in report.results if r.level == "FAIL"]
        fail_results = [r for r in report.results if r.rule_id == "SEC-007" and r.level == "FAIL"]
        assert any("정수가 아님" in r.message_ko for r in fail_results)

    def test_rule_sec008_list_fsgroup_returns_fail(self, tmp_path: Path) -> None:
        """fsGroup에 리스트 → FAIL (TypeError 전파 금지)."""
        doc = _minimal_deployment(fs_group=None)
        doc["spec"]["template"]["spec"]["securityContext"]["fsGroup"] = [1, 2, 3]
        mf = _write_file(tmp_path, doc)
        report = _validator().validate([mf])
        assert "SEC-008" in [r.rule_id for r in report.results if r.level == "FAIL"]
        fail_results = [r for r in report.results if r.rule_id == "SEC-008" and r.level == "FAIL"]
        assert any("정수가 아님" in r.message_ko for r in fail_results)

    def test_rule_svc002_string_targetport_handled(self, tmp_path: Path) -> None:
        """targetPort에 int 대신 문자열 숫자 → 이름 매칭으로 처리 (TypeError 없음)."""
        dep = _minimal_deployment(
            container_ports=[{"name": "http", "containerPort": 8080}]
        )
        svc = _minimal_service(target_port="http")
        mf = _write_file(tmp_path, dep, svc)
        # 예외 없이 동작해야 함
        report = _validator().validate([mf])
        assert isinstance(report, ValidationReport)


# ─── Important 3: None-chain 방어 (_as_dict 헬퍼) ──────────────────────────


class TestNoneChainDefense:
    """spec: null 또는 중간 값 null → AttributeError 없이 정상 처리."""

    def test_spec_null_manifest_no_attribute_error(self, tmp_path: Path) -> None:
        """spec: null인 Deployment → PARSE-ERR 없이 규칙 결과 반환."""
        yaml_content = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: null-spec
spec: null
"""
        mf = tmp_path / "null_spec.yaml"
        mf.write_text(yaml_content)
        report = _validator().validate([mf])
        # PARSE-ERR가 아니라 규칙 결과가 있어야 함 (pod_spec이 {}로 처리됨)
        assert report.exit_code in (0, 1, 2)
        assert not any(r.rule_id == "PARSE-ERR" for r in report.results)

    def test_spec_template_spec_null_manifest(self, tmp_path: Path) -> None:
        """spec.template.spec: null인 Deployment → AttributeError 없이 처리."""
        yaml_content = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: null-template-spec
spec:
  template:
    spec: null
"""
        mf = tmp_path / "null_template_spec.yaml"
        mf.write_text(yaml_content)
        report = _validator().validate([mf])
        assert report.exit_code in (0, 1, 2)
        assert not any(r.rule_id == "PARSE-ERR" for r in report.results)


# ─── Important 4: exception 구체화 + Important 5: path.name만 노출 ─────────


class TestExceptionNarrowing:
    """_safe_collect_file exception narrowing + 경로 노출 방어."""

    def test_permission_error_raises_malformed_with_filename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PermissionError → MalformedManifestError (파일명만 포함, 절대경로 없음)."""
        mf = tmp_path / "manifest.yaml"
        mf.write_text("kind: Deployment\n")

        def raise_permission_error(path: Path, **kwargs: object) -> str:
            raise PermissionError(f"Permission denied: {path}")

        monkeypatch.setattr(
            "scripts.validators.core.read_text_limited", raise_permission_error
        )
        report = _validator().validate([mf])
        assert any(r.rule_id == "PARSE-ERR" for r in report.results)
        fail = next(r for r in report.results if r.rule_id == "PARSE-ERR")
        # 파일명(manifest.yaml)은 포함, 절대 경로는 포함되면 안 됨
        assert "manifest.yaml" in fail.message_ko
        assert str(tmp_path) not in fail.message_ko

    def test_unicode_decode_error_raises_malformed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """UnicodeDecodeError → MalformedManifestError."""
        mf = tmp_path / "bad_encoding.yaml"
        mf.write_bytes(b"\xff\xfe invalid utf-8")

        report = _validator().validate([mf])
        assert any(r.rule_id == "PARSE-ERR" for r in report.results)

    def test_yaml_bomb_17_anchors_parse_err(self, tmp_path: Path) -> None:
        """17개 anchor/alias 포함 manifest → PARSE-ERR FAIL."""
        # 17개 anchor 포함 YAML 생성
        anchors = "\n".join([f"key{i}: &anchor{i} value{i}" for i in range(17)])
        yaml_content = f"kind: Deployment\nmetadata:\n  name: bomb\n{anchors}\n"
        mf = tmp_path / "bomb.yaml"
        mf.write_text(yaml_content)
        report = _validator().validate([mf])
        assert any(r.rule_id == "PARSE-ERR" for r in report.results)
