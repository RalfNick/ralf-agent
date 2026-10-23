"""Pure immutable code classification reuse; no authority/configuration memoization."""

import gc
import sys
import weakref
from concurrent.futures import ThreadPoolExecutor

import pytest

from relf_agent import component_fingerprint as fp
from relf_agent.errors import ValidationError
from relf_agent.types import digest


def original(function):
    return digest({"algorithm": "python-code-v1", "function": fp._function(function, set())})


def test_warm_code_purity_does_not_repeat_the_tree_walk():
    def target():
        return 42

    fp._cached_plain_digest.cache_clear()
    if hasattr(fp, "_CODE_PURITY"):
        fp._CODE_PURITY[0] = {}
    expected = fp.executable_digest(target)
    calls = []
    predicate_code = fp._cacheable_constant.__code__

    def observe(frame, event, arg):
        if event == "call" and frame.f_code is predicate_code:
            calls.append(True)

    before = fp._cached_plain_digest.cache_info()
    sys.setprofile(observe)
    try:
        actual = fp.executable_digest(target)
    finally:
        sys.setprofile(None)
    assert actual == expected == original(target)
    assert calls == []
    assert fp._cached_plain_digest.cache_info().hits == before.hits + 1


def test_rejected_code_is_not_hashed_or_added_after_a_warm_pure_code():
    def target():
        return 42

    fp.executable_digest(target)
    calls = []

    class Opaque:
        def __hash__(self):
            calls.append("hash")
            return 1

    target.__code__ = target.__code__.replace(co_consts=(None, Opaque()))
    before = fp._cached_plain_digest.cache_info()
    with pytest.raises(ValidationError):
        fp.executable_digest(target)
    assert calls == [] and fp._cached_plain_digest.cache_info() == before
    assert id(target.__code__) not in fp._CODE_PURITY[0]


def test_eligibility_retains_identity_and_is_bounded():
    fp._CODE_PURITY[0] = {}
    code = compile("def unique():\n return 773\n", "<pure-code-proof>", "exec").co_consts[0]
    assert fp._cacheable_code(code)
    reference = weakref.ref(code)
    del code
    gc.collect()
    assert reference() is not None
    template = (lambda: 42).__code__
    for index in range(fp._CODE_PURITY_MAX + 1):
        assert fp._cacheable_code(template.replace(co_firstlineno=index + 1))
        assert len(fp._CODE_PURITY[0]) <= fp._CODE_PURITY_MAX
    gc.collect()
    assert reference() is None


def test_concurrent_snapshot_publication_preserves_the_bound_and_results():
    fp._CODE_PURITY[0] = {}
    template = (lambda: 42).__code__

    def check(index):
        code = template.replace(co_firstlineno=index + 1)
        assert fp._cacheable_code(code)
        assert len(fp._CODE_PURITY[0]) <= fp._CODE_PURITY_MAX
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(check, range(fp._CODE_PURITY_MAX * 2)))


def test_corrupt_snapshot_subclass_cannot_execute_its_lookup():
    def target():
        return 42

    expected = original(target)
    calls = []

    class Foreign(dict):
        def get(self, *args):
            calls.append("lookup")
            raise AssertionError("foreign mapping invoked")

    previous = fp._CODE_PURITY[0]
    fp._CODE_PURITY[0] = Foreign()
    try:
        before = fp._cached_plain_digest.cache_info()
        assert fp.executable_digest(target) == expected
        assert fp._cached_plain_digest.cache_info() == before
        assert calls == []
    finally:
        fp._CODE_PURITY[0] = previous


def test_wrong_identity_entry_does_not_approve_opaque_code():
    def target():
        return 42

    changed = target.__code__.replace(co_consts=(None, object()))
    previous = fp._CODE_PURITY[0]
    fp._CODE_PURITY[0] = {id(changed): target.__code__}
    try:
        assert not fp._cacheable_code(changed)
    finally:
        fp._CODE_PURITY[0] = previous


@pytest.mark.parametrize("role", ["_cacheable_code", "_cacheable_constant"])
def test_predicate_code_drift_cannot_reuse_prior_eligibility(monkeypatch, role):
    def target():
        return 42

    fp.executable_digest(target)
    helper = getattr(fp, role)
    monkeypatch.setattr(helper, "__code__", (lambda *args: True).__code__)
    target.__code__ = target.__code__.replace(co_consts=(None, object()))
    before = fp._cached_plain_digest.cache_info()
    with pytest.raises(ValidationError):
        fp.executable_digest(target)
    assert fp._cached_plain_digest.cache_info() == before
