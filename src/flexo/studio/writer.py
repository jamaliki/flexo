"""A studio's documents written by a process of their own, not between its drawings.

A deck is written over its file's words as they were (``flexo.roundtrip``): its comments and
quoting kept, read and merged by ruamel's round trip, which is Python through and through --
a hundred milliseconds and more for each writing of a deck of fifty slides, every pause in
typing. Written by the studio's own threads, that Python took turns with its drawing: a slide
typed on as the deck was written was drawn at half the speed until it was. So, once a studio
asks for it (``start``: the app's studios, ``flexo studio``'s), a kind that keeps its file's
words writes them in a process of its own (``save``): the same kind, by the same code, over
the same words, with what each writing remembers of the file (what was deleted from it, how
each of its parts reads) kept there from one writing to the next, as it was kept here. The
studio waits for it as it waited for its own writing, on a thread that draws nothing.

The parts of a file as it was opened are read there too, ahead of its first writing
(``prime``), and those of each file as it was just written, once it is: the next writing
reads them from what it remembers.

A writing the process cannot do -- it has not started, or has ended, or the kind is not one
it knows as the studio has it -- is done here, as before (``save`` answers False). The
process ends when the studio does, or when the studio has gone.

Requests and answers are pickles framed by their length, on the process's standard input
and output: ``(number, name, arguments)``, answered ``(number, True, value)`` or ``(number,
False, what went wrong)``.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import pickle
import struct
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, BinaryIO

COMMAND: list[str] | None = None
"""How to start the process: this Python by default; an app bundled with its own sets it."""
STARTUP = 60.0
"""Seconds a writing waits for the process to start (Python, flexo and the kinds read in)
before it is done here instead."""
ANSWER = 30.0
"""Seconds a writing waits for its answer: the process is ended after that, and the writing
done here."""
READY = "ready"
NICE = 10
"""How far behind the studio the process is for the computer's time (``os.nice``)."""

_FRAME = struct.Struct(">I")
_LOCK = threading.Lock()
_PROCESS: _Process | None = None
_WANTED = False
_FAILED = 0
FAILURES = 3
"""Starts that never came to be ready, after which writings are done here for good."""


def _send(stream: BinaryIO, message: Any) -> None:
    data = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_FRAME.pack(len(data)) + data)
    stream.flush()


def _receive(stream: BinaryIO) -> Any:
    head = _exactly(stream, _FRAME.size)
    if head is None:
        raise EOFError
    body = _exactly(stream, _FRAME.unpack(head)[0])
    if body is None:
        raise EOFError
    return pickle.loads(body)


def _exactly(stream: BinaryIO, size: int) -> bytes | None:
    chunks, left = [], size
    while left:
        chunk = stream.read(left)
        if not chunk:
            return None
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def _kind_type(kind: Any) -> str:
    return f"{type(kind).__module__}:{type(kind).__qualname__}"


class _Process:
    """The process, asked one thing at a time."""

    def __init__(self) -> None:
        command = COMMAND or [sys.executable, "-m", "flexo.studio.writer"]
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, close_fds=True
        )
        self.asking = threading.Lock()
        self.ready = threading.Event()
        self.gone = False
        self.served = False
        """Whether it ever said it was ready."""
        self.unread: str | None = None
        """A file's words to read the parts of once it is ready (``prime``)."""
        self.numbers = 0
        self.answers: dict[int, list[Any]] = {}
        threading.Thread(target=self._listen, name="studio writer", daemon=True).start()

    def _listen(self) -> None:
        stream = self.process.stdout
        try:
            if _receive(stream) != READY:
                raise EOFError
            self.served = True
            self.ready.set()
            if self.unread is not None:
                threading.Thread(
                    target=self.ask, args=("prime", {"previous": self.unread}, None), daemon=True
                ).start()
            while True:
                number, ok, value = _receive(stream)
                box = self.answers.pop(number, None)
                if box is not None:
                    box[1] = (ok, value)
                    box[0].set()
        except (EOFError, OSError, ValueError, pickle.UnpicklingError):
            pass
        self.gone = True
        self.ready.set()
        for box in list(self.answers.values()):
            box[1] = (False, "the writer has stopped")
            box[0].set()
        self.answers.clear()

    def ask(self, name: str, arguments: dict[str, Any], seconds: float | None) -> Any:
        """The answer to a request, or None for none (``seconds`` None: answered by nobody)."""

        if not self.ready.wait(STARTUP) or self.gone:
            return None
        box: list[Any] = [threading.Event(), None]
        with self.asking:
            if self.gone:
                return None
            self.numbers += 1
            number = self.numbers
            if seconds is not None:
                self.answers[number] = box
            try:
                _send(self.process.stdin, (number, name, arguments))
            except (OSError, ValueError):
                self.answers.pop(number, None)
                self.stop()
                return None
        if seconds is None:
            return None
        if not box[0].wait(seconds):
            self.stop()
            return None
        return box[1]

    def stop(self) -> None:
        self.gone = True
        with contextlib.suppress(OSError, ValueError):
            self.process.stdin.close()
        with contextlib.suppress(Exception):
            self.process.wait(2)
        if self.process.poll() is None:
            with contextlib.suppress(OSError):
                self.process.kill()


