#!/usr/bin/env python3
"""
mcp_chat.py — Universal interactive chat client for any MCP SSE server.

Prompts for all configuration at startup; no env vars required (though they
are used as defaults when present).  Supports:

  • Anthropic API        — direct, API key
  • Google Vertex AI     — Anthropic models via GCP project + region
  • Ollama               — local or remote, any model
  • OpenAI-compatible    — OpenAI, LM Studio, vLLM, llama.cpp, etc.

For HTTPS endpoints backed by a self-signed certificate the script will ask
whether to skip SSL verification rather than failing with a certificate error.

Install dependencies:
  pip install mcp anthropic "anthropic[vertex]" openai httpx
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from typing import Any

import httpx

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client


# ── Interactive setup ─────────────────────────────────────────────────────────

def ask(prompt: str, default: str = "") -> str:
    """Single-line prompt with a default shown in brackets."""
    display = f" [{default}]" if default else ""
    value = input(f"{prompt}{display}: ").strip()
    return value or default


def ask_secret(prompt: str, default: str = "") -> str:
    """Like ask() but masks the existing default so the key is not echoed."""
    masked = f" [{'*' * min(len(default), 8)}…]" if default else ""
    value = input(f"{prompt}{masked}: ").strip()
    return value or default


def ask_bool(prompt: str, default: bool = True) -> bool:
    """Y/n prompt; returns a bool."""
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def ask_choice(prompt: str, choices: list[tuple[str, str]]) -> str:
    """Numbered menu; returns the key string of the chosen option."""
    print(f"\n{prompt}")
    for i, (_, label) in enumerate(choices, 1):
        print(f"  {i}. {label}")
    while True:
        raw = input("Choice: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return choices[int(raw) - 1][0]
        print(f"  Please enter a number between 1 and {len(choices)}.")


def _is_https(url: str) -> bool:
    return url.lower().startswith("https://")


def _ask_ssl_verify(url: str, label: str) -> bool:
    """
    If *url* is HTTPS, ask whether the server has a valid (CA-signed) cert.
    Returns True = verify (safe default), False = skip verification.
    HTTP URLs always return True (no TLS to verify).
    """
    if not _is_https(url):
        return True
    print(f"\n  {label} is using HTTPS.")
    valid = ask_bool(
        f"  Does it use a valid CA-signed certificate? (answer 'n' for self-signed / internal CA)",
        default=True,
    )
    return valid  # True → verify=True, False → verify=False


def prompt_config() -> dict[str, Any]:
    """Walk the user through all runtime settings and return a config dict."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║                  MCP Chat — Setup                           ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    cfg: dict[str, Any] = {}

    # ── MCP server ──────────────────────────────────────────────────────────
    cfg["mcp_transport"] = ask_choice(
        "MCP transport  (check your server's docs or startup logs)",
        [
            ("sse",             "SSE              — older transport, endpoint is typically /sse"),
            ("streamable-http", "Streamable-HTTP  — newer transport, endpoint is typically /mcp"),
        ],
    )
    cfg["mcp_url"] = ask(
        "MCP server URL  (e.g. http://host:port/sse  or  http://host:port/mcp)",
        os.environ.get("MCP_SERVER_URL", ""),
    )
    cfg["mcp_ssl_verify"] = _ask_ssl_verify(cfg["mcp_url"], "The MCP server URL")

    # ── LLM provider ────────────────────────────────────────────────────────
    cfg["provider"] = ask_choice(
        "LLM provider",
        [
            ("anthropic", "Anthropic API  (API key)"),
            ("vertex",    "Google Vertex AI  (GCP project ID + region, GCP ADC auth)"),
            ("ollama",    "Ollama  (local or remote)"),
            ("openai",    "OpenAI-compatible  (OpenAI / LM Studio / vLLM / llama.cpp / …)"),
        ],
    )

    # ── Provider-specific settings ───────────────────────────────────────────
    if cfg["provider"] == "anthropic":
        cfg["api_key"] = ask_secret(
            "Anthropic API key",
            os.environ.get("ANTHROPIC_API_KEY", ""),
        )
        cfg["model"] = ask(
            "Model",
            os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
        )
        # Anthropic's API always uses valid CA-signed certs; no SSL prompt needed.
        cfg["model_ssl_verify"] = True

    elif cfg["provider"] == "vertex":
        print(
            "\n  Vertex auth uses GCP Application Default Credentials.\n"
            "  Run `gcloud auth application-default login` if not already done.\n"
        )
        cfg["vertex_project"] = ask(
            "GCP project ID",
            os.environ.get(
                "ANTHROPIC_VERTEX_PROJECT_ID",
                os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
            ),
        )
        cfg["vertex_region"] = ask(
            "Region",
            os.environ.get(
                "CLOUD_ML_REGION",
                os.environ.get("ANTHROPIC_VERTEX_REGION", "us-east5"),
            ),
        )
        cfg["model"] = ask(
            "Model",
            os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8"),
        )
        # Google Vertex always uses valid CA-signed certs.
        cfg["model_ssl_verify"] = True

    elif cfg["provider"] == "ollama":
        cfg["base_url"] = ask(
            "Ollama base URL",
            os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        )
        cfg["model"] = ask(
            "Model  (run `ollama list` to see available models)",
            os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
        )
        cfg["model_ssl_verify"] = _ask_ssl_verify(cfg["base_url"], "The Ollama endpoint")

    elif cfg["provider"] == "openai":
        cfg["base_url"] = ask(
            "API base URL",
            os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        cfg["api_key"] = ask_secret(
            "API key  (leave blank if not required)",
            os.environ.get("OPENAI_API_KEY", ""),
        )
        cfg["model"] = ask(
            "Model",
            os.environ.get("OPENAI_MODEL", "gpt-4o"),
        )
        cfg["model_ssl_verify"] = _ask_ssl_verify(cfg["base_url"], "The API endpoint")

    print("\n──────────────────────────────────────────────────────────────\n")
    return cfg


# ── SSL helpers ───────────────────────────────────────────────────────────────

@contextlib.contextmanager
def _patch_httpx_async_ssl(verify: bool):
    """
    Temporarily force httpx.AsyncClient to use the given *verify* setting.

    mcp's sse_client() creates its own httpx.AsyncClient internally and does
    not expose a verify= parameter.  This context manager patches the
    constructor for the duration of the MCP connection so self-signed certs
    are accepted when verify=False.  The patch is scoped and restored on exit.
    """
    if verify:
        yield
        return

    _orig = httpx.AsyncClient.__init__

    def _patched(self, *args, **kwargs):
        kwargs["verify"] = False
        _orig(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = _patched  # type: ignore[method-assign]
    try:
        yield
    finally:
        httpx.AsyncClient.__init__ = _orig  # type: ignore[method-assign]


# ── Client builders ───────────────────────────────────────────────────────────

def build_anthropic_client(cfg: dict[str, Any]):
    try:
        from anthropic import Anthropic, AnthropicVertex  # noqa: PLC0415
    except ImportError:
        sys.exit("Missing dependency — run: pip install anthropic 'anthropic[vertex]'")

    if cfg["provider"] == "vertex":
        return AnthropicVertex(
            project_id=cfg["vertex_project"],
            region=cfg["vertex_region"],
        )
    return Anthropic(api_key=cfg["api_key"] or None)


def build_openai_client(cfg: dict[str, Any]):
    try:
        from openai import OpenAI  # noqa: PLC0415
    except ImportError:
        sys.exit("Missing dependency — run: pip install openai")

    base_url = cfg["base_url"].rstrip("/")
    if cfg["provider"] == "ollama" and not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"

    verify = cfg.get("model_ssl_verify", True)
    return OpenAI(
        base_url=base_url,
        api_key=cfg.get("api_key") or "ollama",  # many local servers ignore the key
        # Pass a custom sync httpx.Client so SSL verification can be controlled.
        http_client=httpx.Client(verify=verify),
    )


# ── Tool schema converters ────────────────────────────────────────────────────

def mcp_to_anthropic_tools(mcp_tools: list) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in mcp_tools
    ]


def mcp_to_openai_tools(mcp_tools: list) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema,
            },
        }
        for t in mcp_tools
    ]


