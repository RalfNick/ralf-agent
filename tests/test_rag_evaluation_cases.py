import asyncio
import copy
import importlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from relf_agent.errors import ValidationError
from relf_agent.retrieval import (
    Document,
    InMemoryKnowledgeStore,
    KnowledgeContext,
    LexicalRetriever,
)
from relf_agent.types import Scope, canonical, digest


def api():
    return importlib.import_module("relf_agent.rag_evaluation_cases")


@pytest.fixture
def case():
    return {
        "id": "retention",
        "category": "two-document-merge",
        "question": "How long are restore copies and audit records kept? Return both day counts.",
        "documents": [
            {
                "document_id": "restore-window",
                "text": "Restore policy. Restore copies are retained for 30 days.",
                "namespace": "manuals",
                "metadata": {"facts": {"restore_days": 30}},
            },
            {
                "document_id": "audit-window",
                "text": "Audit policy. Audit records are retained for 90 days.",
                "namespace": "manuals",
                "metadata": {"facts": {"audit_days": 90}},
            },
            {
                "document_id": "unrelated",
                "text": "Restore and audit headings. The canteen closes at 18:00.",
                "namespace": "manuals",
                "metadata": {},
            },
        ],
        "expected": {
            "status": "answered",
            "answer": {"restore_days": 30, "audit_days": 90},
            "support": {
                "restore-window": "retained for 30 days",
                "audit-window": "retained for 90 days",
            },
        },
    }


@pytest.fixture
def references(case):
    # Real retrieval supplies the full persisted reference format, including digest.
    with InMemoryKnowledgeStore(chunk_size=2000, overlap=0) as store:
        for document in case["documents"]:
            store.put(
                Scope("rag-evaluation", "fixture"),
                document["namespace"],
                Document(
                    document["document_id"],
                    document["text"],
                    "fixture:" + document["document_id"],
                    document["metadata"],
                ),
                expected_version=0,
            )
        context = KnowledgeContext(LexicalRetriever(store), namespace="manuals")
        return asyncio.run(context.references(Scope("rag-evaluation", "fixture"), "restore audit"))


@pytest.fixture
def output():
    return {
        "status": "answered",
        "answer": {"audit_days": 90, "restore_days": 30},
        "citations": [
            {"document_id": "restore-window", "version": 1, "quote": "retained for 30 days"},
            {"document_id": "audit-window", "version": 1, "quote": "retained for 90 days"},
        ],
    }


def test_correct_answer_with_two_actual_source_citations_passes(case, output, references):
    assert api().score_rag_answer(case, output, references) == {
        "passed": True,
        "checks": {
            "answer": True,
            "citation_validity": True,
            "citation_coverage": True,
            "decision": True,
        },
    }


def test_json_output_and_scalar_answers_are_scored_by_json_value(case, output, references):
    case["expected"]["answer"] = 30
    output["answer"] = 30
    assert api().score_rag_answer(case, json.dumps(output), references)["passed"]
    output["answer"] = True
    assert not api().score_rag_answer(case, output, references)["checks"]["answer"]


def test_wrong_answer_can_have_valid_and_complete_citations(case, output, references):
    output["answer"]["restore_days"] = 31
    score = api().score_rag_answer(case, output, references)
    assert score == {
        "passed": False,
        "checks": {
            "answer": False,
            "citation_validity": True,
            "citation_coverage": True,
            "decision": True,
        },
    }


@pytest.mark.parametrize("document_id", ["fabricated", "unrelated"])
def test_correct_answer_cannot_add_fabricated_or_irrelevant_citations(
    case, output, references, document_id
):
    output["citations"].append(
        {"document_id": document_id, "version": 1, "quote": "The canteen closes at 18:00."}
    )
    score = api().score_rag_answer(case, output, references)
    assert not score["passed"]
    assert score["checks"]["answer"]
    assert not score["checks"]["citation_validity"]


def test_available_document_is_not_citable_without_an_offered_reference(case, output, references):
    references = [ref for ref in references if ref["value"]["document_id"] != "audit-window"]
    score = api().score_rag_answer(case, output, references)
    assert not score["checks"]["citation_validity"]
    assert not score["checks"]["citation_coverage"]


def test_old_citation_version_fails_against_actual_offered_version(case, output, references):
    for reference in references:
        if reference["value"]["document_id"] == "restore-window":
            reference["version"] = 2
            reference["_knowledge"]["version"] = 2
    score = api().score_rag_answer(case, output, references)
    assert score["checks"]["answer"]
    assert not score["checks"]["citation_validity"]
    assert not score["checks"]["citation_coverage"]


