"""Bound leaf releases remain anchored to the original declared parent selection."""

import asyncio
import copy

import pytest

from relf_agent.errors import ValidationError
from relf_agent.orchestration_evaluation import (
    OfflineOrchestrationProvider,
    evaluate_orchestration,
    load_orchestration_cases,
)
from relf_agent.parent_completion_evaluation import _owned_runs
from relf_agent.storage import SQLiteStore
from relf_agent.types import digest


@pytest.fixture(scope="module", params=["plan-and-execute", "team"])
def original_records(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("inventory-original-binding")
    report = asyncio.run(
        evaluate_orchestration(
            OfflineOrchestrationProvider(),
            kind=request.param,
            cases=load_orchestration_cases()[:1],
            completion_gate=True,
            member_verification=True,
            evidence_dir=directory,
        )
    )
    with SQLiteStore(directory / "wire-a-0.sqlite", readonly=True) as store:
        parent = store.run(report["cases"][0]["run_id"])
        children = [store.run(call["run_id"]) for call in parent["orchestration"]["children"]]
    return parent, children


def test_original_member_binding_is_a_parent_projection(original_records):
    parent, children = copy.deepcopy(original_records)
    assert len(_owned_runs(parent, children)) == 2


@pytest.mark.parametrize(
    "corruption",
    [
        "child-definition",
        "child-entry",
        "child-verifier",
        "parent-entry",
        "parent-declaration",
        "member-release",
        "child-extra-component",
        "coherent-wrong-verifier",
    ],
)
def test_rehashed_wrong_binding_cannot_be_accepted(original_records, corruption):
    parent, children = copy.deepcopy(original_records)
    assert len(_owned_runs(parent, children)) == 2
    call, child = parent["orchestration"]["children"][0], children[0]
    path = parent["definition"]["kind"] + "/members/" + call["member"]
    parent_entry = parent["manifest"]["agent_bindings"]["steps"][path]
    child_entry = child["manifest"]["agent_bindings"]["steps"]["agent"]
    member_release = parent["manifest"]["orchestration"]["members"][call["member"]]
    if corruption == "child-definition":
        child["definition"]["binding_definition"]["bindings"]["verifier"]["component_id"] = (
            "foreign"
        )
    elif corruption == "child-entry":
        child_entry["descriptor"]["verifier"]["component_id"] = "foreign"
    elif corruption == "child-verifier":
        child_entry["manifest"]["completion_verifier"]["member"] = "writer"
    elif corruption == "parent-entry":
        parent_entry["resolved"]["verifier"]["scope"]["principal"] = "foreign"
    elif corruption == "parent-declaration":
        parent["definition"]["binding_definition"]["agent_bindings"][path]["verifier"][
            "component_id"
        ] = "foreign"
    elif corruption == "member-release":
        member_release["runtime_profile"]["version"] = "foreign"
    elif corruption == "child-extra-component":
        child["manifest"]["foreign_source"] = {"version": "1"}
    else:
        for entry in (
            parent_entry,
            child_entry,
            member_release["agent_bindings"]["steps"]["agent"],
        ):
            entry["resolved"]["verifier"]["identity"]["member"] = "writer"
            entry["manifest"]["completion_verifier"]["member"] = "writer"
    for run in (parent, *children):
        run["release_digest"] = digest(
            {"definition": run["definition"], "manifest": run["manifest"]}
        )
    with pytest.raises(ValidationError):
        _owned_runs(parent, children)
