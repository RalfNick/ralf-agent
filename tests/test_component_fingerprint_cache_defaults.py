"""Default snapshots may reuse code, without concealing executable/configuration drift."""

import cProfile

import pytest

from ralf_agent import component_fingerprint as module
from ralf_agent.errors import ValidationError
from ralf_agent.types import digest


def uncached(method):
    return digest({"algorithm": "python-code-v1", "function": module._function(method, set())})


def code_walks(method):
    profile = cProfile.Profile()
    profile.enable()
    actual = module.executable_digest(method)
    profile.disable()
    calls = sum(row.callcount for row in profile.getstats() if row.code is module._code.__code__)
    return actual, calls


@pytest.mark.parametrize(
    "defaults,keyword_defaults",
    [
        (("text", 3, True, None), None),
        (None, {"options": "甲", "deadline": 1.5, "enabled": False}),
        ((), {}),
    ],
)
def test_unchanged_simple_defaults_reuse_code_with_exact_legacy_digest(defaults, keyword_defaults):
    def configured(value=None, *, options=None):
        return value, options

    configured.__defaults__, configured.__kwdefaults__ = defaults, keyword_defaults
    expected = uncached(configured)
    assert module.executable_digest(configured) == expected
    actual, walks = code_walks(configured)
    assert actual == expected
    assert walks == 0, "Unchanged primitive default snapshots should avoid walking immutable code"


@pytest.mark.parametrize(
    "defaults,keyword_defaults",
    [
        (([],), {"options": ()}),
        (({2: "two", 10: "ten"},), {"options": {"nested": {2: False, 10: True}}}),
        (None, {"options": {"unicode": "甲", "values": [False, 1.5]}}),
    ],
)
def test_complex_json_defaults_preserve_exact_legacy_fallback(defaults, keyword_defaults):
    def configured(value=None, *, options=None):
        return value, options

    configured.__defaults__, configured.__kwdefaults__ = defaults, keyword_defaults
    expected = uncached(configured)
    assert module.executable_digest(configured) == expected
    actual, walks = code_walks(configured)
    assert actual == expected
    assert walks > 0, "Complex defaults retain the original uncached serializer"


def test_mutating_nested_defaults_changes_cached_fingerprint_immediately():
    def configured(value=None, *, options=None):
        return value, options

    configured.__defaults__ = ({"values": []},)
    configured.__kwdefaults__ = {"options": {"enabled": False}}
    first = module.executable_digest(configured)
    configured.__defaults__[0]["values"].append({"new": 1})
    second = module.executable_digest(configured)
    assert second == uncached(configured) != first
    configured.__kwdefaults__["options"]["enabled"] = True
    assert module.executable_digest(configured) == uncached(configured) != second


def test_replacing_code_defaults_and_keyword_defaults_invalidates_cache():
    def configured(value=1, *, options=None):
        return value, options

    def different(value=1, *, options=None):
        return options, value

    first = module.executable_digest(configured)
    configured.__code__ = different.__code__
    second = module.executable_digest(configured)
    assert second == uncached(configured) != first
    configured.__defaults__ = (2,)
    third = module.executable_digest(configured)
    assert third == uncached(configured) != second
    configured.__kwdefaults__ = {"options": "changed"}
    assert module.executable_digest(configured) == uncached(configured) != third


@pytest.mark.parametrize("value", [object(), float("nan"), float("inf"), {"not": {1, 2}}])
def test_invalid_defaults_are_rejected_even_after_valid_cache_fill(value):
    def configured(value=None):
        return value

    module.executable_digest(configured)
    configured.__defaults__ = (value,)
    with pytest.raises(ValidationError):
        module.executable_digest(configured)


def test_cyclic_defaults_are_rejected_after_valid_cache_fill():
    def configured(value=None):
        return value

    module.executable_digest(configured)
    values = []
    values.append(values)
    configured.__defaults__ = (values,)
    with pytest.raises(ValidationError):
        module.executable_digest(configured)


def test_closure_defaults_keep_dynamic_capture_validation():
    values = []

    def configured(value=1):
        return values, value

    first = module.executable_digest(configured)
    values.append("changed")
    actual, walks = code_walks(configured)
    assert actual == uncached(configured) != first
    assert walks > 0


def test_wrapped_function_added_after_cache_fill_is_revalidated():
    def configured(value=1):
        return value

    def alternate(value=1):
        return value + 1

    first = module.executable_digest(configured)
    configured.__wrapped__ = alternate
    actual, walks = code_walks(configured)
    assert actual == uncached(configured) != first
    assert walks > 0
    alternate.__defaults__ = (2,)
    assert module.executable_digest(configured) == uncached(configured) != actual


