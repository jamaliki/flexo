"""The assistant built into the studio -- Claude, ChatGPT, or another model that answers as
OpenAI's API does (one running on this Mac in Ollama or LM Studio, say, or one reached
through OpenRouter) -- working on the open documents with the people in it, through the
same tools an outside agent uses (``flexo.studio.agent``).

Claude needs the ``anthropic`` package and credentials its SDK finds (``ANTHROPIC_API_KEY``,
or ``ant auth login``); ChatGPT the ``openai`` package and ``OPENAI_API_KEY``; another model
the ``openai`` package and the address of its server (``FLEXO_STUDIO_OTHER_URL``, with its
``..._MODEL``, ``..._KEY`` if it asks for one, and ``..._NAME`` to call it by). Both packages
come with ``pip install 'flexo[assistant]'``. One conversation belongs to the workspace, so
everyone in the studio sees it; its words stream to every page as they are written, and its
edits arrive as any other change does. Who answers can change part way through: the
conversation so far goes with it (``Assistant.choose``).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import traceback
from typing import Any

from flexo.studio.agent import INSTRUCTIONS, TOOLS, Tools
from flexo.studio.workspace import Workspace

MODEL = os.environ.get("FLEXO_STUDIO_MODEL", "claude-opus-5-5")
"""Claude's model."""
EFFORT = os.environ.get("FLEXO_STUDIO_EFFORT", "medium")
"""Interactive editing: medium keeps replies quick; ``high`` for larger jobs."""
FALLBACK_BETA = "server-side-fallback-2026-07-01"
OPENAI_FALLBACK = "gpt-5"
"""ChatGPT's model when none is set and OpenAI's list of them cannot be read."""
STEPS = 60
"""How many requests one turn may make before it stops and says so."""
MODELS_KEPT = 600.0
"""Seconds a provider's list of models is kept before it is read again."""
WHO = {"id": "assistant", "name": "Claude", "kind": "agent", "provider": "claude"}


def system_prompt(name: str) -> str:
    """What the assistant is told it is and how to work, whoever answers."""

    return (
        f"You are {name}, working in Flexo studio beside the user: an editor for slide decks "
        "(flexo-talk), scientific figures (flexo), and their themes, all written as YAML "
        "documents. You and the user edit the same documents at once; they watch your changes "
        "arrive as you make them. Make changes rather than describing them, in small steps, and "
        "look at the pages you change before saying you are done. Keep replies short: the "
        "documents are the work.\n\n" + INSTRUCTIONS
    )


SYSTEM = system_prompt("Claude")


# -- who answers --


class Provider:
    """One way of answering: its name, whether it can answer here, its models, and the
    conversation in the form its API takes."""

    id = ""
    name = ""

    def __init__(self, client: Any = None) -> None:
        self.client = client
        self.given = client is not None
        self.messages: list[dict[str, Any]] = []
        self.chosen: str | None = None
        """The model its person chose (in the panel), over the one it would take."""
        self._models: tuple[float, list[str]] | None = None

    # (Each provider says these its own way.)
    def unavailable(self) -> str | None:
        raise NotImplementedError

    def explain(self, error: Exception) -> str:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        raise NotImplementedError

    def pick(self, listed: list[str]) -> str:
        """The model it takes of those ``listed``, when none is chosen."""

        raise NotImplementedError

    def converse(self, assistant: Assistant, turn: dict[str, Any]) -> str:
        """Answer, through as many requests and tool calls as it takes: ``done``,
        ``stopped`` (its person stopped it) or ``refused``."""

        raise NotImplementedError

    def user(self, context: str, text: str) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": f"<context>\n{context}\n</context>"},
                {"type": "text", "text": text},
            ],
        }

    def said(self, words: str) -> dict[str, Any]:
        return {"role": "assistant", "content": [{"type": "text", "text": words}]}

    # -- shared --

    def forget(self) -> None:
        """Signed in afresh when next asked (a key set, or taken away)."""

        if not self.given:
            self.client = None
        self._models = None

    def models(self) -> list[str]:
        """The models it can answer with, as its API lists them (kept a while)."""

        if self._models is not None and time.monotonic() - self._models[0] < MODELS_KEPT:
            return self._models[1]
        found = self.list_models()
        self._models = (time.monotonic(), found)
        return found

    def default_model(self) -> str:
        try:
            listed = self.models()
        except Exception:
            listed = []
        return self.pick(listed)

    @property
    def model(self) -> str:
        return self.chosen or self.default_model()

    @property
    def model_known(self) -> str:
        """Its model, as far as is known without asking its API (again)."""

        if self.chosen:
            return self.chosen
        return self.pick(self._models[1]) if self._models is not None else self.env_model() or ""

    def env_model(self) -> str | None:
        return None

    def carry(self, transcript: list[dict[str, Any]]) -> None:
        """Take over a conversation another provider began: its words, as text (the other's
        tool calls are its own; their results are in the documents)."""

        self.messages = []
        for item in transcript:
            if item.get("role") == "user":
                self.messages.append(
                    self.user(_context(item.get("context") or {}), str(item.get("text", "")))
                )
            elif item.get("role") == "assistant":
                words = "".join(
                    part.get("text", "")
                    for part in item.get("parts") or []
                    if part.get("type") == "text"
                ).strip()
                if words:
                    self.messages.append(self.said(words))

    def stopped(self) -> None:
        # A turn stopped part way leaves no half-answered request in the history.
        while self.messages and self.messages[-1]["role"] == "assistant":
            self.messages.pop()


