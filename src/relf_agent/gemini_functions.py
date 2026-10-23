"""Explicit Gemini function protocol; execution remains with the calling engine."""

import copy
import re

from .model_native import GeminiProvider, _gemini_usage
from .model_protocol import ModelCapabilities, json_object, response
from .types import ToolCall, canonical, digest

PROTOCOL = "gemini-content-v1"
_CALL_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}")
_DECLARATION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_:.-]{0,127}")


def _name(value, pattern):
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError("Invalid Gemini function name")
    return value


def _call(value):
    if not isinstance(value, dict) or set(value) - {"name", "args", "id"}:
        raise ValueError("Unsupported native function call")
    _name(value["name"], _CALL_NAME)
    if not isinstance(value.get("args", {}), dict):
        raise ValueError("Function arguments must be an object")
    if "id" in value and (not isinstance(value["id"], str) or not value["id"]):
        raise ValueError("Invalid native function identity")
    canonical(value)


def _content(value):
    if (
        not isinstance(value, dict)
        or set(value) - {"role", "parts"}
        or value.get("role", "model") != "model"
        or not isinstance(value.get("parts"), list)
        or not value["parts"]
    ):
        raise ValueError("Unsupported native model content")
    text, calls, ids = [], [], set()
    for index, part in enumerate(value["parts"]):
        if (
            not isinstance(part, dict)
            or set(part) - {"text", "thought", "thoughtSignature", "functionCall"}
            or type(part.get("thought", False)) is not bool
            or (
                "thoughtSignature" in part
                and (not isinstance(part["thoughtSignature"], str) or not part["thoughtSignature"])
            )
            or ("text" in part) == ("functionCall" in part)
        ):
            raise ValueError("Unsupported native model part")
        if "text" in part:
            if not isinstance(part["text"], str):
                raise ValueError("Invalid native text")
            if not part.get("thought", False):
                text.append(part["text"])
        else:
            if part.get("thought", False):
                raise ValueError("Thought-only function calls cannot be executed")
            call = part["functionCall"]
            _call(call)
            host_id = call.get("id", f"gemini-{index}-{digest(part)}")
            if host_id in ids:
                raise ValueError("Repeated native function identity")
            ids.add(host_id)
            calls.append(ToolCall(call["name"], copy.deepcopy(call.get("args", {})), host_id))
    canonical(value)
    return "".join(text) or None, calls


def _decision(output, calls):
    return {
        "output": output,
        "tool_calls": [
            {"name": item.name, "arguments": item.arguments, "call_id": item.call_id}
            for item in calls
        ],
    }


def _candidate(value):
    if "error" in value or value.get("promptFeedback", {}).get("blockReason"):
        raise ValueError("Blocked or failed model response")
    candidates = value["candidates"]
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("Expected one model candidate")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ValueError("Invalid model candidate")
    index = candidate.get("index", 0)
    if type(index) is not int or index != 0:
        raise ValueError("Unexpected candidate identity")
    content = candidate.get("content")
    _content(content)
    return copy.deepcopy(content), candidate.get("finishReason")


def _declarations(tools):
    declarations, names = [], set()
    for tool in tools:
        if set(tool) != {"type", "function"} or tool["type"] != "function":
            raise ValueError("Only function declarations are supported")
        function = tool["function"]
        if set(function) - {"name", "description", "parameters"}:
            raise ValueError("Unsupported function declaration fields")
        name = _name(function["name"], _DECLARATION_NAME)
        # The published declaration/call grammars differ. Admit only names
        # this adapter can consume and echo through the entire tool loop.
        _name(name, _CALL_NAME)
        if name in names:
            raise ValueError("Repeated function declaration")
        names.add(name)
        if not isinstance(function["parameters"], dict):
            raise ValueError("Function schema must be an object")
        declaration = {"name": name, "parametersJsonSchema": copy.deepcopy(function["parameters"])}
        if "description" in function:
            if not isinstance(function["description"], str):
                raise ValueError("Function description must be text")
            declaration["description"] = function["description"]
        declarations.append(declaration)
    return declarations


