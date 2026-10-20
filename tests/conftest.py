"""Bounded teardown for clients whose test runtime intentionally retains debt."""

import sys

import pytest


@pytest.fixture(autouse=True)
def detach_retained_coding_clients_after_original_loop():
    yield
    resources = sys.modules.get("tests.temporal_fixture_resources")
    if resources is not None:
        resources.retained.finish()
