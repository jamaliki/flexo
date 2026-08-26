"""Ergonomic Python authoring that lowers into the versioned semantic IR."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Self

from flexo.components import (
    NOTE_LESS_KINDS,
    NOTE_PROPERTY,
    OPERATOR_SHAPES,
    attachment_lane_tracks,
    component_port_offsets,
    normalize_node,
    vector_stack_width,
)
from flexo.geometry import Side
from flexo.ir.semantic import (
    TITLE_SIDES,
    EdgeSpec,
    FigureSpec,
    GroupSpec,
    JointStyle,
    LayoutKind,
    LayoutSpec,
    NetSpec,
    NodeSpec,
    PortRef,
    PortSpec,
    Scalar,
    TextRun,
)
from flexo.style import (
    PAINT_PARTS,
    PAINT_PROPERTY_PREFIX,
    RAMP_ROLES,
    STYLES,
    LayoutStyle,
    Palette,
    VectorPreset,
    normalize_colour,
)
from flexo.units import Extent, Length, parse_extent, pt
from flexo.validate import normalize_and_validate

if TYPE_CHECKING:  # pragma: no cover - the builder never needs the back end at runtime
    from flexo.compiler import Compilation
    from flexo.export import Build

type Padding = Length | str | float | Sequence[Length | str | float]
"""One length for all four sides, an ``(x, y)`` pair, or ``(top, right, bottom, left)``."""

type Cell = tuple[int, int]
"""A 0-indexed ``(row, column)`` grid address."""

type AttentionVectors = (
    bool | VectorPreset | str | Mapping[str, VectorPreset | str] | None
)
"""How ``attention`` paints the vector glyphs it grows under its three ports.

``None`` (or ``False``) grows none, which is the plain attention block. ``True``
takes the role defaults; one preset or one ramp-role name paints all three alike;
a mapping keyed ``q``/``k``/``v`` paints each its own way.
"""

_OPERATOR_INPUTS = ("input", "south", "north")
"""The edges an ``operator``'s ``inputs=`` arrive on, in order.

West first because that is where a value comes from in a figure that reads across;
then south, which is where a residual rejoins the spine it bypassed; then north.
Sharing one ``input`` between them -- what ``wire`` does for a component with no
numbered ports -- would put every arrowhead of a join on the same point, which is
two runs a hair apart and a ``routing.track.separation`` error for the pair.
"""

_QKV_PORTS = ("q", "k", "v")
"""The attention ports a vector composite grows a glyph for, in reading order."""

_QKV_RAMPS = {"q": "ramp-q", "k": "ramp-kv", "v": "ramp-kv"}
"""``vectors=True``: the palette's own names for these three values.

The palette already separates a query from a key/value pair -- that is what
``ramp-q`` and ``ramp-kv`` are for -- and keys and values share a ramp because
they are read together, which is how the rest of the system draws them. An author
who wants three distinct colours says so with three presets.
"""

_ATTENTION_VECTOR_PORTS = (
    PortSpec("input", Side.SOUTH),
    PortSpec("output", Side.NORTH),
)
"""The two ports one Q/K/V glyph offers, and why both of them are pinned.

A glyph in this composite sits on exactly two wires, and the composite exists to
say where each one runs: the value arrives from underneath and the drop leaves
straight up into the attention port above. Neither side is a component default
waiting to be improved on, which is why neither is ``auto_side``:

- north is the drop's, and only the drop's. A feed re-sided onto it would put two
  runs on the one edge whose straightness is the whole point of centring the
  glyph under its port -- which is exactly what auto-siding *does* choose when
  the value comes from an encoder further up the page, and it costs a
  ``routing.track.separation`` error for the pair.
- south is the feed's, and the caption stands beside the stack rather than under
  it (``_SideCaption``) precisely so that this approach is empty: a feed enters
  the cells dead straight from below. West or east would send the run between two
  glyphs, and a lane is only as wide as the port spacing it was cut from, so two
  feeds entering sideways have to thread the same gap at the same height -- a
  separation error where it is not simply unreadable.

A value computed off to one side therefore travels to below its glyph and comes
up, the way the paper draws its encoder feeding a decoder's cross-attention.
"""


@dataclass(frozen=True, slots=True)
class _SideCaption:
    """A vector caption placed beside its stack, and the room it was given.

    ``reserve`` is the width of the caption's own box and ``gap`` the air between
    that box and the cells; the composite reserves the *same* ``reserve + gap`` on
    the stack's other side as padding, so the whole glyph stays symmetric about
    its cells. That is what keeps the stack centred in its attachment lane while
    the words hang off one side of it: the caption may not move the thing it names
    off the port it feeds.
    """

    side: Side
    """Which side of the stack the words stand on: west or east."""
    reserve: Length
    gap: Length

    @property
    def mirror(self) -> Length:
        """The padding the far side of the stack takes to balance the caption."""

        return Length(self.reserve.points + self.gap.points)


@dataclass(frozen=True, slots=True)
class NodeHandle:
    """A created component, and the ports it offers.

    Passing a handle where a port is expected takes the port the call needs --
    ``output`` for a source, ``input`` for a target -- so wiring rarely names one.
    """

    id: str
    ports: tuple[str, ...]
    aliases: tuple[tuple[str, PortRef], ...] = ()
    """Ports of this handle that resolve to some *other* node's port.

    A composite has one handle but more than one node, and the author should not
    have to know which. ``attention(..., vectors=...)`` is the case that needs it:
    the handle still answers ``output`` from the attention block, while ``q``,
    ``k`` and ``v`` now answer from the vector glyphs that feed the block's own
    q/k/v ports -- so wiring a source into ``.k`` reaches the glyph, and the
    block's port stays internal to the composite. The alias is a ``PortRef``
    rather than another handle, because what a caller does with it is name one
    endpoint.
    """

    def port(self, name: str) -> PortRef:
        """This node's ``name`` port, or an error listing the ports it has."""

        for alias, reference in self.aliases:
            if alias == name:
                return reference
        if name not in self.ports:
            raise AttributeError(
                f'node "{self.id}" has no port "{name}"; valid ports: {", ".join(self.ports)}'
            )
        return PortRef(self.id, name)

    @property
    def input(self) -> PortRef:
        return self.port("input")

    @property
    def output(self) -> PortRef:
        return self.port("output")

    def __getattr__(self, name: str) -> PortRef:
        return self.port(name)


@dataclass(slots=True)
class _GroupDraft:
    id: str
    layout: LayoutSpec
    collision_policy: str
    label: tuple[TextRun, ...]
    role: str
    title_side: str = "left"
    anchor: str | None = None
    shadow: bool = False
    paint: tuple[tuple[str, str], ...] = ()
    children: list[str] = field(default_factory=list)
    placements: dict[str, Cell] = field(default_factory=dict)
    """Grid cells claimed by ``at=``, collected as children are authored."""


