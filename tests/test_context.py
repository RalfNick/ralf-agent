import pytest

from ralf_agent.context import ContextAssembler
from ralf_agent.errors import ValidationError


def test_trimming_preserves_task_and_complete_tool_groups():
    history = [
        {"role": "system", "content": "Keep the service safe"},
        {"role": "user", "content": "Fix INC-1"},
        {"role": "assistant", "content": "old" * 100},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"ok":true}'},
    ]
    messages, manifest = ContextAssembler().assemble(history, [], 500)
    assert messages[:2] == history[:2]
    assert messages[-2:] == history[-2:]
    assert manifest["dropped_groups"] == 1


def test_oversized_latest_evidence_is_rejected_instead_of_silently_truncated():
    with pytest.raises(ValidationError):
        ContextAssembler().assemble(
            [
                {"role": "system", "content": "x"},
                {"role": "user", "content": "y"},
                {"role": "tool", "tool_call_id": "c", "content": "z" * 1000},
            ],
            [],
            256,
        )


def test_optional_memory_is_selected_by_budget_with_an_accurate_manifest():
    history = [{"role": "system", "content": "x"}, {"role": "user", "content": "hello"}]
    references = [
        {"key": "large", "version": 1, "value": "z" * 1000},
        {"key": "language", "version": 2, "value": "Chinese"},
    ]
    messages, manifest = ContextAssembler().assemble(history, references, 512)
    assert "Chinese" in messages[-1]["content"]
    assert "z" * 1000 not in messages[-1]["content"]
    assert manifest["reference_versions"] == [{"key": "language", "version": 2}]
    assert manifest["dropped_references"] == 1


def test_old_memory_cannot_displace_latest_tool_evidence():
    history = [
        {"role": "system", "content": "x"},
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "c", "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "c", "content": "confirmed effect"},
    ]
    messages, manifest = ContextAssembler().assemble(
        history, [{"key": "old", "value": "z" * 1000}], 512
    )
    assert messages[-2:] == history[-2:]
    assert manifest["reference_versions"] == []
