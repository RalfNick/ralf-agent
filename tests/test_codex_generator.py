import importlib.util
import json
from pathlib import Path

import pytest


def generator():
    spec = importlib.util.spec_from_file_location(
        "codex_generator", Path(__file__).parents[1] / "tools/generate_codex_protocol.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_semantic_pin_accepts_key_order_but_rejects_schema_change(tmp_path):
    module = generator()
    value = {"b": [1, 2], "a": {"type": "object"}}
    expected = module.semantic_digest(value)
    source = tmp_path / "Schema.json"
    source.write_text(json.dumps(value, sort_keys=True, indent=4))
    assert module.read_reviewed(source, expected) == value
    source.write_text(json.dumps({"a": {"type": "string"}, "b": [1, 2]}))
    with pytest.raises(ValueError, match="reviewed"):
        module.read_reviewed(source, expected)
    source.write_text(json.dumps({"a": value["a"], "b": [2, 1]}))
    with pytest.raises(ValueError):
        module.read_reviewed(source, expected)


@pytest.mark.parametrize("wire", ['{"a":1,"a":1}', '{"a":NaN}', '{"a":1e999}'])
def test_schema_input_rejects_ambiguous_or_nonfinite_json(tmp_path, wire):
    module = generator()
    path = tmp_path / "Schema.json"
    path.write_text(wire)
    with pytest.raises(ValueError):
        module.read_reviewed(path, "not-a-reviewed-digest")
