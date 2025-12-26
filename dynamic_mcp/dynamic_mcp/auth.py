from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import Principal

AUTH_MODE_ENV = "DYNAMIC_MCP_AUTH_MODE"  # none | apikey | external
APIKEY_STORE_ENV = "DYNAMIC_MCP_APIKEY_STORE"  # path to json store
APIKEY_HMAC_SECRET_ENV = "DYNAMIC_MCP_APIKEY_HMAC_SECRET"  # required for apikey mode

# External auth headers
EXT_PRINCIPAL_HEADER = "X-MCP-Principal"
EXT_CAPABILITIES_HEADER = "X-MCP-Capabilities"  # comma separated patterns
EXT_CONSTRAINTS_HEADER = "X-MCP-Constraints"  # optional JSON

bearer = HTTPBearer(auto_error=False)

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def get_auth_mode() -> str:
    return os.getenv(AUTH_MODE_ENV, "apikey").strip().lower()

def _store_path() -> Path:
    p = os.getenv(APIKEY_STORE_ENV)
    if p:
        return Path(p).expanduser().resolve()
    return (Path.home() / ".dynamic_mcp" / "apikeys.json").resolve()

def _hmac_secret() -> bytes:
    s = os.getenv(APIKEY_HMAC_SECRET_ENV, "")
    if not s:
        raise RuntimeError(
            f"{APIKEY_HMAC_SECRET_ENV} must be set for apikey auth mode."
        )
    return s.encode("utf-8")

def _hmac_digest(token: str, secret: bytes) -> str:
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()

@dataclass
class StoredKey:
    key_id: str
    token_hmac: str
    principal_id: str
    capabilities: List[str]
    constraints: Dict[str, Any]
    created_at: str
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    last_used_at: Optional[str] = None

class ApiKeyStore:
    """Simple JSON-backed store for opaque API keys."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"keys": []})

    def _read(self) -> Dict[str, Any]:
        return json.loads(self.path.read_text())

    def _write(self, obj: Dict[str, Any]) -> None:
        self.path.write_text(json.dumps(obj, indent=2, sort_keys=True))

    def mint_key(
        self,
        *,
        principal_id: str,
        capabilities: List[str],
        constraints: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime] = None,
        prefix: str = "mcp_live_",
    ) -> str:
        # opaque token that the client will present
        token = prefix + secrets.token_urlsafe(32)
        secret = _hmac_secret()
        token_hmac = _hmac_digest(token, secret)

        rec = StoredKey(
            key_id="k_" + secrets.token_urlsafe(10),
            token_hmac=token_hmac,
            principal_id=principal_id,
            capabilities=capabilities,
            constraints=constraints or {},
            created_at=_utcnow().isoformat(),
            expires_at=expires_at.isoformat() if expires_at else None,
            revoked_at=None,
            last_used_at=None,
        )

        db = self._read()
        db["keys"].append(rec.__dict__)
        self._write(db)
        return token

    def revoke(self, token: str) -> bool:
        secret = _hmac_secret()
        token_hmac = _hmac_digest(token, secret)
        db = self._read()
        changed = False
        for k in db.get("keys", []):
            if k.get("token_hmac") == token_hmac and not k.get("revoked_at"):
                k["revoked_at"] = _utcnow().isoformat()
                changed = True
        if changed:
            self._write(db)
        return changed

    def resolve(self, token: str) -> Principal:
        secret = _hmac_secret()
        token_hmac = _hmac_digest(token, secret)
        db = self._read()
        now = _utcnow()

        for k in db.get("keys", []):
            if k.get("token_hmac") != token_hmac:
                continue

            if k.get("revoked_at"):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key revoked")

            exp = k.get("expires_at")
            if exp:
                try:
                    exp_dt = datetime.fromisoformat(exp)
                except Exception:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key invalid expiry")
                if exp_dt < now:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")

            # update last_used_at (best effort)
            k["last_used_at"] = now.isoformat()
            try:
                self._write(db)
            except Exception:
                pass

            return Principal(
                principal_id=k.get("principal_id", "unknown"),
                capabilities=list(k.get("capabilities") or []),
                constraints=dict(k.get("constraints") or {}),
                disabled=False,
            )

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

def _principal_noauth() -> Principal:
    # Explicitly wide-open: intended for localhost development only.
    return Principal(principal_id="anonymous", capabilities=["*"], constraints={}, disabled=False)

def _principal_external(request: Request) -> Principal:
    pid = request.headers.get(EXT_PRINCIPAL_HEADER, "").strip()
    if not pid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Missing {EXT_PRINCIPAL_HEADER}")

    caps_raw = request.headers.get(EXT_CAPABILITIES_HEADER, "").strip()
    capabilities = [c.strip() for c in caps_raw.split(",") if c.strip()]

    constraints: Dict[str, Any] = {}
    cons_raw = request.headers.get(EXT_CONSTRAINTS_HEADER, "").strip()
    if cons_raw:
        try:
            constraints = json.loads(cons_raw)
            if not isinstance(constraints, dict):
                constraints = {}
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid {EXT_CONSTRAINTS_HEADER}")

    return Principal(principal_id=pid, capabilities=capabilities, constraints=constraints, disabled=False)

def get_current_principal(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> Principal:
    """FastAPI dependency returning the current Principal according to auth mode."""
    mode = get_auth_mode()

    if mode == "none":
        return _principal_noauth()

    if mode == "external":
        return _principal_external(request)

    # default: apikey
    if mode != "apikey":
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unknown auth mode: {mode}")

    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    store = ApiKeyStore(_store_path())
    return store.resolve(creds.credentials)

# Convenience helper for demos / admins:
def mint_api_key(
    *,
    principal_id: str,
    capabilities: List[str],
    constraints: Optional[Dict[str, Any]] = None,
    expires_at: Optional[datetime] = None,
) -> str:
    """Mint and persist an API key in the JSON store (apikey mode)."""
    store = ApiKeyStore(_store_path())
    return store.mint_key(
        principal_id=principal_id,
        capabilities=capabilities,
        constraints=constraints,
        expires_at=expires_at,
    )
