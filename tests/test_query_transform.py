import pytest

from relf_agent.errors import ValidationError


def test_identity_preserves_input_and_aliases_expand_without_chaining():
    from relf_agent import AliasQueryTransform, IdentityQueryTransform

    assert IdentityQueryTransform().transform("  car  ") == ("  car  ",)
    aliases = {"car": "automobile", "automobile": "vehicle"}
    transform = AliasQueryTransform(aliases)
    aliases["car"] = "changed"
    assert transform.transform(" car   safety ") == ("car safety", "automobile safety")
    transform.identity["aliases"].clear()
    assert transform.transform("car") == ("car", "automobile")
    assert AliasQueryTransform({"car": "auto"}, include_original=False).transform("car") == (
        "auto",
    )
    assert AliasQueryTransform({}).transform("unchanged") == ("unchanged",)


@pytest.mark.parametrize("value", [None, True, "", "   ", "\ud800", "x" * 4097])
def test_invalid_query_fails_before_transform(value):
    from relf_agent import IdentityQueryTransform

    with pytest.raises(ValidationError):
        IdentityQueryTransform().transform(value)


@pytest.mark.parametrize(
    "aliases,options",
    [
        ([], {}),
        ({"": "word"}, {}),
        ({"car": None}, {}),
        ({"car": "\ud800"}, {}),
        ({"x" * 257: "v"}, {}),
        ({"car": "v" * 1025}, {}),
        ({str(i): "v" for i in range(129)}, {}),
        ({}, {"include_original": 1}),
    ],
)
def test_invalid_alias_configuration_is_explicit(aliases, options):
    from relf_agent import AliasQueryTransform

    with pytest.raises(ValidationError):
        AliasQueryTransform(aliases, **options)