@pytest.mark.parametrize(
    "change",
    [
        "namespace",
        "key",
        "chunk_id",
        "version",
        "document_id",
        "text_digest",
        "scope",
        "text",
        "metadata",
    ],
)
def test_internally_inconsistent_reference_never_supports_a_citation(
    case, output, references, change
):
    reference = next(ref for ref in references if ref["value"]["document_id"] == "restore-window")
    if change == "key":
        reference["key"] = "knowledge:fake"
    elif change == "text":
        reference["value"]["text"] += " fabricated evidence"
    elif change == "metadata":
        reference["value"]["metadata"] = {"x": float("nan")}
    else:
        reference["_knowledge"][change] = {
            "namespace": "private",
            "chunk_id": "another-chunk",
            "version": 999,
            "document_id": "another-document",
            "text_digest": "0" * 64,
            "scope": {"workspace": "rag-evaluation"},
        }[change]
    score = api().score_rag_answer(case, output, references)
    assert not score["checks"]["citation_validity"]
    assert not score["checks"]["citation_coverage"]


def test_self_consistent_fabricated_chunk_text_still_must_be_in_original_document(
    case, output, references
):
    reference = next(ref for ref in references if ref["value"]["document_id"] == "restore-window")
    reference["value"]["text"] = "Restore copies are retained for 300 days."
    reference["_knowledge"]["text_digest"] = digest(reference["value"]["text"])
    output["citations"][0]["quote"] = "retained for 300 days"
    assert not api().score_rag_answer(case, output, references)["checks"]["citation_validity"]


def test_private_document_with_same_id_is_not_an_authorized_manual_source(case, output, references):
    private_document = copy.deepcopy(case["documents"][0])
    private_document["namespace"] = "private"
    case["documents"].append(private_document)
    reference = next(ref for ref in references if ref["value"]["document_id"] == "restore-window")
    reference["_knowledge"]["namespace"] = "private"
    assert not api().score_rag_answer(case, output, references)["checks"]["citation_validity"]


@pytest.mark.parametrize("quote", ["", "   ", "retained for thirty days", "RETained for 30 days"])
def test_empty_or_nonliteral_quote_cannot_support_an_answer(case, output, references, quote):
    output["citations"][0]["quote"] = quote
    score = api().score_rag_answer(case, output, references)
    assert not score["passed"]
    assert not score["checks"]["citation_validity"]
    assert not score["checks"]["citation_coverage"]


def test_header_only_quote_is_literal_but_does_not_cover_required_evidence(
    case, output, references
):
    output["citations"][0]["quote"] = "Restore policy."
    score = api().score_rag_answer(case, output, references)
    assert score["checks"]["citation_validity"]
    assert not score["checks"]["citation_coverage"]
    assert not score["passed"]


def test_quote_must_be_inside_one_offered_chunk_not_only_full_source(case, output, references):
    reference = next(ref for ref in references if ref["value"]["document_id"] == "restore-window")
    reference["value"]["text"] = "Restore policy."
    reference["_knowledge"]["text_digest"] = digest("Restore policy.")
    assert not api().score_rag_answer(case, output, references)["checks"]["citation_validity"]


def test_quote_must_be_in_displayed_excerpt_of_an_actual_reference(case, output, references):
    reference = next(ref for ref in references if ref["value"]["document_id"] == "restore-window")
    reference["_offered_text"] = "Restore policy."
    score = api().score_rag_answer(case, output, references)
    assert not score["checks"]["citation_validity"]
    assert not score["checks"]["citation_coverage"]


def test_valid_excerpt_preserves_full_source_digest(case, output, references):
    reference = next(ref for ref in references if ref["value"]["document_id"] == "restore-window")
    reference["_offered_text"] = "retained for 30 days"
    assert api().score_rag_answer(case, output, references)["passed"]


def test_self_consistent_projection_cannot_invent_displayed_source_text(case, output, references):
    reference = next(ref for ref in references if ref["value"]["document_id"] == "restore-window")
    reference["_offered_text"] = "Invented source. retained for 30 days"
    assert not api().score_rag_answer(case, output, references)["checks"]["citation_validity"]


def test_missing_one_of_two_supports_fails_coverage(case, output, references):
    output["citations"].pop()
    score = api().score_rag_answer(case, output, references)
    assert score["checks"]["citation_validity"]
    assert not score["checks"]["citation_coverage"]


