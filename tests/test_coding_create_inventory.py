"""Explicit supervision inventory pins code and types without replaying I/O."""

import ast
import builtins
import copy
import hashlib
import importlib
import os
import sys
from pathlib import Path

import pytest

from ralf_agent.errors import RalfError

PROCESS_FUNCTIONS = ("_default_child_policy", "_darwin_group_members", "signal_unreaped_group")
PROCESS_METHODS = ("__init__", "register", "_events", "exited", "close")
NO_CREATE_RULES = (
    "_create_not_dispatched_facts",
    "_create_not_dispatched_digests",
    "_create_digest",
    "validate_create_not_dispatched",
    "adopt_create_not_dispatched",
    "create_not_dispatched_projection",
    "validate_create_not_dispatched_projection",
)


def module():
    return importlib.import_module("ralf_agent.coding_create_inventory")


def changed(*args, **kwargs):
    return "changed reviewed implementation"


def test_explicit_inventory_is_complete_and_detached():
    inventory = module()
    value = inventory.inventory()
    fields = inventory.inventory_fields()
    assert fields["process_functions"] == PROCESS_FUNCTIONS
    assert fields["process_methods"] == PROCESS_METHODS
    assert fields["no_create_rules"] == NO_CREATE_RULES
    assert fields["process_policy"] == ("_GROUP_LIMIT", "_PGRP_ONLY")
    assert fields["inventory"] == (
        "inventory_fields",
        "validate_inventory",
        "_validate_aliases",
        "source_paths",
        "_source_digest",
        "source_inventory",
        "check_source_inventory",
        "inventory",
    )
    assert set(value) == set(fields)
    assert all(set(value[group]) == set(names) for group, names in fields.items())
    inventory.validate_inventory(value)
    value["process_methods"].clear()
    assert set(inventory.inventory()["process_methods"]) == set(PROCESS_METHODS)


@pytest.mark.parametrize("name", ["_cacheable_constant", "_cacheable_code"])
def test_code_cache_purity_gate_is_in_live_inventory(monkeypatch, name):
    from ralf_agent import component_fingerprint

    inventory = module()
    before = inventory.inventory()
    monkeypatch.setattr(component_fingerprint, name, changed)
    after = inventory.inventory()
    assert before["fingerprint"][name] != after["fingerprint"][name]


@pytest.mark.parametrize("name", PROCESS_FUNCTIONS)
def test_each_process_function_mutation_changes_inventory(monkeypatch, name):
    from ralf_agent import coding_process_wait

    inventory = module()
    before = inventory.inventory()
    monkeypatch.setattr(coding_process_wait, name, changed)
    if name == "signal_unreaped_group":
        with pytest.raises(RalfError, match="alias"):
            inventory.inventory()
    else:
        after = inventory.inventory()
        assert before["process_functions"][name] != after["process_functions"][name]


@pytest.mark.parametrize("name", PROCESS_METHODS)
def test_each_monitor_method_mutation_changes_inventory(monkeypatch, name):
    from ralf_agent.coding_process_wait import ChildExitMonitor

    inventory = module()
    before = inventory.inventory()
    monkeypatch.setattr(ChildExitMonitor, name, changed)
    after = inventory.inventory()
    assert before["process_methods"][name] != after["process_methods"][name]


@pytest.mark.parametrize("name", NO_CREATE_RULES)
def test_each_new_no_create_rule_mutation_changes_inventory(monkeypatch, name):
    from ralf_agent import coding_execution_rules

    inventory = module()
    before = inventory.inventory()
    monkeypatch.setattr(coding_execution_rules, name, changed)
    after = inventory.inventory()
    assert before["no_create_rules"][name] != after["no_create_rules"][name]


@pytest.mark.parametrize("name", ["_GROUP_LIMIT", "_PGRP_ONLY"])
def test_policy_type_change_is_pinned(monkeypatch, name):
    from ralf_agent import coding_process_wait

    inventory = module()
    before = inventory.inventory()
    monkeypatch.setattr(coding_process_wait, name, float(getattr(coding_process_wait, name)))
    after = inventory.inventory()
    assert before["process_policy"][name] != after["process_policy"][name]


def test_policy_executable_subclass_is_refused(monkeypatch):
    from ralf_agent import coding_process_wait

    class ExecutableInteger(int):
        pass

    monkeypatch.setattr(coding_process_wait, "_GROUP_LIMIT", ExecutableInteger(4096))
    with pytest.raises(RalfError):
        module().inventory()


@pytest.mark.parametrize(
    "fault",
    [
        "missing_group",
        "extra_group",
        "missing_method",
        "extra_method",
        "wrong_digest",
        "opaque_digest",
        "wrong_group_type",
    ],
)
def test_history_schema_fails_closed(fault):
    inventory = module()
    value = copy.deepcopy(inventory.inventory())
    if fault == "missing_group":
        value.pop("process_policy")
    elif fault == "extra_group":
        value["unreviewed"] = {"helper": "a" * 64}
    elif fault == "missing_method":
        value["process_methods"].pop("register")
    elif fault == "extra_method":
        value["process_methods"]["new_unreviewed"] = "a" * 64
    elif fault == "wrong_digest":
        value["process_methods"]["register"] = "g" * 64
    elif fault == "opaque_digest":
        value["process_methods"]["register"] = True
    else:
        value["process_methods"] = []
    with pytest.raises(RalfError):
        inventory.validate_inventory(value)


