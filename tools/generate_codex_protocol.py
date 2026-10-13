"""Extract the reviewed subset from Codex 0.144.4's generated stable schemas.

Generate inputs with: codex app-server generate-json-schema --out PRIVATE_DIR
This utility reads schemas; it never starts Codex or a business task.
Only object key order/whitespace may vary across native platforms. The default
artifact retains its original reviewed generation source hashes, not the raw
hashes of every subsequently accepted, semantically identical input.
"""

import argparse
import hashlib
import json
from pathlib import Path

METHODS = {
    "initialize": "v1/InitializeResponse.json",
    "thread/start": "v2/ThreadStartResponse.json",
    "thread/read": "v2/ThreadReadResponse.json",
    "thread/resume": "v2/ThreadResumeResponse.json",
    "turn/start": "v2/TurnStartResponse.json",
    "turn/interrupt": "v2/TurnInterruptResponse.json",
}

INPUT_SHA256 = {
    "ClientRequest.json": "3aea6cb46e7b96f882054f5b908dfd1c919396051b0f54062c149d107cb0ddec",
    "v1/InitializeResponse.json": "86dcd236d0576a82c85b933586dc45731260eab1b6edb3447b03f790277322b1",
    "v2/ThreadReadResponse.json": "86adff6de376b567306c20ccb23ec4684c427324cf8ae96f2016e31fdc58023e",
    "v2/ThreadResumeResponse.json": "5715f85072ff6a6d6484f3a91a126b54863d6eafae8bcfe10b687f4e9e85d1df",
    "v2/ThreadStartResponse.json": "0da5385b4d0eef89990a8a0847bd9d7170ee18843f17e52e0bd22c152723363b",
    "v2/TurnInterruptResponse.json": "531de6be06fe979b5963f249bab82498a175e614bf65ac12fb2e849dfe60bcf1",
    "v2/TurnStartResponse.json": "7cfae42a4652fe38119d6a0a625910357c869c448c985513a4cd5966031e18bc",
}

CONTROL_METHODS = {
    "initialize": "v1/InitializeResponse.json",
    "config/read": "v2/ConfigReadResponse.json",
    "configRequirements/read": "v2/ConfigRequirementsReadResponse.json",
    "experimentalFeature/list": "v2/ExperimentalFeatureListResponse.json",
    "permissionProfile/list": "v2/PermissionProfileListResponse.json",
    "mcpServerStatus/list": "v2/ListMcpServerStatusResponse.json",
    "skills/list": "v2/SkillsListResponse.json",
    "plugin/list": "v2/PluginListResponse.json",
    "plugin/installed": "v2/PluginInstalledResponse.json",
}

# Full original native inputs, including documentation, canonically encoded.
SEMANTIC_SHA256 = {
    "ClientRequest.json": "5be9bf8117c33b8d1c20a25cd72eaea9122899cd527744ffaac1d12e3f0ba0fb",
    "v1/InitializeResponse.json": "747401b5d7d395b71e4023d3d13aaaaefb0f6ae044d611675f59838672720c3d",
    "v2/ConfigReadResponse.json": "24ad01fe1ee9b71e0f09ef9052db4f6d250d35abbb750d155cab98c10105390b",
    "v2/ConfigRequirementsReadResponse.json": "2b58de34466436e9701a58d7fea47774c7c6a3e4ae7efcdc1a438e04d6cce880",
    "v2/ExperimentalFeatureListResponse.json": "c3b75b295dd5197e045f888d9fb4ab4d4abf113ab03f04d2186978126eb0e950",
    "v2/ListMcpServerStatusResponse.json": "b72d826608cdf06cc7bbec9caeb8db6f7463bdd2854f43a572bdde0cb3e221ad",
    "v2/PermissionProfileListResponse.json": "695a64e0c32a58006040f487aa04a37eeacd60885aa1ec2f8a927b0d9c671d7b",
    "v2/PluginInstalledResponse.json": "8a66d6b3f882a6b0d710fabe4171274e9b972fc63c6cfce68d30b313e1c925cb",
    "v2/PluginListResponse.json": "501c954b5c9bcb804bc2d65d0718b6a5885b743b01702f873eae285ab1873c6f",
    "v2/SkillsListResponse.json": "fc6abca9b65f95ed94d90815ae0682fdb91af42cc1e928a0f6767537ad85d356",
    "v2/ThreadReadResponse.json": "72eda7e776a6a30f52bc161cd25703e1fd4fb60ed92969b9ddb3978bbae4ae21",
    "v2/ThreadResumeResponse.json": "87a2044caee7ac69a00cf159bf83a0da15a851222761113301f082e627cd6000",
    "v2/ThreadStartResponse.json": "185c3a50c61ae83bc8ac9556e06c2bb759be5a7182017e1121d5992d7c2d2eca",
    "v2/TurnInterruptResponse.json": "06e70e8d7e6a13fa301dfc650a2aa685f44a3cbf8767ce22b4797e35a59e6a8c",
    "v2/TurnStartResponse.json": "d0fdbfb0058b2f964b17d770fa476819c4a2f574c552e703982c3568c016179f",
}


def semantic_digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous native Schema object")
        result[key] = value
    return result


def read_reviewed(path, expected):
    with Path(path).open("rb") as stream:
        wire = stream.read(8 * 1024 * 1024 + 1)
    if len(wire) > 8 * 1024 * 1024:
        raise ValueError("Native Schema exceeds the input bound")
    try:
        value = json.loads(wire, object_pairs_hook=_unique_pairs)
        digest = semantic_digest(value)
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid native Schema JSON") from exc
    if digest != expected:
        raise ValueError("Native schemas differ from the reviewed Codex 0.144.4 inputs")
    return value


def extract(schema, definitions):
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in ("description", "title")}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    schema = clean(schema)
    needed = {}

    def visit(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference:
                if not reference.startswith("#/definitions/"):
                    raise ValueError("Only local native Schema references are supported")
                name = reference.split("/")[-1]
                if name not in needed:
                    needed[name] = clean(definitions[name])
                    visit(needed[name])
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(schema)
    return {"$schema": "http://json-schema.org/draft-07/schema#", **schema, "definitions": needed}


def main(source, target, *, control=False):
    source = Path(source)
    methods = CONTROL_METHODS if control else METHODS
    filenames = {"ClientRequest.json", *methods.values()}
    documents = {
        name: read_reviewed(source / name, SEMANTIC_SHA256[name]) for name in sorted(filenames)
    }
    client = documents["ClientRequest.json"]
    schemas = {}
    for method, filename in methods.items():
        request = next(
            entry for entry in client["oneOf"] if entry["properties"]["method"]["enum"] == [method]
        )
        response = documents[filename]
        schemas[method] = {
            "request": extract(request["properties"]["params"], client["definitions"]),
            "response": extract(
                {k: v for k, v in response.items() if k != "definitions"},
                response.get("definitions", {}),
            ),
        }
    output = {
        "external_version": "0.144.4",
        "generator": "codex app-server generate-json-schema (no --experimental)",
        "source_sha256": {name: SEMANTIC_SHA256[name] for name in sorted(filenames)}
        if control
        else INPUT_SHA256,
        "schemas": schemas,
    }
    if control:
        output["source_digest_kind"] = "canonical-json-utf8-sorted-keys"
    Path(target).write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--control", action="store_true")
    args = parser.parse_args()
    main(args.source, args.target, control=args.control)
