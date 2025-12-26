#!/usr/bin/env python3
"""
dynamic-mcp autonomous agent demo (LangChain OpenAI client)

This version uses `langchain_openai.ChatOpenAI` (OpenAI-style tool calling) instead of Ollama.

It still enforces the same rule:
1) call `get_tool(name)` to fetch the tool's schema
2) then call `call_tool(name, arguments)` with args that match that schema
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional

import requests
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from textwrap import dedent

from dotenv import load_dotenv
load_dotenv()

# -----------------------------
# dynamic-mcp HTTP client
# -----------------------------
class DynamicMCPClient:
    """Tiny HTTP client for dynamic-mcp.

    Default server auth mode is **apikey** (opaque bearer token).
    So the client simply sends:

        Authorization: Bearer <API_KEY>

    There is no login flow.
    """

    def __init__(self, base_url: str, api_key: str, timeout_s: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s

    @property
    def headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError(
                "Missing API key. Provide --api-key or set DYNAMIC_MCP_API_KEY."
            )
        return {"Authorization": f"Bearer {self.api_key}"}

    def list_tools(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/mcp/list_tools"
        resp = requests.get(url, headers=self.headers, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def get_tool(self, name: str) -> Dict[str, Any]:
        url = f"{self.base_url}/mcp/get_tool"
        resp = requests.post(url, headers=self.headers, json={"name": name}, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/mcp/call_tool"
        resp = requests.post(url, headers=self.headers, json={"name": name, "arguments": arguments}, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

def extract_arguments(args_json: Dict[str, Any]) -> Dict[str, Any]:
    if 'arguments' in args_json:
        return args_json['arguments']
    elif 'parameters' in args_json:
        return args_json['parameters']
    else:
        return {}

def format_tool_menu(tool_list: List[Dict[str, Any]]) -> str:
    lines = ["Available tools (name — description):"]
    for t in tool_list:
        lines.append(f"- {t['name']} — {t.get('description','')}".strip())
    return "\n".join(lines)


# -----------------------------
# Explicit OpenAI tool schemas
# -----------------------------
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_tool",
            "description": "Fetch the full schema/spec for a tool by name from dynamic-mcp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Tool name to retrieve schema for"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_tool",
            "description": "Execute a tool on dynamic-mcp by name with JSON arguments (must match schema).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Tool name to execute"},
                    "arguments": {"type": "object", "description": "Arguments object for the tool"},
                },
                "required": ["name", "arguments"],
            },
        },
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="LangChain OpenAI autonomous agent client for dynamic-mcp.")
    parser.add_argument("prompt", type=str, help="User prompt to the agent.")
    parser.add_argument("--model", type=str, default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), help="OpenAI model name.")
    parser.add_argument("--mcp-base", type=str, default="http://localhost:8000", help="dynamic-mcp server base URL.")
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.getenv("DYNAMIC_MCP_API_KEY", ""),
        help="dynamic-mcp API key (Bearer token). You can also set DYNAMIC_MCP_API_KEY.",
    )
    parser.add_argument("--max-steps", type=int, default=12, help="Maximum tool-call iterations.")
    parser.add_argument("--verbose", action="store_true", help="Print tool calls and tool outputs.")
    args = parser.parse_args()

    mcp = DynamicMCPClient(args.mcp_base, args.api_key)
    tool_list = mcp.list_tools()

    system = dedent(f"""
    You are an autonomous agent that can call tools exposed by a dynamic-mcp server.

    Available tools you can directly call:
    - get_tool — Fetch the full schema/spec for a tool by name
    - call_tool — Execute a tool by name with arguments matching its schema

    Available server tools (use get_tool first to understand their schema):
    {format_tool_menu(tool_list)}

    RULES:
    1. To use any server tool, FIRST call `get_tool(name)` to fetch its schema
    2. Read the `input_schema` from the response carefully
    3. Construct arguments that exactly match the schema
    4. THEN call `call_tool(name, arguments)` with those arguments
    5. The way to give the tool_call arguments is to provide the "arugments" key in the json, not the "parameters" key.

    IMPORTANT: You can ONLY directly call `get_tool` and `call_tool`. 
    You cannot directly call the server tools (add, multiply, etc).
    You must use get_tool and call_tool to interact with them.

    Your job is to decide which server tool to use and call it correctly.
    """.strip())

    llm = ChatOpenAI(
        model=args.model,
        temperature=0,
    ).bind_tools(OPENAI_TOOLS)

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=args.prompt),
    ]

    for _ in range(args.max_steps):
        ai: AIMessage = llm.invoke(messages)
        messages.append(ai)

        tool_calls = getattr(ai, "tool_calls", None) or []
        if not tool_calls:
            print((ai.content or "").strip())
            return

        for tc in tool_calls:
            name = tc.get("name")
            args_json = tc.get("args") or {}
            call_id = tc.get("id") or tc.get("tool_call_id") or ""

            # If the model/tooling didn't provide an id (rare), generate a stable-ish one
            # to avoid OpenAI API errors about missing tool_call_id.
            if not call_id:
                call_id = f"tc_{abs(hash((name, json.dumps(args_json, sort_keys=True))))}"

            if args.verbose:
                print(f"[tool_call] {name} {json.dumps(args_json, ensure_ascii=False)}")

            if name == "get_tool":
                result = mcp.get_tool(args_json["name"])
            elif name == "call_tool":
                arguments = extract_arguments(args_json)
                result = mcp.call_tool(args_json["name"], arguments)
            else:
                result = {"error": f"Unknown tool: {name}"}

            if args.verbose:
                print(f"[tool_result] {name} {json.dumps(result, ensure_ascii=False)}")

            messages.append(
                ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=call_id)
            )

    print("Stopped: reached max steps without a final non-tool response. Try increasing --max-steps.")


if __name__ == "__main__":
    main()
