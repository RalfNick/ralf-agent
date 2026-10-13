"""Extract the reviewed subset from Codex 0.144.4's generated stable schemas.

Generate inputs with: codex app-server generate-json-schema --out PRIVATE_DIR
This utility reads schemas; it never starts Codex or a business task.
"""

import hashlib
import json
import sys
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


def main(source, target):
    source = Path(source)
    for filename, expected in INPUT_SHA256.items():
        if hashlib.sha256((source / filename).read_bytes()).hexdigest() != expected:
            raise ValueError("Native schemas differ from the reviewed Codex 0.144.4 inputs")
    client = json.loads((source / "ClientRequest.json").read_text())
    schemas, inputs = {}, {}
    inputs["ClientRequest.json"] = hashlib.sha256(
        (source / "ClientRequest.json").read_bytes()
    ).hexdigest()
    for method, filename in METHODS.items():
        request = next(
            entry for entry in client["oneOf"] if entry["properties"]["method"]["enum"] == [method]
        )
        params = request["properties"]["params"]
        response = json.loads((source / filename).read_text())
        inputs[filename] = hashlib.sha256((source / filename).read_bytes()).hexdigest()
        schemas[method] = {
            "request": extract(params, client["definitions"]),
            "response": extract(
                {k: v for k, v in response.items() if k != "definitions"},
                response.get("definitions", {}),
            ),
        }
    output = {
        "external_version": "0.144.4",
        "generator": "codex app-server generate-json-schema (no --experimental)",
        "source_sha256": inputs,
        "schemas": schemas,
    }
    Path(target).write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:])
