"""Declared receipt rules and a concrete frozen inventory business oracle."""

import json
import re

from .completion import _matches, _pointer, _schema
from .errors import ValidationError
from .parent_completion import ParentCompletionRequest, ParentCompletionVerdict, _json, _path, _text
from .types import canonical, digest

_RULE_FIELDS = {
    "id",
    "member_path",
    "tool",
    "when",
    "result_schema",
    "argument_bindings",
    "output_bindings",
    "require_consumed",
}


def _valid_pointer(value):
    if (
        type(value) is not str
        or value
        and (not value.startswith("/") or re.search(r"~(?![01])", value))
    ):
        raise ValidationError("Parent receipt selectors require valid JSON Pointers")
    return value


def _selectors(value, *, output=False):
    if type(value) is not dict:
        raise ValidationError("Parent receipt bindings require a JSON mapping")
    for key, selector in value.items():
        if output:
            _valid_pointer(key)
        else:
            _text(key, "Receipt argument binding")
        if (
            type(selector) is not dict
            or set(selector) != {"source", "pointer"}
            or type(selector["source"]) is not str
            or selector["source"] not in {"task", "candidate"}
        ):
            raise ValidationError("Receipt selector requires task/candidate and pointer")
        _valid_pointer(selector["pointer"])
    return _json(value)


def _rule(value):
    if (
        type(value) is not dict
        or set(value) - _RULE_FIELDS
        or not {"id", "member_path", "tool"} <= set(value)
    ):
        raise ValidationError("Receipt rule fields are incomplete or undeclared")
    _text(value["id"], "Receipt rule ID")
    _text(value["tool"], "Receipt rule tool")
    consumed = value.get("require_consumed", True)
    if type(consumed) is not bool:
        raise ValidationError("Receipt consumption requirement must be boolean")
    return {
        "id": value["id"],
        "member_path": _path(value["member_path"]),
        "tool": value["tool"],
        "when": _schema(value.get("when")),
        "result_schema": _schema(value.get("result_schema")),
        "argument_bindings": _selectors(value.get("argument_bindings", {})),
        "output_bindings": _selectors(value.get("output_bindings", {}), output=True),
        "require_consumed": consumed,
    }


def _request(request):
    if type(request) is not ParentCompletionRequest:
        raise ValidationError("Parent receipt gate requires a concrete frozen request")
    return ParentCompletionRequest.from_dict(request.to_dict())


def _models(request, path):
    return [
        (owner, model)
        for owner in request.children
        for model in owner["final_models"]
        if model["member_path"] == path
    ]


def _consumed(request, receipt):
    return any(
        model["input_consumed"]
        and "model:" + digest([owner["run_id"], model["action_id"]]) in receipt["consumed_by"]
        for owner, model in _models(request, receipt["member_path"])
        if owner["run_id"] == receipt["run_id"]
    )


def _selected(request, selector):
    return _pointer(getattr(request, selector["source"]), selector["pointer"])


def _missing(config, reason):
    return ParentCompletionVerdict(config["on_missing"], feedback=reason)


