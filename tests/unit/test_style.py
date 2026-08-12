from __future__ import annotations

import pytest

from flexo.diagnostics import FlexoError
from flexo.style import DEFAULT_PALETTE, LayoutStyle


def test_publication_width_preset() -> None:
    assert LayoutStyle().resolve_width("double-column").to("mm") == pytest.approx(180.0)


def test_palette_rejects_unknown_role() -> None:
    with pytest.raises(FlexoError, match="Unknown paint role"):
        DEFAULT_PALETTE.with_overrides({"padding": "pink"})


def test_palette_mapping_is_immutable() -> None:
    with pytest.raises(TypeError):
        DEFAULT_PALETTE.paints["ink"] = "red"  # type: ignore[index]
