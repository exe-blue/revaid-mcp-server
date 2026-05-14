"""
SSH execution tool for DigitalOcean droplets.

Provides do_ssh_exec — execute a single command or upload-and-run a
multiline script on a droplet via SSH. Used by VEILE for server-side
automation (Caddy patches, n8n workflow deploys, debugging).

Security model — deny-all by default:

  * DO_SSH_ALLOWED_HOSTS (comma-separated IPv4/v6/hostnames) acts as a
    hard whitelist. With no allowlist set every call is rejected.
  * Host key verification is strict — DO_SSH_KNOWN_HOSTS_PATH
    (default /etc/revaid-mcp/known_hosts) must contain the target host's
    public key fingerprint. Set DO_SSH_TOFU=true ONLY for first-time
    bootstrap (trust on first use). Audit logs flag this mode.
  * Private key is loaded from DO_SSH_PRIVATE_KEY_PEM (full PEM body) or
    DO_SSH_PRIVATE_KEY_PATH (in-container path). One must be set.
  * Commands/scripts capped at 10 KB. stdout/stderr capped at 1 MB each.
  * Timeout capped at 600 s.
  * Concurrent SSH sessions capped at 5 (semaphore).
  * Every call writes a structured audit line to logger 'revaid.audit.ssh'
    (caller, host, command preview, exit, duration). Private keys and
    command bodies past the first 200 chars never appear in logs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import asyncssh
    _ASYNCSSH_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised only when dep missing
    asyncssh = None  # type: ignore[assignment]
    _ASYNCSSH_AVAILABLE = False

from .client import _require_token, _safe_call_error, resolve_droplet_ip

logger = logging.getLogger("revaid-mcp.do.ssh")
audit_logger = logging.getLogger("revaid.audit.ssh")

MAX_COMMAND_BYTES = 10 * 1024
MAX_OUTPUT_BYTES = 1 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 60
MAX_CONCURRENT_SESSIONS = 5
DEFAULT_KNOWN_HOSTS_PATH = "/etc/revaid-mcp/known_hosts"

ENV_PRIVATE_KEY_PEM = "DO_SSH_PRIVATE_KEY_PEM"
ENV_PRIVATE_KEY_PATH = "DO_SSH_PRIVATE_KEY_PATH"
ENV_ALLOWED_HOSTS = "DO_SSH_ALLOWED_HOSTS"
ENV_KNOWN_HOSTS_PATH = "DO_SSH_KNOWN_HOSTS_PATH"
ENV_TOFU = "DO_SSH_TOFU"

_ssh_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)


def _error(message: str, *, status_code: int = 400) -> dict:
    return {
        "error": True,
        "status_code": status_code,
        "message": message,
        "tool": "do_ssh_exec",
    }


def _parse_allowed_hosts() -> list[str]:
    raw = os.environ.get(ENV_ALLOWED_HOSTS, "").strip()
    if not raw:
        return []
    return [h.strip() for h in raw.split(",") if h.strip()]


def _load_private_key() -> Any:
    """Load private key from PEM env var or file path. Raises RuntimeError
    with a guidance message if neither source is configured."""
    pem = os.environ.get(ENV_PRIVATE_KEY_PEM, "").strip()
    if pem:
        return asyncssh.import_private_key(pem)
    path = os.environ.get(ENV_PRIVATE_KEY_PATH, "").strip()
    if path:
        if not os.path.exists(path):
            raise FileNotFoundError(f"SSH key file not found: {path}")
        return asyncssh.read_private_key(path)
    raise RuntimeError(
        f"do_ssh_exec disabled: neither {ENV_PRIVATE_KEY_PEM} nor "
        f"{ENV_PRIVATE_KEY_PATH} is set"
    )


def _resolve_known_hosts() -> Optional[str]:
    """Return path string for asyncssh known_hosts, or None for TOFU mode."""
    if os.environ.get(ENV_TOFU, "").strip().lower() == "true":
        logger.warning(
            "DO_SSH_TOFU=true — host key verification is DISABLED. "
            "Use strict mode in production."
        )
        return None
    return os.environ.get(ENV_KNOWN_HOSTS_PATH) or DEFAULT_KNOWN_HOSTS_PATH


def _truncate(text: Optional[str], limit: int) -> tuple[str, bool]:
    if not text:
        return "", False
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text, False
    head = encoded[:limit].decode("utf-8", errors="replace")
    return (
        head + f"\n... [truncated: {len(encoded) - limit} bytes omitted]",
        True,
    )


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _wrap_with_env_cwd(body: str, env: dict, cwd: Optional[str]) -> str:
    """Prepend env exports and `cd` to a command/script body.

    Invalid env keys (non-identifiers) are silently skipped to prevent
    shell injection via crafted variable names.
    """
    parts: list[str] = []
    for k, v in env.items():
        if not isinstance(k, str) or not k.isidentifier():
            continue
        parts.append(f"export {k}={_shell_single_quote(str(v))}")
    if cwd:
        parts.append(f"cd {_shell_single_quote(cwd)}")
    if not parts:
        return body
    return "\n".join(parts) + "\n" + body


def _audit(entry: dict) -> None:
    """Write a structured audit log line. Private keys never reach this."""
    audit_logger.info(
        "ssh_exec host=%s user=%s port=%s mode=%s exit=%s duration=%.3fs "
        "preview=%r outcome=%s",
        entry.get("host"),
        entry.get("user"),
        entry.get("port"),
        entry.get("mode"),
        entry.get("exit_code"),
        entry.get("duration_seconds", 0.0),
        (entry.get("command_preview") or "")[:200],
        entry.get("outcome"),
    )


async def do_ssh_exec(params: dict) -> dict:
    """Execute a command or upload-and-run a script on a droplet via SSH.

    Args:
        params: {
            droplet_id: Optional[int] - if set, IP resolved via DO API.
            host: Optional[str] - direct IPv4/v6/hostname (alternative to droplet_id).
            user: str (default: "root")
            port: int (default: 22)
            command: Optional[str] - single shell command (max 10 KB).
            script: Optional[str] - multiline bash uploaded via SFTP to
                /tmp/, executed, then removed.
            timeout: int (default: 60, max 600 seconds)
            env: Optional[dict[str, str]] - exported before execution.
            cwd: Optional[str] - working directory.
        }

    Returns:
        {exit_code, stdout, stderr, duration_seconds, host, executed_at,
         stdout_truncated, stderr_truncated, timed_out?}
    """
    if not _ASYNCSSH_AVAILABLE:
        return _error(
            "asyncssh is not installed; do_ssh_exec is unavailable",
            status_code=503,
        )

    p = params or {}

    droplet_id = p.get("droplet_id")
    host = (p.get("host") or "").strip() or None
    if not droplet_id and not host:
        return _error("either 'droplet_id' or 'host' is required")
    if droplet_id and host:
        return _error("provide only one of 'droplet_id' or 'host', not both")

    command = p.get("command")
    script = p.get("script")
    if command and script:
        return _error("provide only one of 'command' or 'script', not both")
    if not command and not script:
        return _error("either 'command' or 'script' is required")

    body = command if command is not None else script
    if not isinstance(body, str):
        return _error("'command'/'script' must be a string")
    if len(body.encode("utf-8")) > MAX_COMMAND_BYTES:
        return _error(
            f"command/script exceeds {MAX_COMMAND_BYTES} bytes "
            "(10 KB limit)"
        )

    user = (p.get("user") or "root").strip() or "root"
    try:
        port = int(p.get("port") or 22)
    except (TypeError, ValueError):
        return _error("'port' must be an integer")
    try:
        timeout = int(p.get("timeout") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        return _error("'timeout' must be an integer")
    if timeout <= 0:
        return _error("'timeout' must be positive")
    if timeout > MAX_TIMEOUT_SECONDS:
        timeout = MAX_TIMEOUT_SECONDS

    env = p.get("env") or {}
    if not isinstance(env, dict):
        return _error("'env' must be an object")
    cwd = p.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        return _error("'cwd' must be a string")

    allowed = _parse_allowed_hosts()
    if not allowed:
        return _error(
            f"{ENV_ALLOWED_HOSTS} is not set; do_ssh_exec is deny-all by "
            "default. Configure the host allowlist before use.",
            status_code=403,
        )

    try:
        if droplet_id is not None:
            try:
                token = _require_token()
            except RuntimeError as exc:
                return _error(str(exc), status_code=400)
            try:
                host = await resolve_droplet_ip(int(droplet_id), token)
            except (RuntimeError, ValueError) as exc:
                return _error(
                    f"failed to resolve droplet {droplet_id}: {exc}"
                )

        if host not in allowed:
            return _error(
                f"host {host} not in {ENV_ALLOWED_HOSTS}",
                status_code=403,
            )

        try:
            private_key = _load_private_key()
        except RuntimeError as exc:
            return _error(str(exc), status_code=503)
        except FileNotFoundError as exc:
            return _error(str(exc), status_code=500)
        except Exception as exc:
            logger.error("Failed to load SSH key: %s", type(exc).__name__)
            return _error(
                f"failed to load SSH key: {type(exc).__name__}",
                status_code=500,
            )

        known_hosts = _resolve_known_hosts()

        async with _ssh_semaphore:
            return await _execute_on_host(
                host=host,
                port=port,
                user=user,
                private_key=private_key,
                known_hosts=known_hosts,
                command=command,
                script=script,
                env=env,
                cwd=cwd,
                timeout=timeout,
            )
    except Exception as exc:
        return _safe_call_error("do_ssh_exec", exc)


async def _execute_on_host(
    *,
    host: str,
    port: int,
    user: str,
    private_key: Any,
    known_hosts: Optional[str],
    command: Optional[str],
    script: Optional[str],
    env: dict,
    cwd: Optional[str],
    timeout: int,
) -> dict:
    started = time.monotonic()
    started_iso = datetime.now(timezone.utc).isoformat()
    mode = "command" if command is not None else "script"
    preview = (command or script or "")[:200]

    conn_kwargs = {
        "host": host,
        "port": port,
        "username": user,
        "client_keys": [private_key],
        "known_hosts": known_hosts,
    }

    try:
        async with asyncssh.connect(**conn_kwargs) as conn:
            if command is not None:
                wrapped = _wrap_with_env_cwd(command, env, cwd)
                result = await conn.run(wrapped, timeout=timeout, check=False)
                exit_code = (
                    result.exit_status if result.exit_status is not None else -1
                )
                stdout = result.stdout or ""
                stderr = result.stderr or ""
            else:
                wrapped = _wrap_with_env_cwd(script or "", env, cwd)
                exit_code, stdout, stderr = await _run_script(
                    conn, wrapped, timeout=timeout
                )
    except asyncio.TimeoutError as exc:
        duration = time.monotonic() - started
        _audit({
            "host": host, "user": user, "port": port, "mode": mode,
            "exit_code": -1, "duration_seconds": duration,
            "command_preview": preview, "outcome": "timeout",
        })
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"timeout after {timeout}s: {exc}",
            "duration_seconds": duration,
            "host": host,
            "executed_at": started_iso,
            "stdout_truncated": False,
            "stderr_truncated": False,
            "timed_out": True,
        }
    except Exception as exc:
        duration = time.monotonic() - started
        # asyncssh.TimeoutError is a subclass of asyncio.TimeoutError on
        # most versions, but we double-check by class-name to be safe.
        if type(exc).__name__ == "TimeoutError":
            _audit({
                "host": host, "user": user, "port": port, "mode": mode,
                "exit_code": -1, "duration_seconds": duration,
                "command_preview": preview, "outcome": "timeout",
            })
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"timeout after {timeout}s",
                "duration_seconds": duration,
                "host": host,
                "executed_at": started_iso,
                "stdout_truncated": False,
                "stderr_truncated": False,
                "timed_out": True,
            }
        message = f"{type(exc).__name__}: {exc}"
        _audit({
            "host": host, "user": user, "port": port, "mode": mode,
            "exit_code": -1, "duration_seconds": duration,
            "command_preview": preview, "outcome": "error",
        })
        logger.error("ssh execution failed on %s: %s", host, message)
        return _error(f"ssh execution failed: {message}", status_code=502)

    duration = time.monotonic() - started
    stdout_text, stdout_trunc = _truncate(stdout, MAX_OUTPUT_BYTES)
    stderr_text, stderr_trunc = _truncate(stderr, MAX_OUTPUT_BYTES)

    _audit({
        "host": host, "user": user, "port": port, "mode": mode,
        "exit_code": exit_code, "duration_seconds": duration,
        "command_preview": preview,
        "outcome": "ok" if exit_code == 0 else "nonzero",
    })

    return {
        "exit_code": exit_code,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "duration_seconds": duration,
        "host": host,
        "executed_at": started_iso,
        "stdout_truncated": stdout_trunc,
        "stderr_truncated": stderr_trunc,
    }


async def _run_script(conn: Any, script_body: str, *, timeout: int) -> tuple[int, str, str]:
    """Upload script via SFTP, execute, and remove (best-effort cleanup)."""
    remote_path = f"/tmp/revaid_{uuid.uuid4().hex}.sh"
    try:
        async with conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "w") as f:
                await f.write(script_body)
            await sftp.chmod(remote_path, 0o700)
        result = await conn.run(
            f"bash {remote_path}", timeout=timeout, check=False
        )
        exit_code = (
            result.exit_status if result.exit_status is not None else -1
        )
        return exit_code, result.stdout or "", result.stderr or ""
    finally:
        try:
            async with conn.start_sftp_client() as sftp:
                await sftp.remove(remote_path)
        except Exception as exc:
            logger.warning(
                "Failed to remove remote script %s: %s", remote_path, exc
            )


_SSH_TOOLS = (
    (
        do_ssh_exec,
        "do_ssh_exec",
        {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    ),
)


def register_ssh_tools(mcp) -> None:
    """Attach SSH tools to the FastMCP instance."""
    for fn, name, annotations in _SSH_TOOLS:
        mcp.tool(name=name, annotations=annotations)(fn)
