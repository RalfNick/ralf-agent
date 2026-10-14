"""The default credential source is lazy, finite and never embeds key material."""

import asyncio
import importlib.util

import pytest

from ralf_agent.errors import ValidationError


def source_type():
    assert importlib.util.find_spec("ralf_agent.codex_credentials") is not None, (
        "lazy Coding credential source is missing"
    )
    from ralf_agent.codex_credentials import EnvironmentCodingCredentials

    return EnvironmentCodingCredentials


def test_default_source_resolves_only_explicit_requested_environment(monkeypatch):
    cls = source_type()
    monkeypatch.setenv("CODING_TEST_KEY", "synthetic-canary")
    source = cls()
    assert "synthetic-canary" not in str(source.identity)
    assert asyncio.run(source.resolve({"credential_env": "CODING_TEST_KEY"})) == "synthetic-canary"


@pytest.mark.parametrize(
    "value",
    [None, "", " leading", "line\nfeed", "nonascii-\u2603", "x" * 8193],
    ids=["missing", "empty", "space", "newline", "unicode", "oversized"],
)
def test_invalid_credential_has_fixed_error_without_value_or_environment_dump(monkeypatch, value):
    cls = source_type()
    if value is None:
        monkeypatch.delenv("CODING_TEST_KEY", raising=False)
    else:
        monkeypatch.setenv("CODING_TEST_KEY", value)
    with pytest.raises(ValidationError, match="Coding credential is unavailable") as caught:
        asyncio.run(cls().resolve({"credential_env": "CODING_TEST_KEY"}))
    assert str(caught.value) == "Coding credential is unavailable"
