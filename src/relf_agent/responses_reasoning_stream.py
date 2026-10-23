"""Responses SSE evidence agrees with one complete native reasoning snapshot."""

from .model_protocol import json_object
from .responses_reasoning_codec import MAX_ITEMS, identifier, item, text_part

_CONTENT_FIELDS = {"item_id", "output_index", "content_index"}
_SUMMARY_FIELDS = {"item_id", "output_index", "summary_index"}
_EVENT_FIELDS = {
    "response.created": {"response"},
    "response.in_progress": {"response"},
    "response.completed": {"response"},
    "response.output_item.added": {"output_index", "item"},
    "response.output_item.done": {"output_index", "item"},
    "response.content_part.added": _CONTENT_FIELDS | {"part"},
    "response.content_part.done": _CONTENT_FIELDS | {"part"},
    "response.output_text.delta": _CONTENT_FIELDS | {"delta", "logprobs", "obfuscation"},
    "response.output_text.done": _CONTENT_FIELDS | {"text", "logprobs"},
    "response.function_call_arguments.delta": {"item_id", "output_index", "delta", "obfuscation"},
    "response.function_call_arguments.done": {"item_id", "output_index", "arguments"},
    "response.reasoning_summary_part.added": _SUMMARY_FIELDS | {"part"},
    "response.reasoning_summary_part.done": _SUMMARY_FIELDS | {"part", "status"},
    "response.reasoning_summary_text.delta": _SUMMARY_FIELDS | {"delta", "obfuscation"},
    "response.reasoning_summary_text.done": _SUMMARY_FIELDS | {"text"},
    "response.reasoning_text.delta": _CONTENT_FIELDS | {"delta", "obfuscation"},
    "response.reasoning_text.done": _CONTENT_FIELDS | {"text"},
}


def _index(value):
    if type(value) is not int or not 0 <= value < MAX_ITEMS:
        raise ValueError("Invalid native stream index")
    return value