class Claude(Provider):
    """Claude, through Anthropic's Messages API."""

    id = "claude"
    name = "Claude"

    def _client(self) -> Any:
        if self.client is None:
            import anthropic

            self.client = anthropic.Anthropic()
        return self.client

    def unavailable(self) -> str | None:
        if self.given:
            return None
        try:
            import anthropic
        except ImportError:
            return "Claude needs the anthropic package: pip install 'flexo[assistant]'."
        try:
            client = anthropic.Anthropic()
        except Exception as error:
            return f"Claude could not be reached: {error}"
        if client.api_key is None and client.auth_token is None and client.credentials is None:
            # An app opened from the Finder has no shell's environment to find a key in.
            # The app that holds the studio may say where a key is set in it.
            return os.environ.get("FLEXO_STUDIO_KEY_HINT") or (
                "Claude needs an API key: set ANTHROPIC_API_KEY, or run `ant auth login`, "
                "then open the studio again."
            )
        return None

    def env_model(self) -> str | None:
        return MODEL

    def default_model(self) -> str:
        return MODEL

    def pick(self, listed: list[str]) -> str:
        return MODEL

    def list_models(self) -> list[str]:
        return [model.id for model in self._client().models.list()]

    def converse(self, assistant: Assistant, turn: dict[str, Any]) -> str:
        client = self._client()
        tools = [{**tool, "eager_input_streaming": True} for tool in TOOLS]
        for _ in range(STEPS):
            if assistant.stopping.is_set():
                return "stopped"
            writer = _Writer(assistant, turn)
            with client.beta.messages.stream(
                model=self.model,
                max_tokens=64000,
                system=system_prompt(self.name),
                tools=tools,
                messages=self.messages,
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": EFFORT},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                for event in stream:
                    if assistant.stopping.is_set():
                        break
                    if event.type == "text":
                        writer.text(event.text)
                    elif event.type == "thinking":
                        writer.thinking(event.thinking)
                    elif (
                        event.type == "content_block_start"
                        and event.content_block.type == "tool_use"
                    ):
                        writer.cut()
                if assistant.stopping.is_set():
                    return "stopped"
                response = stream.get_final_message()
            if response.stop_reason == "refusal":
                return "refused"
            self.messages.append({"role": "assistant", "content": _echoable(response.content)})
            uses = [block for block in response.content if block.type == "tool_use"]
            if response.stop_reason == "pause_turn":
                continue
            if not uses:
                return "done"
            if response.stop_reason == "max_tokens":
                raise RuntimeError(
                    "A change was cut off at the output limit; ask for a smaller step."
                )
            results = []
            for use in uses:
                blocks, failed = assistant.use(turn, use.id, use.name, use.input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "content": blocks,
                        **({"is_error": True} if failed else {}),
                    }
                )
            self.messages.append({"role": "user", "content": results})
        raise RuntimeError(f"Stopped after {STEPS} steps; ask again to carry on.")

    def explain(self, error: Exception) -> str:
        try:
            import anthropic
        except ImportError:
            # Said as what to do, not as Python's words.
            return (
                "Claude isn't set up in this studio: it needs the assistant package "
                "(pip install 'flexo[assistant]'), then a restart."
            )
        if isinstance(error, anthropic.AuthenticationError):
            return os.environ.get("FLEXO_STUDIO_KEY_HINT") or (
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


class OpenAIStyle(Provider):
    """A model answering as OpenAI's Chat Completions API does: ChatGPT itself, or another
    served the same way, at its own address."""

    def __init__(
        self,
        id: str,
        name: str,
        *,
        key: str,
        url: str | None = None,
        model: str,
        hint: str,
        client: Any = None,
    ) -> None:
        super().__init__(client)
        self.id = id
        self._name = name
        self._key, self._url, self._model, self._hint = key, url, model, hint

    @property
    def name(self) -> str:  # type: ignore[override]
        if self.id == "other":
            return os.environ.get("FLEXO_STUDIO_OTHER_NAME") or self._name
        return self._name

    def _settings(self) -> tuple[str | None, str | None]:
        key = os.environ.get(self._key) or None
        url = os.environ.get(self._url) or None if self._url else None
        return key, url

    def _client(self) -> Any:
        if self.client is None:
            import openai

            key, url = self._settings()
            # (A server on this Mac asks for no key; the SDK wants one all the same.)
            self.client = openai.OpenAI(api_key=key or "none", base_url=url)
        return self.client

    def unavailable(self) -> str | None:
        if self.given:
            return None
        try:
            import openai  # noqa: F401
        except ImportError:
            return f"{self.name} needs the openai package: pip install 'flexo[assistant]'."
        key, url = self._settings()
        if self.id == "other" and not url:
            return os.environ.get(self._hint) or (
                "Set FLEXO_STUDIO_OTHER_URL to the address of a server that answers as "
                "OpenAI's API does (Ollama's is http://localhost:11434/v1), and "
                "FLEXO_STUDIO_OTHER_MODEL to the model it serves."
            )
        if self.id != "other" and not key:
            return os.environ.get(self._hint) or (
                f"{self.name} needs an API key: set {self._key}, then open the studio again."
            )
        return None

    def env_model(self) -> str | None:
        return os.environ.get(self._model) or None

    def list_models(self) -> list[str]:
        found = [model.id for model in self._client().models.list()]
        if self.id == "chatgpt":
            found = [name for name in found if _chatty(name)]
        return sorted(found)

    def default_model(self) -> str:
        # The model set for it is taken without reading its list.
        return self.env_model() or super().default_model()

    def pick(self, listed: list[str]) -> str:
        wanted = self.env_model()
        if wanted:
            return wanted
        if self.id == "chatgpt":
            return _newest_gpt(listed) or OPENAI_FALLBACK
        return listed[0] if listed else ""

    def user(self, context: str, text: str) -> dict[str, Any]:
        return {"role": "user", "content": f"<context>\n{context}\n</context>\n\n{text}"}

    def said(self, words: str) -> dict[str, Any]:
        return {"role": "assistant", "content": words}

    def converse(self, assistant: Assistant, turn: dict[str, Any]) -> str:
        client = self._client()
        model = self.model
        if not model:
            raise RuntimeError(f"Choose a model for {self.name} at the top of the panel.")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in TOOLS
        ]
        for _ in range(STEPS):
            if assistant.stopping.is_set():
                return "stopped"
            writer = _Writer(assistant, turn)
            text, refusal, finish = "", "", None
            calls: dict[int, dict[str, str]] = {}
            stream = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt(self.name)}, *self.messages],
                tools=tools,
                stream=True,
            )
            try:
                for chunk in stream:
                    if assistant.stopping.is_set():
                        break
                    for choice in chunk.choices or ():
                        delta = choice.delta
                        # (Servers that show a model's reasoning send it beside its words.)
                        thought = getattr(delta, "reasoning_content", None) or getattr(
                            delta, "reasoning", None
                        )
                        if isinstance(thought, str) and thought:
                            writer.thinking(thought)
                        if delta.content:
                            text += delta.content
                            writer.text(delta.content)
                        if delta.refusal:
                            refusal += delta.refusal
                        for call in delta.tool_calls or ():
                            slot = calls.setdefault(call.index, {"id": "", "name": "", "args": ""})
                            if call.id:
                                slot["id"] = call.id
                            if call.function is not None:
                                slot["name"] += call.function.name or ""
                                slot["args"] += call.function.arguments or ""
                            writer.cut()
                        if choice.finish_reason:
                            finish = choice.finish_reason
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            if assistant.stopping.is_set():
                return "stopped"
            if refusal or finish == "content_filter":
                return "refused"
            ordered = [calls[index] for index in sorted(calls)]
            for call in ordered:
                call["id"] = call["id"] or f"call_{secrets.token_hex(6)}"
            message: dict[str, Any] = {"role": "assistant", "content": text or None}
            if ordered:
                message["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["args"] or "{}"},
                    }
                    for call in ordered
                ]
            self.messages.append(message)
            if not ordered:
                if finish == "length":
                    raise RuntimeError(
                        "A change was cut off at the output limit; ask for a smaller step."
                    )
                return "done"
            pictures: list[dict[str, Any]] = []
            for call in ordered:
                try:
                    arguments = json.loads(call["args"] or "{}")
                except json.JSONDecodeError:
                    arguments = call["args"]
                blocks, failed = assistant.use(turn, call["id"], call["name"], arguments)
                words = "\n".join(
                    block.get("text", "") for block in blocks if block.get("type") == "text"
                ).strip()
                shown = [block for block in blocks if block.get("type") == "image"]
                if shown:
                    # A tool's answer is words alone here: its pictures follow it, for the
                    # model to see, as the user's.
                    words += f"\n({len(shown)} picture(s) of the pages follow.)"
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": ("Error: " if failed else "") + (words.strip() or "Done."),
                    }
                )
                pictures.extend(shown)
            if pictures:
                self.messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "The pages you looked at, in order:"},
                            *(
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{picture['source']['media_type']};base64,"
                                        f"{picture['source']['data']}"
                                    },
                                }
                                for picture in pictures
                            ),
                        ],
                    }
                )
        raise RuntimeError(f"Stopped after {STEPS} steps; ask again to carry on.")

    def explain(self, error: Exception) -> str:
        try:
            import openai
        except ImportError:
            return (
                f"{self.name} isn't set up in this studio: it needs the assistant package "
                "(pip install 'flexo[assistant]'), then a restart."
            )
        if isinstance(error, openai.AuthenticationError):
            return os.environ.get(self._hint) or (
                f"{self.name} could not sign in: check {self._key}, then restart the studio."
            )
        if isinstance(error, openai.RateLimitError):
            return f"{self.name} is rate-limited just now (or out of credit); try again later."
        if isinstance(error, openai.NotFoundError):
            return (
                f"{self.name} has no model “{self.model}”: choose another at the top of the panel."
            )
        if isinstance(error, openai.APIStatusError):
            return f"{self.name}'s API answered {error.status_code}: {error.message}"
        if isinstance(error, openai.APIConnectionError):
            return f"Could not reach {self.name}'s API: check the network, or its address."
        return str(error)


