# 제약 및 로드맵

## v0.4.0 제약

- JVM 스택만 (Kotlin + Java Spring Boot). Go/Python/React는 v0.5+ 로드맵
- auto-fix 루프 미지원 (v0.5+) — 검증 실패 시 troubleshoot.md 안내 후 수동 수정 지시
- PDB / topologySpreadConstraints 없음
- `buildah` / `kaniko` / `buildctl` 미지원 (v0.5+)
- cluster preset: `orbstack`만 내장. 커스텀은 `storage_class` / `network_policy` 직접 지정

## v0.5+ 로드맵

- Go / Python / React 스택 추가
- auto-fix 루프 (3회 자동 수정)
- PodDisruptionBudget / topologySpreadConstraints
- Helm chart 생성
- cluster preset 확장 (EKS, GKE, kind)
- 도움말 카탈로그 다국어 지원

## 버전 이력

| 버전 | 주요 변경 | Tests |
|------|----------|-------|
| v0.4.0 | StatefulSet/PVC + NetworkPolicy zero-trust + ClusterConfig preset | 688 |
| v0.3.0 | replicas 설정화 + LIFE-W01/IMG-W02 + validators 패키지 모듈화 | 655 |
| v0.2.0 | alpine Dockerfile 호환 + deployment 이미지 wiring + resource_hint tiering | 631 |
| v0.1.0 | JVM 스택 첫 릴리즈 | 613 |