class Figure:
    """A figure under construction, and the root group everything hangs from.

    Used as a context manager, leaving the block lowers and validates the
    figure, so an authoring mistake is raised where it was written rather than at
    the first call that reads ``spec``.

    ``width`` takes a length or one of the publication presets the style defines
    (``"single-column"``, ``"double-column"``, ``"presentation"``); ``height`` is
    normally left out, so the canvas ends at the content plus its margin.
    """

    def __init__(
        self,
        id: str = "figure",
        *,
        width: str | Length = "double-column",
        height: Length | str | float | None = None,
        style: str = "paper",
        palette: str = "default",
        layout: LayoutSpec | None = None,
    ) -> None:
        self.id = id
        self.width = width
        self.height = Length.parse(height) if height is not None else None
        self.style = style
        self.palette = palette
        root = _GroupDraft(
            "root",
            layout or LayoutSpec("column", align="center", justify="center"),
            "disjoint",
            (),
            "canvas",
        )
        self._groups: list[_GroupDraft] = [root]
        self._nodes: list[NodeSpec] = []
        self._edges: list[EdgeSpec] = []
        self._nets: list[NetSpec] = []
        self._edge_counter = 0
        self._net_counter = 0
        self.root = GroupBuilder(self, root)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        if exception_type is None:
            _ = self.spec

    def module(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        layout: LayoutKind | LayoutSpec = "row",
        gap: Length | str | float | None = None,
        padding: Padding | None = None,
        align: str = "center",
        justify: str = "center",
        width: Length | str | float | None = None,
        height: Length | str | float | None = None,
        role: str = "module",
        title_side: str = "left",
        anchor: str | None = None,
        shadow: bool = False,
        paint: Mapping[str, str] | None = None,
    ) -> GroupBuilder:
        """Open a titled module directly on the root: ``figure.root.group`` in one call.

        ``padding`` is the same knob, and the same grammar, that ``group`` takes:
        one length for all four sides, an ``(x, y)`` pair, or a ``(top, right,
        bottom, left)`` 4-tuple. It is here because a module is a group -- a figure
        that needed to pull a port up to its module's wall had to abandon
        ``module()`` and rebuild it as a raw ``group`` for the sake of one
        asymmetric edge (R35).
        """

        return self.root.group(
            id,
            label=label,
            layout=layout,
            gap=gap,
            padding=padding,
            align=align,
            justify=justify,
            width=width,
            height=height,
            role=role,
            title_side=title_side,
            anchor=anchor,
            shadow=shadow,
            paint=paint,
        )

    @property
    def spec(self) -> FigureSpec:
        """This figure lowered into the validated semantic IR.

        Reading it validates, so every read either returns a figure that will
        compile or raises about the one that will not.
        """

        groups = tuple(
            GroupSpec(
                draft.id,
                tuple(draft.children),
                _with_placements(draft),
                draft.collision_policy,  # type: ignore[arg-type]
                draft.label,
                draft.role,
                draft.title_side,  # type: ignore[arg-type]
                _scoped_anchor(draft),
                draft.shadow,
                draft.paint,
            )
            for draft in self._groups
        )
        return normalize_and_validate(
            FigureSpec(
                id=self.id,
                width=self.width,
                height=self.height,
                root="root",
                style=self.style,
                palette=self.palette,
                nodes=tuple(self._nodes),
                edges=tuple(self._edges),
                nets=tuple(self._nets),
                groups=groups,
            )
        )

    def net(
        self,
        *,
        src: NodeHandle | PortRef | str,
        sinks: tuple[NodeHandle | PortRef | str, ...]
        | list[NodeHandle | PortRef | str],
        id: str | None = None,
        rail: Side | str | None = None,
        rail_at: float | None = None,
        via: Side | str | None = None,
        joint: JointStyle = "auto",
        label: str | tuple[TextRun, ...] = "",
        role: str = "flow",
    ) -> NetSpec:
        """Author one shared value read by multiple downstream ports."""

        return self._add_net(
            "fan-out",
            (_reference(src, "output"),),
            tuple(_reference(sink, "input") for sink in sinks),
            id=id,
            rail=rail,
            rail_at=rail_at,
            via=via,
            joint=joint,
            label=label,
            role=role,
        )

    def merge(
        self,
        *,
        sinks: tuple[NodeHandle | PortRef | str, ...]
        | list[NodeHandle | PortRef | str],
        dst: NodeHandle | PortRef | str,
        id: str | None = None,
        rail: Side | str | None = None,
        rail_at: float | None = None,
        via: Side | str | None = None,
        joint: JointStyle = "auto",
        label: str | tuple[TextRun, ...] = "",
        role: str = "flow",
    ) -> NetSpec:
        """Author a true many-to-one combination before one destination."""

        return self._add_net(
            "merge",
            tuple(_reference(source, "output") for source in sinks),
            (_reference(dst, "input"),),
            id=id,
            rail=rail,
            rail_at=rail_at,
            via=via,
            joint=joint,
            label=label,
            role=role,
        )

    def _add_net(
        self,
        kind: str,
        sources: tuple[PortRef, ...],
        targets: tuple[PortRef, ...],
        *,
        id: str | None,
        rail: Side | str | None,
        rail_at: float | None,
        via: Side | str | None,
        joint: JointStyle,
        label: str | tuple[TextRun, ...],
        role: str,
    ) -> NetSpec:
        self._net_counter += 1
        net = NetSpec(
            id or f"net.{self._net_counter}",
            kind,  # type: ignore[arg-type]
            sources,
            targets,
            role,
            _label(label),
            _side(rail, "rail side"),
            rail_at,
            joint,
            _side(via, "via side"),
        )
        self._nets.append(net)
        return net

    def compile(
        self,
        *,
        style: LayoutStyle | None = None,
        palette: Palette | None = None,
    ) -> Compilation:
        """Measure, fit, route, and emit this figure, without writing anything."""

        from flexo.compiler import compile_figure

        return compile_figure(self.spec, style=style, palette=palette)

    def render(
        self,
        output_directory: str | Path = "build",
        *,
        stem: str | None = None,
        formats: tuple[str, ...] = ("editable", "portable", "pdf", "png"),
        dpi: float = 192.0,
        style: LayoutStyle | None = None,
        palette: Palette | None = None,
    ) -> Build:
        """Compile, write the requested formats, and lint -- the whole pipeline.

        ``flexo.build(figure_spec, ...)`` is the same call for a figure that
        already lowered to a ``FigureSpec``.
        """

        from flexo.export import build

        return build(
            self.spec,
            output_directory,
            stem=stem,
            formats=formats,
            dpi=dpi,
            style=style,
            palette=palette,
        )


