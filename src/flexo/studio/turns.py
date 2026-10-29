"""An agent's turn: the edits it makes for one request, as one step its people can undo.

An agent -- Claude Code through ``flexo studio mcp``, or the assistant built into the studio --
makes several edits for one request: a slide added, its words written, a figure put on it.
Each of them is a version of the document, attributed to the agent; together they are one
change, and they are shown as one: a row of the activity named as the agent names it ("Claude:
Add a results slide"), saying what it did ("added slide 5 · edited slide 4"). Undone from that
row, the turn is taken back whole -- by the page, as its person's own change (merge.js's
``replay``, run by run, the last first), on the document as it is now: what the person or
anyone else changed since, or meanwhile, stays as they have it.

A turn is the agent's edits from the first to the last of one request:

- An edit an agent makes through the tools may be given a ``label`` (``edit_document``,
  ``write_document``, ``convert_to_figure_parts``, the comment tools): what the user asked for,
  in a few words. Edits under one label are one turn; an edit under another starts the next.
  An edit with none is the open turn's, else one of its own -- named, until a label comes, by
  what its edits did ("edited slide 4 and added slide 5"): what an agent says it is doing
  (``status``) is where it is at the moment, often reading or looking, not what it changed.
- The assistant's turn is its answer to one request (``begin`` and ``end``, ``held``): named
  by the request, or by the first label the model gives its edits.
- An edit an agent makes to the file itself, with its own tools, is attributed to it as it is
  taken in (``Workspace.agent_on``), and is its open turn's like any other.
- A turn nothing has been added to for a while (``GAP``; ``QUIET``, one with no label) is over;
  so is one its person has undone.

Each run of a turn is a run of the agent's versions with nobody else's between them: what the
document was before the run and after it, as JSON in the document's own order (a run is taken
back on the page, where a mapping it rebuilds keeps the order of what it is made from). Turns
are kept in the studio's process -- a window's own, in the Mac app -- which is where its
documents are and its pages and agents call, and where its YAML is handed to the writer's
process (``flexo.studio.writer``) as any version is: the last ``KEPT`` of them, at most
``KEPT_BYTES`` of documents between them, can be undone; an older one says so, not offered.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

GAP = 600.0
"""Seconds after its last edit an agent's labelled turn is over (one not ``held`` by its caller)."""
QUIET = 180.0
"""Seconds after its last edit an agent's turn with no label is over."""
KEPT = 30
"""Turns whose documents are kept, the latest, to be undone."""
KEPT_BYTES = 96_000_000
"""Bytes of documents kept for turns, at most: the oldest turns' are let go past it."""
NOTES = 8
"""What a turn did, said at most so many ways in its row."""


@dataclass
class Turn:
    id: str
    who: dict[str, Any]
    label: str | None
    """What the agent named it (a ``label``), or its caller (the assistant's request)."""
    held: bool
    """Begun and ended by its caller (the assistant's answer), not by labels or a pause."""
    started: float
    last: float
    named: bool = False
    """Whether the agent has named it: its caller's name is the agent's first label's to take."""
    runs: dict[str, list[list[Any]]] = field(default_factory=dict)
    """Each document's runs of the turn's versions: ``[first, last, before, after]`` -- the
    version before the run and the run's last, and the document at each, as JSON."""
    notes: list[dict[str, Any]] = field(default_factory=list)
    edits: int = 0
    undone: dict[str, Any] | None = None
    """Who undid it, and when, while it is undone."""
    kept: bool = True
    """Whether its documents are kept, so it can be undone."""
    entry: dict[str, Any] | None = None

    def name(self) -> str:
        return self.label or _summed([note["text"] for note in self.notes])

    def size(self) -> int:
        return sum(len(run[2]) + len(run[3]) for runs in self.runs.values() for run in runs)

    def over(self, now: float) -> bool:
        return not self.held and now - self.last > (GAP if self.label else QUIET)


