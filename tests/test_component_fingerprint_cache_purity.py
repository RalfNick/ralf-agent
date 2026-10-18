"""Code-cache keys must never execute callbacks before digest acceptance."""

import types

import pytest

from ralf_agent import component_fingerprint as module
from ralf_agent.errors import ValidationError
from ralf_agent.types import digest


def original(method):
    return digest({"algorithm": "python-code-v1", "function": module._function(method, set())})


@pytest.mark.parametrize("defaults", [False, True])
@pytest.mark.parametrize("container", ["direct", "tuple", "frozenset", "code"])
def test_opaque_constant_cannot_forge_cached_identity(monkeypatch, defaults, container):
    def target(value):
        return "approved"

    def changed(value):
        return "changed"

    if defaults:
        target.__defaults__ = (1,)
    approved = module.executable_digest(target)
    helper = module._defaults_digest if defaults else module._plain_digest
    cache = module._cached_defaults_digest if defaults else module._cached_plain_digest
    saved_code = helper.__code__
    monkeypatch.setattr(module, "_purity_saved_helper", helper, raising=False)
    monkeypatch.setattr(module, "_purity_saved_code", saved_code, raising=False)
    namespace = {}
    signature = "code, defaults_snapshot, keyword_defaults_snapshot" if defaults else "code"
    exec(
        f"def forged({signature}):\n"
        " _purity_saved_helper.__code__ = _purity_saved_code\n"
        f" return {approved!r}",
        namespace,
    )
    calls = []
    armed = False

    class HashTrap:
        def __hash__(self):
            if armed:
                calls.append(True)
                helper.__code__ = namespace["forged"].__code__
            return 41

    value = HashTrap()
    if container == "tuple":
        value = (value,)
    elif container == "frozenset":
        value = frozenset([value])
    elif container == "code":
        value = changed.__code__.replace(co_consts=(*changed.__code__.co_consts, value))
    target.__code__ = changed.__code__.replace(co_consts=(*changed.__code__.co_consts, value))
    with pytest.raises(ValidationError, match="unsupported executable constants"):
        original(target)
    armed = True
    before = cache.cache_info()
    try:
        with pytest.raises(ValidationError):
            module.executable_digest(target)
        assert calls == []
        assert cache.cache_info() == before
    finally:
        helper.__code__ = saved_code
        cache.cache_clear()


@pytest.mark.parametrize("defaults", [False, True])
@pytest.mark.parametrize("field", ["co_name", "co_filename", "co_qualname"])
def test_metadata_subclass_falls_back_without_hash_callback(defaults, field):
    def target(value):
        return value

    if defaults:
        target.__defaults__ = (1,)
    calls = []

    class Name(str):
        def __hash__(self):
            calls.append(True)
            return super().__hash__()

    expected = original(target)
    target.__code__ = target.__code__.replace(**{field: Name(getattr(target.__code__, field))})
    cache = module._cached_defaults_digest if defaults else module._cached_plain_digest
    before = cache.cache_info()
    assert module.executable_digest(target) == expected == original(target)
    assert calls == []
    assert cache.cache_info() == before


def test_opaque_constant_class_hook_is_not_called():
    calls = []

    class Opaque:
        @property
        def __class__(self):
            calls.append(True)
            return types.CodeType

    with pytest.raises(ValidationError, match="unsupported executable constants"):
        module._constant(Opaque())
    assert calls == []


def test_purity_gate_does_not_compare_or_hash_opaque_types():
    calls = []

    class Meta(type):
        def __hash__(cls):
            calls.append("hash")
            raise AssertionError("opaque type hash called")

        def __eq__(cls, other):
            calls.append("eq")
            raise AssertionError("opaque type equality called")

    class Opaque(metaclass=Meta):
        pass

    def target():
        return 1

    code = target.__code__.replace(co_consts=(*target.__code__.co_consts, Opaque()))
    assert module._cacheable_constant(code) is False
    assert calls == []


@pytest.mark.parametrize("defaults", [False, True])
@pytest.mark.parametrize("drift", ["identity", "code", "defaults", "keywords", "wrapper"])
def test_purity_helper_drift_disables_cache(monkeypatch, defaults, drift):
    def target(value):
        return value

    if defaults:
        target.__defaults__ = (1,)
    expected = module.executable_digest(target)
    cache = module._cached_defaults_digest if defaults else module._cached_plain_digest
    before = cache.cache_info()
    helper = module._cacheable_constant
    if drift == "identity":
        monkeypatch.setattr(module, "_cacheable_constant", lambda value, depth=0: True)
    elif drift == "code":
        monkeypatch.setattr(helper, "__code__", (lambda value, depth=0: True).__code__)
    elif drift == "defaults":
        monkeypatch.setattr(helper, "__defaults__", (1,))
    elif drift == "keywords":
        monkeypatch.setattr(helper, "__kwdefaults__", {"unused": True})
    else:
        monkeypatch.setattr(helper, "__wrapped__", target, raising=False)
    assert module.executable_digest(target) == expected == original(target)
    assert cache.cache_info() == before


def test_bounded_purity_check_keeps_legacy_digest_for_deep_constants():
    def target():
        return 1

    value = "deep"
    for _ in range(70):
        value = (value,)
    target.__code__ = target.__code__.replace(co_consts=(*target.__code__.co_consts, value))
    before = module._cached_plain_digest.cache_info()
    assert module.executable_digest(target) == original(target)
    assert module._cached_plain_digest.cache_info() == before


@pytest.mark.parametrize("placement", ["positional", "keyword"])
def test_default_subclass_cannot_forge_cached_identity(monkeypatch, placement):
    def target(value):
        return "approved"

    def changed(value):
        return "changed"

    if placement == "positional":
        target.__defaults__ = ("value",)
    else:
        target.__kwdefaults__ = {"value": "value"}
    approved = module.executable_digest(target)
    helper = module._defaults_digest
    saved_code = helper.__code__
    monkeypatch.setattr(module, "_purity_saved_helper", helper, raising=False)
    monkeypatch.setattr(module, "_purity_saved_code", saved_code, raising=False)
    namespace = {}
    exec(
        "def forged(code, defaults_snapshot, keyword_defaults_snapshot):\n"
        " _purity_saved_helper.__code__ = _purity_saved_code\n"
        f" return {approved!r}",
        namespace,
    )
    calls = []

    class Meta(type):
        def __eq__(cls, other):
            calls.append("type_eq")
            return True

    class Default(str, metaclass=Meta):
        def __hash__(self):
            calls.append("hash")
            helper.__code__ = namespace["forged"].__code__
            return super().__hash__()

    target.__code__ = changed.__code__
    if placement == "positional":
        target.__defaults__ = (Default("value"),)
    else:
        target.__kwdefaults__ = {"value": Default("value")}
    expected = original(target)
    assert expected != approved
    before = module._cached_defaults_digest.cache_info()
    try:
        assert module.executable_digest(target) == expected
        assert calls == []
        assert module._cached_defaults_digest.cache_info() == before
    finally:
        helper.__code__ = saved_code
        module._cached_defaults_digest.cache_clear()
