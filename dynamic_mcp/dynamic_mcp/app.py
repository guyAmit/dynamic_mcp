from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from .auth import ApiKeyStore, get_auth_mode, get_current_principal, mint_api_key
from .models import (
    CallToolRequest,
    CallToolResponse,
    GetToolRequest,
    GetToolResponse,
    SearchToolsRequest,
    ToolListItem,
    Principal,
    Token,
)
from .registry import ToolRegistry

router = APIRouter()

def pyd_schema(model):
    return model.model_json_schema()

def build_mcp_router(registry: ToolRegistry, *, server_name: str, server_description: str) -> APIRouter:
    r = APIRouter()

    @r.get("/mcp/describe_server")
    async def describe_server(principal: Principal = Depends(get_current_principal)):
        registry.authorize_action(principal, "server:describe")
        return {"name": server_name, "description": server_description}

    @r.get("/mcp/list_tools", response_model=List[ToolListItem])
    async def list_tools(principal: Principal = Depends(get_current_principal)):
        registry.authorize_action(principal, "tools:list")
        return [ToolListItem(name=t.name, description=t.description) for t in registry.list()]

    @r.post("/mcp/get_tool", response_model=GetToolResponse)
    async def get_tool(req: GetToolRequest, principal: Principal = Depends(get_current_principal)):
        registry.authorize_action(principal, "tools:get")
        try:
            t = registry.get(req.name)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
        return GetToolResponse(name=t.name, docstring=(t.fn.__doc__ or ""), input_schema=pyd_schema(t.input_model))

    @r.post("/mcp/call_tool", response_model=CallToolResponse)
    async def call_tool(req: CallToolRequest, principal: Principal = Depends(get_current_principal)):
        registry.authorize_action(principal, "tools:call")
        try:
            t = registry.get(req.name)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
        registry.enforce_tool(principal, t)
        out = await registry.call(t, args=req.arguments, principal=principal)
        return CallToolResponse(name=t.name, result=out)

    return r

# --- Optional token minting API (disabled unless explicitly enabled) ---

def build_auth_router() -> APIRouter:
    r = APIRouter(prefix="/auth", tags=["auth"])

    @r.get("/mode")
    async def auth_mode():
        return {"mode": get_auth_mode()}

    @r.post("/mint", response_model=Token)
    async def mint(
        principal_id: str,
        capabilities: List[str],
        ttl_seconds: int = 60 * 60 * 24 * 7,
        admin_token: str | None = None,
    ):
        """Mint an API key (apikey mode only).

        This is intentionally minimal. In production, prefer minting via CLI or an external IAM system.
        To enable this endpoint, set DYNAMIC_MCP_ENABLE_MINT=1 and provide DYNAMIC_MCP_ADMIN_TOKEN.
        """
        if os.getenv("DYNAMIC_MCP_ENABLE_MINT", "0") != "1":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        expected = os.getenv("DYNAMIC_MCP_ADMIN_TOKEN", "")
        if not expected or admin_token != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

        if get_auth_mode() != "apikey":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Minting only supported in apikey mode")

        from datetime import timedelta, datetime, timezone
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        token = mint_api_key(principal_id=principal_id, capabilities=capabilities, expires_at=expires_at)
        return Token(access_token=token)

    return r

import os
auth_router = build_auth_router()
