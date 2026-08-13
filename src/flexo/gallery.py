"""Bundled semantic figures used as documentation and acceptance fixtures."""

from __future__ import annotations

from flexo.builder import Figure, GroupBuilder, NodeHandle
from flexo.geometry import Side
from flexo.ir.semantic import FigureSpec, LayoutSpec, PortSpec, TextRun
from flexo.style import STYLES
from flexo.units import Length, pt


def vertical_slice() -> FigureSpec:
    with Figure("vertical-slice", width="double-column") as figure:  # noqa: SIM117
        with figure.module(
            "cryo",
            label="Cryo-EM information flow",
            gap="12pt",
            justify="center",
        ) as module:
            with module.column(
                "branches",
                gap="12pt",
                padding=0,
                align="end",
                role="layout",
            ) as branches:
                with branches.row(
                    "feature-path",
                    gap="12pt",
                    padding=0,
                    role="layout",
                ) as feature_path:
                    with feature_path.column(
                        "inputs",
                        gap="8pt",
                        padding=0,
                        role="layout",
                    ) as inputs:
                        nodes = inputs.feature_strip("nodes", label="Node features", cells=7)
                        distances = inputs.feature_strip("distances", label="Distances", cells=5)
                    combined = feature_path.concat("concat", inputs=[nodes, distances])
                    projection = feature_path.mlp(
                        "projection",
                        label="Feature MLP",
                        input=combined,
                    )
                    q, v = feature_path.channels(
                        "query-value",
                        labels=["Q", "V"],
                        input=projection,
                    )
                with branches.row(
                    "edge-path",
                    gap="12pt",
                    padding=0,
                    role="layout",
                ) as edge_path:
                    neighbourhoods = edge_path.inset(
                        "neighbourhoods",
                        label="Edge neighbourhoods",
                        width="82pt",
                        height="48pt",
                    )
                    keys = edge_path.cnn("keys", label="Edge CNN", input=neighbourhoods)
                    (k,) = edge_path.channels("key", labels=["K"], input=keys)
            attended = module.attention("attention", q=q, k=k, v=v)
            prediction = module.prediction("prediction", input=attended)
            module.residual(
                nodes,
                prediction,
                id="cryo.residual",
                lane="cryo-bottom",
            )
    return figure.spec


_NORTH_TO_SOUTH = (
    PortSpec("input", Side.NORTH, adaptive=True),
    PortSpec("output", Side.SOUTH, adaptive=True),
)
_SINK_NORTH = (PortSpec("input", Side.NORTH, adaptive=True),)

_ATTENTION_LABEL = (
    TextRun("softmax(QK"),
    TextRun("T", baseline_shift="super"),
    TextRun(")V"),
)
"""Scaled dot-product attention, written the way the reference panel writes it."""

_IPA_LABEL = (
    TextRun("softmax(−ΣD"),  # noqa: RUF001
    TextRun("q", baseline_shift="sub"),
    TextRun(")V"),
)
"""Invariant point attention: distances to the query points replace QK^T."""

_VECTOR_CELLS = 3
"""Cells in every vector glyph of this figure."""

_MODULE_STYLE = STYLES["paper"]

_BOX_HEIGHT = pt(
    _VECTOR_CELLS * _MODULE_STYLE.vector_cell.points
    + (_VECTOR_CELLS - 1) * _MODULE_STYLE.vector_cell_gap.points
)
"""Height of every box inside a module: exactly one vector's cell stack.

Module interiors are grids whose cells align to the top, so a box as tall as a
cell stack puts its side ports at the same y as the vector's middle cell. Every
run along a module row is then straight by construction, with no port adaptation
left to absorb a few points of mismatch.
"""

_INSET_HEIGHT = "42pt"
"""Height of the scientific insets that open the cryo-EM module."""

_MODULE_GAP = "20pt"
"""Gap on both axes of a module grid: one rail corridor fits in one gap."""

_FORMULA_LANE = "20pt"
"""Empty column that lengthens the attention arrow until its formula fits above it."""

_EDGE_LABEL_LANE = "12pt"
"""Empty column that widens the one boundary an edge label (ESM-1b) has to share."""


