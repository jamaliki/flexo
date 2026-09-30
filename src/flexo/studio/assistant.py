"""The assistant built into the studio: Claude, working on the open documents with the
people in it, through the same tools an outside agent uses (``flexo.studio.agent``).

It needs the ``anthropic`` package (``pip install 'flexo[assistant]'``) and
credentials the SDK finds (``ANTHROPIC_API_KEY``, or ``ant auth login``). One
conversation belongs to the workspace, so everyone in the studio sees it; its
words stream to every page as they are written, and its edits arrive as any
other change does.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import traceback
from typing import Any

from flexo.studio.agent import INSTRUCTIONS, TOOLS, Tools
from flexo.studio.workspace import Workspace

MODEL = os.environ.get("FLEXO_STUDIO_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("FLEXO_STUDIO_EFFORT", "medium")
"""Interactive editing: medium keeps replies quick; ``high`` for larger jobs."""
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WHO = {"id": "assistant", "name": "Claude", "kind": "agent"}

SYSTEM = (
    "You are Claude, working in Flexo studio beside the user: an editor for slide decks "
    "(flexo-talk), scientific figures (flexo), and their themes, all written as YAML documents. "
    "You and the user edit the same documents at once; they watch your changes arrive as you "
    "make them. Make changes rather than describing them, in small steps, and look at the pages "
    "you change before saying you are done. Keep replies short: the documents are the work.\n\n"
    + INSTRUCTIONS
)


def unavailable() -> str | None:
    """Why the assistant cannot run here, or None when it can."""

    try:
        import anthropic
    except ImportError:
        return "The assistant needs the anthropic package: pip install 'flexo[assistant]'."
    try:
        client = anthropic.Anthropic()
    except Exception as error:
        return f"Claude could not be reached: {error}"
    if client.api_key is None and client.auth_token is None and client.credentials is None:
        # An app opened from the Finder has no shell's environment to find a key in.
        return (
            "Claude needs an API key: set ANTHROPIC_API_KEY, or run `ant auth login`, "
            "then open the studio again."
        )
    return None


class Assistant:
    """One conversation with Claude, shared by everyone in the workspace."""

    def __init__(self, workspace: Workspace, client: Any = None) -> None:
        self.workspace = workspace
        self.client = client
        self.tools = Tools(workspace, WHO)
        self.messages: list[dict[str, Any]] = []
        self.transcript: list[dict[str, Any]] = []
        self.queue: list[tuple[str, dict[str, Any]]] = []
        self.running = False
        self.stopping = threading.Event()
        self.lock = threading.Lock()

    def _client(self) -> Any:
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        return self.client

    # -- asking --

    def ask(self, text: str, context: dict[str, Any], who: dict[str, Any]) -> None:
        item = {
            "id": secrets.token_hex(5),
            "role": "user",
            "text": text,
            "context": context,
            "who": who,
            "at": time.time(),
        }
        with self.lock:
            self.transcript.append(item)
            self.queue.append((text, context))
            start = not self.running
            self.running = True
        self._send({"event": "user", "item": item})
        if start:
            threading.Thread(target=self._run, name="studio-assistant", daemon=True).start()

    def stop(self) -> None:
        self.stopping.set()

    def clear(self) -> None:
        with self.lock:
            if self.running:
                return
            self.messages.clear()
            self.transcript.clear()
        self._send({"event": "cleared"})

    def state(self) -> dict[str, Any]:
        return {
            "available": unavailable() is None,
            "why": unavailable(),
            "running": self.running,
            "transcript": self.transcript,
            "model": MODEL,
        }

    # -- the loop --

    def _run(self) -> None:
        while True:
            with self.lock:
                if not self.queue:
                    self.running = False
                    self._send({"event": "idle"})
                    return
                text, context = self.queue.pop(0)
            self.stopping.clear()
            self.messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"<context>\n{_context(context)}\n</context>"},
                        {"type": "text", "text": text},
                    ],
                }
            )
            turn = {"id": secrets.token_hex(5), "role": "assistant", "parts": [], "at": time.time()}
            with self.lock:
                self.transcript.append(turn)
            self._send({"event": "turn", "item": turn})
            try:
                self._converse(turn)
            except Exception as error:
                traceback.print_exc()
                message = _explain(error)
                turn["parts"].append({"type": "error", "text": message})
                self._send({"event": "error", "turn": turn["id"], "text": message})
            self.workspace.set_presence(WHO, None, None, "")

    def _converse(self, turn: dict[str, Any]) -> None:
        client = self._client()
        tools = [{**tool, "eager_input_streaming": True} for tool in TOOLS]
        for _ in range(60):
            if self.stopping.is_set():
                self._stopped(turn)
                return
            part: dict[str, Any] | None = None
            with client.beta.messages.stream(
                model=MODEL,
                max_tokens=64000,
                system=SYSTEM,
                tools=tools,
                messages=self.messages,
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": EFFORT},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                for event in stream:
                    if self.stopping.is_set():
                        break
                    if event.type == "text":
                        if part is None or part["type"] != "text":
                            part = {"type": "text", "text": ""}
                            turn["parts"].append(part)
                        part["text"] += event.text
                        self._send({"event": "text", "turn": turn["id"], "delta": event.text})
                    elif event.type == "thinking":
                        if part is None or part["type"] != "thinking":
                            part = {"type": "thinking", "text": ""}
                            turn["parts"].append(part)
                        part["text"] += event.thinking
                        self._send(
                            {"event": "thinking", "turn": turn["id"], "delta": event.thinking}
                        )
                    elif (
                        event.type == "content_block_start"
                        and event.content_block.type == "tool_use"
                    ):
                        part = None
                if self.stopping.is_set():
                    self._stopped(turn)
                    return
                response = stream.get_final_message()
            if response.stop_reason == "refusal":
                turn["parts"].append({"type": "error", "text": "Claude declined this request."})
                self._send(
                    {"event": "error", "turn": turn["id"], "text": "Claude declined this request."}
                )
                self.messages.pop()
                return
            content = _echoable(response.content)
            self.messages.append({"role": "assistant", "content": content})
            uses = [block for block in response.content if block.type == "tool_use"]
            if response.stop_reason == "pause_turn":
                continue
            if not uses:
                self._send({"event": "done", "turn": turn["id"]})
                return
            if response.stop_reason == "max_tokens":
                raise RuntimeError(
                    "A change was cut off at the output limit; ask for a smaller step."
                )
            results = []
            for use in uses:
                label = _label(use.name, use.input)
                entry = {
                    "type": "tool",
                    "id": use.id,
                    "name": use.name,
                    "label": label,
                    "state": "running",
                }
                turn["parts"].append(entry)
                self._send({"event": "tool", "turn": turn["id"], "part": entry})
                if not isinstance(use.input, dict):
                    blocks, failed = (
                        [{"type": "text", "text": json.dumps({"INVALID_JSON": str(use.input)})}],
                        True,
                    )
                else:
                    blocks, failed = self.tools.call(use.name, use.input)
                entry["state"] = "failed" if failed else "done"
                if failed:
                    entry["error"] = "".join(block.get("text", "") for block in blocks)[:300]
                self._send({"event": "tool", "turn": turn["id"], "part": entry})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "content": blocks,
                        **({"is_error": True} if failed else {}),
                    }
                )
            self.messages.append({"role": "user", "content": results})
            part = None
        raise RuntimeError("Stopped after 60 steps; ask again to carry on.")

    def _stopped(self, turn: dict[str, Any]) -> None:
        # A turn stopped part way leaves no half-answered tool call in the history.
        while self.messages and self.messages[-1]["role"] == "assistant":
            self.messages.pop()
        turn["parts"].append({"type": "note", "text": "Stopped."})
        self._send({"event": "stopped", "turn": turn["id"]})

    def _send(self, event: dict[str, Any]) -> None:
        self.workspace.broadcast({"type": "assistant", **event})


def _echoable(content: list[Any]) -> list[dict[str, Any]]:
    """A response's blocks as the next request takes them back: after a model
    fallback, what the declining model left before the switch is not echoed."""

    blocks = [block.model_dump(mode="json", exclude_none=True) for block in content]
    switches = [index for index, block in enumerate(blocks) if block.get("type") == "fallback"]
    if not switches:
        return blocks
    last = switches[-1]
    internal = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    kept = [
        block
        for block in blocks[:last]
        if block.get("type") not in internal and block.get("type") != "fallback"
    ]
    return kept + blocks[last + 1 :]


def _context(context: dict[str, Any]) -> str:
    lines = []
    if context.get("file"):
        lines.append(f"The user is looking at {context['file']}.")
    if context.get("where"):
        where = context["where"]
        label = where.get("label") if isinstance(where, dict) else str(where)
        page = where.get("page") if isinstance(where, dict) else None
        lines.append(f"Selected: {label or ''}{f' (page {page})' if page else ''}.")
    if context.get("open"):
        lines.append("Open documents: " + ", ".join(context["open"]) + ".")
    return "\n".join(lines) or "The user has no document open."


def _label(name: str, arguments: Any) -> str:
    arguments = arguments if isinstance(arguments, dict) else {}
    file = arguments.get("file", "")
    return {
        "list_documents": "Looked around the folder",
        "open_document": f"Opened {file}",
        "read_document": f"Read {file}",
        "edit_document": f"Edited {file}",
        "write_document": f"Rewrote {file}",
        "look": f"Looked at {file}"
        + (f" · page {', '.join(map(str, arguments['pages']))}" if arguments.get("pages") else ""),
        "status": str(arguments.get("doing", "")),
    }.get(name, name)


def _explain(error: Exception) -> str:
    try:
        import anthropic
    except ImportError:
        return str(error)
    if isinstance(error, anthropic.AuthenticationError):
        return (
            "Claude could not sign in: set ANTHROPIC_API_KEY, or run `ant auth login`, "
            "then restart the studio."
        )
    if isinstance(error, anthropic.RateLimitError):
        return "Claude is rate-limited just now; try again in a moment."
    if isinstance(error, anthropic.APIStatusError):
        return f"Claude's API answered {error.status_code}: {error.message}"
    if isinstance(error, anthropic.APIConnectionError):
        return "Could not reach Claude's API: check the network."
    return str(error)