# ── Agentic loops ─────────────────────────────────────────────────────────────

async def anthropic_turn(
    session: ClientSession,
    client: Any,
    model: str,
    tools: list,
    messages: list,
) -> str:
    """One user turn via the Anthropic API. Returns final assistant text."""
    while True:
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            tools=tools,
            messages=messages,
        )

        # Append assistant turn BEFORE tool results — required by the API so that
        # tool_use blocks appear in history before their matching tool_result blocks.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            )

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"  → {block.name}({json.dumps(block.input, separators=(',', ':'))})")
            result = await session.call_tool(block.name, block.input)
            content = "\n".join(c.text for c in result.content if hasattr(c, "text"))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content,
            })

        messages.append({"role": "user", "content": tool_results})


async def openai_turn(
    session: ClientSession,
    client: Any,
    model: str,
    tools: list,
    messages: list,
) -> str:
    """One user turn via an OpenAI-compatible API. Returns final assistant text."""
    while True:
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        response = client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        # Serialize to a plain dict for broadest provider compatibility.
        assistant_entry: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content,
        }
        if msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_entry)

        if not msg.tool_calls:
            return msg.content or ""

        for tc in msg.tool_calls:
            fn = tc.function
            args = (
                fn.arguments
                if isinstance(fn.arguments, dict)
                else json.loads(fn.arguments or "{}")
            )
            print(f"  → {fn.name}({json.dumps(args, separators=(',', ':'))})")
            result = await session.call_tool(fn.name, args)
            content = "\n".join(c.text for c in result.content if hasattr(c, "text"))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": content,
            })


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    cfg = prompt_config()
    model = cfg["model"]
    is_anthropic = cfg["provider"] in ("anthropic", "vertex")

    client = build_anthropic_client(cfg) if is_anthropic else build_openai_client(cfg)

    mcp_verify: bool = cfg["mcp_ssl_verify"]
    if not mcp_verify:
        print("  ⚠  SSL verification disabled for MCP server (self-signed cert).")

    print(f"Connecting to MCP server at {cfg['mcp_url']} …")

    # _patch_httpx_async_ssl patches httpx.AsyncClient's constructor for the
    # duration of the MCP connection so sse_client() skips cert verification
    # when the server uses a self-signed certificate.
    _mcp_ctx = (
        sse_client(cfg["mcp_url"])
        if cfg["mcp_transport"] == "sse"
        else streamablehttp_client(cfg["mcp_url"])
    )

    with _patch_httpx_async_ssl(mcp_verify):
        async with _mcp_ctx as conn:
            read, write = conn[0], conn[1]  # sse: 2-tuple; streamable-http: 3-tuple
            async with ClientSession(read, write) as session:
                await session.initialize()
                mcp_tools_raw = (await session.list_tools()).tools

                tools = (
                    mcp_to_anthropic_tools(mcp_tools_raw)
                    if is_anthropic
                    else mcp_to_openai_tools(mcp_tools_raw)
                )

                print(
                    f"Ready — {len(tools)} tools available"
                    f" | provider: {cfg['provider']}"
                    f" | model: {model}"
                    f"\nType 'quit' to exit.\n"
                )

                messages: list[dict[str, Any]] = []

                while True:
                    try:
                        user_input = input("You: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print()
                        break

                    if user_input.lower() in ("quit", "exit", "q", "bye"):
                        break
                    if not user_input:
                        continue

                    messages.append({"role": "user", "content": user_input})
                    pre_turn = len(messages)

                    try:
                        if is_anthropic:
                            text = await anthropic_turn(
                                session, client, model, tools, messages
                            )
                        else:
                            text = await openai_turn(
                                session, client, model, tools, messages
                            )
                    except Exception as exc:
                        print(f"\n[error] {exc}\n")
                        # Roll back all message additions from this turn so the
                        # next request starts from a clean state.
                        del messages[pre_turn - 1:]
                        continue

                    print(f"\nAssistant: {text}\n")


if __name__ == "__main__":
    asyncio.run(main())
