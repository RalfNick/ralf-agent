"""Static code reuse cannot hide executable or captured configuration drift."""

from functools import wraps

from ralf_agent import component_fingerprint as module
from ralf_agent.types import digest


def original(method):
    return digest({"algorithm": "python-code-v1", "function": module._function(method, set())})


def test_static_fingerprint_reuses_immutable_code_without_changing_digest():
    def plain(value):
        return value + 1

    module._cached_plain_digest.cache_clear()
    assert module.executable_digest(plain) == original(plain)
    before = module._cached_plain_digest.cache_info()
    assert module.executable_digest(plain) == original(plain)
    assert module._cached_plain_digest.cache_info().hits == before.hits + 1


def test_replaced_code_invalidates_static_fingerprint():
    def plain():
        return 1

    def different():
        return 2

    before = module.executable_digest(plain)
    plain.__code__ = different.__code__
    assert module.executable_digest(plain) == original(plain) != before


def test_mutable_defaults_are_always_recomputed():
    def configured(values):
        return values

    configured.__defaults__ = ([],)
    before = module.executable_digest(configured)
    configured.__defaults__[0].append("changed")
    assert module.executable_digest(configured) == original(configured) != before


def test_closure_and_wrapper_changes_are_always_recomputed():
    values = []

    def configured():
        return values

    before = module.executable_digest(configured)
    values.append("changed")
    assert module.executable_digest(configured) == original(configured) != before

    def first():
        return 1

    def second():
        return 2

    @wraps(first)
    def wrapped():
        return first()

    before = module.executable_digest(wrapped)
    wrapped.__wrapped__ = second
    assert module.executable_digest(wrapped) == original(wrapped) != before


def test_changed_serializer_cannot_use_previous_cached_digest(monkeypatch):
    def plain():
        return 1

    before = module.executable_digest(plain)
    previous = module._code

    def changed(code):
        return {**previous(code), "serializer_marker": "changed"}

    monkeypatch.setattr(module, "_code", changed)
    assert module.executable_digest(plain) == original(plain) != before


def test_replaced_cache_and_guard_cannot_supply_foreign_digest(monkeypatch):
    def plain():
        return 1

    expected = original(plain)
    assert module.executable_digest(plain) == expected
    monkeypatch.setattr(module, "_cached_plain_digest", lambda code: "foreign")
    assert module.executable_digest(plain) == expected
    monkeypatch.setattr(module, "_cache_helpers", lambda: module._CACHE_HELPERS)
    assert module.executable_digest(plain) == expected


def test_adding_defaults_or_wrapper_after_caching_is_observed():
    def plain(value):
        return value

    def different():
        return 2

    before = module.executable_digest(plain)
    plain.__defaults__ = ("changed",)
    assert module.executable_digest(plain) == original(plain) != before
    before = module.executable_digest(plain)
    plain.__wrapped__ = different
    assert module.executable_digest(plain) == original(plain) != before


def test_static_and_dynamic_runtime_inventory_digests_keep_original_algorithm():
    from importlib import import_module

    from ralf_agent.temporal_coding_composition_protocol import (
        _pure_sources,
        _resolve,
        _worker_sources,
    )

    for module_name, names in {**_pure_sources(), **_worker_sources()}.values():
        owner = import_module("ralf_agent." + module_name)
        for name in names:
            method = _resolve(owner, name)
            assert module.executable_digest(method) == original(method), (module_name, name)