def _history_calls(value):
    if not isinstance(value, list):
        raise ValueError("Invalid historical calls")
    calls = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "type", "function"}
            or item["type"] != "function"
            or not isinstance(item["id"], str)
            or not item["id"]
            or not isinstance(item["function"], dict)
            or set(item["function"]) != {"name", "arguments"}
        ):
            raise ValueError("Unsupported historical function call")
        function = item["function"]
        _name(function["name"], _CALL_NAME)
        arguments = json_object(function["arguments"])
        calls.append(ToolCall(function["name"], arguments, item["id"]))
    if len({item.call_id for item in calls}) != len(calls):
        raise ValueError("Repeated historical call identity")
    return calls


def _continued_content(message, calls, identity):
    from .model_continuation import ModelContinuation

    original = message["model_continuation"]
    if not isinstance(original, dict) or set(original) != {
        "protocol",
        "owner_digest",
        "decision_digest",
        "data",
    }:
        raise ValueError("Invalid continuation envelope")
    continuation = ModelContinuation(**original).to_dict()
    if (
        continuation["protocol"] != identity["protocol"]
        or continuation["owner_digest"] != identity["owner_digest"]
        or continuation["decision_digest"] != digest(_decision(message.get("content"), calls))
    ):
        raise ValueError("Continuation owner or decision changed")
    data = continuation["data"]
    if set(data) != {"content", "call_ids"}:
        raise ValueError("Unsupported continuation data")
    output, native_calls = _content(data["content"])
    response(output, native_calls)
    if (
        data["call_ids"] != [item.call_id for item in native_calls]
        or digest(_decision(output, native_calls)) != continuation["decision_digest"]
    ):
        raise ValueError("Continuation native content does not match decision")
    return copy.deepcopy(data["content"])


def _messages(messages, identity):
    system, native, pending = [], [], {}
    for message in messages:
        role, content = message["role"], message.get("content")
        allowed = {"role", "content"}
        if role == "assistant":
            allowed |= {"tool_calls", "model_continuation"}
        elif role == "tool":
            allowed |= {"tool_call_id"}
        if set(message) - allowed:
            raise ValueError("Unsupported historical message fields")
        if pending and role != "tool":
            raise ValueError("Function receipt group is incomplete")
        if role == "tool":
            identifier = message.get("tool_call_id")
            if not isinstance(identifier, str) or identifier not in pending:
                raise ValueError("Unknown or repeated function receipt")
            call, native_id = pending.pop(identifier)
            result = json_object('{"result":' + content + "}")["result"]
            result = result if isinstance(result, dict) else {"result": result}
            function_response = {"name": call.name, "response": result}
            if native_id is not None:
                function_response["id"] = native_id
            part = {"functionResponse": function_response}
            if (
                native
                and native[-1]["role"] == "user"
                and all("functionResponse" in item for item in native[-1]["parts"])
            ):
                native[-1]["parts"].append(part)
            else:
                native.append({"role": "user", "parts": [part]})
            continue
        if role == "system":
            if native:
                raise ValueError("System instruction must precede conversation")
            system.append(content)
            continue
        if role != "assistant":
            native.append({"role": "user", "parts": [{"text": content}]})
            continue
        calls = _history_calls(message.get("tool_calls", []))
        if "model_continuation" in message:
            model_content = _continued_content(message, calls, identity)
            raw_calls = [
                part["functionCall"] for part in model_content["parts"] if "functionCall" in part
            ]
        else:
            parts = [{"text": content}] if content else []
            raw_calls = [{"name": call.name, "args": call.arguments} for call in calls]
            parts.extend({"functionCall": value} for value in raw_calls)
            model_content = {"role": "model", "parts": parts}
            _content(model_content)
            response(content, calls)
        for call, original in zip(calls, raw_calls, strict=True):
            pending[call.call_id] = (call, original.get("id"))
        native.append(model_content)
    if pending:
        raise ValueError("Function receipt group is incomplete")
    return system, native