def providers(client: Any = None) -> dict[str, Provider]:
    """Everyone who can answer, in the order they are offered. A ``client`` given is
    Claude's (a test's stand-in)."""

    return {
        "claude": Claude(client),
        "chatgpt": OpenAIStyle(
            "chatgpt",
            "ChatGPT",
            key="OPENAI_API_KEY",
            url="OPENAI_BASE_URL",
            model="FLEXO_STUDIO_OPENAI_MODEL",
            hint="FLEXO_STUDIO_OPENAI_HINT",
        ),
        "other": OpenAIStyle(
            "other",
            "Other Model",
            key="FLEXO_STUDIO_OTHER_KEY",
            url="FLEXO_STUDIO_OTHER_URL",
            model="FLEXO_STUDIO_OTHER_MODEL",
            hint="FLEXO_STUDIO_OTHER_HINT",
        ),
    }


def unavailable(provider: str = "claude") -> str | None:
    """Why ``provider`` cannot answer here, or None when it can."""

    return providers()[provider].unavailable()


def announce(workspace: Workspace) -> None:
    """Tell the workspace's pages who can answer now (a key was set, or taken away), and
    have each sign in afresh when next asked."""

    assistant = workspace.assistant
    if assistant is None:
        assistant = Assistant(workspace)
        workspace.assistant = assistant
    for provider in assistant.providers.values():
        provider.forget()
    workspace.broadcast({"type": "assistant", "event": "availability", **assistant.availability()})


