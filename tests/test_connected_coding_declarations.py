"""SDK/JSON/TOML connected declarations assemble actual owned resources lazily."""

import asyncio
import json
import secrets

import pytest

from ralf_agent import BindingSelection, Scope, TemporalProfile, TemporalProfileCatalog
from ralf_agent.codex_connected_runner import ConnectedCodexCodingRunner
from ralf_agent.codex_credentials import EnvironmentCodingCredentials
from ralf_agent.errors import CoordinatorBusy, ValidationError
from ralf_agent.runner_journal import RunnerJournal
from ralf_agent.runtime_builder import RuntimeBuilder
from ralf_agent.runtime_config import RuntimeProfile, load_catalog
from ralf_agent.temporal_journal import PostgresEffectJournal
from tests.test_connected_coding_factories import entry
from tests.test_temporal_coding_factories import Connection, publish_initialization


async def forbidden_resolution(self, connection):
    pytest.fail("Connected declaration resolved a credential during assembly or close")


def declarations(tmp_path, value, *, temporal, multiple):
    adapter = "codex-coding-connected-postgres" if temporal else "codex-coding-connected"
    component_config = {"tools": [value]} if multiple else value
    components = {"tools": {"adapter": adapter, "config": component_config}}
    bindings = [
        {
            "role": "runner",
            "component_id": "native",
            "version": "1",
            "component": {"adapter": "registered-tool", "config": {"name": "coding"}},
        }
    ]
    if temporal:
        components["effect_journal"] = {
            "adapter": "postgres",
            "config": {"dsn_env": "DECLARATION_DSN", "backend_id": "effects", "initialize": True},
        }
        sdk = TemporalProfile(
            "connected",
            "1",
            {"default": {"adapter": "offline-echo"}},
            components=components,
            execution={"coding_execution": True},
            binding_components=bindings,
        )
        catalog = TemporalProfileCatalog(base_dir=tmp_path)
        catalog.register(sdk, default=True)
        document = catalog.to_dict()
    else:
        sdk = RuntimeProfile(
            "connected",
            "1",
            {"default": {"adapter": "offline-echo"}},
            components,
            binding_components=bindings,
        )
        document = {
            "schema_version": 2,
            "default": {"name": "connected", "version": "1"},
            "profiles": [
                {
                    "name": "connected",
                    "version": "1",
                    "providers": sdk.providers,
                    "components": sdk.components,
                    "binding_components": sdk.binding_components,
                }
            ],
        }
    json_path, toml_path = tmp_path / "connected.json", tmp_path / "connected.toml"
    json_path.write_text(json.dumps(document))
    header = (
        'kind = "temporal-profiles"\nschema_version = 1\n' if temporal else "schema_version = 2\n"
    )
    text = (
        header
        + """[default]
name = "connected"
version = "1"
[[profiles]]
name = "connected"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
"""
    )
    if temporal:
        text += """[profiles.execution]
coding_execution = true
[profiles.components.effect_journal]
adapter = "postgres"
[profiles.components.effect_journal.config]
dsn_env = "DECLARATION_DSN"
backend_id = "effects"
initialize = true
"""
    text += f'[profiles.components.tools]\nadapter = "{adapter}"\n'
    prefix = "profiles.components.tools.config" + (".tools" if multiple else "")
    text += f"[[{prefix}]]\n" if multiple else f"[{prefix}]\n"
    text += (
        "\n".join(
            f"{name} = {json.dumps(item)}"
            for name, item in value.items()
            if name not in {"fixed_dependencies", "connection"}
        )
        + "\n"
    )
    text += f'[{prefix}.fixed_dependencies]\nfixture = "assembly-v1"\n'
    text += f"[{prefix}.connection]\n"
    text += "\n".join(f"{name} = {json.dumps(item)}" for name, item in value["connection"].items())
    text += """
[[profiles.binding_components]]
role = "runner"
component_id = "native"
version = "1"
[profiles.binding_components.component]
adapter = "registered-tool"
[profiles.binding_components.component.config]
name = "coding"
"""
    toml_path.write_text(text)

    def load(path):
        if temporal:
            return TemporalProfileCatalog.from_file(path).default_profile
        return load_catalog(path).default

    return sdk, load(json_path), load(toml_path)


def assert_nonsecret_connection(runner, key):
    assert type(runner) is ConnectedCodexCodingRunner
    assert runner.identity["connection"] == {
        "kind": "codex-model-connection",
        "version": "1",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "credential_env": "CODING_TEST_KEY",
        "credential_id": "coding-primary",
        "generation": "1",
        "reasoning_effort": "low",
    }
    assert runner.identity["credentials"] == "ephemeral-api-key"
    assert key not in repr(runner.identity)


