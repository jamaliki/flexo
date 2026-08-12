from __future__ import annotations

import yaml

from flexo.builder import Figure, NodeHandle
from flexo.compiler import compile_figure
from flexo.gallery import vertical_slice
from flexo.serialization import dump_figure, parse_figure
from flexo.units import pt


def test_builder_scopes_ids_and_connects_handles() -> None:
    with Figure("builder", width=pt(180)) as figure:  # noqa: SIM117
        with figure.module("encoder") as module:
            source = module.feature_strip("source", label="Features")
            target = module.mlp("target", input=source)
            assert isinstance(target, NodeHandle)
    semantic = figure.spec
    assert {node.id for node in semantic.nodes} == {"encoder.source", "encoder.target"}
    assert str(semantic.edges[0].source) == "encoder.source.output"
    assert str(semantic.edges[0].target) == "encoder.target.input"


def test_builder_round_trips_through_schema_document() -> None:
    original = vertical_slice()
    document = yaml.safe_load(dump_figure(original))
    parsed = parse_figure(document)
    assert parsed == original


def test_vertical_slice_compiles_without_coordinates() -> None:
    compiled = compile_figure(vertical_slice())
    assert len(compiled.routed.edges) == 8
    assert "cryo.residual" in compiled.document.text
