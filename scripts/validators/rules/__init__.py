"""규칙 모듈 일괄 임포트 — 데코레이터 등록 트리거.

임포트 순서가 registry 실행 순서를 결정한다:
  pod_spec: [SEC-006, SEC-008, SA-001, SA-002, LIFE-W01]
  container: [SEC-001~009, RES-001/W01, IMG-001/W01/W02, PRB-001/002]
  service:   [SVC-001, SVC-002]
"""

from scripts.validators.rules import img, life, prb, res, sa, sec, svc  # noqa: F401
