"""Tests for do_ssh_exec.

These tests stub out the asyncssh module entirely — no real network is
contacted. The goal is to lock in the security/control-flow invariants:
allowlist enforcement, deny-all-by-default, droplet_id resolution,
timeout handling, and script cleanup.

Run with:  pytest tests/tools/test_digitalocean_ssh.py
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import the module under test. asyncssh may be absent at test time —
# the module guards the import and exposes _ASYNCSSH_AVAILABLE for tests.
from src.tools.digitalocean import ssh as ssh_module

# Reserved documentation / placeholder IPs used purely as test fixtures.
# Centralised here so the literals appear once and obvious test-only intent
# is clear. NOSONAR suppressions document that S1313 is acknowledged.
_ALLOWED_HOST = "1.2.3.4"  # NOSONAR S1313 — test fixture only
_ALLOWED_HOST_2 = "5.6.7.8"  # NOSONAR S1313 — test fixture only
_DENIED_HOST = "8.8.8.8"  # NOSONAR S1313 — test fixture only
_RESOLVED_HOST = "9.9.9.9"  # NOSONAR S1313 — test fixture only


# ---- helpers ---------------------------------------------------------------


def _make_conn_ctx(*, run_result=None, sftp_files: list | None = None):
    """Build a connection context manager mock + the inner conn mock."""
    conn = MagicMock(name="ssh_conn")
    conn.run = AsyncMock(return_value=run_result)

    if sftp_files is not None:
        sftp = MagicMock(name="sftp")

        open_ctx = MagicMock(name="sftp_open_ctx")
        file_mock = MagicMock(name="sftp_file")
        file_mock.write = AsyncMock()
        open_ctx.__aenter__ = AsyncMock(return_value=file_mock)
        open_ctx.__aexit__ = AsyncMock(return_value=False)
        sftp.open = MagicMock(return_value=open_ctx)
        sftp.chmod = AsyncMock()
        sftp.remove = AsyncMock(side_effect=lambda p: sftp_files.append(p))

        sftp_ctx = MagicMock(name="sftp_ctx")
        sftp_ctx.__aenter__ = AsyncMock(return_value=sftp)
        sftp_ctx.__aexit__ = AsyncMock(return_value=False)
        conn.start_sftp_client = MagicMock(return_value=sftp_ctx)

    conn_ctx = MagicMock(name="conn_ctx")
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    return conn_ctx, conn


@pytest.fixture
def stub_asyncssh(monkeypatch):
    """Replace ssh_module.asyncssh with a MagicMock for the duration of a test."""
    mock_module = MagicMock(name="asyncssh")
    mock_module.import_private_key = MagicMock(return_value="FAKEKEY")
    mock_module.read_private_key = MagicMock(return_value="FAKEKEY")
    monkeypatch.setattr(ssh_module, "asyncssh", mock_module)
    monkeypatch.setattr(ssh_module, "_ASYNCSSH_AVAILABLE", True)
    return mock_module


@pytest.fixture
def env_minimal(monkeypatch):
    """Minimum env to make do_ssh_exec produce a call (allowlist + key)."""
    monkeypatch.setenv("DO_SSH_PRIVATE_KEY_PEM", "fake-pem-body")
    monkeypatch.setenv("DO_SSH_ALLOWED_HOSTS", f"{_ALLOWED_HOST}, {_ALLOWED_HOST_2}")
    monkeypatch.setenv("DO_SSH_TOFU", "true")  # avoid known_hosts file check
    # ensure no leak from prior tests
    monkeypatch.delenv("DO_SSH_PRIVATE_KEY_PATH", raising=False)


# ---- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_success(stub_asyncssh, env_minimal):
    run_result = MagicMock(exit_status=0, stdout="hello\n", stderr="")
    conn_ctx, conn = _make_conn_ctx(run_result=run_result)
    stub_asyncssh.connect = MagicMock(return_value=conn_ctx)

    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": "echo hello",
    })

    assert result.get("error") is not True, result
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]
    assert result["host"] == _ALLOWED_HOST
    assert result["stderr"] == ""
    assert result["stdout_truncated"] is False
    # connect was called with the right host/user
    kwargs = stub_asyncssh.connect.call_args.kwargs
    assert kwargs["host"] == _ALLOWED_HOST
    assert kwargs["username"] == "root"
    # the run command was executed
    conn.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_host_not_in_allowlist(stub_asyncssh, env_minimal):
    result = await ssh_module.do_ssh_exec({
        "host": _DENIED_HOST,
        "command": "echo test",
    })
    assert result.get("error") is True
    assert "not in DO_SSH_ALLOWED_HOSTS" in result["message"]
    assert result["status_code"] == 403
    # connect must never be reached
    assert getattr(stub_asyncssh, "connect", MagicMock()).called is False


@pytest.mark.asyncio
async def test_allowlist_empty_denies_all(stub_asyncssh, monkeypatch):
    monkeypatch.setenv("DO_SSH_PRIVATE_KEY_PEM", "fake-pem-body")
    monkeypatch.delenv("DO_SSH_ALLOWED_HOSTS", raising=False)

    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": "echo test",
    })
    assert result.get("error") is True
    assert result["status_code"] == 403
    assert "deny-all" in result["message"]


@pytest.mark.asyncio
async def test_missing_key_denies(stub_asyncssh, monkeypatch):
    monkeypatch.setenv("DO_SSH_ALLOWED_HOSTS", _ALLOWED_HOST)
    monkeypatch.delenv("DO_SSH_PRIVATE_KEY_PEM", raising=False)
    monkeypatch.delenv("DO_SSH_PRIVATE_KEY_PATH", raising=False)

    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": "echo test",
    })
    assert result.get("error") is True
    assert result["status_code"] == 503
    assert "DO_SSH_PRIVATE_KEY_PEM" in result["message"]
    assert "DO_SSH_PRIVATE_KEY_PATH" in result["message"]


@pytest.mark.asyncio
async def test_command_or_script_required(stub_asyncssh, env_minimal):
    result = await ssh_module.do_ssh_exec({"host": _ALLOWED_HOST})
    assert result.get("error") is True
    assert "command" in result["message"].lower()


@pytest.mark.asyncio
async def test_command_and_script_conflict(stub_asyncssh, env_minimal):
    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": "echo a",
        "script": "echo b",
    })
    assert result.get("error") is True
    assert "only one" in result["message"]


@pytest.mark.asyncio
async def test_command_size_limit(stub_asyncssh, env_minimal):
    huge = "x" * (ssh_module.MAX_COMMAND_BYTES + 1)
    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": huge,
    })
    assert result.get("error") is True
    assert "exceeds" in result["message"]


@pytest.mark.asyncio
async def test_timeout(stub_asyncssh, env_minimal):
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError("connect timeout"))
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    stub_asyncssh.connect = MagicMock(return_value=conn_ctx)

    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": "sleep 9999",
        "timeout": 1,
    })
    assert result.get("error") is not True, result
    assert result["exit_code"] == -1
    assert result["timed_out"] is True
    assert "timeout" in result["stderr"].lower()


@pytest.mark.asyncio
async def test_timeout_clamped_to_max(stub_asyncssh, env_minimal):
    run_result = MagicMock(exit_status=0, stdout="", stderr="")
    conn_ctx, conn = _make_conn_ctx(run_result=run_result)
    stub_asyncssh.connect = MagicMock(return_value=conn_ctx)

    await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": "true",
        "timeout": 99999,  # asks for huge, must clamp to 600
    })
    call_kwargs = conn.run.call_args.kwargs
    assert call_kwargs["timeout"] == ssh_module.MAX_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_script_upload_cleanup_on_success(stub_asyncssh, env_minimal):
    run_result = MagicMock(exit_status=0, stdout="done\n", stderr="")
    removed: list = []
    conn_ctx, conn = _make_conn_ctx(run_result=run_result, sftp_files=removed)
    stub_asyncssh.connect = MagicMock(return_value=conn_ctx)

    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "script": "#!/bin/bash\necho done\n",
    })
    assert result["exit_code"] == 0
    # SFTP remove called once with the same path the script was uploaded to
    assert len(removed) == 1
    assert removed[0].startswith("/tmp/revaid_")
    assert removed[0].endswith(".sh")
    # The run command should reference that path
    bash_call = conn.run.call_args.args[0]
    assert removed[0] in bash_call


@pytest.mark.asyncio
async def test_script_cleanup_on_exec_failure(stub_asyncssh, env_minimal):
    # conn.run() raises after SFTP upload — finally must still remove.
    removed: list = []
    conn = MagicMock()
    conn.run = AsyncMock(side_effect=RuntimeError("script blew up"))

    sftp = MagicMock()
    open_ctx = MagicMock()
    fmock = MagicMock()
    fmock.write = AsyncMock()
    open_ctx.__aenter__ = AsyncMock(return_value=fmock)
    open_ctx.__aexit__ = AsyncMock(return_value=False)
    sftp.open = MagicMock(return_value=open_ctx)
    sftp.chmod = AsyncMock()
    sftp.remove = AsyncMock(side_effect=lambda p: removed.append(p))

    sftp_ctx = MagicMock()
    sftp_ctx.__aenter__ = AsyncMock(return_value=sftp)
    sftp_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.start_sftp_client = MagicMock(return_value=sftp_ctx)

    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    stub_asyncssh.connect = MagicMock(return_value=conn_ctx)

    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "script": "echo hi",
    })
    # The exec raised so we report a structured error, but cleanup ran.
    assert result.get("error") is True
    assert len(removed) == 1


@pytest.mark.asyncio
async def test_droplet_id_resolves_to_ip(stub_asyncssh, env_minimal, monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_API_TOKEN", "fake-token")
    resolver = AsyncMock(return_value=_ALLOWED_HOST)
    monkeypatch.setattr(ssh_module, "resolve_droplet_ip", resolver)

    run_result = MagicMock(exit_status=0, stdout="ok\n", stderr="")
    conn_ctx, _conn = _make_conn_ctx(run_result=run_result)
    stub_asyncssh.connect = MagicMock(return_value=conn_ctx)

    result = await ssh_module.do_ssh_exec({
        "droplet_id": 570463287,
        "command": "uname -a",
    })
    assert result.get("error") is not True, result
    resolver.assert_awaited_once_with(570463287, "fake-token")
    assert stub_asyncssh.connect.call_args.kwargs["host"] == _ALLOWED_HOST
    assert result["host"] == _ALLOWED_HOST


@pytest.mark.asyncio
async def test_droplet_id_resolved_ip_not_in_allowlist(stub_asyncssh, env_minimal, monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_API_TOKEN", "fake-token")
    # Resolver returns an IP that is NOT in the test allowlist.
    monkeypatch.setattr(ssh_module, "resolve_droplet_ip", AsyncMock(return_value=_RESOLVED_HOST))

    result = await ssh_module.do_ssh_exec({
        "droplet_id": 1,
        "command": "echo nope",
    })
    assert result.get("error") is True
    assert result["status_code"] == 403
    assert _RESOLVED_HOST in result["message"]


@pytest.mark.asyncio
async def test_host_and_droplet_id_conflict(stub_asyncssh, env_minimal):
    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "droplet_id": 1,
        "command": "echo a",
    })
    assert result.get("error") is True
    assert "only one" in result["message"]


@pytest.mark.asyncio
async def test_output_truncation(stub_asyncssh, env_minimal):
    big = "x" * (ssh_module.MAX_OUTPUT_BYTES + 100)
    run_result = MagicMock(exit_status=0, stdout=big, stderr="")
    conn_ctx, _conn = _make_conn_ctx(run_result=run_result)
    stub_asyncssh.connect = MagicMock(return_value=conn_ctx)

    result = await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": "cat big",
    })
    assert result["stdout_truncated"] is True
    assert "truncated" in result["stdout"]
    assert len(result["stdout"].encode("utf-8")) < len(big)


@pytest.mark.asyncio
async def test_env_and_cwd_wrap(stub_asyncssh, env_minimal):
    run_result = MagicMock(exit_status=0, stdout="", stderr="")
    conn_ctx, conn = _make_conn_ctx(run_result=run_result)
    stub_asyncssh.connect = MagicMock(return_value=conn_ctx)

    await ssh_module.do_ssh_exec({
        "host": _ALLOWED_HOST,
        "command": "echo $FOO",
        "env": {"FOO": "bar baz", "BAD KEY": "skipped"},
        "cwd": "/var/log",
    })
    sent = conn.run.call_args.args[0]
    assert "export FOO='bar baz'" in sent
    # invalid key skipped
    assert "BAD KEY" not in sent
    assert "cd '/var/log'" in sent
    assert sent.endswith("echo $FOO")