class ReceiptParentCompletionGate:
    def __init__(self, rules, *, required_members=(), candidate_schema=None, on_missing="reject"):
        if type(rules) not in {tuple, list} or not 1 <= len(rules) <= 256:
            raise ValidationError("Receipt parent gate requires 1 to 256 rules")
        if type(on_missing) is not str or on_missing not in {"reject", "replan"}:
            raise ValidationError("Missing parent receipt must reject or replan")
        normalized = [_rule(value) for value in rules]
        if len({value["id"] for value in normalized}) != len(normalized):
            raise ValidationError("Receipt rule IDs must be unique")
        if type(required_members) not in {tuple, list} or len(required_members) > 256:
            raise ValidationError("Required members must be bounded declared paths")
        required = [_path(path) for path in required_members]
        if len({tuple(path) for path in required}) != len(required):
            raise ValidationError("Required member paths must be unique")
        self._identity_json = canonical(
            {
                "kind": "receipt-parent-completion-gate",
                "version": "1",
                "rules": normalized,
                "required_members": required,
                "candidate_schema": _schema(candidate_schema),
                "on_missing": on_missing,
            }
        )

    @property
    def identity(self):
        return json.loads(self._identity_json)

    def verify(self, request):
        request, config = _request(request), self.identity
        if config["candidate_schema"] is not None and not _matches(
            config["candidate_schema"], request.candidate
        ):
            return _missing(config, "The frozen candidate does not satisfy its declared Schema.")
        ids = []
        for path in config["required_members"]:
            owners = [owner for owner in request.children if owner["member_path"] == path]
            owners.extend(owner for owner, _ in _models(request, path))
            if not owners:
                return _missing(
                    config, "A required business member has no completed owned evidence."
                )
            ids.append(owners[0]["id"])
        for rule in config["rules"]:
            if rule["when"] is not None and not _matches(rule["when"], request.candidate):
                continue
            try:
                arguments = {
                    key: _selected(request, selector)
                    for key, selector in rule["argument_bindings"].items()
                }
                outputs = {
                    pointer: _selected(request, selector)
                    for pointer, selector in rule["output_bindings"].items()
                }
            except (KeyError, IndexError, TypeError):
                return _missing(
                    config, "A receipt binding selector is absent from the frozen source."
                )
            matched = None
            for tool in request.receipts:
                if tool["tool"] != rule["tool"] or tool["member_path"] != rule["member_path"]:
                    continue
                if rule["require_consumed"] and not _consumed(request, tool):
                    continue
                if any(
                    key not in tool["arguments"]
                    or canonical(tool["arguments"][key]) != canonical(expected)
                    for key, expected in arguments.items()
                ):
                    continue
                if rule["result_schema"] is not None and not _matches(
                    rule["result_schema"], tool["result"]
                ):
                    continue
                try:
                    if any(
                        canonical(_pointer(tool["result"], pointer)) != canonical(expected)
                        for pointer, expected in outputs.items()
                    ):
                        continue
                except (KeyError, IndexError, TypeError):
                    continue
                matched = tool
                break
            if matched is None:
                return _missing(
                    config, f"Rule {rule['id']} requires one corresponding consumed tool receipt."
                )
            ids.extend(
                [
                    next(
                        owner["id"]
                        for owner in request.children
                        if owner["run_id"] == matched["run_id"]
                    ),
                    matched["id"],
                ]
            )
        return ParentCompletionVerdict("accept", evidence_ids=list(dict.fromkeys(ids)))


def _dataset(dataset):
    value = _json(dataset)
    if (
        type(value) is not dict
        or set(value) != {"id", "inventory"}
        or type(value["inventory"]) is not list
        or not 1 <= len(value["inventory"]) <= 1000
    ):
        raise ValidationError("Inventory policy requires a frozen bounded dataset")
    _text(value["id"], "Inventory dataset ID")
    seen = set()
    for item in value["inventory"]:
        if type(item) is not dict or set(item) != {"sku", "units_available", "unit_price_cents"}:
            raise ValidationError("Inventory policy item fields are incomplete or undeclared")
        _text(item["sku"], "Inventory SKU")
        if (
            item["sku"] in seen
            or type(item["units_available"]) is not int
            or not 0 <= item["units_available"] <= 100000
            or type(item["unit_price_cents"]) is not int
            or not 0 <= item["unit_price_cents"] <= 100000000
        ):
            raise ValidationError(
                "Inventory policy items require unique SKUs and bounded integer quantities/prices"
            )
        seen.add(item["sku"])
    return value


