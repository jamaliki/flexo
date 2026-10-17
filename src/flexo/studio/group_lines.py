"""Lines to groups, as the figure editor makes and keeps them (``flexo.group_ends``).

A line may start or end at a group -- ``{from: substrates, to: cell}`` -- as at a part: the
Connect tool draws one from a group chosen, or to a group clicked, and a line's From and To
offer the figure's groups beside its parts. What the figure would refuse, the editor says
before it is made: a line between a group and what it holds (there is no way to it from
outside), or to the group that holds the whole figure. A line to a group the figure no
longer has -- deleted, or ungrouped -- goes with it, as a line to a deleted part does.
"""

from __future__ import annotations

from typing import Any

from flexo.group_ends import PLAIN_PORTS


def group_ids(document: Any) -> set[str]:
    """The ids of the groups ``document`` (a ``figure_edit._Document``) writes."""

    return {str(group.get("id")) for group in document.groups if isinstance(group, dict)}


def end_of(document: Any, reference: str) -> str | None:
    """The group a line's end names (``substrates``, or ``substrates.output`` as the figure
    writes it itself), or None: a part's end, or nothing's."""

    reference = str(reference)
    if reference in document.node_ids():
        return None
    groups = group_ids(document) | {document.root}
    if reference in groups:
        return reference
    head, _, port = reference.rpartition(".")
    return head if head in groups and port in PLAIN_PORTS else None


def named(document: Any, identifier: str) -> str:
    """A group as a person knows it: by its title, else its name in the file."""

    group = document.group(identifier) or {}
    label = group.get("label")
    if isinstance(label, list):
        label = "".join(str(run.get("text", "")) for run in label)
    return str(label or identifier)


def outside_groups(document: Any, *ends: str) -> None:
    """A line between ``ends`` (parts or groups, by id) is one that can be drawn where an end
    is a group: from outside it -- never from a part or group it holds, nor at the group
    that holds the whole figure."""

    from flexo.studio.figure_edit import EditError

    for group in ends:
        if end_of(document, group) != group:
            continue
        if group == document.root:
            raise EditError(
                "A line can\u2019t end at the figure\u2019s layout: it holds every part. "
                "Join a group inside it."
            )
        if ends.count(group) > 1:
            raise EditError(f"A line can\u2019t start and end at “{named(document, group)}”.")
        held = set(document.descendants(group))
        for other in ends:
            if other in held:
                part = document.node(other)
                said = document.said(part) if part is not None else named(document, other)
                raise EditError(
                    f"A line can\u2019t end at “{named(document, group)}” from inside it: the "
                    f"group holds “{said}”."
                )


def drop_gone(document: Any, before: set[str]) -> None:
    """The lines to groups that were in the figure (``before``) and are not now -- deleted,
    ungrouped, emptied -- taken out with them: there is nothing for them to end at."""

    gone = before - group_ids(document) - document.node_ids() - {document.root}
    if not gone:
        return

    def lost(reference: object) -> bool:
        reference = str(reference)
        head, _, port = reference.rpartition(".")
        return reference in gone or (head in gone and port in PLAIN_PORTS)

    edges = document.data.get("edges")
    if isinstance(edges, list):
        kept = [
            edge
            for edge in edges
            if not (isinstance(edge, dict) and (lost(edge.get("from")) or lost(edge.get("to"))))
        ]
        if len(kept) != len(edges):
            edges[:] = kept
    nets = document.data.get("nets")
    if isinstance(nets, list) and any(
        isinstance(net, dict)
        and any(lost(end) for side in ("sources", "targets") for end in net.get(side) or [])
        for net in nets
    ):
        from flexo.studio.figure_edit import mend

        mend(document.data, before | document.node_ids())
    for key in ("edges", "nets"):
        if key in document.data and not document.data[key]:
            del document.data[key]


__all__ = ["drop_gone", "end_of", "group_ids", "named", "outside_groups"]
