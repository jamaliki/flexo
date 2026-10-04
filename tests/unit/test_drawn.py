"""Protein domain maps, trees, well plates, and timelines: drawn components."""

from __future__ import annotations

import itertools
import re

import pytest

import flexo
from flexo.compiler import compile_figure
from flexo.diagnostics import FlexoError
from flexo.drawn import picture
from flexo.lint import lint_compilation
from flexo.phylogeny import NewickError, parse_newick
from flexo.schema import validate_document
from flexo.serialization import figure_to_document, parse_figure
from flexo.themes import figure_style

ABL = [
    {"type": "domain", "label": "SH3", "start": 61, "end": 121},
    {"type": "domain", "label": "SH2", "start": 127, "end": 217},
    {"type": "domain", "label": "Kinase", "start": 242, "end": 493, "id": "kinase"},
    {"type": "region", "label": "Disordered", "start": 540, "end": 960},
    {"type": "mutation", "label": "T315I", "at": 315},
    {"type": "mutation", "label": "E255K", "at": 255},
    {"type": "phosphorylation", "label": "Y412", "at": 412},
    {"type": "disulfide", "start": 600, "end": 700},
]
NEWICK = "(((Human:0.08,Chimp:0.09)100:0.12,Gorilla:0.21)98:0.25,(Mouse:0.35,Rat:0.33):0.3);"


def _figure(theme: str = "paper") -> flexo.Figure:
    with flexo.Figure("bench", theme=theme) as figure:
        column = figure.root.column("all", gap=16)
        abl = column.protein("abl", 1130, ABL, label="ABL1")
        column.protein(
            "constructs",
            1130,
            ABL[:3],
            tracks=[
                {"label": "Full length"},
                {"label": "ΔSH3", "delete": "61-121"},
                {"label": "Kinase domain", "start": 229, "end": 500},
            ],
        )
        drug = column.block("drug", label="Imatinib", tone="Kinase")
        figure.connect(drug, abl.port("kinase"), head="inhibition")
        column.tree(
            "tree", NEWICK, support=True, clades=[{"tips": "Human, Gorilla", "label": "Apes"}]
        )
        column.tree("ring", NEWICK, layout="circular")
        column.wellplate(
            "plate",
            [{"wells": "A1-A12", "label": "Control"}, {"wells": "B-D", "label": "Drug"}],
        )
        column.timeline(
            "protocol",
            events=[{"at": 0, "label": "Seed"}, {"at": 2, "label": "Induce", "id": "induce"}],
            spans=[{"start": 2, "end": 5, "label": "Doxycycline"}],
            unit="day",
        )
    return figure


def _drawing(figure: flexo.Figure, node_id: str):
    node = next(node for node in figure.spec.nodes if node.id.endswith(node_id))
    return picture(node, figure_style(figure.spec))


def test_every_drawn_component_compiles_lint_clean_and_reads_back() -> None:
    figure = _figure()
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    document = figure_to_document(figure.spec)
    validate_document(document)
    assert parse_figure(document) == figure.spec


def test_a_protein_is_drawn_to_scale_and_its_domains_take_their_names_colours() -> None:
    figure = _figure()
    drawing = _drawing(figure, "abl")
    shapes = {shape.id: shape for shape in drawing.shapes}

    def left(identifier: str) -> float:
        return min(float(x) for x in re.findall(r"[ML] (-?[\d.]+)", shapes[identifier].d))

    chain = left("all.abl.chain")
    sh3, kinase = left("all.abl.feature1"), left("all.abl.feature3")
    # Residue 61 and residue 242 stand where the scale puts them.
    scale = (kinase - chain) / 241
    assert abs((sh3 - chain) / scale - 60) < 1.5
    svg = compile_figure(figure.spec).document.text

    def fill(identifier: str) -> str:
        found = re.search(rf'id="{re.escape(identifier)}"[^>]*data-flexo-fill="([^"]+)"', svg)
        assert found, identifier
        return found.group(1)

    # The kinase domain is one colour in both proteins and in the box toned "Kinase".
    assert fill("all.abl.feature3") == fill("all.constructs.track1.feature3")
    assert fill("all.abl.feature3") == fill("all.drug.body")
    # Every mutation shares a colour; a phosphorylation takes another.
    assert fill("all.abl.site1") == fill("all.abl.site2") != fill("all.abl.site3")


