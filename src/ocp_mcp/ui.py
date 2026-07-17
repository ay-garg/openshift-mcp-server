"""Gradio web UI — Tool Playground + AI Chat."""
from __future__ import annotations

import inspect
import json
import os
import threading
from typing import Any

try:
    import gradio as gr
except ImportError:
    raise SystemExit(
        "gradio is not installed. Run: pip install 'ocp-mcp-server[ui]'"
    ) from None

# Gradio 6+ removed the `type=` constructor argument from Chatbot;
# messages format is now the default. Older versions need it explicitly.
_GRADIO_MAJOR = int(gr.__version__.split(".")[0])

import ocp_mcp.tools.acm            as _m_acm           # noqa: F401
import ocp_mcp.tools.autoscaling    as _m_autoscaling   # noqa: F401
import ocp_mcp.tools.builds         as _m_builds        # noqa: F401
import ocp_mcp.tools.cluster        as _m_cluster       # noqa: F401
import ocp_mcp.tools.config         as _m_config        # noqa: F401
import ocp_mcp.tools.generic        as _m_generic       # noqa: F401
import ocp_mcp.tools.gitops         as _m_gitops        # noqa: F401
import ocp_mcp.tools.konflux        as _m_konflux       # noqa: F401
import ocp_mcp.tools.machines       as _m_machines      # noqa: F401
import ocp_mcp.tools.monitoring     as _m_monitoring    # noqa: F401
import ocp_mcp.tools.networking     as _m_networking    # noqa: F401
import ocp_mcp.tools.ocp_ai         as _m_ocp_ai        # noqa: F401
import ocp_mcp.tools.operators      as _m_operators     # noqa: F401
import ocp_mcp.tools.pipelines      as _m_pipelines     # noqa: F401
import ocp_mcp.tools.rbac           as _m_rbac          # noqa: F401
import ocp_mcp.tools.security       as _m_security      # noqa: F401
import ocp_mcp.tools.service_mesh   as _m_service_mesh  # noqa: F401
import ocp_mcp.tools.storage        as _m_storage       # noqa: F401
import ocp_mcp.tools.virtualization as _m_virtualization # noqa: F401
import ocp_mcp.tools.workloads      as _m_workloads     # noqa: F401

from ocp_mcp.app import _parse_port
from ocp_mcp.client import format_error, list_clusters

# Single source of truth for the default model — referenced in _chat_respond
# and in the UI header markdown so both stay in sync.
_DEFAULT_MODEL = "claude-sonnet-5"

# Derived from the _m_* module imports above — a new tool module only needs to
# be added in one place (the import line); no separate list to keep in sync.
_TOOL_MODULES = sorted(
    [m for n, m in vars().items() if n.startswith("_m_")],
    key=lambda m: m.__name__,
)

_MAX_PARAMS = 15
_MAX_TOOL_ROUNDS = 10

_CHAT_EXAMPLES = [
    "What is the status of my cluster?",
    "List all pods in the default namespace",
    "Show me any currently firing alerts",
    "What nodes are available and their current status?",
    "Are there any degraded cluster operators?",
]


# ─── Tool discovery ────────────────────────────────────────────────────────────

