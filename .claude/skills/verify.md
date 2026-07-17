# OCP MCP Server UI Verifier

## Environment requirements

### mcp version
`app.py` imports from `mcp.server.mcpserver.server` (mcp 2.0.0b1 path). Current PyPI max is 1.28.1.
**Workaround:** Temporarily patch `app.py`:
```bash
sed -i '' 's|from mcp.server.mcpserver.server import MCPServer as FastMCP|from mcp.server.fastmcp import FastMCP|' src/ocp_mcp/app.py
# restore after:
git checkout src/ocp_mcp/app.py
```

### Gradio version
The UI targets Gradio 4.x/5.x. Gradio 6.x removed `type="tuples"` from Chatbot and moved `theme=` from `Blocks()` to `launch()`. With Gradio 6+, these must be patched for testing.

### Install
```bash
pip install -e ".[ui]"   # installs gradio + anthropic
```

## Running
```bash
ANTHROPIC_API_KEY=sk-ant-... ocp-mcp-ui
# Opens at http://localhost:7860
```

## What to drive
1. **Tool Playground**: pick `get_cluster_info`, click Run → should return error string (no cluster), not exception
2. **Tool selection**: pick any tool → should show description + parameter rows
3. **Chat (no key)**: send message without ANTHROPIC_API_KEY → should show "not set" inline message
4. **Chat (bad key)**: send with invalid key → should show "API error" inline, chatbot state should NOT accumulate
5. **Example buttons**: click any example button → should auto-submit the example text
6. **Clear Chat**: mid-request → should cancel in-flight request

## Testing via gradio_client
```python
from gradio_client import Client
c = Client("http://127.0.0.1:7860/", verbose=False)
# Tool select
c.predict("get_cluster_info", api_name="/on_tool_select")
# Run tool
c.predict("get_cluster_info", "(default)", [], *[""] * 15, api_name="/lambda_1")
# Chat
c.predict("list pods", [], [], api_name="/on_chat_send")
# Example buttons
c.predict([], [], api_name="/_fn")   # first example
```

## Flows NOT exercisable without a real cluster
- Any tool that makes Kubernetes API calls (all 216 tools will return connection errors)
- Multi-turn tool-calling loop in chat (needs valid API key + cluster)