def test_a_deletion_breaks_the_chain_and_a_truncation_keeps_only_its_residues() -> None:
    drawing = _drawing(_figure(), "constructs")
    ids = {shape.id for shape in drawing.shapes}
    assert "all.constructs.track2.deletion1" in ids
    assert "all.constructs.track2.feature1" not in ids  # SH3 is deleted
    assert "all.constructs.track3.feature2" not in ids  # SH2 is before residue 229
    assert "all.constructs.track3.feature3" in ids


def test_newick_reads_names_lengths_support_and_quotes() -> None:
    root = parse_newick("((A:1,'B c':2)95:0.5,C_d:3);")
    assert [tip.name for tip in root.tips()] == ["A", "B c", "C d"]
    assert root.children[0].name == "95" and root.children[0].length == 0.5
    for bad in ("((A,B);", "(A,B));", "(A:x,B);", ""):
        with pytest.raises(NewickError):
            parse_newick(bad)


def test_a_tree_puts_tips_in_order_and_colours_a_clade() -> None:
    figure = _figure()
    drawing = _drawing(figure, "all.tree")
    tips = [words for words in drawing.words if ".tip" in words.id]
    assert [words.runs[0].text for words in tips] == ["Human", "Chimp", "Gorilla", "Mouse", "Rat"]
    assert [words.y for words in tips] == sorted(words.y for words in tips)
    coloured = {shape.tone for shape in drawing.shapes if shape.tone}
    assert coloured == {"Apes"}
    # A phylogram: Mouse, on the longer path, reaches further right than Human.
    x = {words.runs[0].text: words.x for words in tips}
    assert x["Mouse"] > x["Human"]
    assert any(words.id.endswith(".scale.label") for words in drawing.words)


def test_a_plate_fills_its_groups_and_leaves_the_rest_empty() -> None:
    drawing = _drawing(_figure(), "plate")
    paints = {shape.id: (shape.paint, shape.tone) for shape in drawing.shapes}
    assert paints["all.plate.A1"] == ("body", "Control")
    assert paints["all.plate.C7"] == ("body", "Drug")
    assert paints["all.plate.H12"][0] == "hollow"
    assert (
        sum(
            shape.id.startswith("all.plate.")
            and shape.id[10:11].isalpha()
            and shape.id[11:].isdigit()
            for shape in drawing.shapes
        )
        == 96
    )


def test_a_timeline_writes_its_times_and_stacks_its_spans() -> None:
    drawing = _drawing(_figure(), "protocol")
    times = [words.runs[0].text for words in drawing.words if ".tick" in words.id]
    assert times[0] == "Day 0" and "Day 5" in times
    ports = {port.name for port in drawing.ports}
    assert "induce" in ports


def test_timeline_spans_that_only_touch_share_a_lane() -> None:
    def lanes(spans: list[dict]) -> list[float]:
        with flexo.Figure("assay") as figure:
            figure.root.timeline("t", events=[{"at": 0}, {"at": 40}], spans=spans)
        drawing = _drawing(figure, "t")
        tops = {
            shape.id: float(re.match(r"M\s*[-\d.]+[ ,]+([-\d.]+)", shape.d).group(1))
            for shape in drawing.shapes
            if re.search(r"\.span\d+$", shape.id)
        }
        return [round(tops[key], 1) for key in sorted(tops)]

    # Lag, then the burst as it ends, then the plateau as that ends: one lane.
    touching = [
        {"start": 0, "end": 8, "label": "Lag"},
        {"start": 8, "end": 14},
        {"start": 14, "end": 40, "label": "Plateau"},
    ]
    assert len(set(lanes(touching))) == 1
    # A span too narrow for its words, its words under it: the next span still shares its lane.
    narrow = [
        {"start": 0, "end": 1, "label": "Excitation"},
        {"start": 1, "end": 10, "label": "Adaptation"},
        {"start": 10, "end": 40, "label": "Adapted"},
    ]
    assert len(set(lanes(narrow))) == 1
    # Spans that overlap are stacked.
    assert len(set(lanes([{"start": 0, "end": 10}, {"start": 5, "end": 20}]))) == 2