class ResponsesReasoningStream:
    """Fragments are observations; only a validated complete snapshot is a decision."""

    def __init__(self, parse):
        self.parse = parse
        self.completed, self.response_id = None, None
        self.sequence = -1
        self.created = False
        self.snapshot_items, self.snapshot_latest = [], {}
        self.items_added, self.items_done = {}, {}
        self.parts_added, self.parts_done = {}, {}
        self.summaries_added, self.summaries_done = {}, {}
        self.text, self.text_done = {}, {}
        self.reasoning, self.reasoning_done = {}, {}
        self.summary, self.summary_done = {}, {}
        self.arguments, self.arguments_done = {}, {}
        self.pending_text = []

    @staticmethod
    def _record(target, key, value):
        if key in target:
            raise ValueError("Duplicate native stream metadata")
        target[key] = value

    def _delta(self, target, finished, key, delta, *, parts=None):
        if (
            not isinstance(delta, str)
            or key in finished
            or key[0] in self.items_done
            or parts is not None
            and key in parts
        ):
            raise ValueError("Invalid fragment after native completion")
        target[key] = target.get(key, "") + delta

    def _known_item(self, index, item_id):
        known = self.items_done.get(
            index, self.items_added.get(index, self.snapshot_latest.get(index))
        )
        if known is not None and known["id"] != item_id:
            raise ValueError("Native stream item identity changed")
        return known

    def _observe_snapshot(self, snapshot, kind):
        if not isinstance(snapshot, dict):
            raise ValueError("Invalid native response snapshot")
        expected = "completed" if kind == "response.completed" else "in_progress"
        if (
            "status" in snapshot
            and snapshot["status"] != expected
            or snapshot.get("error") is not None
            or snapshot.get("incomplete_details") is not None
        ):
            raise ValueError("Native response snapshot contains incompatible completion evidence")
        current = identifier(snapshot["id"])
        if self.response_id is not None and self.response_id != current:
            raise ValueError("Native response identity changed")
        self.response_id = current
        if kind == "response.completed" or "output" not in snapshot:
            return
        output = snapshot["output"]
        if not isinstance(output, list) or len(output) > MAX_ITEMS:
            raise ValueError("Native snapshot output must be a bounded list")
        ids = set()
        for index, raw in enumerate(output):
            observed = item(raw, complete=False)
            if observed["id"] in ids:
                raise ValueError("Repeated native snapshot item identity")
            ids.add(observed["id"])
            self._known_item(index, observed["id"])
            self.snapshot_items.append((index, observed))
            self.snapshot_latest[index] = observed

    def feed(self, event, data):
        value = json_object(data)
        kind, sequence = value.get("type"), value.get("sequence_number")
        if self.completed is not None or event is not None and event != kind:
            raise ValueError("Native event after completion or mismatching type")
        if type(sequence) is not int or sequence < 0 or sequence <= self.sequence:
            raise ValueError("Invalid native stream sequence")
        self.sequence = sequence
        if kind in {"response.failed", "response.incomplete", "error"}:
            raise ValueError("Native response failed or was incomplete")
        fields = _EVENT_FIELDS.get(kind)
        if fields is None or set(value) - fields - {"type", "sequence_number"}:
            raise ValueError("Unsupported native semantic event fields")
        if "obfuscation" in value and not isinstance(value["obfuscation"], str):
            raise ValueError("Invalid native stream padding")
        if kind in {"response.created", "response.in_progress", "response.completed"}:
            snapshot = value["response"]
            self._observe_snapshot(snapshot, kind)
            if kind == "response.created":
                if self.created:
                    raise ValueError("Repeated native response creation")
                self.created = True
            if kind == "response.completed":
                parsed = self.parse(snapshot)
                self._agree(snapshot)
                ready = [
                    delta
                    for key, delta in self.pending_text
                    if self._final_item(snapshot, key[0], key[2]).get("phase") != "commentary"
                    and delta
                ]
                self.completed = parsed
                return ready
            return []
        index = _index(value["output_index"])
        done = kind.endswith("done")
        if kind in {"response.output_item.added", "response.output_item.done"}:
            observed = item(value["item"], complete=done)
            self._known_item(index, observed["id"])
            if not done and index in self.items_done:
                raise ValueError("Native item added after completion")
            for source in (self.items_added, self.items_done):
                if any(
                    other != index and old["id"] == observed["id"] for other, old in source.items()
                ):
                    raise ValueError("Repeated native stream item identity")
            self._record(self.items_done if done else self.items_added, index, observed)
            return []
        item_id = identifier(value["item_id"])
        known = self._known_item(index, item_id)
        if index in self.items_done:
            raise ValueError("Native fragment after item completion")
        if kind.startswith("response.function_call_arguments."):
            if known is not None and known["type"] != "function_call":
                raise ValueError("Function fragment belongs to another native item")
            key = (index, item_id)
            if done:
                arguments = value["arguments"]
                if not isinstance(arguments, str):
                    raise ValueError("Invalid completed native arguments")
                self._record(self.arguments_done, key, arguments)
            else:
                self._delta(self.arguments, self.arguments_done, key, value["delta"])
            return []
        summary = kind.startswith("response.reasoning_summary_")
        position = _index(value["summary_index" if summary else "content_index"])
        key = (index, position, item_id)
        if summary and known is not None and known["type"] != "reasoning":
            raise ValueError("Summary fragment belongs to another native item")
        if kind in {
            "response.content_part.added",
            "response.content_part.done",
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_part.done",
        }:
            part = value["part"]
            part_kind = (
                "summary_text" if summary else part.get("type") if isinstance(part, dict) else None
            )
            if part_kind not in {"summary_text", "output_text", "reasoning_text"}:
                raise ValueError("Unsupported native stream content")
            if (
                not summary
                and known is not None
                and (known["type"] == "reasoning") != (part_kind == "reasoning_text")
            ):
                raise ValueError("Content fragment belongs to another native item")
            text_part(part, part_kind)
            if value.get("status") is not None:
                raise ValueError("Incomplete native stream content")
            finished = self.summaries_done if summary else self.parts_done
            if not done and (key in finished or index in self.items_done):
                raise ValueError("Native content added after completion")
            self._record(
                finished if done else self.summaries_added if summary else self.parts_added,
                key,
                part,
            )
            return []
        reasoning = kind.startswith("response.reasoning_text.")
        expected = "reasoning" if summary or reasoning else "message"
        if known is not None and known["type"] != expected:
            raise ValueError("Text fragment belongs to another native item")
        target, finished = (
            (self.summary, self.summary_done)
            if summary
            else (self.reasoning, self.reasoning_done)
            if reasoning
            else (self.text, self.text_done)
        )
        if done:
            if key in (self.summaries_done if summary else self.parts_done):
                raise ValueError("Native text completion after part completion")
            if not isinstance(value["text"], str):
                raise ValueError("Invalid completed native text")
            if not summary and not reasoning and value.get("logprobs", []) != []:
                raise ValueError("Unsupported native text log probabilities")
            self._record(finished, key, value["text"])
            return []
        delta = value["delta"]
        self._delta(
            target, finished, key, delta, parts=self.summaries_done if summary else self.parts_done
        )
        if summary or reasoning:
            return []
        if value.get("logprobs", []) != []:
            raise ValueError("Unsupported native text log probabilities")
        if self.pending_text or known is None or "phase" not in known:
            self.pending_text.append((key, delta))
            return []
        return [delta] if delta and known.get("phase") != "commentary" else []

    @staticmethod
    def _final_item(final, index, item_id=None):
        native = final["output"][index]
        if item_id is not None and native["id"] != item_id:
            raise ValueError("Final native item identity changed")
        return native

    def _part(self, final, key, *, summary=False):
        index, position, item_id = key
        native = self._final_item(final, index, item_id)
        return native["summary" if summary else "content"][position]

    def _agree(self, final):
        for index, observed in self.items_done.items():
            if observed != self._final_item(final, index, observed["id"]):
                raise ValueError("Completed native item differs from final snapshot")
        for index, observed in (*self.snapshot_items, *self.items_added.items()):
            native = self._final_item(final, index, observed["id"])
            mutable = {"status", "encrypted_content", "arguments", "content", "summary"}
            if any(observed[field] != native.get(field) for field in observed.keys() - mutable):
                raise ValueError("Added native item identity differs from final snapshot")
            if "arguments" in observed and not native["arguments"].startswith(
                observed["arguments"]
            ):
                raise ValueError("Added native arguments differ from final snapshot")
            for field in ("content", "summary"):
                for position, part in enumerate(observed.get(field) or []):
                    target = native[field][position]
                    if any(
                        part[name] != target.get(name) for name in part.keys() - {"text"}
                    ) or not target["text"].startswith(part["text"]):
                        raise ValueError("Added native content differs from final snapshot")
        for added, finished, summary in (
            (self.parts_added, self.parts_done, False),
            (self.summaries_added, self.summaries_done, True),
        ):
            for key, observed in finished.items():
                if observed != self._part(final, key, summary=summary):
                    raise ValueError("Completed native content differs from final snapshot")
            for key, observed in added.items():
                target = self._part(final, key, summary=summary)
                if any(
                    observed[field] != target.get(field) for field in observed.keys() - {"text"}
                ) or not target["text"].startswith(observed["text"]):
                    raise ValueError("Added native content differs from final snapshot")
        for source, expected, field in (
            (self.text, "message", "content"),
            (self.text_done, "message", "content"),
            (self.reasoning, "reasoning", "content"),
            (self.reasoning_done, "reasoning", "content"),
            (self.summary, "reasoning", "summary"),
            (self.summary_done, "reasoning", "summary"),
        ):
            for (index, position, item_id), observed in source.items():
                native = self._final_item(final, index, item_id)
                expected_part = (
                    "output_text"
                    if expected == "message"
                    else "summary_text"
                    if field == "summary"
                    else "reasoning_text"
                )
                part = native[field][position]
                if (
                    native["type"] != expected
                    or part["type"] != expected_part
                    or part["text"] != observed
                ):
                    raise ValueError("Final native text differs from stream evidence")
        for source in (self.arguments, self.arguments_done):
            for (index, item_id), observed in source.items():
                native = self._final_item(final, index, item_id)
                if native["type"] != "function_call" or native["arguments"] != observed:
                    raise ValueError("Final native arguments differ from stream evidence")

    def finish(self):
        if self.completed is None:
            raise ValueError("No complete native Responses snapshot")
        return self.completed
