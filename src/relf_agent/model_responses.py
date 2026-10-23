"""Native stateless Responses text/functions; explicit unsupported continuations."""

import copy
import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .errors import ValidationError
from .model_http import HTTPModelProvider
from .model_protocol import json_object
from .responses_codec import input_items, parse_response
from .responses_format import LOCAL_SCHEMA_REGISTRY, validate_strict_schema
from .responses_stream import ResponsesStream
from .types import canonical


class OpenAIResponsesProvider(HTTPModelProvider):
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
        temperature=None,
        top_p=None,
        stream=False,
        capabilities=None,
        json_mode=False,
        output_schema=None,
        schema_name="ralf_output",
        reasoning_effort=None,
    ):
        self.json_mode, self.schema_name, self.reasoning_effort = (
            json_mode,
            schema_name,
            reasoning_effort,
        )
        self._schema_json = None if output_schema is None else canonical(output_schema)
        self._configure(
            model,
            api_key,
            "OPENAI_API_KEY",
            base_url,
            max_output_tokens,
            timeout,
            client,
            temperature,
            top_p,
            None,
            None,
            stream,
            capabilities,
        )

    @property
    def identity(self):
        value = self._configuration("openai-responses")
        if (
            type(self.json_mode) is not bool
            or self.reasoning_effort is not None
            and self.reasoning_effort != "none"
        ):
            raise ValidationError("Responses format/continuation configuration is unsupported")
        if self.json_mode and self._schema_json is not None:
            raise ValidationError("Choose JSON object or explicit Schema formatting")
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
            value["output_schema"] = schema
            value["schema_name"] = self.schema_name
        if self.reasoning_effort is not None:
            value["reasoning_effort"] = self.reasoning_effort
        return value

    def _headers(self, key):
        return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

    def _body(self, messages, tools, config):
        if config.get("json_mode") and not any(
            m["role"] in {"system", "user"} and "json" in (m["content"] or "").lower()
            for m in messages
        ):
            raise ValidationError("JSON mode requires an explicit JSON instruction")
        body = {
            "model": config["model"],
            "input": input_items(messages),
            "max_output_tokens": config["max_output_tokens"],
            "store": False,
            **config.get("generation", {}),
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "parameters": copy.deepcopy(t["function"]["parameters"]),
                    "strict": False,
                }
                for t in tools
            ]
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
        if "reasoning_effort" in config:
            body["reasoning"] = {"effort": config["reasoning_effort"]}
        return config["base_url"] + "/responses", body

    def _parse(self, text):
        result = parse_response(json_object(text))
        if not result.tool_calls and (self.json_mode or self._schema_json is not None):
            value = json_object(result.output)
            if self._schema_json is not None:
                schema = json.loads(self._schema_json)
                validate_strict_schema(schema)
                if not Draft202012Validator(schema, registry=LOCAL_SCHEMA_REGISTRY).is_valid(value):
                    raise ValueError("Final output does not match the configured Schema")
        return result

    def _stream_body(self, url, body):
        return url, {**body, "stream": True}

    def _stream_state(self):
        return ResponsesStream(lambda value: self._parse(canonical(value)))