@pytest.mark.parametrize(
    ("make", "words"),
    [
        (
            lambda g: g.protein("p", 100, [{"type": "domain", "start": 50, "end": 200}]),
            "outside the protein",
        ),
        (
            lambda g: g.protein("p", 100, [{"type": "helicase", "start": 5, "end": 9}]),
            'no feature called "helicase"',
        ),
        (lambda g: g.protein("p", 100, tracks=[{"delete": "a-b"}]), "not a stretch"),
        (lambda g: g.tree("t", "((A,B);"), "does not read"),
        (lambda g: g.tree("t", "(A,B);", clades=[{"tips": "A, Z"}]), "no tip called 'Z'"),
        (lambda g: g.wellplate("w", [{"wells": "Q1"}]), "not on this plate"),
        (lambda g: g.wellplate("w", wells=100), "not a plate format"),
        (lambda g: g.timeline("t", spans=[{"start": 5, "end": 1}]), "before it starts"),
    ],
)
def test_a_wrong_drawing_says_what_is_wrong(make, words: str) -> None:
    with pytest.raises(FlexoError, match=re.escape(words)):
        with flexo.Figure("wrong") as figure:
            make(figure.root)
        compile_figure(figure.spec)


@pytest.mark.parametrize("theme", ["sketch", "dark", "tikz"])
def test_drawn_components_draw_in_every_theme(theme: str) -> None:
    compiled = compile_figure(_figure(theme).spec)
    assert 'id="all.abl.chain"' in compiled.document.text


UBIQUITIN = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
UBIQUITIN_DSSP = "CEEEEEETTSCEEEEEECTTSBHHHHHHHHHHHHCCCGGGEEEEETTEEECTTSBTTTTTCCTTCEEEEEEECCCC"


def test_dssp_reads_into_numbered_helices_strands_and_turns() -> None:
    from flexo.secondary import dssp_elements, numbered

    elements = numbered(dssp_elements("CHHHHCCEEEETTEEEC", 10), True)
    assert [(item.kind, item.start, item.end) for item in elements] == [
        ("helix", 11, 14),
        ("strand", 17, 20),
        ("turn", 21, 22),
        ("strand", 23, 25),
    ]
    assert ["".join(run.text for run in item.label) for item in elements] == [
        "\N{GREEK SMALL LETTER ALPHA}1",
        "\N{GREEK SMALL LETTER BETA}1",
        "",
        "\N{GREEK SMALL LETTER BETA}2",
    ]
    assert dssp_elements("HHX", 1) == "X"


def _ubiquitin(**options: object) -> flexo.Figure:
    with flexo.Figure("ubq") as figure:
        options.setdefault("secondary", UBIQUITIN_DSSP)
        figure.root.protein("ubq", 76, **options)  # type: ignore[arg-type]
    return figure


def test_secondary_structure_takes_the_chains_place_or_a_strip_under_it() -> None:
    alone = _drawing(_ubiquitin(), "ubq")
    ids = {shape.id for shape in alone.shapes}
    assert "ubq.chain" not in ids and "ubq.secondary.ss1" in ids
    kinds = {shape.id: shape.tone for shape in alone.shapes}
    assert "helix" in kinds.values() and "strand" in kinds.values()
    compiled = compile_figure(_ubiquitin().spec)
    assert not lint_compilation(compiled).diagnostics
    domain = [{"type": "domain", "label": "Ubiquitin-like", "start": 1, "end": 72}]
    with flexo.Figure("both") as figure:
        figure.root.protein("ubq", 76, domain, secondary=UBIQUITIN_DSSP)
    both = _drawing(figure, "ubq")
    chain_y = min(
        float(v) for v in re.findall(r"M [\d.]+ ([\d.]+)", _shape(both, "ubq.feature1").d)
    )
    strip_y = float(re.findall(r"M [\d.]+ ([\d.]+)", _shape(both, "ubq.secondary.loop1").d)[0])
    assert strip_y > chain_y


def _shape(drawing, identifier: str):
    return next(shape for shape in drawing.shapes if shape.id == identifier)


def test_the_sequence_is_written_only_where_a_letter_fits_a_residue() -> None:
    close = _drawing(_ubiquitin(sequence=UBIQUITIN, scale=6.5), "ubq")
    letters = [words for words in close.words if ".residue" in words.id]
    assert "".join(words.runs[0].text for words in letters) == UBIQUITIN
    far = _drawing(_ubiquitin(sequence=UBIQUITIN, scale=1.0), "ubq")
    assert not [words for words in far.words if ".residue" in words.id]


