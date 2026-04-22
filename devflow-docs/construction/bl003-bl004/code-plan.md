# Code Generation Plan: bl003-bl004

> **For agentic workers:** REQUIRED: Use `aidlc:aidlc-code-generation` with the
> "GENERATE" signal to execute this plan. Do NOT implement ad-hoc.
> `"code-generation: GENERATE — proceed with the approved plan for bl003-bl004"`

## Files to Create

- [x] `tests/test_cluster_config.py` — ClusterConfig 타입 + ConfigLoader.resolve_cluster_config() 테스트
- [x] `tests/test_statefulset_generator.py` — ManifestGenerator.generate_statefulset() 테스트
- [x] `tests/test_networkpolicy_generator.py` — ManifestGenerator.generate_networkpolicy() 테스트
- [x] `tests/test_validators_sts.py` — STS-W01 규칙 테스트
- [x] `tests/test_validators_net.py` — NET-W01 규칙 테스트
- [x] `scripts/validators/rules/sts.py` — STS-W01 규칙 구현
- [x] `scripts/validators/rules/net.py` — NET-W01 규칙 구현
- [x] `.devflow-k8s-deploy.yml.sample` (worktree) — cluster: 섹션 추가
- Note: statefulset.tmpl / networkpolicy.tmpl — Python dict+yaml.dump 방식으로 대체 (템플릿 불필요)

## Files to Modify

- [x] `scripts/_shared/types.py` — ClusterConfig frozen dataclass 추가
- [x] `scripts/config_loader.py` — resolve_cluster_config() 메서드 + BUILTIN_CLUSTER_PRESETS 추가
- [x] `scripts/manifest_generator.py` — generate_statefulset(), generate_networkpolicy(), _validate_k8s_quantity() 추가
- [x] `scripts/validators/registry.py` — "statefulset", "manifest_set" scope 추가
- [x] `scripts/validators/core.py` — StatefulSet→STS scope 디스패치, manifest_set 후처리 추가
- [x] `scripts/validators/rules/__init__.py` — sts, net 모듈 import 추가
- [x] `scripts/pipeline/orchestrator.py` — ClusterConfig 통합, StatefulSet/NetworkPolicy 분기 추가
- [x] `tests/test_validate_k8s.py` — NET-W01 영향 2개 테스트 NetworkPolicy 추가

## Implementation Steps

- [x] Step 1: ClusterConfig 타입 정의
  - [x] RED: `test_cluster_config_fields` — ClusterConfig 필드(preset, storage_class, network_policy) 검증
  - [x] RED: `test_cluster_config_frozen` — frozen dataclass 불변성 확인
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `scripts/_shared/types.py`에 ClusterConfig 추가
  - [x] Verify GREEN: 통과 확인 + 전체 회귀 (655 → 663 tests)

- [x] Step 2: ConfigLoader.resolve_cluster_config()
  - [x] RED: `test_resolve_cluster_config_orbstack` — orbstack preset → storageClassName=local-path, network_policy=True
  - [x] RED: `test_resolve_cluster_config_field_override` — preset 기본값을 config override 값이 덮어씀
  - [x] RED: `test_resolve_cluster_config_missing_preset_no_prompt` — prompt_callback=None, preset 미설정 → orbstack fallback
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `config_loader.py`에 `resolve_cluster_config()` + BUILTIN_CLUSTER_PRESETS 추가
  - [x] Verify GREEN: 통과 확인 + 전체 회귀 (663 tests)

- [x] Step 3: generate_statefulset()
  - [x] RED: 5개 테스트 작성
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `manifest_generator.py`에 `generate_statefulset()` + `_validate_k8s_quantity()` 추가
  - [x] Verify GREEN: 통과 확인 + 전체 회귀 (669 tests)

- [x] Step 4: generate_networkpolicy()
  - [x] RED: 5개 테스트 작성
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `manifest_generator.py`에 `generate_networkpolicy()` 추가
  - [x] Verify GREEN: 통과 확인 + 전체 회귀 (674 tests)

- [x] Step 5: STS-W01 validator 규칙
  - [x] RED: 3개 테스트 작성
  - [x] Verify RED: 실패 확인 (STS-W01 미존재)
  - [x] GREEN: `validators/rules/sts.py` + registry/core/rules/__init__ 업데이트
  - [x] Verify GREEN: 통과 확인

- [x] Step 6: NET-W01 validator 규칙
  - [x] RED: 3개 테스트 작성
  - [x] GREEN: `validators/rules/net.py` 생성 (Step 5에서 미리 생성됨)
  - [x] Verify GREEN: 통과 확인 + 전체 회귀 (기존 2개 테스트 수정 포함 → 684 tests)

- [x] Step 7: SkillPipeline orchestrator 통합
  - [x] RED: 4개 테스트 작성
  - [x] Verify RED: 실패 확인
  - [x] GREEN: `orchestrator.py`에 ClusterConfig 통합, StatefulSet/NetworkPolicy 분기 추가
  - [x] Verify GREEN: 통과 확인 + 전체 회귀 (684 tests)

