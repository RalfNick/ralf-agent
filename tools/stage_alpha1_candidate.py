"""Read exact original Alpha artifacts from a private draft; never publish it."""

import argparse
import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

import release_gate

MAX_ASSET_BYTES = 16 * 1024 * 1024
STAGING_PREFIXES = {
    "0.1.0a1": "ralf-alpha1-private-stage-",
    "0.1.0a2": "ralf-alpha2-private-stage-",
}


class AssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise RuntimeError("unsafe_asset_redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


def stage(release_id, output, spec, fetch_json, fetch_blob):
    output.mkdir(parents=True, exist_ok=False)
    proof = {"status": "failed", "release_id": release_id, "public_release": False}
    try:
        release = fetch_json(release_id)
        prefix = STAGING_PREFIXES.get(spec.get("version"))
        if (
            prefix is None
            or release.get("id") != release_id
            or release.get("draft") is not True
            or release.get("published_at") is not None
            or not release.get("tag_name", "").startswith(prefix)
        ):
            raise RuntimeError("private_staging_release_mismatch")
        assets = release["assets"]
        if len(assets) != len(spec["artifacts"]) or {a["name"] for a in assets} != set(
            spec["artifacts"]
        ):
            raise RuntimeError("staging_asset_names_mismatch")
        pending = {}
        actual = {}
        for asset in assets:
            size = asset["size"]
            if (
                asset.get("state") != "uploaded"
                or type(size) is not int
                or not 0 < size <= MAX_ASSET_BYTES
            ):
                raise RuntimeError("staging_asset_metadata_mismatch")
            content = fetch_blob(asset["id"])
            digest = hashlib.sha256(content).hexdigest()
            if len(content) != size or digest != spec["artifacts"][asset["name"]]:
                raise RuntimeError("staging_asset_bytes_mismatch")
            pending[asset["name"]] = content
            actual[asset["name"]] = digest
        candidate = output / "candidate.pending"
        candidate.mkdir()
        for name, content in pending.items():
            (candidate / name).write_bytes(content)
        candidate.rename(output / "candidate")
        proof.update(
            status="verified_original_candidate",
            draft=True,
            tag=release["tag_name"],
            artifacts=actual,
        )
    except Exception as error:
        proof.update(error_type=type(error).__name__, http_status=getattr(error, "code", None))
        raise
    finally:
        (output / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if args.release_id <= 0 or not token:
        parser.error("positive release id and GITHUB_TOKEN are required")
    opener = urllib.request.build_opener(AssetRedirect())

    def fetch(path, accept):
        request = urllib.request.Request(
            "https://api.github.com/repos/RalfNick/ralf-agent/" + path,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": accept,
                "User-Agent": "ralf-private-staging",
            },
        )
        with opener.open(request, timeout=60) as response:
            content = response.read(MAX_ASSET_BYTES + 1)
        if len(content) > MAX_ASSET_BYTES:
            raise RuntimeError("staging_response_too_large")
        return content

    try:
        result = stage(
            args.release_id,
            args.output,
            release_gate.read_spec(),
            lambda identifier: json.loads(
                fetch("releases/" + str(identifier), "application/vnd.github+json")
            ),
            lambda identifier: fetch(
                "releases/assets/" + str(identifier), "application/octet-stream"
            ),
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "http_status": getattr(error, "code", None),
                }
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