def _cell(grid: GroupBuilder, id: str, width: Length | str | float = 0.0) -> None:
    """Hold one grid cell open: a zero-height spacer, optionally a lane wide.

    Grids place their children row by row, so an empty cell has to be authored.
    A ``width`` turns that cell into a reserved corridor: grid gaps are uniform,
    and only two boundaries per module need more than one.
    """

    grid.node(id, "spacer", width=width, height=0.0)


def _module_grid(band: GroupBuilder, id: str, label: str, columns: int) -> GroupBuilder:
    """A module container laid out as an aligned grid of rows and columns.

    Rows are chains that read left to right; columns line the chains up so a
    reader compares them vertically. ``align="start"`` puts every cell's content
    at the top of its row, which is what makes boxes and vector cell stacks share
    a port y (see ``_BOX_HEIGHT``).
    """

    return band.group(
        id,
        label=label,
        layout="grid",
        columns=columns,
        gap=_MODULE_GAP,
        align="start",
        role="module",
    )


def _cryo_module(band: GroupBuilder) -> tuple[NodeHandle, NodeHandle, NodeHandle]:
    """The cryo-EM module: returns (node features, feature update, predictions).

    Seven columns -- inputs, encoders, feature vectors, formula lane, attended
    value, readout MLPs, output vectors -- over three rows::

        edge rectangles -> CNN -> K,V ......... | predict MLP -> predictions
        node features   -> MLP -> Q --------> attended -> update MLP -> update
        centre cube     -> CNN ---------------> C

    The row order is what keeps the module free of crossings. The centre-cube
    embedding C joins the update input *after* attention, so its row sits below
    the attention rows: its long run east then passes under the attention rail
    instead of through it. The prediction path leaves the attended value's north
    port -- its label hangs below the cells, so a south departure would cross its
    own caption -- and turns east above the fan-in rail.
    """

    figure = band.figure
    with _module_grid(band, "cryo", "Cryo-EM module", 7) as module:
        rects = module.inset("rectangles", label="Edge\nrectangles", height=_INSET_HEIGHT)
        edge_cnn = module.cnn("edge-cnn", label="CNN", input=rects, height=_BOX_HEIGHT)
        kv = module.vector("kv", label="K, V", ramp="ramp-kv", columns=2, input=edge_cnn)
        _cell(module, "formula-lane", _FORMULA_LANE)
        _cell(module, "attention-lane")
        predict = module.mlp("predict", label="MLP", height=_BOX_HEIGHT)
        predictions = module.vector(
            "predictions",
            label="Residue\npredictions",
            ramp="ramp-output",
            input=predict,
        )
        nodes = module.vector("nodes", label="Node features", ramp="ramp-node")
        q_mlp = module.mlp("q-mlp", label="MLP", input=nodes, height=_BOX_HEIGHT)
        q = module.vector("q", label="Q", ramp="ramp-q", input=q_mlp)
        _cell(module, "formula-lane-2")
        attended = module.vector("attended", label="Attended\nvalue", ramp="ramp-attended")
        update = module.mlp("update", label="MLP", height=_BOX_HEIGHT)
        out = module.vector("out", label="Feature\nupdate", ramp="ramp-output", input=update)
        cube = module.inset("cube", label="Centre cube", height=_INSET_HEIGHT)
        cube_cnn = module.cnn("cube-cnn", label="CNN", input=cube, height=_BOX_HEIGHT)
        _cell(module, "features-lane")
        _cell(module, "formula-lane-3")
        context = module.vector("c", label="C", ramp="ramp-embedding", input=cube_cnn)
        _cell(module, "readout-lane")
        _cell(module, "outputs-lane")
        module.connect(attended.north, predict)
        figure.merge(
            sinks=[q, kv],
            dst=attended,
            id=f"{module.id}.attention",
            label=_ATTENTION_LABEL,
        )
        figure.merge(sinks=[attended, context], dst=update, id=f"{module.id}.context")
    return nodes, out, predictions


