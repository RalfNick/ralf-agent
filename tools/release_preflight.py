"""Offline pre-publication checks and handoff of the exact frozen Alpha artifacts.

Does not import the SDK, build a package, run platform gates, upload or publish.
"""

import argparse
import email
import json
import shutil
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

import release_gate as gate


def prepare(wheel, sdist, source, spec, output):
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "status": "failed",
        "version": spec["version"],
        "artifact_source_commit": spec["artifact_source_commit"],
        "spec_sha256": gate.digest(spec),
        "deferred": spec["deferred"],
        "publication_ready": False,
        "pending_external": [
            "native AMD64 report",
            "remote CI",
            "publication authorization and permissions",
            "published installation check",
            "independent user feedback",
        ],
        "public_upload": False,
    }
    try:
        distribution = gate.distribution_name(spec)
        result["distribution_name"] = distribution
        with tempfile.TemporaryDirectory(prefix="ralf-release-preflight-") as temporary:
            gate.prepare_artifacts(wheel, sdist, Path(temporary), spec)
        project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
        if project["name"] != distribution or project["version"] != spec["version"]:
            raise gate.GateError("source_version_mismatch")
        package = source / "src/ralf_agent"
        products = {
            p.relative_to(package).as_posix(): gate.file_digest(p)
            for p in package.rglob("*")
            if p.is_file() and p.suffix in (".py", ".json")
        }
        if (
            len(products) != spec["product_files"]
            or gate.digest(products) != spec["product_tree_sha256"]
        ):
            raise gate.GateError("source_product_tree_mismatch")
        prefix = f"{distribution.replace('-', '_')}-{spec['version']}"
        with zipfile.ZipFile(wheel) as archive, tarfile.open(sdist, "r:gz") as tar:
            metadata = email.message_from_bytes(archive.read(prefix + ".dist-info/METADATA"))
            if metadata["License-Expression"] != "Apache-2.0":
                raise gate.GateError("license_expression_mismatch")
            for name in ("LICENSE", "NOTICE"):
                original = (source / name).read_bytes()
                if (
                    archive.read(prefix + ".dist-info/licenses/" + name) != original
                    or tar.extractfile(prefix + "/" + name).read() != original
                ):
                    raise gate.GateError("license_content_mismatch:" + name)
        pending = output / "candidate.pending"
        pending.mkdir()
        for artifact in (wheel, sdist):
            shutil.copyfile(artifact, pending / artifact.name)
        actual = {p.name: gate.file_digest(p) for p in pending.iterdir()}
        if actual != spec["artifacts"]:
            raise gate.GateError("copied_artifact_sha256_mismatch")
        pending.rename(output / "candidate")
        (output / "candidate.sha256").write_text(
            "".join(f"{sha}  candidate/{name}\n" for name, sha in sorted(actual.items()))
        )
        result.update(
            status="passed_local_preflight", artifacts=actual, product_files=len(products)
        )
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        (output / "preflight.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=gate.HERE / "release_gate_manifest.json")
    for name in ("wheel", "sdist", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(
            args.wheel.resolve(),
            args.sdist.resolve(),
            gate.HERE.parent,
            gate.read_spec(args.manifest),
            args.output.resolve(),
        )
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
