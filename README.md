
# Dynamic MCP (Model Context Protocol)

Dynamic MCP is a lightweight and security-aware implementation of the **Model Context Protocol (MCP)** that enables **on-demand tool discovery and invocation** instead of eagerly exposing all tools and schemas to the model upfront.

The core idea is simple but powerful:  
**only provide the model with the tools it actually needs, at the moment it needs them.**

This approach significantly reduces token usage, improves reasoning quality around tool calls, and slightly raises the bar for attackers during reconnaissance — all while remaining fully compatible with existing MCP concepts.

---

## 1. Concept & Advantages

### On-Demand Tool Fetching

Traditional MCP setups often inject *all* available tool schemas into the model context at startup. Dynamic MCP replaces this with a **just-in-time discovery model**:

1. The client retrieves basic server metadata.
2. When a task requires a tool, the client explicitly asks the server for relevant tool schemas.
3. Only the matching tool schemas are injected into the model context.
4. The model calls the tool using the standard MCP flow.

This makes tool usage **intentional**, **minimal**, and **context-aligned**.

---

### Reduced Token Consumption

Fetching all tool schemas upfront can easily consume thousands of tokens, especially in large systems with many tools.

Dynamic MCP avoids this by:
- Not serializing unused tool schemas
- Injecting only a small subset of tools per request
- Keeping prompts shorter and more focused

This leads to:
- Lower latency
- Lower cost
- More available context window for reasoning

---

### Tool Schemas Are Closer to the Actual Tool Call

Because tools are fetched immediately before use:
- Their schemas appear **closer in the context** to the actual `tool_call`
- The model is less likely to hallucinate parameters
- Argument names and types are fresher in the model’s attention

This typically results in **higher-quality and more accurate tool calls** compared to large, distant schema blocks at the beginning of the prompt.

---

Here’s the same section **with a compact, concrete code example**, written to drop cleanly into your README:

---

### Short Descriptions vs. Full Tool Schemas

In Dynamic MCP, tools are decorated with a **short description** that is always available for lightweight discovery. This description is intentionally concise and used to determine **which tool should be fetched**, without exposing the full schema upfront.

The **full tool schema and detailed documentation** — including parameter definitions and rich docstrings — are fetched **only on demand**, immediately before the tool is invoked.

This enables:

* Accurate tool selection with minimal context
* Rich, expressive docstrings without token bloat
* Better parameter accuracy at call time
* Reduced passive exposure of internal APIs

If a tool decorator does **not** define a short description, Dynamic MCP automatically falls back to using the tool’s **docstring** as the description.

---

#### Example

```python
from dynamic_mcp import tool

@tool(
    description="Add two integers together",
    required_caps=["tool:math.add"],
    tags=["safe", "arithmetic"]
)
def add(a: int, b: int) -> int:
    """
    Adds two integers and returns their sum.

    Parameters:
        a (int): First operand
        b (int): Second operand

    Returns:
        int: The sum of a and b
    """
    return a + b
```

**How this is used internally:**

* During discovery, only
  `"Add two integers together"`
  is exposed to decide whether this tool is relevant.
* When the tool is selected, the **full schema and docstring** are fetched and injected into the model context right before the `tool_call`.

This allows tool authors to write **clear, complete documentation** without paying the cost unless the tool is actually used.

---


### Security by Reduced Exposure

Dynamic MCP does **not** claim to be a full security solution — but it does provide a meaningful improvement during the **reconnaissance phase** of an attack.

By default:
- The model never sees the full tool surface
- Unused tool schemas are never exposed
- Attackers must actively probe to discover functionality

> In short: **you don’t expose what you don’t need**.

---

## 2. Installation & Usage

### Setup

```bash
git clone https://github.com/your-org/dynamic-mcp.git
cd dynamic-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Environment Variables & API Keys

Dynamic MCP uses **HMAC-signed API keys** and environment variables to secure client–server communication.

#### Required Environment Variables

```bash
# Shared secret used to sign and verify API keys (openssl rand -base64 32)
export DYNAMIC_MCP_APIKEY_HMAC_SECRET="change-this-secret"
```

### Starting the Server

```bash
python server.py
```

### Example HTTP Request

```http
POST /mcp/call_tool
Content-Type: application/json

{
  "tool_name": "math.add",
  "arguments": {
    "a": 2,
    "b": 3
  }
}
```

---

## 3. Security Model

Dynamic MCP supports **three security modes**:

1. Open mode
2. Tag-based filtering
3. Capability-based authorization (recommended)

### Capabilities

```python
@tool(required_caps=["tool:math.add"])
def add(a: int, b: int) -> int:
    return a + b
```


Capabilities support:
- Namespacing
- Wildcards (`tool:math.*`)
- Fine-grained access control

### Tags

```python
@tool(
    required_caps=["tool:math.*"],
    tags=["safe", "arithmetic"]
)
def multiply(a: int, b: int) -> int:
    return a * b
```

Tags are for discovery and categorization only — **not authorization**.

---

### Generating an API Key

API keys are **capability tokens**, not opaque secrets. They are cryptographically signed and can be safely verified by the server.

Example (Python):

```python
from dynamic_mcp.security import generate_api_key

api_key = mint_api_key(
            principal_id="demo",
            # Allow the common MCP actions and all tools in this demo
            capabilities=[
                "tools:list",
                "tools:get",
                "tools:call",
                "tool:math:*",
            ],
        )

print(api_key)
```

The generated key encodes:
- Subject / user identifier
- Allowed capabilities
- Expiration timestamp
- HMAC signature

The server validates the signature and enforces capabilities on every request.


## Summary

Dynamic MCP provides:
- On-demand tool schemas
- Lower token usage
- Better tool-call accuracy
- Reduced schema exposure
- Flexible, capability-based security