class GroupBuilder:
    """One layout group, and the factory for everything inside it.

    Every id an author writes here is scoped by the group that owns it, so
    ``module.mlp("q-mlp")`` inside group ``cryo`` is ``cryo.q-mlp`` -- which is
    what lets the same component name appear in every module of a figure.
    """

    def __init__(self, figure: Figure, draft: _GroupDraft) -> None:
        self.figure = figure
        self._draft = draft

    @property
    def id(self) -> str:
        return self._draft.id

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        return None

    def group(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        layout: LayoutKind | LayoutSpec = "row",
        gap: Length | str | float | None = None,
        row_gap: Length | str | float | None = None,
        column_gap: Length | str | float | None = None,
        padding: Padding | None = None,
        align: str = "center",
        justify: str = "start",
        columns: int | None = None,
        column_widths: Mapping[int, Length | str | float] | None = None,
        width: Length | str | float | None = None,
        height: Length | str | float | None = None,
        reflow: LayoutKind | None = None,
        equal_size: bool = False,
        collision_policy: str = "disjoint",
        role: str = "container",
        title_side: str = "left",
        anchor: str | None = None,
        shadow: bool = False,
        paint: Mapping[str, str] | None = None,
        at: Cell | None = None,
    ) -> GroupBuilder:
        """Open a nested layout group.

        ``gap`` spaces siblings on both axes; ``row_gap`` and ``column_gap``
        override it for one axis each, so a grid can breathe vertically without
        also spreading sideways. ``padding`` is one length for all four sides, an
        ``(x, y)`` pair, or ``(top, right, bottom, left)``.

        ``align="ports"`` lines this group's children up by the line their side
        ports sit on rather than by their boxes, and ``anchor="<child>"`` names
        the child this group in turn presents to a ports-aligned parent (by
        default, its first child that is neither a label nor a spacer).

        ``shadow=True`` gives the container a soft drop shadow.

        ``paint={"fill": ..., "stroke": ..., "label": ...}`` overrides the
        palette role for this container's body fill, body stroke, and title with
        literal hex colours, exactly as it does for a component. An overridden
        part carries no paint role into the SVG, so ``flexo retheme`` leaves it
        as authored.

        ``at=(row, column)`` places this group in one cell of the enclosing grid
        (see ``grid`` for the rules), and ``column_widths`` reserves minimum
        widths in this group's own grid.

        ``title_side="right"`` anchors the group's title to the right end of its
        top edge instead of the left. The title band is the same height either
        way, so nothing else in the figure moves.
        """

        scoped_id = self._scoped(id)
        if title_side not in TITLE_SIDES:
            raise ValueError(
                f'unknown title side "{title_side}" for group "{scoped_id}"; '
                f"valid sides: {', '.join(TITLE_SIDES)}"
            )
        uniform, top, right, bottom, left = _padding(padding)
        layout_spec = (
            layout
            if isinstance(layout, LayoutSpec)
            else LayoutSpec(
                kind=layout,
                gap=_length(gap),
                padding=uniform,
                align=align,  # type: ignore[arg-type]
                justify=justify,  # type: ignore[arg-type]
                columns=columns,
                width=_length(width),
                height=_length(height),
                reflow=reflow,
                equal_size=equal_size,
                row_gap=_length(row_gap),
                column_gap=_length(column_gap),
                padding_top=top,
                padding_right=right,
                padding_bottom=bottom,
                padding_left=left,
                column_widths=_column_widths(column_widths, columns),
            )
        )
        draft = _GroupDraft(
            scoped_id,
            layout_spec,
            collision_policy,
            _label(label),
            role,
            title_side,
            anchor,
            shadow,
            _paint_parts(paint),
        )
        self._draft.children.append(scoped_id)
        self._place(scoped_id, at)
        self.figure._groups.append(draft)
        return GroupBuilder(self.figure, draft)

    def row(self, id: str, **options: object) -> GroupBuilder:
        """Open a group whose children run left to right; see ``group``."""

        return self.group(id, layout="row", **options)

    def column(self, id: str, **options: object) -> GroupBuilder:
        """Open a group whose children run top to bottom; see ``group``."""

        return self.group(id, layout="column", **options)

    def grid(self, id: str, *, columns: int, **options: object) -> GroupBuilder:
        """Open a grid of ``columns`` columns whose children fill it by cell.

        A child may name its cell with ``at=(row, column)``, 0-indexed from the
        top-left. Mixed mode is deterministic: **addressed children claim their
        cells first, then the unaddressed ones keep author order and flow
        row-major into whatever cells are left.** So a child addressed at (0, 4)
        pushes no sibling sideways -- the flow simply steps over that cell when
        it reaches it.

        Nothing has to fill the holes. A short last row, an empty column, or a
        gap in the middle of a row all cost zero children; the grid pads them
        internally. Rows grow to hold the highest row any child addresses.

        An empty column still occupies its slot, and ``column_widths={index:
        length}`` reserves a minimum width for one -- that is how a lane that
        carries only a connector and its caption gets its space, with no node in
        it at all.

        Two children addressed to the same cell, or a column outside the grid,
        is an error at the point of authoring.
        """

        return self.group(id, layout="grid", columns=columns, **options)

    def overlay(self, id: str, **options: object) -> GroupBuilder:
        """Open a group whose children stack on one another, overlap allowed."""

        return self.group(id, layout="overlay", collision_policy="overlay", **options)

    def node(
        self,
        id: str,
        kind: str = "block",
        *,
        label: str | tuple[TextRun, ...] = "",
        note: str = "",
        role: str = "block",
        ports: tuple[PortSpec, ...] = (),
        width: Extent | str | float | None = None,
        height: Extent | str | float | None = None,
        properties: dict[str, Scalar] | None = None,
        paint: Mapping[str, str] | None = None,
        motif: bool = True,
        shadow: bool = False,
        at: Cell | None = None,
        input: NodeHandle | PortRef | str | None = None,
        inputs: tuple[NodeHandle | PortRef | str, ...]
        | list[NodeHandle | PortRef | str] = (),
    ) -> NodeHandle:
        """Author one component.

        ``width`` and ``height`` take any length, or the string ``"cells:N"`` --
        the height of an N-cell vector stack under the figure's style, so a box
        lines its side ports up with a vector without the author computing the
        stack. ``at=(row, column)`` places the node in one cell of an enclosing
        grid.

        ``paint={"fill": ..., "stroke": ..., "label": ...}`` overrides the
        palette role for this node's body fill, body stroke, and label text with
        literal hex colours. An overridden part carries no paint role into the
        SVG, so ``flexo retheme`` leaves it as authored -- reach for it when one
        component has to differ from its palette, and change the palette when
        every component of a kind does.

        ``note="384 → 768 → 384"`` prints a remark about the component in small
        muted type along the inside of its bottom edge, and grows the box enough
        to hold it. It is drawn like a motif rather than placed like a caption, so
        it neither blocks the south port nor hangs off a stem, and no wrapper
        column is needed to hold the two together; ``\\n`` breaks it into lines.
        Keep the label the name of the operation and put the dimensions here.

        ``motif=False`` drops the component's decorative motif -- an MLP's three
        dots, a matrix's cell grid -- and changes nothing else.

        ``shadow=True`` gives the component a soft drop shadow. Paint only: a
        shadow moves nothing and reserves no space.

        ``input=`` connects one upstream value into this component after it is
        created, and ``inputs=`` connects several. Every component factory takes
        both, with the same meaning, so wiring never depends on which one you
        reached for: one source lands on the component's ``input`` port, several
        land on ``input1``, ``input2``, ... when the component has them and on
        ``input`` when it does not.
        """

        resolved = dict(properties or {})
        resolved.update(_paint_properties(paint))
        if not motif:
            resolved["motif"] = False
        if note:
            if kind in NOTE_LESS_KINDS:
                raise ValueError(
                    f'a "{kind}" has no body to hold a note: its bounds are exactly '
                    "the one thing it draws. Put the words in a label node beside it, "
                    "the way vector() captions its stack."
                )
            resolved[NOTE_PROPERTY] = note
        node = normalize_node(
            NodeSpec(
                self._scoped(id),
                kind,
                _label(label),
                role,
                ports,
                _extent(width),
                _extent(height),
                tuple(sorted(resolved.items())),
                shadow,
            )
        )
        self.figure._nodes.append(node)
        self._draft.children.append(node.id)
        self._place(node.id, at)
        handle = NodeHandle(node.id, tuple(port.name for port in node.ports))
        self.wire(handle, ((input,) if input is not None else ()) + tuple(inputs))
        return handle

    def wire(
        self,
        target: NodeHandle,
        sources: tuple[NodeHandle | PortRef | str, ...],
    ) -> None:
        """Connect every source into ``target``'s input port or ports.

        One source takes the port named ``input``; several take ``input1`` and
        friends when the component offers them, and share ``input`` when it does
        not -- a fan-in the router draws as one arrival. A component with neither
        says so by name rather than by ``AttributeError`` from somewhere deeper.
        """

        if not sources:
            return
        numbered = tuple(f"input{index + 1}" for index in range(len(sources)))
        if len(sources) > 1 and all(name in target.ports for name in numbered):
            names = numbered
        else:
            names = (_single_input(target),) * len(sources)
        for source, name in zip(sources, names, strict=True):
            self.connect(source, target.port(name))

    def block(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        **options: object,
    ) -> NodeHandle:
        """A plain labelled box: the component to reach for when none of the others fit."""

        return self.node(id, "block", label=label, **options)

    def operator(
        self,
        id: str,
        glyph: str = "+",
        *,
        shape: str = "square",
        input: NodeHandle | PortRef | str | None = None,
        inputs: tuple[NodeHandle | PortRef | str, ...]
        | list[NodeHandle | PortRef | str] = (),
        **options: object,
    ) -> NodeHandle:
        """One arithmetic symbol: a 14 pt square or circle bearing a single glyph.

        Simple operations are symbols, not modules (R2). ``+`` is a residual
        join, a multiplication sign a gate, ``·`` a matrix or affine
        application, ``Σ`` a weighted sum -- and nothing else goes inside the
        shape, so an operation that needs qualification takes a caption or an
        edge label beside it rather than a second word in the glyph. A ``block``
        labelled "Add" is a module-sized claim about an operation that costs one
        character to draw.

        It offers the four side centres -- ``input`` west, ``output`` east, plus
        ``north`` and ``south`` -- because a symbol this small has no edge for an
        adaptive port to slide along, and because a join is normally drawn with one
        value arriving along the spine and the other from the side it was tapped
        from. Wiring follows the standard keywords: ``input=`` lands on ``input``,
        and ``inputs=`` fills ``input``, then ``south``, then ``north``, so
        ``operator("join", "+", inputs=(sublayer, skip))`` draws two arrivals on
        two edges rather than two arrowheads on one point. An authored ``ports=``
        replaces the table and the sources are wired through it as usual.

        ``shape="circle"`` draws the same symbol as a circle. ``paint=``,
        ``width``/``height``, and ``at=`` all behave as they do on any component.
        """

        if shape not in OPERATOR_SHAPES:
            raise ValueError(
                f'unknown operator shape "{shape}" for "{id}"; '
                f"valid shapes: {', '.join(OPERATOR_SHAPES)}"
            )
        if len(glyph.strip()) != 1:
            raise ValueError(
                f'an operator carries exactly one glyph, not "{glyph}"; '
                "qualify the operation with a caption or an edge label beside it"
            )
        ports = _authored_ports(options)
        if shape != OPERATOR_SHAPES[0]:
            options = _with_properties(options, shape=shape)
        result = self.node(id, "operator", label=glyph.strip(), ports=ports, **options)
        sources = ((input,) if input is not None else ()) + tuple(inputs)
        if len(sources) > 1 and not ports:
            if len(sources) > len(_OPERATOR_INPUTS):
                raise ValueError(
                    f'operator "{id}" has {len(_OPERATOR_INPUTS)} sides to read from '
                    f"({', '.join(_OPERATOR_INPUTS)}), not {len(sources)}; "
                    "give it a ports= table, or feed it from a net"
                )
            for source, name in zip(sources, _OPERATOR_INPUTS, strict=False):
                self.connect(source, result.port(name))
        else:
            self.wire(result, sources)
        return result

    def feature_strip(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        cells: int = 6,
        **options: object,
    ) -> NodeHandle:
        """A horizontal strip of ``cells`` shaded cells under its label."""

        return self.node(
            id,
            "feature-strip",
            label=label,
            **_with_properties(options, cells=cells),
        )

    def vector(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        preset: VectorPreset | None = None,
        ramp: str | None = None,
        cells: int | None = None,
        columns: int | None = None,
        input: NodeHandle | PortRef | str | None = None,
        gap: Length | str | float | None = None,
        at: Cell | None = None,
        **options: object,
    ) -> NodeHandle:
        """A labelled vertical vector glyph: a cell stack with its label below it.

        The composite lowers into a small layout column holding two children --
        ``<id>.cells`` (kind ``vector``) and, when a label is given,
        ``<id>.label`` (kind ``label``). Keeping the caption in its own node is
        what lets the glyph's ports stay the trivial centres of the cell rect:
        no port arithmetic has to know that a caption hangs underneath, and an
        arrow arrives on the middle cell rather than on the middle of
        cells-plus-caption. The returned handle is always the cells node, so
        edges and nets attach to the glyph itself.

        A caption wider than the stack is fine -- the column centres both -- and
        a ``\\n`` in the label breaks it across lines instead of widening it.

        A ``preset`` replaces ``ramp``, ``cells``, and ``columns``: it carries
        the author's own base colour and topology, and the cells paint the
        shades it derives rather than a palette role.

        ``at=(row, column)`` addresses the composite -- caption and all -- in an
        enclosing grid, because the column holding both is the grid's child.
        """

        return self._vector_composite(
            id,
            label=label,
            preset=preset,
            ramp=ramp,
            cells=cells,
            columns=columns,
            input=input,
            gap=gap,
            at=at,
            options=options,
        )

    def _vector_composite(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...],
        preset: VectorPreset | None,
        ramp: str | None,
        cells: int | None,
        columns: int | None,
        input: NodeHandle | PortRef | str | None,
        gap: Length | str | float | None,
        at: Cell | None,
        options: dict[str, object],
        label_role: str = "label",
        caption: _SideCaption | None = None,
    ) -> NodeHandle:
        """Lower one captioned vector glyph; see ``vector`` for the shape.

        ``label_role`` is for a composite that owns the glyph rather than the
        author: ``attention`` captions its Q/K/V glyphs as captions, so they paint
        in muted ink the way every other secondary label in the system does.

        ``caption`` moves those words *beside* the stack instead of under it, on a
        ports-aligned row so they sit on the cells' own port line, with the same
        room reserved as padding on the stack's other side. The stack therefore
        stays exactly where a caption-below composite put it -- centred in
        whatever cell it was placed in -- and the corridor under it, which is the
        only approach a south-facing feed has, is left empty.
        """

        if preset is not None:
            if ramp is not None or cells is not None or columns is not None:
                raise ValueError(
                    "a vector preset already carries colour and topology; "
                    "drop ramp, cells, and columns"
                )
            properties: dict[str, Scalar] = {
                "cells": preset.cells,
                "columns": preset.columns,
                "shades": preset.encode(),
            }
        else:
            ramp = "ramp-node" if ramp is None else ramp
            cells = 3 if cells is None else cells
            columns = 1 if columns is None else columns
            if cells < 1:
                raise ValueError("a vector needs at least one cell")
            if columns < 1:
                raise ValueError("a vector needs at least one column")
            if ramp not in RAMP_ROLES:
                valid = ", ".join(RAMP_ROLES)
                raise ValueError(f'unknown vector ramp "{ramp}"; valid ramps: {valid}')
            properties = {"cells": cells, "columns": columns, "ramp": ramp}
        words = _label(label)
        beside = caption if words else None
        if beside is None:
            stack = self.column(
                id,
                gap=_vector_label_gap(self.figure.style) if gap is None else gap,
                padding=0,
                align="center",
                role="layout",
                at=at,
            )
        else:
            zero = pt(0.0)
            # (top, right, bottom, left): the stack's far side takes the caption's
            # room back as padding, so the glyph stays symmetric about its cells.
            padding = (
                (zero, beside.mirror, zero, zero)
                if beside.side is Side.WEST
                else (zero, zero, zero, beside.mirror)
            )
            stack = self.row(
                id,
                gap=beside.gap,
                padding=padding,
                align="ports",
                anchor="cells",
                role="layout",
                at=at,
            )

        def write_caption() -> None:
            stack.node(
                "label",
                "label",
                label=words,
                role=label_role,
                **({} if beside is None else {"width": beside.reserve}),
            )

        leads = beside is not None and beside.side is Side.WEST
        if leads:
            write_caption()
        result = stack.node(
            "cells",
            "vector",
            **{"role": "vector", **_with_properties(options, **properties)},
        )
        if words and not leads:
            write_caption()
        if input is not None:
            self.connect(input, result.input)
        return result

    def matrix(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        **options: object,
    ) -> NodeHandle:
        """A box whose motif is a grid of shaded cells."""

        return self.node(id, "matrix", label=label, **options)

    def sequence(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        tokens: int = 7,
        **options: object,
    ) -> NodeHandle:
        """A box whose motif is a run of ``tokens`` dots: a sequence of residues."""

        return self.node(
            id,
            "sequence",
            label=label,
            **_with_properties(options, tokens=tokens),
        )

    def graph(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        **options: object,
    ) -> NodeHandle:
        """A bordered panel whose motif is a little node-and-edge network."""

        return self.node(id, "graph", label=label, **options)

    def inset(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        **options: object,
    ) -> NodeHandle:
        """A bordered scientific panel whose motif is a molecule illustration.

        Give two insets in one figure the same ``height``: an inset sized to its
        own label draws its molecule at a different scale from its neighbour's.
        """

        return self.node(id, "inset", label=label, **options)

    def image(
        self,
        id: str,
        source: str | Path,
        *,
        width: Extent | str | float | None = None,
        height: Extent | str | float | None = None,
        label: str | tuple[TextRun, ...] = "",
        **options: object,
    ) -> NodeHandle:
        """Place artwork the author drew, as a first-class node.

        Some ink is not the compiler's to invent -- a molecule, a density map,
        the one panel that has to be the real thing. Draw it as an ``.svg`` (or
        render it to a ``.png``) and hand Flexo the file: it becomes an ordinary
        component with the four side-centre ports, so connectors, layout, and
        routing treat it exactly as they treat a block, and routes keep clear of
        it like any other body.

        An SVG source stays vector all the way through. Flexo nests the file's
        own content at the node's bounds with its viewBox intact, so the drawing
        is crisp at any zoom and still made of objects an editor can select --
        and it is *embedded*, not linked, so the editable SVG, the portable SVG,
        and the PDF each carry the artwork with them.

        Size follows the file. Its intrinsic size comes from its ``width`` and
        ``height``, or from its viewBox read as CSS pixels; a PNG's comes from
        its pixel size at 96 dpi. Give ``width`` or ``height`` alone and the
        other follows the artwork's aspect ratio; give both and the drawing
        letterboxes inside those bounds rather than distorting. Both extents
        take any length or ``"cells:N"``, so a panel of icons can be exactly as
        tall as the vector stack beside it.

        The path resolves against the working directory the figure is
        *compiled* in, so absolute paths are the reliable choice. A missing
        file, an unreadable one, or a suffix that is neither ``.svg`` nor
        ``.png`` is a diagnostic naming this node and that path.

        Artwork is checked before it is inlined, because inlining is what makes
        it dangerous: a file carrying a ``<script>``, an ``on*`` event handler,
        or a reference to anything outside itself is rejected with a diagnostic
        rather than quietly stripped. Every id in the artwork is rewritten under
        this node's id, so the same file may be embedded twice in one figure
        without the two copies sharing a gradient.

        A ``label`` sits over the artwork, centred, as on any other node. For a
        caption *under* the drawing, put the image and a ``label`` node in a
        column, the way ``vector`` captions its stack.
        """

        return self.node(
            id,
            "image",
            label=label,
            width=width,
            height=height,
            **_with_properties(options, source=str(source)),  # type: ignore[arg-type]
        )

    def tensor(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "",
        **options: object,
    ) -> NodeHandle:
        """A labelled box drawn as a stacked slab: a multi-dimensional value."""

        return self.node(id, "tensor", label=label, **options)

    def concat(
        self,
        id: str,
        *,
        inputs: tuple[NodeHandle | PortRef | str, ...]
        | list[NodeHandle | PortRef | str],
        label: str | tuple[TextRun, ...] = "Concat",
        **options: object,
    ) -> NodeHandle:
        """Join two or more values, one west port each, in the order given.

        Two inputs is the minimum: a concat of one is the value itself.
        """

        sources = tuple(inputs)
        if len(sources) < 2:
            raise ValueError("concat requires at least two inputs")
        ports = _authored_ports(options) or (
            *(
                PortSpec(
                    f"input{index + 1}",
                    Side.WEST,
                    (index + 1) / (len(sources) + 1),
                    adaptive=True,
                )
                for index in range(len(sources))
            ),
            PortSpec("output", Side.EAST, adaptive=True),
        )
        result = self.node(id, "concat", label=label, ports=ports, **options)
        self.wire(result, sources)
        return result

    def channels(
        self,
        id: str,
        *,
        labels: tuple[str, ...] | list[str],
        input: NodeHandle | PortRef | str | None = None,
        **options: object,
    ) -> tuple[PortRef, ...]:
        """Split one value into a captioned east port per label.

        Returns the ports rather than the node, in ``labels`` order, because what
        an author wants next is to wire each channel somewhere different.
        """

        names = tuple(labels)
        if not names:
            raise ValueError("channels requires at least one label")
        ports = _authored_ports(options) or (
            PortSpec("input", Side.WEST, adaptive=True),
            *(
                PortSpec(
                    _port_name(name),
                    Side.EAST,
                    (index + 1) / (len(names) + 1),
                    adaptive=True,
                )
                for index, name in enumerate(names)
            ),
        )
        result = self.node(
            id,
            "channels",
            ports=ports,
            **_with_properties(options, count=len(names), labels=",".join(names)),
        )
        if input is not None:
            self.wire(result, (input,))
        return tuple(result.port(_port_name(name)) for name in names)

    def add_norm(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "Add + norm",
        input: NodeHandle | PortRef | str | None = None,
        skip: NodeHandle | PortRef | str | None = None,
        **options: object,
    ) -> NodeHandle:
        """A residual-normalization box, with a port for each wire it sits on.

        It carries no motif: the words are the component. What it does carry is a
        port table shaped like a residual join. ``skip`` is a third default port
        beside ``input`` and ``output``, because a residual target takes *two*
        values and they are not interchangeable -- ``input`` is the sublayer's
        output and ``skip`` is the value that bypassed it. Sending both into
        ``input`` puts two arrowheads on one point, which the router draws as two
        runs a hair apart with a hook on each.

        So ``add_norm("an", input=attention, skip=embedding)`` is the idiom, and
        ``connect(x, an, target_port="skip")`` says the same thing for a value
        authored later. ``branch`` completes it on the way out: the value leaving
        here feeds the next sublayer through ``output`` and bypasses it through
        ``branch``, so a spine of these reads as one arrow per wire instead of
        two arrows leaving one point.

        Every port is auto-sided, so in a tower that reads upward they all end up
        where the ink is with no port table written down. Everything else
        composes as on any block -- ``width``, ``paint``, ``input=``/``inputs=``,
        and ``ports=`` to replace the table wholesale.
        """

        result = self.node(id, "add-norm", label=label, **options)
        if input is not None:
            self.wire(result, (input,))
        if skip is not None:
            self.connect(skip, result.port("skip"))
        return result

    def mlp(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "MLP",
        input: NodeHandle | PortRef | str | None = None,
        inputs: tuple[NodeHandle | PortRef | str, ...] | list[NodeHandle | PortRef | str] = (),
        outputs: tuple[str, ...] | list[str] = (),
        **options: object,
    ) -> NodeHandle | tuple[PortRef, ...]:
        """A multilayer perceptron, sized to its label and wired to its sources.

        Several ``inputs`` give the block one west port each, and named
        ``outputs`` one east port each, so a component that reads two values and
        publishes two more needs no port table. An authored ``ports=`` replaces
        that table wholesale -- the author's sides and offsets are the design --
        and the sources are then wired to the input ports it declares.
        """

        sources = ((input,) if input is not None else ()) + tuple(inputs)
        ports = _authored_ports(options) or (
            _processing_ports(len(sources), tuple(outputs)) if sources or outputs else ()
        )
        result = self.node(id, "mlp", label=label, ports=ports, **options)
        self.wire(result, sources)
        if outputs:
            return tuple(result.port(_port_name(name)) for name in outputs)
        return result

    def cnn(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "CNN",
        input: NodeHandle | PortRef | str | None = None,
        output: str | None = None,
        **options: object,
    ) -> NodeHandle | PortRef:
        """A convolutional block, motif a zigzag.

        Naming ``output`` returns that port instead of the node, so a chain can
        continue from it directly.
        """

        ports = _authored_ports(options) or (
            (
                PortSpec("input", Side.WEST, adaptive=True),
                PortSpec(_port_name(output), Side.EAST, adaptive=True),
            )
            if output
            else ()
        )
        result = self.node(id, "cnn", label=label, ports=ports, **options)
        if input is not None:
            self.wire(result, (input,))
        return result.port(_port_name(output)) if output else result

    def attention(
        self,
        id: str,
        *,
        q: NodeHandle | PortRef | str | None = None,
        k: NodeHandle | PortRef | str | None = None,
        v: NodeHandle | PortRef | str | None = None,
        vectors: AttentionVectors = None,
        label: str | tuple[TextRun, ...] = "Attention",
        **options: object,
    ) -> NodeHandle:
        """An attention block, wired from as many of its three sources as exist yet.

        ``q``, ``k``, and ``v`` wire straight into the component's three ports
        when they are given, which is what an author writes when the sources
        already exist. All three are optional, because a figure is not always
        written in flow order: a decoder's cross-attention reads keys and values
        from an encoder that is authored *after* it, and a component that could
        not be created before its inputs would force the whole tower to be
        written inside out. The q/k/v ports exist either way, so the missing legs
        are ordinary ``connect(source, block.k)`` calls later on.

        ``vectors=`` grows the block's three inputs as *vector glyphs* under it,
        the way the Transformer paper draws them: one cell stack per port, each
        centred exactly under the port it feeds, joined to it by a plain vertical,
        and captioned to one side so that nothing stands in the way of the value
        arriving from below. ``vectors=True`` takes the palette's own q and k/v
        ramps; one ``VectorPreset`` or one ramp-role name paints all three alike;
        a ``{"q": ..., "k": ..., "v": ...}`` mapping paints each its own way.

        The composite is the block plus the glyph row, and the handle it returns
        still speaks for the block -- ``output`` is the attention output -- but
        ``q``, ``k`` and ``v`` now answer from the *glyphs*, because that is where
        a value entering this attention now arrives. Every glyph is fed from
        underneath and drops straight up into its port
        (``_ATTENTION_VECTOR_PORTS``), so a value computed off to one side
        travels to below its glyph and comes up, the way the paper draws an
        encoder feeding a decoder's cross-attention.

        Lanes fill in port-offset order, so an authored ``ports=`` that reads the
        value on the left puts that glyph on the left too -- which is how a
        cross-attention is drawn, and what keeps the line feeding it clear of the
        query arriving from the decoder's own spine.

        A composite needs a ``width``: centring a glyph under a port fraction is
        arithmetic on the block's width, and the whole point of ``vectors=`` is
        that the author does not do that arithmetic. In a ports-aligned parent the
        composite answers with the *block*, so a row of towers lines up on the
        attention boxes rather than on the glyphs and captions hanging beneath
        them.

        For attention drawn as a captioned arrow instead of a box, reach for
        ``merge`` with a formula label.
        """

        if not vectors:
            result = self.node(id, "attention", label=label, **options)
            for source, name in ((q, "q"), (k, "k"), (v, "v")):
                if source is not None:
                    self.connect(source, result.port(name))
            return result
        return self._attention_composite(
            id, vectors, sources=(q, k, v), label=label, options=options
        )

    def _attention_composite(
        self,
        id: str,
        vectors: AttentionVectors,
        *,
        sources: tuple[NodeHandle | PortRef | str | None, ...],
        label: str | tuple[TextRun, ...],
        options: dict[str, object],
    ) -> NodeHandle:
        """Lower ``attention(..., vectors=...)`` into a block over a row of glyphs.

        The row is a one-row grid as wide as the block, whose reserved column
        widths come from the block's own port offsets
        (``attachment_lane_tracks``): a pad, then a lane per port, then a pad.
        Each glyph is centred in its lane, so its cells' centre is the port's x by
        construction and the connector between them is a vertical with nothing to
        route around -- which is also why the corridor above the glyphs is not a
        number written here. The block and the row are siblings of one column, so
        the three drops cross that column's one sibling boundary and the ordinary
        edge-aware gap machinery reserves clearance, an arrival, and a lane per
        drop, exactly as it does for any crossed boundary.

        Lanes are filled in *offset* order rather than in q/k/v order, so an
        authored ``ports=`` that puts the value on the left puts its glyph there
        too. Nothing else here knows which name sits where.

        Each caption sits *beside* its stack, in the lane's own padding
        (``_glyph_caption``), because the corridor under a glyph is the only
        approach its feed has: a caption parked in it makes every arriving arrow
        hook around the words. Beside, the feeds enter dead straight.
        """

        presets = _attention_vectors(vectors)
        width = options.pop("width", None)
        if width is None:
            raise ValueError(
                f'attention "{self._scoped(id)}" needs a width to grow its vectors: '
                "the glyphs are centred under the block's q/k/v ports, which is a "
                "fraction of a width the block would otherwise take from its label"
            )
        style = STYLES.get(self.figure.style) or LayoutStyle()
        block_width = style.resolve_extent(parse_extent(width)).points  # type: ignore[arg-type]
        offsets = _attention_offsets(tuple(options.get("ports") or ()), tuple(presets))
        presets = {name: presets[name] for name in sorted(presets, key=offsets.__getitem__)}
        tracks = attachment_lane_tracks(tuple(offsets[name] for name in presets), block_width)
        caption = _glyph_caption(
            tracks[1],
            max(
                vector_stack_width(
                    preset.columns if isinstance(preset, VectorPreset) else 1, style
                )
                for preset in presets.values()
            ),
            style,
        )
        composite = self.column(
            id,
            padding=0,
            role="layout",
            anchor="block",
            at=options.pop("at", None),  # type: ignore[arg-type]
        )
        block = composite.node("block", "attention", label=label, width=width, **options)
        row = composite.grid(
            "qkv",
            columns=len(tracks),
            column_widths={index: pt(track) for index, track in enumerate(tracks)},
            width=pt(block_width),
            gap=pt(0.0),
            padding=0,
            align="center",
            role="layout",
        )
        glyphs = {
            name: row._vector_composite(
                name,
                label=name.upper(),
                preset=preset if isinstance(preset, VectorPreset) else None,
                ramp=None if isinstance(preset, VectorPreset) else preset,
                cells=None,
                columns=None,
                input=None,
                gap=None if caption is not None else _glyph_caption_gap(self.figure.style),
                at=(0, 2 * index + 1),
                options={"ports": _ATTENTION_VECTOR_PORTS},
                label_role="caption",
                caption=caption,
            )
            for index, (name, preset) in enumerate(presets.items())
        }
        for name, glyph in glyphs.items():
            composite.connect(glyph, block.port(name))
        result = NodeHandle(
            block.id,
            block.ports,
            tuple((name, glyph.input) for name, glyph in glyphs.items()),
        )
        for source, name in zip(sources, _QKV_PORTS, strict=True):
            if source is not None:
                self.connect(source, result.port(name))
        return result

    def prediction(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "Prediction",
        input: NodeHandle | PortRef | str | None = None,
        **options: object,
    ) -> NodeHandle:
        """A terminal readout box, painted in the warm role rather than the block one."""

        result = self.node(id, "prediction", label=label, **options)
        if input is not None:
            self.wire(result, (input,))
        return result

    def loss(
        self,
        id: str,
        *,
        label: str | tuple[TextRun, ...] = "Loss",
        input: NodeHandle | PortRef | str | None = None,
        **options: object,
    ) -> NodeHandle:
        """A training-objective box, painted in the warm role like ``prediction``."""

        result = self.node(id, "loss", label=label, **options)
        if input is not None:
            self.wire(result, (input,))
        return result

    def net(
        self,
        *,
        src: NodeHandle | PortRef | str,
        sinks: tuple[NodeHandle | PortRef | str, ...] | list[NodeHandle | PortRef | str],
        id: str | None = None,
        rail: Side | str | None = None,
        rail_at: float | None = None,
        via: Side | str | None = None,
        joint: JointStyle = "auto",
        label: str | tuple[TextRun, ...] = "",
        role: str = "flow",
    ) -> NetSpec:
        """Author one shared value read by multiple downstream ports.

        A net belongs to the figure -- its rail may leave any group it likes --
        but the group builder is what an author has in hand while writing the
        components it joins. Reaching for ``figure.net`` mid-block only to name
        the same handles is a detour, so ``root.net(...)`` works wherever
        ``root.connect(...)`` does, with the same arguments and the same result.
        """

        return self.figure.net(
            src=src,
            sinks=sinks,
            id=id,
            rail=rail,
            rail_at=rail_at,
            via=via,
            joint=joint,
            label=label,
            role=role,
        )

    def merge(
        self,
        *,
        sinks: tuple[NodeHandle | PortRef | str, ...] | list[NodeHandle | PortRef | str],
        dst: NodeHandle | PortRef | str,
        id: str | None = None,
        rail: Side | str | None = None,
        rail_at: float | None = None,
        via: Side | str | None = None,
        joint: JointStyle = "auto",
        label: str | tuple[TextRun, ...] = "",
        role: str = "flow",
    ) -> NetSpec:
        """Author a true many-to-one combination; see ``net`` and ``Figure.merge``."""

        return self.figure.merge(
            sinks=sinks,
            dst=dst,
            id=id,
            rail=rail,
            rail_at=rail_at,
            via=via,
            joint=joint,
            label=label,
            role=role,
        )

    def connect(
        self,
        source: NodeHandle | PortRef | str,
        target: NodeHandle | PortRef | str,
        *,
        id: str | None = None,
        source_port: str = "output",
        target_port: str = "input",
        role: str = "flow",
        label: str | tuple[TextRun, ...] = "",
        lane: str | None = None,
        via: Side | str | None = None,
    ) -> EdgeSpec:
        """Draw one connector from ``source`` to ``target``.

        Handles take their ``output`` and ``input`` ports; a ``"node.port"``
        string or a ``PortRef`` names one exactly. ``lane=`` routes the edge
        through an authored corridor instead of wherever the router would take
        it, and a lane-routed edge no longer votes on which side its ports face.

        ``via="west"`` (or any side) leans the route toward that side of the
        region between its two endpoints rather than pinning it anywhere: the
        router pays extra for corridors beyond that region on the *opposite*
        side, and the arriving port faces the hinted side when its own side is a
        component default. It is one word for "go round the near side", and it
        reports ``routing.via.clamped`` if the geometry left it no choice.
        """

        source_ref = _reference(source, source_port)
        target_ref = _reference(target, target_port)
        self.figure._edge_counter += 1
        edge = EdgeSpec(
            id or f"edge.{self.figure._edge_counter}.{source_ref.node_id}-to-{target_ref.node_id}",
            source_ref,
            target_ref,
            role,
            _label(label),
            lane,
            via=_side(via, "via side"),
        )
        self.figure._edges.append(edge)
        return edge

    def residual(
        self,
        source: NodeHandle | PortRef | str,
        target: NodeHandle | PortRef | str,
        *,
        id: str | None = None,
        lane: str | None = None,
        via: Side | str | None = None,
        source_port: str | None = None,
        target_port: str | None = None,
    ) -> EdgeSpec:
        """A skip connection, painted in the ``residual`` role.

        It prefers whichever port a component dedicates to skip traffic --
        ``residual``, then ``skip`` -- and falls back to the ordinary
        ``output``/``input`` pair, so a component that declares one gets its skip
        ink where it meant to instead of crowding the port its sublayer output
        already arrives on.
        """

        if source_port is None and isinstance(source, NodeHandle):
            source_port = _skip_port(source, "output")
        if target_port is None and isinstance(target, NodeHandle):
            target_port = _skip_port(target, "input")
        return self.connect(
            source,
            target,
            id=id,
            source_port=source_port or "output",
            target_port=target_port or "input",
            role="residual",
            lane=lane,
            via=via,
        )

    def _scoped(self, id: str) -> str:
        if self.id == "root" or id.startswith(f"{self.id}."):
            return id
        return f"{self.id}.{id}"

    def _place(self, child_id: str, at: Cell | None) -> None:
        """Claim one grid cell for a child, rejecting a clash where it is made."""

        if at is None:
            return
        layout = self._draft.layout
        if layout.kind != "grid":
            raise ValueError(
                f'"at" addresses a grid cell, but group "{self.id}" lays out as a {layout.kind}'
            )
        if len(tuple(at)) != 2:
            raise ValueError('"at" takes a (row, column) pair')
        row, column = (int(value) for value in at)
        columns = layout.columns or 1
        if row < 0 or column < 0:
            raise ValueError(
                f'cell (row {row}, column {column}) for "{child_id}" is out of range; '
                "grid rows and columns are 0-indexed"
            )
        if column >= columns:
            raise ValueError(
                f'column {column} for "{child_id}" is out of range; '
                f'group "{self.id}" has {columns} columns (0-{columns - 1})'
            )
        for other_id, cell in self._draft.placements.items():
            if cell == (row, column):
                raise ValueError(
                    f'cell (row {row}, column {column}) of group "{self.id}" is already '
                    f'taken by "{other_id}"'
                )
        self._draft.placements[child_id] = (row, column)


