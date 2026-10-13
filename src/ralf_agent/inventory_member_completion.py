"""Pure completion policy for the two declared reference inventory members.

This policy checks the original member input and committed tool evidence. The
registered inventory tool and parent gate retain business truth authority; this
module does not read a dataset, execute a tool or schedule a retry.
"""

import json

from .completion import CompletionRequest, CompletionVerdict, ToolReceiptVerifier
from .errors import ValidationError
from .types import canonical


def _object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise ValidationError("Inventory member input requires structured JSON") from error
    if type(value) is not dict:
        raise ValidationError("Inventory member input requires an object")
    return value


def _request(value, pointer):
    value = _object(value)
    if "task" in value and type(value["task"]) is dict and "dataset_id" not in value:
        value = value["task"]
    if pointer == "/request":
        value = _object(value.get("request"))
    if (
        set(value) != {"dataset_id", "target", "quantity"}
        or type(value["dataset_id"]) is not str
        or not value["dataset_id"].strip()
        or value["target"] is not None
        and (type(value["target"]) is not str or not value["target"].strip())
        or value["quantity"] is not None
        and (type(value["quantity"]) is not int or not 1 <= value["quantity"] <= 100000)
    ):
        raise ValidationError("Inventory member request requires dataset_id,target,quantity")
    return value


def _lookup(value, request):
    if (
        type(value) is not dict
        or set(value) != {"found", "dataset_id", "target", "item"}
        or type(value["found"]) is not bool
        or value["dataset_id"] != request["dataset_id"]
        or value["target"] != request["target"]
    ):
        return False
    if not value["found"]:
        return value["item"] is None
    item = value["item"]
    return (
        type(item) is dict
        and set(item) == {"sku", "units_available", "unit_price_cents"}
        and item["sku"] == request["target"]
        and type(item["units_available"]) is int
        and 1 <= item["units_available"] <= 100000
        and type(item["unit_price_cents"]) is int
        and 0 <= item["unit_price_cents"] <= 100000000
    )


class InventoryMemberCompletionVerifier:
    """Reference-only researcher/writer rules using original completion ports."""

    def __init__(self, member, *, request_pointer=""):
        if type(member) is not str or member not in {"researcher", "writer"}:
            raise ValidationError("Inventory completion requires researcher or writer")
        if type(request_pointer) is not str or request_pointer not in {"", "/request"}:
            raise ValidationError("Inventory completion requires its declared request shape")
        self._identity_json = canonical(
            {
                "kind": "inventory-member-completion-verifier",
                "version": "1",
                "member": member,
                "request_pointer": request_pointer,
            }
        )

    @property
    def identity(self):
        return json.loads(self._identity_json)

    def verify(self, request):
        if type(request) is not CompletionRequest:
            raise ValidationError("Inventory completion requires the original completion request")
        config = self.identity
        try:
            if config["member"] == "researcher":
                return self._researcher(request, config["request_pointer"])
            return self._writer(request, config["request_pointer"])
        except (ValidationError, KeyError, TypeError):
            return CompletionVerdict(
                "reject", "The declared inventory member input is not valid structured evidence."
            )

    def _researcher(self, request, pointer):
        intent = _request(request.task, pointer)
        feedback = (
            "Use inventory_lookup with exactly the original request dataset_id and target. "
            "Consume the actual tool result, then return {request,lookup} preserving both "
            "the original request and that complete result. Do not invent found=false. "
            "If target or quantity is null, return lookup:null without calling inventory_lookup."
        )
        missing = CompletionVerdict("retry", feedback)
        output = request.output
        if (
            type(output) is not dict
            or set(output) != {"request", "lookup"}
            or canonical(output["request"]) != canonical(intent)
        ):
            return missing
        if intent["target"] is None or intent["quantity"] is None:
            return (
                CompletionVerdict("accept")
                if output["lookup"] is None and not request.receipts
                else missing
            )
        rule = ToolReceiptVerifier(
            "inventory_lookup",
            argument_bindings={"dataset_id": "/request/dataset_id", "target": "/request/target"},
            feedback=feedback,
        )
        if rule.verify(request).status != "accept" or not _lookup(output["lookup"], intent):
            return missing
        expected_arguments = {"dataset_id": intent["dataset_id"], "target": intent["target"]}
        if any(
            receipt["tool"] == "inventory_lookup"
            and canonical(receipt["arguments"]) == canonical(expected_arguments)
            and canonical(receipt["result"]) == canonical(output["lookup"])
            for receipt in request.receipts
        ):
            return CompletionVerdict("accept")
        return missing

    def _writer(self, request, pointer):
        incoming = _object(request.task)
        if "results" in incoming:
            evidence = _object(_object(incoming["results"]).get("researcher"))
            original = _request(incoming["task"], pointer)
            if canonical(evidence.get("request")) != canonical(original):
                raise ValidationError("Writer evidence differs from its original Team request")
        else:
            evidence = incoming
        intent = _request(evidence.get("request"), "")
        lookup = evidence.get("lookup")
        stop = None
        if intent["target"] is None or intent["quantity"] is None:
            if lookup is not None:
                raise ValidationError("Missing inventory input requires absent lookup")
            stop = "needs_input"
        elif not _lookup(lookup, intent):
            raise ValidationError("Writer requires the declared researcher lookup evidence")
        elif not lookup["found"]:
            stop = "not_found"
        elif intent["quantity"] > lookup["item"]["units_available"]:
            stop = "needs_input"
        if stop is not None:
            expected = {"status": stop, "total": None}
            if canonical(request.output) == canonical(expected) and not request.receipts:
                return CompletionVerdict("accept")
            return CompletionVerdict(
                "retry",
                "Return the truthful inventory stop "
                + canonical(expected)
                + "; do not call calculator for missing input, unknown stock or insufficient stock.",
            )
        feedback = (
            "Call calculator with exactly the predecessor request quantity and lookup item "
            "unit_price_cents. Consume its committed result, then return completed and that "
            "integer total. Do not invent a total or a needs_input/not_found stop."
        )
        missing = CompletionVerdict("retry", feedback)
        if ToolReceiptVerifier("calculator", feedback=feedback).verify(request).status != "accept":
            return missing
        arguments = {
            "quantity": intent["quantity"],
            "unit_price_cents": lookup["item"]["unit_price_cents"],
        }
        total = arguments["quantity"] * arguments["unit_price_cents"]
        for receipt in request.receipts:
            if (
                receipt["tool"] == "calculator"
                and canonical(receipt["arguments"]) == canonical(arguments)
                and canonical(receipt["result"]) == canonical({"total": total})
                and canonical(request.output) == canonical({"status": "completed", "total": total})
            ):
                return CompletionVerdict("accept")
        return missing
