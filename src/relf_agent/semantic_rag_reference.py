"""An explicit local semantic RAG reference app using original SDK authority.

Model assets and generation configuration are supplied by the host. The default
module performs no requests or model loads; it reports not_run.
"""

import asyncio
import copy
import hashlib
import importlib.metadata
import json
import math
import platform
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .binding_artifacts import _method_binding, _same_binding
from .errors import CloseIncomplete, DefinitionMismatch, RuntimeClosed, ValidationError
from .types import canonical, digest
from .vector import _vector

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
ASSET_MANIFEST = {
    "assets": {
        "1_Pooling/config.json": {
            "bytes": 190,
            "sha256": "4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23",
        },
        "config.json": {
            "bytes": 645,
            "sha256": "6300193cb75e01cf80c96decef7187dfb33094d97cc1490b7ead6ff134476e4e",
        },
        "config_sentence_transformers.json": {
            "bytes": 122,
            "sha256": "b8c64b5cece00d8424b4896ea75b512b6008576088497609dfeb6bd63e6d36b8",
        },
        "model.safetensors": {
            "bytes": 470641600,
            "sha256": "eaa086f0ffee582aeb45b36e34cdd1fe2d6de2bef61f8a559a1bbc9bd955917b",
        },
        "modules.json": {
            "bytes": 229,
            "sha256": "8f4b264b80206c830bebbdcae377e137925650a433b689343a63bdc9b3145460",
        },
        "sentence_bert_config.json": {
            "bytes": 53,
            "sha256": "70f4448f31320443fe3557cacea5abf2dcc4915dda8c80646bec9f3bb0aa5a1f",
        },
        "sentencepiece.bpe.model": {
            "bytes": 5069051,
            "sha256": "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
        },
        "special_tokens_map.json": {
            "bytes": 239,
            "sha256": "378eb3bf733eb16e65792d7e3fda5b8a4631387ca04d2015199c4d4f22ae554d",
        },
        "tokenizer.json": {
            "bytes": 9081518,
            "sha256": "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8",
        },
        "tokenizer_config.json": {
            "bytes": 526,
            "sha256": "5036ea374ffedd706e3bef33e2e0d6953cb868ef8a490e76e32ba0faa37a6b9b",
        },
        "unigram.json": {
            "bytes": 14763234,
            "sha256": "71b44701d7efd054205115acfa6ef126c5d2f84bd3affe0c59e48163674d19a6",
        },
    },
    "config": {
        "batch_size": 8,
        "device": "cpu",
        "dimensions": 384,
        "max_seq_length": 128,
        "normalize_embeddings": True,
        "pooling": "mean_tokens",
        "precision": "float32",
        "query_prefix": None,
        "torch_num_threads": 1,
    },
    "download_cli": "huggingface-hub1.33.0",
    "model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "model_card": "https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "no_authentication": True,
    "remote_code": False,
    "revision": "e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
    "safe_weights": "model.safetensors",
}


