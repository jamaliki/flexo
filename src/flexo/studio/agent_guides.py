"""What an agent is taught, a little at a time: a short brief first, then a topic as it needs it.

A kind gives an agent its ``brief()`` -- about ninety lines: the loop, the habits, the shape of
a document, the topics there are -- the first time the agent opens one of its documents, and
its ``topics()`` on asking (the ``guide`` tool). A topic is cut from the kind's whole guide
(``guide()``, the one text that says how its documents are written: ``sliced``), so the two
never disagree, and carries small examples -- snippets of YAML that a test puts together into
one document and draws, so an example that no longer draws fails the tests, not an agent.

The briefs name tools and their arguments as ``{tool:look}`` and ``{arg:look.sheet}``:
``written`` puts in the names, and refuses one the studio has no tool or argument by.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MORE = "more"
"""The topic that holds whatever of a guide no other topic's anchors reach."""


@dataclass(frozen=True, slots=True)
class Snippet:
    """A small example of one thing a document can say, as YAML: for a deck, slides (a list),
    slides with the figures they share (``slides:`` and ``figures:``), or a whole deck (with
    its ``deck:``); for a figure, a whole figure file. ``files``: what it names beside the
    document, by name, for a test to put there (``b"png"`` stands for a small picture)."""

    name: str
    yaml: str
    files: dict[str, str | bytes] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Topic:
    """One topic of a kind's guide: what it is about, in a line, and its text and examples."""

    name: str
    about: str
    text: str
    snippets: tuple[Snippet, ...] = ()


def sliced(text: str, anchors: dict[str, list[str]], first: str) -> dict[str, str]:
    """``text`` cut into topics: each of a topic's ``anchors`` (patterns, a space in one any
    whitespace) starts a piece of it where it is first found, running to the next anchor of
    any topic; what comes before the first anchor is ``first``'s. What no anchor is found for
    is never lost: a piece runs on over it. Pieces of one topic are joined in their order."""

    starts: list[tuple[int, str]] = [(0, first)]
    for topic, patterns in anchors.items():
        for pattern in patterns:
            # (A space in a pattern is any run of spaces and line breaks: the guide's lines may
            # be wrapped anew.)
            found = re.search(pattern.replace(" ", r"\s+"), text, re.M)
            if found is not None and found.start() > 0:
                starts.append((found.start(), topic))
    starts.sort()
    pieces: dict[str, list[str]] = {}
    for (start, topic), (end, _) in zip(starts, [*starts[1:], (len(text), "")], strict=True):
        piece = text[start:end].strip()
        if piece:
            pieces.setdefault(topic, []).append(piece)
    return {topic: "\n\n".join(parts) for topic, parts in pieces.items()}


def topics_from(
    text: str,
    about: dict[str, str],
    anchors: dict[str, list[str]],
    snippets: dict[str, list[Snippet]],
    *,
    first: str,
) -> dict[str, Topic]:
    """A kind's topics: its guide ``text`` cut by ``anchors`` (``sliced``), each said in a line
    (``about``) with its examples -- in ``about``'s order, with whatever the anchors left over
    last (``MORE``)."""

    pieces = sliced(text, anchors, first)
    topics = {
        name: Topic(name, line, pieces.get(name, ""), tuple(snippets.get(name, ())))
        for name, line in about.items()
        if pieces.get(name) or snippets.get(name)
    }
    rest = "\n\n".join(piece for name, piece in pieces.items() if name not in about)
    if rest:
        topics[MORE] = Topic(MORE, "Everything else the guide says", rest)
    return topics


def tool_names() -> dict[str, set[str]]:
    """The studio's tools by name, each with the names of its arguments: the live list."""

    from flexo.studio.agent import TOOLS

    return {
        tool["name"]: set((tool.get("input_schema") or {}).get("properties") or {})
        for tool in TOOLS
    }


