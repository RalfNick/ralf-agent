import asyncio
import importlib
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from relf_agent import (
    Document,
    IngestionCoordinator,
    InMemoryKnowledgeStore,
    ParsedDocument,
    Scope,
    SourceDocument,
    SQLiteKnowledgeStore,
)
from relf_agent.errors import DefinitionMismatch, ValidationError


def api():
    module = importlib.import_module("relf_agent")
    assert hasattr(module, "TokenChunker"), "Missing replaceable token chunking"
    return module


def parsed(text):
    return ParsedDocument(Document("source", text), "0" * 64)


def test_byte_tokenizer_preserves_unicode_and_literal_special_tokens():
    tokenizer = api().UTF8ByteTokenizer()
    assert tokenizer.count("中🙂a") == 8
    assert tokenizer.prefix("中🙂a", 6) == "中"
    assert tokenizer.suffix("a中🙂", 6) == "🙂"
    assert tokenizer.prefix("<|endoftext|>", 100) == "<|endoftext|>"


def test_token_chunks_overlap_without_splitting_unicode_or_losing_source():
    chunker = api().TokenChunker(size=7, overlap=3)
    text = "中文🙂abc"
    spans = chunker.split(parsed(text))
    assert [(s.start, s.end) for s in spans] == [(0, 2), (1, 3), (3, 6)]
    assert [text[s.start : s.end] for s in spans] == ["中文", "文🙂", "abc"]


@pytest.mark.parametrize(
    "text,size,overlap,locations",
    [
        ("a🙂🙂", 5, 4, [(0, 2), (2, 3)]),
        ("a中文", 4, 3, [(0, 2), (2, 3)]),
        ("ab🙂🙂", 6, 4, [(0, 3), (3, 4)]),
    ],
)
def test_overlap_shrinks_when_wide_unicode_prevents_new_content(text, size, overlap, locations):
    spans = api().TokenChunker(size=size, overlap=overlap).split(parsed(text))
    assert [(s.start, s.end) for s in spans] == locations


def test_unfittable_unicode_and_excessive_chunk_count_fail():
    with pytest.raises(ValidationError):
        api().TokenChunker(size=2, overlap=0).split(parsed("中"))
    with pytest.raises(ValidationError):
        api().TokenChunker(size=1, overlap=0).split(parsed("x" * 4097))


@pytest.mark.parametrize("value", [True, -1, 0, 100000001])
def test_invalid_chunk_budget_is_rejected(value):
    with pytest.raises(ValidationError):
        api().TokenChunker(size=value, overlap=0)


def test_canonical_message_counter_reserves_output_in_same_units():
    counter = api().TokenizerMessageCounter(output_reserve=10)
    result = counter.count([{"role": "user", "content": "中"}])
    assert result.units == 43  # 33 UTF-8 bytes of canonical JSON + 10 reserved.
    assert result.unit == "canonical/utf8-bytes"
    assert result.estimated is True  # Vendor framing and billing are not measured.


def test_output_reserve_prevents_dispatch_and_managed_factory_supports_it():
    from relf_agent.context_factories import budgeted_context, managed_context

    history = [{"role": "system", "content": "a"}, {"role": "user", "content": "b"}]
    assembler = budgeted_context({"counter": "utf8-bytes", "output_reserve": 20, "max_units": 75})
    with pytest.raises(ValidationError):
        assembler.validate_request(history, 1000)
    managed = managed_context({"counter": "utf8-bytes", "output_reserve": 20, "max_units": 75})
    assert managed.identity["assembler"] == assembler.identity


class BadTokenizer:
    identity = {"kind": "test-tokenizer", "version": "1"}
    unit = "test-tokens"

    def count(self, text):
        return len(text)

    def prefix(self, text, limit):
        return "unrelated"

    def suffix(self, text, limit):
        return text[-limit:]


def test_custom_tokenizer_return_contract_and_identity_are_checked():
    tokenizer = BadTokenizer()
    chunker = api().TokenChunker(tokenizer, size=3, overlap=1)
    with pytest.raises(ValidationError):
        chunker.split(parsed("abcdef"))
    tokenizer.identity = {"kind": "test-tokenizer", "version": "2"}
    with pytest.raises(DefinitionMismatch):
        chunker.split(parsed("abcdef"))


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
@pytest.mark.parametrize(
    "text,size,overlap,expected",
    [
        ("中文🙂abc", 7, 3, ["中文", "文🙂", "abc"]),
        ("a🙂🙂", 5, 4, ["a🙂", "🙂"]),
        ("a中文", 4, 3, ["a中", "文"]),
        ("ab🙂🙂", 6, 4, ["ab🙂", "🙂"]),
    ],
)
def test_atomic_token_ingestion_replays_original_after_pipeline_move(
    tmp_path, backend, text, size, overlap, expected
):
    module = api()
    path = tmp_path / "knowledge.sqlite"
    store = InMemoryKnowledgeStore() if backend == "memory" else SQLiteKnowledgeStore(path)
    source = SourceDocument("source", text.encode())

    def ingest(store, chunker, command="one"):
        return asyncio.run(
            IngestionCoordinator(store, chunker=chunker).ingest(
                Scope(), "docs", source, command_id=command, expected_version=0
            )
        )

    try:
        with pytest.raises(ValidationError):
            ingest(store, module.TokenChunker(size=2, overlap=0))
        assert store.get(Scope(), "docs", "source") is None
        assert store.ingestion_receipt(Scope(), "docs", "one") is None
        original = ingest(store, module.TokenChunker(size=size, overlap=overlap))
        assert [c.text for c in store.chunks(Scope(), "docs", "source")] == expected
        if backend == "sqlite":
            store.close()
            store = SQLiteKnowledgeStore(path)
        assert ingest(store, module.CharacterChunker(size=1, overlap=0)) == original
        assert store.get(Scope(), "docs", "source").version == 1
    finally:
        store.close()