def test_duplicate_citation_fails_even_with_full_coverage(case, output, references):
    output["citations"].append(copy.deepcopy(output["citations"][0]))
    assert not api().score_rag_answer(case, output, references)["checks"]["citation_validity"]


def test_correct_decision_requires_null_answer_and_empty_citations_for_stops(case, references):
    for status in ("needs_input", "refused"):
        case["expected"] = {"status": status, "answer": None, "support": {}}
        output = {"status": status, "answer": None, "citations": []}
        assert api().score_rag_answer(case, output, references)["passed"]
        output["answer"] = "made up"
        assert not api().score_rag_answer(case, output, references)["passed"]
        output["answer"] = None
        output["citations"] = [
            {"document_id": "restore-window", "version": 1, "quote": "retained for 30 days"}
        ]
        assert not api().score_rag_answer(case, output, references)["passed"]


def test_wrong_stop_decision_is_not_a_success(case, references):
    case["expected"] = {"status": "needs_input", "answer": None, "support": {}}
    score = api().score_rag_answer(
        case, {"status": "refused", "answer": None, "citations": []}, references
    )
    assert not score["passed"]
    assert not score["checks"]["decision"]


@pytest.mark.parametrize(
    "output",
    [
        "not JSON",
        '{"status":"answered","answer":NaN,"citations":[]}',
        '{"status":"answered","status":"refused","answer":null,"citations":[]}',
        {"status": "answered", "answer": {"restore_days": 30, "audit_days": 90}},
        {"status": "answered", "answer": None, "citations": []},
        {"status": "invented", "answer": None, "citations": []},
        {"status": "answered", "answer": 30, "citations": [], "debug": "raw private text"},
        None,
        [],
    ],
)
def test_malformed_outputs_fail_without_disclosing_content(case, references, output):
    assert api().score_rag_answer(case, output, references) == {
        "passed": False,
        "checks": {
            "answer": False,
            "citation_validity": False,
            "citation_coverage": False,
            "decision": False,
        },
    }


def test_citation_output_fields_are_exact_and_versions_are_real_integers(case, output, references):
    for change in ({"version": True}, {"version": 1.0}, {"reason": "private detail"}):
        altered = copy.deepcopy(output)
        altered["citations"][0].update(change)
        assert not api().score_rag_answer(case, altered, references)["passed"]


def test_scoring_is_pure_and_scores_contain_only_boolean_checks(case, output, references):
    before = copy.deepcopy((case, output, references))
    score = api().score_rag_answer(case, output, references)
    assert (case, output, references) == before
    assert set(score) == {"passed", "checks"}
    assert all(type(value) is bool for value in score["checks"].values())
    assert "retained" not in json.dumps(score)
    assert "restore_days" not in json.dumps(score)


def test_default_cases_are_frozen_reviewable_and_detached():
    module = api()
    cases = module.load_rag_cases()
    frozen = Path(__file__).parents[1] / "evals" / "rag-cases.json"
    assert cases == module.load_rag_cases(frozen)
    assert len(cases) >= 8
    assert len({case["category"] for case in cases}) >= 8
    assert {case["expected"]["status"] for case in cases} == {"answered", "needs_input", "refused"}
    assert any(any("\u4e00" <= letter <= "\u9fff" for letter in case["question"]) for case in cases)
    assert any(len(case["expected"]["support"]) == 2 for case in cases)
    assert any(doc["namespace"] == "private" for case in cases for doc in case["documents"])
    cases[0]["documents"][0]["metadata"]["facts"]["mutated"] = True
    cases[0]["expected"]["answer"] = "changed"
    assert module.load_rag_cases() == module.load_rag_cases(frozen)


def test_every_frozen_answer_requires_all_of_its_manual_supports():
    module = api()
    for case in module.load_rag_cases():
        if case["expected"]["status"] != "answered":
            continue
        documents = {
            doc["document_id"]: doc for doc in case["documents"] if doc["namespace"] == "manuals"
        }
        with InMemoryKnowledgeStore(chunk_size=2000, overlap=0) as store:
            for doc in documents.values():
                store.put(
                    Scope(),
                    "manuals",
                    Document(doc["document_id"], doc["text"], metadata=doc["metadata"]),
                    expected_version=0,
                )
            context = KnowledgeContext(
                LexicalRetriever(store), namespace="manuals", limit=128, max_chars=100000
            )
            references = asyncio.run(
                context.references(Scope(), " ".join(doc["text"] for doc in documents.values()))
            )
            output = {
                "status": "answered",
                "answer": case["expected"]["answer"],
                "citations": [
                    {"document_id": doc_id, "version": 1, "quote": anchor}
                    for doc_id, anchor in case["expected"]["support"].items()
                ],
            }
            assert module.score_rag_answer(case, output, references)["passed"], case["id"]


