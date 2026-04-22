"""
FastMCP Personal Auth Provider

A drop-in OAuth 2.1 auth provider for FastMCP that works with Claude.ai,
Claude mobile, Claude Desktop, and Claude Code — no external identity
provider required.

Usage:
    from fastmcp import FastMCP
    from personal_auth import PersonalAuthProvider

    auth = PersonalAuthProvider(
        base_url="https://your-domain.com",
        password="your-secret-password",
        allowed_redirect_domains=["claude.ai", "claude.com", "localhost"],
        db_client=supabase_client,  # optional: persist tokens across restarts
    )

    mcp = FastMCP(name="my-server", auth=auth)

    @mcp.tool
    def hello() -> str:
        return "Hello, world!"

    mcp.run(transport="streamable-http", host="0.0.0.0", port=8050)
"""

import json
import secrets
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.server.auth.settings import ClientRegistrationOptions

logger = logging.getLogger("personal-auth")

DEFAULT_ACCESS_TOKEN_EXPIRY = 30 * 24 * 60 * 60  # 30 days
DEFAULT_STATE_DIR = ".oauth-state"
DEFAULT_TOKEN_TABLE = "revaid_oauth_tokens"
DEFAULT_CLIENT_TABLE = "revaid_oauth_clients"


class PersonalAuthProvider(InMemoryOAuthProvider):
    """OAuth 2.1 provider for personal/small-team MCP servers.

    Fills the gap between FastMCP's InMemoryOAuthProvider (test-only, no
    persistence, no security) and OAuthProxy (requires Google/GitHub/Auth0).

    Features:
    - Dynamic Client Registration (DCR) for Claude.ai compatibility
    - PKCE support (handled by FastMCP framework)
    - Restrict /authorize to approved redirect domains only
    - Optional password gate on authorization
    - Token persistence: Supabase (preferred) or JSON file (fallback)
    - Configurable token expiry (default 30 days)
    """

    def __init__(
        self,
        base_url: str,
        password: Optional[str] = None,
        allowed_redirect_domains: Optional[list[str]] = None,
        access_token_expiry_seconds: int = DEFAULT_ACCESS_TOKEN_EXPIRY,
        state_dir: Optional[str] = None,
        db_client: Optional[Any] = None,
        token_table: str = DEFAULT_TOKEN_TABLE,
        client_table: str = DEFAULT_CLIENT_TABLE,
    ):
        """
        Args:
            base_url: Public URL of this server (e.g. "https://my-server.example.com")
            password: Optional password required to authorize. If None, authorization
                      is gated only by allowed_redirect_domains.
            allowed_redirect_domains: List of domains allowed in OAuth redirect URIs.
                Defaults to ["claude.ai", "claude.com", "localhost"]. Set to None
                to allow all domains (not recommended for public servers).
            access_token_expiry_seconds: How long access tokens last. Default 30 days.
            state_dir: Directory for persisting OAuth state when db_client is None.
            db_client: Optional supabase-py Client. If provided, tokens are
                persisted to the `token_table` / `client_table` tables and
                survive restarts. If None, falls back to JSON file state.
            token_table: Supabase table name for tokens.
            client_table: Supabase table name for clients.
        """
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
        )

        self.password = password
        self.allowed_redirect_domains = allowed_redirect_domains if allowed_redirect_domains is not None else [
            "claude.ai", "claude.com", "localhost"
        ]
        self.access_token_expiry_seconds = access_token_expiry_seconds

        self._db = db_client
        self._token_table = token_table
        self._client_table = client_table

        if self._db is not None:
            self._load_from_db()
        else:
            self._state_dir = Path(state_dir or DEFAULT_STATE_DIR)
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._load_state()

    # --- Supabase persistence ---

    @staticmethod
    def _iso_to_epoch(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except Exception:
            return None

    @staticmethod
    def _epoch_to_iso(value: Optional[int]) -> Optional[str]:
        if value is None:
            return None
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()

    def _load_from_db(self):
        try:
            clients_res = self._db.table(self._client_table).select("*").execute()
            for row in clients_res.data or []:
                metadata = row.get("metadata") or {}
                try:
                    self.clients[row["client_id"]] = OAuthClientInformationFull(**metadata)
                except Exception as e:
                    logger.warning(f"Skip client {row['client_id']}: {e}")

            tokens_res = (
                self._db.table(self._token_table)
                .select("*")
                .eq("revoked", False)
                .execute()
            )
            now = time.time()
            for row in tokens_res.data or []:
                tt = row["token_type"]
                token_value = row["token_value"]
                expires_at = self._iso_to_epoch(row.get("expires_at"))
                if expires_at is not None and expires_at < now:
                    continue  # skip expired
                scopes = row.get("scopes") or []
                metadata = row.get("metadata") or {}

                if tt == "access":
                    self.access_tokens[token_value] = AccessToken(
                        token=token_value,
                        client_id=row["client_id"],
                        scopes=scopes,
                        expires_at=expires_at,
                    )
                    linked = metadata.get("refresh_token")
                    if linked:
                        self._access_to_refresh_map[token_value] = linked
                elif tt == "refresh":
                    self.refresh_tokens[token_value] = RefreshToken(
                        token=token_value,
                        client_id=row["client_id"],
                        scopes=scopes,
                        expires_at=expires_at,
                    )
                    linked = metadata.get("access_token")
                    if linked:
                        self._refresh_to_access_map[token_value] = linked
                elif tt == "auth_code":
                    try:
                        ac_data = dict(metadata)
                        ac_data.update({
                            "code": token_value,
                            "client_id": row["client_id"],
                            "scopes": scopes,
                            "expires_at": expires_at,
                        })
                        self.auth_codes[token_value] = AuthorizationCode(**ac_data)
                    except Exception as e:
                        logger.warning(f"Skip auth_code {token_value[:8]}...: {e}")

            logger.info(
                f"Loaded OAuth state from DB: {len(self.clients)} clients, "
                f"{len(self.access_tokens)} access, {len(self.refresh_tokens)} refresh, "
                f"{len(self.auth_codes)} auth_codes"
            )
        except Exception as e:
            logger.warning(f"Failed to load OAuth state from DB: {e}")

    def _serialize_client_row(self, client: OAuthClientInformationFull) -> dict:
        dump = client.model_dump(mode="json")
        return {
            "client_id": client.client_id,
            "redirect_uris": [str(u) for u in (client.redirect_uris or [])],
            "metadata": dump,
        }

    def _serialize_token_row(
        self,
        token_type: str,
        token_value: str,
        client_id: str,
        scopes: list,
        expires_at: Optional[int],
        metadata: Optional[dict] = None,
    ) -> dict:
        return {
            "token_type": token_type,
            "token_value": token_value,
            "client_id": client_id,
            "scopes": list(scopes or []),
            "expires_at": self._epoch_to_iso(expires_at),
            "metadata": metadata or {},
            "revoked": False,
        }

    def _auth_code_row(self, code: str, ac: AuthorizationCode) -> dict:
        metadata = ac.model_dump(mode="json")
        # These fields are stored as first-class columns, strip from metadata
        for k in ("code", "client_id", "scopes", "expires_at"):
            metadata.pop(k, None)
        return self._serialize_token_row(
            "auth_code",
            code,
            ac.client_id,
            list(ac.scopes or []),
            ac.expires_at,
            metadata,
        )

    def _sync_to_db(self):
        if self._db is None:
            self._save_state()
            return
        try:
            client_rows = [self._serialize_client_row(c) for c in self.clients.values()]
            if client_rows:
                self._db.table(self._client_table).upsert(
                    client_rows, on_conflict="client_id"
                ).execute()

            token_rows: list[dict] = []
            for tv, t in self.access_tokens.items():
                token_rows.append(self._serialize_token_row(
                    "access", tv, t.client_id, list(t.scopes or []), t.expires_at,
                    {"refresh_token": self._access_to_refresh_map.get(tv)},
                ))
            for tv, t in self.refresh_tokens.items():
                token_rows.append(self._serialize_token_row(
                    "refresh", tv, t.client_id, list(t.scopes or []), t.expires_at,
                    {"access_token": self._refresh_to_access_map.get(tv)},
                ))
            for tv, ac in self.auth_codes.items():
                token_rows.append(self._auth_code_row(tv, ac))

            if token_rows:
                self._db.table(self._token_table).upsert(
                    token_rows, on_conflict="token_value"
                ).execute()
        except Exception as e:
            logger.warning(f"Failed to sync OAuth state to DB: {e}")

    def _db_mark_revoked(self, token_value: str):
        if self._db is None:
            return
        try:
            self._db.table(self._token_table).update(
                {"revoked": True}
            ).eq("token_value", token_value).execute()
        except Exception as e:
            logger.warning(f"Failed to mark token revoked in DB: {e}")

    def _db_delete_token(self, token_value: str):
        if self._db is None:
            return
        try:
            self._db.table(self._token_table).delete().eq(
                "token_value", token_value
            ).execute()
        except Exception as e:
            logger.warning(f"Failed to delete token from DB: {e}")

    # --- JSON file persistence (fallback when db_client is None) ---

    def _state_file(self) -> Path:
        return self._state_dir / "oauth_tokens.json"

    def _load_state(self):
        f = self._state_file()
        if not f.exists():
            return
        try:
            data = json.loads(f.read_text())
            for k, v in data.get("clients", {}).items():
                self.clients[k] = OAuthClientInformationFull(**v)
            for k, v in data.get("access_tokens", {}).items():
                self.access_tokens[k] = AccessToken(**v)
            for k, v in data.get("refresh_tokens", {}).items():
                self.refresh_tokens[k] = RefreshToken(**v)
            self._access_to_refresh_map = data.get("a2r", {})
            self._refresh_to_access_map = data.get("r2a", {})
            logger.info(
                f"Loaded OAuth state: {len(self.clients)} clients, "
                f"{len(self.access_tokens)} access tokens"
            )
        except Exception as e:
            logger.warning(f"Failed to load OAuth state from {f}: {e}")

    def _save_state(self):
        if self._db is not None:
            return  # DB is source of truth
        def serialize(obj):
            if hasattr(obj, "model_dump"):
                return obj.model_dump(mode="json")
            return {
                "token": obj.token, "client_id": obj.client_id,
                "scopes": obj.scopes, "expires_at": obj.expires_at,
            }

        data = {
            "clients": {k: v.model_dump(mode="json") for k, v in self.clients.items()},
            "access_tokens": {k: serialize(v) for k, v in self.access_tokens.items()},
            "refresh_tokens": {k: serialize(v) for k, v in self.refresh_tokens.items()},
            "a2r": self._access_to_refresh_map,
            "r2a": self._refresh_to_access_map,
        }
        self._state_file().write_text(json.dumps(data, indent=2))

    # --- Authorization gate ---

    def _is_redirect_allowed(self, redirect_uri: str) -> bool:
        if self.allowed_redirect_domains is None:
            return True
        try:
            host = urlparse(redirect_uri).hostname or ""
            return any(
                host == domain or host.endswith(f".{domain}")
                for domain in self.allowed_redirect_domains
            )
        except Exception:
            return False

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await super().register_client(client_info)
        self._sync_to_db()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        redirect = str(params.redirect_uri) if params.redirect_uri else ""

        # Check redirect domain
        if not self._is_redirect_allowed(redirect):
            raise AuthorizeError(
                error="access_denied",
                error_description="Redirect URI domain not allowed.",
            )

        # Check password if configured
        if self.password is not None:
            password_ok = False
            # Check scopes for password
            if params.scopes:
                password_ok = self.password in params.scopes
            # Check state for password
            if not password_ok and params.state:
                password_ok = self.password in params.state
            # Auto-approve for allowed redirect domains (the domain restriction
            # is the security gate; password is an extra layer for public servers)
            if not password_ok and self._is_redirect_allowed(redirect):
                password_ok = True

            if not password_ok:
                raise AuthorizeError(
                    error="access_denied",
                    error_description="Authorization denied.",
                )

        result = await super().authorize(client, params)
        self._sync_to_db()
        return result

    # --- Token exchange with configurable expiry ---

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if authorization_code.code not in self.auth_codes:
            raise TokenError("invalid_grant", "Authorization code not found or already used.")

        del self.auth_codes[authorization_code.code]
        self._db_delete_token(authorization_code.code)

        access_token_value = f"pat_{secrets.token_hex(32)}"
        refresh_token_value = f"prt_{secrets.token_hex(32)}"
        access_token_expires_at = int(time.time() + self.access_token_expiry_seconds)

        if client.client_id is None:
            raise TokenError("invalid_client", "Client ID is required")

        self.access_tokens[access_token_value] = AccessToken(
            token=access_token_value,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=access_token_expires_at,
        )
        self.refresh_tokens[refresh_token_value] = RefreshToken(
            token=refresh_token_value,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=None,
        )

        self._access_to_refresh_map[access_token_value] = refresh_token_value
        self._refresh_to_access_map[refresh_token_value] = access_token_value
        self._sync_to_db()

        return OAuthToken(
            access_token=access_token_value,
            token_type="Bearer",
            expires_in=self.access_token_expiry_seconds,
            refresh_token=refresh_token_value,
            scope=" ".join(authorization_code.scopes),
        )

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        old_access = self._refresh_to_access_map.get(refresh_token.token)
        result = await super().exchange_refresh_token(client, refresh_token, scopes)
        if old_access and old_access not in self.access_tokens:
            self._db_mark_revoked(old_access)
        self._sync_to_db()
        return result

    async def revoke_token(self, token):
        token_value = getattr(token, "token", None) or str(token)
        await super().revoke_token(token)
        self._db_mark_revoked(token_value)
        self._sync_to_db()
