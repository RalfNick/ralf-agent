import pytest

from ralf_agent import component_fingerprint as fp
from ralf_agent.types import digest


@pytest.mark.parametrize("defaults", [False, True])
def test_helper_dictionary_key_cannot_run_equality_and_forge_digest(monkeypatch, defaults):
    def target(value):
        return "approved"

    def changed(value):
        return "changed"

    if defaults:
        target.__defaults__ = (1,)
    approved = fp.executable_digest(target)
    target.__code__ = changed.__code__
    expected = digest({"algorithm": "python-code-v1", "function": fp._function(target, set())})
    helper = fp._defaults_digest if defaults else fp._plain_digest
    saved = helper.__code__
    calls = []
    monkeypatch.setattr(fp, "_dict_guard_saved_helper", helper, raising=False)
    monkeypatch.setattr(fp, "_dict_guard_saved_code", saved, raising=False)
    args = "code, ds, ks" if defaults else "code"
    ns = {}
    exec(
        f"def forged({args}):\n _dict_guard_saved_helper.__code__=_dict_guard_saved_code\n return {approved!r}",
        ns,
    )

    class Key(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            calls.append(True)
            helper.__code__ = ns["forged"].__code__
            return str.__eq__(self, other)

    previous = fp._cacheable_constant.__dict__
    fp._cacheable_constant.__dict__ = {Key("__wrapped__"): None}
    cache = fp._cached_defaults_digest if defaults else fp._cached_plain_digest
    before = cache.cache_info()
    try:
        assert fp.executable_digest(target) == expected
        assert calls == [] and cache.cache_info() == before
    finally:
        fp._cacheable_constant.__dict__ = previous
        helper.__code__ = saved
        cache.cache_clear()