def _sequence_module(band: GroupBuilder) -> tuple[NodeHandle, NodeHandle, NodeHandle]:
    """The sequence module: returns (node features, feature update, predictions).

    Two rows, the language-model branch above the node branch::

        Sequence -ESM-1b-> embedding -> MLP -> K,V ..... | predict MLP -> predictions
        node features ----------------> MLP -> Q ---> attended -> update MLP -> update

    With no third input to gather, the attended value fans out as a net: one
    trunk east, one rail, and a branch into each readout MLP's west centre.
    """

    figure = band.figure
    with _module_grid(band, "sequence", "Sequence module", 9) as module:
        tokens = module.sequence("tokens", label="Sequence", tokens=6)
        _cell(module, "esm-lane", _EDGE_LABEL_LANE)
        embedding = module.vector(
            "embedding",
            label="Sequence\nembedding",
            ramp="ramp-embedding",
        )
        kv_mlp = module.mlp("kv-mlp", label="MLP", input=embedding, height=_BOX_HEIGHT)
        kv = module.vector("kv", label="K, V", ramp="ramp-kv", columns=2, input=kv_mlp)
        _cell(module, "formula-lane", _FORMULA_LANE)
        _cell(module, "attention-lane")
        predict = module.mlp("predict", label="MLP", height=_BOX_HEIGHT)
        predictions = module.vector(
            "predictions",
            label="Residue\npredictions",
            ramp="ramp-output",
            input=predict,
        )
        nodes = module.vector("nodes", label="Node features", ramp="ramp-node")
        _cell(module, "esm-lane-2")
        _cell(module, "embedding-lane")
        q_mlp = module.mlp("q-mlp", label="MLP", input=nodes, height=_BOX_HEIGHT)
        q = module.vector("q", label="Q", ramp="ramp-q", input=q_mlp)
        _cell(module, "formula-lane-2")
        attended = module.vector("attended", label="Attended\nvalue", ramp="ramp-attended")
        update = module.mlp("update", label="MLP", height=_BOX_HEIGHT)
        out = module.vector("out", label="Feature\nupdate", ramp="ramp-output", input=update)
        module.connect(tokens, embedding, label="ESM-1b")
        figure.merge(
            sinks=[q, kv],
            dst=attended,
            id=f"{module.id}.attention",
            label=_ATTENTION_LABEL,
        )
        figure.net(src=attended, sinks=[update, predict], id=f"{module.id}.readout")
    return nodes, out, predictions


def _ipa_module(band: GroupBuilder) -> tuple[NodeHandle, NodeHandle]:
    """The invariant point attention module: returns (node features, update).

    Two rows; the geometry inset sits under the vectors it scores::

        node features -> MLP -> Q points, V ---> attended -> update MLP -> update
                                distances .....^
    """

    figure = band.figure
    with _module_grid(band, "ipa", "IPA module", 7) as module:
        nodes = module.vector("nodes", label="Node features", ramp="ramp-node")
        qv_mlp = module.mlp("qv-mlp", label="MLP", input=nodes, height=_BOX_HEIGHT)
        qv = module.vector(
            "qv",
            label="Q points, V",
            ramp="ramp-q",
            columns=2,
            input=qv_mlp,
        )
        _cell(module, "formula-lane", _FORMULA_LANE)
        attended = module.vector("attended", label="Attended\nvalue", ramp="ramp-attended")
        update = module.mlp("update", label="MLP", input=attended, height=_BOX_HEIGHT)
        out = module.vector("out", label="Feature\nupdate", ramp="ramp-output", input=update)
        _cell(module, "inputs-lane")
        _cell(module, "encoders-lane")
        graph = module.graph(
            "graph",
            label="Distances to Q points",
            ports=(
                PortSpec("input", Side.WEST, adaptive=True),
                # The graph shares its column with the Q points vector, so the
                # climb into the merge rail has to leave east of that vector and
                # of its caption rather than from the side centre.
                PortSpec("output", Side.NORTH, 0.75),
            ),
        )
        _cell(module, "formula-lane-2")
        _cell(module, "attended-lane")
        _cell(module, "readout-lane")
        _cell(module, "outputs-lane")
        figure.merge(
            sinks=[qv, graph],
            dst=attended,
            id=f"{module.id}.attention",
            label=_IPA_LABEL,
        )
    return nodes, out


_SPINE_WIDTH = "72pt"
"""Fixed width of every band's spine cell, so the Add/LN blocks share a column."""

_BAND_GAP = "24pt"
"""Horizontal gutter between a band's spine cell and its module."""

_HEADS_CORRIDOR = "14pt"
"""Height of the spacer row that opens the fan-out corridor above the heads."""

