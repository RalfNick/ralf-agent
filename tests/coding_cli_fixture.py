"""Prepare a synthetic executable before bounded product ownership starts."""

import subprocess


def ready_cli(cli):
    """One silent, side-effect-free handshake; never retry a business command."""
    original = cli.read_bytes()
    completed = subprocess.run(
        [str(cli), "--fixture-ready"],
        env={"PATH": str(cli.parent) + ":/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        start_new_session=True,
        timeout=5,
        check=True,
    )
    assert completed.stdout == completed.stderr == b""
    assert cli.read_bytes() == original
