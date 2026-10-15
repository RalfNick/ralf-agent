"""One fresh selected3 publication retains final coupled validation, without a cache."""

import asyncio
import copy
import cProfile
import pstats

import pytest

from ralf_agent import DeploymentAdmissionPolicy, Scope, TemporalRuntime
from ralf_agent.errors import DefinitionMismatch, ValidationError
from ralf_agent.runtime_lifecycle import BuildContext
from ralf_agent.temporal_journal import PostgresEffectJournal
from ralf_agent.types import canonical
from tests.test_temporal_coding_factories import Connection, entry, publish_initialization
from tests.test_temporal_deployment_public_registry import Provider


@pytest.fixture(autouse=True, scope="module")
def optional_sdk():
    pytest.importorskip("temporalio")


async def construct(tmp_path, monkeypatch, *, composition=True, selected=True):
    from ralf_agent.temporal_coding_factories import build

    events = []
    publish_initialization(monkeypatch, events)
    context = BuildContext(None, tmp_path / "unused", Scope(), tmp_path, allow_async=True)
    effect = context.own_async(PostgresEffectJournal(Connection(events), owns_connection=True))
    context.coding_execution, context.effect_journal = True, effect
    tools = await build(entry(tmp_path), context)
    runtime = TemporalRuntime(
        providers={"default": Provider()},
        tools=tools,
        journal=effect,
        coding_execution=True,
        coding_composition=composition,
        **({"admission_policy": DeploymentAdmissionPolicy("publication-cost")} if selected else {}),
    )
    return runtime, context


def base_manifest(manifest):
    value = copy.deepcopy(manifest)
    for name in (
        "deployment_admission_protocol",
        "coding_execution_protocol",
        "coding_composition_protocol",
    ):
        value.pop(name, None)
    return value


def profile_call(function):
    profile = cProfile.Profile()
    result = profile.runcall(function)
    return result, profile


def count(profile, function):
    return sum(entry.callcount for entry in profile.getstats() if entry.code is function.__code__)


def publication_clones(profile):
    sources = {
        "temporal_coding_protocol.py",
        "temporal_coding_composition_protocol.py",
        "temporal_deployment_protocol.py",
    }
    return sum(
        details[0]
        for (filename, line, name), (_, _, _, _, callers) in pstats.Stats(profile).stats.items()
        if name in {"detached", "deepcopy"}
        for (caller_file, caller_line, caller_name), details in callers.items()
        if caller_name == "publish" and caller_file.rsplit("/", 1)[-1] in sources
    )


@pytest.mark.parametrize("composition", [False, True])
def test_selected3_fresh_pipeline_matches_strict_publication_with_one_final_validation(
    tmp_path, monkeypatch, composition
):
    from ralf_agent import temporal_coding_composition_protocol as tree
    from ralf_agent import temporal_coding_protocol as native
    from ralf_agent import temporal_deployment_protocol as deployment

    async def scenario():
        runtime, context = await construct(tmp_path, monkeypatch, composition=composition)
        try:
            base = base_manifest(runtime.manifest)

            def strict():
                result = native.publish(base, runtime)
                if composition:
                    result = tree.publish(result, runtime)
                return deployment.publish(
                    result, runtime._deployment_admission_identity, public=True
                )

            expected, strict_profile = profile_call(strict)
            actual, current_profile = profile_call(runtime._current_manifest)
            assert canonical(actual) == canonical(expected)
            # Two pre-existing base-component validate_manifest calls stay;
            # the final publisher adds the coupled selected3 validation.
            assert count(current_profile, deployment.validate_protocol) == 3
            assert count(current_profile, native.validate_protocol) == 1
            assert count(current_profile, tree.validate_protocol) == 3
            assert count(strict_profile, native.validate_protocol) == 2
            assert count(strict_profile, tree.validate_protocol) == (3 if composition else 2)
            assert publication_clones(strict_profile) == (3 if composition else 2)
            assert publication_clones(current_profile) == 0
            assert runtime.validate_release(actual) == runtime.manifest
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())


def test_legacy_runtime_keeps_strict_detached_publication(tmp_path, monkeypatch):
    from ralf_agent import temporal_coding_composition_protocol as tree
    from ralf_agent import temporal_coding_protocol as native

    async def scenario():
        runtime, context = await construct(tmp_path, monkeypatch, selected=False)
        try:
            current, profile = profile_call(runtime._current_manifest)
            assert "deployment_admission_protocol" not in current
            assert count(profile, native.validate_protocol) == 1
            assert count(profile, tree.validate_protocol) == 4
            assert publication_clones(profile) == 3
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())


