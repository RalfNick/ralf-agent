"""Explicit installed adapter checks; no configuration means no testing I/O."""

import argparse
import asyncio
import json

from .adapter_contracts import AdapterContractSuite
from .errors import CloseIncomplete, ValidationError


async def _execute(arguments):
    suite = AdapterContractSuite(
        role=arguments.role, contract_version=arguments.contract_version, profile=arguments.profile
    )
    fixture = None
    if arguments.offline:
        if arguments.role == "knowledge-retriever":
            from .adapter_contract_reference import offline_knowledge_fixture

            fixture = offline_knowledge_fixture()
        else:
            from .session_adapter_contract_reference import offline_session_fixture

            fixture = offline_session_fixture()
    try:
        return await suite.run(fixture=fixture, evidence_dir=arguments.evidence_dir)
    finally:
        await suite.aclose()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check adapter contracts. Use --offline explicitly for an independent SQLite fixture."
    )
    parser.add_argument("--role", default="knowledge-retriever")
    parser.add_argument("--contract-version", default="1")
    parser.add_argument("--profile", default="core", help="core, or session-store receipts")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--evidence-dir", help="New private directory for retained case evidence")
    arguments = parser.parse_args(argv)
    try:
        report = asyncio.run(_execute(arguments))
    except CloseIncomplete as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "cleanup_incomplete",
                    "contract_report": exc.report.get("contract_report"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    except ValidationError:
        print(json.dumps({"status": "invalid", "reason": "invalid_contract_configuration"}))
        return 2
    value = report.to_dict()
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0 if value["status"] in {"passed", "not_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
