"""Drawing conventions: how a figure marks what its lines mean.

A figure's lines meet in three ways, and papers disagree on how to draw each.
``Conventions`` is the one place those choices live. A theme carries a set, a
figure may override any of them (``Figure(conventions={"merge": "dot"})``, or
``conventions:`` in YAML), and a net's own ``joint=`` overrides both for that
one net.

``branch``
    Where one value is read by several components and its line forks.
    ``"plain"`` (default) draws the fork as a bare T; ``"dot"`` puts a dot on
    every fork, the circuit-diagram convention.

``merge``
    Where several lines join before they arrive (a ``merge`` net).
    ``"auto"`` (default) ends the joining line in an arrowhead when two lines
    meet, and draws a bus of three or more as plain Ts with the one arrow into
    the destination. ``"arrow"`` puts an arrowhead on every joining line,
    ``"plain"`` on none, and ``"dot"`` marks every join with a dot.

``arrivals``
    Where several connectors end at one port of one component.
    ``"separate"`` (default) gives each its own arrow, spread along the side;
    ``"joined"`` joins them into one line before the port, as a merge would.

``lines``
    How an edge with no ``shape=`` of its own is drawn. ``"orthogonal"``
    (default) routes it with right angles round everything in its way;
    ``"straight"`` draws one segment between the two outlines, the way a
    fully connected layer or a graphical model is drawn.

``pin_spread``
    Where arrows meet a side of a box. The central ``pin_spread`` of the
    side is cut into equal shares, one per arrow, and each arrow meets the
    side at the middle of its share: one arrow at the middle of the side,
    two at 30% and 70% of it with the default ``0.8``, three at 23%, 50%
    and 77%. ``0`` puts every arrow at the middle; ``1`` shares out the
    whole side. An arrow still moves off its place to run straight to the
    box it faces.

An operation on the values that meet -- a sum, a product -- is not a
convention: author it with ``add``, ``multiply`` or ``op`` and it is drawn as a
circle with the arrows pointing into it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Literal

type BranchMark = Literal["plain", "dot"]
type MergeMark = Literal["auto", "arrow", "plain", "dot"]
type Arrivals = Literal["separate", "joined"]
type Lines = Literal["orthogonal", "straight"]

CHOICES: dict[str, tuple[str, ...]] = {
    "branch": ("plain", "dot"),
    "merge": ("auto", "arrow", "plain", "dot"),
    "arrivals": ("separate", "joined"),
    "lines": ("orthogonal", "straight"),
}


@dataclass(frozen=True, slots=True)
class Conventions:
    """How branches, merges, and shared arrivals are drawn; see the module docs."""

    branch: BranchMark = "plain"
    merge: MergeMark = "auto"
    arrivals: Arrivals = "separate"
    lines: Lines = "orthogonal"
    pin_spread: float = 0.8

    def __post_init__(self) -> None:
        for name, allowed in CHOICES.items():
            value = getattr(self, name)
            if value not in allowed:
                raise ValueError(
                    f'unknown {name} convention "{value}"; valid values: {", ".join(allowed)}'
                )
        if isinstance(self.pin_spread, bool) or not isinstance(self.pin_spread, int | float):
            raise ValueError(f"pin_spread must be a number from 0 to 1, not {self.pin_spread!r}")
        if not 0.0 <= self.pin_spread <= 1.0:
            raise ValueError(f"pin_spread must be from 0 to 1, not {self.pin_spread}")

    def with_updates(
        self, updates: Mapping[str, str | float] | Conventions | None
    ) -> Conventions:
        """These conventions with ``updates`` laid over them."""

        if updates is None:
            return self
        if isinstance(updates, Conventions):
            updates = updates.changes()
        names = [field.name for field in fields(self)]
        unknown = set(updates) - set(names)
        if unknown:
            raise ValueError(
                f"unknown convention {', '.join(sorted(unknown))}; "
                f"conventions are {', '.join(names)}"
            )
        return replace(self, **dict(updates))

    def changes(self) -> dict[str, str | float]:
        """The fields that differ from the defaults, as a plain mapping."""

        default = Conventions()
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if getattr(self, field.name) != getattr(default, field.name)
        }


DEFAULT_CONVENTIONS = Conventions()


def parse_conventions(
    value: Mapping[str, str | float] | Conventions | None,
) -> Conventions | None:
    """``value`` as ``Conventions``, validated; ``None`` stays ``None``."""

    if value is None or isinstance(value, Conventions):
        return value
    return Conventions().with_updates(value)
