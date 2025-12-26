from __future__ import annotations

import inspect
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Callable, Dict, List, Optional, Type, get_type_hints

from pydantic import BaseModel, ValidationError, create_model

from .models import Principal

Handler = Callable[..., Any]

def _is_async(fn: Handler) -> bool:
    return inspect.iscoroutinefunction(fn)

@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    fn: Handler
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    required_caps: List[str]
    tags: List[str]

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolDef] = {}

    def list(self) -> List[ToolDef]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolDef:
        return self._tools[name]

    def register(
        self,
        fn: Handler,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        required_caps: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> ToolDef:
        tool_name = name or fn.__name__
        desc = description or (fn.__doc__ or "").strip() or f"Tool {tool_name}"

        # Build input model from signature
        sig = inspect.signature(fn)
        hints = get_type_hints(fn)
        fields: Dict[str, Any] = {}

        for pname, p in sig.parameters.items():
            if pname == "user":
                continue
            ann = hints.get(pname, Any)
            default = ... if p.default is inspect._empty else p.default
            fields[pname] = (ann, default)

        input_model = create_model(f"{tool_name}_Input", **fields)  # type: ignore[arg-type]

        # Wrap output value
        output_model = create_model(f"{tool_name}_Output", value=(Any, ...))  # type: ignore[arg-type]

        # Authorization metadata
        req: List[str] = []
        if required_caps:
            req.extend(required_caps)
        if not req:
            # default: capability per tool name
            req = [f"tool:{tool_name}"]

        tool_tags = list(tags or [])

        t = ToolDef(
            name=tool_name,
            description=desc,
            fn=fn,
            input_model=input_model,
            output_model=output_model,
            required_caps=req,
            tags=tool_tags,
        )
        self._tools[tool_name] = t
        return t

    def _principal_has(self, principal: Principal, required: str) -> bool:
        # Expand tool tags into virtual required caps: tag:<tag>
        # Caller side patterns are supported (fnmatch semantics).
        for cap in principal.capabilities:
            if cap == "*" or cap == "admin:*":
                return True
            if fnmatch(required, cap) or fnmatch(cap, required):
                return True
        return False

    def authorize_action(self, principal: Principal, action: str) -> None:
        # action is something like tools:list, tools:search, tools:get, tools:call
        if self._principal_has(principal, action):
            return
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing capability: {action}")

    def enforce_tool(self, principal: Principal, tool: ToolDef) -> None:
        from fastapi import HTTPException, status

        # required caps
        for req in tool.required_caps:
            if self._principal_has(principal, req):
                return

        # tag caps (tag:<tag>)
        for tag in tool.tags:
            if self._principal_has(principal, f"tag:{tag}"):
                return

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this tool")

    async def call(self, tool: ToolDef, *, args: dict, principal: Principal) -> dict:
        # Validate
        try:
            parsed = tool.input_model(**args)
        except ValidationError as e:
            from fastapi import HTTPException, status
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors())

        # Inject principal if the function accepts it (back compat: parameter name 'user' too)
        sig = inspect.signature(tool.fn)
        kwargs = dict(parsed.model_dump())
        if "principal" in sig.parameters:
            kwargs["principal"] = principal
        elif "user" in sig.parameters:
            kwargs["user"] = principal  # type: ignore[assignment]

        # Call
        if _is_async(tool.fn):
            value = await tool.fn(**kwargs)  # type: ignore[misc]
        else:
            value = tool.fn(**kwargs)

        out = tool.output_model(value=value)
        return out.model_dump()