def assert_no_native_or_secret(tmp_path, key):
    assert not (tmp_path / "native").exists()
    assert list((tmp_path / "runner").iterdir()) == []
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert key.encode() not in path.read_bytes(), path.name


@pytest.mark.parametrize("multiple", [False, True], ids=["single", "tool-list"])
def test_local_sdk_json_toml_assemble_same_lazy_identity_and_close_owned_journal(
    tmp_path, monkeypatch, multiple
):
    key = "synthetic-declaration-" + secrets.token_hex(24)
    monkeypatch.setenv("CODING_TEST_KEY", key)
    monkeypatch.setattr(EnvironmentCodingCredentials, "resolve", forbidden_resolution)
    value = entry(tmp_path)
    profiles = declarations(tmp_path, value, temporal=False, multiple=multiple)
    assert all(selected.identity == profiles[0].identity for selected in profiles)

    async def scenario():
        identities = []
        for selected in profiles:
            runtime = await RuntimeBuilder().abuild(selected, tmp_path / "runs.sqlite")
            try:
                runner = runtime.tools.get("coding").handler.runner
                borrowed, _ = runtime.binding_catalog.resolve(
                    "runner", BindingSelection.ref("native", "1"), Scope()
                )
                assert borrowed is runner
                assert_nonsecret_connection(runner, key)
                identities.append(runner.identity)
                with pytest.raises(CoordinatorBusy):
                    RunnerJournal(value["journal_path"], identity=value["fixed_dependencies"])
                assert_no_native_or_secret(tmp_path, key)
            finally:
                await runtime.aclose()
            assert runner._closing is True
            with pytest.raises(ValidationError):
                _ = runtime.tools
            reopened = RunnerJournal(value["journal_path"], identity=value["fixed_dependencies"])
            reopened.close()
            await runtime.aclose()
        assert identities[0] == identities[1] == identities[2]

    asyncio.run(scenario())


@pytest.mark.parametrize("multiple", [False, True], ids=["single", "tool-list"])
def test_postgres_sdk_json_toml_borrow_same_effect_owner_and_close_owned_resources(
    tmp_path, monkeypatch, multiple
):
    from ralf_agent import TemporalRuntimeBuilder

    key = "synthetic-declaration-" + secrets.token_hex(24)
    monkeypatch.setenv("CODING_TEST_KEY", key)
    monkeypatch.setattr(EnvironmentCodingCredentials, "resolve", forbidden_resolution)
    events = []
    publish_initialization(monkeypatch, events)

    async def connect(dsn, *, backend_id):
        assert dsn == "synthetic-local-dsn" and backend_id == "effects"
        return PostgresEffectJournal(
            Connection(events), backend_id=backend_id, owns_connection=True
        )

    async def initialize(self):
        events.append("initialize-effect-owner")

    monkeypatch.setattr(PostgresEffectJournal, "connect", connect)
    monkeypatch.setattr(PostgresEffectJournal, "initialize", initialize)
    monkeypatch.setenv("DECLARATION_DSN", "synthetic-local-dsn")
    value = entry(tmp_path)
    value.pop("journal_path")
    profiles = declarations(tmp_path, value, temporal=True, multiple=multiple)
    assert all(selected.identity == profiles[0].identity for selected in profiles)

    async def scenario():
        identities = []
        for selected in profiles:
            assembly = await TemporalRuntimeBuilder(base_dir=tmp_path).abuild(selected)
            try:
                runtime = assembly._runtime
                runner = runtime.tools.get("coding").handler.runner
                borrowed, _ = runtime.binding_catalog.resolve(
                    "runner", BindingSelection.ref("native", "1"), Scope()
                )
                assert borrowed is runner
                assert runner._journal._effect is runtime.journal
                assert runner._journal._effect._lock is runtime.journal._lock
                assert_nonsecret_connection(runner, key)
                identities.append(runner.identity)
                assert_no_native_or_secret(tmp_path, key)
                closed_before = events.count("connection")
            finally:
                await assembly.aclose()
            assert runner._closing is True
            assert events.count("connection") == closed_before + 1
            await assembly.aclose()
            assert events.count("connection") == closed_before + 1
        assert identities[0] == identities[1] == identities[2]
        assert events.count("initialize-effect-owner") == 3
        assert events.count("initialize-view") == 3

    asyncio.run(scenario())