def test_custom_case_file_is_validated_and_returned_detached(tmp_path, case):
    path = tmp_path / "cases.json"
    path.write_text(canonical({"version": "1", "cases": [case]}), encoding="utf-8")
    loaded = api().load_rag_cases(path)
    loaded[0]["documents"][0]["metadata"]["facts"]["restore_days"] = 999
    assert api().load_rag_cases(path)[0]["documents"][0]["metadata"]["facts"] == {
        "restore_days": 30
    }


@pytest.mark.parametrize(
    "bad",
    [
        "extra-case-field",
        "extra-document-field",
        "extra-expected-field",
        "duplicate-document",
        "duplicate-case",
        "private-support",
        "missing-support-document",
        "missing-support-substring",
        "empty-support",
        "answered-null",
        "stopped-answer",
        "stopped-support",
        "nonfinite-metadata",
        "not-object-metadata",
        "bad-namespace",
        "blank-question",
        "blank-category",
        "empty-cases",
        "bad-version",
        "extra-document-envelope-field",
    ],
)
def test_invalid_case_documents_are_rejected_before_runtime_use(tmp_path, case, bad):
    document = {"version": "1", "cases": [case]}
    if bad.startswith("extra-"):
        target = {
            "extra-case-field": case,
            "extra-document-field": case["documents"][0],
            "extra-expected-field": case["expected"],
            "extra-document-envelope-field": document,
        }[bad]
        target["unexpected"] = True
    elif bad == "duplicate-document":
        case["documents"].append(copy.deepcopy(case["documents"][0]))
    elif bad == "duplicate-case":
        document["cases"].append(copy.deepcopy(case))
    elif bad == "private-support":
        case["documents"][0]["namespace"] = "private"
    elif bad == "missing-support-document":
        case["expected"]["support"]["absent"] = "missing"
    elif bad == "missing-support-substring":
        case["expected"]["support"]["restore-window"] = "retained for 300 days"
    elif bad == "empty-support":
        case["expected"]["support"] = {}
    elif bad == "answered-null":
        case["expected"]["answer"] = None
    elif bad == "stopped-answer":
        case["expected"] = {"status": "needs_input", "answer": 30, "support": {}}
    elif bad == "stopped-support":
        case["expected"]["status"] = "refused"
        case["expected"]["answer"] = None
    elif bad == "nonfinite-metadata":
        case["documents"][0]["metadata"] = {"invalid": float("nan")}
    elif bad == "not-object-metadata":
        case["documents"][0]["metadata"] = []
    elif bad == "bad-namespace":
        case["documents"][0]["namespace"] = "public"
    elif bad == "blank-question":
        case["question"] = " "
    elif bad == "blank-category":
        case["category"] = " "
    elif bad == "empty-cases":
        document["cases"] = []
    elif bad == "bad-version":
        document["version"] = 1
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValidationError):
        api().load_rag_cases(path)


def test_loader_rejects_duplicate_json_keys_and_unreadable_files(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"version":"2","version":"1","cases":[]}', encoding="utf-8")
    with pytest.raises(ValidationError):
        api().load_rag_cases(path)
    with pytest.raises(ValidationError):
        api().load_rag_cases(tmp_path / "absent.json")


def test_output_schema_prohibits_extra_fields_and_enforces_stop_shape():
    validator = Draft202012Validator(api().RAG_OUTPUT_SCHEMA)
    assert validator.is_valid(
        {
            "status": "answered",
            "answer": 30,
            "citations": [
                {"document_id": "restore-window", "version": 1, "quote": "retained for 30 days"}
            ],
        }
    )
    assert validator.is_valid({"status": "refused", "answer": None, "citations": []})
    assert not validator.is_valid({"status": "answered", "answer": None, "citations": []})
    assert not validator.is_valid({"status": "needs_input", "answer": 30, "citations": []})
    assert not validator.is_valid(
        {
            "status": "answered",
            "answer": 30,
            "citations": [
                {
                    "document_id": "restore-window",
                    "version": 1,
                    "quote": "retained for 30 days",
                    "source": "fake",
                }
            ],
        }
    )
