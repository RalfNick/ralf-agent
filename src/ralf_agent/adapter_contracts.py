"""Fixed adapter checks without an additional execution authority.

Fixtures prepare sources and faults. The role implementation supplies verdicts.
Observation cancellation drains the actual role task and its original cleanup
before the suite releases its own temporary workspace.
"""

import asyncio
import hashlib
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from .adapter_contract_catalog import catalog_for, catalog_for_case
from .adapter_contract_types import (
    AdapterContractCaseResult,
    AdapterContractCleanupPending,
    AdapterContractEvidence,
    AdapterContractReport,
)
from .errors import CloseIncomplete, ValidationError
from .types import canonical


async def _run_case(case_id, fixture, workspace):
    catalog = catalog_for_case(case_id)
    if catalog.role == "knowledge-retriever":
        from .knowledge_adapter_contract import run_knowledge_case

        return await run_knowledge_case(case_id, fixture, workspace)
    if catalog.role == "session-store":
        from .session_adapter_contract import run_session_case

        return await run_session_case(case_id, fixture, workspace)
    from .facts_adapter_contract import run_facts_case

    return await run_facts_case(case_id, fixture, workspace)


async def _drain_cancelled(task):
    task.cancel()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    if task.done():
        try:
            task.result()
        except AdapterContractCleanupPending as pending:
            return pending
        except BaseException:
            pass
    return None


def _evidence_path(value):
    if value is None:
        return None
    if not isinstance(value, (str, Path)) or (
        isinstance(value, str) and (not value.strip() or "\x00" in value)
    ):
        raise ValidationError("Contract evidence requires an explicit directory path")
    return Path(value)


def _physical_identity(path):
    try:
        value = path.stat(follow_symlinks=False)
        return value.st_dev, value.st_ino
    except OSError:
        raise ValidationError("Contract evidence workspace is unavailable") from None


def _archive(root, workspace, result, root_identity, workspace_identity):
    data = canonical(result.to_dict()).encode("utf-8")
    if len(data) > 1048576:
        raise ValidationError("Contract evidence exceeds its bounded record size")
    directories = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    root_fd = workspace_fd = None
    try:
        if workspace.is_symlink() or workspace.parent != root:
            raise ValidationError("Contract evidence workspace changed during execution")
        root_fd = os.open(root, directories)
        value = os.fstat(root_fd)
        if (value.st_dev, value.st_ino) != root_identity:
            raise ValidationError("Contract evidence root changed during execution")
        workspace_fd = os.open(result.case_id, directories, dir_fd=root_fd)
        value = os.fstat(workspace_fd)
        if (value.st_dev, value.st_ino) != workspace_identity:
            raise ValidationError("Contract evidence workspace changed during execution")
        descriptor = os.open("result.json", flags, 0o600, dir_fd=workspace_fd)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except OSError:
        raise ValidationError("Contract evidence could not be retained") from None
    finally:
        if workspace_fd is not None:
            os.close(workspace_fd)
        if root_fd is not None:
            os.close(root_fd)
    return replace(
        result,
        evidence=(
            AdapterContractEvidence(
                f"{result.case_id}/result.json", hashlib.sha256(data).hexdigest(), len(data)
            ),
        ),
    )


@dataclass
class _PendingCleanup:
    original: AdapterContractCleanupPending
    task: asyncio.Task | None = None