class Turns:
    """A workspace's agents' turns: the one each agent has open, and those kept."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace
        self.lock = threading.Lock()
        self.open: dict[str, Turn] = {}
        self.kept: list[Turn] = []

    # -- begun, ended --

    def begin(self, who: dict[str, Any], label: str | None = None, *, held: bool = False) -> Turn:
        """The turn ``who``'s next edits are made in: the one open, if ``label`` is its own (or
        none is given), else a new one. ``held``: a new one, begun by its caller and ended by
        it (``end``) -- a label given within it names it, the first time, and starts no other."""

        label = _label(label)
        key = _key(who)
        now = time.time()
        renamed = None
        with self.lock:
            turn = self.open.get(key)
            if turn is not None and (
                held
                or (
                    not turn.held
                    and (
                        turn.over(now) or (label is not None and turn.named and label != turn.label)
                    )
                )
            ):
                self._close(key)
                turn = None
            if turn is None:
                turn = Turn(
                    secrets.token_hex(6),
                    dict(who),
                    label,
                    held,
                    now,
                    now,
                    named=label is not None and not held,
                )
                self.open[key] = turn
            elif label is not None and not turn.named:
                turn.label, turn.named = label, True
                renamed = turn
            turn.who = dict(who)
        if renamed is not None and renamed.entry is not None:
            self._said(renamed)
        return turn

    def end(self, who: dict[str, Any]) -> None:
        """``who``'s turn is over: its next edit starts another."""

        with self.lock:
            self._close(_key(who))

    def _close(self, key: str) -> None:
        self.open.pop(key, None)

    # -- the edits --

    def took(
        self, doc: Any, who: dict[str, Any], before: Any, after: Any, notes: list[dict[str, Any]]
    ) -> bool:
        """A change to ``doc`` (``before`` to ``after``, its version now), made by ``who``: an
        agent's is its turn's -- the one open, else one of its own -- and its row of the
        activity is that turn's. Whether it was (a person's is not)."""

        if who.get("kind") != "agent":
            return False
        key = _key(who)
        version = doc.version
        now = time.time()
        with self.lock:
            turn = self.open.get(key)
            if turn is not None and turn.over(now):
                self._close(key)
                turn = None
        if turn is None:
            turn = self.begin(who)
        # (As JSON in the document's own order -- the history's is sorted -- taken now, while
        # the version is the document's: no change made after it is in the run.)
        with self.lock:
            runs = turn.runs.setdefault(doc.name, [])
            if runs and runs[-1][1] == version - 1 and turn.kept:
                runs[-1][1], runs[-1][3] = version, _json(after)
            else:
                runs.append([version - 1, version, _json(before), _json(after)])
            turn.last = now
            turn.edits += 1
            for note in notes[:6]:
                said = {
                    "text": str(note.get("text", "")),
                    "where": note.get("where"),
                    "file": doc.name,
                }
                turn.notes = [
                    one
                    for one in turn.notes
                    if (one["text"], one["file"]) != (said["text"], doc.name)
                ]
                turn.notes.append(said)
            del turn.notes[:-NOTES]
            if turn not in self.kept:
                self.kept.append(turn)
            let_go = self._let_go()
        self._said(turn)
        for entry in let_go:
            self.workspace.broadcast({"type": "activity", "entry": entry, "followed": True})
        return True

    def _let_go(self) -> list[dict[str, Any]]:
        """The oldest turns' documents let go, past ``KEPT`` turns or ``KEPT_BYTES``: their
        rows, to be said again."""

        size, gone = 0, []
        for index, turn in enumerate(reversed(self.kept)):
            size += turn.size()
            if (
                turn.kept
                and (index >= KEPT or size > KEPT_BYTES)
                and turn not in self.open.values()
            ):
                turn.kept = False
                turn.runs = {
                    name: [[run[0], run[1], "", ""] for run in runs]
                    for name, runs in turn.runs.items()
                }
                if turn.entry is not None:
                    turn.entry["turn"]["kept"] = False
                    gone.append(turn.entry)
        del self.kept[: max(0, len(self.kept) - 4 * KEPT)]
        return gone

    # -- its row of the activity --

    def _said(self, turn: Turn) -> None:
        """The turn's row of the activity, made or said again: named by its label (else by what
        it did), what it did, and where it last did something."""

        with self.lock:
            notes = list(turn.notes)
            last = notes[-1] if notes else {"file": "", "where": None}
            entry = turn.entry
            fresh = entry is None
            if fresh:
                entry = turn.entry = {"id": turn.id}
            entry.update(
                at=turn.last,
                who=turn.who,
                file=last.get("file") or next(iter(turn.runs), ""),
                text=turn.name(),
                where=last.get("where"),
                turn={
                    "named": bool(turn.label),
                    "done": [note["text"] for note in notes],
                    "files": list(turn.runs),
                    "edits": turn.edits,
                    "kept": turn.kept,
                    "undone": turn.undone,
                },
            )
        workspace = self.workspace
        with workspace.lock:
            # (Gone on, it is the latest: kept among those a page opened now is given.)
            if not fresh and workspace.activity and workspace.activity[-1] is not entry:
                with contextlib.suppress(ValueError):
                    workspace.activity.remove(entry)
                fresh = True
            if fresh:
                workspace.activity.append(entry)
        workspace.broadcast({"type": "activity", "entry": entry})

    # -- undone --

    def runs(self, ident: str, file: str) -> bytes:
        """What the page takes the turn ``ident`` back by in ``file``: its runs there, each the
        document before it and after it, as JSON -- ``{"turn": {"label", "who"}, "runs":
        [{"before", "after"}]}``, the first first."""

        with self.lock:
            turn = self._find(ident)
            if turn is None or not turn.kept:
                raise ValueError("That change is too long ago to undo.")
            runs = [list(run) for run in turn.runs.get(file, [])]
            head = json.dumps({"label": turn.name(), "who": turn.who}, ensure_ascii=False)
        body = ",".join(f'{{"before":{run[2]},"after":{run[3]}}}' for run in runs)
        return f'{{"turn":{head},"runs":[{body}]}}'.encode()

    def undo(self, ident: str, who: dict[str, Any], undone: bool) -> dict[str, Any] | None:
        """The turn ``ident`` taken back by ``who`` (``undone``), or made again: its row says so.
        Taken back, it is over: the agent's next edit is another turn's."""

        with self.lock:
            turn = self._find(ident)
            if turn is None:
                return None
            turn.undone = {"who": who, "at": time.time()} if undone else None
            if undone and self.open.get(_key(turn.who)) is turn:
                self._close(_key(turn.who))
            entry = turn.entry
            if entry is not None:
                entry["turn"]["undone"] = turn.undone
            agent = str(turn.who.get("name") or "an agent")
            named = (
                f"{agent}\u2019s \u201c{turn.label}\u201d"
                if turn.label
                else f"{agent}\u2019s change"
            )
            files = set(turn.runs)
        if entry is not None:
            self.workspace.broadcast({"type": "activity", "entry": entry, "followed": True})
        self._reworded(who, files, f"undid {named}" if undone else f"made {named} again")
        return entry

    def _reworded(self, who: dict[str, Any], files: set[str], text: str) -> None:
        """The row the change ``who`` just made to undo a turn (or make it again) is said as
        that -- "undid Claude's change" -- not as what the change did to its slides."""

        workspace, now = self.workspace, time.time()
        with workspace.lock:
            row = next(
                (
                    entry
                    for entry in reversed(workspace.activity)
                    if entry.get("who", {}).get("id") == who.get("id")
                    and entry.get("file") in files
                    and "turn" not in entry
                    and now - entry.get("at", 0) < 10
                ),
                None,
            )
            if row is not None:
                row["text"] = text
                row.pop("count", None)
        if row is not None:
            workspace.broadcast({"type": "activity", "entry": row, "followed": True})

    def _find(self, ident: str) -> Turn | None:
        return next((turn for turn in reversed(self.kept) if turn.id == ident), None)