def start() -> None:
    """Have this studio's documents written by the process, started now (it reads in flexo
    and the kinds while the studio draws its first pages)."""

    global _WANTED
    _WANTED = True
    _process()


def _process() -> _Process | None:
    global _PROCESS, _FAILED
    if not _WANTED:
        return None
    with _LOCK:
        if _PROCESS is not None and _PROCESS.gone:
            if not _PROCESS.served:
                _FAILED += 1
            _PROCESS = None
        if _PROCESS is None and _FAILED < FAILURES:
            try:
                _PROCESS = _Process()
            except OSError:
                _FAILED += 1
        return _PROCESS


def stop() -> None:
    """End the process (the studio has stopped): asked again, writings are done here."""

    global _PROCESS, _WANTED
    with _LOCK:
        process, _PROCESS, _WANTED = _PROCESS, None, False
    if process is not None:
        process.stop()


atexit.register(stop)


def save(
    kind: Any, path: Path, document: Any, previous: str | None, name: str
) -> dict[str, Any] | None:
    """``document`` written to ``path`` by ``kind`` over ``previous`` -- the words of the file
    it is (``name``, as ``flexo.roundtrip.writing`` names it) -- by the process; None if it
    was not (the caller writes it here, as ever). Written, what kind of document its words
    are, as the process read them (``claim``: ``flexo.studio.workspace.claim_of``), if it could
    tell."""

    process = _process()
    if process is None:
        return None
    answer = process.ask(
        "save",
        {
            "kind": kind.name,
            "kind_type": _kind_type(kind),
            "path": str(path),
            "document": document,
            "previous": previous,
            "name": name,
        },
        ANSWER,
    )
    return answer[1] if answer and answer[0] and isinstance(answer[1], dict) else None


def prime(previous: str) -> bool:
    """Have the process read the parts of a file (its words, ``previous``) before its first
    writing, as ``flexo.roundtrip.prime`` reads them here: whether it was asked to."""

    process = _process()
    if process is None or process.gone:
        return False
    if not process.ready.is_set():
        # (Still starting: read once it is.)
        process.unread = previous
        return True
    process.ask("prime", {"previous": previous}, None)
    return True


# -- the process's side ---------------------------------------------------------------------


def _do_save(
    kind: str, kind_type: str, path: str, document: Any, previous: str | None, name: str
) -> dict[str, Any]:
    from flexo.roundtrip import writing
    from flexo.studio import kinds
    from flexo.studio.workspace import CLAIM_LIMIT, claim_of

    found = _kinds(kinds).get(kind)
    if found is None or _kind_type(found) != kind_type:
        raise LookupError(f"no kind {kind_type} here")
    with writing(name):
        found.save(Path(path), document, previous=previous)
    claim = None
    with contextlib.suppress(OSError, UnicodeDecodeError):
        text = Path(path).read_text(encoding="utf-8")
        _after.append(text)
        # (What kind of document they are, read here, as the studio would read them.)
        if len(text.encode("utf-8")) < CLAIM_LIMIT:
            with contextlib.suppress(Exception):
                claim = list(claim_of(_kinds(kinds), text, Path(name).suffix))
    return {"claim": claim, "kinds": sorted(_kinds(kinds))}


_KINDS: dict[str, Any] = {}
_after: list[str] = []
"""The words just written, whose parts are read once the answer is sent."""


def _kinds(kinds: Any) -> dict[str, Any]:
    if not _KINDS:
        _KINDS.update(kinds())
    return _KINDS


def _read_ahead(previous: str) -> None:
    from flexo.roundtrip import prime as read_parts

    with contextlib.suppress(Exception):
        while not read_parts(previous, 1.0):
            pass


def serve() -> int:
    """This process as a studio's writer: requests read from standard input, answered on
    standard output (where nothing else is written). Ends when its input closes."""

    incoming = os.fdopen(os.dup(0), "rb")
    outgoing = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    # (Behind the studio for the computer's time: a page's drawing comes first, a file's
    # writing a moment later.)
    with contextlib.suppress(OSError):
        os.nice(NICE)
    from flexo.studio import kinds

    with contextlib.suppress(Exception):
        _kinds(kinds)
        import flexo.roundtrip  # noqa: F401
    _send(outgoing, READY)
    while True:
        try:
            number, name, arguments = _receive(incoming)
        except (EOFError, OSError, ValueError, pickle.UnpicklingError):
            break
        if name == "prime":
            _read_ahead(arguments["previous"])
            continue
        try:
            answer = (number, True, _do_save(**arguments))
        except BaseException as error:  # (said to the studio, which writes it itself)
            answer = (number, False, f"{type(error).__name__}: {error}")
        try:
            _send(outgoing, answer)
        except (OSError, ValueError):
            break
        # (The file as just written, its parts read for the next writing over it.)
        while _after:
            _read_ahead(_after.pop())
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