class InventoryParentCompletionGate:
    def __init__(
        self,
        *,
        dataset,
        request_pointer="",
        researcher_path=("researcher",),
        writer_path=("writer",),
        on_missing="reject",
    ):
        if type(on_missing) is not str or on_missing not in {"reject", "replan"}:
            raise ValidationError("Missing inventory evidence must reject or replan")
        researcher_path, writer_path = _path(researcher_path), _path(writer_path)
        if researcher_path == writer_path:
            raise ValidationError("Inventory researcher and writer must be distinct declared paths")
        self._identity_json = canonical(
            {
                "kind": "inventory-parent-completion-gate",
                "version": "1",
                "dataset": _dataset(dataset),
                "request_pointer": _valid_pointer(request_pointer),
                "researcher_path": researcher_path,
                "writer_path": writer_path,
                "on_missing": on_missing,
            }
        )

    @property
    def identity(self):
        return json.loads(self._identity_json)

    def verify(self, request):
        request, config = _request(request), self.identity
        rejected = _missing(
            config,
            "Inventory completion lacks exact owned receipts, arithmetic, stopping or input consumption evidence.",
        )
        try:
            structured = _pointer(request.task, config["request_pointer"])
        except (KeyError, IndexError, TypeError):
            return rejected
        if (
            type(structured) is not dict
            or set(structured) != {"dataset_id", "target", "quantity"}
            or structured["dataset_id"] != config["dataset"]["id"]
        ):
            return rejected
        target, quantity = structured["target"], structured["quantity"]
        if (
            target is not None
            and (type(target) is not str or not target.strip())
            or quantity is not None
            and (type(quantity) is not int or not 1 <= quantity <= 100000)
        ):
            return rejected
        researcher_models = [
            (owner, model)
            for owner, model in _models(request, config["researcher_path"])
            if model["input_consumed"]
        ]
        writer_models = [
            (owner, model)
            for owner, model in _models(request, config["writer_path"])
            if model["input_consumed"]
        ]
        if not researcher_models or not writer_models:
            return rejected
        lookup = None
        if target is not None and quantity is not None:
            item = next(
                (item for item in config["dataset"]["inventory"] if item["sku"] == target), None
            )
            lookup = {
                "found": item is not None,
                "dataset_id": structured["dataset_id"],
                "target": target,
                "item": item,
            }
        evidence = {"request": structured, "lookup": lookup}
        if lookup is None and request.receipts:
            return rejected
        if lookup is None or lookup["found"] and quantity > lookup["item"]["units_available"]:
            expected = {"status": "needs_input", "total": None}
        elif not lookup["found"]:
            expected = {"status": "not_found", "total": None}
        else:
            expected = {
                "status": "completed",
                "total": quantity * lookup["item"]["unit_price_cents"],
            }
        if canonical(request.candidate) != canonical(expected):
            return rejected
        researcher_owners = {
            owner["run_id"]: owner
            for owner, _ in researcher_models
            if owner["member_path"] != config["researcher_path"]
            or canonical(owner["result"]) == canonical(evidence)
        }
        writer_input = (
            {"task": request.task, "results": {config["researcher_path"][-1]: evidence}}
            if request.parent_kind == "team"
            else evidence
        )
        writer_owners = {
            owner["run_id"]: owner
            for owner, model in writer_models
            if model["input_digest"] == digest(writer_input)
            and (
                owner["member_path"] != config["writer_path"]
                or canonical(owner["result"]) == canonical(expected)
            )
        }
        if not researcher_owners or not writer_owners:
            return rejected
        lookups = [
            tool for tool in request.receipts if tool["member_path"] == config["researcher_path"]
        ]
        calculators = [
            tool for tool in request.receipts if tool["member_path"] == config["writer_path"]
        ]
        ids = [
            next(iter(researcher_owners.values()))["id"],
            next(iter(writer_owners.values()))["id"],
        ]
        if lookup is None:
            if lookups:
                return rejected
        else:
            if len(lookups) != 1:
                return rejected
            tool = lookups[0]
            if (
                tool["run_id"] not in researcher_owners
                or tool["tool"] != "inventory_lookup"
                or canonical(tool["arguments"])
                != canonical({"dataset_id": structured["dataset_id"], "target": target})
                or canonical(tool["result"]) != canonical(lookup)
                or not _consumed(request, tool)
            ):
                return rejected
            ids.append(tool["id"])
        if expected["status"] != "completed":
            if calculators:
                return rejected
        else:
            if len(calculators) != 1:
                return rejected
            tool = calculators[0]
            arguments = {
                "quantity": quantity,
                "unit_price_cents": lookup["item"]["unit_price_cents"],
            }
            if (
                tool["run_id"] not in writer_owners
                or tool["tool"] != "calculator"
                or canonical(tool["arguments"]) != canonical(arguments)
                or canonical(tool["result"]) != canonical({"total": expected["total"]})
                or not _consumed(request, tool)
            ):
                return rejected
            ids.append(tool["id"])
        return ParentCompletionVerdict("accept", evidence_ids=list(dict.fromkeys(ids)))