_RECYCLE_LANE = "20pt"
"""Width of the margin lane west of the spine that carries the recycle rail."""


def _band(root: GroupBuilder, id: str) -> GroupBuilder:
    """One band row: margin lane, spine cell, then the content the spine feeds.

    Every band opens with the same zero-height lane spacer, so the recycle rail
    has an empty column west of the spine to climb and the Add/LN blocks still
    share one x.
    """

    band = root.row(id, gap=_BAND_GAP, padding=0, align="start", role="layout")
    band.node("recycle-lane", "spacer", width=_RECYCLE_LANE, height=0.0)
    return band


def _spine_slot(band: GroupBuilder, id: str = "spine") -> NodeHandle:
    """Hold the spine column open in a band that carries no spine block."""

    return band.node(id, "spacer", width=_SPINE_WIDTH, height=0.0)


def _feedback_lane(band: GroupBuilder) -> str:
    """Open a routing lane east of the module and name it for ``lane=`` hints.

    The zero-size spacer carries the band's right edge one gutter past the
    module, so ``<band>-right`` resolves to a column in open canvas: the
    residual rail drops south there instead of inside the module, where the
    container fill would hide it.
    """

    band.node("feedback-lane", "spacer", width=0.0, height=0.0)
    return f"{band.id}-right"


def _add_norm(strip: GroupBuilder, id: str) -> NodeHandle:
    """One residual normalization block: skip enters north, feedback east."""

    return strip.node(
        id,
        "add-norm",
        label="Add LN",
        width=_SPINE_WIDTH,
        ports=(
            PortSpec("skip", Side.NORTH, adaptive=True),
            PortSpec("feedback", Side.EAST, adaptive=True),
            PortSpec("output", Side.SOUTH, adaptive=True),
        ),
    )


