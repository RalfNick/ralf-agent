"""Actual SDK submission task remains owned after observer cancellation."""

import asyncio
import importlib

import pytest

from relf_agent.errors import CloseIncomplete, DefinitionMismatch
from relf_agent.types import Scope, digest


def owner():
    name = "relf_agent.temporal_coding_composition_submissions"
    assert importlib.util.find_spec(name), "Missing original SDK submission owner"
    return importlib.import_module(name).CompositionSubmissionOwner(
        scope=Scope(), release={"original": "release"}
    )


def test_cancelled_submit_observer_cannot_release_original_sdk_operation():
    async def run():
        actual = owner()
        entered, release, ended = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def submit():
            entered.set()
            await release.wait()
            ended.set()
            return "original-start-reply"

        observer = asyncio.create_task(
            actual.execute(
                submit,
                scope={"workspace": "default", "principal": "local-owner"},
                release_digest=digest({"original": "release"}),
                request_digest=digest({"request": "original"}),
            )
        )
        try:
            await entered.wait()
            observer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await observer
            actual.stop_admission()
            assert not await actual.wait(wait_timeout=0)
            with pytest.raises(CloseIncomplete):
                await actual.aclose(wait_timeout=0)
            assert not ended.is_set()
            release.set()
            await actual.aclose(wait_timeout=1)
            assert ended.is_set()
        finally:
            release.set()
            await asyncio.gather(observer, return_exceptions=True)

    asyncio.run(run())


def test_submission_owner_rejects_foreign_release_before_sdk_dispatch():
    async def run():
        actual, calls = owner(), []

        async def submit():
            calls.append("actual")

        with pytest.raises(DefinitionMismatch):
            await actual.execute(
                submit,
                scope={"workspace": "default", "principal": "local-owner"},
                release_digest=digest({"foreign": "release"}),
                request_digest=digest({"request": "original"}),
            )
        assert calls == []
        await actual.aclose()

    asyncio.run(run())