def written(template: str) -> str:
    """A brief with the tools and arguments it names put in: ``{tool:outline}`` is
    ``outline``, ``{arg:look.sheet}`` is ``sheet``. One that is not a tool or argument the
    studio has is refused (``ValueError``): a brief never teaches a tool that is not there."""

    tools = tool_names()

    def put(match: re.Match[str]) -> str:
        sort, name = match.group(1), match.group(2)
        if sort == "tool":
            if name not in tools:
                raise ValueError(f"the brief names a tool there is none of: {name}")
            return name
        tool, _, argument = name.partition(".")
        if argument not in tools.get(tool, set()):
            raise ValueError(f"the brief names an argument there is none of: {name}")
        return argument

    return re.sub(r"\{(tool|arg):([a-z_.]+)\}", put, template)


def topic_list(topics: dict[str, Topic]) -> str:
    """The topics, a line each: for a brief's end, and for ``guide`` with none named."""

    return "\n".join(f"  {name}: {topic.about}" for name, topic in topics.items())


def topic_text(kind: Any, name: str) -> str:
    """A topic of ``kind``'s guide as an agent reads it: its text, then its examples. The
    topic ``reference`` is the whole guide."""

    if name == "reference":
        return kind.guide()
    topics = kind.topics()
    topic = topics.get(name)
    if topic is None:
        raise ValueError(
            f"{kind.title} has no topic {name!r}; it has: {', '.join([*topics, 'reference'])}"
        )
    parts = [f"{kind.title}: {topic.name} -- {topic.about}.", topic.text]
    if topic.snippets:
        parts.append(
            "Examples (each draws as it is):\n\n"
            + "\n\n".join(
                f"# {snippet.name}\n{snippet.yaml.rstrip()}" for snippet in topic.snippets
            )
        )
    return "\n\n".join(part for part in parts if part)


FIRST = ("deck", "figure")
"""The kinds whose topics come first: a topic both have (shapes) is the first's, unless asked."""


def kinds_with_topics(kinds: dict[str, Any]) -> dict[str, Any]:
    """The kinds that have topics to give, by name: decks first, then figures, then the rest."""

    having = [name for name, kind in kinds.items() if callable(getattr(kind, "topics", None))]
    having.sort(key=lambda name: FIRST.index(name) if name in FIRST else len(FIRST))
    return {name: kinds[name] for name in having}


def answer(kinds: dict[str, Any], topic: str | None, kind: str | None, briefed: Any = ()) -> str:
    """The ``guide`` tool's answer: a topic of a kind's guide, or, with none named, every
    kind's topics. A topic two kinds have, its kind not named, is the one the agent has been
    briefed on (``briefed``: their names) -- a deck's, where it has been briefed on both."""

    having = kinds_with_topics(kinds)
    if kind is None and briefed:
        # (The kinds it knows, first: a figure's shapes to an agent at work on figures.)
        having = {
            **{name: each for name, each in having.items() if name in briefed},
            **{name: each for name, each in having.items() if name not in briefed},
        }
    if kind is not None and kind not in kinds:
        raise ValueError(f"There is no kind of document {kind!r}: {', '.join(kinds)}.")
    if not topic:
        chosen = (
            {kind: kinds[kind]}
            if kind
            else {**having, **{n: k for n, k in kinds.items() if n not in having}}
        )
        parts = []
        for name, each in chosen.items():
            topics = each.topics() if name in having else {}
            listed = topic_list(topics) + "\n" if topics else ""
            parts.append(
                f"{each.title} topics (guide(topic), kind: {name}):\n{listed}"
                "  reference: the whole guide"
            )
        return "\n\n".join(parts)
    if kind is None:
        # The kind whose topic it is: a deck's first, where both have one (shapes).
        kind = next((name for name, each in having.items() if topic in each.topics()), None)
        if kind is None:
            if topic == "reference":
                raise ValueError("Say which kind's reference: kind deck, figure or theme.")
            known = sorted({name for each in having.values() for name in each.topics()})
            raise ValueError(f"There is no topic {topic!r}. The topics: {', '.join(known)}.")
    chosen_kind = kinds[kind]
    if topic != "reference" and kind not in having:
        raise ValueError(f"{chosen_kind.title} has no topics: its whole guide is topic reference.")
    return topic_text(chosen_kind, topic)