def modelangelo_gnn() -> FigureSpec:
    """An original figure with the structure of the ModelAngelo GNN panel.

    Authored as **band rows**, alternating module bands with thin strip bands::

        band1  [ lane | previous | Cryo-EM module   | feedback lane ]
        strip1 [ lane | addln1   ]
        band2  [ lane | spine    | Sequence module  | feedback lane ]
        strip2 [ lane | addln2   ]
        band3  [ lane | spine    | IPA module       | feedback lane ]
        strip3 [ lane | addln3   ]
        band4  [ lane | spine    | corridor + heads row ]

    Every band opens with the same margin lane and the same fixed-width spine
    cell, so the Add/LN blocks share one x and the recycle rail has an empty
    column to climb. Each Add/LN owning the strip *between* its modules is what
    makes its feedback rail read correctly: east out of the module's output
    vector, south in the lane just past the module, west along the strip, into
    the east feedback port -- always below the module it normalizes. The corridor
    above the heads row is a height-only spacer rather than padding, so the canvas
    ends at the content plus the ordinary margin on every side.

    Inside a module the language is **vector glyphs and formula arrows** (R20):
    every feature value is a labelled cell stack in its own colour ramp, boxes
    take one arrow per side centre, and attention is a merge net captioned
    ``softmax(QK^T)V`` above the horizontal run it labels rather than a matrix
    component. Each module is a grid, so its chains align into rows a reader can
    compare and into columns that share an x; ``_BOX_HEIGHT`` ties the boxes to
    the cell stacks, which is what makes those rows come out straight.
    """

    with Figure(
        "modelangelo-gnn",
        width="presentation",
        layout=LayoutSpec("column", gap=pt(20.0), align="start", justify="start"),
    ) as figure:
        root = figure.root
        with _band(root, "band1") as band:
            previous = band.node(
                "previous",
                "block",
                label="Previous layer",
                width=_SPINE_WIDTH,
                ports=(
                    PortSpec("recycle", Side.WEST),
                    PortSpec("output", Side.SOUTH, adaptive=True),
                ),
            )
            cryo_nodes, cryo_update, cryo_prediction = _cryo_module(band)
            cryo_lane = _feedback_lane(band)
        with _band(root, "strip1") as strip:
            addln1 = _add_norm(strip, "addln1")
        with _band(root, "band2") as band:
            _spine_slot(band)
            seq_nodes, seq_update, seq_prediction = _sequence_module(band)
            seq_lane = _feedback_lane(band)
        with _band(root, "strip2") as strip:
            addln2 = _add_norm(strip, "addln2")
        with _band(root, "band3") as band:
            _spine_slot(band)
            ipa_nodes, ipa_update = _ipa_module(band)
            ipa_lane = _feedback_lane(band)
        with _band(root, "strip3") as strip:
            addln3 = _add_norm(strip, "addln3")
        with _band(root, "band4") as band:
            _spine_slot(band)
            with band.column(
                "heads",
                gap=0,
                padding=0,
                align="start",
                role="layout",
            ) as heads_stack:
                heads_stack.node(
                    "corridor",
                    "spacer",
                    width=0.0,
                    height=_HEADS_CORRIDOR,
                )
                with heads_stack.row(
                    "row",
                    gap="18pt",
                    padding=0,
                    align="start",
                    role="layout",
                ) as heads:
                    head_mlps = []
                    with heads.column(
                        "node-features",
                        gap="12pt",
                        padding=0,
                        role="layout",
                    ) as head:
                        mlp = head.node("mlp", "mlp", label="MLP", ports=_NORTH_TO_SOUTH)
                        # The recycled features are a feature value, so this head
                        # ends in a vector glyph like every other one in the
                        # figure. Its west centre carries the recycle rail; the
                        # port is named "input" because a vector's four ports are
                        # its four side centres, whichever way a rail uses them.
                        recycled = head.vector(
                            "out",
                            label="Node features",
                            ramp="ramp-node",
                            cells=_VECTOR_CELLS,
                        )
                        head.connect(mlp, recycled.north)
                        head_mlps.append(mlp)
                    for head_id, head_label in (
                        ("shifts", "N, Ca, C shifts"),
                        ("torsions", "Torsion angles"),
                        ("confidence", "Confidence"),
                    ):
                        with heads.column(
                            head_id,
                            gap="12pt",
                            padding=0,
                            role="layout",
                        ) as head:
                            mlp = head.node(
                                "mlp", "mlp", label="MLP", ports=_NORTH_TO_SOUTH
                            )
                            sink = head.node(
                                "out",
                                "block",
                                label=head_label,
                                ports=_SINK_NORTH,
                            )
                            head.connect(mlp, sink)
                            head_mlps.append(mlp)
                    with heads.column(
                        "average",
                        gap="12pt",
                        padding=0,
                        role="layout",
                    ) as average:
                        average_block = average.node(
                            "block",
                            "block",
                            label="Average",
                            ports=_NORTH_TO_SOUTH,
                        )
                        residue_out = average.vector(
                            "out",
                            label="Residue\npredictions",
                            ramp="ramp-output",
                            cells=_VECTOR_CELLS,
                        )
                        average.connect(average_block, residue_out.north)

        figure.net(
            src=previous,
            sinks=[cryo_nodes, addln1.port("skip")],
            id="skip.previous",
        )
        root.residual(
            cryo_update,
            addln1.port("feedback"),
            id="feedback.cryo",
            lane=cryo_lane,
        )
        figure.net(
            src=addln1,
            sinks=[seq_nodes, addln2.port("skip")],
            id="skip.cryo",
        )
        root.residual(
            seq_update,
            addln2.port("feedback"),
            id="feedback.sequence",
            lane=seq_lane,
        )
        figure.net(
            src=addln2,
            sinks=[ipa_nodes, addln3.port("skip")],
            id="skip.sequence",
        )
        root.residual(
            ipa_update,
            addln3.port("feedback"),
            id="feedback.ipa",
            lane=ipa_lane,
        )
        figure.net(
            src=addln3,
            sinks=list(head_mlps),
            id="heads.fan-out",
        )
        root.residual(
            recycled.input,
            previous.port("recycle"),
            id="recycle.node-features",
        )
        figure.merge(
            sinks=[cryo_prediction, seq_prediction],
            dst=average_block,
            rail="east",
            id="predictions.merge",
        )
    return figure.spec


GALLERY = {
    "vertical-slice": vertical_slice,
    "modelangelo-gnn": modelangelo_gnn,
}


def gallery_figure(name: str) -> FigureSpec:
    try:
        return GALLERY[name]()
    except KeyError as error:
        valid = ", ".join(GALLERY)
        raise ValueError(f'unknown gallery figure "{name}"; valid names: {valid}') from error
