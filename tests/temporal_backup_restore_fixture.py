"""Owned, opt-in dev-service backup fixture; never inspects old Docker resources."""

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import uuid
from pathlib import Path

CLI = Path("/private/tmp/ralf-agent-dev55-5hg43c2i/temporal-cli")
CLI_SHA = "33c298d41f6eefebf01a28a3511f444480e939e21d3518cb0c12a4abad467c4b"
IMAGE = "public.ecr.aws/docker/library/postgres:16"


def file_hash(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def files(directory):
    return {
        str(path.relative_to(directory)): {"sha256": file_hash(path), "bytes": path.stat().st_size}
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def write_private(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "wb" if isinstance(value, bytes) else "w") as stream:
        stream.write(value)


def secure_tree(directory):
    directory.chmod(0o700)
    for path in directory.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)


class OwnedServices:
    def __init__(self, directory):
        self.directory = directory
        self.directory.chmod(0o700)
        suffix = uuid.uuid4().hex
        self.container = "ralf-backup-pg-" + suffix
        self.volume = self.container + "-data"
        self.password = secrets.token_urlsafe(32)
        self.temporal = None
        self.temporal_log = None
        self.temporal_directory = None
        self.address = None
        self.port = None
        self.created_container = self.created_volume = False
        self.command_count = 0
        self.databases = []

    async def command(self, *args, data=None):
        self.command_count += 1
        process = await asyncio.create_subprocess_exec(
            *map(str, args),
            stdin=asyncio.subprocess.PIPE if data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, error = await asyncio.wait_for(process.communicate(data), 60)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        write_private(self.directory / f"command-{self.command_count}.stderr", error)
        assert process.returncode == 0, "Owned backup fixture command failed; see local stderr"
        return output

    async def start_pg(self):
        assert shutil.which("docker"), "Docker CLI must be explicitly available"
        if not self.created_container:
            await self.command("docker", "image", "inspect", IMAGE)
            await self.command(
                "docker", "volume", "create", "--label", "ralf.owned-backup=true", self.volume
            )
            self.created_volume = True
            environment = self.directory / "postgres.env"
            write_private(
                environment,
                f"POSTGRES_USER=ralf\nPOSTGRES_PASSWORD={self.password}\nPOSTGRES_DB=stage0\n",
            )
            await self.command(
                "docker",
                "create",
                "--pull=never",
                "--name",
                self.container,
                "--label",
                "ralf.owned-backup=true",
                "--env-file",
                environment,
                "--publish",
                "127.0.0.1::5432",
                "--mount",
                f"type=volume,source={self.volume},target=/var/lib/postgresql/data",
                IMAGE,
            )
            self.created_container = True
        await self.command("docker", "start", self.container)
        listing = (await self.command("docker", "port", self.container, "5432/tcp")).decode()
        self.port = int(listing.strip().splitlines()[0].rsplit(":", 1)[1])
        from psycopg import AsyncConnection

        async with asyncio.timeout(40):
            while True:
                try:
                    connection = await AsyncConnection.connect(self.dsn("stage0"), autocommit=True)
                    await connection.close()
                    break
                except Exception:
                    await asyncio.sleep(0.1)
        write_private(
            self.directory / "connections.json",
            json.dumps(
                {
                    "stage0": self.dsn("stage0"),
                    "stage1": self.dsn("stage1"),
                    "stage2": self.dsn("stage2"),
                }
            ),
        )

    def dsn(self, database, *, schema=None):
        from psycopg.conninfo import make_conninfo

        values = {
            "host": "127.0.0.1",
            "port": self.port,
            "user": "ralf",
            "password": self.password,
            "dbname": database,
        }
        if schema is not None:
            values["options"] = "-csearch_path=" + schema
        return make_conninfo(**values)

    async def stop_pg(self):
        if self.created_container:
            await self.command("docker", "stop", "--time", "15", self.container)

    async def start_temporal(self, stage, *, restore=None):
        assert self.temporal is None
        assert await asyncio.to_thread(file_hash, CLI) == CLI_SHA, (
            "Original Temporal CLI SHA differs"
        )
        directory = self.directory / ("temporal-" + stage)
        if restore is None:
            directory.mkdir(mode=0o700)
            restored = None
        else:
            shutil.copytree(restore / "temporal", directory)
            secure_tree(directory)
            restored = files(directory)
            expected = json.loads((restore / "backup.json").read_text())["temporal_files"]
            assert restored == expected
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        log_path = self.directory / ("temporal-" + stage + ".log")
        write_private(log_path, "")
        self.temporal_log = log_path.open("w")
        self.temporal = await asyncio.create_subprocess_exec(
            str(CLI),
            "server",
            "start-dev",
            "--headless",
            "--ip",
            "127.0.0.1",
            "--port",
            str(port),
            "--db-filename",
            str(directory / "temporal.sqlite"),
            stdout=self.temporal_log,
            stderr=self.temporal_log,
            umask=0o077,
        )
        self.temporal_directory, self.address = directory, f"127.0.0.1:{port}"
        from temporalio.client import Client

        async with asyncio.timeout(45):
            while True:
                assert self.temporal.returncode is None, (
                    "Owned Temporal server exited during startup"
                )
                try:
                    await Client.connect(self.address)
                    break
                except Exception:
                    await asyncio.sleep(0.1)
        secure_tree(directory)
        write_private(
            self.directory / ("temporal-" + stage + "-start.json"),
            json.dumps(
                {
                    "cli_sha256": CLI_SHA,
                    "pid": self.temporal.pid,
                    "new_service_directory": str(directory),
                    "restored_files_before_start": restored,
                }
            ),
        )

    async def stop_temporal(self):
        if self.temporal is not None:
            process = self.temporal
            if process.returncode is None:
                process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(process.wait(), 30)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise AssertionError(
                    "Owned Temporal did not stop gracefully; no backup allowed"
                ) from None
            assert process.returncode in (0, -signal.SIGINT)
            self.temporal = None
            self.temporal_log.close()
            self.temporal_log = None
            secure_tree(self.temporal_directory)
            return process.pid
        return None

    async def backup(self, database, name):
        stopped_pid = await self.stop_temporal()
        assert stopped_pid is not None
        directory = self.directory / name
        directory.mkdir(mode=0o700)
        shutil.copytree(self.temporal_directory, directory / "temporal")
        secure_tree(directory)
        snapshot = files(directory / "temporal")
        assert snapshot and snapshot == files(self.temporal_directory)
        dump = await self.command(
            "docker",
            "exec",
            self.container,
            "pg_dump",
            "-U",
            "ralf",
            "-d",
            database,
            "--format=custom",
        )
        assert dump.startswith(b"PGDMP")
        dump_path = directory / "postgres.dump"
        write_private(dump_path, dump)
        await self.stop_pg()
        write_private(
            directory / "backup.json",
            json.dumps(
                {
                    "stopped_temporal_pid": stopped_pid,
                    "copied_after_server_stopped": True,
                    "temporal_files": snapshot,
                    "postgres_dump_sha256": file_hash(dump_path),
                    "postgres_source_database": database,
                    "source_database_preserved": True,
                    "scope": "entire owned database, including effect_store and business_store",
                    "external_business_writes_during_restore": False,
                    "postgres_owner_acl_included": True,
                }
            ),
        )
        return directory

    async def restore_pg(self, backup, database):
        from psycopg import AsyncConnection

        await self.start_pg()
        await self.command("docker", "exec", self.container, "createdb", "-U", "ralf", database)
        self.databases.append(database)
        connection = await AsyncConnection.connect(self.dsn(database), autocommit=True)
        try:
            count = await (
                await connection.execute(
                    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"
                )
            ).fetchone()
            assert count == (0,), "Restore target must be an empty new database"
        finally:
            await connection.close()
        metadata = json.loads((backup / "backup.json").read_text())
        dump = backup / "postgres.dump"
        assert file_hash(dump) == metadata["postgres_dump_sha256"]
        await self.command(
            "docker",
            "exec",
            "-i",
            self.container,
            "pg_restore",
            "-U",
            "ralf",
            "-d",
            database,
            "--exit-on-error",
            "--single-transaction",
            data=dump.read_bytes(),
        )
        write_private(
            self.directory / (database + "-restore.json"),
            json.dumps(
                {
                    "new_empty_database": database,
                    "source_database": metadata["postgres_source_database"],
                    "source_untouched": database != metadata["postgres_source_database"],
                    "dump_sha256": file_hash(dump),
                    "owner_acl_restored": True,
                    "single_transaction": True,
                }
            ),
        )

    async def finish(self, *, verified):
        errors = []
        for operation in (self.stop_temporal, self.stop_pg):
            try:
                await operation()
            except BaseException as exc:
                errors.append(type(exc).__name__)
        removed = False
        if verified and not errors:
            if self.created_container:
                await self.command("docker", "rm", self.container)
            if self.created_volume:
                await self.command("docker", "volume", "rm", self.volume)
            removed = True
        write_private(
            self.directory / "owned-service-cleanup.json",
            json.dumps(
                {
                    "container": self.container,
                    "volume": self.volume,
                    "owned_services_stopped": not errors,
                    "errors": errors,
                    "new_container_and_volume_removed": removed,
                    "retained_on_failure": not removed,
                    "old_resources_touched": False,
                }
            ),
        )
        secure_tree(self.directory)
        assert not errors, "Owned services could not be confirmed stopped"
