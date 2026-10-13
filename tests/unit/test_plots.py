"""Plots in a figure: a function's matplotlib figure, drawn at its shape's size in the
figure's type -- or an empty box that says why not."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import flexo
from flexo import compile_figure
from flexo.plots import plot_size, plot_style
from flexo.serialization import parse_figure
from flexo.studio import code_allowed
from flexo.studio.figure_edit import apply, plot_functions
from flexo.studio.figure_parts import catalogue

PLOTS = '''
import matplotlib.pyplot as plt

CALLS = []


def loss():
    CALLS.append("loss")
    with open(__file__ + ".calls", "a") as said:
        said.write("loss\\n")
    figure, axes = plt.subplots()
    axes.plot([1, 2, 3, 4], [2.0, 1.2, 0.7, 0.5], label="Adam")
    axes.set_xlabel("Epoch")
    axes.set_ylabel("Loss")
    axes.legend()
    return figure


def not_a_figure():
    return 3


def fails():
    raise ValueError("no data")


def _helper():
    return None
'''


def _figure(source: Path, function: str = "loss", **node: object) -> flexo.FigureSpec:
    return parse_figure(
        {
            "figure": {"id": "plotted", "style": "paper"},
            "nodes": [
                {"id": "p", "kind": "plot", "width": "60mm", "height": "40mm", **node,
                 "properties": {"source": str(source), "function": function}},
                {"id": "b", "label": "Model"},
            ],
        }
    )


def _calls(source: Path) -> int:
    said = Path(str(source) + ".calls")
    return len(said.read_text().split()) if said.exists() else 0


def test_a_plot_is_drawn_at_its_shapes_size_in_the_figures_type(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    source = tmp_path / "plots.py"
    source.write_text(PLOTS)
    compiled = compile_figure(_figure(source))
    assert not compiled.measured.diagnostics
    # (However deep matplotlib nests its own groups, the plot is one object of the figure.)
    codes = {item.code for item in flexo.lint_compilation(compiled).diagnostics}
    assert "svg.hierarchy.deep" not in codes
    box = next(n.bounds for n in compiled.fitted.nodes if n.measured.spec.id == "p")
    assert (box.width, box.height) == pytest.approx((170.08, 113.39), abs=0.01)
    svg = compiled.document.text
    window = re.search(r'<svg[^>]*id="p\.artwork"[^>]*>', svg)[0]
    # Laid out for exactly that size, so nothing is scaled: its words are the figure's size
    # (8 points in this theme) and in its family, and they are still words.
    assert re.search(r'viewBox="0 0 170\.07\d* 113\.38\d*"', window)
    words = re.findall(r"<text[^>]*style=\"([^\"]*)\"[^>]*>\s*(?:<[^>]+>)*([^<]+)", svg)
    said = {text.strip(): style for style, text in words}
    assert "Epoch" in said and "Loss" in said and "Adam" in said
    assert "font-size: 8px" in said["Epoch"] and "Figtree" in said["Epoch"]
    # In the palette's first tone, as the figure's shapes are.
    palette = flexo.resolve_palette("paper")
    assert palette.get("tone-1-stroke") in svg


def test_a_plot_is_drawn_off_the_main_thread_as_a_studio_draws_it(tmp_path: Path) -> None:
    """In the Mac app a plot failed once its folder was trusted: matplotlib chose the Mac's
    own backend, which makes no figure outside the main thread, where a studio draws."""

    import threading

    pytest.importorskip("matplotlib")
    import matplotlib

    source = tmp_path / "plots.py"
    source.write_text(PLOTS)
    before = matplotlib.get_backend()
    said: list[object] = []

    def draw() -> None:
        try:
            compiled = compile_figure(_figure(source))
            said.append([item.message for item in compiled.measured.diagnostics])
        except Exception as error:  # (told to the test, not lost with the thread)
            said.append(error)

    thread = threading.Thread(target=draw)
    thread.start()
    thread.join(60)
    assert said == [[]]
    # And on the main thread the backend a person had is theirs again after.
    compile_figure(_figure(source, width="71mm"))
    assert matplotlib.get_backend().lower() in {before.lower(), "agg"}


def test_a_plot_is_drawn_again_only_when_something_it_is_drawn_from_changes(
    tmp_path: Path,
) -> None:
    pytest.importorskip("matplotlib")
    source = tmp_path / "plots.py"
    source.write_text(PLOTS)
    compile_figure(_figure(source))
    compile_figure(_figure(source))
    # (Once for the figure, however often it is drawn: every edit draws it.)
    assert _calls(source) == 1
    compile_figure(_figure(source, width="70mm"))
    assert _calls(source) == 2
    source.write_text(PLOTS + "\n# changed\n")
    compile_figure(_figure(source, width="70mm"))
    assert _calls(source) == 3


def test_a_plot_that_is_not_drawn_is_an_empty_box_that_says_why(tmp_path: Path) -> None:
    source = tmp_path / "plots.py"
    source.write_text(PLOTS)

    def said(figure: flexo.FigureSpec) -> tuple[str, str]:
        compiled = compile_figure(figure)
        (diagnostic,) = compiled.measured.diagnostics
        drawn = compiled.document.text
        assert 'id="p.placeholder"' in drawn and 'id="b.label"' in drawn
        assert diagnostic.entity_id == "p" and diagnostic.severity is flexo.Severity.WARNING
        return diagnostic.code, diagnostic.message

    # In a folder its person has not trusted, the file is not run at all.
    allowed = code_allowed.set(False)
    try:
        code, message = said(_figure(source))
    finally:
        code_allowed.reset(allowed)
    assert code == "code.untrusted" and "trust the folder" in message and _calls(source) == 0
    assert said(_figure(tmp_path / "gone.py"))[0] == "plot.source.unreadable"
    assert said(_figure(source, ""))[0] == "plot.source.missing"
    pytest.importorskip("matplotlib")
    assert said(_figure(source, "nothing"))[0] == "plot.function.missing"
    code, message = said(_figure(source, "not_a_figure"))
    assert code == "plot.function.result" and "must return a matplotlib figure" in message
    code, message = said(_figure(source, "fails"))
    assert code == "plot.function.failed" and "ValueError: no data" in message


def test_a_plots_size_and_look() -> None:
    style = flexo.resolve_style("paper")
    plain = flexo.NodeSpec("p", "plot")
    assert (plot_size(plain, style).width, plot_size(plain, style).height) == pytest.approx(
        (170.08, 113.39), abs=0.01
    )
    tall = parse_figure(
        {"figure": {"id": "f"}, "nodes": [{"id": "p", "kind": "plot", "height": "30mm"}]}
    )
    size = plot_size(tall.node("p"), style)
    assert size.width == pytest.approx(size.height * 1.5)
    pytest.importorskip("matplotlib")
    look = plot_style(style, flexo.resolve_palette("paper"))
    assert look["font.family"][0] == style.typography.family
    assert look["font.size"] == style.typography.size.points and look["svg.fonttype"] == "none"
    assert not look["axes.spines.top"]


def test_the_studio_offers_a_plot_and_names_its_first_function(tmp_path: Path) -> None:
    (tmp_path / "plots.py").write_text(PLOTS)
    assert plot_functions(tmp_path / "plots.py") == ["loss", "not_a_figure", "fails"]
    assert plot_functions(tmp_path / "gone.py") == []
    part = catalogue()["parts"]["plot"]
    assert part["needs_file"] and not part["styled"]
    keys = [field["key"] for field in part["fields"]]
    assert keys[:2] == ["properties.source", "properties.function"]
    assert next(f for f in part["fields"] if f["type"] == "file")["types"] == ["python"]
    text = "figure: {id: f, style: paper}\nnodes:\n- {id: a, label: A}\n"
    action = {"do": "add", "kind": "plot", "node": {"properties": {"source": "plots.py"}}}
    made = yaml.safe_load(apply(text, action, base=tmp_path)["text"])["nodes"][-1]
    assert made == {
        "id": "plot", "kind": "plot", "properties": {"source": "plots.py", "function": "loss"},
    }
