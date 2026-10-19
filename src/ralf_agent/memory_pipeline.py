"""Opt-in automatic memory over managed Runs and interchangeable CAS stores."""

import copy
import inspect
import time
from dataclasses import asdict

from .errors import DefinitionMismatch, RalfError, ValidationError
from .memory import memory_call
from .memory_extraction import MemoryAdmissionPolicy, RuleMemoryExtractor
from .ports import is_async_callable
from .recall import RecallPage, RecallQuery
from .task_controls import _binding
from .types import canonical, digest


async def _await(value):
    return await value if inspect.isawaitable(value) else value


class MemoryPipeline:
    """Business result and memory receipt are separate; all resources borrowed.

    Facts are append-only sourced observations with deterministic storage keys.
    Multi-fact admission is resumable rather than globally transactional.
    """

    def __init__(
        self, engine, *, memory=None, policy=None, extractor=None, namespace="auto-memory"
    ):
        self.engine = engine
        self.memory = engine.memory if memory is None else memory
        self.policy = policy or MemoryAdmissionPolicy()
        self.extractor = extractor or RuleMemoryExtractor(self.policy)
        if not isinstance(self.policy, MemoryAdmissionPolicy):
            raise ValidationError("Memory admission requires a host policy")
        if not isinstance(namespace, str) or not namespace.strip() or len(namespace) > 128:
            raise ValidationError("Memory namespace must be bounded text")
        self.namespace = namespace
        self._scope = asdict(engine.scope)
        self._backend = self.memory.backend_id
        if not isinstance(self._backend, str) or not self._backend:
            raise ValidationError("Memory requires a stable backend identity")
        self._methods = {}
        for name in ("put_fact", "recall", "validate_facts"):
            method = getattr(self.memory, name, None)
            if not callable(method):
                raise ValidationError("Automatic memory requires CAS and bounded recall/validation")
            self._methods[name] = _binding(method)
        if not is_async_callable(getattr(self.extractor, "extract", None)):
            raise ValidationError("Memory extractor requires an async extract method")
        self._extract_binding = _binding(self.extractor.extract)
        self._policy_binding = _binding(self.policy.validate)
        self._release = copy.deepcopy(
            {
                "backend": self._backend,
                "namespace": namespace,
                "policy": self.policy.identity,
                "extractor": self.extractor.identity,
            }
        )
        canonical(self._release)

    @property
    def identity(self):
        self._check()
        return copy.deepcopy(self._release)

    def _check(self):
        if (
            self.memory.backend_id != self._backend
            or asdict(self.engine.scope) != self._scope
            or self.namespace != self._release["namespace"]
            or digest(self.policy.identity) != digest(self._release["policy"])
            or _binding(self.policy.validate) != self._policy_binding
            or digest(self.extractor.identity) != digest(self._release["extractor"])
            or _binding(self.extractor.extract) != self._extract_binding
            or any(_binding(getattr(self.memory, n, None)) != b for n, b in self._methods.items())
        ):
            raise DefinitionMismatch("Memory pipeline registration changed")

    async def _source(self, run_id):
        self._check()
        result = await _await(self.engine.status(run_id))
        self._check()
        if result.state != "succeeded" or result.consistency != "authoritative":
            raise ValidationError("Memory source must be an authoritative successful Run")
        evidence = {
            "run_id": run_id,
            "scope": self._scope,
            "revision": result.state_revision,
            "result": copy.deepcopy(result.result),
        }
        if len(canonical(evidence)) > 65536:
            raise ValidationError("Memory source exceeds its bounded evidence limit")
        return evidence

    async def _same_source(self, evidence):
        if digest(await self._source(evidence["run_id"])) != digest(evidence):
            raise DefinitionMismatch("Memory source changed during extraction or admission")

    def _fresh(self):
        expiry = self.policy.identity["expires_at"]
        if expiry is not None and expiry <= time.time():
            raise ValidationError("Memory admission policy has expired")

    async def _duplicate(self, key, value, namespace):
        cursor = None
        seen, snapshot = set(), None
        for _ in range(32):
            self._check()
            page = await memory_call(
                self.memory.recall,
                self.engine.scope,
                namespace,
                RecallQuery(max_items=16, max_chars=65536, scan_limit=256, text=key, cursor=cursor),
            )
            self._check()
            if not isinstance(page, RecallPage):
                raise ValidationError("Memory recall must return a completed bounded page")
            page = RecallPage(**asdict(page))
            if len(page.items) > 16 or page.used_chars > 65536 or page.scanned > 256:
                raise ValidationError("Memory duplicate recall exceeded its page allowance")
            if snapshot is not None and page.snapshot_id != snapshot:
                raise ValidationError("Memory duplicate recall changed snapshot")
            snapshot = page.snapshot_id
            for fact in page.items:
                if fact.get("key") == key:
                    if fact.get("version") != 1 or canonical(fact.get("value")) != canonical(value):
                        raise ValidationError("Memory observation conflicts with an existing fact")
                    outcome = await memory_call(
                        self.memory.validate_facts, self.engine.scope, namespace, [fact]
                    )
                    self._check()
                    if outcome is not None:
                        raise ValidationError("Memory validation must complete with None")
                    return 1
            cursor = page.next_cursor
            if cursor is None:
                break
            if cursor in seen:
                raise ValidationError("Memory duplicate recall repeated a cursor")
            seen.add(cursor)
        raise ValidationError("Memory duplicate is unavailable, expired or exceeds recall bounds")

    async def consolidate(self, source_run_id, *, command_id):
        if not isinstance(command_id, str) or not command_id.strip() or len(command_id) > 256:
            raise ValidationError("Memory consolidation requires a bounded command identity")
        evidence = await self._source(source_run_id)
        self._fresh()
        # Bind the caller's command independently of model use. A rule extraction
        # must not silently admit another source under the same command ID.
        command_value = {
            "kind": "memory-command-binding",
            "source_digest": digest(evidence),
            "release_digest": digest(self._release),
        }
        command_namespace = self.namespace + ":commands"
        command_key = "command:" + digest(command_id)
        try:
            version = await memory_call(
                self.memory.put_fact,
                self.engine.scope,
                command_namespace,
                command_key,
                command_value,
                expected_version=0,
            )
            self._check()
            if type(version) is not int or version != 1:
                raise ValidationError("Memory command CAS returned an invalid version")
        except ValidationError:
            await self._duplicate(command_key, command_value, command_namespace)
        await self._same_source(evidence)
        try:
            extracted = await self.extractor.extract(
                copy.deepcopy(evidence), self.engine, command_id=command_id
            )
        except RalfError:
            raise
        except Exception:
            raise ValidationError("Memory extractor failed") from None
        if type(extracted) not in {tuple, list} or len(extracted) != 2:
            if inspect.isgenerator(extracted) or inspect.iscoroutine(extracted):
                extracted.close()
            raise ValidationError("Memory extractor must return a completed proposals/Run pair")
        proposals, extraction_run = extracted
        if extraction_run is not None and (
            not isinstance(extraction_run, str)
            or not extraction_run.strip()
            or len(extraction_run) > 1024
        ):
            raise ValidationError("Memory extractor returned an invalid Run identity")
        await self._same_source(evidence)
        if not isinstance(proposals, list) or len(proposals) > self.policy.identity["max_facts"]:
            raise ValidationError("Memory extraction exceeded its proposal contract")
        validated = [self.policy.validate(p, evidence) for p in proposals]
        if len({p.key for p in validated}) != len(validated):
            raise ValidationError("Memory extraction contains duplicate logical keys")
        source_digest, receipts = digest(evidence), []
        for proposal in validated:
            await self._same_source(evidence)
            self._fresh()
            key = "auto:" + digest([source_run_id, proposal.key])
            value = {
                **proposal.to_dict(),
                "source_run_id": source_run_id,
                "source_digest": source_digest,
                "release_digest": digest(self._release),
                "trust": "source-observation",
                "extraction_run_id": extraction_run,
            }
            duplicate = False
            try:
                version = await memory_call(
                    self.memory.put_fact,
                    self.engine.scope,
                    self.namespace,
                    key,
                    value,
                    expected_version=0,
                    expires_at=self.policy.identity["expires_at"],
                )
                self._check()
                if type(version) is not int or version != 1:
                    raise ValidationError("Memory CAS returned an invalid initial version")
            except ValidationError:
                version = await self._duplicate(key, value, self.namespace)
                duplicate = True
            # A returned CAS version alone is not a current observation. Validate
            # first writes too, including expiry/deletion during an awaited write.
            self._fresh()
            outcome = await memory_call(
                self.memory.validate_facts,
                self.engine.scope,
                self.namespace,
                [
                    {
                        "key": key,
                        "value": value,
                        "version": version,
                        "expires_at": self.policy.identity["expires_at"],
                    }
                ],
            )
            self._check()
            if outcome is not None:
                raise ValidationError("Memory admission validation must complete with None")
            await self._same_source(evidence)
            self._fresh()
            receipts.append(
                {
                    "key": proposal.key,
                    "storage_key": key,
                    "version": version,
                    "duplicate": duplicate,
                }
            )
        return {
            "status": "completed",
            "source_run_id": source_run_id,
            "source_digest": source_digest,
            "extraction_run_id": extraction_run,
            "facts": receipts,
            "release_digest": digest(self._release),
        }

    async def run(self, definition, input_value, *, command_id, **submit_options):
        self._check()
        handle = await _await(
            self.engine.submit(definition, input_value, command_id=command_id, **submit_options)
        )
        task = await _await(self.engine.drive(handle.run_id))
        if task.state != "succeeded":
            memory = {"status": "skipped", "reason": "source_not_succeeded"}
        else:
            try:
                memory = await self.consolidate(handle.run_id, command_id=command_id + ":memory")
            except RalfError as exc:
                memory = {
                    "status": "failed",
                    "code": getattr(exc, "code", "memory_failed"),
                    "source_run_id": handle.run_id,
                }
        return {"task": asdict(task), "memory": memory}