@dataclass(frozen=True)
class AdapterContractSuite:
    """Explicit installed adapter role and profile contract version 1.

    An unconfigured run describes the cases without performing I/O. Supplying a
    fixture enables its actual setup and checks. No remote backend, model or
    offline fixture is selected implicitly. If cleanup fails, keep this suite
    and call ``await suite.aclose()`` on the original event loop to retry that
    same owner; neither cases nor successfully closed resources are repeated.
    """

    role: str = "knowledge-retriever"
    contract_version: str = "1"
    profile: str = field(default="core", kw_only=True)
    _pending: list = field(default_factory=list, init=False, repr=False, compare=False)
    _temporaries: list = field(default_factory=list, init=False, repr=False, compare=False)
    _running: bool = field(default=False, init=False, repr=False, compare=False)
    _closing: bool = field(default=False, init=False, repr=False, compare=False)
    _loop: object = field(default=None, init=False, repr=False, compare=False)
    _cleanup_report: object = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        catalog_for(self.role, self.contract_version, self.profile)

    @property
    def case_ids(self):
        return catalog_for(self.role, self.contract_version, self.profile).case_ids

    def _report(self, **kwargs):
        return AdapterContractReport(role=self.role, profile=self.profile, **kwargs)

    @property
    def pending_cleanup(self):
        return bool(self._pending or self._temporaries)

    def _incomplete(self):
        return CloseIncomplete(
            {
                "kind": "adapter-contract-cleanup",
                "pending_owners": len(self._pending),
                "temporary_workspaces": len(self._temporaries),
                "contract_report": (
                    None if self._cleanup_report is None else self._cleanup_report.to_dict()
                ),
            }
        )

    def _retain(self, pending, case_id, completed, temporary):
        result = pending.result
        if result.case_id != case_id:
            result = AdapterContractCaseResult(
                case_id, "failed", "cleanup_failed", {"cleanup_complete": False}
            )
        self._pending.append(_PendingCleanup(pending))
        if temporary is not None:
            self._temporaries.append(temporary)
        remainder = [
            AdapterContractCaseResult(value, "not_verified", "case_not_verified")
            for value in self.case_ids[len(completed) + 1 :]
        ]
        report = self._report(cases=(*completed, result, *remainder))
        object.__setattr__(self, "_cleanup_report", report)
        return result, remainder

    async def run(self, fixture=None, *, evidence_dir=None) -> AdapterContractReport:
        destination = _evidence_path(evidence_dir)
        if fixture is None:
            return self._report(
                cases=tuple(
                    AdapterContractCaseResult(case_id, "not_verified", "adapter_not_configured")
                    for case_id in self.case_ids
                ),
                status="not_run",
                reason="adapter_not_configured",
            )
        if self._running or self._closing or self.pending_cleanup:
            raise ValidationError("Finish original adapter contract cleanup before another run")
        object.__setattr__(self, "_running", True)
        object.__setattr__(self, "_loop", asyncio.get_running_loop())
        temporary = None
        try:
            if destination is None:
                temporary = tempfile.TemporaryDirectory(prefix="ralf-adapter-contract-")
                root = Path(temporary.name)
            else:
                try:
                    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
                except OSError:
                    raise ValidationError(
                        "Contract evidence directory must be newly created"
                    ) from None
                root = destination.resolve()
            root_identity = _physical_identity(root)
            results = []
            for case_id in self.case_ids:
                workspace = root / case_id
                try:
                    workspace.mkdir(mode=0o700)
                except OSError:
                    raise ValidationError("Contract workspace could not be created") from None
                workspace_identity = _physical_identity(workspace)
                operation = asyncio.create_task(_run_case(case_id, fixture, workspace))
                remainder = None
                try:
                    result = await asyncio.shield(operation)
                except asyncio.CancelledError:
                    pending = await _drain_cancelled(operation)
                    if pending is not None:
                        self._retain(pending, case_id, results, temporary)
                        temporary = None
                    raise
                except AdapterContractCleanupPending as pending:
                    result, remainder = self._retain(pending, case_id, results, temporary)
                    temporary = None
                except Exception:
                    result = AdapterContractCaseResult(case_id, "failed", "case_failed")
                if (
                    type(result) is not AdapterContractCaseResult
                    or result.case_id != case_id
                    or result.evidence
                ):
                    result = AdapterContractCaseResult(case_id, "failed", "invalid_case_result")
                if destination is not None:
                    result = _archive(root, workspace, result, root_identity, workspace_identity)
                results.append(result)
                if remainder is not None:
                    results.extend(remainder)
                    break
            report = self._report(cases=tuple(results))
            object.__setattr__(self, "_cleanup_report", report)
            return report
        finally:
            object.__setattr__(self, "_running", False)
            if temporary is not None:
                try:
                    temporary.cleanup()
                except OSError:
                    self._temporaries.append(temporary)
                    raise self._incomplete() from None
            if not self.pending_cleanup:
                object.__setattr__(self, "_loop", None)

    async def aclose(self):
        """Retry retained original cleanup; observation cancel drains real work."""
        if self._running or self._closing:
            raise self._incomplete()
        if not self.pending_cleanup:
            return
        if asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Adapter contract cleanup requires its original event loop")
        object.__setattr__(self, "_closing", True)
        cancelled = False
        try:
            while self._pending:
                pending = self._pending[0]
                if pending.task is None:
                    pending.task = asyncio.create_task(self._cleanup_once(pending.original))
                while not pending.task.done():
                    try:
                        await asyncio.shield(pending.task)
                    except asyncio.CancelledError:
                        cancelled = True
                    except Exception:
                        break
                try:
                    pending.task.result()
                except BaseException:
                    pending.task = None
                    if cancelled:
                        raise asyncio.CancelledError from None
                    raise self._incomplete() from None
                self._pending.pop(0)
            while self._temporaries:
                try:
                    self._temporaries[0].cleanup()
                except OSError:
                    if cancelled:
                        raise asyncio.CancelledError from None
                    raise self._incomplete() from None
                self._temporaries.pop(0)
            object.__setattr__(self, "_loop", None)
            if cancelled:
                raise asyncio.CancelledError from None
        finally:
            object.__setattr__(self, "_closing", False)

    @staticmethod
    async def _cleanup_once(pending):
        result = await pending.cleanup()
        if result is not None:
            raise ValidationError("Original adapter contract cleanup must complete with None")
