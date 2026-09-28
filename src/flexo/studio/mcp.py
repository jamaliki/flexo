"""``flexo studio mcp``: the studio's tools for an agent, over the Model Context Protocol.

Add it to an agent once -- ``claude mcp add flexo-studio -- flexo studio mcp`` -- and
the agent works in the studio open on its folder: the people there watch its
edits arrive, see what it is doing, and it can look at the pages it draws. If
no studio is open on the folder, one is started (its address is in
``list_documents``) and runs as long as the agent does.

The protocol is JSON-RPC over standard input and output, one message per line.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from flexo import __version__
from flexo.studio import sessions
from flexo.studio.agent import INSTRUCTIONS, TOOLS

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")


class Connection:
    """The studio the tools act on: found running, or started here."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        found = sessions.find(folder)
        if found is None:
            from flexo.studio.server import start

            server, workspace = start(folder, browser=False)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            found = {"port": server.server_address[1], "token": workspace.token}
            print(f"flexo studio: {workspace.address}", file=sys.stderr)
        self.base = f"http://127.0.0.1:{found['port']}"
        self.token = found["token"]

    def call(self, name: str, arguments: dict[str, Any], who: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"name": name, "input": arguments, "who": who}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}/api/agent/call",
            data=body,
            headers={"Content-Type": "application/json", "X-Studio-Token": self.token},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=600) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            return {
                "content": [{"type": "text", "text": error.read().decode("utf-8", "replace")}],
                "is_error": True,
            }
        except OSError as error:
            return {
                "content": [{"type": "text", "text": f"The studio did not answer: {error}"}],
                "is_error": True,
            }


def _content(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages API blocks as MCP content."""

    content = []
    for block in blocks:
        if block["type"] == "image":
            content.append(
                {
                    "type": "image",
                    "data": block["source"]["data"],
                    "mimeType": block["source"]["media_type"],
                }
            )
        else:
            content.append({"type": "text", "text": block["text"]})
    return content


def serve(folder: Path, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    connection: Connection | None = None
    who = {"id": "mcp:agent", "name": "Agent"}

    def send(message: dict[str, Any]) -> None:
        stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
        stdout.flush()

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "not JSON"}})
            continue
        method, ident = message.get("method"), message.get("id")
        params = message.get("params") or {}
        if ident is None:
            continue  # a notification: nothing to answer
        if method == "initialize":
            client = params.get("clientInfo") or {}
            name = str(client.get("name") or "Agent")
            who = {"id": f"mcp:{name}", "name": _pretty(name)}
            wanted = params.get("protocolVersion")
            send(
                {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "result": {
                        "protocolVersion": wanted if wanted in PROTOCOLS else PROTOCOLS[0],
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "flexo-studio", "version": __version__},
                        "instructions": INSTRUCTIONS,
                    },
                }
            )
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": ident, "result": {}})
        elif method == "tools/list":
            tools = [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": tool["input_schema"],
                }
                for tool in TOOLS
            ]
            send({"jsonrpc": "2.0", "id": ident, "result": {"tools": tools}})
        elif method == "tools/call":
            if connection is None:
                connection = Connection(folder)
            result = connection.call(str(params.get("name")), params.get("arguments") or {}, who)
            send(
                {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "result": {
                        "content": _content(result.get("content", [])),
                        "isError": bool(result.get("is_error")),
                    },
                }
            )
        else:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "error": {"code": -32601, "message": f"no method {method}"},
                }
            )


def _pretty(name: str) -> str:
    known = {
        "claude-code": "Claude Code",
        "claude-ai": "Claude",
        "cursor": "Cursor",
        "codex": "Codex",
    }
    return known.get(name.lower(), name.replace("-", " ").strip().title() or "Agent")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flexo studio mcp", description=__doc__.split("\n\n")[0])
    parser.add_argument("--folder", type=Path, default=Path.cwd(), help="the folder to work in")
    arguments = parser.parse_args(argv)
    serve(arguments.folder)
    return 0
