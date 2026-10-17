"""Figures in the studio: a figure file edited as its YAML, drawn as it changes.

The document the page edits is ``{"text": ...}``, the file's own words, so its
comments and order survive saving. The page shows the figure's parts (nodes,
groups, edges) beside the text, and selecting one marks it in the drawing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from flexo.studio import Drawing, Message, Page

NEW_FIGURE = """\
# A figure: its shapes (nodes), then the lines between them (edges).
figure:
  id: figure
  style: paper
nodes:
- id: shape
"""
"""A new figure file: one shape with no words yet, as a new figure on a slide starts. The
editor shows what it is, faintly, until its words are typed; nothing is drawn for it."""

SAMPLE_FIGURE = """\
# A figure: its shapes (nodes), then the lines between them (edges).
figure:
  id: figure
  style: paper
nodes:
- id: x
  kind: text
  label: Input $x$
- id: encoder
  label: Encoder
  properties:
    tone: encoder
- id: y
  kind: text
  label: Output $y$
edges:
- from: x
  to: encoder
- from: encoder
  to: y
"""
"""A small figure to try things on: an input, an encoder and an output."""


GUIDE = """\
A flexo figure file: YAML naming what the figure is, not where things go -- flexo lays it out
and routes every line.

figure: {id, style (a theme: paper, tikz, dark, sketch, ... or a theme file), palette, width
  (single-column, double-column, or a length: 89mm for a column of Nature's, 183mm for two;
  90mm, 144mm and 184mm are Science's one, one and a half, and two),
  height (a length, for a page of a fixed size: 210mm x 297mm is A4; left out, the page is as
  tall as the figure), panel_labels (a, A, (a): how panels are lettered), spacing,
  shape_padding, line_width, head_size (each a share of the theme's, 1 by default: spacing 0.6
  is the room between shapes, round groups and kept by lines at 0.6 of the theme's -- for a
  figure tighter, or with smaller arrowheads, than the rest)}
nodes: each {id, label, kind (block by default; text, op, circle, feature-strip, mlp,
  attention, channels, inset, ...), properties: {tone: encoder|head|attention|..., badge, ...}}
Genetics: kind construct, properties {parts: [{type: promoter|rbs|cds|terminator|operator|origin|
  insulator|primer|site|region, label, id (makes a port), strand: + or -, tone}]}; kind plasmid,
  properties {length: bp, features: [{type, label, start, end, strand}]}.
Proteins: kind protein, properties {length, features: [{type: domain|region|motif|transmembrane|
  signal|mutation|phosphorylation|...|disulfide, label, start, end (or at, for a site)}],
  tracks: [{label, start, end, delete: "61-121"}], secondary: DSSP string (H helix, E strand,
  T turn), sequence: one-letter, helix: ribbon|cylinder|spiral}. Trees: kind tree,
  properties {newick,
  layout: rectangular|circular, clades: [{tips: "A, B", label}], support}. The bench: kind
  wellplate {wells: 96, groups: [{wells: "A1-A12", label}]}; kind timeline {unit: day,
  events: [{at, label}], spans: [{start, end, label}]}.
Grids: kind cells, properties {grid: "K . K\n. Y R" (one row per line, one symbol per word,
  . empty, numbers shaded on ramp), key: [{symbol, color: tone or #hex, mark, label}], cell,
  gap, corner, lines: ink|muted|#hex, row_labels / column_labels: numbers|letters|"a, b",
  row_side, column_side, ramp: "#lo, #hi", range: "lo, hi", values: true}.
edges: each {from: node, node.port or group, to: node, node.port or group, label, role, head:
  triangle|stealth|latex|open|hollow|dot|diamond|square, or SBGN's inhibition|catalysis|
  stimulation|necessary|modulation,
  arrow: none|both|reversible, tail (the start's head, with arrow: both), back_label, cofactors:
  [ATP, ADP], shape: orthogonal|straight|curved, line: dashed|dotted, tone, width (pt), head_size
  (1.5 = half as large again), depart/arrive: north|south|east|west (the side it leaves or meets)}
groups: each {id, children: [ids], layout: {kind: row|column|grid, gap}, label, title_side:
  left|right|bottom-left|bottom-right (where its label stands)}; the root group (figure.root,
  "root" by default) holds the rest. A file without groups stacks its nodes.
An edge may start or end at a group, as at a node -- everything going in, a step, everything
  coming out: {from: substrates, to: cell}, {from: cell, to: products, arrive: west}. It meets
  a group drawn with an outline at its outline, and a layout group or panel (which draws none)
  at the box round what it holds, stopping as short of those parts as of a node; at the middle
  of the side facing its other end (or depart/arrive's) -- at the left or right, level with
  the drawings of the named parts it centres -- through none of its parts, and it moves
  nothing. Never between a group and a part it holds, nor to the root; a group has no ports
  (substrates.top: write substrates, depart: north).
A picture: {id, kind: image, label, properties: {source: photo.png (.jpg, .svg), title_side:
  top|bottom (its label over or under the picture, set as a structure's is)}, width}. An SVG's
  words are set in the figure's font, the same in every output; its properties may say otherwise --
  font: drawn (the faces its file names, as found) or a family; texts: [{id: text1 (the text's
  id in the file; one with none is text: 3, its place among the file's texts), words:
  "two\nlines", size (pt, at the drawing's own size), bold, italic, colour: "#c0392b"}];
  colours: {"#4a90d9": "#2e7d32"} (every use of a colour, drawn in another). The file itself is
  never changed: a text it no longer has is passed over. A molecule's
  structure: {id, kind: structure, properties: {source: a .pdb or .cif file in the folder, or a
  mol-sketch scene (.json: a reaction drawn with its orbitals, lone pairs, arrows and measures),
  step (a scene's: 1, its first; drawn as its arrows finish), look (engraved-colour, textbook,
  flat, ...), scheme (flat: look, its own coral and amber, or figure, the figure's tones), width,
  height, yaw, pitch, roll, zoom, pan_x, pan_y, frame (a name: structures naming one frame are
  drawn with one camera, at one scale, about one centre, as the first of them is turned and
  framed -- a diffusion trajectory, a motif held fixed), title_side: top|bottom (its label over
  or under the molecule), style: {mol-sketch's settings: show: {orbitals, measures},
  lone_pair_style, ...}}}.
A reaction mechanism: {id, kind: mechanism, properties: {steps: [{smiles: "[OH-:5].[CH3:1]
  [C:2](=[O:3])[Cl:4]", arrows: ["5 -> 2", "2=3 -> 3"], label, reagents, conditions},
  {arrows: ["3 -> 2", "2-4 -> 4"]}]}} -- the atoms its arrows name are mapped ([O-:5] is 5); an
  arrow from a lone pair is "5 -> 2", from a bond "2=3 -> 3"; a step with no smiles is drawn
  from the arrows before it. An atom may be a placeholder, drawn as written, for a reaction in
  general: "[X:1].[Y:2][Z:3]", [Nu-], [E], [LG], [R1] ([*Ar], [*B] where the letters are an
  element's).
A frame round shapes anywhere in the figure (in different groups too), which moves none of
  them: a node {id, kind: frame, label, properties: {around: "id, id" (shapes or groups),
  layer: behind|front|over (a tint they show through), tone, title_side:
  left|right|bottom-left|bottom-right (the corner its label stands at: the top left unless
  written -- at the bottom where a line leaves the top of what it holds)}}. An edge may
  start or end at a frame, from a shape the frame does not go round: {from: block, to:
  stage, arrive: south} -- it meets the frame's outline at the middle of that side
  (depart, for where it leaves one; north|south|east|west; left out, the side that faces
  its other end), and moves no shape.
A plot: {id, kind: plot, properties: {source: plots.py, function: name}, width, height} -- the
  matplotlib figure that function returns, in the figure's font and colours, at that size (don't
  set fonts, sizes or colours in the function: they are the figure's). It is drawn again when
  a file it reads changes; properties.data: [loss.h5, "runs/*.parquet"] names data it reads
  through a library that opens files itself (HDF5, Parquet), which is not seen otherwise.
A node, a group and a frame each take line: dashed|dotted for their outline, as an edge does.
A node's properties set its whole label: bold: true, italic: true, size: 6pt, align: left|right;
  an image's crop it: crop_left|crop_top|crop_right|crop_bottom (hundredths cut off that side);
  a GIF image plays, and still: 12 is the frame its PDF and PNG show (from 1; the first unset).
figure: {hide: [ids], dim: [ids], highlight: [ids]} leaves parts out, draws them faint, or draws
  all but them faint -- where they stand, nothing moved (one figure shown several ways in a talk).
shapes: drawn over the figure where they are put, taking no room -- what you would open Inkscape
  for: an arrow at a part, a ring round some, a brace and its words beside a stack, a highlight
  behind a word, a dimension line, a box of words. Each is a slide's shape (the same words: one
  copied from a slide pastes here): {kind, id, ...}, kinds line, arrow, double-arrow, curved-arrow
  (bend, lean), elbow, arc, polyline and pen (points), rectangle, rounded-rectangle, ellipse,
  triangle, diamond, polygon, star, block arrows (arrow-right...), chevron, plus, cross, check,
  cloud, bubble (tail), brace and bracket (depth, tip), dimension, scale-bar, highlight, ring,
  text (at, width), path (d: SVG path data, fill_rule: nonzero|evenodd; any outline, holes
  too; no at or size), group (shapes). Lines take from and to, boxes at and size (rotate, flip).
  Places are the figure's points, y down, from its top left as laid out -- so attach them to
  its parts, which the layout moves: an end glued to a part, to: {part: encoder, side:
  top|right|bottom|left|centre} (any node, group or frame by id, or a piece of one its drawing
  names, such as spike.feature2 or tree.tip3); on: encoder, the shape's places from that part's
  top left; around: [encoder, decoder] with margin (points; a ring passes their corners), the
  shape sized round them -- a brace, bracket or dimension along their side (right unless said).
  Style: fill and line are theme colours (accent, accent2, accent-fill, muted, ink, paper, grey)
  or #rrggbb, line_width, dash (dashed, dotted), start and end heads (triangle, open, stealth,
  dot, circle, bar, diamond), head_size, opacity, fill_opacity, shadow; words: text (the
  figure's label markup), font_size, bold, italic, colour, align, valign. behind: true draws one
  under the parts; hide, dim and highlight name a shape by its id. A zoom inset, kind: inset,
  of: a part (on: that part too, to move with it), region: [x, y, width, height] as fractions
  of the part, at and size, shows that region magnified in its box, joined to it by two lines
  (frame_line, connector_line, their _width and _dash; text a corner label). E.g.
  shapes: [{kind: ring, around: [encoder]}, {kind: arrow, from: [20, 10], to: {part: decoder,
  side: top}, text: "here"}, {kind: text, on: decoder, at: [0, -16], text: bottleneck}].
  A diagram pasted as shapes (boxes with words, arrows, a titled box round some) becomes the
  figure's own parts with the convert_to_figure_parts tool: laid out and themed as drawn.
A figure of several panels, as a journal prints one: each panel a group with role: panel (no
  frame; lettered a, b, c in the order the root holds them, so write no letter -- a label is
  a title after it), the root laying them out ({id: root, role: canvas, layout: {kind: grid,
  columns: 2}, children: [first, second, ...]}).
Labels are markup: $maths$, `code`, [words]{accent} in a colour, [words]{bold} or {italic},
\\n a new line (asterisks are drawn as typed). `flexo schema` prints the full schema.
"""


class FigureKind:
    name = "figure"
    title = "Figure"
    static = Path(__file__).parent / "static" / "figure"

    def mended(self, document: object, notes: list | None = None, base: object = None) -> object:
        """A figure two edits were merged into, with no line left naming a shape gone."""

        from flexo.studio.figure_edit import mend

        mend(document)
        return document

    def claims(self, document: object) -> bool:
        return isinstance(document, dict) and ("nodes" in document or "figure" in document)

    def new(self, path: Path) -> dict[str, Any]:
        # Named for its file, as a deck or a theme is: "Pipeline figure" is pipeline-figure.
        from flexo.studio.figure_edit import _slug

        return {"text": NEW_FIGURE.replace("  id: figure\n", f"  id: {_slug(path.stem)}\n", 1)}

    def adopt(self, data: dict[str, Any]) -> dict[str, Any]:
        """A parsed figure document (one written inline in a deck) as a file's words."""

        return {"text": yaml.safe_dump(data, sort_keys=False, allow_unicode=True)}

    def load(self, path: Path) -> dict[str, Any]:
        # A file that does not read is not opened as words to draw (said "Saved", with
        # nothing drawn): it is a document whose file can't be read, as a deck's or a
        # theme's is, its line chosen to put right.
        return self.parse(path.read_text(encoding="utf-8"))

    def save(self, path: Path, document: dict[str, Any]) -> None:
        path.write_text(document["text"], encoding="utf-8")

    def dump(self, document: dict[str, Any]) -> str:
        return document["text"]

    def parse(self, text: str) -> dict[str, Any]:
        yaml.safe_load(text)  # refuse what does not read, before anyone sees it
        return {"text": text}

    def references(self, data: Any, base: Path) -> list[Any]:
        """The files a figure file (``data``, as it reads) names, for a bundle of it."""

        from flexo.bundle import figure_references

        return figure_references(data, base)

    def theme_of(self, document: dict[str, Any]) -> str | None:
        data = yaml.safe_load(document["text"])
        figure = data.get("figure") if isinstance(data, dict) else None
        style = figure.get("style") if isinstance(figure, dict) else None
        return str(style) if style else None

    def with_theme(self, document: dict[str, Any], theme: str, base: Path) -> dict[str, Any]:
        from flexo.studio.figure_edit import apply

        action = {"do": "update", "target": {"type": "figure"}, "values": {"figure.style": theme}}
        result = apply(document["text"], action, suffix=document.get("suffix", ".yaml"), base=base)
        return {**document, "text": result["text"]}

    def guide(self) -> str:
        return GUIDE

    def describe(self, before: Any, after: Any) -> list[dict[str, Any]]:
        """What an edit did, said as the figure has it ("added “Cache”", "connected “A” to
        “B”"), not as lines of its file -- but for a file that does not read as a figure."""

        import difflib

        said = _changes(_figure_of(before), _figure_of(after))
        if said is not None:
            return said
        old = (before or {}).get("text", "").splitlines()
        new = (after or {}).get("text", "").splitlines()
        changed = [
            (tag, start)
            for tag, start, _, _, _ in difflib.SequenceMatcher(None, old, new).get_opcodes()
            if tag != "equal"
        ]
        if not changed:
            return []
        first = changed[0][1] + 1
        return [
            {
                "text": f"edited line {first}"
                if len(changed) == 1
                else f"edited {len(changed)} places",
                "where": {"line": first, "label": f"line {first}"},
            }
        ]

    def act(self, document: dict[str, Any], action: dict[str, Any], base: Path) -> dict[str, Any]:
        """An edit made on the page (add, connect, rename, ...), made to the file's words."""

        from flexo.studio.figure_edit import apply

        if action.get("do") == "structure-view":
            return {"document": document, "view": _structure_view(document, action, base)}
        if action.get("do") == "structure-settings":
            spec = _as_drawn(document, base)
            return {"document": document, "settings": settings_of(spec, str(action.get("id")))}
        if action.get("do") == "structure-fetch":
            # One that can't be had is an answer, said in the dialog -- not a failed request
            # (which the browser would also log as an error).
            from flexo.studio.figure_edit import EditError
            from flexo.studio.plain import explain

            try:
                return {"document": document, "id": fetched(str(action.get("id") or ""))}
            except EditError as error:
                return {"document": document, "failed": explain(error)}
        if action.get("do") == "previews":
            # The figure drawn in a design before it is chosen: the Design bar's (previews.py).
            from flexo.studio.previews import previews

            return previews(self, document, action, base)
        result = apply(document["text"], action, suffix=document.get("suffix", ".yaml"), base=base)
        from flexo.studio.figure_edit import model

        suffix = document.get("suffix", ".yaml")
        return {
            "document": {**document, "text": result["text"]},
            "select": result["select"],
            "model": model(result["text"], suffix=suffix, base=base),
            **({"said": result["said"]} if result.get("said") else {}),
        }

    def check(self, document: dict[str, Any], base: Path) -> list[str]:
        drawing = self.draw(document, base)
        return [message.text for message in drawing.messages if message.severity == "error"]

    def catalog(self) -> dict[str, Any]:
        from flexo.colour import design_palettes
        from flexo.components import COMPONENTS
        from flexo.fonts import available_families
        from flexo.studio.figure_parts import catalogue
        from flexo.themes import theme_names

        found = {
            "themes": list(theme_names()),
            "palettes": {name: list(colours) for name, colours in design_palettes().items()},
            "fonts": list(available_families()),
            "components": sorted(COMPONENTS),
        }
        return {**found, "editor": catalogue(found), "shapes": shapes_catalogue()}

    def draw(
        self, document: dict[str, Any], base: Path, hints: dict[str, Any] | None = None
    ) -> Drawing:
        from flexo.compiler import compile_figure
        from flexo.diagnostics import FlexoError
        from flexo.lint import lint_compilation
        from flexo.plots import WAITING
        from flexo.studio.figure_edit import model
        from flexo.studio.plain import explain

        # The figure as written, for the page's inspector, whether or not it draws.
        try:
            suffix = document.get("suffix", ".yaml")
            info = {"model": model(document["text"], suffix=suffix, base=base)}
        except Exception:  # not a shape the inspector can list: the drawing says why
            info = {}
        said_first: list[Message] = []
        wrong: set[str] = set()  # the shapes drawn as plain boxes
        # A line to a shape there is none of is left out, and said; the rest is drawn.
        document = _strays(document, said_first)
        # So is a shape drawn over the figure that is written wrong: each keeps its place.
        document, drawn_over = _shapes_apart(document, said_first)
        try:
            spec = parse(document["text"], base, suffix=document.get("suffix", ".yaml"))
        except (yaml.YAMLError, json.JSONDecodeError) as error:
            return Drawing(
                [], [Message(_yaml_problem(error), "error", _yaml_line(error))], info=info
            )
        except FlexoError as error:
            # A shape that can't be drawn as it is (a protein with no length): said by its
            # name, plainly, the message leading to it -- and the rest of the figure drawn,
            # it a plain box with its words meanwhile.
            spec = _stand_in(document, base, error, info, said_first, wrong)
            if spec is None:
                return Drawing([], said_first, info=info)
        except Exception as error:
            return Drawing([], [Message(explain(error), "error")], info=info)
        # So too a shape found wanting as it is drawn (a plasmid of -5 bp, a tree whose
        # Newick does not read).
        try:
            drawn = _despite(
                document,
                base,
                spec,
                info,
                said_first,
                wrong,
                lambda spec: compile_figure(_shaped(spec, drawn_over)),
            )
        except Exception as error:
            return Drawing([], [Message(explain(error), "error")], info=info)
        if drawn is None:
            return Drawing([], said_first, info=info)
        spec, compilation = drawn
        report = lint_compilation(compilation)
        info["tones"] = _tones(spec)
        info |= _drawn_over(compilation, spec, drawn_over)
        page = Page(
            spec.id, compilation.document.text, label=spec.id, extra={"outline": outline(spec)}
        )
        files = [base / value for value in (spec.style, spec.palette) if _is_file(value)]
        files += _plot_files(spec, base)
        files += _part_files(_shaped(spec, drawn_over), base)
        said = [*report.diagnostics, *structure_problems(spec)]
        # (A plot not run yet, its Python still starting, is asked for again by the page.)
        again = any(item.code == WAITING for item in said)
        messages = [*said_first, *(_message(item) for item in said)]
        return Drawing([page], messages, files, info, again=again)

    def export(
        self,
        document: dict[str, Any],
        base: Path,
        stem: str,
        formats: list[str],
        *,
        into: Path | None = None,
    ) -> list[Path]:
        from flexo.diagnostics import FlexoError
        from flexo.export import build
        from flexo.studio.figure_edit import model

        # Exported as it is drawn: lines to shapes it has none of left out, a shape that
        # can't be drawn as written (a protein with no length) a plain box of its words --
        # each said in a note with what was made.
        said: list[Message] = []
        wrong: set[str] = set()
        document = _strays(document, said)
        document, drawn_over = _shapes_apart(document, said)
        info = {"model": model(document["text"], suffix=document.get("suffix", ".yaml"))}
        try:
            spec = parse(document["text"], base, suffix=document.get("suffix", ".yaml"))
        except FlexoError as error:
            spec = _stand_in(document, base, error, info, said, wrong)
            if spec is None:
                raise ValueError(" ".join(message.text for message in said)) from None
        made = _despite(
            document,
            base,
            spec,
            info,
            said,
            wrong,
            lambda spec: build(
                _shaped(spec, drawn_over), into or base / "build", stem=stem, formats=tuple(formats)
            ),
        )
        if made is None:
            raise ValueError(" ".join(message.text for message in said))
        self.export_notes = [_exported_as(message.text) for message in said]
        result = made[1]
        written = list(result.outputs.existing())
        if into is not None and "editable" not in formats and len(written) > 1:
            # The editable SVG is written whatever is asked for: made aside, to be handed
            # over, only what was asked for is.
            result.outputs.editable_svg.unlink()
            written.remove(result.outputs.editable_svg)
        return written


def shapes_catalogue() -> dict[str, Any]:
    """The shapes a figure may have drawn over it (``flexo.figure_shapes``), for the editor:
    their kinds by section, names, defaults and sizes, what a figure says of one besides, and
    how far one drawn round parts stands out from them."""

    from flexo.figure_shapes import MARGIN, MARGINS, SHAPE_KEYS
    from flexo.freeform import catalogue

    return {**catalogue(), "keys": list(SHAPE_KEYS), "margin": MARGIN, "margins": dict(MARGINS)}


def _plot_files(spec, base: Path) -> list[Path]:
    """What the figure's plots are drawn from -- each one's Python file (there or not
    yet), and what its function read (``flexo.plots.files``: its data, and the folders it
    listed): one saved, or a file put in such a folder, the figure is drawn again."""

    from flexo.confine import outside
    from flexo.plots import PLOT_KIND, files

    found: list[Path] = []
    for node in spec.nodes:
        source = str(node.property("source", "") or "").strip()
        if node.kind == PLOT_KIND and source and not outside(base / source):
            function = str(node.property("function", "") or "").strip()
            found += files(base / source, function, node.property("data"))
    return found


def _part_files(spec, base: Path) -> list[Path]:
    """The files the figure's parts draw -- each picture (a PDF's page, its file), structure,
    map and structure one is coloured by, and the pictures among the shapes drawn over it --
    found from ``base`` as ``parse`` finds them: one edited, the figure is drawn again. (A PDB
    ID is no file.)"""

    from flexo.plots import PLOT_KIND
    from flexo.shape_pictures import sources

    names = [
        str(value).strip()
        for node in spec.nodes
        if node.kind != PLOT_KIND
        for key, value in node.properties
        if key in ("source", "density", "ss_from") and isinstance(value, str) and value.strip()
    ]
    for shape in spec.shapes:
        if '"picture"' in shape.written:
            names += sources([shape.spec])
    found = []
    for name in names:
        path = base / Path(name).expanduser()
        if not path.is_file() and "#" in name:
            path = path.with_name(path.name.rpartition("#")[0])  # (a PDF's page: art.pdf#2)
        if path.is_file():
            found.append(path)
    return found


def _tones(spec) -> dict[str, Any]:
    """The figure's tone colours, for the page's colour chips: the theme's, in order,
    and which of them each tone name the figure uses paints with."""

    from flexo.emit import _tone_map
    from flexo.themes import TONE_COUNT, figure_palette, figure_style, with_tone_roles

    palette = with_tone_roles(figure_palette(spec))
    colours = [
        {"fill": palette.get(f"tone-{index}-fill"), "stroke": palette.get(f"tone-{index}-stroke")}
        for index in range(1, TONE_COUNT + 1)
    ]
    # The theme's grey, as a shape toned ``neutral`` is painted (its block paint).
    neutral = {"fill": palette.get("block-fill"), "stroke": palette.get("block-stroke")}
    return {"colours": colours, "used": _tone_map(spec, figure_style(spec)), "neutral": neutral}


def outline(spec) -> dict[str, Any]:
    """The figure's parts as the page lists them: groups holding nodes, and edges."""

    def words(label) -> str:
        return "".join(run.text for run in label)

    nodes = {
        node.id: {"id": node.id, "type": "node", "kind": node.kind, "label": words(node.label)}
        for node in spec.nodes
    }
    groups = {group.id: group for group in spec.groups}

    def tree(identifier: str, seen: frozenset[str] = frozenset()) -> dict[str, Any]:
        if identifier in nodes:
            return nodes[identifier]
        group = groups.get(identifier)
        if group is None or identifier in seen:
            return {"id": identifier, "type": "missing", "label": ""}
        return {
            "id": identifier,
            "type": "group",
            "kind": group.layout.kind,
            "label": words(group.label),
            "children": [tree(child, seen | {identifier}) for child in group.children],
        }

    edges = [
        {
            "id": edge.id,
            "source": edge.source.node_id,
            "target": edge.target.node_id,
            "label": words(edge.label),
        }
        for edge in spec.edges
    ]
    return {"root": tree(spec.root), "edges": edges, "nets": [net.id for net in spec.nets]}


def parse(text: str, base: Path, *, suffix: str = ".yaml"):
    """A figure from its file's words, theme and palette files -- and the pictures and
    structures its parts draw -- found from ``base``."""

    from flexo.plots import PLOT_KIND, beside
    from flexo.serialization import parse_figure

    document = json.loads(text) if suffix == ".json" else yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ValueError("a figure file is a mapping: figure, nodes, edges, groups")
    figure = document.get("figure")
    if isinstance(figure, dict):
        for key in ("theme", "style", "palette"):
            value = figure.get(key)
            if _is_file(value) and (base / value).is_file():
                figure[key] = str((base / value).resolve())
    for node in document.get("nodes") or []:
        properties = node.get("properties") if isinstance(node, dict) else None
        for key in ("source", "density", "ss_from"):
            value = properties.get(key) if isinstance(properties, dict) else None
            if isinstance(value, str) and value and (base / value).is_file():
                properties[key] = str((base / value).resolve())
        # (The data a plot names is its figure's too: found from the figure's folder.)
        if isinstance(properties, dict) and node.get("kind") == PLOT_KIND and "data" in properties:
            properties["data"] = beside(base, properties["data"])
    if "shapes" in document:
        from flexo.shape_pictures import anchored

        # (A picture among the shapes drawn over it is found as a part's picture is.)
        document["shapes"] = anchored(document["shapes"], base)
    return parse_figure(document)


def _structure_view(document: dict[str, Any], action: dict[str, Any], base: Path) -> Any:
    """A structure's trace and turn, for the page to turn while it is dragged round."""

    return view_of(_as_drawn(document, base), str(action.get("id")))


def _as_drawn(document: dict[str, Any], base: Path) -> Any:
    """The figure as it is drawn -- a line to a shape it has none of left out, a shape that
    can't be drawn as written a plain box -- for what is asked of one of its parts (a
    structure's settings), which the rest being wrong does not change."""

    from flexo.diagnostics import FlexoError

    document = _strays(document, [])
    try:
        return parse(document["text"], base, suffix=document.get("suffix", ".yaml"))
    except FlexoError as error:
        spec = _stand_in(document, base, error, {}, [], set())
        if spec is None:
            raise
        return spec


def settings_of(spec, identifier: str) -> dict[str, Any]:
    """The mol-sketch settings the structure ``identifier`` in ``spec`` is drawn with --
    its look's, the figure's colours, and its own -- with mol-sketch's looks and palettes:
    what the studio shows beside the settings a structure may be given."""

    from flexo.emit import _tone_map
    from flexo.structures import structure_settings
    from flexo.studio.figure_edit import EditError
    from flexo.themes import figure_palette, figure_style, with_tone_roles

    node = next((item for item in spec.nodes if item.id == identifier), None)
    if node is None or node.kind != "structure":
        raise EditError(f"“{identifier}” isn't a structure.")
    style = figure_style(spec)
    # The figure's tones as it is drawn with them, so a chain coloured by a tone is one.
    palette = with_tone_roles(figure_palette(spec)).with_tones(_tone_map(spec, style))
    return structure_settings(node, style, palette)


def fetched(pdb_id: str) -> str:
    """A PDB entry downloaded before a structure is made of it: its ID, or an EditError
    saying why it couldn't be (for any kind that draws figures)."""

    from flexo.structures import fetch_structure
    from flexo.studio.figure_edit import EditError

    try:
        return fetch_structure(pdb_id)
    except ValueError as error:
        raise EditError(str(error)) from None


def structure_problems(spec) -> list[Any]:
    """What keeps each structure in ``spec`` from being drawn as written, as warnings: the
    figure is drawn all the same, a structure that can't be had as a panel saying why -- and
    a structure's or a picture's name written to stand neither over it nor under it."""

    from flexo.structure_frames import frame_problems
    from flexo.structures import structure_problem
    from flexo.themes import figure_style
    from flexo.title_sides import SIDED_KINDS, title_side_problem

    style = figure_style(spec)
    found = [structure_problem(node, style) for node in spec.nodes if node.kind == "structure"]
    # (A picture's name stands over it or under it as a structure's does: flexo.title_sides.)
    found += [title_side_problem(node) for node in spec.nodes if node.kind in SIDED_KINDS]
    return [item for item in found if item is not None] + frame_problems(spec)


def view_of(spec, identifier: str) -> dict[str, Any]:
    """The trace and turn of the structure ``identifier`` in ``spec``, drawn as ``spec``
    says (its theme chooses the look) -- in a frame with others, as the frame turns it
    (``flexo.structure_frames.framed_view``): for any kind that draws figures."""

    from flexo.structure_frames import framed_view
    from flexo.studio.figure_edit import EditError
    from flexo.themes import figure_palette, figure_style

    node = next((item for item in spec.nodes if item.id == identifier), None)
    if node is None or node.kind != "structure":
        raise EditError(f"“{identifier}” isn't a structure.")
    return framed_view(spec, identifier, figure_style(spec), figure_palette(spec))


def _is_file(value: object) -> bool:
    return isinstance(value, str) and value.lower().endswith((".yaml", ".yml", ".json"))


_PLAIN = {
    "layout.width.grown": (
        "The figure is wider than its page. Choose a wider Width, or fewer shapes in a row."
    ),
    "layout.height.grown": (
        "The figure is taller than its page. Choose a taller Page Size, or empty Height for "
        "a page as tall as the figure."
    ),
}
"""Diagnostics said in the editor's words, not the file's (what to do there, not what to write)."""


def _message(diagnostic) -> Message:
    text = _PLAIN.get(diagnostic.code) or (
        diagnostic.message + (f" ({diagnostic.hint})" if diagnostic.hint else "")
    )
    severity = "note" if diagnostic.severity.value == "info" else diagnostic.severity.value
    return Message(text, severity, diagnostic.entity_id or "", code=diagnostic.code)


def _shape_problem(diagnostic, info: dict[str, Any]) -> Message:
    """What keeps a shape from being drawn, said of it by its name ("“Spike” can't be drawn
    yet: a protein needs its length in residues.") -- the editor's words: its panel is where
    it is put right, not a file to write in."""

    nodes = (info.get("model") or {}).get("nodes") or []
    node = next((item for item in nodes if item.get("id") == diagnostic.entity_id), None)
    if node is None:
        return _message(diagnostic)
    label = node.get("label")
    words = (
        label
        if isinstance(label, str)
        else " ".join(str(run.get("text", "")) for run in label or [] if isinstance(run, dict))
    )
    # (Its words as read: emphasis, code and maths marks left out.)
    name = re.sub(r"\]\{[^}]*\}|[*`$\[]", "", words).strip()
    message = diagnostic.message.strip()
    first = message.split(" ", 1)[0]
    lower = message if len(first) > 1 and first.isupper() else message[:1].lower() + message[1:]
    called = f"\u201c{name}\u201d" if name else f"This {node.get('kind') or 'shape'!s}"
    return Message(
        f"{called} can\u2019t be drawn yet: {lower} Choose it to set this in its panel.",
        "error",
        diagnostic.entity_id or "",
        code=diagnostic.code,
    )


def _exported_as(said: str) -> str:
    """What an export says of a shape it drew as a plain box, or a line it left out."""

    found = re.match(r"(\u201c[^\u201d]*\u201d|This \S+) can\u2019t be drawn yet: ", said)
    if found:
        why = said[found.end() :].split(" Choose it")[0]
        return f"{found.group(1)} is drawn as a plain box: {why}"
    return said


def _strays(document: dict[str, Any], said: list[Message]) -> dict[str, Any]:
    """The figure without its lines to (or from) shapes it has none of, each said in
    ``said`` -- or as it is, with none (or should it not read)."""

    from flexo.studio.figure_edit import astray

    json_file = document.get("suffix", ".yaml") == ".json"
    try:
        data = json.loads(document["text"]) if json_file else yaml.safe_load(document["text"])
    except (yaml.YAMLError, json.JSONDecodeError, TypeError):
        return document
    ids: list[str] = []
    lost = astray(data, ids)
    if not lost:
        return document
    # (Each at its line: chosen from the message, its panel says where it goes.)
    said += [Message(line, "warning", where) for line, where in zip(lost, ids, strict=True)]
    text = (
        json.dumps(data, indent=2, ensure_ascii=False)
        if json_file
        else yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
    return {**document, "text": text}


def _shapes_apart(
    document: dict[str, Any], said: list[Message]
) -> tuple[dict[str, Any], list[dict[str, Any] | None] | None]:
    """The figure without the shapes drawn over it, and those shapes, each checked
    (``flexo.figure_shapes``): one written wrong -- or named as a part of the figure is --
    is said in ``said`` and is ``None``, keeping its place in the list, so the rest are drawn
    as they are numbered. None for a figure with no shapes (or that does not read)."""

    from flexo.figure_shapes import read, shape_names

    json_file = document.get("suffix", ".yaml") == ".json"
    try:
        data = json.loads(document["text"]) if json_file else yaml.safe_load(document["text"])
    except (yaml.YAMLError, json.JSONDecodeError, TypeError):
        return document, None
    if not isinstance(data, dict) or "shapes" not in data:
        return document, None
    found, problems = read(data.pop("shapes"))
    said += [Message(item.message, "error", item.entity_id or "", code=item.code)
             for item in problems]
    # (Named as a part of the figure is: which would an end glued to it be glued to?)
    taken = {str(item.get("id")) for key in ("nodes", "groups", "edges", "nets")
             for item in data.get(key) or [] if isinstance(item, dict) and item.get("id")}
    for index, spec in enumerate(found):
        clash = [name for name in shape_names(spec or {}) if name in taken]
        if clash:
            said.append(Message(f"shapes[{index}].id: a shape is called {clash[0]}, as a part "
                                "of the figure is: each needs a name of its own.", "error",
                                clash[0], code="shape.id.taken"))
            found[index] = None
    text = (
        json.dumps(data, indent=2, ensure_ascii=False)
        if json_file
        else yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
    return {**document, "text": text}, found


def _shaped(spec: Any, shapes: list[dict[str, Any] | None] | None) -> Any:
    """``spec`` with the shapes drawn over it again (``_shapes_apart``): one written wrong
    holds its place, drawing nothing."""

    from dataclasses import replace

    from flexo.ir.semantic import FreeShape

    if not shapes:
        return spec
    return replace(spec, shapes=tuple(FreeShape.of(item) for item in shapes))


def _drawn_over(compilation: Any, spec: Any, shapes: list[dict[str, Any] | None] | None) -> dict:
    """What the page needs to edit the shapes drawn over the figure as it draws them: each
    as it is placed (``shapes``, by its place in the list; ``None`` where none is drawn), the
    box of each part a shape may be glued to or put on (``boxes``), the figure's colours by
    their palette roles, and the size and family its words are set in."""

    from flexo.emit import _tone_map
    from flexo.figure_shapes import part_boxes
    from flexo.themes import figure_palette, figure_style, with_tone_roles

    def rounded(box: tuple) -> list[float]:
        return [round(float(value), 3) for value in box]

    overlay = compilation.shapes
    boxes = part_boxes(compilation.routed.fitted, compilation.frames)
    if overlay is not None:
        boxes |= overlay.named
    style = figure_style(spec)
    palette = with_tone_roles(figure_palette(spec)).with_tones(_tone_map(spec, style))
    placed: list[Any] = []
    if overlay is not None:
        placed = [_rounded(one.spec) if one is not None else None for one in overlay.placed]
    typography = style.typography
    return {
        "shapes": placed if shapes else [],
        "boxes": {name: rounded(box) for name, box in boxes.items()},
        "roles": dict(palette.paints),
        "sizes": {"words": typography.size.points},
        "fonts": {"body": typography.family},
    }


def _rounded(value: Any) -> Any:
    """Places to a thousandth of a point, for the page."""

    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


def _stand_in(
    document: dict[str, Any],
    base: Path,
    error,
    info: dict[str, Any],
    said: list[Message],
    wrong: set[str],
) -> Any:
    """The figure with each shape ``error`` names (and those in ``wrong``, found so
    before) a plain box of its words, each said in ``said`` by its name; None, said too,
    should ``error`` name no shape not found so already, or the figure not draw even so."""

    said += [_shape_problem(item, info) for item in error.diagnostics]
    named = {item.entity_id for item in error.diagnostics if item.entity_id} - wrong
    if not named:
        return None
    wrong |= named
    return _without(document, base, wrong)


def _despite(
    document: dict[str, Any],
    base: Path,
    spec,
    info: dict[str, Any],
    said: list[Message],
    wrong: set[str],
    attempt,
) -> tuple[Any, Any] | None:
    """``spec`` and what ``attempt(spec)`` makes of it -- a shape it fails at (a plasmid of
    -5 bp, a tree whose Newick does not read) a plain box of its words, and tried again, so
    one wrong shape does not blank the rest; each said in ``said``, and kept in ``wrong``
    with those found so before. None should it fail otherwise."""

    from flexo.diagnostics import FlexoError

    while True:
        try:
            return spec, attempt(spec)
        except FlexoError as error:
            spec = _stand_in(document, base, error, info, said, wrong)
            if spec is None:
                return None


def _without(document: dict[str, Any], base: Path, wrong: set[str]) -> Any:
    """The figure with each shape in ``wrong`` (that can't be drawn) a plain box of its
    words, so the rest is drawn: None should it name none of them, or not draw even so."""

    from flexo.diagnostics import FlexoError

    suffix = document.get("suffix", ".yaml")
    data = json.loads(document["text"]) if suffix == ".json" else yaml.safe_load(document["text"])
    if not isinstance(data, dict):
        return None
    nodes = [node for node in data.get("nodes") or [] if isinstance(node, dict)]
    if not any(node.get("id") in wrong for node in nodes):
        return None
    for node in nodes:
        if node.get("id") in wrong:
            node.pop("properties", None)
            node["kind"] = "block"
    try:
        return parse(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), base)
    except (FlexoError, ValueError, TypeError, yaml.YAMLError):
        return None


# What the YAML reader says of a file it can't read, and what that is to whoever wrote it.
_YAML_SAID = (
    (
        r"expected ',' or '\]'",
        "a list in square brackets isn\u2019t closed, or a word in it needs quotes",
    ),
    (
        r"expected ',' or '\}'",
        "a set of settings in braces isn\u2019t closed, or a word in it needs quotes",
    ),
    (r"mapping values are not allowed", "a colon is among words; put words with a colon in quotes"),
    (r"found character '\\t'|found character '\t'", "a line is indented with a tab, not spaces"),
    (r"could not find expected ':'", "a line is missing its colon"),
    (r"unexpected end of stream|while scanning a quoted scalar", "a quote isn\u2019t closed"),
    (
        r"did not find expected key|expected <block end>|did not find expected '-' indicator",
        "a line is indented differently from the lines around it",
    ),
    (r"found duplicate anchor|found undefined alias", "a name after & or * is used wrongly"),
)


def yaml_said(error: Exception) -> str | None:
    """What the YAML reader found wrong in a file, in its writer's words ("a quote is not
    closed"); None if it is none of those it is known to say."""

    problem = str(getattr(error, "problem", None) or error)
    context = str(getattr(error, "context", None) or "")
    return next(
        (said for pattern, said in _YAML_SAID if re.search(pattern, f"{context} {problem}")), None
    )


def _yaml_problem(error: Exception) -> str:
    """Why a figure's file can't be read, in its writer's words, never the reader's."""

    said = yaml_said(error)
    if said:
        return f"The file can\u2019t be read: {said}."
    problem = str(getattr(error, "problem", None) or error)
    return f"The file can\u2019t be read as written: {problem}."


def _yaml_line(error: Exception) -> str:
    mark = getattr(error, "problem_mark", None)
    return f"line {mark.line + 1}" if mark is not None else ""


def _figure_of(document: Any) -> dict[str, Any] | None:
    """A figure file's nodes, lines, groups and settings, as written; None if it does not
    read as one."""

    try:
        data = yaml.safe_load((document or {}).get("text", "") or "") or {}
    except yaml.YAMLError:
        return None
    return _read_figure(data)


def figure_changes(old: Any, new: Any) -> list[str]:
    """What an edit did to a figure written in another document (a deck's slide), as its
    data before and after: a few notes ("added “Cache”", "moved “Encoder”"); none when it
    does not read as a figure."""

    return [note["text"] for note in _changes(_read_figure(old), _read_figure(new)) or []]


def _read_figure(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or not isinstance(data.get("nodes", []), list):
        return None
    nodes = {
        str(node["id"]): node
        for node in data.get("nodes") or []
        if isinstance(node, dict) and "id" in node
    }

    def end(value: Any) -> str:
        value = str(value)
        return value if value in nodes else value.rsplit(".", 1)[0]

    edges = {}
    for edge in data.get("edges") or []:
        if isinstance(edge, dict) and "from" in edge and "to" in edge:
            edges[(end(edge["from"]), end(edge["to"]))] = edge
    groups = {
        str(group["id"]): group
        for group in data.get("groups") or []
        if isinstance(group, dict) and "id" in group
    }
    # A line that branches, by its id: the pairs of parts its branches join, and its hub.
    nets = {}
    for net in data.get("nets") or []:
        if isinstance(net, dict) and net.get("id") and net.get("sources") and net.get("targets"):
            merge = net.get("kind") == "merge"
            sources = [end(item) for item in net["sources"]]
            targets = [end(item) for item in net["targets"]]
            hub = targets[0] if merge else sources[0]
            branches = sources if merge else targets
            pairs = {(item, hub) if merge else (hub, item) for item in branches}
            nets[str(net["id"])] = {"net": net, "hub": hub, "merge": merge, "pairs": pairs}
    rest = {
        key: value
        for key, value in data.items()
        if key not in {"nodes", "edges", "groups", "nets", "shapes"}
    }
    drawn = data.get("shapes") if isinstance(data.get("shapes"), list) else []
    return {
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
        "nets": nets,
        "rest": rest,
        "drawn": drawn,
    }


def _shape_called(shape: Any) -> str:
    """A shape drawn over a figure as the activity names it: "an arrow", "a highlight ring"."""

    from flexo.freeform import LABELS

    kind = shape.get("kind") if isinstance(shape, dict) else None
    label = LABELS.get(str(kind), "Shape").lower()
    return f"{'an' if label[:1] in 'aeiou' else 'a'} {label}"


def _changes(old: dict[str, Any] | None, new: dict[str, Any] | None) -> list[dict] | None:
    """What changed between two readings of a figure file, a few notes at most."""

    if old is None or new is None:
        return None
    old = _same_shapes(old, new)

    def name(node: dict[str, Any]) -> str:
        words = re.sub(r"\s+", " ", str(node.get("label") or "")).strip()
        if words:
            return f"\u201c{words}\u201d"
        kind = str(node.get("kind") or "block")
        return "a shape" if kind == "block" else f"a {kind.replace('-', ' ')}"

    def called(identifier: str) -> str:
        node = new["nodes"].get(identifier) or old["nodes"].get(identifier) or {}
        return name(node)

    notes: list[dict[str, Any]] = []
    added = [key for key in new["nodes"] if key not in old["nodes"]]
    gone = [key for key in old["nodes"] if key not in new["nodes"]]
    if len(added) > 2:
        notes.append({"text": f"added {len(added)} shapes", "where": None})
    else:
        notes += [{"text": f"added {called(key)}", "where": {"id": key}} for key in added]
    if len(gone) > 2:
        notes.append({"text": f"deleted {len(gone)} shapes", "where": None})
    else:
        notes += [{"text": f"deleted {called(key)}", "where": None} for key in gone]
    for key, node in new["nodes"].items():
        was = old["nodes"].get(key)
        if was is None or was == node:
            continue
        before, after = str(was.get("label") or "").strip(), str(node.get("label") or "").strip()
        if before != after:
            text = (
                f"named {name(was)} \u201c{after}\u201d"
                if not before
                else f"emptied {name(was)}"
                if not after
                else f"renamed {name(was)} to {name(node)}"
            )
        elif was.get("kind") != node.get("kind"):
            kind = str(node.get("kind") or "block").replace("-", " ")
            text = f"made {name(was)} a {kind}"
        else:
            text = f"changed {name(node)}"
        notes.append({"text": text, "where": {"id": key}})
    # A part there before put into a line (let go on it): said as that, not as the lines.
    kept = [key for key in new["nodes"] if key in old["nodes"]]
    spliced = [
        (pair, key)
        for pair in old["edges"]
        if pair not in new["edges"]
        for key in kept
        if key not in pair
        and (pair[0], key) in new["edges"]
        and (key, pair[1]) in new["edges"]
        and ((pair[0], key) not in old["edges"] or (key, pair[1]) not in old["edges"])
    ]
    for pair, key in spliced:
        notes.append(
            {
                "text": f"put {called(key)} between {called(pair[0])} and {called(pair[1])}",
                "where": {"id": key},
            }
        )
    told = {(pair[0], key) for pair, key in spliced} | {(key, pair[1]) for pair, key in spliced}
    # Lines joined into one (a net), or one parted into lines: said as that, not line by line.
    for key, net in new["nets"].items():
        was = old["nets"].get(key)
        joined = net["pairs"] & set(old["edges"])
        way = "into" if net["merge"] else "out of"
        if was is None and joined:
            notes.append({"text": f"joined the lines {way} {called(net['hub'])}", "where": None})
            told |= joined
        elif was is None:
            notes.append({"text": f"added a line {way} {called(net['hub'])}", "where": None})
        elif was["net"] != net["net"]:
            notes.append({"text": f"changed the line {way} {called(net['hub'])}", "where": None})
            told |= (net["pairs"] ^ was["pairs"])
    for key, net in old["nets"].items():
        if key in new["nets"]:
            continue
        parted = net["pairs"] & set(new["edges"])
        way = "into" if net["merge"] else "out of"
        verb = "separated" if parted else "removed"
        notes.append({"text": f"{verb} the line {way} {called(net['hub'])}", "where": None})
        told |= parted
    # Lines: a line between two parts made or taken away (not those that went with a part,
    # nor one joined up round a part taken out of it).
    for pair, edge in new["edges"].items():
        rejoined = any(
            (pair[0], key) in old["edges"] and (key, pair[1]) in old["edges"] for key in gone
        )
        if pair not in old["edges"] and not set(pair) & set(added) and not rejoined:
            if pair in told:
                continue
            notes.append(
                {"text": f"connected {called(pair[0])} to {called(pair[1])}", "where": None}
            )
        elif pair in old["edges"] and old["edges"][pair] != edge:
            notes.append(
                {
                    "text": f"changed the line from {called(pair[0])} to {called(pair[1])}",
                    "where": None,
                }
            )
    for pair in old["edges"]:
        # (A line a new part was put into runs on through it: nothing was taken away.)
        through = any(
            (pair[0], key) in new["edges"] and (key, pair[1]) in new["edges"] for key in added
        )
        if pair not in new["edges"] and not set(pair) & set(gone) and not through:
            if any(pair == each for each, _ in spliced) or pair in told:
                continue
            notes.append(
                {
                    "text": f"removed the line from {called(pair[0])} to {called(pair[1])}",
                    "where": None,
                }
            )
    if spliced:
        pass  # (its place among the parts is the line's: said already)
    elif not added and not gone and _order(old) != _order(new):
        moved = [
            key
            for key in new["nodes"]
            if [item for item in _order(old) if item != key]
            == [item for item in _order(new) if item != key]
        ]
        if len(moved) == 1:
            notes.append({"text": f"moved {called(moved[0])}", "where": {"id": moved[0]}})
        else:
            notes.append({"text": "rearranged the figure", "where": None})
    elif old["groups"] != new["groups"] and not added and not gone:
        notes.append({"text": "rearranged the figure", "where": None})
    # What is drawn over it: one shape added or deleted by its name ("added an arrow").
    was, now = old.get("drawn") or [], new.get("drawn") or []
    if was != now:
        if len(now) == len(was) + 1:
            shape = next((item for item in now if item not in was), now[-1])
            notes.append({"text": f"added {_shape_called(shape)}", "where": None})
        elif len(now) == len(was) - 1:
            shape = next((item for item in was if item not in now), was[-1])
            notes.append({"text": f"deleted {_shape_called(shape)}", "where": None})
        else:
            notes.append({"text": "edited the shapes drawn over it", "where": None})
    if old["rest"] != new["rest"]:
        notes.append({"text": "changed the figure's settings", "where": None})
    return notes[:4] if notes else None


def _same_shapes(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """``old`` with each shape whose id alone has changed -- a new shape's made from the words
    typed in it, say -- under its new id: the same shape, not one deleted and another added
    (an id is the file's business, not news)."""

    gone = [key for key in old["nodes"] if key not in new["nodes"]]
    added = [key for key in new["nodes"] if key not in old["nodes"]]

    def without_id(node: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in node.items() if key != "id"}

    ids: dict[str, str] = {}
    for key in gone:
        twin = next(
            (
                item
                for item in added
                if item not in ids.values()
                and without_id(new["nodes"][item]) == without_id(old["nodes"][key])
            ),
            None,
        )
        if twin is not None:
            ids[key] = twin
    if not ids:
        return old

    def swap(value: Any) -> Any:
        if isinstance(value, str):
            head, dot, tail = value.partition(".")
            return ids[head] + dot + tail if head in ids else value
        if isinstance(value, (list, tuple, set)):
            return type(value)(swap(item) for item in value)
        if isinstance(value, dict):
            return {swap(key): swap(item) for key, item in value.items()}
        return value

    nodes = {
        ids.get(key, key): {**node, "id": ids.get(key, key)} for key, node in old["nodes"].items()
    }
    parts = {part: swap(old[part]) for part in ("edges", "groups", "nets", "drawn") if part in old}
    return {**old, "nodes": nodes, **parts}


def _order(figure: dict[str, Any]) -> list[str]:
    """The parts as the figure lays them out, in turn: through its groups from the root (or,
    with none written, as the file lists them)."""

    groups, nodes = figure["groups"], figure["nodes"]
    root = str((figure["rest"].get("figure") or {}).get("root") or "root")
    held = {str(child) for group in groups.values() for child in group.get("children") or []}
    top = (
        [str(child) for child in groups[root].get("children") or []]
        if root in groups
        else [key for key in [*groups, *nodes] if key not in held]
    )
    found: list[str] = []

    def walk(items: list[str], seen: set[str]) -> None:
        for item in items:
            if item in nodes:
                found.append(item)
            elif item in groups and item not in seen:
                walk([str(child) for child in groups[item].get("children") or []], seen | {item})

    walk(top, {root})
    return found
