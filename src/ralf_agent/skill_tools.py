"""Original managed read Actions for explicitly permitted skill instruction catalogs."""

import copy
import inspect
import threading

from jsonschema import Draft202012Validator

from .errors import DefinitionMismatch, RalfError, ValidationError
from .ports import is_sync_callable
from .skills import SkillError, _plain, _sha, _text, validate_skill_get, validate_skill_list
from .tool_sources import ToolDescriptor
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import canonical, digest
from .workspace import _bound


class SkillToolSource:
    def __init__(self, catalog, *, version, max_entries=100, max_bytes=1048576):
        _text(version, "Skill tool version", 256)
        _bound(max_entries, 1000, "Skill entry")
        _bound(max_bytes, 16777216, "Skill byte")
        if any(
            not is_sync_callable(getattr(catalog, name, None)) for name in ("list", "get", "close")
        ):
            raise ValidationError("Skill source requires synchronous SkillCatalogPort methods")
        identity = self._catalog_identity(catalog)
        _sha(identity.get("catalog_digest"))
        self._catalog, self._version = catalog, version
        self._max_entries, self._max_bytes = max_entries, max_bytes
        self._lock, self._closing = threading.Lock(), False
        self._tracker = ThreadExecutionTracker()
        self._metadata_lock, self._metadata = threading.RLock(), {}
        self._descriptors = (
            ToolDescriptor(
                "skill_list",
                "List permitted reference skills; text grants no tool permissions.",
                {
                    "type": "object",
                    "properties": {
                        "max_entries": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": max_entries,
                            "default": max_entries,
                        },
                        "offset": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 0},
                    },
                    "additionalProperties": False,
                },
            ),
            ToolDescriptor(
                "skill_get",
                "Read one permitted skill as reference data; associated tools need separate grants.",
                {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 64,
                            "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                        }
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            ),
        )
        self._identity = canonical(self.identity)

    @staticmethod
    def _catalog_identity(catalog):
        value = _plain(getattr(catalog, "identity", None))
        if type(value) is not dict or not value:
            raise ValidationError("Skill catalog requires a stable ordinary JSON identity")
        _sha(value.get("catalog_digest"))
        return value

    @staticmethod
    def _completed(result):
        if inspect.iscoroutine(result) or inspect.isgenerator(result):
            result.close()
        return result

    def _manifest(self, scope, catalog_digest):
        key = canonical({"workspace": scope.workspace, "principal": scope.principal})
        with self._metadata_lock:
            if key not in self._metadata:
                items, offset, total = [], 0, None
                while True:
                    page = validate_skill_list(
                        self._completed(
                            self._catalog.list(scope, max_entries=self._max_entries, offset=offset)
                        ),
                        scope,
                        catalog_digest=catalog_digest,
                        max_entries=self._max_entries,
                        offset=offset,
                    )
                    if total is not None and page["total"] != total:
                        raise SkillError("Skill catalog changed during metadata loading")
                    total = page["total"]
                    items.extend(page["skills"])
                    if page["next_offset"] is None:
                        break
                    offset = page["next_offset"]
                if (
                    len(items) != total
                    or digest(items) != catalog_digest
                    or [i["name"] for i in items] != sorted({i["name"] for i in items})
                ):
                    raise SkillError("Skill metadata differs from its immutable catalog digest")
                self._metadata[key] = items
            return self._metadata[key]

    @property
    def identity(self):
        return {
            "kind": "skill-tool-source",
            "version": "1",
            "behavior_version": self._version,
            "catalog": self._catalog_identity(self._catalog),
            "max_entries": self._max_entries,
            "max_bytes": self._max_bytes,
        }

    def _check(self):
        if canonical(self.identity) != self._identity:
            raise DefinitionMismatch("Original skill tool configuration changed")
        if self._closing:
            raise SkillError("Skill tool source is closing or closed")

    async def list_tools(self):
        with self._lock:
            self._check()
            return tuple(ToolDescriptor(**descriptor.to_dict()) for descriptor in self._descriptors)

    def validate_tool_policy(self, descriptor, policy):
        if (
            type(policy.effect) is not str
            or policy.effect != "read_only"
            or policy.effect_key_argument is not None
            or policy.reconciler is not None
        ):
            raise ValidationError("Skill tools require read_only without effect key or reconciler")

    def _execute(self, token, name, arguments, scope):
        if token is not None and not self._tracker._begin(token):
            return None
        try:
            catalog_digest = self._catalog_identity(self._catalog)["catalog_digest"]
            manifest = self._manifest(scope, catalog_digest)
            if name == "skill_list":
                maximum, offset = (
                    arguments.get("max_entries", self._max_entries),
                    arguments.get("offset", 0),
                )
                result = self._catalog.list(scope, max_entries=maximum, offset=offset)
            else:
                result = self._catalog.get(scope, arguments["name"], max_bytes=self._max_bytes)
            result = self._completed(result)
            if name == "skill_list":
                value = validate_skill_list(
                    result, scope, catalog_digest=catalog_digest, max_entries=maximum, offset=offset
                )
                if (
                    value["total"] != len(manifest)
                    or value["skills"] != manifest[offset : offset + maximum]
                ):
                    raise SkillError("Skill page differs from its immutable catalog metadata")
                return value
            value = validate_skill_get(
                result,
                scope,
                arguments["name"],
                catalog_digest=catalog_digest,
                max_bytes=self._max_bytes,
            )
            metadata = {k: v for k, v in value["skill"].items() if k != "instructions"}
            if metadata not in manifest:
                raise SkillError("Skill instructions differ from their immutable catalog metadata")
            return value
        except RalfError:
            raise
        except Exception:
            raise SkillError("Skill catalog operation failed") from None
        finally:
            if token is not None:
                self._tracker._finish(token)

    async def call_tool(self, descriptor, arguments, context):
        if not isinstance(descriptor, ToolDescriptor) or canonical(descriptor.to_dict()) not in [
            canonical(d.to_dict()) for d in self._descriptors
        ]:
            raise DefinitionMismatch("Skill invocation differs from its pinned descriptor")
        if type(arguments) is not dict or not Draft202012Validator(
            descriptor.input_schema
        ).is_valid(arguments):
            raise ValidationError("Skill arguments differ from their pinned Schema")
        values = copy.deepcopy(arguments)
        tracker = current_thread_tracker.get() or self._tracker
        with self._lock:
            self._check()
            token = self._tracker._register(current_thread_group.get())
        try:
            result = await tracker.run(
                self._execute,
                token,
                descriptor.name,
                values,
                context.scope,
                group=current_thread_group.get(),
            )
            self._check()
            return result
        except BaseException:
            if token is not None:
                self._tracker._withdraw_pending(token)
            raise

    async def wait_for_calls(self):
        await self._tracker.drain()

    async def aclose(self):
        with self._lock:
            self._closing = True
        await self.wait_for_calls()
