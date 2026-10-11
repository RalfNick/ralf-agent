"""Actual read lifetime alongside per-Agent Context, automatic memory and RAG."""

import os

import pytest

from .test_temporal_session_tree_data_context import (
    test_actual_tree_summary_and_offload_preserve_sources_across_turns as offload_scenario,
)
from .test_temporal_session_tree_memory_rag import (
    test_actual_tree_bound_memory_and_rag_finish_before_root_save as memory_rag_scenario,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("RALF_TEST_TEMPORAL_ADDRESS"), reason="requires actual Temporal Service"
)


@pytest.mark.parametrize("kind", ["parallel", "dynamic-dag", "nested"])
def test_actual_read_owner_per_agent_memory_rag_and_cached_sources(tmp_path, kind):
    memory_rag_scenario(tmp_path, kind, context_reads=True)


@pytest.mark.parametrize("backend", ["sqlite", "file"])
def test_actual_read_owner_summary_artifact_reads_and_source_once(tmp_path, backend):
    offload_scenario(tmp_path, backend, context_reads=True)