@pytest.mark.parametrize("publisher", ["native", "composition", "deployment"])
def test_standalone_publish_remains_strict_and_detached(tmp_path, monkeypatch, publisher):
    from ralf_agent import temporal_coding_composition_protocol as tree
    from ralf_agent import temporal_coding_protocol as native
    from ralf_agent import temporal_deployment_protocol as deployment

    async def scenario():
        runtime, context = await construct(tmp_path, monkeypatch)
        try:
            base = base_manifest(runtime.manifest)
            base["probe"] = {"items": []}
            if publisher != "native":
                base = native.publish(base, runtime)
            if publisher == "deployment":
                base = tree.publish(base, runtime)

            def publish(value):
                if publisher == "native":
                    return native.publish(value, runtime)
                if publisher == "composition":
                    return tree.publish(value, runtime)
                return deployment.publish(
                    value, runtime._deployment_admission_identity, public=True
                )

            result = publish(base)
            assert result is not base
            result["probe"]["items"].append("separate")
            assert base["probe"]["items"] == []
            invalid = copy.deepcopy(base)
            if publisher == "native":
                name = next(iter(runtime.manifest["coding_execution_protocol"]["tools"]))
                invalid["tools"][name]["config"]["delegated_runner"]["runner"] = {
                    "foreign": "runner"
                }
            elif publisher == "composition":
                invalid.pop("coding_execution_protocol")
            else:
                invalid["coding_execution_protocol"]["version"] = 5
            with pytest.raises(DefinitionMismatch):
                publish(invalid)
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())


def test_final_selected3_validation_still_rejects_guard_code_drift(tmp_path, monkeypatch):
    from ralf_agent import temporal_deployment_coding_state as guards

    async def scenario():
        runtime, context = await construct(tmp_path, monkeypatch)
        original = guards.guard_mutation.__code__
        try:
            guards.guard_mutation.__code__ = original.replace(co_name="foreign-guard")
            with pytest.raises(DefinitionMismatch):
                runtime._current_manifest()
        finally:
            guards.guard_mutation.__code__ = original
            await context.cleanup_async()

    asyncio.run(scenario())


def test_final_deployment_publisher_has_no_validation_disable_option(tmp_path, monkeypatch):
    from ralf_agent import temporal_deployment_protocol as deployment

    async def scenario():
        runtime, context = await construct(tmp_path, monkeypatch)
        try:
            with pytest.raises(TypeError):
                deployment.publish(
                    runtime.manifest,
                    runtime._deployment_admission_identity,
                    public=True,
                    _validate=False,
                )
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())


@pytest.mark.parametrize("drift", ["provider", "policy"])
def test_selected3_live_configuration_still_refuses_before_republication(
    tmp_path, monkeypatch, drift
):
    async def scenario():
        runtime, context = await construct(tmp_path, monkeypatch)
        try:
            if drift == "provider":
                runtime.providers["default"] = Provider()
            else:
                runtime._deployment_admission_policy = DeploymentAdmissionPolicy("foreign")
            with pytest.raises(DefinitionMismatch):
                runtime.validate_release()
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())


@pytest.mark.parametrize("publisher", ["native", "composition"])
def test_owned_no_copy_still_rejects_non_json_before_registration(tmp_path, monkeypatch, publisher):
    from ralf_agent import temporal_coding_composition_protocol as tree
    from ralf_agent import temporal_coding_protocol as native

    async def scenario():
        runtime, context = await construct(tmp_path, monkeypatch)
        try:
            value = base_manifest(runtime.manifest)
            value["invalid"] = float("nan")
            function, registration = (
                (native.publish, native.registration)
                if publisher == "native"
                else (tree.publish, tree.implementation)
            )
            profile = cProfile.Profile()
            with pytest.raises(ValidationError):
                profile.runcall(function, value, runtime, _validate=False, _copy=False)
            assert count(profile, registration) == 0
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())


def test_final_validation_rejects_cross_inventory_mismatch_from_owned_intermediates(
    tmp_path, monkeypatch
):
    from ralf_agent import temporal_coding_composition_protocol as tree
    from ralf_agent import temporal_coding_protocol as native
    from ralf_agent import temporal_deployment_protocol as deployment

    async def scenario():
        runtime, context = await construct(tmp_path, monkeypatch)
        try:
            value = base_manifest(runtime.manifest)
            name = next(iter(runtime.manifest["coding_execution_protocol"]["tools"]))
            value["tools"][name]["config"]["delegated_runner"]["runner"] = {"foreign": "runner"}
            value = native.publish(value, runtime, _validate=False, _copy=False)
            value = tree.publish(value, runtime, _validate=False, _copy=False)
            with pytest.raises(DefinitionMismatch):
                deployment.publish(
                    value, runtime._deployment_admission_identity, public=True, _copy=False
                )
        finally:
            await context.cleanup_async()

    asyncio.run(scenario())
