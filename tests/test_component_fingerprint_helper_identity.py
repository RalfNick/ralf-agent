"""Existing product metadata guards must not execute foreign equality callbacks."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ralf_agent import component_fingerprint as fp

PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from ralf_agent import component_fingerprint as fp
role, drift, kind = sys.argv[2:]
def target(value):
    return 42
if kind == 'defaults':
    target.__defaults__ = (1,)
expected = fp.executable_digest(target)
cache = fp._cached_defaults_digest if kind == 'defaults' else fp._cached_plain_digest
cache.cache_clear()
helper = getattr(fp, role)
calls = []
class Name(str):
    def __eq__(self, other):
        calls.append('code equality')
        fp._plain_digest.__code__ = (lambda *args: 'foreign').__code__
        return str.__eq__(self, other)
    __hash__ = str.__hash__
class Zero(int):
    def __eq__(self, other):
        calls.append('default equality')
        fp._plain_digest.__code__ = (lambda *args: 'foreign').__code__
        return int.__eq__(self, other)
    __hash__ = int.__hash__
class Wrapped:
    def __eq__(self, other):
        calls.append('wrapper equality')
        fp._plain_digest.__code__ = (lambda *args: 'foreign').__code__
        return True
if drift == 'code':
    helper.__code__ = helper.__code__.replace(co_name=Name(helper.__code__.co_name))
elif drift == 'defaults':
    helper.__defaults__ = (Zero(0),)
else:
    helper.__wrapped__ = Wrapped()
actual = fp.executable_digest(target)
print(json.dumps({'actual':actual,'expected':expected,'callbacks':calls,'cache':cache.cache_info()._asdict()}))
"""


@pytest.mark.parametrize("kind", ["plain", "defaults"])
@pytest.mark.parametrize(
    "role,drift",
    [
        ("_cache_helpers", "code"),
        ("_cacheable_constant", "code"),
        ("_plain_digest", "code"),
        ("_defaults_digest", "code"),
        ("_cacheable_constant", "defaults"),
        ("_cached_plain_digest", "wrapped"),
        ("_cached_defaults_digest", "wrapped"),
    ],
)
def test_metadata_guard_rejects_callback_without_cache_admission(kind, role, drift):
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            PROBE,
            str(Path(fp.__file__).resolve().parent.parent),
            role,
            drift,
            kind,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    assert value["actual"] == value["expected"], value
    assert value["callbacks"] == [], value
    assert value["cache"]["currsize"] == value["cache"]["hits"] == value["cache"]["misses"] == 0
