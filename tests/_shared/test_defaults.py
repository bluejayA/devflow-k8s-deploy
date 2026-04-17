"""defaults.py 단위 테스트 — BUILTIN_DEFAULTS 필수 키 + 타입 확인."""



def test_builtin_defaults_has_stack_key() -> None:
    """BUILTIN_DEFAULTS: 'stack' 키가 'auto' 문자열이어야 함."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS

    assert "stack" in BUILTIN_DEFAULTS
    assert BUILTIN_DEFAULTS["stack"] == "auto"
    assert isinstance(BUILTIN_DEFAULTS["stack"], str)


def test_builtin_defaults_namespace_is_none() -> None:
    """BUILTIN_DEFAULTS: 'namespace'는 None (default 자동 배정 금지)."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS

    assert "namespace" in BUILTIN_DEFAULTS
    assert BUILTIN_DEFAULTS["namespace"] is None


def test_builtin_defaults_output_dir() -> None:
    """BUILTIN_DEFAULTS: 'output.dir'은 'k8s-output' 문자열."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS

    assert "output" in BUILTIN_DEFAULTS
    assert isinstance(BUILTIN_DEFAULTS["output"], dict)
    assert BUILTIN_DEFAULTS["output"]["dir"] == "k8s-output"


def test_builtin_defaults_output_on_exists() -> None:
    """BUILTIN_DEFAULTS: 'output.on_exists'는 'prompt'."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS

    assert BUILTIN_DEFAULTS["output"]["on_exists"] == "prompt"


def test_builtin_defaults_build_engine() -> None:
    """BUILTIN_DEFAULTS: 'build.engine'은 'skip'."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS

    assert "build" in BUILTIN_DEFAULTS
    assert isinstance(BUILTIN_DEFAULTS["build"], dict)
    assert BUILTIN_DEFAULTS["build"]["engine"] == "skip"


def test_builtin_defaults_build_timeout() -> None:
    """BUILTIN_DEFAULTS: 'build.timeout_sec'는 정수 300."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS

    assert BUILTIN_DEFAULTS["build"]["timeout_sec"] == 300
    assert isinstance(BUILTIN_DEFAULTS["build"]["timeout_sec"], int)


def test_builtin_defaults_kubectl_dry_run_true() -> None:
    """BUILTIN_DEFAULTS: 'kubectl.dry_run'은 True (안전 기본값)."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS

    assert "kubectl" in BUILTIN_DEFAULTS
    assert isinstance(BUILTIN_DEFAULTS["kubectl"], dict)
    assert BUILTIN_DEFAULTS["kubectl"]["dry_run"] is True


def test_load_builtin_defaults_returns_dict() -> None:
    """load_builtin_defaults(): dict 반환 + BUILTIN_DEFAULTS와 동일 내용."""
    from scripts._shared.defaults import BUILTIN_DEFAULTS, load_builtin_defaults

    result = load_builtin_defaults()
    assert isinstance(result, dict)
    assert result["stack"] == BUILTIN_DEFAULTS["stack"]
    assert result["output"]["dir"] == BUILTIN_DEFAULTS["output"]["dir"]


def test_load_builtin_defaults_returns_copy() -> None:
    """load_builtin_defaults(): 매 호출 시 새 객체 반환 (원본 변경 방지)."""
    from scripts._shared.defaults import load_builtin_defaults

    d1 = load_builtin_defaults()
    d2 = load_builtin_defaults()
    # 반환된 dict는 독립된 객체여야 함
    d1["stack"] = "mutated"
    assert d2["stack"] != "mutated"
