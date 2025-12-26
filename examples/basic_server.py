"""Basic dynamic-mcp server example (default auth mode: apikey).

How to run:

1) Create a .env with at least:

   DYNAMIC_MCP_APIKEY_HMAC_SECRET=change-me-to-a-long-random-string

   # Optional: where to store API keys (defaults to ~/.dynamic_mcp/apikeys.json)
   # DYNAMIC_MCP_APIKEY_STORE=./apikeys.json

2) Start the server:

   uvicorn basic_server:app --reload

3) Mint a demo key (printed once at startup) or mint your own:

   The demo prints a key to stdout on first start. Export it for the client:
     export DYNAMIC_MCP_API_KEY='...'
"""

from dynamic_mcp import tool, create_app
from dynamic_mcp.auth import mint_api_key
from dotenv import load_dotenv  
load_dotenv()  # take environment variables from .env

@tool(tags=["safe", "math"], required_caps=['tool:math:add'], description="Add two floats.")
def add(a: float, b: float) -> float:
    """Add two numbers a and b and return the result.
        a: float - The first number to add.
        b: float - The second number to add.
        returns: float - The sum of a and b.
    """
    return a + b

@tool(tags=["safe", "math"], required_caps=['tool:math:mult'], description="Multiply two floats.")
def multiply(a: float, b: float) -> float:
    """Multiply two numbers a and b and return the result.
        a: float - The first number to multiply.
        b: float - The second number to multiply.
        returns: float - The product of a and b.
    """
    return a * b

@tool(tags=["safe", "math"], required_caps=['tool:math:div'], description="Divide two floats.")
def divide(a: float, b: float) -> float:
    """Divide two numbers a and b and return the result.
        a: float - The first number to divide.
        b: float - The second number to divide.
        returns: float - The quotient of a and b.
    """
    return a / (b+1e-10)  # avoid div by zero

@tool(tags=["dangerous"], required_caps=['tool:secret:*'], description="Fetch a secret by key (demo).")
def get_secret(key: str) -> str:
    """Fetch a secret by key (demo)."""
    return f"secret-value-for:{key}"


app = create_app(
    server_name="Basic Dynamic MCP Server",
    server_description="An example dynamic MCP server with basic math tools.",
)

# Mint a demo key (best-effort) so people can immediately use the client.
# NOTE: With --reload, this file is imported multiple times; minting every reload
# would create many keys. So we only mint if the user did not provide a key.
import os

if not os.getenv("DYNAMIC_MCP_DEMO_KEY_MINTED", ""):
    os.environ["DYNAMIC_MCP_DEMO_KEY_MINTED"] = "1"
    try:
        demo_key = mint_api_key(
            principal_id="demo",
            # Allow the common MCP actions and all tools in this demo
            capabilities=[
                "server:describe",
                "tools:list",
                "tools:get",
                "tools:call",
                "tool:math:*",
            ],
        )
        print("\n=== dynamic-mcp demo API key (set this in your client) ===")
        print(demo_key)
        print("=========================================================\n")
    except Exception as e:
        # Most common cause: missing DYNAMIC_MCP_APIKEY_HMAC_SECRET
        print(f"[basic_server] Could not mint demo API key: {e}")

# Run: uvicorn basic_server:app --reload