def _scoped_anchor(draft: _GroupDraft) -> str | None:
    """The authored anchor child, resolved to the id this group actually holds.

    Ids are scoped by the group that owns them, so an author naming a child
    writes the short name they wrote when they made it. A name that is already a
    child is taken as written, and one that matches neither form is passed
    through so ``GroupSpec`` raises about the name the author actually typed.
    """

    if draft.anchor is None or draft.anchor in draft.children:
        return draft.anchor
    scoped = f"{draft.id}.{draft.anchor}"
    return scoped if scoped in draft.children else draft.anchor


def _with_placements(draft: _GroupDraft) -> LayoutSpec:
    if not draft.placements:
        return draft.layout
    return replace(
        draft.layout,
        placements=tuple(
            (child_id, row, column) for child_id, (row, column) in draft.placements.items()
        ),
    )


def _authored_ports(options: dict[str, object]) -> tuple[PortSpec, ...]:
    """Take an author's ``ports=`` out of a factory's options, if they gave one.

    A factory that computes ports -- an MLP with three inputs, a channels strip
    -- computes them for the author who did not write any. One who did has said
    something more specific than the factory knows, so their table wins whole:
    the alternative used to be ``got multiple values for keyword argument
    'ports'``, which is a bug report about our signature, not about their figure.
    """

    authored = options.pop("ports", None)
    return tuple(authored) if authored else ()  # type: ignore[arg-type]


