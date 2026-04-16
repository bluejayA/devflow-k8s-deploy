#!/usr/bin/env python3
"""
K8s manifest 정책 검증기
SKILL.md의 필수 규칙을 결정론적으로 검사.
LLM이 생성한 manifest를 dry-run 전에 반드시 통과해야 한다.
"""

import sys
import yaml
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    passed: list = field(default_factory=list)
    failed: list = field(default_factory=list)

    @property
    def ok(self):
        return len(self.failed) == 0


def check_no_latest_tag(doc, result):
    containers = []
    containers += doc.get("spec",{}).get("template",{}).get("spec",{}).get("containers",[])
    containers += doc.get("spec",{}).get("template",{}).get("spec",{}).get("initContainers",[])
    for c in containers:
        image = c.get("image","")
        name = c.get("name","unknown")
        if image.endswith(":latest") or (":" not in image):
            result.failed.append(
                f"[FAIL] '{name}': latest 태그 사용 금지 (현재: '{image}')\n"
                f"       → myregistry.io/{name}:v1.0.0 형식으로 수정"
            )
        else:
            result.passed.append(f"[PASS] '{name}': 이미지 태그 명시됨 ({image})")


def check_run_as_non_root(doc, result):
    pod_spec = doc.get("spec",{}).get("template",{}).get("spec",{})
    pod_non_root = pod_spec.get("securityContext",{}).get("runAsNonRoot", False)
    for c in pod_spec.get("containers",[]):
        name = c.get("name","unknown")
        ctr_non_root = c.get("securityContext",{}).get("runAsNonRoot", False)
        if not pod_non_root and not ctr_non_root:
            result.failed.append(
                f"[FAIL] '{name}': runAsNonRoot 미설정\n"
                f"       → spec.securityContext.runAsNonRoot: true 추가 필요\n"
                f"       → 미설정 시 컨테이너 탈출 공격 시 호스트 root 권한 획득 가능"
            )
        else:
            result.passed.append(f"[PASS] '{name}': runAsNonRoot 설정됨")


def check_no_privileged(doc, result):
    pod_spec = doc.get("spec",{}).get("template",{}).get("spec",{})
    for c in pod_spec.get("containers",[]):
        name = c.get("name","unknown")
        if c.get("securityContext",{}).get("privileged", False) is True:
            result.failed.append(
                f"[FAIL] '{name}': privileged: true 설정됨\n"
                f"       → 즉시 제거. 호스트 커널에 무제한 접근 허용하는 위험 설정"
            )
        else:
            result.passed.append(f"[PASS] '{name}': privileged 모드 비활성화")


def check_no_privilege_escalation(doc, result):
    pod_spec = doc.get("spec",{}).get("template",{}).get("spec",{})
    for c in pod_spec.get("containers",[]):
        name = c.get("name","unknown")
        sc = c.get("securityContext",{})
        if "allowPrivilegeEscalation" not in sc:
            result.failed.append(
                f"[FAIL] '{name}': allowPrivilegeEscalation 미설정\n"
                f"       → securityContext.allowPrivilegeEscalation: false 추가 필요"
            )
        elif sc["allowPrivilegeEscalation"] is True:
            result.failed.append(
                f"[FAIL] '{name}': allowPrivilegeEscalation: true\n"
                f"       → false로 변경. setuid 바이너리를 통한 권한 상승 가능"
            )
        else:
            result.passed.append(f"[PASS] '{name}': 권한 상승 차단됨")


def check_resources(doc, result):
    pod_spec = doc.get("spec",{}).get("template",{}).get("spec",{})
    for c in pod_spec.get("containers",[]):
        name = c.get("name","unknown")
        resources = c.get("resources",{})
        requests = resources.get("requests",{})
        limits = resources.get("limits",{})
        missing = []
        if "cpu" not in requests:    missing.append("requests.cpu")
        if "memory" not in requests: missing.append("requests.memory")
        if "cpu" not in limits:      missing.append("limits.cpu")
        if "memory" not in limits:   missing.append("limits.memory")
        if missing:
            result.failed.append(
                f"[FAIL] '{name}': 리소스 스펙 미설정 → {', '.join(missing)}\n"
                f"       → 미설정 시 노드 자원 고갈(OOM) 또는 CPU throttling 예측 불가"
            )
        else:
            result.passed.append(
                f"[PASS] '{name}': 리소스 스펙 완비\n"
                f"       cpu {requests['cpu']}/{limits['cpu']}, "
                f"memory {requests['memory']}/{limits['memory']}"
            )


def validate_file(filepath):
    result = CheckResult()
    path = Path(filepath)
    if not path.exists():
        result.failed.append(f"[FAIL] 파일 없음: {filepath}")
        return result

    with open(path) as f:
        docs = list(yaml.safe_load_all(f))

    for doc in docs:
        if doc is None:
            continue
        kind = doc.get("kind","")
        name = doc.get("metadata",{}).get("name","unknown")
        if kind != "Deployment":
            result.passed.append(f"[SKIP] {kind}/{name}")
            continue
        print(f"\n검증 대상: {kind}/{name}")
        check_no_latest_tag(doc, result)
        check_run_as_non_root(doc, result)
        check_no_privileged(doc, result)
        check_no_privilege_escalation(doc, result)
        check_resources(doc, result)
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_k8s.py <manifest.yaml>")
        sys.exit(1)

    total = CheckResult()
    for fp in sys.argv[1:]:
        r = validate_file(fp)
        total.passed.extend(r.passed)
        total.failed.extend(r.failed)

    print("\n" + "="*50)
    print("검증 결과")
    print("="*50)
    for m in total.passed:
        print(m)
    if total.failed:
        print("\n--- 실패 항목 ---")
        for m in total.failed:
            print(m)
        print(f"\n결과: FAIL ({len(total.failed)}개 항목 수정 필요)")
        sys.exit(1)
    else:
        print(f"\n결과: PASS ({len(total.passed)}개 항목 모두 통과)")
        sys.exit(0)


if __name__ == "__main__":
    main()
