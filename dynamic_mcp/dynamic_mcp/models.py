from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class ToolListItem(BaseModel):
    name: str
    description: str

class GetToolResponse(BaseModel):
    name: str
    docstring: str
    input_schema: Dict[str, Any]

class GetToolRequest(BaseModel):
    name: str

class SearchToolsRequest(BaseModel):
    description: str
    threshold: float = 0.35

class CallToolRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)

class CallToolResponse(BaseModel):
    name: str
    result: Any

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class Principal(BaseModel):
    """Authenticated caller context."""
    principal_id: str
    capabilities: List[str] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    disabled: bool = False