def _with_properties(options: dict[str, object], **defaults: Scalar) -> dict[str, object]:
    """Merge a factory's own node properties under whatever the author passed."""

    authored = options.pop("properties", None) or {}
    return {**options, "properties": {**defaults, **authored}}  # type: ignore[dict-item]


def _single_input(target: NodeHandle) -> str:
    """The one port a lone source should arrive on."""

    if "input" in target.ports:
        return "input"
    candidates = tuple(name for name in target.ports if name.startswith("input"))
    if len(candidates) == 1:
        return candidates[0]
    detail = (
        f"it has {', '.join(candidates)}; name the one you mean"
        if candidates
        else f'its ports are {", ".join(target.ports) or "none"}'
    )
    raise ValueError(f'node "{target.id}" has no "input" port to wire into: {detail}')


_SKIP_PORTS = ("residual", "skip")
"""Port names a component may dedicate to skip traffic, in preference order.

``residual`` came first and stays first; ``skip`` is what the residual-target
components call the same thing now (see ``add_norm``). One tuple, so a component
declaring either gets its skip ink on it.
"""


def _skip_port(handle: NodeHandle, fallback: str) -> str:
    """The port a skip connection should use on ``handle``."""

    return next((name for name in _SKIP_PORTS if name in handle.ports), fallback)


