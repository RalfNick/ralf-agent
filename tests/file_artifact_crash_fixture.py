"""Terminate real file/index publications, keeping SDK guards enabled."""

import os
import sys
from pathlib import Path

import relf_agent.file_artifacts as module
from relf_agent import FileArtifactStore, Scope, SQLiteArtifactStore
from relf_agent.types import canonical

root, phase = Path(sys.argv[1]), sys.argv[2]


def crash():
    print("file-artifact-crash-window", flush=True)
    os._exit(79)


class Index(SQLiteArtifactStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        connection = self.conn

        class Connection:
            def __getattr__(self, name):
                return getattr(connection, name)

            def execute(self, sql, *values):
                if sql == "COMMIT" and phase == "before-index-commit":
                    crash()
                result = connection.execute(sql, *values)
                if sql == "COMMIT" and phase == "after-index-commit":
                    crash()
                return result

        self.conn = Connection()


module.SQLiteArtifactStore = Index
replace = os.replace


def publish(*args, **kwargs):
    if phase == "before-publish":
        crash()
    result = replace(*args, **kwargs)
    if phase == "payload-published":
        crash()
    return result


os.replace = publish
with FileArtifactStore(root / "artifacts") as store:
    reference, _ = store._prepare(Scope(), "results", {"evidence": "中文🙂"}, None)
    (root / "reference.json").write_text(canonical(reference.to_dict()))
    store.put(Scope(), "results", {"evidence": "中文🙂"})
raise AssertionError("Expected process exit")
