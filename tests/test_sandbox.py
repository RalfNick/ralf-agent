"""Plain bounded native execution evidence, independent of Docker or any Engine."""

import importlib.util
from dataclasses import FrozenInstanceError, replace

import pytest

import ralf_agent as r
from ralf_agent.errors import RalfError

NATIVE = "a" * 64


def api(name):
    value = getattr(r, name, None)
    assert value is not None, "Missing public Sandbox contract: " + name
    return value


def observation(**values):
    return api("SandboxObservation")(
        **{
            "invocation_id": "call-1",
            "native_id": NATIVE,
            "state": "stopped",
            "exit_code": 0,
            **values,
        }
    )


def result(**values):
    return api("SandboxResult")(
        **{
            "invocation_id": "call-1",
            "native_id": NATIVE,
            "exit_code": 0,
            "stdout": "中文🙂",
            "stderr": "",
            "truncated": False,
            "timed_out": False,
            "observation": observation(),
            **values,
        }
    )


def test_frozen_plain_roundtrip_and_public_provider_port():
    request = api("SandboxRequest")(["/usr/bin/python3", "-c", "print('hello')"])
    assert request.argv == ("/usr/bin/python3", "-c", "print('hello')") and request.timeout == 30
    assert api("SandboxRequest").from_dict(request.to_dict()) == request
    value = result()
    assert api("SandboxResult").from_dict(value.to_dict()) == value
    assert api("SandboxObservation").from_dict(value.observation.to_dict()) == value.observation
    with pytest.raises(FrozenInstanceError):
        request.timeout = 2
    provider = api("SandboxProvider")
    assert all(
        callable(getattr(provider, name, None)) for name in ("run", "observe", "stop", "aclose")
    )
    assert api("SandboxError").code == "sandbox_error"
    assert api("SandboxUnavailable").code == "sandbox_unavailable"
    assert api("SandboxIsolationViolation").code == "sandbox_isolation_violation"


@pytest.mark.parametrize(
    "argv",
    [
        [],
        "/bin/echo",
        ["echo"],
        [True],
        ["/bin/echo", None],
        ["/bin/echo", "\x00"],
        ["/bin/echo", "\ud800"],
        ["/bin/echo"] * 65,
        ["/bin/echo", "x" * 65536],
        ["/bin/echo", "🙂" * 16384],
    ],
)
def test_request_argv_refuses_malformed_unbounded_or_relative_values(argv):
    with pytest.raises(RalfError):
        api("SandboxRequest")(argv)


@pytest.mark.parametrize("timeout", [True, None, "30", 0, -1, 301, float("nan"), float("inf")])
def test_request_timeout_requires_finite_ordinary_allowance(timeout):
    with pytest.raises(RalfError):
        api("SandboxRequest")(["/bin/echo"], timeout=timeout)


@pytest.mark.parametrize(
    "values",
    [
        {"invocation_id": ""},
        {"invocation_id": "x" * 129},
        {"invocation_id": "中文"},
        {"native_id": "A" * 64},
        {"native_id": "a" * 63},
        {"native_id": None},
        {"state": "success"},
        {"state": "running", "exit_code": 0},
        {"state": "created", "exit_code": 0},
        {"exit_code": True},
        {"exit_code": None},
    ],
)
def test_observation_has_exact_native_state_and_stop_evidence(values):
    with pytest.raises(RalfError):
        observation(**values)


def test_native_created_not_found_and_unknown_are_distinct_from_stop():
    for state, native in (
        ("created", NATIVE),
        ("running", NATIVE),
        ("not_found", None),
        ("unknown", None),
    ):
        value = observation(state=state, native_id=native, exit_code=None)
        assert value.state == state
        with pytest.raises(RalfError):
            result(observation=value)


@pytest.mark.parametrize(
    "values",
    [
        {"invocation_id": "other"},
        {"native_id": "b" * 64},
        {"exit_code": 1},
        {"truncated": 1},
        {"timed_out": 0},
        {"stdout": None},
        {"stderr": "\ud800"},
        {"stdout": "x" * (16777216 + 1)},
    ],
)
def test_completed_result_requires_matching_plain_bounded_stopped_evidence(values):
    with pytest.raises(RalfError):
        result(**values)


def test_result_boundary_rechecks_raw_fields_without_copy_hooks():
    validate = api("validate_sandbox_result")
    value = result()
    copied = []

    class Forged(str):
        def __deepcopy__(self, memo):
            copied.append(True)
            return "中文🙂"

    object.__setattr__(value, "stdout", Forged("forged"))
    with pytest.raises(RalfError):
        validate(value, "call-1", max_output_bytes=100)
    assert copied == []


def test_result_boundary_enforces_configured_bytes_invocation_and_exact_dto():
    validate = api("validate_sandbox_result")
    value = result()
    assert validate(value, "call-1", max_output_bytes=10) == value
    for item, identity, limit in (
        (value, "other", 100),
        (value, "call-1", 9),
        (value.to_dict(), "call-1", 100),
    ):
        with pytest.raises(RalfError):
            validate(item, identity, max_output_bytes=limit)
    mutated = replace(value)
    object.__setattr__(mutated.observation, "exit_code", 1)
    with pytest.raises(RalfError):
        validate(mutated, "call-1", max_output_bytes=100)


@pytest.mark.parametrize(
    "name,payload",
    [
        ("SandboxRequest", {"argv": ["/bin/echo"], "host_path": "/private"}),
        (
            "SandboxObservation",
            {"invocation_id": "call-1", "state": "not_found", "native_id": None, "extra": True},
        ),
        ("SandboxResult", {}),
    ],
)
def test_wire_decoders_reject_unknown_or_missing_fields(name, payload):
    with pytest.raises(RalfError):
        api(name).from_dict(payload)


def test_contract_import_does_not_require_optional_container_sdk():
    api("SandboxRequest")(["/bin/echo"])
    assert importlib.util.find_spec("ralf_agent.sandbox") is not None


@pytest.mark.parametrize("target", ["result", "observation"])
def test_completed_boundary_never_calls_instance_revalidation_hook(target):
    value = result()
    called = []

    def bypass():
        called.append(True)

    if target == "result":
        object.__setattr__(value, "truncated", 1)
        object.__setattr__(value, "__post_init__", bypass)
    else:
        object.__setattr__(value.observation, "exit_code", True)
        object.__setattr__(value.observation, "__post_init__", bypass)
    with pytest.raises(RalfError):
        api("validate_sandbox_result")(value, "call-1", max_output_bytes=100)
    assert called == []
