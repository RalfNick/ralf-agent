"""Borrowed immutable Skill metadata through the original Retriever protocol."""

import math

from .component_fingerprint import executable_digest
from .errors import DefinitionMismatch, ValidationError
from .ports import is_sync_callable
from .retrieval import Chunk, RetrievalQuery, RetrievedChunk, _bounded_result, _scope
from .skill_selection import LexicalSkillSelector, fixed_identity, selection_input
from .skills import _bound, _metadata, _name, _plain, _sha, _text, validate_skill_list
from .task_controls import _binding
from .tools import ThreadExecutionTracker, current_thread_group, current_thread_tracker
from .types import Scope, canonical, digest


class SkillDirectoryRetriever:
    def __init__(self, catalog, *, version, names=None, selector=None, max_entries=1000):
        _text(version, "Skill directory version", 256)
        _bound(max_entries, 1000, "Skill directory entry")
        if names is not None:
            if type(names) not in (list, tuple) or not 1 <= len(names) <= 1000:
                raise ValidationError("Skill names require a nonempty bounded allowlist")
            for name in names:
                _name(name)
            if len(set(names)) != len(names):
                raise ValidationError("Skill names must be unique")
        self.catalog, self.selector = (
            catalog,
            LexicalSkillSelector() if selector is None else selector,
        )
        self.version, self.names, self.max_entries = (
            version,
            None if names is None else tuple(sorted(names)),
            max_entries,
        )
        self._catalog, self._selector = self.catalog, self.selector
        self._tracker = ThreadExecutionTracker()
        self._hooks = {
            "list": _binding(getattr(catalog, "list", None)),
            "get": _binding(getattr(catalog, "get", None)),
            "select": _binding(getattr(self.selector, "select", None)),
        }
        self._fixed = self._capture()

    def _capture(self):
        if any(
            not is_sync_callable(getattr(self.catalog, name, None)) for name in ("list", "get")
        ) or not is_sync_callable(getattr(self.selector, "select", None)):
            raise ValidationError("Skill discovery requires synchronous catalog and pure selector")
        catalog, selector = (
            fixed_identity(self.catalog.identity),
            fixed_identity(self.selector.identity),
        )
        if type(catalog) is not dict or type(selector) is not dict or not catalog or not selector:
            raise ValidationError("Skill discovery requires fixed ordinary component identities")
        _sha(catalog.get("catalog_digest"))
        if len(canonical([catalog, selector]).encode("utf-8")) > 65536:
            raise ValidationError("Skill discovery component identities exceed allowance")
        return {
            "kind": "skill-directory-retriever",
            "version": "1",
            "behavior_version": self.version,
            "catalog": catalog,
            "selector": selector,
            "names": None if self.names is None else list(self.names),
            "max_entries": self.max_entries,
            "implementation": {
                "list": executable_digest(self.catalog.list),
                "get": executable_digest(self.catalog.get),
                "select": executable_digest(self.selector.select),
            },
        }

    def _check(self):
        if (
            self.catalog is not self._catalog
            or self.selector is not self._selector
            or any(
                _binding(getattr(self.catalog if name != "select" else self.selector, name, None))
                != value
                for name, value in self._hooks.items()
            )
            or digest(self._capture()) != digest(self._fixed)
        ):
            raise DefinitionMismatch("Skill directory source, selector or configuration changed")

    @property
    def identity(self):
        self._check()
        return _plain(self._fixed)

    async def _entries(self, scope):
        self._check()
        entries, offset, total = [], 0, None
        catalog_digest = self._fixed["catalog"]["catalog_digest"]
        while True:
            tracker = current_thread_tracker.get() or self._tracker
            page = await tracker.run(
                self.catalog.list,
                scope,
                max_entries=self.max_entries,
                offset=offset,
                group=current_thread_group.get(),
            )
            self._check()
            if (
                type(page) is not dict
                or set(page)
                != {"kind", "version", "scope", "catalog_digest", "skills", "total", "next_offset"}
                or type(page["kind"]) is not str
                or page["kind"] != "skill-list"
                or type(page["version"]) is not str
                or page["version"] != "1"
                or type(page["catalog_digest"]) is not str
                or page["catalog_digest"] != catalog_digest
                or type(page["scope"]) is not dict
                or set(page["scope"]) != {"workspace", "principal"}
                or any(
                    type(page["scope"][key]) is not str or page["scope"][key] != getattr(scope, key)
                    for key in ("workspace", "principal")
                )
                or type(page.get("skills")) is not list
                or len(page["skills"]) > self.max_entries
                or type(page.get("total")) is not int
                or not 0 <= page["total"] <= self.max_entries
                or len(page["skills"]) != max(0, min(self.max_entries, page["total"] - offset))
                or (page["next_offset"] is not None and type(page["next_offset"]) is not int)
                or page["next_offset"]
                != (
                    offset + len(page["skills"])
                    if offset + len(page["skills"]) < page["total"]
                    else None
                )
            ):
                raise ValidationError("Skill directory exceeded its complete metadata allowance")
            for item in page["skills"]:
                _metadata(item)
            page = validate_skill_list(
                page,
                scope,
                catalog_digest=catalog_digest,
                max_entries=self.max_entries,
                offset=offset,
            )
            if total is not None and total != page["total"]:
                raise DefinitionMismatch("Skill directory changed its original page total")
            total = page["total"]
            entries.extend(page["skills"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        if [item["name"] for item in entries] != sorted(
            set(item["name"] for item in entries)
        ) or digest(entries) != catalog_digest:
            raise DefinitionMismatch("Skill directory differs from its complete catalog digest")
        if self.names is not None:
            if not set(self.names) <= {item["name"] for item in entries}:
                raise ValidationError(
                    "Skill allowlist names are unavailable in this scoped catalog"
                )
            entries = [item for item in entries if item["name"] in self.names]
        return entries

    def _chunk(self, scope, namespace, entry):
        catalog_digest = self._fixed["catalog"]["catalog_digest"]
        metadata = {
            "reference_kind": "skill-directory",
            "name": entry["name"],
            "description": entry["description"],
            "skill_version": entry["version"],
            "catalog_digest": catalog_digest,
            "metadata_digest": digest(entry),
            "permissions": "none",
        }
        return RetrievedChunk(
            document_id=entry["name"],
            chunk_id=digest([catalog_digest, entry["name"], entry]),
            version=1,
            text=entry["name"] + ": " + entry["description"],
            source_uri="skill:" + catalog_digest + "/" + entry["name"],
            metadata=metadata,
            expires_at=None,
            scope=scope,
            namespace=namespace,
            score=0,
        )

    async def retrieve(self, scope, namespace, query):
        _scope(scope, namespace)
        if (
            type(query) is not RetrievalQuery
            or type(query.limit) is not int
            or not 1 <= query.limit <= 256
        ):
            raise ValidationError("Skill discovery requires a bounded original RetrievalQuery")
        entries = await self._entries(scope)
        selected_limit = min(query.limit, 100)
        entries = selection_input(query.text, entries, selected_limit)
        selected = self.selector.select(query.text, _plain(entries), limit=selected_limit)
        self._check()
        if (
            type(selected) is not list
            or len(selected) > selected_limit
            or any(type(name) is not str for name in selected)
            or len(set(selected)) != len(selected)
            or not set(selected) <= {item["name"] for item in entries}
        ):
            if hasattr(selected, "close"):
                selected.close()
            raise ValidationError("Skill selector requires completed unique permitted names")
        by_name = {item["name"]: item for item in entries}
        return _bounded_result(
            [self._chunk(scope, namespace, by_name[name]) for name in selected],
            query,
            "skill-directory",
        )

    async def validate(self, scope, namespace, items):
        _scope(scope, namespace)
        if type(items) not in (list, tuple) or len(items) > 256:
            raise ValidationError("Skill validation requires bounded original chunks")
        entries = {item["name"]: item for item in await self._entries(scope)}
        seen = set()
        for item in items:
            current = self._snapshot(item)
            expected = (
                self._snapshot(self._chunk(scope, namespace, entries[item.document_id]))
                if current is not None and item.document_id in entries
                else None
            )
            if (
                current is None
                or item.document_id not in entries
                or item.chunk_id in seen
                or current != expected
            ):
                raise DefinitionMismatch(
                    "Skill reference differs from its original scoped metadata"
                )
            seen.add(item.chunk_id)

    @staticmethod
    def _snapshot(item):
        """Check raw native fields before any metadata view or copying hook."""
        if type(item) not in (Chunk, RetrievedChunk):
            raise DefinitionMismatch("Skill reference requires an original native chunk")
        fields = {
            name: object.__getattribute__(item, name)
            for name in (
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
        }
        limits = {
            "document_id": 64,
            "chunk_id": 64,
            "text": 4162,
            "source_uri": 135,
            "namespace": 128,
        }
        for name, maximum in limits.items():
            _text(fields[name], "Skill reference " + name, maximum)
        if (
            type(fields["version"]) is not int
            or fields["version"] != 1
            or fields["expires_at"] is not None
        ):
            raise DefinitionMismatch("Skill reference version or expiry changed")
        scope = fields["scope"]
        if type(scope) is not Scope or any(
            type(object.__getattribute__(scope, key)) is not str
            for key in ("workspace", "principal")
        ):
            raise DefinitionMismatch("Skill reference requires original ordinary Scope")
        metadata = fields["metadata"]
        limits = {
            "reference_kind": 32,
            "name": 64,
            "description": 4096,
            "skill_version": 256,
            "catalog_digest": 64,
            "metadata_digest": 64,
            "permissions": 16,
        }
        if type(metadata) is not dict or set(metadata) != set(limits):
            raise DefinitionMismatch("Skill reference requires original ordinary metadata")
        for name, maximum in limits.items():
            _text(metadata[name], "Skill metadata " + name, maximum)
        if type(item) is RetrievedChunk:
            score = object.__getattribute__(item, "score")
            if type(score) not in (int, float) or (
                type(score) is float and not math.isfinite(score)
            ):
                raise ValidationError("Skill reference score must be ordinary finite numeric data")
        return fields
