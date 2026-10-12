"""The four CLIs opt in explicitly and reject options before credentials or clients."""

import hashlib
import importlib
import json
import os

import httpx
import pytest

NAMES = [
    "model_check_cli",
    "planning_evaluation_cli",
    "rag_evaluation_cli",
    "orchestration_evaluation_cli",
]


def cli(name):
    return importlib.import_module("ralf_agent." + name)


def selection(name, provider="openai-responses-reasoning"):
    return ["--adapter" if name == "model_check_cli" else "--provider", provider]


@pytest.mark.parametrize("name", NAMES)
def test_selected_responses_without_credentials_is_zero_call_not_run(name, monkeypatch, capsys):
    monkeypatch.delenv("RESPONSES_MISSING_FIXTURE_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Missing credentials cannot create HTTP clients")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    key_arg = "--api-key-env" if name == "model_check_cli" else "--key-env"
    assert (
        cli(name).main(
            [
                *selection(name),
                "--model",
                "explicit-fixture-model",
                key_arg,
                "RESPONSES_MISSING_FIXTURE_KEY",
            ]
        )
        == 2
    )
    report = json.loads(capsys.readouterr().out)
    assert report.get("calls", 0) == 0
    if name == "model_check_cli":
        assert report["error"]["code"] == "validation_error"
    else:
        assert report["status"] == "not_run"
        assert report["reason"] == "credential_not_configured"
        assert report["requested_provider"] == "openai-responses-reasoning"


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "option,value",
    [("effort", "medium"), ("context", "all_turns"), ("summary", "detailed"), ("mode", "pro")],
)
def test_unrelated_reasoning_configuration_rejects_before_credential_lookup(
    name, option, value, monkeypatch, capsys
):
    consulted = []
    original = os.environ.get

    def watched(key, *args):
        if key == "REASONING_FORBIDDEN_KEY":
            consulted.append(key)
        return original(key, *args)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unrelated reasoning options must fail before HTTP clients")

    monkeypatch.setattr(os.environ, "get", watched)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    key_arg = "--api-key-env" if name == "model_check_cli" else "--key-env"
    assert (
        cli(name).main(
            [
                "--model",
                "fixture",
                key_arg,
                "REASONING_FORBIDDEN_KEY",
                "--reasoning-" + option,
                value,
            ]
        )
        == 2
    )
    assert consulted == []
    assert json.loads(capsys.readouterr().out).get("calls", 0) == 0


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "option,value",
    [
        ("effort", "none"),
        ("effort", "minimal"),
        ("effort", "medium"),
        ("effort", "xhigh"),
        ("context", "auto"),
        ("summary", "auto"),
        ("mode", "standard"),
    ],
)
def test_deepseek_keeps_its_effort_subset_and_rejects_responses_only_options(
    name, option, value, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid DeepSeek options cannot create HTTP clients")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    assert (
        cli(name).main(
            [
                *selection(name, "deepseek-thinking"),
                "--model",
                "fixture",
                "--reasoning-" + option,
                value,
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out).get("calls", 0) == 0


@pytest.mark.parametrize("name", NAMES)
def test_offline_reasoning_options_are_rejected_before_fixture_or_clients(
    name, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline reasoning options must be rejected before provider creation")

    module = cli(name)
    if name == "planning_evaluation_cli":
        monkeypatch.setattr(module, "_fixture", forbidden)
        source = ["--fixture", "missing-fixture.json"]
    else:
        source = ["--offline"]
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    assert module.main([*source, "--reasoning-summary", "concise"]) == 2
    assert json.loads(capsys.readouterr().out).get("calls", 0) == 0


@pytest.mark.parametrize("name", NAMES)
def test_default_cli_output_preserves_dev90_bytes(name, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "UNREQUESTED_PRIVATE_FIXTURE")
    assert cli(name).main([]) == 0
    encoded = capsys.readouterr().out
    expected = {
        "model_check_cli": "baa387effa95489cc0f14cedcea15931eccc1a648fa02598c347e2f1f9d5b746",
        "planning_evaluation_cli": "ef0eb0e1d83876af2353aa57b8d9c4d58285ebb75326a5a8f5e2122035c33305",
        "rag_evaluation_cli": "b44d328be5e33b960700723666e0a1a978acc3626d682c597a72e011b7c253e2",
        "orchestration_evaluation_cli": "5dc8c94f4730b177c19649faa791096eab95349589ca865f84ec02819de04881",
    }
    assert hashlib.sha256(encoded.encode()).hexdigest() == expected[name]


@pytest.mark.parametrize("source", [[], ["--offline"], ["--adapter", "openai-responses"]])
def test_model_check_legacy_unrelated_effort_error_preserves_dev90_bytes(source, capsys):
    assert cli("model_check_cli").main([*source, "--reasoning-effort", "max"]) == 2
    assert (
        capsys.readouterr().out
        == '{"error": {"code": "validation_error", "message": "Reasoning effort requires explicit deepseek-thinking selection"}}\n'
    )


def plain_messages(items):
    messages = []
    for item in items:
        if item.get("type") == "function_call_output":
            messages.append(
                {"role": "tool", "content": item["output"], "tool_call_id": item["call_id"]}
            )
        elif "role" in item:
            content = item["content"]
            if isinstance(content, list):
                content = "".join(part["text"] for part in content)
            messages.append({"role": item["role"], "content": content})
    return messages


@pytest.mark.parametrize("name", NAMES)
def test_responses_cli_runs_managed_evaluation_and_replays_native_reasoning(
    name, tmp_path, monkeypatch, capsys
):
    from ralf_agent.embeddings import HashEmbeddingProvider
    from ralf_agent.orchestration_evaluation import OfflineOrchestrationProvider
    from ralf_agent.rag_evaluation import OfflineRAGProvider
    from tests.test_planning_evaluation import proposal

    native_client = httpx.AsyncClient
    requests, clients = [], []

    async def handle(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            vectors = await HashEmbeddingProvider(dimensions=16).embed(body["input"])
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "explicit-embedding",
                    "data": [
                        {"object": "embedding", "index": i, "embedding": vector}
                        for i, vector in enumerate(vectors)
                    ],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        requests.append(body)
        assert request.url.path.endswith("/responses")
        assert body["model"] == "explicit-fixture-model"
        assert body["reasoning"] == {
            "effort": "xhigh",
            "context": "all_turns",
            "summary": "detailed",
            "mode": "pro",
        }
        assert body["store"] is False and body["include"] == ["reasoning.encrypted_content"]
        messages = plain_messages(body["input"])
        if name == "planning_evaluation_cli":
            output, calls = proposal(), ()
        elif name == "rag_evaluation_cli":
            response = await OfflineRAGProvider().complete(messages, [])
            output, calls = response.output, response.tool_calls
        elif name == "orchestration_evaluation_cli":
            tools = [
                {
                    "type": "function",
                    "function": {key: value for key, value in item.items() if key != "type"},
                }
                for item in body.get("tools", [])
            ]
            response = await OfflineOrchestrationProvider().complete(messages, tools)
            output, calls = response.output, response.tool_calls
        elif not any(item.get("type") == "function_call_output" for item in body["input"]):
            from ralf_agent import ToolCall

            output, calls = (
                None,
                (ToolCall("ralf_model_echo", {"value": "RALF_TOOL_CHECK"}, "native-echo"),),
            )
        else:
            output, calls = {"ok": True}, ()
        native = [
            {
                "id": "rs-" + str(len(requests)),
                "type": "reasoning",
                "summary": [],
                "encrypted_content": "PRIVATE_ENCRYPTED_FIXTURE",
            }
        ]
        native.extend(
            {
                "id": "fc-" + str(i),
                "type": "function_call",
                "status": "completed",
                "call_id": call.call_id or f"native-{i}",
                "name": call.name,
                "arguments": json.dumps(call.arguments),
            }
            for i, call in enumerate(calls)
        )
        if output is not None:
            native.append(
                {
                    "id": "msg-" + str(len(requests)),
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "phase": "final_answer",
                    "content": [
                        {"type": "output_text", "text": json.dumps(output), "annotations": []}
                    ],
                }
            )
        return httpx.Response(
            200,
            json={
                "id": "resp-" + str(len(requests)),
                "status": "completed",
                "output": native,
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 10,
                    "total_tokens": 30,
                    "output_tokens_details": {"reasoning_tokens": 4},
                },
            },
        )

    class RecordedClient(native_client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **{**kwargs, "transport": httpx.MockTransport(handle)})
            clients.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", RecordedClient)
    monkeypatch.setenv("RESPONSES_ASSEMBLY_KEY", "PRIVATE_RESPONSES_CREDENTIAL")
    monkeypatch.setenv("RESPONSES_EMBEDDING_KEY", "PRIVATE_EMBEDDING_CREDENTIAL")
    options = [
        *selection(name),
        "--model",
        "explicit-fixture-model",
        "--reasoning-effort",
        "xhigh",
        "--reasoning-context",
        "all_turns",
        "--reasoning-summary",
        "detailed",
        "--reasoning-mode",
        "pro",
        "--evidence-dir",
        str(tmp_path / "evidence"),
    ]
    if name == "model_check_cli":
        options += ["--api-key-env", "RESPONSES_ASSEMBLY_KEY", "--cases", "tool"]
    else:
        options += ["--key-env", "RESPONSES_ASSEMBLY_KEY", "--max-cases", "1"]
    if name == "rag_evaluation_cli":
        options += [
            "--embedding-model",
            "explicit-embedding",
            "--embedding-dimensions",
            "16",
            "--embedding-key-env",
            "RESPONSES_EMBEDDING_KEY",
        ]
    assert cli(name).main(options) == 0
    encoded = capsys.readouterr().out
    report = json.loads(encoded)
    assert report["passed"] == report["total"] == 1
    assert requests and clients and all(client.is_closed for client in clients)
    assert "PRIVATE_RESPONSES_CREDENTIAL" not in encoded
    assert "PRIVATE_EMBEDDING_CREDENTIAL" not in encoded
    assert "PRIVATE_ENCRYPTED_FIXTURE" not in encoded
    if name in {"model_check_cli", "orchestration_evaluation_cli"}:
        assert any(
            item.get("encrypted_content") == "PRIVATE_ENCRYPTED_FIXTURE"
            for request in requests[1:]
            for item in request["input"]
        )