def test_tiktoken_uses_owned_vocabulary_and_literal_special_tokens():
    pytest.importorskip("tiktoken")
    ranks = {bytes([i]): i for i in range(256)}
    ranks[b"ab"] = 256
    tokenizer = api().TiktokenTokenizer(
        name="test-byte-bpe",
        pat_str=r"[\s\S]+",
        mergeable_ranks=ranks,
        special_tokens={"<|endoftext|>": 257},
    )
    assert tokenizer.count("ab中🙂") == 8
    assert tokenizer.prefix("ab中🙂", 4) == "ab中"
    assert tokenizer.suffix("ab中🙂", 4) == "🙂"
    assert tokenizer.count("<|endoftext|>") == 13
    ranks[b"cd"] = 258
    assert tokenizer.count("cd") == 2
    assert tokenizer.prefix("中", 2) == ""
    assert tokenizer.suffix("中", 2) == ""


@pytest.mark.parametrize("mode", ["before", "after"])
def test_token_ingestion_process_loss_rolls_back_or_replays_exact_receipt(tmp_path, mode):
    path = tmp_path / "knowledge.sqlite"
    crashed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.ingestion_crash_fixture",
            "sqlite",
            f"token-{mode}",
            str(path),
            "token-crash",
        ],
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert crashed.returncode == 79 and "crash-window-reached" in crashed.stdout, crashed.stderr
    with SQLiteKnowledgeStore(path) as store:
        scope = Scope("token-crash", "owner")
        previous = store.ingestion_receipt(scope, "docs", "first")
        if mode == "before":
            assert previous is None and store.get(scope, "docs", "guide") is None
            assert store.chunks(scope, "docs", "guide") == []
        receipt = asyncio.run(
            IngestionCoordinator(store, chunker=api().TokenChunker(size=7, overlap=3)).ingest(
                scope,
                "docs",
                SourceDocument("guide", "中文🙂abc".encode()),
                command_id="first",
                expected_version=0,
            )
        )
        assert receipt.document_version == 1
        assert [c.text for c in store.chunks(scope, "docs", "guide")] == ["中文", "文🙂", "abc"]
        if mode == "after":
            assert receipt == previous


@pytest.mark.parametrize("kind", ["bool", "negative", "coroutine", "generator", "contextmanager"])
def test_custom_counter_rejects_lazy_or_invalid_units(kind):
    class Invalid(BadTokenizer):
        def count(self, text):
            if kind == "bool":
                return True
            if kind == "negative":
                return -1
            if kind == "coroutine":

                async def lazy():
                    return 1

                return lazy()
            if kind == "generator":
                return (x for x in ())
            return contextmanager(lambda: iter(()))()

    with pytest.raises(ValidationError):
        api().TokenizerMessageCounter(Invalid()).count([])


def test_tokenizer_swap_is_detected_before_use():
    tokenizer = api().UTF8ByteTokenizer()
    counter = api().TokenizerMessageCounter(tokenizer)
    tokenizer.count = lambda text: 0
    with pytest.raises(DefinitionMismatch):
        counter.count([])


@pytest.mark.parametrize("limit", [True, -1, 100000001])
def test_invalid_reserve_and_slice_limits_fail(limit):
    with pytest.raises(ValidationError):
        api().TokenizerMessageCounter(output_reserve=limit)
    with pytest.raises(ValidationError):
        api().UTF8ByteTokenizer().prefix("text", limit)


def test_invalid_utf8_is_not_silently_repaired():
    with pytest.raises(ValidationError):
        api().UTF8ByteTokenizer().count("\ud800")
    pytest.importorskip("tiktoken")
    tokenizer = api().TiktokenTokenizer(
        name="bytes", pat_str=r"[\s\S]+", mergeable_ranks={bytes([i]): i for i in range(256)}
    )
    with pytest.raises(ValidationError):
        tokenizer.count("\ud800")


def test_native_pattern_cannot_silently_omit_unmatched_text():
    pytest.importorskip("tiktoken")
    tokenizer = api().TiktokenTokenizer(
        name="incomplete-pattern",
        pat_str=r"[a-z]+",
        mergeable_ranks={bytes([i]): i for i in range(256)},
    )
    with pytest.raises(ValidationError):
        tokenizer.count("abc中文")


