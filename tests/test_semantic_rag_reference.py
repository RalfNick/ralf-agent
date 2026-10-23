"""Installed-module shape and original RAG state for the semantic reference app."""

import asyncio
import importlib
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from relf_agent.embeddings import HashEmbeddingProvider
from relf_agent.planning_evaluation import EvaluationLimits
from relf_agent.rag_evaluation import OfflineRAGProvider
from relf_agent.rag_evaluation_cases import load_rag_cases


def module():
    assert importlib.util.find_spec("relf_agent.semantic_rag_reference"), (
        "Missing complete semantic reference application"
    )
    return importlib.import_module("relf_agent.semantic_rag_reference")


def test_default_module_cli_not_run_without_model_assets_or_credentials(
    tmp_path, capsys, monkeypatch
):
    app = module()

    def forbidden(*args, **kwargs):
        raise AssertionError("Unconfigured default may not load or download a model")

    monkeypatch.setattr(app, "LocalSentenceEmbeddingProvider", forbidden)
    assert app.main(["--report", str(tmp_path / "report.json")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_run" and report["typed_answers"] is True
    assert report["calls"] == report["embedding_calls"] == 0
    assert report["model_quality"] is report["semantic_quality"] is None


def test_sdk_explicit_embedding_replacement_is_borrowed_and_original_rag(tmp_path):
    app = module()

    class Borrowed(HashEmbeddingProvider):
        closed = False

        async def aclose(self):
            self.closed = True

    embedding = Borrowed()
    report = asyncio.run(
        app.evaluate_semantic_rag(
            OfflineRAGProvider(),
            embedding=embedding,
            cases=load_rag_cases()[:1],
            limits=EvaluationLimits(max_cases=1),
            evidence_dir=tmp_path,
        )
    )
    assert report["passed"] == report["total"] == 1
    assert report["typed_answers"] is True and not embedding.closed
    assert report["cases"][0]["recovery"] == {
        "additional_model_calls": 0,
        "additional_embedding_calls": 0,
    }


def test_missing_local_model_is_explicit_not_run_without_generation_calls(tmp_path):
    app = module()
    report = asyncio.run(app.evaluate_semantic_rag(OfflineRAGProvider(), evidence_dir=tmp_path))
    assert report["status"] == "not_run" and report["reason"] == "local_embedding_not_configured"
    assert report["calls"] == report["embedding_calls"] == 0
    assert list(tmp_path.iterdir()) == []


def test_cli_missing_assets_is_sanitized_and_does_not_dispatch(tmp_path, capsys):
    app = module()
    assert app.main(["--offline", "--model-directory", str(tmp_path)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_run" and report["reason"] == "configuration_invalid"
    assert report["calls"] == 0
    assert str(tmp_path) not in json.dumps(report)


def test_invalid_embedding_cap_rejects_before_generation_construction(
    tmp_path, capsys, monkeypatch
):
    app = module()
    import relf_agent.planning_evaluation_cli as shared

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid cap must reject before constructing a generation client")

    monkeypatch.setattr(shared, "_http_provider", forbidden)
    assert app.main(["--provider", "openai", "--max-embedding-calls", "0"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "configuration_invalid"


def test_owned_incomplete_close_retains_original_resource_for_same_loop_retry(
    tmp_path, monkeypatch
):
    app = module()
    from relf_agent.errors import CloseIncomplete

    originals = []

    class PausedCleanup(HashEmbeddingProvider):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.fail = True
            self.closed = False
            originals.append(self)

        async def aclose(self):
            if self.fail:
                raise CloseIncomplete({"active_calls": 1, "cleanup_complete": False})
            self.closed = True

    monkeypatch.setattr(app, "LocalSentenceEmbeddingProvider", PausedCleanup)

    async def run():
        try:
            await app.evaluate_semantic_rag(
                OfflineRAGProvider(),
                model_directory=tmp_path,
                cases=load_rag_cases()[:1],
                evidence_dir=tmp_path,
            )
        except CloseIncomplete as refusal:
            assert refusal.local_embedding is originals[0]
            assert not refusal.local_embedding.closed
            refusal.local_embedding.fail = False
            await refusal.local_embedding.aclose()
            assert refusal.local_embedding.closed
        else:
            raise AssertionError("Original incomplete owner was lost")
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(run())


@pytest.fixture
def controlled_cpu_owner():
    """Independent model, original provider worker/close methods, actual thread.

    This tests resource ownership, not neural quality or model asset loading.
    """
    app = module()
    from relf_agent.binding_artifacts import _method_binding

    class Values:
        def tolist(self):
            return [[1.0] + [0.0] * 383]

    class Parameter:
        dtype = "torch.float32"

    class Model:
        max_seq_length = 128
        default_prompt_name = None
        prompts = {"query": "", "document": ""}
        device = "cpu"
        training = False

        def __init__(self):
            self.entered, self.release = threading.Event(), threading.Event()

        def parameters(self):
            return iter([Parameter()])

        def encode(self, *args, **kwargs):
            self.entered.set()
            assert self.release.wait(5), "Original CPU worker was not released"
            return Values()

    originals = []

    class Controlled(app.LocalSentenceEmbeddingProvider):
        def __init__(self, *args, **kwargs):
            self._model = self._model_ref = Model()
            self._encode_pin = _method_binding(self._model.encode)
            self._executor = self._executor_ref = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="test-semantic-original"
            )
            self._pending = self._pending_ref = {}
            self._loop = None
            self._closed = self._closing = False
            self._observations = []
            self._definition = self._definition_ref = "{}"
            self._methods = tuple(
                (name, _method_binding(getattr(self, name)))
                for name in ("embed", "_check", "_encode", "aclose")
            )
            originals.append((self, self._model_ref, self._executor_ref))

    yield Controlled, originals
    # RED failures must also release/join every original thread.
    for _, model, executor in originals:
        model.release.set()
        executor.shutdown(wait=True, cancel_futures=False)
    assert not any(t.name.startswith("test-semantic-original") for t in threading.enumerate())


async def wait_for_cpu(predicate):
    for _ in range(2000):
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("Original CPU boundary was not observed")


def test_second_cleanup_cancel_retains_original_cpu_owner(controlled_cpu_owner, monkeypatch):
    app = module()
    import relf_agent.rag_evaluation as original_rag
    from relf_agent.errors import CloseIncomplete

    controlled, originals = controlled_cpu_owner

    async def evaluate(provider=None, **kwargs):
        if provider is None:
            return {"status": "not_run"}
        await kwargs["embedding"].embed(["Original actual worker"])
        return {"status": "completed"}

    monkeypatch.setattr(app, "LocalSentenceEmbeddingProvider", controlled)
    monkeypatch.setattr(original_rag, "evaluate_rag", evaluate)

    async def run():
        task = asyncio.create_task(app.evaluate_semantic_rag(object(), model_directory="unused"))
        await wait_for_cpu(lambda: bool(originals) and originals[0][1].entered.is_set())
        owner, model, executor = originals[0]
        task.cancel()
        await wait_for_cpu(lambda: owner._closing)
        task.cancel()
        try:
            await task
        except BaseException as refusal:
            assert isinstance(refusal, CloseIncomplete), "Cleanup lost the original CPU owner"
            assert refusal.local_embedding is owner and refusal.evaluation_report is None
            assert not owner._closed and owner._model_ref is model
            assert owner._executor_ref is executor
            assert any(not future.done() for future in owner._pending_ref)
            model.release.set()
            await refusal.local_embedding.aclose()
            assert owner._closed and owner._model_ref is None and not owner._pending_ref
        else:
            raise AssertionError("Actual canceled cleanup must expose its retained original owner")
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(run())


def test_inference_drift_refuses_admission_but_drains_original_owner(controlled_cpu_owner):
    from relf_agent.errors import CloseIncomplete, DefinitionMismatch

    controlled, originals = controlled_cpu_owner

    async def run():
        owner = controlled()
        _, model, executor = originals[0]
        task = asyncio.create_task(owner.embed(["Original actual worker"]))
        await wait_for_cpu(model.entered.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        model.max_seq_length = 127
        with pytest.raises(DefinitionMismatch):
            _ = owner.identity
        with pytest.raises(DefinitionMismatch):
            await owner.embed(["Must not run"])
        with pytest.raises(CloseIncomplete):
            await owner.aclose(wait_timeout=0)
        assert owner._model_ref is model and owner._executor_ref is executor
        assert len(owner._pending_ref) == 1 and not owner._closed
        model.release.set()
        await owner.aclose()
        assert owner._closed and owner._model_ref is None and not owner._pending_ref
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(run())


def test_closed_owner_releases_original_model_receiver(controlled_cpu_owner):
    import gc
    import weakref

    controlled, originals = controlled_cpu_owner

    async def run():
        owner = controlled()
        model = owner._model_ref
        reference = weakref.ref(model)
        model.release.set()
        await owner.embed(["Original completed CPU work"])
        await owner.aclose()
        assert owner._closed and not owner._pending_ref
        return owner, reference

    owner, reference = asyncio.run(run())
    # The fixture's audit record intentionally retained the original model.
    # All workers are already joined; release that independent test reference.
    originals.clear()
    gc.collect()
    assert reference() is None, "A retained closed owner still owns the original model weights"
    assert owner._encode_pin is None
