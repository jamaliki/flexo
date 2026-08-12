"""Independent geometric, publication, and editable-SVG linting."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from flexo.compiler import Compilation
from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.geometry import Rect, segments
from flexo.style import STYLES, LayoutStyle
from flexo.svg import INKSCAPE_NS, SVG_NS


@dataclass(frozen=True, slots=True)
class LintReport:
    diagnostics: tuple[Diagnostic, ...]

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise FlexoError(self.errors)

    def format(self) -> str:
        return "\n".join(item.format() for item in self.diagnostics) or "ok: no diagnostics"


def lint_compilation(
    compilation: Compilation,
    *,
    style: LayoutStyle | None = None,
) -> LintReport:
    layout_style = style or STYLES[compilation.measured.semantic.style]
    diagnostics = [
        *_fitted_diagnostics(compilation),
        *_routing_diagnostics(compilation, layout_style),
        *_svg_diagnostics(compilation),
        *_publication_diagnostics(compilation, layout_style),
    ]
    return LintReport(tuple(diagnostics))


def lint_svg(svg_text: str) -> LintReport:
    return LintReport(_structural_svg_diagnostics(svg_text, expected_ids=()))


def _fitted_diagnostics(
    compilation: Compilation,
) -> tuple[Diagnostic, ...]:
    fitted = compilation.fitted
    diagnostics: list[Diagnostic] = []
    nodes = {node.measured.spec.id: node.bounds for node in fitted.nodes}
    groups = {group.measured.spec.id: group for group in fitted.groups}
    for group in fitted.groups:
        spec = group.measured.spec
        child_bounds = [
            nodes[child_id] if child_id in nodes else groups[child_id].bounds
            for child_id in spec.children
        ]
        for child_id, bounds in zip(spec.children, child_bounds, strict=True):
            if not group.content_bounds.contains_rect(bounds):
                diagnostics.append(
                    Diagnostic(
                        "layout.child.outside",
                        "Child lies outside its parent content bounds.",
                        entity_id=child_id,
                    )
                )
        if spec.collision_policy == "disjoint":
            for (first_id, first), (second_id, second) in combinations(
                zip(spec.children, child_bounds, strict=True), 2
            ):
                if first.intersects(second):
                    diagnostics.append(
                        Diagnostic(
                            "layout.sibling.overlap",
                            f'Overlaps sibling "{second_id}".',
                            entity_id=first_id,
                        )
                    )
    for node in fitted.nodes:
        metrics = node.measured.label
        if metrics.width > node.bounds.width + 1e-6 or metrics.height > node.bounds.height + 1e-6:
            diagnostics.append(
                Diagnostic(
                    "layout.text.overflow",
                    "Measured label does not fit its component.",
                    entity_id=node.measured.spec.id,
                )
            )
    canvas = Rect(0.0, 0.0, fitted.canvas_size.width, fitted.canvas_size.height)
    root = fitted.group(fitted.measured.semantic.root)
    if not canvas.contains_rect(root.bounds):
        diagnostics.append(
            Diagnostic(
                "layout.canvas.clipped",
                "Root group exceeds the canvas.",
                entity_id=root.measured.spec.id,
            )
        )
    return tuple(diagnostics)


def _routing_diagnostics(
    compilation: Compilation,
    style: LayoutStyle,
) -> tuple[Diagnostic, ...]:
    routed = compilation.routed
    diagnostics: list[Diagnostic] = []
    canvas = Rect(0.0, 0.0, routed.fitted.canvas_size.width, routed.fitted.canvas_size.height)
    for edge in routed.edges:
        source = routed.fitted.node(edge.spec.source.node_id).port(edge.spec.source.port_name)
        target = routed.fitted.node(edge.spec.target.node_id).port(edge.spec.target.port_name)
        if not edge.centerline or edge.centerline[0] != source.position:
            diagnostics.append(
                Diagnostic(
                    "routing.source.mismatch",
                    "Centerline misses source port.",
                    entity_id=edge.spec.id,
                )
            )
        if not edge.centerline or edge.centerline[-1] != target.position:
            diagnostics.append(
                Diagnostic(
                    "routing.target.mismatch",
                    "Centerline misses target port.",
                    entity_id=edge.spec.id,
                )
            )
        for segment in segments(edge.centerline):
            if not segment.orthogonal:
                diagnostics.append(
                    Diagnostic(
                        "routing.non-orthogonal",
                        "Route contains a diagonal.",
                        entity_id=edge.spec.id,
                    )
                )
            for node in routed.fitted.nodes:
                if node.measured.spec.id in {edge.spec.source.node_id, edge.spec.target.node_id}:
                    continue
                if segment.intersects_rect_interior(node.bounds):
                    diagnostics.append(
                        Diagnostic(
                            "routing.obstacle.intersection",
                            f'Route crosses component "{node.measured.spec.id}".',
                            entity_id=edge.spec.id,
                        )
                    )
        center_length = sum(segment.length for segment in segments(edge.centerline))
        shaft_length = sum(segment.length for segment in segments(edge.shaft))
        if abs(center_length - shaft_length - style.arrow_length.points) > 1e-5:
            diagnostics.append(
                Diagnostic(
                    "routing.marker.clearance",
                    "Visible shaft does not reserve the configured arrow length.",
                    entity_id=edge.spec.id,
                )
            )
        if any(not canvas.contains_point(point) for point in edge.centerline):
            diagnostics.append(
                Diagnostic(
                    "routing.canvas.clipped",
                    "Route leaves the canvas.",
                    entity_id=edge.spec.id,
                )
            )
    return tuple(diagnostics)


def _svg_diagnostics(compilation: Compilation) -> tuple[Diagnostic, ...]:
    semantic = compilation.measured.semantic
    expected_ids = tuple(
        [group.id for group in semantic.groups]
        + [node.id for node in semantic.nodes]
        + [edge.id for edge in semantic.edges]
    )
    return _structural_svg_diagnostics(compilation.document.text, expected_ids)


def _structural_svg_diagnostics(
    svg_text: str,
    expected_ids: tuple[str, ...],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as error:
        return (Diagnostic("svg.xml.invalid", str(error)),)
    elements = tuple(root.iter())
    ids = [item.get("id") for item in elements if item.get("id")]
    for item_id, count in sorted(Counter(ids).items()):
        if count > 1:
            diagnostics.append(
                Diagnostic("svg.id.duplicate", "SVG ID is not unique.", entity_id=item_id)
            )
    for expected_id in expected_ids:
        if expected_id not in ids:
            diagnostics.append(
                Diagnostic(
                    "svg.id.missing",
                    "Semantic entity is absent from SVG.",
                    entity_id=expected_id,
                )
            )
    if any(_local_name(item.tag) == "foreignObject" for item in elements):
        diagnostics.append(
            Diagnostic("svg.foreign-object", "foreignObject is not editable enough.")
        )
    text_elements = [item for item in elements if _local_name(item.tag) == "text"]
    if expected_ids and not text_elements:
        diagnostics.append(
            Diagnostic("svg.text.flattened", "Editable master contains no live text.")
        )
    layer_attribute = f"{{{INKSCAPE_NS}}}groupmode"
    label_attribute = f"{{{INKSCAPE_NS}}}label"
    for item in elements:
        if item.get(layer_attribute) == "layer" and not item.get(label_attribute):
            diagnostics.append(
                Diagnostic(
                    "svg.layer.unnamed",
                    "Inkscape layer lacks a label.",
                    entity_id=item.get("id"),
                )
            )
        for attribute in ("href", f"{{{SVG_NS}}}href"):
            reference = item.get(attribute)
            if reference and not reference.startswith(("data:", "#")):
                diagnostics.append(
                    Diagnostic(
                        "svg.resource.external",
                        f'External resource "{reference}" is not portable.',
                        entity_id=item.get("id"),
                    )
                )
    if _tree_depth(root) > 10:
        diagnostics.append(
            Diagnostic(
                "svg.hierarchy.deep",
                "SVG object hierarchy exceeds 10 levels.",
                Severity.WARNING,
            )
        )
    return tuple(diagnostics)


def _publication_diagnostics(
    compilation: Compilation,
    style: LayoutStyle,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    if style.typography.size.points < style.typography.minimum_size.points:
        diagnostics.append(
            Diagnostic("publication.type.small", "Type is below the configured minimum.")
        )
    if compilation.document.width_mm <= 0.0 or compilation.document.height_mm <= 0.0:
        diagnostics.append(
            Diagnostic(
                "publication.size.invalid",
                "Physical dimensions must be positive.",
            )
        )
    if style.connector_width.points < 0.5:
        diagnostics.append(
            Diagnostic(
                "publication.stroke.thin",
                "Connector stroke may disappear in print.",
                Severity.WARNING,
            )
        )
    return tuple(diagnostics)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _tree_depth(root: ET.Element) -> int:
    children = list(root)
    return 1 if not children else 1 + max(_tree_depth(child) for child in children)
