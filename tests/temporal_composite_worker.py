"""Registered multi-process composite probe; all child work belongs to History."""

import asyncio
import json
import os

import temporal_worker_fixture as native

from relf_agent import ModelResponse
from relf_agent.governance import TemporalExecutionPolicy
from relf_agent.temporal import build_temporal_worker
from relf_agent.temporal_activities import TemporalRuntime


class CompositeProvider(native.FixtureProvider):
    identity = {"kind": "composite-fixture-provider", "version": "1"}

    async def complete(self, messages, tools):
        if (
            "json dag" in messages[0]["content"].lower()
            or "planner" in messages[0]["content"].lower()
            or "supplied member" in messages[0]["content"]
        ):
            print("TEMPORAL_PLANNER_CALLED", flush=True)
            value = json.loads(messages[1]["content"])
            members = value["members"]
            nodes = [
                {
                    "id": f"step-{i}",
                    "member": member,
                    "depends_on": [] if i == 0 else [f"step-{i - 1}"],
                    "input": {
                        "kind": "ref",
                        "source": "input" if i == 0 else f"step-{i - 1}",
                        "path": [],
                        "required": True,
                        "default": None,
                    },
                }
                for i, member in enumerate(members)
            ]
            return ModelResponse(
                output={
                    "status": "plan",
                    "nodes": nodes,
                    "output": {
                        "kind": "ref",
                        "source": nodes[-1]["id"],
                        "path": [],
                        "required": True,
                        "default": None,
                    },
                }
            )
        if messages[-1]["role"] != "tool":
            for message in messages:
                if message.get("content", "").startswith("Reference memory;"):
                    references = json.loads(message["content"].partition("\n")[2])
                    print("TEMPORAL_PROVIDER_CALLED", flush=True)
                    return ModelResponse(
                        output={
                            "citations": [
                                {
                                    "document_id": ref["value"]["document_id"],
                                    "version": ref["version"],
                                    "text": ref["value"]["text"],
                                }
                                for ref in references
                                if "_knowledge" in ref
                            ]
                        }
                    )
            try:
                value = json.loads(messages[1]["content"])
            except ValueError:
                value = None
            while isinstance(value, dict) and isinstance(value.get("task"), dict):
                value = value["task"]
            if isinstance(value, dict) and value.get("model_delay"):
                print("TEMPORAL_PROVIDER_CALLED", flush=True)
                await asyncio.sleep(value["model_delay"])
                return ModelResponse(output={"slow": "complete"})
            if isinstance(value, dict) and value.get("tool"):
                from relf_agent import ToolCall

                print("TEMPORAL_PROVIDER_CALLED", flush=True)
                return ModelResponse(tool_calls=[ToolCall("write", value["arguments"])])
        return await super().complete(messages, tools)


async def runtime(*, rag_collection=None):
    original = await native.runtime()
    limits = json.loads(os.environ.get("RALF_TEST_EXECUTION_POLICY", "null"))
    policy = None if limits is None else TemporalExecutionPolicy(**limits)
    collection = rag_collection or os.environ.get("RALF_TEST_RAG_COLLECTION")
    knowledge, resources = None, []
    if collection:
        from relf_agent import (
            HashEmbeddingProvider,
            KnowledgeContext,
            PostgresKnowledgeStore,
            QdrantVectorIndex,
            VectorRetriever,
        )

        store = await PostgresKnowledgeStore.connect(
            os.environ["RALF_TEST_POSTGRES_DSN"], backend_id="temporal-composite-knowledge"
        )
        await store.initialize()
        index = QdrantVectorIndex(
            os.environ["RALF_TEST_QDRANT_URL"],
            collection=collection,
            dimensions=128,
            backend_id=collection,
        )
        await index.initialize(create=True)
        resources = [store, index]
        knowledge = KnowledgeContext(
            VectorRetriever(store, index, HashEmbeddingProvider()), namespace="runbooks"
        )
    result = TemporalRuntime(
        providers={"default": CompositeProvider()},
        tools=native.tools(),
        journal=original.journal,
        execution_policy=policy,
        knowledge=knowledge,
    )
    result.rag_resources = resources
    return result


async def main():
    from temporalio.client import Client

    client = await Client.connect(os.environ["RALF_TEST_TEMPORAL_ADDRESS"])
    execution = await runtime()
    try:
        async with build_temporal_worker(
            client,
            task_queue=os.environ["RALF_TEST_TEMPORAL_QUEUE"],
            runtime=execution,
            release=execution.orchestration_release,
            max_concurrent_activities=8,
        ):
            print("TEMPORAL_WORKER_READY", flush=True)
            await asyncio.Event().wait()
    finally:
        for resource in execution.rag_resources:
            await resource.aclose()
        await execution.journal.aclose()


if __name__ == "__main__":
    asyncio.run(main())
