"""Independent geometric, publication, and editable-SVG linting."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from flexo.compiler import Compilation
from flexo.components import TRANSPARENT_KINDS
from flexo.diagnostics import Diagnostic, FlexoError, Severity
from flexo.geometry import Point, Rect, Segment, segments
from flexo.hierarchy import bounded_owner, parent_map
from flexo.style import STYLES, LayoutStyle
from flexo.svg import INKSCAPE_NS, SVG_NS, local_name

_CONTAINMENT_TOLERANCE = 1e-6


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
    diagnostics: list[Diagnostic] = list(fitted.diagnostics)
    nodes = {node.measured.spec.id: node.bounds for node in fitted.nodes}
    groups = {group.measured.spec.id: group for group in fitted.groups}
    for group in fitted.groups:
        spec = group.measured.spec
        child_bounds = [
            nodes[child_id] if child_id in nodes else groups[child_id].bounds
            for child_id in spec.children
        ]
        content = group.content_bounds.inflated(_CONTAINMENT_TOLERANCE)
        for child_id, bounds in zip(spec.children, child_bounds, strict=True):
            if not content.contains_rect(bounds):
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
    owner_bounds = {
        edge.spec.id: _routing_owner_bounds(
            compilation,
            edge.spec.source.node_id,
            edge.spec.target.node_id,
        )
        for edge in routed.edges
    }
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
                if node.measured.spec.kind in TRANSPARENT_KINDS:
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
        # Arrow length once, standoff twice: the shaft gives up air at both ends.
        reserved = style.arrow_length.points + 2.0 * style.connector_standoff.points
        if abs(center_length - shaft_length - reserved) > 1e-5:
            diagnostics.append(
                Diagnostic(
                    "routing.marker.clearance",
                    "Visible shaft does not reserve the arrow length and both standoffs.",
                    entity_id=edge.spec.id,
                )
            )
        center_segments = segments(edge.centerline)
        shaft_segments = segments(edge.shaft)
        if center_segments and shaft_segments:
            center_final = center_segments[-1]
            shaft_final = shaft_segments[-1]
            if center_final.horizontal != shaft_final.horizontal:
                diagnostics.append(
                    Diagnostic(
                        "routing.marker.orientation",
                        "Arrow marker orientation does not match the final approach segment.",
                        entity_id=edge.spec.id,
                    )
                )
        if center_segments:
            first = center_segments[0]
            final = center_segments[-1]
            source_vector = source.side.vector
            target_vector = target.side.vector
            if not _same_direction(first, source_vector.x, source_vector.y):
                diagnostics.append(
                    Diagnostic(
                        "routing.source.direction",
                        "Route does not depart in the source port direction.",
                        entity_id=edge.spec.id,
                    )
                )
            if not _same_direction(final, -target_vector.x, -target_vector.y):
                diagnostics.append(
                    Diagnostic(
                        "routing.target.direction",
                        "Route does not arrive opposite the target port direction.",
                        entity_id=edge.spec.id,
                    )
                )
            if first.length + 1e-5 < style.route_clearance.points:
                diagnostics.append(
                    Diagnostic(
                        "routing.source.clearance",
                        "Route turns before clearing the source component.",
                        entity_id=edge.spec.id,
                    )
                )
            target_clearance = style.arrival_clearance.points
            if final.length + 1e-5 < target_clearance:
                diagnostics.append(
                    Diagnostic(
                        "routing.target.clearance",
                        "Route turns before the arrow clears the target component.",
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
        if any(
            not owner_bounds[edge.spec.id].contains_point(point)
            for point in edge.centerline
        ):
            diagnostics.append(
                Diagnostic(
                    "routing.container.clipped",
                    "Route leaves its owning editorial container.",
                    entity_id=edge.spec.id,
                )
            )
    diagnostics.extend(_net_routing_diagnostics(compilation, style, canvas))
    diagnostics.extend(_track_separation_diagnostics(compilation, style))
    return tuple(diagnostics)


def _net_routing_diagnostics(
    compilation: Compilation,
    style: LayoutStyle,
    canvas: Rect,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    fitted = compilation.routed.fitted
    target_clearance = style.arrival_clearance.points
    for net in compilation.routed.nets:
        # What the router had to overrule -- an unreachable rail_at, say -- is
        # reported here rather than at route time, so one clamped hint never
        # costs the author their figure.
        diagnostics.extend(net.diagnostics)
        routes = (
            net.rail,
            *(stem.centerline for stem in net.source_stems + net.target_stems),
        )
        for route in routes:
            for segment in segments(route):
                if not segment.orthogonal:
                    diagnostics.append(
                        Diagnostic(
                            "routing.net.non-orthogonal",
                            "Net contains a diagonal segment.",
                            entity_id=net.spec.id,
                        )
                    )
            if any(not canvas.contains_point(point) for point in route):
                diagnostics.append(
                    Diagnostic(
                        "routing.net.canvas.clipped",
                        "Net leaves the canvas.",
                        entity_id=net.spec.id,
                    )
                )
        for stem in net.source_stems:
            expected = fitted.node(stem.port.node_id).port(stem.port.port_name).position
            if not stem.centerline or stem.centerline[0] != expected:
                diagnostics.append(
                    Diagnostic(
                        "routing.net.source.mismatch",
                        "Source stem misses its authored port.",
                        entity_id=net.spec.id,
                    )
                )
            if stem.arrow_end:
                diagnostics.append(
                    Diagnostic(
                        "routing.net.source.arrow",
                        "Source stems must not carry arrowheads.",
                        entity_id=net.spec.id,
                    )
                )
        for stem in net.target_stems:
            expected = fitted.node(stem.port.node_id).port(stem.port.port_name).position
            if not stem.centerline or stem.centerline[-1] != expected:
                diagnostics.append(
                    Diagnostic(
                        "routing.net.target.mismatch",
                        "Target stem misses its authored port.",
                        entity_id=net.spec.id,
                    )
                )
            if not stem.arrow_end:
                diagnostics.append(
                    Diagnostic(
                        "routing.net.target.arrow",
                        "Every target stem must carry an arrowhead.",
                        entity_id=net.spec.id,
                    )
                )
            stem_segments = segments(stem.centerline)
            if stem_segments and stem_segments[-1].length + 1e-5 < target_clearance:
                diagnostics.append(
                    Diagnostic(
                        "routing.net.target.clearance",
                        "Net turns before the arrow clears its target component.",
                        entity_id=net.spec.id,
                    )
                )
        diagnostics.extend(_net_obstacle_diagnostics(compilation, net.spec.id, routes))
    return tuple(diagnostics)


def _net_obstacle_diagnostics(
    compilation: Compilation,
    net_id: str,
    routes: tuple[tuple[Point, ...], ...],
) -> tuple[Diagnostic, ...]:
    net = compilation.routed.net(net_id)
    diagnostics = []
    for route_index, route in enumerate(routes):
        endpoint_id = None
        if route_index > 0:
            stems = net.source_stems + net.target_stems
            endpoint_id = stems[route_index - 1].port.node_id
        for node in compilation.routed.fitted.nodes:
            if node.measured.spec.id == endpoint_id:
                continue
            if node.measured.spec.kind in TRANSPARENT_KINDS:
                continue
            if any(
                segment.intersects_rect_interior(node.bounds)
                for segment in segments(route)
            ):
                diagnostics.append(
                    Diagnostic(
                        "routing.net.obstacle.intersection",
                        f'Net crosses component "{node.measured.spec.id}".',
                        entity_id=net_id,
                    )
                )
    return tuple(diagnostics)


def _track_separation_diagnostics(
    compilation: Compilation,
    style: LayoutStyle,
) -> tuple[Diagnostic, ...]:
    diagnostics = []
    minimum = style.port_spacing.points
    routes = [(edge.spec.id, edge.centerline) for edge in compilation.routed.edges]
    for net in compilation.routed.nets:
        routes.append((net.spec.id, net.rail))
        routes.extend((net.spec.id, stem.centerline) for stem in net.source_stems)
        routes.extend((net.spec.id, stem.centerline) for stem in net.target_stems)
    for (first_id, first_route), (second_id, second_route) in combinations(routes, 2):
        if first_id == second_id:
            continue
        crossing = any(
            _segments_cross(first, second)
            for first in segments(first_route)
            for second in segments(second_route)
        )
        if crossing:
            diagnostics.append(
                Diagnostic(
                    "routing.connector.crossing",
                    f'Route crosses "{second_id}".',
                    Severity.WARNING,
                    entity_id=first_id,
                )
            )
        violation = any(
            _parallel_tracks_too_close(first, second, minimum)
            for first in segments(first_route)
            for second in segments(second_route)
        )
        if violation:
            diagnostics.append(
                Diagnostic(
                    "routing.track.separation",
                    f'Parallel route is too close to "{second_id}".',
                    entity_id=first_id,
                )
            )
    return tuple(diagnostics)


def _segments_cross(first: Segment, second: Segment) -> bool:
    if first.horizontal == second.horizontal:
        return False
    horizontal, vertical = (first, second) if first.horizontal else (second, first)
    x_low, x_high = sorted((horizontal.start.x, horizontal.end.x))
    y_low, y_high = sorted((vertical.start.y, vertical.end.y))
    return (
        x_low + 1e-7 < vertical.start.x < x_high - 1e-7
        and y_low + 1e-7 < horizontal.start.y < y_high - 1e-7
    )


def _parallel_tracks_too_close(first: Segment, second: Segment, minimum: float) -> bool:
    if first.horizontal and second.horizontal:
        distance = abs(first.start.y - second.start.y)
        overlap = _interval_overlap(first.start.x, first.end.x, second.start.x, second.end.x)
        return overlap > 1e-7 and distance + 1e-7 < minimum
    if first.vertical and second.vertical:
        distance = abs(first.start.x - second.start.x)
        overlap = _interval_overlap(first.start.y, first.end.y, second.start.y, second.end.y)
        return overlap > 1e-7 and distance + 1e-7 < minimum
    return False


def _interval_overlap(first_a: float, first_b: float, second_a: float, second_b: float) -> float:
    first_low, first_high = sorted((first_a, first_b))
    second_low, second_high = sorted((second_a, second_b))
    return max(0.0, min(first_high, second_high) - max(first_low, second_low))


def _routing_owner_bounds(
    compilation: Compilation,
    source_id: str,
    target_id: str,
) -> Rect:
    semantic = compilation.measured.semantic
    owner = bounded_owner(semantic, parent_map(semantic.groups), (source_id, target_id))
    return compilation.fitted.group(owner).bounds


def _svg_diagnostics(compilation: Compilation) -> tuple[Diagnostic, ...]:
    semantic = compilation.measured.semantic
    expected_ids = tuple(
        [group.id for group in semantic.groups]
        + [node.id for node in semantic.nodes]
        + [edge.id for edge in semantic.edges]
        + [net.id for net in semantic.nets]
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
    if any(local_name(item.tag) == "foreignObject" for item in elements):
        diagnostics.append(
            Diagnostic("svg.foreign-object", "foreignObject is not editable enough.")
        )
    text_elements = [item for item in elements if local_name(item.tag) == "text"]
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


def _tree_depth(root: ET.Element) -> int:
    children = list(root)
    return 1 if not children else 1 + max(_tree_depth(child) for child in children)


def _same_direction(segment: Segment, expected_x: float, expected_y: float) -> bool:
    delta_x = segment.end.x - segment.start.x
    delta_y = segment.end.y - segment.start.y
    if expected_x:
        return delta_x * expected_x > 0.0 and abs(delta_y) < 1e-7
    return delta_y * expected_y > 0.0 and abs(delta_x) < 1e-7
