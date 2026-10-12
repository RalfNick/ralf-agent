"""Explicit stateless Responses reasoning; execution remains with the engine."""

import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .errors import ValidationError
from .model_continuation import ContinuedModelResponse, ModelContinuation
from .model_http import HTTPModelProvider
from .model_protocol import json_object
from .responses_format import LOCAL_SCHEMA_REGISTRY, validate_strict_schema
from .responses_reasoning_codec import PROTOCOL, decision, declarations, input_items, parse_response
from .responses_reasoning_stream import ResponsesReasoningStream
from .types import canonical, digest

_OPTIONS = {
    "reasoning_effort": {"none", "minimal", "low", "medium", "high", "xhigh", "max"},
    "reasoning_context": {"auto", "current_turn", "all_turns"},
    "reasoning_summary": {"auto", "concise", "detailed"},
    "reasoning_mode": {"standard", "pro"},
}


class OpenAIResponsesReasoningProvider(HTTPModelProvider):
    """Text/client functions with original encrypted reasoning and phase replay."""

    allow_seed = False

    def __init__(
        self,
        model,
        *,
        api_key=None,
        base_url="https://api.openai.com/v1",
        max_output_tokens=1024,
        timeout=60,
        client=None,
        stream=False,
        capabilities=None,
        json_mode=False,
        output_schema=None,
        schema_name="ralf_output",
        reasoning_effort=None,
        reasoning_context=None,
        reasoning_summary=None,
        reasoning_mode=None,
    ):
        self.json_mode, self.schema_name = json_mode, schema_name
        self.reasoning_effort, self.reasoning_context = reasoning_effort, reasoning_context
        self.reasoning_summary, self.reasoning_mode = reasoning_summary, reasoning_mode
        self._schema_json = None if output_schema is None else canonical(output_schema)
        self._configure(
            model,
            api_key,
            "OPENAI_API_KEY",
            base_url,
            max_output_tokens,
            timeout,
            client,
            None,
            None,
            None,
            None,
            stream,
            capabilities,
        )

    @property
    def identity(self):
        if any(
            getattr(self, field) is not None for field in ("temperature", "top_p", "stop", "seed")
        ):
            raise ValidationError(
                "Responses reasoning does not support inherited generation options"
            )
        value = self._configuration("openai-responses-reasoning")
        if type(self.json_mode) is not bool or self.json_mode and self._schema_json is not None:
            raise ValidationError("Choose JSON object or explicit Schema formatting")
        for field, accepted in _OPTIONS.items():
            current = getattr(self, field)
            if current is not None:
                if not isinstance(current, str) or current not in accepted:
                    raise ValidationError("Invalid Responses reasoning option")
                value[field] = current
        if self.json_mode:
            value["json_mode"] = True
        if self._schema_json is not None:
            schema = json.loads(self._schema_json)
            if (
                not isinstance(schema, dict)
                or schema.get("type") != "object"
                or len(self._schema_json) > 65536
            ):
                raise ValidationError("Responses output Schema requires a bounded object Schema")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise ValidationError("Invalid Responses output Schema") from exc
            if (
                not isinstance(self.schema_name, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.schema_name) is None
            ):
                raise ValidationError("Invalid Responses Schema name")
            validate_strict_schema(schema)
            value.update(output_schema=schema, schema_name=self.schema_name)
        return value

    @property
    def continuation_identity(self):
        return {"protocol": PROTOCOL, "owner_digest": digest(self.identity)}

    def _headers(self, key):
        return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

    def _body(self, messages, tools, config):
        if config.get("json_mode") and not any(
            message["role"] in {"system", "user"} and "json" in (message["content"] or "").lower()
            for message in messages
        ):
            raise ValueError("JSON object mode requires an explicit JSON instruction")
        functions = declarations(tools)
        body = {
            "model": config["model"],
            "max_output_tokens": config["max_output_tokens"],
            "input": input_items(
                messages,
                {"protocol": PROTOCOL, "owner_digest": digest(config)},
                tools=bool(functions),
            ),
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        reasoning = {
            field.removeprefix("reasoning_"): config[field] for field in _OPTIONS if field in config
        }
        if reasoning:
            body["reasoning"] = reasoning
        if functions:
            body["tools"] = functions
        if config.get("json_mode"):
            body["text"] = {"format": {"type": "json_object"}}
        elif "output_schema" in config:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": config["schema_name"],
                    "strict": True,
                    "schema": config["output_schema"],
                }
            }
        return config["base_url"] + "/responses", body

    def _parse(self, text):
        value = json_object(text)
        completed = parse_response(value)
        if not completed.tool_calls and (self.json_mode or self._schema_json is not None):
            final = json_object(completed.output)
            if self._schema_json is not None:
                schema = json.loads(self._schema_json)
                validate_strict_schema(schema)
                if not Draft202012Validator(schema, registry=LOCAL_SCHEMA_REGISTRY).is_valid(final):
                    raise ValueError("Final output does not match configured Schema")
        continuation = ModelContinuation(
            protocol=PROTOCOL,
            owner_digest=digest(self.identity),
            decision_digest=digest(decision(completed.output, completed.tool_calls)),
            data={"output": value["output"]},
        )
        return ContinuedModelResponse(
            completed.output, completed.tool_calls, completed.usage, continuation=continuation
        )

    def _stream_body(self, url, body):
        return url, {**body, "stream": True}

    def _stream_state(self):
        return ResponsesReasoningStream(lambda value: self._parse(canonical(value)))
