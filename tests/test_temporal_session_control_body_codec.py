"""Bounded Coding4 control-body transport preserves the original semantic bytes."""

import asyncio
import base64
import copy
import json
import zlib

import pytest

from ralf_agent import temporal_session_deployment_dto as dto
from ralf_agent.errors import RalfError
from ralf_agent.types import canonical, digest
from tests.test_temporal_deployment_session_registry import deployment_intent
from tests.test_temporal_session_deployment_coding_configuration import coding_session_manifest

MARKER = "_ralf_session_control_body"
LIMIT = 8 * 1024 * 1024


def codec():
    encode = getattr(dto, "encode_control_body", None)
    decode = getattr(dto, "decode_control_body", None)
    assert callable(encode) and callable(decode), "Missing bounded Session control body codec"
    return encode, decode


def test_large_original_coding_body_roundtrips_below_wire_limit():
    encode, decode = codec()
    manifest = coding_session_manifest()
    body = {"ok": True, "result": {"original_evidence": "e" * (2 * 1024 * 1024)}}
    assert len(canonical(body).encode()) > 2 * 1024 * 1024
    encoded = encode(body, manifest)
    assert len(canonical(encoded).encode()) < 1024 * 1024
    assert decode(encoded, manifest) == body


@pytest.mark.parametrize("kind", ["native", "composition", "ordinary", "legacy"])
def test_small_body_and_legacy_raw_keep_original_detached_representation(kind):
    encode, decode = codec()
    if kind == "ordinary":
        manifest = deployment_intent()["binding"]["manifest"]
    else:
        manifest = coding_session_manifest(composition=kind == "composition")
        if kind == "legacy":
            manifest["deployment_admission_protocol"]["version"] = 3
    body = {"ok": True, "result": {"evidence": ["original"]}}
    encoded = encode(body, manifest)
    decoded = decode(body, manifest)
    assert encoded == decoded == body
    encoded["result"]["evidence"].append("encoded mutation")
    decoded["result"]["evidence"].append("decoded mutation")
    assert body["result"]["evidence"] == ["original"]
    large = {"ok": True, "result": {"evidence": "legacy" * 100000}}
    assert decode(large, manifest) == large


def wire(raw, *, size=None, checksum=None, compressed=None):
    return {
        MARKER: {
            "version": 1,
            "encoding": "zlib-json-base64",
            "raw_size": len(raw) if size is None else size,
            "digest": digest(json.loads(raw)) if checksum is None else checksum,
            "data": base64.b64encode(
                zlib.compress(raw) if compressed is None else compressed
            ).decode(),
        }
    }


@pytest.mark.parametrize(
    "fault",
    [
        "extra-envelope",
        "extra-header",
        "missing-header",
        "version",
        "bool-version",
        "encoding",
        "bool-size",
        "negative-size",
        "size-mismatch",
        "digest",
        "base64",
        "wire-size",
        "semantic-size",
        "bomb",
        "truncated",
        "concatenated",
        "tail",
        "noncanonical",
        "invalid-json",
    ],
)
def test_malformed_or_unbounded_encoded_body_is_never_accepted(fault):
    _, decode = codec()
    body = {"ok": True, "result": {"evidence": "x" * (512 * 1024)}}
    raw = canonical(body).encode()
    encoded = wire(raw)
    header = encoded[MARKER]
    if fault == "extra-envelope":
        encoded["extra"] = None
    elif fault == "extra-header":
        header["extra"] = None
    elif fault == "missing-header":
        del header["digest"]
    elif fault == "version":
        header["version"] = 2
    elif fault == "bool-version":
        header["version"] = True
    elif fault == "encoding":
        header["encoding"] = "json"
    elif fault == "bool-size":
        header["raw_size"] = True
    elif fault == "negative-size":
        header["raw_size"] = -1
    elif fault == "size-mismatch":
        header["raw_size"] += 1
    elif fault == "digest":
        header["digest"] = "0" * 64
    elif fault == "base64":
        header["data"] = "!invalid!"
    elif fault == "wire-size":
        header["data"] = "A" * (1024 * 1024)
    elif fault == "semantic-size":
        header["raw_size"] = LIMIT + 1
    elif fault == "bomb":
        header["data"] = base64.b64encode(zlib.compress(b"x" * (LIMIT + 1))).decode()
    elif fault in {"truncated", "concatenated", "tail"}:
        compressed = zlib.compress(raw)
        compressed = (
            compressed[:-1]
            if fault == "truncated"
            else compressed + (zlib.compress(raw) if fault == "concatenated" else b"tail")
        )
        header["data"] = base64.b64encode(compressed).decode()
    elif fault == "noncanonical":
        encoded = wire(json.dumps(body, indent=1).encode(), checksum=digest(body))
    else:
        encoded = wire(b"!" * len(raw), checksum=digest(body))
    before = copy.deepcopy(encoded)
    with pytest.raises(RalfError):
        decode(encoded, coding_session_manifest())
    assert encoded == before


def test_ordinary_session_rejects_compressed_envelope_and_semantic_limit_is_unchanged():
    encode, decode = codec()
    coding = coding_session_manifest()
    ordinary = deployment_intent()["binding"]["manifest"]
    body = {"ok": True, "result": {"evidence": "x" * (512 * 1024)}}
    encoded = encode(body, coding)
    with pytest.raises(RalfError):
        decode(encoded, ordinary)
    oversized = {"ok": True, "result": {"evidence": "x" * LIMIT}}
    for manifest in (coding, ordinary):
        for operation in (encode, decode):
            with pytest.raises(RalfError):
                operation(oversized, manifest)


@pytest.mark.parametrize(
    "name", ["encode_control_body", "decode_control_body", "_coded_control_body", "_body_reject"]
)
def test_original_session_source_pins_reject_codec_replacement_after_await(monkeypatch, name):
    from tests.test_temporal_session_deployment_control import validation

    async def scenario():
        proof, _ = validation()
        await asyncio.sleep(0)
        monkeypatch.setattr(dto, name, lambda *args: None)
        with pytest.raises(RalfError):
            proof._check()

    asyncio.run(scenario())