def test_history_schema_import_and_validation_never_import_worker_io(monkeypatch):
    inventory = module()
    value = inventory.inventory()
    original_import = builtins.__import__
    forbidden = (
        "coding_process_wait",
        "codex_create_supervisor",
        "codex_create_gate",
        "codex_create_journal",
        "subprocess",
        "socket",
    )

    def guarded(name, *args, **kwargs):
        if any(part in name for part in forbidden):
            raise AssertionError("History imported Worker I/O: " + name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    importlib.reload(inventory)
    inventory.inventory_fields()
    inventory.validate_inventory(value)
    assert sys.modules[inventory.__name__] is inventory


def test_worker_source_declaration_binds_exact_files_and_detects_later_change(
    tmp_path, monkeypatch
):
    inventory = module()
    paths = inventory.source_paths()
    name = "coding_process_wait"
    copied = tmp_path / (name + ".py")
    copied.write_bytes(Path(paths[name]).read_bytes())
    paths[name] = str(copied)
    monkeypatch.setattr(inventory, "source_paths", lambda: paths.copy())
    expected = inventory.source_inventory()
    assert expected[name] == hashlib.sha256(copied.read_bytes()).hexdigest()
    inventory.check_source_inventory(expected)
    copied.write_bytes(copied.read_bytes() + b"\n# changed subprocess bytes\n")
    with pytest.raises(RalfError):
        inventory.check_source_inventory(expected)


@pytest.mark.parametrize("fault", ["missing", "extra", "bad_sha", "typed_sha"])
def test_worker_source_declaration_fails_closed(fault):
    inventory = module()
    value = inventory.source_inventory()
    if fault == "missing":
        value.pop("coding_process_wait")
    elif fault == "extra":
        value["unreviewed"] = "a" * 64
    elif fault == "bad_sha":
        value["coding_process_wait"] = "g" * 64
    else:
        value["coding_process_wait"] = True
    with pytest.raises(RalfError):
        inventory.check_source_inventory(value)


@pytest.mark.parametrize("fault", ["symlink", "hardlink", "missing", "empty", "directory"])
def test_source_reader_refuses_alias_or_missing_bytes(tmp_path, fault):
    inventory = module()
    path = tmp_path / "source.py"
    path.write_bytes(b"bounded original source")
    if fault == "symlink":
        alias = tmp_path / "alias.py"
        alias.symlink_to(path)
        path = alias
    elif fault == "hardlink":
        os.link(path, tmp_path / "alias.py")
    elif fault == "missing":
        path.unlink()
    elif fault == "empty":
        path.write_bytes(b"")
    else:
        path.unlink()
        path.mkdir()
    with pytest.raises(RalfError):
        inventory._source_digest(str(path))


def test_source_reader_refuses_incomplete_read(tmp_path, monkeypatch):
    path = tmp_path / "source.py"
    path.write_bytes(b"bounded original source")
    monkeypatch.setattr(os, "read", lambda *args: b"")
    with pytest.raises(RalfError):
        module()._source_digest(str(path))


@pytest.mark.parametrize(
    "group,module_name,owner,names",
    [
        (
            "journal_functions",
            "codex_create_journal",
            None,
            (
                "require",
                "hex_value",
                "pin",
                "private_directory",
                "private_file",
                "pairs",
                "birth",
                "process_ended",
                "check_fd",
                "lock_released",
                "registration",
                "check_registration",
                "gate_message",
                "accepted_frame",
                "load_declaration",
            ),
        ),
        (
            "journal_methods",
            "codex_create_journal",
            "OperationJournal",
            ("__init__", "check", "read", "write"),
        ),
        (
            "broker_functions",
            "codex_create_supervisor",
            None,
            (
                "_peer",
                "_socket_pin",
                "_request",
                "_serve",
                "_receipt",
                "validate_receipt",
                "run_broker",
                "_spawn_argv",
                "main",
            ),
        ),
        (
            "broker_methods",
            "codex_create_supervisor",
            "CreateSupervisor",
            (
                "__init__",
                "create",
                "open",
                "launch",
                "start_once",
                "query",
                "drain",
                "abort",
                "close",
            ),
        ),
        ("gate_functions", "codex_create_gate", None, ("run_gate", "main")),
    ],
)
def test_complete_broker_gate_journal_inventory_and_each_mutation(
    monkeypatch, group, module_name, owner, names
):
    inventory = module()
    source = importlib.import_module("ralf_agent." + module_name)
    target = source if owner is None else getattr(source, owner)
    assert inventory.inventory_fields()[group] == names
    for name in names:
        before = inventory.inventory()
        with monkeypatch.context() as patch:
            patch.setattr(target, name, changed)
            if group == "journal_functions" and name != "private_file":
                with pytest.raises(RalfError, match="alias"):
                    inventory.inventory()
            else:
                after = inventory.inventory()
                assert before[group][name] != after[group][name], name


def test_broker_property_and_each_policy_constant_are_pinned(monkeypatch):
    from ralf_agent import codex_create_journal, codex_create_supervisor

    inventory = module()
    before = inventory.inventory()
    with monkeypatch.context() as patch:
        patch.setattr(codex_create_supervisor.CreateSupervisor, "declaration", property(changed))
        assert (
            inventory.inventory()["broker_properties"]["declaration"]
            != before["broker_properties"]["declaration"]
        )
    for group, source, name, replacement in (
        ("journal_policy", codex_create_journal, "_MAX_RECORD", 65535),
        ("journal_policy", codex_create_journal, "_WRITERS", {}),
        ("broker_policy", codex_create_supervisor, "_PYTHON_ENV", {}),
        ("broker_policy", codex_create_supervisor, "_RECEIPT_FIELDS", frozenset()),
        ("broker_policy", codex_create_supervisor, "_BOOTSTRAP", "changed interpreter bootstrap"),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(source, name, replacement)
            assert inventory.inventory()[group][name] != before[group][name], name


@pytest.mark.parametrize(
    "name,function_group,class_name,method_group,property_group,policy_group",
    [
        (
            "coding_process_wait",
            "process_functions",
            "ChildExitMonitor",
            "process_methods",
            None,
            "process_policy",
        ),
        (
            "codex_create_journal",
            "journal_functions",
            "OperationJournal",
            "journal_methods",
            None,
            "journal_policy",
        ),
        (
            "codex_create_supervisor",
            "broker_functions",
            "CreateSupervisor",
            "broker_methods",
            "broker_properties",
            "broker_policy",
        ),
        ("codex_create_gate", "gate_functions", None, None, None, None),
    ],
)
def test_reviewed_source_definitions_have_no_unlisted_helper_or_policy(
    name, function_group, class_name, method_group, property_group, policy_group
):
    inventory = module()
    fields = inventory.inventory_fields()
    tree = ast.parse(Path(inventory.source_paths()[name]).read_text())
    functions = {
        item.name for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    constants = {
        target.id
        for item in tree.body
        if isinstance(item, ast.Assign)
        for target in item.targets
        if isinstance(target, ast.Name)
        and target.id.startswith("_")
        and target.id.upper() == target.id
    }
    assert functions == set(fields[function_group])
    assert constants == (set() if policy_group is None else set(fields[policy_group]))
    classes = {item.name: item for item in tree.body if isinstance(item, ast.ClassDef)}
    assert set(classes) == (set() if class_name is None else {class_name})
    if class_name is not None:
        methods, properties = set(), set()
        for item in classes[class_name].body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(
                    isinstance(decorator, ast.Name) and decorator.id == "property"
                    for decorator in item.decorator_list
                ):
                    properties.add(item.name)
                else:
                    methods.add(item.name)
        assert methods == set(fields[method_group])
        assert properties == (set() if property_group is None else set(fields[property_group]))


@pytest.mark.parametrize(
    "module_name,names",
    [
        (
            "codex_create_supervisor",
            (
                "OperationJournal",
                "accepted_frame",
                "birth",
                "process_ended",
                "check_fd",
                "check_registration",
                "gate_message",
                "hex_value",
                "load_declaration",
                "lock_released",
                "pairs",
                "pin",
                "private_directory",
                "registration",
                "require",
                "ChildExitMonitor",
                "signal_unreaped_group",
                "policy_value",
                "canonical",
                "digest",
                "DefinitionMismatch",
                "ExecutionHostFailed",
                "ValidationError",
            ),
        ),
        (
            "codex_create_gate",
            (
                "OperationJournal",
                "accepted_frame",
                "check_fd",
                "gate_message",
                "load_declaration",
                "registration",
                "require",
            ),
        ),
        ("codex_create_journal", ("policy_value", "DefinitionMismatch", "canonical", "digest")),
        (
            "coding_execution_rules",
            ("canonical", "digest", "AuthorizationDenied", "DefinitionMismatch", "ValidationError"),
        ),
        ("coding_resource_fingerprint", ("canonical", "DefinitionMismatch")),
        ("component_fingerprint", ("canonical", "digest", "ValidationError")),
        ("coding_process_wait", ("Popen",)),
    ],
)
def test_each_actual_imported_role_rebind_is_refused(monkeypatch, module_name, names):
    inventory = module()
    target = importlib.import_module("ralf_agent." + module_name)
    for name in names:
        with monkeypatch.context() as patch:
            patch.setattr(target, name, changed)
            with pytest.raises(RalfError, match="alias"):
                inventory.inventory()