def _side(value: Side | str | None, label: str) -> Side | None:
    """One authored side, by name or by value, or ``None`` for no hint."""

    if value is None or isinstance(value, Side):
        return value
    try:
        return Side(value)
    except ValueError:
        valid = ", ".join(side.value for side in Side)
        raise ValueError(f'unknown {label} "{value}"; valid sides: {valid}') from None


def _paint_parts(paint: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    """One authored ``paint`` mapping, validated and sorted, as ``(part, colour)``.

    Colours are normalized to ``#rrggbb`` here, which is both the validation and
    what keeps ``#abc`` and ``#aabbcc`` from serializing as two different
    figures. Components and containers take the same three parts, so they take
    the same check.
    """

    if not paint:
        return ()
    unknown = sorted(set(paint) - set(PAINT_PARTS))
    if unknown:
        raise ValueError(
            f"unknown paint part(s) {', '.join(unknown)}; "
            f"valid parts: {', '.join(PAINT_PARTS)}"
        )
    return tuple(sorted((part, normalize_colour(colour)) for part, colour in paint.items()))


def _paint_properties(paint: Mapping[str, str] | None) -> dict[str, Scalar]:
    """Lower an authored ``paint`` mapping into one scalar property per part.

    A node property holds a scalar, never a mapping, so the three parts travel
    separately as ``paint-fill``, ``paint-stroke``, and ``paint-label``.
    """

    return {
        f"{PAINT_PROPERTY_PREFIX}{part}": colour for part, colour in _paint_parts(paint)
    }


def _padding(value: Padding | None) -> tuple[Length | None, ...]:
    """Normalize an authored padding into (uniform, top, right, bottom, left).

    One length stays uniform, so a figure that never asks for asymmetry keeps
    exactly the spec it had before the four sides existed.
    """

    if value is None or isinstance(value, (Length, str, int, float)):
        return (_length(value), None, None, None, None)
    sides = tuple(Length.parse(item) for item in value)
    if len(sides) == 2:
        x, y = sides
        return (None, y, x, y, x)
    if len(sides) == 4:
        return (None, *sides)
    raise ValueError(
        "padding takes one length, an (x, y) pair, or a (top, right, bottom, left) 4-tuple, "
        f"not {len(sides)} values"
    )


def _column_widths(
    value: Mapping[int, Length | str | float] | None,
    columns: int | None,
) -> tuple[tuple[int, Length], ...]:
    if not value:
        return ()
    if columns is None:
        raise ValueError("column widths need a column count; give the group columns=")
    return tuple(sorted((int(column), Length.parse(width)) for column, width in value.items()))


def _processing_ports(input_count: int, outputs: tuple[str, ...]) -> tuple[PortSpec, ...]:
    inputs = tuple(
        PortSpec(
            "input" if input_count == 1 else f"input{index + 1}",
            Side.WEST,
            (index + 1) / (input_count + 1),
            adaptive=True,
        )
        for index in range(input_count)
    )
    output_names = outputs or ("output",)
    result_outputs = tuple(
        PortSpec(
            _port_name(name),
            Side.EAST,
            (index + 1) / (len(output_names) + 1),
            adaptive=True,
        )
        for index, name in enumerate(output_names)
    )
    return inputs + result_outputs


def _attention_vectors(value: AttentionVectors) -> dict[str, VectorPreset | str]:
    """One paint per q/k/v glyph, from whichever of the four forms was written.

    Keys are matched case-insensitively, because a figure that names its presets
    ``Q``, ``K``, ``V`` -- which is what the captions say -- should be able to hand
    that same mapping straight over.
    """

    if value is True:
        return dict(_QKV_RAMPS)
    if isinstance(value, (VectorPreset, str)):
        return {name: value for name in _QKV_PORTS}
    if not isinstance(value, Mapping):
        raise ValueError(
            f"vectors= takes True, one preset or ramp role, or a mapping keyed "
            f'{", ".join(_QKV_PORTS)}, not {type(value).__name__}'
        )
    given = {str(key).lower(): item for key, item in value.items()}
    unknown = sorted(set(given) - set(_QKV_PORTS))
    if unknown:
        raise ValueError(
            f'vectors= does not know the key(s) {", ".join(unknown)}; '
            f'an attention block reads {", ".join(_QKV_PORTS)}'
        )
    missing = [name for name in _QKV_PORTS if name not in given]
    if missing:
        raise ValueError(
            f'vectors= leaves {", ".join(missing)} unpainted; give every key, or one '
            "preset for all three"
        )
    return {name: given[name] for name in _QKV_PORTS}


def _attention_offsets(
    authored: tuple[PortSpec, ...],
    names: tuple[str, ...],
) -> dict[str, float]:
    """Where along the block's bottom edge each of ``names`` attaches.

    An authored ``ports=`` is the design -- it is the one way to say that this
    attention reads its value on the left, which is how the paper draws a
    cross-attention -- so its offsets win. Otherwise the component grammar's own
    fractions do, read from ``COMPONENTS`` rather than repeated here.
    """

    if authored:
        offsets = {port.name: port.offset for port in authored}
        missing = [name for name in names if name not in offsets]
        if missing:
            raise ValueError(
                f'the authored port table declares no {", ".join(missing)} port, so '
                "vectors= has nothing to hang those glyphs under"
            )
        return {name: offsets[name] for name in names}
    return dict(zip(names, component_port_offsets("attention", names), strict=True))


_GLYPH_CAPTION_SIDE = Side.WEST
"""Which side of its stack a Q/K/V caption stands on.

One side for all three, not the outer side of each: the lanes are cut to the same
width, so every stack has the same room on either side of it, and a row of
captions that all lean the same way reads as a convention while a mirrored pair
around a middle glyph reads as an accident. It is also the side with no
competition -- two captions meeting in one inter-lane gap would sit a few points
apart, each nearer the other glyph's stack than to its own.
"""


def _glyph_caption(lane: float, stack: float, style: LayoutStyle) -> _SideCaption | None:
    """The caption box that fits beside a ``stack``-wide glyph in a ``lane``.

    A lane is wider than the stack standing in it -- it is as wide as the port
    spacing it was cut from -- and that surplus, half of it on each side, is
    exactly the room a caption may use without reaching into the neighbouring
    lane. So the caption takes the half it stands in, less one
    ``caption_clearance`` of air against the cells, and the glyph reserves the
    same amount on its other side: the stack then sits dead centre of its lane
    with the words in the padding, and the whole glyph is precisely as wide as the
    lane it fills.

    ``None`` when that half-lane holds no more than the air itself, which is a
    lane too narrow for a caption beside it; the composite then keeps the caption
    under the stack, where it costs the feeds their straightness but is at least
    legible.
    """

    gap = style.caption_clearance.points
    reserve = max(0.0, lane / 2.0 - stack / 2.0) - gap
    if reserve <= 0.0:
        return None
    return _SideCaption(_GLYPH_CAPTION_SIDE, pt(reserve), pt(gap))


def _glyph_caption_gap(style_name: str) -> Length:
    """Air *under* one Q/K/V stack when its caption could not stand beside it.

    Only the narrow-lane fallback reaches this now (see ``_glyph_caption``); a
    caption with room beside its stack leaves the corridor below empty instead of
    reserving an arrival's worth of it.

    This is the corridor *below* the glyphs, and it is a token sum rather than a
    number chosen by eye. A glyph in this composite is fed from underneath, and a
    route arriving at a port needs ``arrival_clearance`` of straight run to turn
    its elbow and draw its arrowhead in; the caption then hangs one
    ``caption_clearance`` clear of that run. Anything less and the caption's own
    words close the only approach its glyph has -- which is a
    ``routing.net.no-stem`` error, not a cramped picture -- so the composite
    reserves it whether or not this particular figure feeds from below.

    It is why these captions sit further from their stack than a plain
    ``vector()`` caption does: a plain vector is wired from the side, and has no
    approach to protect.
    """

    style = STYLES.get(style_name) or LayoutStyle()
    return Length(style.arrival_clearance.points + style.caption_clearance.points)


def _vector_label_gap(style_name: str) -> Length:
    """The authored gap between a vector's cells and its caption.

    Composites lower to geometry-free semantics, so the token is resolved here,
    against the style the figure names; an unknown name is left to validation.
    """

    return (STYLES.get(style_name) or LayoutStyle()).vector_label_gap


def _reference(value: NodeHandle | PortRef | str, default_port: str) -> PortRef:
    if isinstance(value, PortRef):
        return value
    if isinstance(value, NodeHandle):
        return value.port(default_port)
    return PortRef.parse(value) if "." in value else PortRef(value, default_port)


def _label(value: str | tuple[TextRun, ...]) -> tuple[TextRun, ...]:
    if isinstance(value, str):
        return (TextRun(value),) if value else ()
    return value


def _length(value: Length | str | float | None) -> Length | None:
    return None if value is None else Length.parse(value)


def _extent(value: Extent | str | float | None) -> Extent | None:
    return None if value is None else parse_extent(value)


def _port_name(value: str | None) -> str:
    if value is None:
        return "output"
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return normalized if normalized and normalized[0].isalpha() else f"p-{normalized or 'output'}"