def _discover_tools() -> dict[str, dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for mod in _TOOL_MODULES:
        mod_name = mod.__name__
        domain = mod_name.rsplit(".", 1)[-1]
        for fn_name, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ != mod_name or fn_name.startswith("_"):
                continue
            sig = inspect.signature(fn)
            doc = inspect.getdoc(fn) or ""
            params: dict[str, dict[str, Any]] = {}
            for pname, param in sig.parameters.items():
                ann = param.annotation
                if ann is inspect.Parameter.empty:
                    ann = str
                params[pname] = {
                    "annotation": ann,
                    "default": None if param.default is inspect.Parameter.empty else param.default,
                    "required": param.default is inspect.Parameter.empty,
                }
            tools[fn_name] = {
                "func": fn,
                "params": params,
                "description": doc.split("\n")[0],
                "domain": domain,
            }
    return dict(sorted(tools.items()))


_TOOLS = _discover_tools()
_TOOL_CHOICES = list(_TOOLS.keys())


# ─── Anthropic tool schema ─────────────────────────────────────────────────────

def _build_anthropic_tools() -> list[dict[str, Any]]:
    result = []
    for name, info in _TOOLS.items():
        properties: dict[str, Any] = {}
        required: list[str] = []
        for pname, pinfo in info["params"].items():
            ann = pinfo["annotation"]
            if ann is int:
                ptype = "integer"
            elif ann is bool:
                ptype = "boolean"
            elif ann is float:
                ptype = "number"
            else:
                ptype = "string"
            properties[pname] = {"type": ptype}
            if pinfo["required"]:
                required.append(pname)
        result.append({
            "name": name,
            "description": info["description"] or name,
            "input_schema": {"type": "object", "properties": properties, "required": required},
        })
    # Marks the tools block for Anthropic prompt caching — eliminates re-billing
    # all 216 schemas on every round-trip within a multi-step agentic loop
    if result:
        result[-1]["cache_control"] = {"type": "ephemeral"}
    return result


_ANTHROPIC_TOOLS = _build_anthropic_tools()

_anthropic_client: Any = None
# Stores the last constructor failure reason so _chat_respond can surface the
# real error instead of the generic "install dependencies" message
_anthropic_client_error: str = ""
_anthropic_client_lock = threading.Lock()
# Set to True after the first init attempt (success, no-key, or constructor error)
# so subsequent calls skip the lock entirely rather than re-running the full body
# every time — prevents all concurrent Gradio workers from serializing through the
# lock on every chat send when ANTHROPIC_API_KEY is absent.
_anthropic_client_init_done: bool = False


def _get_anthropic_client() -> tuple[Any, str]:
    """Return (client_or_None, error_str) — both captured under the lock so the
    caller never observes a stale error string from a prior initialization attempt."""
    global _anthropic_client, _anthropic_client_error, _anthropic_client_init_done
    if _anthropic_client is not None:
        return _anthropic_client, ""
    if _anthropic_client_init_done:
        # Init was attempted but produced no client (no-key or constructor error);
        # skip the lock — the result is already cached in _anthropic_client_error.
        return None, _anthropic_client_error
    with _anthropic_client_lock:
        if not _anthropic_client_init_done:
            try:
                from anthropic import Anthropic
            except ImportError:
                _anthropic_client_init_done = True
                return None, ""  # package absent; caller shows install prompt
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if api_key:
                try:
                    _anthropic_client = Anthropic(api_key=api_key)
                    _anthropic_client_error = ""
                except Exception as exc:
                    try:
                        _anthropic_client_error = str(exc)
                    except Exception:
                        _anthropic_client_error = type(exc).__name__
            _anthropic_client_init_done = True
        return _anthropic_client, _anthropic_client_error


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _cluster_choices() -> list[str]:
    try:
        clusters = list_clusters()
        return ["(default)", *clusters] if clusters else ["(default)"]
    except Exception:
        return ["(default)"]


def _run_tool(
    tool_name: str,
    cluster_val: str,
    param_names: list[str],
    param_vals: tuple[Any, ...],
) -> str:
    if tool_name not in _TOOLS:
        return f"Unknown tool: {tool_name!r}"
    t = _TOOLS[tool_name]
    kwargs: dict[str, Any] = {}

    for i, pname in enumerate(param_names):
        pinfo = t["params"][pname]
        raw = str(param_vals[i]) if i < len(param_vals) else ""
        ann = pinfo["annotation"]
        default = pinfo["default"]
        if ann is int:
            try:
                kwargs[pname] = int(raw) if raw.strip() else (default if default is not None else 0)
            except ValueError:
                kwargs[pname] = default if default is not None else 0
        elif ann is bool:
            if raw.strip():
                kwargs[pname] = raw.strip().lower() in ("true", "1", "yes", "on")
            else:
                kwargs[pname] = bool(default) if default is not None else False
        elif ann is float:
            try:
                kwargs[pname] = float(raw) if raw.strip() else (default if default is not None else 0.0)
            except ValueError:
                kwargs[pname] = default if default is not None else 0.0
        else:
            kwargs[pname] = raw if raw.strip() else (default if default is not None else "")

    if "cluster" in t["params"]:
        kwargs["cluster"] = "" if cluster_val in ("", "(default)") else cluster_val

    try:
        result = t["func"](**kwargs)
        return str(result) if result is not None else ""
    except Exception as exc:
        return _safe_format_error(exc)


def _safe_format_error(exc: Exception) -> str:
    """format_error wrapper that survives exceptions whose __str__ itself raises."""
    try:
        return format_error(exc)
    except Exception:
        pass
    try:
        return f"{type(exc).__name__}: (error details unavailable)"
    except Exception:
        return "unknown error"


def _chat_respond(
    message: str,
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """
    Run one user turn of the agentic loop.
    Returns (updated_messages, display_text).
    The full messages list (with SDK tool_use/tool_result objects) is returned
    and stored in gr.State so multi-turn context is never collapsed to HTML.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return messages, (
            "**`ANTHROPIC_API_KEY` not set.** Export it before starting the UI:\n\n"
            "```bash\nexport ANTHROPIC_API_KEY=sk-ant-...\n```"
        )

    client, init_error = _get_anthropic_client()
    if client is None:
        if init_error:
            return messages, f"**Client error:** {init_error}"
        return messages, "Install dependencies: `pip install 'ocp-mcp-server[ui]'`"

    model = os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)

    original_messages = messages
    messages = messages + [{"role": "user", "content": message}]

    tool_log: list[str] = []
    final_text = ""

    for _ in range(_MAX_TOOL_ROUNDS):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                tools=_ANTHROPIC_TOOLS,
                messages=messages,
            )
        except Exception as exc:
            try:
                error_str = f"**API error:** {exc}"
            except Exception:
                error_str = f"**API error:** {type(exc).__name__}"
            # Return original_messages (pre-user-turn) rather than any intermediate
            # state: intermediate states end either on a user-role tool_result entry
            # or on an assistant turn containing unresolved ToolUseBlock SDK objects —
            # both violate the Anthropic API's role-alternation rules and cause a
            # permanent 400 on the next send. Losing tool-call progress is preferable
            # to breaking the session.
            return original_messages, error_str

        turn_texts: list[str] = []
        tool_uses = []
        for block in response.content:
            if hasattr(block, "text"):
                turn_texts.append(block.text)
            if hasattr(block, "type") and block.type == "tool_use":
                tool_uses.append(block)

        # Model hit the token limit mid-generation with pending tool calls —
        # executing them is impossible so surface a clear warning instead of
        # silently orphaning the tool_use blocks
        if response.stop_reason == "max_tokens" and tool_uses:
            prefix = (" ".join(filter(None, turn_texts)) + "\n\n") if turn_texts else ""
            final_text = prefix + "*[Response cut off at token limit — tool calls could not be completed.]*"
            break

        if response.stop_reason != "tool_use" or not tool_uses:
            final_text = "\n".join(filter(None, turn_texts))
            break

        if turn_texts:
            combined = " ".join(filter(None, turn_texts))
            tool_log.append(f"\n*{combined}*")

        tool_results = []
        for tu in tool_uses:
            tool_input = dict(tu.input)
            try:
                input_repr = json.dumps(tool_input, separators=(",", ":"))
            except (TypeError, ValueError):
                try:
                    input_repr = repr(tool_input)
                except Exception:
                    # Last resort: log parameter names rather than the useless type string
                    input_repr = str(list(tool_input.keys()))[:80]
            tool_log.append(f"\n**`{tu.name}`** `{input_repr}`")
            if tu.name in _TOOLS:
                try:
                    raw_result = _TOOLS[tu.name]["func"](**tool_input)
                    result = str(raw_result) if raw_result is not None else ""
                except Exception as exc:
                    result = _safe_format_error(exc)
            else:
                result = f"Unknown tool: {tu.name}"
            if len(result) > 8000:
                result = result[:8000] + "\n…(truncated)"
            tool_log.append(f"\n```\n{result}\n```")
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})

        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": tool_results},
        ]

    else:
        final_text = "*[Tool call limit reached — response may be incomplete.]*"

    # Always append an assistant turn to maintain role alternation — omitting it
    # when final_text=="" leaves messages ending on a user-role entry and causes a
    # permanent Anthropic 400 on the next send.
    # stored_content must be a neutral phrase (not a markdown UI artifact) so
    # Claude's next turn doesn't see boilerplate as its own prior utterance.
    # This applies both when final_text is empty AND when the tool-call limit fired
    # (whose sentinel string is a UI-facing display label, not a real response).
    display_text = final_text if final_text else "*(Model returned no text response.)*"
    if not final_text:
        stored_content = "(no response)"
    elif final_text.startswith("*[Tool call limit"):
        stored_content = "(tool call limit reached)"
    else:
        stored_content = final_text
    messages = messages + [{"role": "assistant", "content": stored_content}]

    if tool_log:
        log_body = "\n".join(tool_log)
        display = (
            f"{display_text}\n\n"
            f"<details>\n<summary>Tool calls</summary>\n\n{log_body}\n\n</details>"
        )
    else:
        display = display_text

    return messages, display


# ─── Gradio app ────────────────────────────────────────────────────────────────

def build_ui() -> gr.Blocks:
    with gr.Blocks(title="OCP MCP Server — Web UI") as demo:
        param_names_state = gr.State([])
        chat_messages_state = gr.State([])

        gr.Markdown(
            "# OCP MCP Server\n"
            f"OpenShift 4 cluster operations via **{len(_TOOLS)} tools** — "
            "direct invocation or AI-assisted."
        )

        with gr.Tabs():
            # ── Tool Playground ────────────────────────────────────────────────
            with gr.TabItem("🛠  Tool Playground"):
                gr.Markdown(
                    "Pick a tool, fill in its parameters, and run it directly — no LLM required."
                )
                with gr.Row():
                    with gr.Column(scale=1, min_width=280):
                        tool_dd = gr.Dropdown(
                            choices=_TOOL_CHOICES,
                            label=f"Tool ({len(_TOOL_CHOICES)} available — type to filter)",
                            filterable=True,
                        )
                        tool_desc = gr.Textbox(
                            label="Description",
                            interactive=False,
                            lines=2,
                            max_lines=5,
                        )
                        with gr.Row():
                            cluster_dd = gr.Dropdown(
                                choices=_cluster_choices(),
                                value="(default)",
                                label="Cluster",
                                allow_custom_value=True,
                                scale=4,
                            )
                            refresh_btn = gr.Button("↻", size="sm", scale=1, min_width=40)
                        run_btn = gr.Button("Run Tool ▶", variant="primary")

                    with gr.Column(scale=2):
                        param_rows: list[gr.Textbox] = []
                        for i in range(_MAX_PARAMS):
                            param_rows.append(
                                gr.Textbox(label=f"param_{i}", visible=False, interactive=True)
                            )
                        output = gr.Code(
                            label="Output", language=None, lines=20, interactive=False
                        )

            # ── AI Chat ────────────────────────────────────────────────────────
            with gr.TabItem("💬  AI Chat"):
                gr.Markdown(
                    "Chat in natural language. Claude will call OCP tools automatically.\n\n"
                    f"> Requires `ANTHROPIC_API_KEY` · Model: "
                    f"`{os.getenv('ANTHROPIC_MODEL', _DEFAULT_MODEL)}`"
                )
                chatbot = gr.Chatbot(
                    height=450,
                    show_label=False,
                    **({} if _GRADIO_MAJOR >= 6 else {"type": "messages"}),
                )
                with gr.Row():
                    chat_input = gr.Textbox(
                        placeholder="Ask anything about your cluster…",
                        show_label=False,
                        scale=8,
                    )
                    chat_send = gr.Button("Send ▶", variant="primary", scale=1)
                chat_clear = gr.Button("Clear Chat", size="sm")
                gr.Markdown("**Examples:**")
                # gr.Row keeps buttons compact instead of each spanning full tab width
                with gr.Row():
                    example_btns = [gr.Button(ex, size="sm") for ex in _CHAT_EXAMPLES]

        # ── Tool Playground event handlers ─────────────────────────────────────

        def on_tool_select(tool_name: str):
            if not tool_name or tool_name not in _TOOLS:
                return (
                    gr.update(value=""),
                    [],
                    *[gr.update(visible=False, value="") for _ in range(_MAX_PARAMS)],
                )
            t = _TOOLS[tool_name]
            non_cluster = [(n, p) for n, p in t["params"].items() if n != "cluster"]
            updates = []
            for i in range(_MAX_PARAMS):
                if i < len(non_cluster):
                    pname, pinfo = non_cluster[i]
                    ann = pinfo["annotation"]
                    ann_str = ann.__name__ if hasattr(ann, "__name__") else str(ann)
                    label = f"{pname}: {ann_str}" + (" *" if pinfo["required"] else "")
                    default = pinfo["default"]
                    updates.append(gr.update(
                        visible=True,
                        label=label,
                        value="" if default is None else str(default),
                        placeholder="" if default is None else f"default: {default}",
                    ))
                else:
                    updates.append(gr.update(visible=False, value=""))
            return (gr.update(value=t["description"]), [n for n, _ in non_cluster], *updates)

        tool_dd.change(
            fn=on_tool_select,
            inputs=[tool_dd],
            outputs=[tool_desc, param_names_state, *param_rows],
        )
        refresh_btn.click(
            fn=lambda: gr.update(choices=_cluster_choices()),
            outputs=[cluster_dd],
        )
        run_btn.click(
            fn=lambda tn, cv, pn, *pv: _run_tool(tn, cv, pn, pv),
            inputs=[tool_dd, cluster_dd, param_names_state, *param_rows],
            outputs=[output],
        )

        # ── AI Chat event handlers ─────────────────────────────────────────────

        def on_chat_send(message: str, messages: list, history: list):
            if not message.strip():
                yield history, messages, ""
                return
            user_turn = {"role": "user", "content": message}
            yield history + [user_turn, {"role": "assistant", "content": "…"}], messages, ""
            try:
                updated_messages, response_text = _chat_respond(message, messages)
            except Exception as exc:
                # Replace the "…" placeholder rather than leaving it frozen
                response_text = _safe_format_error(exc)
                updated_messages = messages
            yield history + [user_turn, {"role": "assistant", "content": response_text}], updated_messages, ""

        _chat_kwargs = dict(
            fn=on_chat_send,
            inputs=[chat_input, chat_messages_state, chatbot],
            outputs=[chatbot, chat_messages_state, chat_input],
        )

        cancellable_events = []
        cancellable_events.append(chat_send.click(**_chat_kwargs))
        cancellable_events.append(chat_input.submit(**_chat_kwargs))

        # Each example button passes its text directly to _chat_respond without
        # routing through chat_input — eliminates the race where rapid double-clicks
        # on different example buttons overwrite chat_input before .then() reads it
        for ex, btn in zip(_CHAT_EXAMPLES, example_btns):
            def _make_example_fn(msg: str = ex):
                def _fn(messages: list, history: list):
                    yield from on_chat_send(msg, messages, history)
                return _fn

            run_ev = btn.click(
                fn=_make_example_fn(),
                inputs=[chat_messages_state, chatbot],
                outputs=[chatbot, chat_messages_state, chat_input],
            )
            cancellable_events.append(run_ev)

        chat_clear.click(
            fn=lambda: ([], [], ""),
            outputs=[chatbot, chat_messages_state, chat_input],
            cancels=cancellable_events,
        )

    return demo


def main() -> None:
    # Validate GRADIO_PORT before building the UI — avoids wasting 2-3 s of
    # graph construction before a clean error. _parse_port warns on whitespace,
    # validates the range, and gives a clear error message including the range.
    server_port = _parse_port(os.getenv("GRADIO_PORT", "7860"), "GRADIO_PORT")

    # Accept any non-empty GRADIO_HOST value. ipaddress.ip_address() would
    # only validate IP literals — it cannot distinguish an intentional hostname
    # ('my-host.internal') from a typo ('127.0.0.l'), so a try/except that
    # passes on ValueError would be a no-op. Defer host resolution to uvicorn.
    server_name = os.getenv("GRADIO_HOST", "0.0.0.0")
    if not server_name or server_name.isspace():
        raise SystemExit("GRADIO_HOST must not be empty")

    demo = build_ui()
    demo.launch(
        server_name=server_name,
        server_port=server_port,
        share=os.getenv("GRADIO_SHARE", "").lower() == "true",
        theme=gr.themes.Soft(),
    )


if __name__ == "__main__":
    main()
