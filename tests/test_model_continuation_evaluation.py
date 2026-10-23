"""Native Gemini evidence survives the installed recommended evaluation chains."""

import asyncio
import json

import pytest

from relf_agent import GeminiFunctionProvider
from relf_agent.errors import ValidationError
from relf_agent.orchestration_evaluation import (
    OfflineOrchestrationProvider,
    evaluate_orchestration,
    load_orchestration_cases,
)
from relf_agent.rag_evaluation import OfflineRAGProvider, evaluate_rag
from relf_agent.rag_evaluation_cases import load_rag_cases
from relf_agent.storage import SQLiteStore
from relf_agent.types import canonical


class SignedFixture(GeminiFunctionProvider):
    """Original native codec with scripted choices; no model quality assertion."""

    def __init__(self, fixture):
        super().__init__("fixture", api_key="fixture", max_output_tokens=2048, timeout=60)
        self.fixture = fixture
        self.requests = []

    async def complete(self, messages, tools):
        # Exercise the actual strict native request encoder too. The policy
        # fixture operates on standard SDK messages, never the scoring oracle.
        _, body = self._body(messages, tools, self.identity)
        self.requests.append(body)
        result = await self.fixture.complete(messages, tools)
        parts = []
        if result.output is not None:
            parts.append(
                {
                    "text": result.output
                    if isinstance(result.output, str)
                    else canonical(result.output)
                }
            )
        for call in result.tool_calls:
            parts.append(
                {
                    "functionCall": {
                        "name": call.name,
                        "args": call.arguments,
                        **({"id": call.call_id} if call.call_id is not None else {}),
                    }
                }
            )
        parts[0]["thoughtSignature"] = "b3JpZ2luYWwtc2lnbmF0dXJl"
        return self._parse(
            json.dumps(
                {
                    "candidates": [
                        {"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}
                    ],
                    "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1},
                }
            )
        )


@pytest.mark.parametrize("kind", ["plan-and-execute", "team"])
def test_signed_native_plan_team_default_combinations_and_reconnection(kind, tmp_path):
    provider = SignedFixture(OfflineOrchestrationProvider())
    report = asyncio.run(
        evaluate_orchestration(
            provider,
            kind=kind,
            cases=load_orchestration_cases()[:1],
            evidence_dir=tmp_path,
            offline=True,
            model_continuation=True,
        )
    )
    assert report["passed"] == report["total"] == 1, report
    assert report["model_quality"] is None
    assert len(provider.requests) == 4
    assert (
        sum(
            any(
                "functionResponse" in part
                for content in req["contents"]
                for part in content["parts"]
            )
            for req in provider.requests
        )
        == 2
    )
    assert all(row["recovery"]["additional_calls"] == 0 for row in report["cases"])


def test_signed_native_rag_default_chain_has_persisted_original_response(tmp_path):
    provider = SignedFixture(OfflineRAGProvider())
    report = asyncio.run(
        evaluate_rag(
            provider,
            cases=load_rag_cases()[:1],
            evidence_dir=tmp_path,
            offline=True,
            model_continuation=True,
        )
    )
    assert report["passed"] == report["total"] == 1, report
    row = report["cases"][0]
    with SQLiteStore(tmp_path / f"{row['case_id']}-0.sqlite", readonly=True) as store:
        record = store.run(row["run_id"])
    model = next(a for a in record["actions"] if a["kind"] == "model")
    assert record["manifest"]["model_continuation_protocol"] == 1
    assert model["received_response"]["continuation"]["data"]["content"]["parts"][0][
        "thoughtSignature"
    ]
    assert model["response"]["continuation"] == model["received_response"]["continuation"]
    assert row["recovery"]["additional_model_calls"] == 0
    assert report["model_quality"] is None


@pytest.mark.parametrize("evaluate", [evaluate_rag, evaluate_orchestration])
def test_continuation_option_rejects_non_boolean_before_evidence_io(evaluate, tmp_path):
    with pytest.raises(ValidationError, match="boolean"):
        asyncio.run(evaluate(evidence_dir=tmp_path, model_continuation=1))
    assert not list(tmp_path.iterdir())