- [x] Step 8: 샘플 config 업데이트 (non-TDD)
  - [x] `.devflow-k8s-deploy.yml.sample`에 `cluster:` 섹션 추가

## Test Strategy

- [x] `test_cluster_config_fields`: ClusterConfig 필드 기본값 및 타입 검증
- [x] `test_cluster_config_frozen`: frozen dataclass — 수정 시 FrozenInstanceError
- [x] `test_resolve_cluster_config_orbstack`: orbstack preset 기본값 확인
- [x] `test_resolve_cluster_config_field_override`: config override 우선순위
- [x] `test_resolve_cluster_config_missing_preset_no_prompt`: 자동모드 fallback
- [x] `test_generate_statefulset_basic_yaml`: StatefulSet YAML 구조 (kind, apiVersion)
- [x] `test_generate_statefulset_volume_claim_templates`: volumeClaimTemplates 포함 여부
- [x] `test_generate_statefulset_orbstack_storage_class`: storageClassName=local-path
- [x] `test_generate_statefulset_storage_size_invalid`: K8s quantity 형식 오류
- [x] `test_generate_statefulset_injection_defense`: YAML injection 방어
- [x] `test_generate_networkpolicy_deny_all`: deny-all 기본 정책 + CoreDNS 예외
- [x] `test_generate_networkpolicy_coredns_always_present`: CoreDNS 예외 항상 유지
- [x] `test_generate_networkpolicy_allow_ingress`: 허용 ingress 규칙 추가
- [x] `test_generate_networkpolicy_allow_egress`: 허용 egress 규칙 추가
- [x] `test_generate_networkpolicy_none_when_disabled`: network_policy=False → None
- [x] `test_sts_w01_no_vct`: STS-W01 WARN
- [x] `test_sts_w01_with_vct`: STS-W01 PASS (no WARN)
- [x] `test_sts_w01_deployment_not_triggered`: Deployment 미적용
- [x] `test_net_w01_no_networkpolicy`: NET-W01 WARN
- [x] `test_net_w01_with_networkpolicy`: NET-W01 PASS
- [x] `test_net_w01_empty_manifest_set`: 빈 집합 → WARN
- [x] `test_orchestrator_stateful_high_generates_statefulset`: HIGH → StatefulSet
- [x] `test_orchestrator_stateful_low_generates_deployment`: LOW → Deployment
- [x] `test_orchestrator_network_policy_true_generates_networkpolicy`: NPol 생성
- [x] `test_orchestrator_network_policy_false_skips_networkpolicy`: NPol 스킵

## Verification Contract

### 완료 조건
- [x] 기존 655개 테스트 전체 통과 (리그레션 없음) → 684개 (신규 29개 + 회귀 수정 2개)
- [x] 신규 테스트 29개 통과 (Steps 1-7 RED→GREEN 완료)
- [x] StatefulSet YAML — kind: StatefulSet, volumeClaimTemplates 포함
- [x] NetworkPolicy YAML — ingress/egress deny-all + CoreDNS egress(kube-system:53 UDP+TCP) 포함
- [x] orbstack preset: storageClassName=local-path, network_policy=True
- [x] network_policy=False 시 networkpolicy.yaml 미생성 + NET-W01 WARN 발생
- [x] YAML injection 방어 — storage_class 필드 개행 차단

### 검증 명령
- `uv run pytest tests/test_cluster_config.py tests/test_statefulset_generator.py tests/test_networkpolicy_generator.py tests/test_validators_sts.py tests/test_validators_net.py tests/test_orchestrator.py -v` — 신규 테스트 전체
- `uv run pytest --tb=short -q` — 전체 회귀 (684 passed)
- `uv tool run ruff check scripts/ tests/` — 린트 클린

### 리스크 태그
- 없음 (auth/security 변경 없음, DB schema 변경 없음)

## Key Design Decisions (구현 참조)

- `ClusterConfig`: `preset: str`, `storage_class: str | None` (None=클러스터기본값), `network_policy: bool`
- `BUILTIN_CLUSTER_PRESETS`: `{"orbstack": {"storage_class": "local-path", "network_policy": True}}`
- `registry.py` 신규 scope: `"statefulset"` (StatefulSet 문서 전달), `"manifest_set"` (전체 문서 리스트를 `docs=` kwarg로 전달)
- `generate_networkpolicy()` 반환: `str | None` — network_policy=False 시 None
- `_validate_k8s_quantity()`: `^[0-9]+([KMGTPE]i|[KMGTPE])?$` 패턴 (storage_size 검증)
- CoreDNS egress: `namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}`, port 53 UDP+TCP
- StatefulSet/NetworkPolicy: Python dict + yaml.dump 방식 (Jinja2 템플릿 미사용 — 조건부 YAML 구조 처리 용이)