@pytest.mark.parametrize("helper", ["_code", "_function", "canonical", "digest"])
def test_replaced_fingerprint_helpers_cannot_reuse_old_default_digest(monkeypatch, helper):
    def configured(value=1):
        return value

    first = module.executable_digest(configured)
    original = getattr(module, helper)
    if helper in {"_code", "_function"}:

        def changed(*args, **kwargs):
            return {**original(*args, **kwargs), "marker": "changed"}
    elif helper == "canonical":

        def changed(value):
            return original(value) + " "
    else:

        def changed(value):
            return "changed-" + original(value)

    monkeypatch.setattr(module, helper, changed)
    # canonical is a module alias, whereas the original digest owns its own serializer.
    expected = (
        first
        if helper == "canonical"
        else "changed-" + uncached(configured)
        if helper == "digest"
        else uncached(configured)
    )
    assert module.executable_digest(configured) == expected
    if helper != "canonical":
        assert expected != first


def test_callable_objects_with_defaults_preserve_original_fallback():
    class Callable:
        def __call__(self, value=1):
            return value

    assert module.executable_digest(Callable()) == uncached(Callable())


@pytest.mark.parametrize("helper", ["_defaults_digest", "_cached_defaults_digest"])
def test_replaced_defaults_cache_helpers_cannot_return_foreign_digest(monkeypatch, helper):
    def configured(value=1):
        return value

    expected = uncached(configured)
    assert module.executable_digest(configured) == expected
    monkeypatch.setattr(module, helper, lambda *args: "foreign")
    assert module.executable_digest(configured) == expected


def test_defaults_cache_evicts_old_snapshots_and_keeps_original_digest():
    def configured(value=1):
        return value

    module._cached_defaults_digest.cache_clear()
    limit = module._cached_defaults_digest.cache_info().maxsize
    for value in range(limit + 1):
        configured.__defaults__ = (value,)
        assert module.executable_digest(configured) == uncached(configured)
    configured.__defaults__ = (0,)
    actual, walks = code_walks(configured)
    assert actual == uncached(configured)
    assert walks > 0  # The oldest snapshot was evicted rather than retained without a bound.
    assert code_walks(configured) == (actual, 0)


def test_primitive_keyword_default_mutation_invalidates_cache_immediately():
    def configured(*, options=1):
        return options

    first = module.executable_digest(configured)
    configured.__kwdefaults__["options"] = 2
    assert module.executable_digest(configured) == uncached(configured) != first


@pytest.mark.parametrize("change", ["code", "keyword_default", "default_decoder"])
def test_changed_json_decoder_cannot_reuse_or_poison_default_snapshots(monkeypatch, change):
    import json

    module._cached_defaults_digest.cache_clear()

    def configured(value=1):
        return value

    first = module.executable_digest(configured)
    with monkeypatch.context() as patch:
        if change == "code":

            def foreign(*args, **kwargs):
                return None

            patch.setattr(json.loads, "__code__", foreign.__code__)
        elif change == "keyword_default":
            patch.setitem(json.loads.__kwdefaults__, "parse_int", lambda value: 999)
        else:

            class ForeignDecoder:
                def decode(self, value):
                    return None

            patch.setattr(json, "_default_decoder", ForeignDecoder())
        assert module.executable_digest(configured) == first
        configured.__defaults__ = (2,)
        assert module.executable_digest(configured) == uncached(configured)
    assert module.executable_digest(configured) == uncached(configured)
    configured.__defaults__ = (1,)
    assert module.executable_digest(configured) == first


@pytest.mark.parametrize("container", ["positional", "keyword"])
def test_default_container_subclasses_keep_original_serializer_path(container):
    class TupleDefaults(tuple):
        pass

    class KeywordDefaults(dict):
        pass

    def configured(value=1, *, options=2):
        return value, options

    if container == "positional":
        configured.__defaults__ = TupleDefaults((1,))
    else:
        configured.__kwdefaults__ = KeywordDefaults(options=2)
    assert module.executable_digest(configured) == uncached(configured)
    assert code_walks(configured)[1] > 0


@pytest.mark.parametrize("left,right", [(True, 1), (1, 1.0), (0.0, -0.0)])
@pytest.mark.parametrize("container", ["positional", "keyword"])
def test_json_distinct_equal_primitives_cannot_share_a_cached_digest(left, right, container):
    def configured(value=None, *, options=None):
        return value, options

    if container == "positional":
        configured.__defaults__ = (left,)
    else:
        configured.__kwdefaults__ = {"options": left}
    first = module.executable_digest(configured)
    assert first == uncached(configured)
    if container == "positional":
        configured.__defaults__ = (right,)
    else:
        configured.__kwdefaults__ = {"options": right}
    assert module.executable_digest(configured) == uncached(configured) != first


def test_large_default_snapshots_preserve_digest_without_retaining_cache_entries():
    def configured(value=None, *, options=None):
        return value, options

    module._cached_defaults_digest.cache_clear()
    configured.__defaults__ = ("x" * 20_000,)
    configured.__kwdefaults__ = {"options": "y" * 20_000}
    actual, walks = code_walks(configured)
    assert actual == uncached(configured)
    assert walks > 0
    assert module._cached_defaults_digest.cache_info().currsize == 0
