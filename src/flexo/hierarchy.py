"""Which group holds an entity, and which group holds a relationship.

Every phase after fitting asks the same question of the group tree: emission
nests a connector in the group that owns both its ends, routing confines the
route to that group's bounds, and lint checks the route stayed inside it. One
walk, so those three can never disagree about who owns what.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from flexo.geometry import Rect
from flexo.ir.fitted import FittedFigure
from flexo.ir.semantic import FigureSpec, GroupSpec

LAYOUT_ROLE = "layout"
"""Role of a group that arranges its children but paints no boundary of its own."""


def parent_map(groups: Iterable[GroupSpec]) -> dict[str, str]:
    """Every child id mapped to the id of the group holding it."""

    return {child_id: group.id for group in groups for child_id in group.children}


def ancestors(parents: Mapping[str, str], entity_id: str) -> tuple[str, ...]:
    """The groups enclosing ``entity_id``, innermost first."""

    result: list[str] = []
    current = entity_id
    while current in parents:
        current = parents[current]
        result.append(current)
    return tuple(result)


def lowest_common_group(parents: Mapping[str, str], entity_ids: Sequence[str]) -> str:
    """The innermost group enclosing every one of ``entity_ids``."""

    chain = ancestors(parents, entity_ids[0])
    common = set(chain)
    for entity_id in entity_ids[1:]:
        common.intersection_update(ancestors(parents, entity_id))
    return next(group_id for group_id in chain if group_id in common)


def bounded_owner(
    figure: FigureSpec,
    parents: Mapping[str, str],
    entity_ids: Sequence[str],
) -> str:
    """The innermost group enclosing ``entity_ids`` that paints a boundary.

    A layout group is furniture: confining a route to one would confine it to a
    rectangle no reader can see, so the search climbs past them to the container
    the figure actually draws.
    """

    groups = {group.id: group for group in figure.groups}
    owner = lowest_common_group(parents, entity_ids)
    while groups[owner].role == LAYOUT_ROLE and owner in parents:
        owner = parents[owner]
    return owner


def routing_boundary(
    fitted: FittedFigure,
    entity_ids: Sequence[str],
    clearance: float,
) -> Rect:
    """The rectangle a route between ``entity_ids`` must stay inside."""

    figure = fitted.measured.semantic
    owner = bounded_owner(figure, parent_map(figure.groups), entity_ids)
    return fitted.group(owner).bounds.inflated(-clearance)