def test_native_regex_panic_is_a_typed_validation_failure():
    pytest.importorskip("tiktoken")
    tokenizer = api().TiktokenTokenizer(
        name="backtracking-pattern",
        pat_str=r"(a|aa)+(?=b)|[\s\S]",
        mergeable_ranks={bytes([i]): i for i in range(256)},
    )
    with pytest.raises(ValidationError):
        tokenizer.count("a" * 10000 + "c")


def test_native_binding_drift_during_unicode_retry_is_detected(monkeypatch):
    tiktoken = pytest.importorskip("tiktoken")
    original = tiktoken.Encoding.decode_bytes
    calls = []

    def decode(self, tokens):
        value = original(self, tokens)
        calls.append(tokens)
        if len(calls) == 2:
            self._core_bpe = object()
        return value

    monkeypatch.setattr(tiktoken.Encoding, "decode_bytes", decode)
    tokenizer = api().TiktokenTokenizer(
        name="bytes", pat_str=r"[\s\S]+", mergeable_ranks={bytes([i]): i for i in range(256)}
    )
    with pytest.raises(DefinitionMismatch):
        tokenizer.prefix("中", 2)


def test_temporal_token_measurement_is_accepted_once_and_release_checked():
    import copy

    from tests.test_temporal_custom_context import setup

    async def run():
        tokenizer = api().UTF8ByteTokenizer()
        runtime, state, provider = setup(
            api().BudgetedContextAssembler(
                counter=api().TokenizerMessageCounter(tokenizer, output_reserve=32), max_units=500
            )
        )
        action, request = state.next_operation()
        evidence = await runtime.prepare_context(request)
        assert evidence["ok"] and provider.calls == 0
        assert evidence["context_identity"]["measurement"]["unit"] == "canonical/utf8-bytes"
        state.accept_context(action["id"], evidence)
        restored = copy.deepcopy(state)
        action, request = restored.next_operation()
        assert action["kind"] == "model" and request["context"] == evidence
        assert (await runtime.complete_model(request))["ok"] and provider.calls == 1
        tokenizer.identity = {"kind": "replacement", "version": "2"}
        with pytest.raises(DefinitionMismatch):
            runtime.validate_release()

    asyncio.run(run())


def test_temporal_output_reserve_refuses_model_before_dispatch():
    from tests.test_temporal_custom_context import setup

    async def run():
        runtime, state, provider = setup(
            api().BudgetedContextAssembler(
                counter=api().TokenizerMessageCounter(output_reserve=1000), max_units=100
            )
        )
        action, request = state.next_operation()
        evidence = await runtime.prepare_context(request)
        assert evidence == {"ok": False, "code": "validation_error"}
        state.accept_context(action["id"], evidence)
        assert state.state == "failed" and provider.calls == 0

    asyncio.run(run())


def test_local_tokenizer_approval_reopen_preserves_snapshot_and_one_write(tmp_path):
    from relf_agent import (
        AgentSpec,
        LocalEngine,
        ModelResponse,
        SQLiteStore,
        ToolCall,
        ToolRegistry,
        ToolSpec,
    )

    dispatches, writes = [], []

    class Provider:
        identity = {"kind": "token-context-restart", "version": "1"}

        async def complete(self, messages, tools):
            dispatches.append(messages)
            return (
                ModelResponse(output="confirmed")
                if any(m.get("role") == "tool" for m in messages)
                else ModelResponse(tool_calls=(ToolCall("write", {}, "one"),))
            )

    def handler(arguments, context):
        writes.append(context.effect_key)
        return {"confirmed": True}

    def factory():
        tools = ToolRegistry()
        tools.register(
            ToolSpec(
                "write",
                "Write evidence",
                {"type": "object", "additionalProperties": False},
                effect="idempotent_write",
                requires_approval=True,
            ),
            handler,
        )
        return LocalEngine(
            SQLiteStore(tmp_path / "runs.sqlite"),
            providers={"default": Provider()},
            tools=tools,
            context_assembler=api().BudgetedContextAssembler(
                counter=api().TokenizerMessageCounter(output_reserve=32), max_units=2000
            ),
        )

    with factory() as engine:
        handle = engine.submit(
            AgentSpec("answer", "Complete", tools=("write",)), "中文", command_id="one"
        )
        first = asyncio.run(engine.drive(handle.run_id))
        assert first.state == "waiting_approval" and len(dispatches) == 1
        measurement = first.actions[0]["context_manifest"]["measurement"]
        assert measurement["unit"] == "canonical/utf8-bytes" and measurement["units"] <= 2000
    with factory() as engine:
        pending = engine.status(handle.run_id).pending[0]
        engine.approve(handle.run_id, pending["action_id"], pending["digest"], command_id="approve")
        final = asyncio.run(engine.drive(handle.run_id))
        assert final.state == "succeeded" and len(writes) == 1 and len(dispatches) == 2
        assert final.actions[0]["context_manifest"]["measurement"] == measurement
