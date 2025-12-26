from __future__ import annotations
from fastapi import FastAPI

from .app import auth_router, build_mcp_router
from .registry import ToolRegistry
from .decorators import get_registry

def create_app(
    registry: ToolRegistry | None = None,
    server_name: str = "dynamic-mcp",
    server_description: str = "A dynamic MCP server.",
) -> FastAPI:
    reg = registry or get_registry()

    app = FastAPI(title="dynamic-MCP (capability tokens)")
    app.include_router(auth_router)
    app.include_router(build_mcp_router(reg, server_name=server_name, server_description=server_description))

    @app.get("/health")
    def health():
        return {"ok": True}

    return app
