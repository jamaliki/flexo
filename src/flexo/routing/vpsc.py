"""Separation constraints in one dimension, solved by block merging (VPSC).

Minimise ``sum(w_i * (x_i - d_i)**2)`` subject to ``x_l + gap <= x_r`` for a set
of constraints that form a DAG. This is the "satisfy" and "refine" procedure of
Dwyer, Marriott and Stuckey ("Fast node overlap removal", GD 2005), which is what
libavoid nudges connector segments with: variables that push against each other
merge into a block that moves as one, at the weighted mean of what its members
want, so a bundle of runs forced one lane apart spreads evenly about where they
all wanted to be. Refinement splits a block again wherever a constraint inside it
is pulling rather than pushing, which is what makes the answer the optimum rather
than merely feasible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_EPSILON = 1e-9


@dataclass(eq=False, slots=True)
class _Variable:
    index: int
    desired: float
    weight: float
    offset: float = 0.0
    block: _Block | None = None
    ins: list[_Constraint] = field(default_factory=list)
    outs: list[_Constraint] = field(default_factory=list)

    @property
    def position(self) -> float:
        assert self.block is not None
        return self.block.position + self.offset


@dataclass(eq=False, slots=True)
class _Constraint:
    left: _Variable
    right: _Variable
    gap: float
    active: bool = False
    multiplier: float = 0.0

    @property
    def violation(self) -> float:
        return self.left.position + self.gap - self.right.position


@dataclass(eq=False, slots=True)
class _Block:
    variables: list[_Variable]
    weighted: float = 0.0
    weight: float = 0.0

    @property
    def position(self) -> float:
        return self.weighted / self.weight

    def refresh(self) -> None:
        self.weight = sum(variable.weight for variable in self.variables)
        self.weighted = sum(
            variable.weight * (variable.desired - variable.offset) for variable in self.variables
        )


def solve(
    desired: list[float],
    weights: list[float],
    constraints: list[tuple[int, int, float]],
) -> list[float]:
    """Positions closest to ``desired`` (by ``weights``) that satisfy ``constraints``.

    ``constraints`` are ``(left, right, gap)``: ``x[left] + gap <= x[right]``. They
    must not form a cycle.
    """

    variables = [
        _Variable(index, value, max(weight, 1e-12))
        for index, (value, weight) in enumerate(zip(desired, weights, strict=True))
    ]
    edges = [
        _Constraint(variables[left], variables[right], gap) for left, right, gap in constraints
    ]
    for constraint in edges:
        constraint.left.outs.append(constraint)
        constraint.right.ins.append(constraint)
    for variable in variables:
        variable.block = _Block([variable])
        variable.block.refresh()
    order = _topological(variables)
    _satisfy(order)
    for _ in range(4 * len(edges) + 4):
        split = _split_once(variables)
        if not split:
            break
        _resatisfy(edges)
    return [variable.position for variable in variables]


def _topological(variables: list[_Variable]) -> list[_Variable]:
    """Variables ordered so every constraint's left side comes first."""

    indegree = {variable.index: len(variable.ins) for variable in variables}
    ready = sorted(
        (variable for variable in variables if not variable.ins),
        key=lambda item: (item.desired, item.index),
    )
    result: list[_Variable] = []
    while ready:
        variable = ready.pop(0)
        result.append(variable)
        released = []
        for constraint in variable.outs:
            indegree[constraint.right.index] -= 1
            if indegree[constraint.right.index] == 0:
                released.append(constraint.right)
        if released:
            ready.extend(released)
            ready.sort(key=lambda item: (item.desired, item.index))
    if len(result) != len(variables):
        raise ValueError("separation constraints form a cycle")
    return result


def _satisfy(order: list[_Variable]) -> None:
    for variable in order:
        block = variable.block
        assert block is not None
        while True:
            worst: _Constraint | None = None
            worst_violation = _EPSILON
            for member in block.variables:
                for constraint in member.ins:
                    if constraint.left.block is block:
                        continue
                    violation = constraint.violation
                    if violation > worst_violation:
                        worst, worst_violation = constraint, violation
            if worst is None:
                break
            block = _merge(worst)


