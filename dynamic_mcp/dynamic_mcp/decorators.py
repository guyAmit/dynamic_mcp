from __future__ import annotations
from typing import Callable, List, Optional

from .registry import ToolRegistry, Handler

_default_registry = ToolRegistry()

def get_registry() -> ToolRegistry:
    return _default_registry

def tool(
    *,
    # New model: capabilities / tags
    required_caps: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    registry: Optional[ToolRegistry] = None,
) -> Callable[[Handler], Handler]:
    """Register a function as a dynamic-MCP tool.

    Authorization:
      - Prefer `required_caps` (e.g. ["tool:math.*"] or ["tool:add"])
      - Use `tags` to allow tag-based capability grants (e.g. tag:safe)
    """
    def wrapper(fn: Handler) -> Handler:
        reg = registry or _default_registry
        reg.register(
            fn,
            name=name,
            description=description,
            required_caps=required_caps,
            tags=tags,
        )
        return fn
    return wrapper