def _hash(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


class LocalSentenceEmbeddingProvider:
    """One CPU model/worker with pinned local assets and shielded actual work.

    Only local safetensors, with no query prefix, fixture oracle or downloaded code.
    128-token truncation belongs to the selected model. Input/count bounds limit
    local requests, not general semantic quality. Host owns aclose on same loop.
    """

    def __init__(self, model_directory, *, revision=REVISION, asset_manifest=None):
        if type(revision) is not str or revision != REVISION:
            raise ValidationError("Select the pinned local semantic model revision")
        if not isinstance(model_directory, (str, Path)):
            raise ValidationError("Local semantic model requires an explicit directory")
        directory = Path(model_directory).resolve()
        manifest = copy.deepcopy(ASSET_MANIFEST)
        if asset_manifest is not None:
            if not isinstance(asset_manifest, (str, Path)):
                raise ValidationError("Local semantic manifest requires an explicit file")
            try:
                declared = json.loads(Path(asset_manifest).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise ValidationError("Local semantic manifest is unavailable or invalid") from None
            if type(declared) is not dict or any(
                canonical(declared.get(key)) != canonical(manifest[key])
                for key in ("model", "revision", "assets", "config")
            ):
                raise DefinitionMismatch("Local semantic declared assets/configuration changed")
        for name, expected in manifest["assets"].items():
            path = directory / name
            try:
                valid = (
                    not path.is_symlink()
                    and path.stat().st_size == expected["bytes"]
                    and _hash(path) == expected["sha256"]
                )
            except OSError:
                valid = False
            if not valid:
                raise DefinitionMismatch("Local semantic original asset unavailable or changed")
        modules = json.loads((directory / "modules.json").read_text())
        if [(v["path"], v["type"]) for v in modules] != [
            ("", "sentence_transformers.models.Transformer"),
            ("1_Pooling", "sentence_transformers.models.Pooling"),
        ]:
            raise DefinitionMismatch("Local semantic module selection changed")
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ValidationError(
                "Install the documented local semantic dependencies explicitly"
            ) from None

        torch.set_num_threads(1)
        self._model = self._model_ref = SentenceTransformer(
            str(directory),
            device="cpu",
            trust_remote_code=False,
            local_files_only=True,
            token=False,
            backend="torch",
            model_kwargs={"use_safetensors": True, "dtype": torch.float32},
        )
        if (
            self._model.get_embedding_dimension() != 384
            or self._model.max_seq_length != 128
            or self._model.default_prompt_name is not None
            or self._model.prompts != {"query": "", "document": ""}
        ):
            raise DefinitionMismatch("Local semantic loaded configuration changed")
        self._model.eval()
        self._encode_pin = _method_binding(self._model.encode)
        self._executor = self._executor_ref = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ralf-local-semantic"
        )
        self._pending = self._pending_ref = {}
        self._loop = None
        self._closed = self._closing = False
        self._observations = []
        self._definition = canonical(
            {
                "kind": "local-sentence-transformer",
                "version": "1",
                "model": MODEL,
                "revision": REVISION,
                "dimensions": 384,
                "manifest_sha256": digest(manifest),
                "assets_sha256": digest(manifest["assets"]),
                "configuration": manifest["config"],
                "max_text_chars": 64000,
                "max_batch_items": 16,
                "libraries": {
                    name: importlib.metadata.version(name)
                    for name in (
                        "sentence-transformers",
                        "transformers",
                        "torch",
                        "numpy",
                        "safetensors",
                        "huggingface-hub",
                    )
                },
                "python": platform.python_version(),
            }
        )
        self._definition_ref = self._definition
        self._methods = tuple(
            (name, _method_binding(getattr(self, name)))
            for name in ("embed", "_check", "_encode", "aclose")
        )

    @property
    def dimensions(self):
        return 384

    @property
    def identity(self):
        self._check()
        return json.loads(self._definition_ref)

    @property
    def observations(self):
        return copy.deepcopy(self._observations)

    def _check(self, *, closing=False):
        if self._closed:
            raise RuntimeClosed("Local semantic model is closed")
        if self._closing and not closing:
            raise RuntimeClosed("Local semantic model is closing")
        if (
            self._definition != self._definition_ref
            or self._model is not self._model_ref
            or self._executor is not self._executor_ref
            or self._pending is not self._pending_ref
            or not _same_binding(_method_binding(self._model_ref.encode), self._encode_pin)
            or any(
                not _same_binding(_method_binding(getattr(self, name)), pin)
                for name, pin in self._methods
            )
        ):
            raise DefinitionMismatch("Local semantic original resource/method changed")
        if (
            self._model_ref.max_seq_length != 128
            or self._model_ref.default_prompt_name is not None
            or self._model_ref.prompts != {"query": "", "document": ""}
            or str(self._model_ref.device) != "cpu"
            or str(next(self._model_ref.parameters()).dtype) != "torch.float32"
            or self._model_ref.training
        ):
            raise DefinitionMismatch("Local semantic original inference selection changed")

    def _encode(self, texts):
        started = time.perf_counter()
        values = self._model_ref.encode(
            list(texts),
            prompt_name=None,
            prompt=None,
            batch_size=8,
            show_progress_bar=False,
            precision="float32",
            convert_to_numpy=True,
            convert_to_tensor=False,
            device="cpu",
            normalize_embeddings=True,
        ).tolist()
        if type(values) is not list or len(values) != len(texts):
            raise ValidationError("Local semantic result cardinality differs")
        result = [list(_vector(value, 384)) for value in values]
        self._observations.append(
            {
                "input_count": len(texts),
                "input_sha256": digest(list(texts)),
                "vector_sha256": digest(result),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
        return result

    async def embed(self, texts):
        LocalSentenceEmbeddingProvider._check(self)
        if (
            type(texts) is not list
            or len(texts) > 16
            or any(type(v) is not str or len(v) > 64000 for v in texts)
        ):
            raise ValidationError("Local semantic input exceeds bounded native text batch")
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise ValidationError("Local semantic original worker belongs to another loop")
        self._loop = loop
        original = self._executor_ref.submit(self._encode, tuple(texts))
        future = asyncio.wrap_future(original)
        self._pending_ref[original] = future

        def finished(value):
            self._pending_ref.pop(original, None)
            if not value.cancelled():
                value.exception()

        future.add_done_callback(finished)
        result = await asyncio.shield(future)
        LocalSentenceEmbeddingProvider._check(self)
        return copy.deepcopy(result)

    async def aclose(self, *, wait_timeout=30):
        if (
            type(wait_timeout) not in (int, float)
            or not math.isfinite(wait_timeout)
            or not 0 <= wait_timeout <= 300
        ):
            raise ValidationError("Local semantic close requires bounded finite seconds")
        if self._closed:
            return
        if self._loop is not None and asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Local semantic cleanup requires original loop")
        # Cleanup uses original resource owners even when inference selection
        # has drifted. Admission remains fail-closed in identity/embed.
        original_executor, original_pending = self._executor_ref, self._pending_ref
        self._closing = True
        futures = tuple(original_pending.values())
        if futures:
            _, pending = await asyncio.wait(futures, timeout=wait_timeout)
            if pending:
                raise CloseIncomplete({"active_calls": len(pending), "cleanup_complete": False})
        original_executor.shutdown(wait=True, cancel_futures=False)
        original_pending.clear()
        self._model = self._model_ref = None
        # The pinned encode receiver also owns the model weights. Retain it
        # through incomplete cleanup, then release it after the worker joins.
        self._encode_pin = None
        self._closed = True


async def evaluate_semantic_rag(
    provider=None,
    *,
    model_directory=None,
    asset_manifest=None,
    revision=REVISION,
    embedding=None,
    cases=None,
    limits=None,
    evidence_dir=None,
    typed_answers=True,
    prices=None,
    max_embedding_calls=128,
    model_continuation=False,
):
    """Run the original ingestion/retrieval/Agent/scorer with explicit components.

    Generation and explicitly injected embeddings are borrowed. This application
    owns only the local CPU provider it constructs, then drains that original
    worker on the same loop. A missing selection never starts a download or model.
    The fixture scorer and its strict answer comparison remain unchanged.
    """
    from .rag_evaluation import evaluate_rag

    # Delegate common preflight and packaged case selection before allocating
    # local models/resources. The original no-provider path performs no requests.
    options = dict(
        cases=cases,
        limits=limits,
        evidence_dir=evidence_dir,
        typed_answers=typed_answers,
        prices=prices,
        max_embedding_calls=max_embedding_calls,
        model_continuation=model_continuation,
    )
    absent = await evaluate_rag(None, **options)
    if provider is None:
        return absent
    if embedding is not None:
        if model_directory is not None or asset_manifest is not None:
            raise ValidationError("Select injected embedding or an owned local model")
        return await evaluate_rag(provider, embedding=embedding, **options)
    if model_directory is None:
        absent["reason"] = "local_embedding_not_configured"
        return absent
    local = LocalSentenceEmbeddingProvider(
        model_directory, revision=revision, asset_manifest=asset_manifest
    )
    close_original = local.aclose
    report = None
    try:
        report = await evaluate_rag(provider, embedding=local, **options)
        return report
    finally:
        try:
            await close_original()
        except asyncio.CancelledError as cancellation:
            refusal = CloseIncomplete({"cleanup_complete": False, "cleanup_cancelled": True})
            refusal.local_embedding = local
            refusal.evaluation_report = report
            raise refusal from cancellation
        except CloseIncomplete as refusal:
            # Original resource retention, not an execution receipt or retry.
            refusal.local_embedding = local
            refusal.evaluation_report = report
            raise


def arguments(argv):
    import argparse

    from .orchestration_evaluation_cli import _common_arguments

    parser = argparse.ArgumentParser(description=__doc__)
    _common_arguments(parser, max_cases=8)
    parser.add_argument(
        "--model-directory",
        help="Explicit downloaded local model directory; never downloaded automatically",
    )
    parser.add_argument("--asset-manifest", help="Optional original pinned asset/config JSON")
    parser.add_argument("--embedding-revision", default=REVISION)
    parser.add_argument("--max-embedding-calls", type=int, default=128)
    parser.add_argument(
        "--typed-answers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Native JSON quantity/object answer instructions; default on in this reference app",
    )
    return parser.parse_args(argv)


async def run(args):
    from contextlib import AsyncExitStack

    from .orchestration_evaluation_cli import _configuration, _own_client
    from .planning_evaluation_cli import _http_provider
    from .rag_evaluation import OfflineRAGProvider
    from .rag_evaluation_cases import load_rag_cases

    limits, prices = _configuration(args)
    cases = load_rag_cases(args.cases)
    if type(args.embedding_revision) is not str or args.embedding_revision != REVISION:
        raise ValidationError("Select the pinned local semantic model revision")
    await evaluate_semantic_rag(
        limits=limits,
        cases=cases,
        typed_answers=args.typed_answers,
        max_embedding_calls=args.max_embedding_calls,
    )
    async with AsyncExitStack() as owned:
        provider = reason = None
        if args.offline:
            provider = OfflineRAGProvider()
        elif args.provider:
            provider, reason = _http_provider(args, limits)
            if provider is not None:
                _own_client(owned, provider)
        try:
            report = await evaluate_semantic_rag(
                provider if reason is None else None,
                model_directory=args.model_directory,
                asset_manifest=args.asset_manifest,
                revision=args.embedding_revision,
                cases=cases,
                limits=limits,
                evidence_dir=args.evidence_dir,
                typed_answers=args.typed_answers,
                prices=prices,
                max_embedding_calls=args.max_embedding_calls,
                model_continuation=args.provider
                in {"gemini-functions", "deepseek-thinking", "openai-responses-reasoning"},
            )
        except DefinitionMismatch:
            raise ValidationError("Configured local semantic assets or selection changed") from None
        if reason:
            report["reason"] = reason
            report["requested_provider"] = args.provider
        return report


def main(argv=None):
    from .orchestration_evaluation_cli import _main

    return _main(arguments(argv), run)


if __name__ == "__main__":
    raise SystemExit(main())