def _merge(constraint: _Constraint) -> _Block:
    left_block = constraint.left.block
    right_block = constraint.right.block
    assert left_block is not None and right_block is not None
    distance = constraint.left.offset + constraint.gap - constraint.right.offset
    # Keep the larger block and move the smaller one's offsets into it.
    if len(left_block.variables) >= len(right_block.variables):
        for member in right_block.variables:
            member.offset += distance
            member.block = left_block
        left_block.variables.extend(right_block.variables)
        survivor = left_block
    else:
        for member in left_block.variables:
            member.offset -= distance
            member.block = right_block
        right_block.variables.extend(left_block.variables)
        survivor = right_block
    constraint.active = True
    survivor.refresh()
    return survivor


def _split_once(variables: list[_Variable]) -> bool:
    """Split the block held together by the most negative multiplier, if any."""

    blocks: dict[int, _Block] = {}
    for variable in variables:
        assert variable.block is not None
        blocks[id(variable.block)] = variable.block
    worst: _Constraint | None = None
    worst_value = -1e-7
    worst_block: _Block | None = None
    for block in blocks.values():
        active = [
            constraint
            for member in block.variables
            for constraint in member.outs
            if constraint.active and constraint.right.block is block
        ]
        if not active:
            continue
        multipliers = _multipliers(block, active)
        for constraint in active:
            value = multipliers[id(constraint)]
            if value < worst_value:
                worst, worst_value, worst_block = constraint, value, block
    if worst is None or worst_block is None:
        return False
    worst.active = False
    _split(worst_block, worst)
    return True


def _split(block: _Block, removed: _Constraint) -> None:
    """Break ``block`` in two at ``removed``; each half settles on its own."""

    members = {id(member) for member in block.variables}
    right_side: list[_Variable] = []
    stack = [removed.right]
    seen = {id(removed.right)}
    while stack:
        variable = stack.pop()
        right_side.append(variable)
        for constraint in (*variable.ins, *variable.outs):
            if not constraint.active or constraint is removed:
                continue
            other = constraint.left if constraint.right is variable else constraint.right
            if id(other) in members and id(other) not in seen:
                seen.add(id(other))
                stack.append(other)
    left_side = [member for member in block.variables if id(member) not in seen]
    for part in (left_side, right_side):
        fresh = _Block(part)
        for member in part:
            member.block = fresh
        fresh.refresh()


def _resatisfy(edges: list[_Constraint]) -> None:
    """Merge across violated constraints, most violated first, until none remain."""

    while True:
        worst: _Constraint | None = None
        worst_violation = _EPSILON
        for constraint in edges:
            if constraint.left.block is constraint.right.block:
                continue
            violation = constraint.violation
            if violation > worst_violation:
                worst, worst_violation = constraint, violation
        if worst is None:
            return
        _merge(worst)


def _multipliers(block: _Block, active: list[_Constraint]) -> dict[int, float]:
    """Lagrange multipliers of the active constraints of one block.

    The active constraints of a block form a spanning tree over its members, so
    the multiplier of each is the total pull of the subtree it holds up:
    ``sum(w * (x - d))`` over the variables on its right-hand side of the tree.
    """

    adjacency: dict[int, list[tuple[_Constraint, _Variable, int]]] = {}
    for constraint in active:
        adjacency.setdefault(id(constraint.left), []).append((constraint, constraint.right, 1))
        adjacency.setdefault(id(constraint.right), []).append((constraint, constraint.left, -1))
    result: dict[int, float] = {}
    root = block.variables[0]

    def pull(variable: _Variable, parent: _Constraint | None) -> float:
        total = variable.weight * (variable.position - variable.desired)
        for constraint, other, direction in adjacency.get(id(variable), ()):
            if constraint is parent:
                continue
            child = pull(other, constraint)
            # Moving the child side right is what the constraint resists when
            # the child is its right-hand variable.
            result[id(constraint)] = child if direction == 1 else -child
            total += child
        return total

    pull(root, None)
    return result