# -- the conversation --


class Assistant:
    """One conversation, shared by everyone in the workspace, answered by one provider at a
    time."""

    def __init__(self, workspace: Workspace, client: Any = None) -> None:
        self.workspace = workspace
        self.providers = providers(client)
        self.provider = self.providers[_first(self.providers, given=client is not None)]
        self.tools = Tools(workspace, self.who)
        self.transcript: list[dict[str, Any]] = []
        self.queue: list[tuple[str, dict[str, Any]]] = []
        self.running = False
        self.stopping = threading.Event()
        self.lock = threading.Lock()

    @property
    def who(self) -> dict[str, Any]:
        return {**WHO, "name": self.provider.name, "provider": self.provider.id}

    @property
    def messages(self) -> list[dict[str, Any]]:
        """The conversation as the provider answering takes it."""

        return self.provider.messages

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
            for provider in self.providers.values():
                provider.messages.clear()
            self.transcript.clear()
        self._send({"event": "cleared"})

    def choose(self, provider: str, model: str | None = None) -> str | None:
        """Have ``provider`` answer from now on (in ``model``, if given: "" for its own
        choice); why not, if it cannot."""

        with self.lock:
            if self.running:
                return "Wait for the answer to finish, or stop it, first."
            chosen = self.providers.get(provider)
            if chosen is None:
                return f"No assistant called {provider!r}."
            if model is not None:
                chosen.chosen = model or None
            before = self.provider
            if chosen is not before:
                chosen.carry(self.transcript)
                self.provider = chosen
                self.tools = Tools(self.workspace, self.who)
                if self.transcript:
                    self.transcript.append(
                        {
                            "id": secrets.token_hex(5),
                            "role": "switch",
                            "name": chosen.name,
                            "at": time.time(),
                        }
                    )
        if chosen is not before:
            # The one that answered before is no longer at work here.
            self.workspace.absent({**WHO, "name": before.name, "provider": before.id})
        self._send({"event": "provider", **self.availability(), "transcript": self.transcript})
        return None

    def availability(self) -> dict[str, Any]:
        """Who answers, whether it can, and who else could."""

        why = self.provider.unavailable()
        return {
            "available": why is None,
            "why": why,
            "provider": self.provider.id,
            "name": self.provider.name,
            "model": self.provider.model_known,
            "providers": [
                {
                    "id": item.id,
                    "name": item.name,
                    "why": item.unavailable(),
                    "model": item.model_known,
                }
                for item in self.providers.values()
            ],
        }

    def models(self, provider: str) -> dict[str, Any]:
        """The models ``provider`` can answer with, and the one it uses."""

        chosen = self.providers.get(provider)
        if chosen is None:
            return {"models": [], "error": f"No assistant called {provider!r}."}
        try:
            return {"models": chosen.models(), "model": chosen.model}
        except Exception as error:
            return {"models": [], "model": chosen.model_known, "error": chosen.explain(error)}

    def state(self) -> dict[str, Any]:
        return {**self.availability(), "running": self.running, "transcript": self.transcript}

    # -- the loop --

    def _run(self) -> None:
        while True:
            with self.lock:
                if not self.queue:
                    self.running = False
                    self._send({"event": "idle"})
                    return
                text, context = self.queue.pop(0)
                provider = self.provider
            self.stopping.clear()
            mark = len(provider.messages)
            provider.messages.append(provider.user(_context(context), text))
            turn = {
                "id": secrets.token_hex(5),
                "role": "assistant",
                "name": provider.name,
                "provider": provider.id,
                "parts": [],
                "at": time.time(),
            }
            with self.lock:
                self.transcript.append(turn)
            self._send({"event": "turn", "item": turn})
            try:
                ended = provider.converse(self, turn)
            except Exception as error:
                traceback.print_exc()
                message = provider.explain(error)
                turn["parts"].append({"type": "error", "text": message})
                self._send({"event": "error", "turn": turn["id"], "text": message})
            else:
                if ended == "stopped":
                    provider.stopped()
                    turn["parts"].append({"type": "note", "text": "Stopped."})
                    self._send({"event": "stopped", "turn": turn["id"]})
                elif ended == "refused":
                    # Nothing of a refused turn is kept to be answered again.
                    del provider.messages[mark:]
                    said = f"{provider.name} declined this request."
                    turn["parts"].append({"type": "error", "text": said})
                    self._send({"event": "error", "turn": turn["id"], "text": said})
                else:
                    self._send({"event": "done", "turn": turn["id"]})
            # Done: shown as lately at work where it worked, and not at all if it did nothing.
            if any(part.get("type") == "tool" for part in turn["parts"]):
                self.workspace.set_presence(self.who, None, None, "")
            else:
                self.workspace.absent(self.who)

    def use(
        self, turn: dict[str, Any], call: str, name: str, arguments: Any
    ) -> tuple[list[dict[str, Any]], bool]:
        """Run a tool the model asked for, saying so as it runs: its result's blocks, and
        whether it failed."""

        entry = {
            "type": "tool",
            "id": call,
            "name": name,
            "label": _label(name, arguments),
            "state": "running",
        }
        turn["parts"].append(entry)
        self._send({"event": "tool", "turn": turn["id"], "part": entry})
        if not isinstance(arguments, dict):
            blocks, failed = (
                [{"type": "text", "text": json.dumps({"INVALID_JSON": str(arguments)})}],
                True,
            )
        else:
            blocks, failed = self.tools.call(name, arguments)
        entry["state"] = "failed" if failed else "done"
        if failed:
            entry["error"] = "".join(block.get("text", "") for block in blocks)[:300]
        self._send({"event": "tool", "turn": turn["id"], "part": entry})
        return blocks, failed

    def _send(self, event: dict[str, Any]) -> None:
        self.workspace.broadcast({"type": "assistant", **event})