def of(workspace: Any) -> Turns:
    """The workspace's turns (made as they are first asked for)."""

    turns = getattr(workspace, "_turns", None)
    if turns is None:
        with workspace.lock:
            turns = getattr(workspace, "_turns", None)
            if turns is None:
                turns = Turns(workspace)
                workspace._turns = turns
    return turns


def took(
    workspace: Any, doc: Any, who: dict[str, Any], before: Any, after: Any, notes: list
) -> bool:
    """``Turns.took``, for the workspace's changes: whether an agent's turn holds this one."""

    if who.get("kind") != "agent":
        return False
    return of(workspace).took(doc, who, before, after, notes)


def _key(who: dict[str, Any]) -> str:
    return str(who.get("id") or who.get("name") or "agent")


def _label(label: Any) -> str | None:
    """A label as a row shows it: its words on one line, a sentence's capital, no full stop."""

    if not isinstance(label, str):
        return None
    words = " ".join(label.split()).strip().rstrip(".")
    if not words:
        return None
    if len(words) > 90:
        words = words[:89].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return words[0].upper() + words[1:]


def _summed(done: list[str]) -> str:
    """What a turn with no name did: its first two notes, and how many more."""

    if not done:
        return "edited"
    if len(done) <= 2:
        return " and ".join(done)
    return f"{done[0]}, {done[1]} and {len(done) - 2} more"


def _json(document: Any) -> str:
    return json.dumps(document, ensure_ascii=False, default=str, separators=(",", ":"))
