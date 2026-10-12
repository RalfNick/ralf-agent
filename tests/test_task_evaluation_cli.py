import asyncio
import importlib
import importlib.util
import json
import stat

import pytest

from ralf_agent.errors import ProviderError, ValidationError


def command(kind):
    name = f"ralf_agent.{kind}_evaluation_cli"
    assert importlib.util.find_spec(name), f"Missing bounded {kind} task evaluation CLI"
    return importlib.import_module(name)


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_default_cli_is_explicit_not_run_without_credentials(kind, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-discovered")
    cli = command(kind)
    assert cli.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_run" and report["calls"] == 0
    assert report["model_quality"] is None


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_offline_cli_completes_actual_managed_tasks(kind, tmp_path, capsys):
    cli = command(kind)
    report_path = tmp_path / "report.json"
    assert cli.main(["--offline", "--report", str(report_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["total"] > 1 and report["passed"] == report["total"]
    assert report["calls"] > 0 and report["model_quality"] is None
    assert json.loads(report_path.read_text()) == report
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600


def test_team_cli_executes_actual_team_default_combination(capsys):
    cli = command("orchestration")
    assert cli.main(["--offline", "--kind", "team", "--max-cases", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["orchestration_kind"] == "team" and report["passed"] == 1


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_global_call_cap_preserves_failed_repeat_denominator(kind, capsys):
    cli = command(kind)
    assert cli.main(["--offline", "--repeats", "2", "--max-calls", "1"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["calls"] <= 1 and report["passed"] < report["total"]
    assert report["limits"]["repeats"] == 2


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
@pytest.mark.parametrize("existing", ["regular", "symlink", "broken-symlink"])
def test_existing_report_is_rejected_before_provider_construction(
    kind, existing, tmp_path, capsys, monkeypatch
):
    cli = command(kind)
    destination = tmp_path / "report.json"
    target = tmp_path / "private-token-file"
    if existing != "broken-symlink":
        target.write_text("private-credential")
    if existing == "regular":
        destination.write_text("existing-report")
    else:
        destination.symlink_to(target)

    def forbidden(*args):
        raise AssertionError("A report conflict must reject before constructing clients")

    monkeypatch.setattr(cli, "_http_provider", forbidden)
    assert cli.main(["--provider", "openai", "--report", str(destination)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["calls"] == 0 and report["reason"] == "configuration_invalid"
    if existing == "regular":
        assert destination.read_text() == "existing-report"
    elif existing == "symlink":
        assert target.read_text() == "private-credential"
    else:
        assert not target.exists()


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_missing_requested_configuration_returns_sanitized_reason(kind, capsys, monkeypatch):
    cli = command(kind)
    monkeypatch.delenv("TASK_EVAL_NO_SUCH_MODEL", raising=False)
    assert cli.main(["--provider", "openai", "--model-env", "TASK_EVAL_NO_SUCH_MODEL"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_run" and report["reason"] == "model_not_configured"
    assert report["calls"] == 0


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
@pytest.mark.parametrize(
    "options",
    [
        ["--max-calls", "0"],
        ["--timeout", "nan"],
        ["--repeats", "0"],
        ["--input-price-per-million", "1"],
        ["--input-price-per-million", "-1", "--output-price-per-million", "1"],
    ],
)
def test_invalid_limits_and_prices_are_rejected_before_constructing_clients(
    kind, options, capsys, monkeypatch
):
    cli = command(kind)

    def forbidden(*args):
        raise AssertionError("Invalid preflight must not create clients")

    monkeypatch.setattr(cli, "_http_provider", forbidden)
    assert cli.main(["--provider", "openai", *options]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["calls"] == 0 and report["reason"] == "configuration_invalid"


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_partial_client_lifecycle_is_closed_on_configuration_failure(kind, monkeypatch):
    cli = command(kind)
    closed = []

    class Client:
        async def aclose(self):
            closed.append("provider")

    monkeypatch.setattr(cli, "_http_provider", lambda *args: (Client(), None))
    if kind == "rag":

        def fail(*args):
            raise ValidationError("private-key private-url must never be echoed")

        monkeypatch.setattr(cli, "_embedding_provider", fail)
    else:

        async def fail(*args, **kwargs):
            raise ValidationError("private-key private-task")

        monkeypatch.setattr(cli, "evaluate_orchestration", fail)
    with pytest.raises(ValidationError):
        asyncio.run(cli.run(cli.arguments(["--provider", "openai"])))
    assert closed == ["provider"]


def test_rag_uses_only_explicit_embedding_model_endpoint_and_key(monkeypatch):
    cli = command("rag")
    import ralf_agent.embedding_http as embedding_http

    captures, closed = [], []

    class Client:
        async def aclose(self):
            closed.append("provider")

    class Embedding:
        def __init__(self, model, **kwargs):
            captures.append((model, kwargs))

        async def aclose(self):
            closed.append("embedding")

    async def evaluate(provider, **kwargs):
        assert isinstance(kwargs["embedding"], Embedding)
        assert kwargs["max_embedding_calls"] == 17
        return {"status": "completed", "total": 1, "passed": 1}

    monkeypatch.setattr(cli, "_http_provider", lambda *args: (Client(), None))
    monkeypatch.setattr(cli, "evaluate_rag", evaluate)
    monkeypatch.setattr(embedding_http, "OpenAIEmbeddingProvider", Embedding)
    monkeypatch.setenv("GEN_KEY", "generation-secret")
    monkeypatch.setenv("EMBED_KEY", "embedding-secret")
    monkeypatch.setenv("EMBED_MODEL", "specific-embedding")
    monkeypatch.setenv("EMBED_URL", "https://embedding.invalid/v1")
    args = cli.arguments(
        [
            "--provider",
            "openai",
            "--model",
            "generation-only",
            "--key-env",
            "GEN_KEY",
            "--base-url",
            "https://generation.invalid/v1",
            "--embedding-model-env",
            "EMBED_MODEL",
            "--embedding-key-env",
            "EMBED_KEY",
            "--embedding-base-url-env",
            "EMBED_URL",
            "--embedding-dimensions",
            "32",
            "--max-embedding-calls",
            "17",
        ]
    )
    asyncio.run(cli.run(args))
    model, options = captures[0]
    assert model == "specific-embedding" and options["dimensions"] == 32
    assert options["api_key"] == "embedding-secret"
    assert options["base_url"] == "https://embedding.invalid/v1"
    assert closed == ["embedding", "provider"]


def test_rag_live_generation_does_not_infer_embedding_from_generation(monkeypatch):
    cli = command("rag")
    closed = []

    class Client:
        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(cli, "_http_provider", lambda *args: (Client(), None))
    args = cli.arguments(["--provider", "openai", "--model", "generation-only"])
    report = asyncio.run(cli.run(args))
    assert report["status"] == "not_run" and report["reason"] == "embedding_model_not_configured"
    assert report["calls"] == 0 and closed == [True]


def test_rag_without_generation_provider_does_not_construct_embedding(monkeypatch, capsys):
    cli = command("rag")

    def forbidden(*args):
        raise AssertionError("No generation provider means no embedding I/O or client")

    monkeypatch.setattr(cli, "_embedding_provider", forbidden)
    assert cli.main(["--embedding-model", "unused", "--embedding-dimensions", "32"]) == 0
    assert json.loads(capsys.readouterr().out)["calls"] == 0


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_owned_clients_close_on_evaluation_cancellation(kind, monkeypatch):
    cli = command(kind)
    closed = []

    class Client:
        def __init__(self, name):
            self.name = name

        async def aclose(self):
            closed.append(self.name)

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(cli, "_http_provider", lambda *args: (Client("provider"), None))
    monkeypatch.setattr(cli, f"evaluate_{kind}", cancel)
    if kind == "rag":
        monkeypatch.setattr(cli, "_embedding_provider", lambda *args: (Client("embedding"), None))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cli.run(cli.arguments(["--provider", "openai"])))
    assert closed == (["embedding", "provider"] if kind == "rag" else ["provider"])


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_configuration_exception_has_sanitized_json_also_saved_to_report(
    kind, tmp_path, monkeypatch, capsys
):
    cli = command(kind)

    def fail(*args):
        raise ProviderError("secret-key https://private-url.invalid raw-question")

    monkeypatch.setattr(cli, "_http_provider", fail)
    report_path = tmp_path / "report.json"
    assert cli.main(["--provider", "openai", "--report", str(report_path)]) == 2
    encoded = capsys.readouterr().out
    report = json.loads(encoded)
    assert report["reason"] == "configuration_invalid" and report["calls"] == 0
    assert not any(text in encoded for text in ("secret-key", "private-url", "raw-question"))
    assert json.loads(report_path.read_text()) == report


@pytest.mark.parametrize("kind", ["rag", "orchestration"])
def test_provider_and_offline_arguments_are_mutually_exclusive(kind):
    cli = command(kind)
    with pytest.raises(SystemExit) as exc:
        cli.arguments(["--provider", "openai", "--offline"])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "options,reason",
    [
        (["--embedding-model-env", "UNSET_EMBED_MODEL"], "embedding_model_not_configured"),
        (["--embedding-model", "specific"], "embedding_dimensions_not_configured"),
        (
            ["--embedding-model", "specific", "--embedding-dimensions", "16"],
            "embedding_credential_not_configured",
        ),
        (
            [
                "--embedding-model",
                "specific",
                "--embedding-dimensions",
                "16",
                "--embedding-key-env",
                "EMBED_KEY",
                "--embedding-base-url-env",
                "UNSET_EMBED_URL",
            ],
            "embedding_endpoint_not_configured",
        ),
    ],
)
def test_missing_explicit_embedding_configuration_is_not_run(options, reason, monkeypatch):
    cli = command("rag")
    closed = []

    class Client:
        async def aclose(self):
            closed.append(True)

    monkeypatch.delenv("UNSET_EMBED_MODEL", raising=False)
    monkeypatch.delenv("UNSET_EMBED_URL", raising=False)
    monkeypatch.setenv("EMBED_KEY", "separate-key")
    monkeypatch.setattr(cli, "_http_provider", lambda *args: (Client(), None))
    report = asyncio.run(cli.run(cli.arguments(["--provider", "openai", *options])))
    assert report["reason"] == reason and report["calls"] == 0 and closed == [True]


def test_actual_native_http_rag_clients_close_and_separate_credentials(monkeypatch, capsys):
    import httpx

    from ralf_agent.embeddings import HashEmbeddingProvider
    from ralf_agent.rag_evaluation import OfflineRAGProvider

    cli = command("rag")
    native_client = httpx.AsyncClient
    clients, requests = [], []

    async def handle(request):
        body = json.loads(request.content)
        requests.append((request.url.host, request.headers["authorization"], body["model"]))
        if request.url.path.endswith("/embeddings"):
            vectors = await HashEmbeddingProvider(dimensions=16).embed(body["input"])
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "embedding-specific",
                    "data": [
                        {"object": "embedding", "index": index, "embedding": vector}
                        for index, vector in enumerate(vectors)
                    ],
                    "usage": {"prompt_tokens": 10, "total_tokens": 10},
                },
            )
        response = await OfflineRAGProvider().complete(body["messages"], [])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(response.output)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            },
        )

    class RecordedClient(native_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            super().__init__(*args, **kwargs)
            clients.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", RecordedClient)
    monkeypatch.setenv("GENERATION_TEST_KEY", "generation-test-credential")
    monkeypatch.setenv("EMBEDDING_TEST_KEY", "embedding-test-credential")
    assert (
        cli.main(
            [
                "--provider",
                "openai",
                "--model",
                "generation-specific",
                "--base-url",
                "https://generation.invalid/v1",
                "--key-env",
                "GENERATION_TEST_KEY",
                "--embedding-model",
                "embedding-specific",
                "--embedding-dimensions",
                "16",
                "--embedding-base-url",
                "https://embedding.invalid/v1",
                "--embedding-key-env",
                "EMBEDDING_TEST_KEY",
                "--max-cases",
                "1",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] == 1 and report["calls"] == 1
    assert len(clients) == 2 and all(client.is_closed for client in clients)
    assert (
        "generation.invalid",
        "Bearer generation-test-credential",
        "generation-specific",
    ) in requests
    assert (
        "embedding.invalid",
        "Bearer embedding-test-credential",
        "embedding-specific",
    ) in requests
    assert "generation-test-credential" not in json.dumps(report)
    assert "embedding-test-credential" not in json.dumps(report)


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_native_http_orchestration_executes_and_closes_each_tool_continuation(
    kind, monkeypatch, capsys
):
    import httpx

    from ralf_agent.orchestration_evaluation import OfflineOrchestrationProvider

    cli = command("orchestration")
    native_client = httpx.AsyncClient
    clients = []

    async def handle(request):
        body = json.loads(request.content)
        response = await OfflineOrchestrationProvider().complete(body["messages"], body["tools"])
        message = {"role": "assistant", "content": None}
        if response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": f"call-{index}",
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for index, call in enumerate(response.tool_calls)
            ]
        else:
            message["content"] = json.dumps(response.output)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": message,
                        "finish_reason": "tool_calls" if response.tool_calls else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            },
        )

    class RecordedClient(native_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            super().__init__(*args, **kwargs)
            clients.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", RecordedClient)
    monkeypatch.setenv("ORCHESTRATION_TEST_KEY", "local-fixture-key")
    assert (
        cli.main(
            [
                "--provider",
                "openai",
                "--model",
                "fixture-model",
                "--base-url",
                "https://models.invalid/v1",
                "--key-env",
                "ORCHESTRATION_TEST_KEY",
                "--kind",
                kind,
                "--max-cases",
                "1",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] == 1 and report["calls"] == 4
    assert len(clients) == 4 and all(client.is_closed for client in clients)
    assert report["cases"][0]["checks"]["lookup_receipt"]
    assert report["cases"][0]["checks"]["calculator_receipt"]
