from fastmcp import FastMCP

mcp = FastMCP("Calculator MCP")

@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers and return the result."""
    print(f"[MCP TOOL] Adding {a} and {b}")
    return a + b

if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=8000)