def test_a_track_can_show_a_close_view_of_a_segment() -> None:
    drawing = _drawing(
        _ubiquitin(sequence=UBIQUITIN, scale=8.0, tracks=[{"start": 20, "end": 45}]), "ubq"
    )
    ticks = [
        words.runs[0].text
        for words in drawing.words
        if words.id.endswith(".label") and ".tick" in words.id
    ]
    assert ticks[0] == "20" and ticks[-1] == "45"
    assert drawing.size.width < 26 * 8.0 + 80


@pytest.mark.parametrize(
    ("options", "words"),
    [
        ({"secondary": "HHHXHH"}, '"X" is not a DSSP letter'),
        ({"secondary": "H" * 90}, "outside the protein"),
    ],
)
def test_a_wrong_secondary_structure_says_what_is_wrong(options: dict, words: str) -> None:
    with pytest.raises(FlexoError, match=re.escape(words)):
        compile_figure(_ubiquitin(**options).spec)


def test_a_residue_letter_sits_over_its_own_residue() -> None:
    drawing = _drawing(
        _ubiquitin(sequence=UBIQUITIN, scale=8.0, tracks=[{"start": 20, "end": 45}]), "ubq"
    )
    axis = _shape(drawing, "ubq.axis")
    left = float(re.findall(r"M (-?[\d.]+)", axis.d)[0])
    letters = {words.id: words for words in drawing.words if ".residue" in words.id}
    # Residue 20 is the first of the view: its letter centred on the first 8 points.
    assert abs(letters["ubq.secondary.residue20"].x - (left + 4.0)) < 0.01
    assert letters["ubq.secondary.residue20"].runs[0].text == UBIQUITIN[19]


# -- regressions from review ------------------------------------------------------------


def test_a_domain_name_survives_a_deletion_through_it() -> None:
    with flexo.Figure("deleted") as figure:
        figure.root.protein(
            "p",
            400,
            [{"type": "domain", "label": "Kinase domain", "start": 100, "end": 300}],
            tracks=[{"label": "Δ", "delete": "130-290"}],
        )
    drawing = _drawing(figure, "p")
    assert any(words.id.endswith("feature1.label") for words in drawing.words)


def test_a_construct_is_as_wide_as_its_title() -> None:
    from flexo.genetics import construct_drawing

    with flexo.Figure("title") as figure:
        figure.root.construct(
            "c", [{"type": "promoter"}], label="A very long construct title that goes on and on"
        )
    node = figure.spec.nodes[0]
    drawing = construct_drawing(node, figure_style(figure.spec))
    title = next(words for words in drawing.words if words.id == "c.label")
    assert drawing.size.width >= title.x + title.metrics.width


def test_crowded_timeline_names_stay_inside_the_picture() -> None:
    with flexo.Figure("crowded") as figure:
        figure.root.timeline(
            "t",
            events=[
                {"at": 0, "label": "Transfect cells now"},
                {"at": 0.2, "label": "Induce expression now"},
                {"at": 10, "label": "Harvest"},
            ],
        )
    drawing = _drawing(figure, "t")
    for words in drawing.words:
        left = words.x - (words.metrics.width / 2.0 if words.anchor == "middle" else 0.0)
        assert left >= 0.0, words.id
        assert left + words.metrics.width <= drawing.size.width + 0.01, words.id


def test_clade_tips_may_be_written_as_the_newick_writes_them() -> None:
    with flexo.Figure("apes") as figure:
        figure.root.tree(
            "t",
            "((Homo_sapiens,Pan_troglodytes),Mus_musculus);",
            clades=[{"tips": "Homo_sapiens, Pan_troglodytes", "label": "Apes"}],
        )
    assert not lint_compilation(compile_figure(figure.spec)).diagnostics


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda g: g.protein("p", 400, tracks=[{"start": 300, "end": 100}]), "protein.track.range"),
        (lambda g: g.timeline("t", events=[{"at": 0, "label": "a", "id": "input"}]), "timeline.id"),
        (
            lambda g: g.timeline("t", events=[{"at": 0, "id": "seed"}, {"at": 1, "id": "seed"}]),
            "timeline.id",
        ),
        (
            lambda g: g.protein("p", 100, [{"type": "domain", "start": 1, "end": 9, "id": "1st"}]),
            "protein.id",
        ),
    ],
)
def test_a_bad_range_or_id_is_a_diagnostic(make, code: str) -> None:
    with pytest.raises(FlexoError) as caught:
        with flexo.Figure("bad") as figure:
            make(figure.root)
        compile_figure(figure.spec)
    assert caught.value.diagnostics[0].code == code


