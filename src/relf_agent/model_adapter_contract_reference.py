"""Independent offline supplier and application-owned business data.

SQLite records supplier observations, never model idempotency or Run authority.
The provider implements the async core port directly and consumes real requests.
"""

import asyncio
import json
import os
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from weakref import WeakKeyDictionary

from .errors import AuthorizationDenied, DefinitionMismatch, ProviderError, ValidationError
from .types import ModelResponse, Scope, ToolCall, canonical, digest

_COUNTS = (
    "model_calls",
    "request_count",
    "response_count",
    "close_calls",
    "backend_switches",
    "identity_checks",
    "method_checks",
    "consumer_runs",
    "rejection_checks",
    "received_count",
    "adopted_count",
    "tool_calls",
    "write_count",
    "approval_count",
    "duplicate_checks",
    "reservation_checks",
    "settlement_checks",
    "reopen_calls",
)


def _detached(value):
    try:
        return json.loads(canonical(value))
    except (RecursionError, UnicodeError):
        raise ValidationError("Reference supplier requires bounded finite JSON") from None


class ReferenceModelSource:
    """Application-owned supplier audit with a pinned durable and physical source."""

    def __init__(self, path):
        self.path = self._original_path = str(Path(path).resolve())
        self._closed = False
        self._file_unavailable = False
        self._file_descriptor = None
        self._dependents = []
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS model_resource (singleton INTEGER PRIMARY KEY CHECK(singleton=1),dataset_id TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS supplier_requests (id INTEGER PRIMARY KEY AUTOINCREMENT,messages TEXT NOT NULL,tools TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS supplier_responses (id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER NOT NULL,response TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS supplier_settings (singleton INTEGER PRIMARY KEY CHECK(singleton=1),kind TEXT NOT NULL,value TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS supplier_audit (kind TEXT PRIMARY KEY,count INTEGER NOT NULL);"
                "CREATE TABLE IF NOT EXISTS business_documents (workspace TEXT,principal TEXT,incident TEXT,recommendation TEXT NOT NULL,source_uri TEXT NOT NULL,version INTEGER NOT NULL,PRIMARY KEY(workspace,principal,incident));"
                "CREATE TABLE IF NOT EXISTS business_effects (effect_key TEXT PRIMARY KEY,result TEXT NOT NULL);"
            )
            with connection:
                connection.execute(
                    "INSERT OR IGNORE INTO model_resource VALUES (1,?)", (uuid.uuid4().hex,)
                )
                self._dataset_id = connection.execute(
                    "SELECT dataset_id FROM model_resource WHERE singleton=1"
                ).fetchone()[0]
        finally:
            connection.close()
        descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            value = os.fstat(descriptor)
            self._file_identity = value.st_dev, value.st_ino
            self._check_file()
        except BaseException:
            os.close(descriptor)
            raise
        self._file_descriptor = descriptor
        self.backend_id = "external-sqlite-model-v1:" + digest(
            [self._original_path, self._dataset_id]
        )

    def _check_file(self):
        if self._file_unavailable:
            raise DefinitionMismatch("Original supplier source is unavailable")
        try:
            value = os.stat(self._original_path, follow_symlinks=False)
        except OSError:
            self._file_unavailable = True
            raise DefinitionMismatch("Original supplier source is unavailable") from None
        if not stat.S_ISREG(value.st_mode) or (value.st_dev, value.st_ino) != self._file_identity:
            self._file_unavailable = True
            raise DefinitionMismatch("Actual supplier file changed")

    def _check(self):
        if self._closed:
            raise ValidationError("Reference supplier source is closed")
        if self.path != self._original_path:
            raise DefinitionMismatch("Actual supplier path changed")
        self._check_file()

    @contextmanager
    def _connection(self, *, write=False):
        self._check_file()
        connection = sqlite3.connect(self._original_path)
        try:
            self._check_file()
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            row = connection.execute(
                "SELECT dataset_id FROM model_resource WHERE singleton=1"
            ).fetchone()
            if row is None or row[0] != self._dataset_id:
                self._file_unavailable = True
                raise DefinitionMismatch("Original supplier dataset changed")
            yield connection
            self._check_file()
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        self._check_file()

    @staticmethod
    def _count(connection, kind):
        connection.execute(
            "INSERT INTO supplier_audit VALUES (?,1) ON CONFLICT(kind) DO UPDATE SET count=count+1",
            (kind,),
        )

    def count(self, kind):
        self._check()
        with self._connection(write=True) as connection:
            self._count(connection, kind)

    def configure(self, kind, value):
        self._check()
        if type(value) is not dict:
            raise ValidationError("Supplier configuration requires a JSON object")
        value = _detached(value)
        if kind == "output":
            if set(value) - {"output", "usage"} or "output" not in value:
                raise ValidationError("Output configuration requires output and optional usage")
            usage = value.get("usage")
            if usage is not None:
                if type(usage) is not dict or any(
                    type(usage[key]) is not int or usage[key] < 0
                    for key in ("input_tokens", "output_tokens")
                    if key in usage
                ):
                    raise ValidationError("Usage requires nonnegative token counts")
        elif kind == "invalid-output":
            if set(value) != {"invalid"} or value["invalid"] not in {"nan", "lazy", "deep"}:
                raise ValidationError("Invalid output must select nan, lazy or deep")
        elif kind == "tools":
            if (
                set(value) - {"name", "arguments", "call_id"}
                or not isinstance(value.get("name"), str)
                or not value["name"].strip()
                or type(value.get("arguments")) is not dict
                or value.get("call_id") is not None
                and (not isinstance(value["call_id"], str) or not value["call_id"].strip())
            ):
                raise ValidationError(
                    "Tool configuration requires name, arguments and optional call_id"
                )
        else:
            raise ValidationError("Unsupported supplier configuration")
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO supplier_settings VALUES (1,?,?) ON CONFLICT(singleton) DO UPDATE SET kind=excluded.kind,value=excluded.value",
                (kind, canonical(value)),
            )

    def settings(self):
        self._check()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT kind,value FROM supplier_settings WHERE singleton=1"
            ).fetchone()
        return (row[0], json.loads(row[1])) if row else ("business", {})

    def record_request(self, messages, tools):
        self._check()
        messages, tools = _detached(messages), _detached(tools)
        if (
            type(messages) is not list
            or type(tools) is not list
            or any(type(item) is not dict for item in messages + tools)
        ):
            raise ValidationError("Supplier request requires message and descriptor lists")
        with self._connection(write=True) as connection:
            cursor = connection.execute(
                "INSERT INTO supplier_requests(messages,tools) VALUES (?,?)",
                (canonical(messages), canonical(tools)),
            )
            self._count(connection, "request_count")
            self._count(connection, "model_calls")
            return cursor.lastrowid, messages, tools

    def record_response(self, request_id, response, *, invalid=None):
        self._check()
        observation = (
            {"invalid": invalid}
            if invalid
            else {
                "output": response.output,
                "tool_calls": [asdict(call) for call in response.tool_calls],
                "usage": response.usage,
            }
        )
        encoded = canonical(observation)
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT INTO supplier_responses(request_id,response) VALUES (?,?)",
                (request_id, encoded),
            )
            self._count(connection, "response_count")

    def requests(self):
        """Private read-only debugging; raw supplier data never enters suite reports."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT messages,tools FROM supplier_requests ORDER BY id"
            ).fetchall()
        return [{"messages": json.loads(row[0]), "tools": json.loads(row[1])} for row in rows]

    def audit(self):
        with self._connection() as connection:
            counts = dict(connection.execute("SELECT kind,count FROM supplier_audit"))
        return {key: counts.get(key, 0) for key in _COUNTS}

    def reopen(self):
        self._check()
        with self._connection(write=True) as connection:
            connection.execute("SELECT count(*) FROM supplier_requests").fetchone()
            self._count(connection, "reopen_calls")

    def seed(self):
        self._check()
        with self._connection(write=True) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO business_documents VALUES (?,?,?,?,?,1)",
                (
                    Scope().workspace,
                    Scope().principal,
                    "cache",
                    "Inspect connection pool before changing cache timeout.",
                    "business://runbooks/cache",
                ),
            )
            return cursor.rowcount

    def lookup(self, scope, incident):
        self._check()
        if not isinstance(scope, Scope) or not isinstance(incident, str) or not incident.strip():
            raise ValidationError("Business lookup requires trusted Scope and incident")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT recommendation,source_uri,version FROM business_documents WHERE workspace=? AND principal=? AND incident=?",
                (scope.workspace, scope.principal, incident),
            ).fetchone()
        return (
            {
                "incident": incident,
                "recommendation": row[0],
                "source_uri": row[1],
                "version": row[2],
            }
            if row
            else None
        )

    def record_resolution(self, context, incident):
        record = self.lookup(context.scope, incident)
        if record is None:
            raise ValidationError("Business record is absent; run explicit seed")
        result = {"recorded": True, **record}
        with self._connection(write=True) as connection:
            prior = connection.execute(
                "SELECT result FROM business_effects WHERE effect_key=?", (context.effect_key,)
            ).fetchone()
            if prior is not None:
                return json.loads(prior[0])
            connection.execute(
                "INSERT INTO business_effects VALUES (?,?)", (context.effect_key, canonical(result))
            )
            self._count(connection, "write_count")
        return result

    def close(self):
        if self._closed and not self._dependents:
            return
        try:
            while self._dependents:
                self._dependents[-1].close()
                self._dependents.pop()
            if not self._closed:
                try:
                    self.count("close_calls")
                except DefinitionMismatch:
                    pass
        finally:
            if self._file_descriptor is not None:
                os.close(self._file_descriptor)
                self._file_descriptor = None
            self._closed = True

    async def aclose(self):
        self.close()


def _receipts(messages):
    return [json.loads(message["content"]) for message in messages if message.get("role") == "tool"]


def _business_input(messages):
    content = next(
        (
            message.get("content")
            for message in messages
            if message.get("role") == "user"
            and not str(message.get("content", "")).startswith("Reference memory;")
        ),
        None,
    )
    try:
        value = json.loads(content) if isinstance(content, str) else content
    except ValueError:
        value = None
    value = value if type(value) is dict else {}
    task = value
    for _ in range(8):
        if "incident" in task:
            break
        nested = task.get("task")
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except ValueError:
                break
        if type(nested) is not dict:
            break
        task = nested
    incident = task.get("incident", "cache")
    members = []
    if type(value.get("results")) is dict:
        members = list(value["results"].values())
    elif type(value.get("prior")) is list:
        members = [
            item["result"] for item in value["prior"] if type(item) is dict and "result" in item
        ]
    elif "lookup" in value and "recommendation" in value:
        members = [value]
    if len(members) > 4 or not isinstance(incident, str) or not incident.strip():
        raise ValidationError("Business input exceeds declared incident/member bounds")
    return incident, members


class ReferenceSQLiteModelProvider:
    """Independent async core ModelProvider; every complete calls the supplier."""

    def __init__(self, source, *, variant="primary"):
        if not isinstance(source, ReferenceModelSource) or variant not in {"primary", "alternate"}:
            raise ValidationError("Provider requires its original source and explicit variant")
        self.source = self._original_source = source
        self.backend_id = source.backend_id
        self.variant = variant
        self._identity_version = "1"
        self._fault = None
        self._pauses = {}

    @property
    def identity(self):
        return {
            "kind": "independent-sqlite-model",
            "version": self._identity_version,
            "variant": self.variant,
            "source": self.backend_id,
        }

    def _check(self):
        if self.source is not self._original_source or self.source.backend_id != self.backend_id:
            raise DefinitionMismatch("Actual supplier backend changed")
        self.source._check()

    async def complete(self, messages, tools):
        self._check()
        request_id, messages, tools = self.source.record_request(messages, tools)
        gate = self._pauses.pop("complete", None)
        if gate is not None:
            gate[0].set()
            await gate[1].wait()
            self._check()
        if self._fault == "authorization-denied":
            raise AuthorizationDenied("Private supplier authorization denied")
        if self._fault == "provider-error":
            raise ProviderError("Private supplier error secret-value")
        kind, value = self.source.settings()
        invalid = None
        receipts = _receipts(messages)
        if kind == "output":
            response = ModelResponse(output=value["output"], usage=value.get("usage"))
        elif kind == "invalid-output":
            invalid = value["invalid"]
            if invalid == "nan":
                output = float("nan")
            elif invalid == "lazy":

                async def lazy():
                    return "not a completed JSON value"

                output = {"lazy": lazy()}
            else:
                output = []
                for _ in range(1500):
                    output = [output]
            response = ModelResponse(output=output)
        elif kind == "tools":
            if receipts:
                response = ModelResponse(output={"tool_receipts": receipts})
            else:
                names = [item.get("function", {}).get("name") for item in tools]
                if value["name"] not in names:
                    raise ValidationError("Configured supplier proposal has no actual descriptor")
                response = ModelResponse(
                    tool_calls=(ToolCall(value["name"], value["arguments"], value.get("call_id")),)
                )
        else:
            response = self._business_response(messages, tools, receipts)
        self.source.record_response(request_id, response, invalid=invalid)
        self._check()
        if self._fault == "response-lost":
            self._fault = None
            raise ConnectionError("Private supplier accepted response was lost")
        return response

    def _business_response(self, messages, tools, receipts):
        names = [item.get("function", {}).get("name") for item in tools]
        if "lookup_incident" in names:
            incident, members = _business_input(messages)
            if not receipts:
                if self.source.lookup(Scope(), incident) is None:
                    return ModelResponse(output={"status": "source_missing"})
                return ModelResponse(
                    tool_calls=(ToolCall("lookup_incident", {"incident": incident}),)
                )
            record = next(
                (item for item in receipts if type(item) is dict and "recommendation" in item), None
            )
            if record is None:
                raise ValidationError("Actual business lookup receipt is absent")
            references = []
            for message in messages:
                content = message.get("content")
                if isinstance(content, str) and content.startswith("Reference memory;"):
                    references.extend(
                        item
                        for item in json.loads(content.partition("\n")[2])
                        if "_knowledge" in item
                    )
            return ModelResponse(
                output={
                    **record,
                    "lookup": record,
                    "sources": references,
                    "members": members,
                    "supplier": self.variant,
                },
                usage={"input_tokens": 0, "output_tokens": 0},
            )
        users = [item.get("content") for item in messages if item.get("role") == "user"]
        return ModelResponse(
            output={"message_count": len(messages), "last_user": users[-1] if users else None}
        )


class OfflineModelFixture:
    def prepare(self, case_id, workspace):
        from .model_adapter_contract import (
            ModelContractPause,
            ModelContractResource,
            ModelContractSession,
        )

        source = ReferenceModelSource(Path(workspace) / "supplier.sqlite")
        try:
            provider = ReferenceSQLiteModelProvider(source)
            original_complete = provider.complete

            def fault(kind):
                if kind == "backend-swap":
                    source.count("backend_switches")
                    alternate = ReferenceModelSource(Path(workspace) / "alternate.sqlite")
                    source._dependents.append(alternate)
                    provider.source = alternate
                elif kind == "identity-drift":
                    provider._identity_version = "changed"
                elif kind == "method-drift":

                    async def changed(messages, tools):
                        return await original_complete(messages, tools)

                    provider.complete = changed
                elif kind == "reset":
                    provider.source = source
                    provider._identity_version = "1"
                    provider.complete = original_complete
                    provider._fault = None
                    while source._dependents:
                        source._dependents[-1].close()
                        source._dependents.pop()
                elif kind in {"provider-error", "authorization-denied", "response-lost"}:
                    provider._fault = kind
                else:
                    raise ValidationError("Unsupported reference supplier fault")

            def pause(operation):
                if operation != "complete":
                    raise ValidationError("Reference supplier pause requires complete")
                entered, released = asyncio.Event(), asyncio.Event()
                provider._pauses[operation] = entered, released

                async def wait_entered():
                    await entered.wait()

                async def release():
                    released.set()

                return ModelContractPause(wait_entered, release)

            return ModelContractSession(
                provider=provider,
                resources=(ModelContractResource(source, asynchronous=True),),
                configure=source.configure,
                inject_fault=fault,
                pause=pause,
                audit=source.audit,
                reopen=source.reopen,
            )
        except BaseException:
            source.close()
            raise


def offline_model_fixture():
    """Explicit pure selection; prepare opens each actual independent supplier."""
    return OfflineModelFixture()


class BusinessCompletionVerifier:
    identity = {"kind": "incident-receipt-verifier", "version": "1", "max_receipts": 16}

    def verify(self, request):
        from .completion import CompletionVerdict

        output = request.output
        incident = _business_input([{"role": "user", "content": request.task}])[0]
        if type(output) is dict and len(request.receipts) <= 16:
            for receipt in request.receipts:
                result = receipt["result"]
                if (
                    receipt["tool"] == "record_resolution"
                    and type(result) is dict
                    and result.get("recorded") is True
                    and receipt["arguments"] == {"incident": incident}
                    and result.get("incident") == incident
                    and output == {"tool_receipts": [result]}
                ):
                    return CompletionVerdict("accept")
                if _lookup_matches(output, receipt, incident):
                    return CompletionVerdict("accept")
        return CompletionVerdict(
            "reject", "Actual corresponding business lookup evidence is required"
        )


def _lookup_matches(output, receipt, incident):
    result = receipt["result"]
    return (
        type(output) is dict
        and type(result) is dict
        and receipt["tool"] == "lookup_incident"
        and receipt["arguments"] == {"incident": incident}
        and result.get("incident") == output.get("incident") == incident
        and output.get("lookup") == result
        and output.get("recommendation") == result.get("recommendation")
        and output.get("source_uri") == result.get("source_uri")
    )


class BusinessParentGate:
    identity = {
        "kind": "incident-member-receipt-gate",
        "version": "1",
        "max_children": 4,
        "max_receipts": 16,
    }

    def verify(self, request):
        from .parent_completion import ParentCompletionVerdict

        ids = []
        parent_incident = _business_input([{"role": "user", "content": request.task}])[0]
        if not 2 <= len(request.children) <= 4 or len(request.receipts) > 16:
            return ParentCompletionVerdict(
                "reject", feedback="Bounded business member evidence is required"
            )
        for child in request.children:
            incident, expected_members = _business_input(
                [{"role": "user", "content": child["input"]}]
            )
            if incident != parent_incident:
                return ParentCompletionVerdict(
                    "reject",
                    feedback="Business member input differs from the original parent incident",
                )
            matching = [
                receipt
                for receipt in request.receipts
                if receipt["run_id"] == child["run_id"]
                and _lookup_matches(child["result"], receipt, incident)
                and child["result"].get("members") == expected_members
                and any(
                    "model:" + digest([child["run_id"], final["action_id"]])
                    in receipt["consumed_by"]
                    and final["input_consumed"]
                    for final in child["final_models"]
                )
            ]
            if not matching:
                return ParentCompletionVerdict(
                    "reject", feedback="A business member has no consumed original lookup receipt"
                )
            ids.extend((child["id"], matching[0]["id"]))
        if type(request.candidate) is not dict or not any(
            request.candidate == child["result"] for child in request.children
        ):
            return ParentCompletionVerdict(
                "reject", feedback="Candidate differs from original business member result"
            )
        return ParentCompletionVerdict("accept", evidence_ids=tuple(dict.fromkeys(ids)))


class ReferenceBusinessRetriever:
    def __init__(self, source):
        self.source = source

    @property
    def identity(self):
        return {"kind": "incident-current-source", "version": "1", "source": self.source.backend_id}

    async def retrieve(self, scope, namespace, query):
        from .retrieval import RetrievalResult, RetrievedChunk

        record = self.source.lookup(scope, "cache")
        if namespace != "runbooks" or record is None or "cache" not in query.text.lower():
            return RetrievalResult((), "business-current", 2)
        item = RetrievedChunk(
            "cache",
            "cache:1",
            record["version"],
            "cache " + record["recommendation"],
            record["source_uri"],
            {"incident": "cache"},
            None,
            scope,
            namespace,
            1.0,
        )
        size = len(canonical([asdict(item)]))
        return RetrievalResult(
            (item,) if size <= query.max_chars else (),
            "business-current",
            size if size <= query.max_chars else 2,
        )

    async def validate(self, scope, namespace, items):
        from .retrieval import RetrievalQuery

        current = (await self.retrieve(scope, namespace, RetrievalQuery("cache"))).items
        names = (
            "document_id",
            "chunk_id",
            "version",
            "text",
            "source_uri",
            "metadata",
            "expires_at",
            "scope",
            "namespace",
        )
        if any(
            not any(
                all(getattr(item, name) == getattr(live, name) for name in names)
                for live in current
            )
            for item in items
        ):
            raise DefinitionMismatch("Disclosed business source changed")


def register_model_reference_components(registry, source=None, *, asynchronous=False, owned=True):
    """Lazy provider and unchanged business components through original BuildContext."""
    if type(asynchronous) is not bool or type(owned) is not bool or source is None and not owned:
        raise ValidationError("Borrowing requires the original host source and boolean ownership")
    sources = WeakKeyDictionary()

    def config(values):
        if (
            set(values) - {"path"}
            or "path" in values
            and (not isinstance(values["path"], str) or not values["path"].strip())
        ):
            raise ValidationError("Reference factory requires only a non-empty path")

    def selected(context, values):
        path = context.path(values.get("path", ".ralf/business.sqlite"))
        if source is not None:
            if source._original_path != path:
                raise ValidationError("Borrowed source path differs from explicit configuration")
            return (
                (context.own_async(source) if asynchronous else context.own(source))
                if owned
                else source
            )
        if context not in sources:
            created = ReferenceModelSource(path)
            try:
                sources[context] = (
                    context.own_async(created) if asynchronous else context.own(created)
                )
            except BaseException:
                created.close()
                raise
        elif sources[context]._original_path != path:
            raise ValidationError("Shared business factories require one source path")
        return sources[context]

    def tools(values, context):
        from .tools import ToolRegistry, ToolSpec

        actual_source = selected(context, values)
        result = ToolRegistry()
        schema = {
            "type": "object",
            "properties": {"incident": {"type": "string", "default": "cache"}},
            "additionalProperties": False,
        }

        def lookup(arguments, invocation):
            actual_source.count("tool_calls")
            record = actual_source.lookup(invocation.scope, arguments["incident"])
            if record is None:
                raise ValidationError("Business record is absent; run explicit seed")
            return record

        def write(arguments, invocation):
            actual_source.count("tool_calls")
            return actual_source.record_resolution(invocation, arguments["incident"])

        result.register(
            ToolSpec("lookup_incident", "Read the current incident runbook", schema), lookup
        )
        result.register(
            ToolSpec(
                "record_resolution",
                "Record approved resolution",
                schema,
                effect="idempotent_write",
                requires_approval=True,
            ),
            write,
        )
        return result

    def knowledge(values, context):
        from .retrieval import KnowledgeContext

        return KnowledgeContext(
            ReferenceBusinessRetriever(selected(context, values)),
            namespace="runbooks",
            limit=1,
            max_chars=4000,
        )

    def parent(values, context):
        from .parent_completion import ParentCompletionPolicy

        return {
            "business": ParentCompletionPolicy(
                BusinessParentGate(), max_receipts=16, max_evidence_children=4
            )
        }

    def planners(values, context):
        from .dag_planning import RuleDAGPlanner
        from .planning import RulePlanner

        return {"rule": RulePlanner(), "dag-rule": RuleDAGPlanner()}

    factories = (
        (
            "provider",
            "external-sqlite-model",
            lambda values, context: ReferenceSQLiteModelProvider(selected(context, values)),
        ),
        (
            "provider",
            "external-sqlite-model-alternate",
            lambda values, context: ReferenceSQLiteModelProvider(
                selected(context, values), variant="alternate"
            ),
        ),
        ("tools", "incident-tools", tools),
        ("knowledge", "incident-current-source", knowledge),
        ("verifier", "incident-receipts", lambda values, context: BusinessCompletionVerifier()),
        ("parent_completion_policies", "incident-members", parent),
        ("planners", "incident-rule", planners),
    )
    for role, name, factory in factories:
        if asynchronous:

            async def build(values, context, factory=factory):
                return factory(values, context)

            registry.register_async(role, name, build, validator=config)
        else:
            registry.register(role, name, factory, validator=config)
