"""Semantic SSE fragments must agree with the complete authoritative response."""

from .model_protocol import json_object


def _index(value):
    if type(value) is not int or not 0 <= value < 1000:
        raise ValueError("Invalid stream index")
    return value


def _id(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Invalid stream identity")
    return value


class ResponsesStream:
    def __init__(self, parse):
        self.parse = parse
        self.completed = None
        self.sequence = -1
        self.response_id = None
        self.text, self.arguments = {}, {}
        self.items_added, self.items_done = {}, {}
        self.parts_added, self.parts_done = {}, {}
        self.text_done, self.arguments_done = {}, {}

    def feed(self, event, data):
        value = json_object(data)
        kind, sequence = value.get("type"), value.get("sequence_number")
        if self.completed is not None or (event is not None and event != kind):
            raise ValueError("Invalid event after completion or mismatching type")
        if type(sequence) is not int or sequence < 0 or sequence <= self.sequence:
            raise ValueError("Invalid stream event sequence")
        self.sequence = sequence
        if kind in {"response.created", "response.in_progress", "response.completed"}:
            snapshot = value["response"]
            identity = _id(snapshot["id"])
            if self.response_id is not None and self.response_id != identity:
                raise ValueError("Stream response identity changed")
            self.response_id = identity
            if kind == "response.completed":
                parsed = self.parse(snapshot)
                self._agree(snapshot)
                self.completed = parsed
            return []
        index = _index(value["output_index"])
        if kind in {"response.output_item.added", "response.output_item.done"}:
            item = value["item"]
            if not isinstance(item, dict) or item.get("type") not in {"message", "function_call"}:
                raise ValueError("Unsupported stream item")
            _id(item["id"])
            target = self.items_done if kind.endswith("done") else self.items_added
            self._record(target, index, item)
            return []
        item_id = _id(value["item_id"])
        if kind in {
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        }:
            key = (index, item_id)
            if kind.endswith("done"):
                arguments = value["arguments"]
                if not isinstance(arguments, str):
                    raise ValueError("Invalid completed arguments")
                self._record(self.arguments_done, key, arguments)
            else:
                self._delta(self.arguments, self.arguments_done, key, value["delta"])
            return []
        content_index = _index(value["content_index"])
        key = (index, content_index, item_id)
        if kind in {"response.content_part.added", "response.content_part.done"}:
            part = value["part"]
            if not isinstance(part, dict) or part.get("type") != "output_text":
                raise ValueError("Unsupported stream content")
            self._record(self.parts_done if kind.endswith("done") else self.parts_added, key, part)
            return []
        if kind == "response.output_text.done":
            if not isinstance(value["text"], str):
                raise ValueError("Invalid completed text")
            self._record(self.text_done, key, value["text"])
            return []
        if kind == "response.output_text.delta":
            delta = value["delta"]
            self._delta(self.text, self.text_done, key, delta)
            return [delta] if delta else []
        raise ValueError("Unsupported semantic event")

    @staticmethod
    def _record(target, key, value):
        if key in target:
            raise ValueError("Duplicate completion metadata")
        target[key] = value

    def _delta(self, target, completed, key, delta):
        if key in completed or key[0] in self.items_done or not isinstance(delta, str):
            raise ValueError("Invalid fragment after completion")
        target[key] = target.get(key, "") + delta

    @staticmethod
    def _item(final, index, item_id=None):
        item = final["output"][index]
        if item_id is not None and item["id"] != item_id:
            raise ValueError("Stream item identity changed")
        return item

    def _agree(self, final):
        for source, complete in ((self.items_added, False), (self.items_done, True)):
            for index, observed in source.items():
                item = self._item(final, index, observed["id"])
                fields = ("type", "id", "name", "call_id", "role")
                if complete:
                    fields += ("arguments", "content", "status")
                if any(name in observed and observed[name] != item.get(name) for name in fields):
                    raise ValueError("Completed item differs from final snapshot")
        for source, complete in ((self.parts_added, False), (self.parts_done, True)):
            for (index, content_index, item_id), part in source.items():
                item = self._item(final, index, item_id)
                target = item["content"][content_index]
                fields = ("type", "annotations") + (("text",) if complete else ())
                if any(name in part and part[name] != target.get(name) for name in fields):
                    raise ValueError("Completed content differs from final snapshot")
        for source in (self.text, self.text_done):
            for (index, content_index, item_id), text in source.items():
                item = self._item(final, index, item_id)
                if item["type"] != "message" or item["content"][content_index]["text"] != text:
                    raise ValueError("Final text differs from stream evidence")
        for source in (self.arguments, self.arguments_done):
            for (index, item_id), arguments in source.items():
                item = self._item(final, index, item_id)
                if item["type"] != "function_call" or item["arguments"] != arguments:
                    raise ValueError("Final function arguments differ from stream evidence")

    def finish(self):
        if self.completed is None:
            raise ValueError("No completed Responses snapshot")
        return self.completed