def test_a_feature_all_the_way_round_a_plasmid_is_a_ring() -> None:
    from flexo.genetics import plasmid_drawing

    with flexo.Figure("ring") as figure:
        figure.root.plasmid(
            "p", 5421, [{"type": "region", "label": "backbone", "start": 1, "end": 5421}]
        )
    shapes = {
        s.id: s for s in plasmid_drawing(figure.spec.nodes[0], figure_style(figure.spec)).shapes
    }
    ring = shapes["p.feature1"].d
    assert ring.count("M") == 2 and ring.count("A") == 4


# -- limitations lifted ---------------------------------------------------------------


def test_crowded_sites_fan_out_at_one_height() -> None:
    with flexo.Figure("crowded") as figure:
        figure.root.protein(
            "p",
            400,
            [{"type": "mutation", "label": f"X{at}", "at": at} for at in (100, 101, 102, 103)],
        )
    drawing = _drawing(figure, "p")
    heads = [shape for shape in drawing.shapes if re.fullmatch(r"p\.site\d", shape.id)]
    centres = sorted(
        (float(x) + 0.0, float(y))
        for x, y in (re.findall(r"M (-?[\d.]+) (-?[\d.]+)", shape.d)[0] for shape in heads)
    )
    assert len({round(y, 3) for _, y in centres}) == 1  # one height
    assert all(b[0] - a[0] > 1.0 for a, b in itertools.pairwise(centres))  # apart


def test_a_track_with_an_id_is_a_port_at_its_chain() -> None:
    with flexo.Figure("tracks") as figure:
        row = figure.root.row("r", gap=40)
        nanobody = row.block("nb", label="Nanobody")
        protein = row.protein(
            "p",
            500,
            [{"type": "domain", "label": "Kinase", "start": 100, "end": 300}],
            tracks=[{"label": "Full"}, {"label": "ΔN", "start": 90, "id": "short"}],
        )
        figure.connect(nanobody, protein.port("short"))
    compiled = compile_figure(figure.spec)
    assert not lint_compilation(compiled).diagnostics
    ports = {port.name: port for port in compiled.measured.node("r.p").spec.ports}
    assert ports["short"].side.value == "west" and ports["short.end"].side.value == "east"
    assert ports["short"].offset > ports["input"].offset  # the second track is lower


def test_a_construct_drawn_to_scale_sets_parts_by_their_base_pairs() -> None:
    from flexo.genetics import construct_drawing

    parts = [
        {"type": "promoter", "label": "pTet", "bp": 55},
        {"type": "cds", "label": "GFP", "bp": 720},
        {"type": "spacer", "bp": 300},
        {"type": "cds", "label": "TetR", "bp": 624},
    ]
    with flexo.Figure("scaled") as figure:
        figure.root.construct("c", parts, scale=0.1)
    drawing = construct_drawing(figure.spec.nodes[0], figure_style(figure.spec))
    shapes = {shape.id: shape for shape in drawing.shapes}

    def span(identifier: str) -> float:
        xs = [float(x) for x in re.findall(r"[ML] (-?[\d.]+)", shapes[identifier].d)]
        return max(xs) - min(xs)

    assert abs(span("c.part2") - 72.0) < 0.5 and abs(span("c.part4") - 62.4) < 0.5
    assert any(words.id == "c.tick1699.label" for words in drawing.words)
    with pytest.raises(FlexoError, match="needs each part's length"):
        with flexo.Figure("unscaled") as broken:
            broken.root.construct("c", [{"type": "cds", "label": "GFP"}], scale=0.1)
        compile_figure(broken.spec)


# -- found rebuilding real figures ----------------------------------------------------