class GeminiFunctionProvider(GeminiProvider):
    """Gemini text/functions with explicit native continuation evidence."""

    supported = ModelCapabilities()

    @property
    def identity(self):
        value = super().identity
        value["kind"] = "gemini-generate-content-functions"
        return value

    @property
    def continuation_identity(self):
        return {"protocol": PROTOCOL, "owner_digest": digest(self.identity)}

    def _body(self, messages, tools, config):
        system, native = _messages(messages, {"protocol": PROTOCOL, "owner_digest": digest(config)})
        names = {
            "temperature": "temperature",
            "top_p": "topP",
            "stop": "stopSequences",
            "seed": "seed",
        }
        options = {names[key]: value for key, value in config.get("generation", {}).items()}
        body = {
            "contents": native,
            "generationConfig": {"maxOutputTokens": config["max_output_tokens"], **options},
        }
        declarations = _declarations(tools)
        if declarations:
            body["tools"] = [{"functionDeclarations": declarations}]
        if system:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        return config["base_url"] + "/models/" + config["model"] + ":generateContent", body

    def _completed(self, content, usage):
        from .model_continuation import ContinuedModelResponse, ModelContinuation

        output, calls = _content(content)
        completed = response(output, calls, usage)
        continuation = ModelContinuation(
            protocol=PROTOCOL,
            owner_digest=digest(self.identity),
            decision_digest=digest(_decision(output, calls)),
            data={"content": content, "call_ids": [item.call_id for item in calls]},
        )
        return ContinuedModelResponse(
            completed.output, completed.tool_calls, completed.usage, continuation=continuation
        )

    def _parse(self, text):
        value = json_object(text)
        content, reason = _candidate(value)
        if reason != "STOP":
            raise ValueError("Incomplete or refused function response")
        return self._completed(content, _gemini_usage(value.get("usageMetadata")))

    def _stream_state(self):
        return GeminiFunctionStream(self)


class GeminiFunctionStream:
    """Accumulate completed native parts without merging opaque signatures."""

    def __init__(self, provider):
        self.provider = provider
        self.parts, self.role, self.reason, self.usage = [], None, None, None

    def feed(self, event, data):
        value = json_object(data)
        if (
            event == "error"
            or "error" in value
            or value.get("promptFeedback", {}).get("blockReason")
        ):
            raise ValueError("Upstream function stream failed")
        if value.get("usageMetadata") is not None:
            self.usage = _gemini_usage(value["usageMetadata"])
        if "candidates" not in value and value.get("usageMetadata") is not None:
            return []
        if self.reason is not None:
            raise ValueError("Content or completion after final candidate")
        candidates = value["candidates"]
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ValueError("Expected one function stream candidate")
        candidate = candidates[0]
        if (
            not isinstance(candidate, dict)
            or type(candidate.get("index", 0)) is not int
            or candidate.get("index", 0) != 0
        ):
            raise ValueError("Invalid function stream candidate")
        reason = candidate.get("finishReason")
        if reason is not None and reason != "STOP":
            raise ValueError("Function stream did not finish successfully")
        content = candidate.get("content")
        emitted = []
        if content is not None:
            _content(content)
            role = content.get("role")
            if role is not None:
                if self.role is not None and self.role != role:
                    raise ValueError("Changed native stream role")
                self.role = role
            self.parts.extend(copy.deepcopy(content["parts"]))
            aggregate = {"parts": self.parts}
            if self.role is not None:
                aggregate["role"] = self.role
            _content(aggregate)
            emitted = [
                part["text"]
                for part in content["parts"]
                if "text" in part and not part.get("thought", False) and part["text"]
            ]
        elif reason is None or not self.parts:
            raise ValueError("Missing native stream content")
        self.reason = reason
        return emitted

    def finish(self):
        if self.reason != "STOP":
            raise ValueError("Function stream did not complete")
        content = {"parts": self.parts}
        if self.role is not None:
            content["role"] = self.role
        return self.provider._completed(content, self.usage)
