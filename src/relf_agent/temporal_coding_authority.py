"""Worker callbacks to the original Workflow History, never a second authority."""

import copy
from dataclasses import asdict

from .errors import DefinitionMismatch, ValidationError
from .executors import DispatchEnvelope
from .ports import is_async_callable
from .task_controls import _binding
from .types import canonical, digest


class TemporalCodingAuthority:
    """Fixed per-invocation async ports; History validates every phase claim."""

    def __init__(self, *, request, invocation_id, query, update, validate, owner_proof=None):
        if any(not is_async_callable(method) for method in (query, update, validate)):
            raise ValidationError("Coding History requires fixed async callbacks")
        if type(invocation_id) is not str or not invocation_id or len(invocation_id) > 1024:
            raise ValidationError("Coding requires its bounded original invocation claim")
        from .temporal_state import detached

        self._request = detached(request)
        native = self._request.get("coding_request")
        if type(native) is not dict or native.get("request_digest") != digest(
            {key: value for key, value in native.items() if key != "request_digest"}
        ):
            raise DefinitionMismatch("Coding original native intent is unavailable")
        self._query, self._update, self._validate = query, update, validate
        self._pins = tuple(_binding(method) for method in (query, update, validate))
        self._proof = {
            name: self._request[name]
            for name in ("scope", "run_id", "action_id", "release_digest", "execution_epoch")
        } | {"request_digest": digest(self._request), "invocation_id": invocation_id}
        self._owner_proof = detached(owner_proof) if owner_proof is not None else None

    @property
    def owner_proof(self):
        return copy.deepcopy(self._owner_proof)

    def _check_pins(self):
        if (
            tuple(_binding(method) for method in (self._query, self._update, self._validate))
            != self._pins
        ):
            raise DefinitionMismatch("Coding original History callbacks changed")

    async def validate_registration(self):
        self._check_pins()
        await self._validate()
        self._check_pins()

    async def _call(self, name, payload, *, update=False):
        self._check_pins()
        await self._validate()
        self._check_pins()
        result = await (self._update if update else self._query)(name, copy.deepcopy(payload))
        self._check_pins()
        await self._validate()
        self._check_pins()
        canonical(result)
        return copy.deepcopy(result)

    async def _state(self, *dispatch):
        from .temporal_coding_state import CODING_QUERY

        if len(dispatch) not in (0, 2):
            raise DefinitionMismatch("Coding requires its original dispatch and Runner pair")
        if dispatch:
            envelope, runner_identity = dispatch
            if type(envelope) is not DispatchEnvelope:
                raise DefinitionMismatch("Coding requires its original DispatchEnvelope")
            expected = asdict(envelope.context) | {
                "tool_manifest": envelope.tool_manifest,
                "arguments": envelope.arguments,
                "operation_digest": envelope.operation_digest,
            }
            if expected != self._request["coding_request"]["dispatch"]:
                raise DefinitionMismatch("Coding original dispatch changed")
        result = await self._call(CODING_QUERY, self._proof)
        if (
            type(result) is not dict
            or result.get("request") != self._request["coding_request"]
            or type(result.get("runner")) is not dict
            or type(result.get("state")) is not dict
            or type(result.get("cancelled")) is not bool
        ):
            raise DefinitionMismatch("Coding query lost its original native intent")
        if dispatch and result["runner"] != runner_identity:
            raise DefinitionMismatch("Coding original Runner changed")
        return result

    async def check(self, envelope, runner_identity):
        value = await self._state(envelope, runner_identity)
        return value["request"]

    async def resource_state(self, envelope, runner_identity):
        # Project the same fresh response whose dispatch and Runner were checked;
        # a second Query would require another complete pre/post validation set.
        value = (await self._state(envelope, runner_identity))["state"]
        result = {"prepare_grant": value["grants"].get("prepare")} | {
            name: value.get(name) for name in ("prepared", "binding", "thread", "turn")
        }
        if value.get("create_not_dispatched") is not None:
            result["create_not_dispatched"] = value["create_not_dispatched"]
        return result

    async def cancelled(self):
        return (await self._state())["cancelled"]

    async def authorize(self, method, params, binding):
        from .temporal_coding_state import CODING_GRANT

        return await self._call(
            CODING_GRANT,
            self._proof | {"method": method, "params": params, "binding": binding},
            update=True,
        )

    async def adopt(self, kind, evidence):
        from .temporal_coding_state import CODING_RECEIPT

        result = await self._call(
            CODING_RECEIPT, self._proof | {"kind": kind, "evidence": evidence}, update=True
        )
        if result != {"action_id": self._proof["action_id"], "recorded": True}:
            raise DefinitionMismatch("Coding receipt lacks original History acknowledgement")