def test_a_domain_name_keeps_clear_of_a_motif_inside_it() -> None:
    with flexo.Figure("capsid") as figure:
        figure.root.protein(
            "ca",
            231,
            [
                {"type": "domain", "label": "N-terminal domain", "start": 1, "end": 145},
                {"type": "motif", "label": "CypA loop", "start": 85, "end": 93},
            ],
            scale=1.9,
        )
    drawing = _drawing(figure, "ca")
    name = next(words for words in drawing.words if words.id == "ca.feature1.label")
    loop = _shape(drawing, "ca.feature2")
    xs = [float(x) for x in re.findall(r"[ML] (-?[\d.]+)", loop.d)]
    left, right = name.x - name.metrics.width / 2.0, name.x + name.metrics.width / 2.0
    assert right < min(xs) or left > max(xs)


def test_a_timeline_of_whole_days_ticks_whole_days() -> None:
    with flexo.Figure("days") as figure:
        figure.root.timeline("t", events=[{"at": 0}, {"at": 3}], unit="day")
    ticks = [words.runs[0].text for words in _drawing(figure, "t").words if ".tick" in words.id]
    assert ticks == ["Day 0", "Day 1", "Day 2", "Day 3"]


def test_a_domain_s_name_is_inside_it_whenever_it_fits_and_its_domains_names_are_one_size() -> None:
    from flexo.builder import Figure

    domains = [
        {"type": "domain", "label": "NTD · DNA binding", "start": 1, "end": 92},
        {"type": "domain", "label": "CTD · dimerisation", "start": 132, "end": 236},
    ]
    with Figure("repressor") as figure:
        figure.root.protein("ci", 236, domains, label="λ repressor (CI)")
    svg = compile_figure(figure.spec).document.text
    names = {
        identifier: (float(y), size)
        for identifier, y, size in re.findall(
            r'<text id="ci\.(feature\d)\.label"[^>]* y="([\d.]+)"[^>]*font-size="([\d.]+)"', svg
        )
    }
    # The narrower domain's name fits inside only at the small size: both are set inside, at
    # it -- neither under an empty box, nor one larger than the other.
    assert set(names) == {"feature1", "feature2"}
    (first_y, first_size), (second_y, second_size) = names["feature1"], names["feature2"]
    assert first_y == pytest.approx(second_y) and first_size == second_size


def test_short_domains_names_sit_near_them_in_rows_not_led_to_from_afar() -> None:
    from flexo.builder import Figure

    domains = [
        {"type": "domain", "label": "Signal peptide", "start": 1, "end": 15},
        {"type": "domain", "label": "Activation peptide", "start": 16, "end": 23},
        {"type": "domain", "label": "Serine protease domain", "start": 24, "end": 247},
    ]
    with Figure("prss1") as figure:
        figure.root.protein("p", 247, domains, label="PRSS1")
    svg = compile_figure(figure.spec).document.text
    # Each name too long for its domain is under it, on a row of its own where the one
    # before it is in the way -- not pushed along and led back to by a line under the chain.
    assert 'p.feature1.label.leader' not in svg and 'p.feature2.label.leader' not in svg
    rows = {
        name: float(y)
        for name, y in re.findall(r'<text id="p\.(feature[12])\.label"[^>]* y="([\d.]+)"', svg)
    }
    assert rows["feature2"] > rows["feature1"]


def test_a_drawn_things_words_are_drawn_as_read_its_name_then_its_parts_in_order() -> None:
    from flexo.builder import Figure

    features = [
        {"type": "domain", "label": "P4 kinase", "start": 355, "end": 507},
        {"type": "domain", "label": "P1", "start": 1, "end": 134},
        {"type": "domain", "label": "P2", "start": 159, "end": 227},
        {"type": "phosphorylation", "label": "His48", "at": 48},
    ]
    with Figure("chea") as figure:
        figure.root.protein("p", 654, features, label="CheA")
    svg = compile_figure(figure.spec).document.text
    # A PDF's tags, a slide program and a screen reader read words in the order drawn: its
    # name first, then its parts from the N-terminus on (a site among its domains), then
    # the residue numbers -- not the widest domain first, nor its name last.
    said = re.findall(r'<text id="p(?:\.[\w.]+)?"[^>]*>(?:<tspan[^>]*>)?([^<]+)<', svg)
    assert said[:5] == ["CheA", "P1", "His48", "P2", "P4 kinase"]
    # Drawn under nothing, as nothing is drawn where it is; the domains from the N-terminus.
    assert svg.index('id="p.label"') < svg.index('id="p.chain"')
    shapes = re.findall(r'<path id="p\.(feature\d)"', svg)
    assert shapes == ["feature2", "feature3", "feature1"]
