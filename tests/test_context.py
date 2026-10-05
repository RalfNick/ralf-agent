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
