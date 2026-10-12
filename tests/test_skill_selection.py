"""Pure replaceable skill metadata selection, without catalog or body access."""

import pytest

import ralf_agent as r
from ralf_agent.errors import RalfError
from ralf_agent.skills import skill_metadata


def api():
    selector = getattr(r, "LexicalSkillSelector", None)
    assert selector is not None and getattr(r, "SkillSelector", None) is not None
    return selector


def entries():
    return [
        skill_metadata(r.SkillSpec("billing", "Invoice payment help", "secret invoice body")),
        skill_metadata(r.SkillSpec("deploy", "发布部署失败排查", "secret deployment body")),
        skill_metadata(
            r.SkillSpec("support", "Help diagnose customer issues", "secret support body")
        ),
    ]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("invoice", ["billing"]),
        ("部署失败", ["deploy"]),
        ("unmatched", []),
        ("", ["billing", "deploy"]),
    ],
)
def test_default_selector_returns_deterministic_names_only(query, expected):
    selector = api()(version="1")
    assert selector.select(query, entries(), limit=2) == expected
    assert "instructions" not in str(selector.identity)


@pytest.mark.parametrize("limit", [True, 0, -1, 101, "5", None])
def test_invalid_selection_limit_refuses(limit):
    selector = api()(version="1")
    with pytest.raises(RalfError):
        selector.select("", entries(), limit=limit)


@pytest.mark.parametrize("version", [None, True, "", " ", "x" * 257])
def test_invalid_selector_behavior_version_refuses(version):
    with pytest.raises(RalfError):
        api()(version=version)


def test_tie_order_ignores_input_order_and_does_not_mutate_metadata():
    selector = api()()
    values = entries()
    before = repr(values)
    assert selector.select("help", list(reversed(values)), limit=2) == ["billing", "support"]
    assert repr(values) == before


def test_invalid_unicode_query_has_public_validation_error():
    selector = api()()
    with pytest.raises(RalfError):
        selector.select("\ud800", entries(), limit=2)