class _Writer:
    """A reply's words and reasoning, as they stream: each run its own part of the turn,
    sent to the pages as it grows."""

    def __init__(self, assistant: Assistant, turn: dict[str, Any]) -> None:
        self.assistant, self.turn = assistant, turn
        self.part: dict[str, Any] | None = None

    def _add(self, kind: str, delta: str) -> None:
        if self.part is None or self.part["type"] != kind:
            self.part = {"type": kind, "text": ""}
            self.turn["parts"].append(self.part)
        self.part["text"] += delta
        self.assistant._send({"event": kind, "turn": self.turn["id"], "delta": delta})

    def text(self, delta: str) -> None:
        self._add("text", delta)

    def thinking(self, delta: str) -> None:
        self._add("thinking", delta)

    def cut(self) -> None:
        self.part = None


def _first(found: dict[str, Provider], *, given: bool) -> str:
    """Who answers first: the one ``FLEXO_STUDIO_PROVIDER`` names, else the first that can."""

    wanted = os.environ.get("FLEXO_STUDIO_PROVIDER", "")
    if wanted in found:
        return wanted
    if given:
        return "claude"
    return next((key for key, item in found.items() if item.unavailable() is None), "claude")


_SIDELINE = re.compile(
    r"audio|realtime|transcribe|tts|image|search|embedding|moderation|instruct|codex|"
    r"computer|deep-research|dall|whisper|babbage|davinci|preview"
)


def _chatty(name: str) -> bool:
    """Whether an OpenAI model is one to talk to and hand tools to (not speech, pictures,
    embeddings, or an older completion model)."""

    return bool(re.match(r"(gpt-|chatgpt-|o\d)", name)) and not _SIDELINE.search(name)


def _newest_gpt(names: list[str]) -> str | None:
    """The newest full GPT model among ``names``: the highest version, a full one before a
    mini or nano, the alias before a dated snapshot."""

    best: tuple[Any, ...] | None = None
    found = None
    for name in names:
        matched = re.fullmatch(r"gpt-(\d+)(?:\.(\d+))?(-.*)?", name)
        if not matched:
            continue
        rest = matched.group(3) or ""
        key = (
            int(matched.group(1)),
            int(matched.group(2) or 0),
            not re.search(r"mini|nano|chat-latest", rest),
            not re.search(r"\d{4}-\d{2}-\d{2}", rest),
            -len(rest),
        )
        if best is None or key > best:
            best, found = key, name
    return found


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
