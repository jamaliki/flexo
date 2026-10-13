"""Plots in a figure: a function's matplotlib figure, drawn at its shape's size in the
figure's type -- or an empty box that says why not."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

import flexo
from flexo import compile_figure
from flexo.plots import plot_size, plot_style
from flexo.serialization import parse_figure
from flexo.studio import code_allowed
from flexo.studio.figure_edit import apply, apply_to_data, model, plot_functions
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


READS = '''
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

import scale

HERE = Path(__file__).parent
TITLE = (HERE / "title.txt").read_text().strip()


def curve():
    with open(__file__ + ".calls", "a") as said:
        said.write("curve\\n")
    values = np.loadtxt(HERE / "data" / "curve.csv", delimiter=",")
    # (A file of its own making, written and read back, is none of its data.)
    (HERE / "kept.txt").write_text(str(len(values)))
    (HERE / "kept.txt").read_text()
    figure, axes = plt.subplots()
    axes.plot(values)
    axes.set_title(f"{TITLE} by {scale.BY}")
    return figure


def waiting():
    return plt.figure(num=open(HERE / "late.csv").read())
'''


def test_a_plot_is_drawn_again_when_a_file_its_function_read_changes(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    from flexo.plots import files

    source = tmp_path / "reads.py"
    source.write_text(READS)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "curve.csv").write_text("1,2,3\n")
    (tmp_path / "data" / "other.csv").write_text("9\n")
    (tmp_path / "title.txt").write_text("Curve\n")
    (tmp_path / "scale.py").write_text("BY = 2\n")

    def drawn() -> str:
        compiled = compile_figure(_figure(source, "curve"))
        assert not compiled.measured.diagnostics
        return compiled.document.text

    assert "Curve by 2" in drawn()
    drawn()
    assert _calls(source) == 1
    # What it read: the file numpy opened, the one read as its Python was imported, and the
    # module beside it -- not what it wrote, nor a file there it never opened.
    read = {file.relative_to(tmp_path).as_posix() for file in files(source, "curve")}
    assert read == {"reads.py", "data/curve.csv", "title.txt", "scale.py"}
    (tmp_path / "data" / "other.csv").write_text("9,9\n")
    drawn()
    assert _calls(source) == 1
    (tmp_path / "data" / "curve.csv").write_text("1,2,3,5\n")
    drawn()
    assert _calls(source) == 2
    (tmp_path / "title.txt").write_text("Fitted curve\n")
    assert "Fitted curve by 2" in drawn() and _calls(source) == 3
    (tmp_path / "scale.py").write_text("BY = 10\n")
    assert "Fitted curve by 10" in drawn() and _calls(source) == 4
    drawn()
    assert _calls(source) == 4
    # A file it looked for and did not find is waited for: there, the plot is drawn.
    (code,) = (d.code for d in compile_figure(_figure(source, "waiting")).measured.diagnostics)
    assert code == "plot.function.failed" and tmp_path / "late.csv" in files(source, "waiting")
    (tmp_path / "late.csv").write_text("late")
    assert not compile_figure(_figure(source, "waiting")).measured.diagnostics


BESIDE = '''
import pickle

import matplotlib.pyplot as plt

import scale


def curve():
    import late
    import scale as again

    # (Its classes are found by their module, as it runs: one of them is pickled.)
    assert again is scale and isinstance(pickle.loads(pickle.dumps(scale.Kept())), scale.Kept)
    figure, axes = plt.subplots()
    axes.set_title(f"{late.WORD} by {scale.BY}")
    return figure
'''


def test_the_modules_beside_a_plots_file_are_its_own(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    import sys

    for name, by in (("one", 2), ("two", 3)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "scale.py").write_text(f"BY = {by}\n\n\nclass Kept:\n    pass\n")
        (tmp_path / name / "late.py").write_text(f"WORD = 'late in {name}'\n")
        (tmp_path / name / "plots.py").write_text(BESIDE)

    def drawn(name: str, **node: object) -> str:
        compiled = compile_figure(_figure(tmp_path / name / "plots.py", "curve", **node))
        assert [item.message for item in compiled.measured.diagnostics] == []
        return compiled.document.text

    # Each finds the modules beside it -- as it is imported, and as it runs -- never those
    # of the same names beside the other; and they are no one else's after.
    assert "late in one by 2" in drawn("one") and "late in two by 3" in drawn("two")
    assert "late in one by 2" in drawn("one", width="61mm")
    assert "scale" not in sys.modules and "late" not in sys.modules
    # One edited is imported again, with the plot's own file.
    (tmp_path / "one" / "late.py").write_text("WORD = 'later in one'\n")
    (tmp_path / "one" / "scale.py").write_text("BY = 20\n\n\nclass Kept:\n    pass\n")
    assert "later in one by 20" in drawn("one") and "late in two by 3" in drawn("two")


def test_a_studio_watches_the_files_a_figures_plots_are_drawn_from(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    from flexo.studio.figure_kind import FigureKind

    (tmp_path / "plots.py").write_text(
        "from pathlib import Path\n\n"
        "import matplotlib.pyplot as plt\n\n\n"
        "def bars():\n"
        "    numbers = (Path(__file__).parent / 'n.txt').read_text().split()\n"
        "    figure, axes = plt.subplots()\n"
        "    axes.bar([0, 1], [float(n) for n in numbers])\n"
        "    return figure\n"
    )
    (tmp_path / "n.txt").write_text("3 4")
    text = yaml.safe_dump({
        "figure": {"id": "f", "style": "paper"},
        "nodes": [
            {"id": "p", "kind": "plot", "properties": {"source": "plots.py", "function": "bars"}},
            {"id": "q", "kind": "plot", "properties": {"source": "soon.py", "function": "bars"}},
        ],
    })
    drawing = FigureKind().draw({"text": text}, tmp_path)
    # Its Python file and the data it read; and a Python file not there yet, watched for.
    watched = {file.resolve() for file in drawing.files}
    assert watched == {(tmp_path / name).resolve() for name in ("plots.py", "n.txt", "soon.py")}


def test_a_plot_is_run_apart_by_whoever_says_they_run_plots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("matplotlib")
    import flexo.plots

    source = tmp_path / "plots.py"
    source.write_text(PLOTS)
    (tmp_path / "numbers.txt").write_text("1 2")
    asked: list[dict] = []

    def stopped(request: dict) -> dict:
        asked.append(request)
        said = "loss in plots.py took longer than 3 seconds and was stopped."
        return {"said": said, "code": "plot.function.stopped",
                "files": [str(tmp_path / "numbers.txt")]}

    monkeypatch.setattr(flexo.plots, "RUNNER", stopped)
    compiled = compile_figure(_figure(source))
    (diagnostic,) = compiled.measured.diagnostics
    assert (diagnostic.code, diagnostic.entity_id) == ("plot.function.stopped", "p")
    assert diagnostic.message.endswith("took longer than 3 seconds and was stopped.")
    assert 'id="p.placeholder"' in compiled.document.text and _calls(source) == 0
    # Asked with all it takes to draw it elsewhere, as plain values: the file and function,
    # the size, the figure's look, and the folder its data is in.
    (request,) = asked
    style = flexo.resolve_style("paper")
    assert (request["file"], request["function"]) == (str(source.resolve()), "loss")
    assert (request["width"], request["height"]) == pytest.approx((170.08, 113.39), abs=0.01)
    assert request["look"]["font.family"][0] == style.typography.family
    assert request["folder"] == str(tmp_path.resolve())
    # What it says stands till a file changes -- the files it says it read among them --
    # and is not asked for at every drawing.
    compile_figure(_figure(source))
    assert len(asked) == 1
    (tmp_path / "numbers.txt").write_text("1 2 3")
    compile_figure(_figure(source))
    assert len(asked) == 2

    # Its drawing is placed as one made here is, made safe: a script in it is refused.
    def answers(request: dict) -> dict:
        made = flexo.plots.run(request)
        return {**made, "svg": made["svg"].replace(b"</svg>", b"<script>1</script></svg>")}

    monkeypatch.setattr(flexo.plots, "RUNNER", answers)
    compiled = compile_figure(_figure(source, width="61mm"))
    assert [item.code for item in compiled.measured.diagnostics] == ["plot.unplaceable"]
    # And one who has nowhere to run it leaves it to be run here.
    monkeypatch.setattr(flexo.plots, "RUNNER", lambda request: None)
    compiled = compile_figure(_figure(source, width="62mm"))
    assert not compiled.measured.diagnostics and "Epoch" in compiled.document.text


def test_a_plot_run_apart_that_hangs_does_not_hold_up_anothers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    import flexo.plots

    for name in ("slow", "quick"):
        (tmp_path / f"{name}.py").write_text(PLOTS)
    asked, let_go, done = threading.Event(), threading.Event(), threading.Event()

    def runner(request: dict) -> dict:
        if request["file"].endswith("slow.py"):
            asked.set()
            let_go.wait(5)
        return {"said": "loss in plots.py was stopped.", "code": "plot.function.stopped"}

    def slow() -> None:
        compile_figure(_figure(tmp_path / "slow.py"))
        done.set()

    monkeypatch.setattr(flexo.plots, "RUNNER", runner)
    thread = threading.Thread(target=slow)
    thread.start()
    try:
        assert asked.wait(5)
        # (Another folder's, in the app: its runner is not waited on behind this one's.)
        compiled = compile_figure(_figure(tmp_path / "quick.py"))
        assert [item.code for item in compiled.measured.diagnostics] == ["plot.function.stopped"]
        assert not done.is_set()
    finally:
        let_go.set()
        thread.join(10)
    assert done.is_set()


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


def test_a_plots_function_is_chosen_among_those_its_file_offers(tmp_path: Path) -> None:
    from flexo.studio.figure_kind import FigureKind

    (tmp_path / "plots.py").write_text(PLOTS)
    (tmp_path / "more.py").write_text("def accuracy():\n    pass\n\n\ndef loss():\n    pass\n")
    (tmp_path / "other.py").write_text("def first():\n    pass\n\n\ndef second():\n    pass\n")
    (tmp_path / "broken.py").write_text("def (:\n")
    fields = {field["key"]: field for field in catalogue()["parts"]["plot"]["fields"]}
    assert fields["properties.function"]["type"] == "function"
    text = (
        "figure: {id: f, style: paper}\n"
        "nodes:\n"
        "- {id: p, kind: plot, properties: {source: plots.py, function: loss}}\n"
        "- {id: q, kind: plot, properties: {source: broken.py, function: typed}}\n"
        "- {id: a, label: A}\n"
    )
    # The page is given each plot's functions with the figure, read from its file as it is
    # now: none for a file that does not read (its function is typed), nor with no folder.
    offered = {"p": ["loss", "not_a_figure", "fails"]}
    assert model(text, base=tmp_path)["functions"] == offered
    assert model(text)["functions"] == {}
    kind, document = FigureKind(), {"text": text}
    allowed = code_allowed.set(False)
    try:
        assert kind.draw(document, tmp_path).info["model"]["functions"] == offered
    finally:
        code_allowed.reset(allowed)
    assert kind.act(document, {"do": "read"}, tmp_path)["model"]["functions"] == offered
    inline = apply_to_data(yaml.safe_load(text), {"do": "read"}, base=tmp_path)
    assert inline["model"]["functions"] == offered
    (tmp_path / "plots.py").write_text(PLOTS + "\n\ndef added():\n    pass\n")
    assert model(text, base=tmp_path)["functions"] == {"p": [*offered["p"], "added"]}

    def given(source: str, **also: str) -> dict:
        action = {"do": "update", "target": {"type": "node", "id": "p"},
                  "values": {"properties.source": source, **also}}
        return yaml.safe_load(apply(text, action, base=tmp_path)["text"])["nodes"][0]["properties"]

    # Given another file, a plot keeps its function if that file has one of the name; else
    # it takes the file's first -- unless the file does not read, or a function is given.
    assert given("more.py") == {"source": "more.py", "function": "loss"}
    assert given("other.py") == {"source": "other.py", "function": "first"}
    assert given("broken.py") == {"source": "broken.py", "function": "loss"}
    assert given("gone.py") == {"source": "gone.py", "function": "loss"}
    assert given("other.py", **{"properties.function": "second"})["function"] == "second"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_offers_a_plots_functions_and_writes_the_size_its_corner_is_dragged_to() -> None:
    from test_pages import _studio

    def page(code: str, *given: object) -> object:
        return _studio(f"parts.{code}(...{json.dumps(given)})")

    # The Function pop-up: the file's functions; the one named, if the file has none of the
    # name, said so before them; and with none to offer, no pop-up (the name is typed).
    assert page("plotFunctions", ["loss", "accuracy"], "loss") == ["loss", "accuracy"]
    assert page("plotFunctions", ["loss"], "gone") == [
        {"value": "gone", "label": "gone \u2014 Not in the File"}, {"line": True}, "loss",
    ]
    assert page("plotFunctions", ["loss"], None)[0] == {"value": "", "label": "Choose\u2026"}
    assert page("plotFunctions", [], "loss") is None and page("plotFunctions", None, "") is None
    # A corner dragged sets its width and its height, each in the unit it was written in
    # (or the other's; points, with neither written), to a step a person would type.
    free = {"width": False, "height": False}
    dragged = {"width": 200.2, "height": 99.6}
    written = {"width": "60mm", "height": "4cm"}
    assert page("plotSize", dragged, free, written) == {"width": "71mm", "height": "3.5cm"}
    assert page("plotSize", dragged, free, {"width": None, "height": None}) == {
        "width": "200pt", "height": "100pt",
    }
    assert page("plotSize", dragged, free, {"width": "2.5in", "height": None}) == {
        "width": "2.8in", "height": "1.4in",
    }
    # A side not moved keeps what it had; one that had none is written as it is drawn, or
    # it would follow the side that moved (a plot with one side given is three to two).
    wide = {"width": False, "height": True}
    assert page("plotSize", dragged, wide, written) == {"width": "71mm", "height": "4cm"}
    assert page("plotSize", dragged, wide, {"width": "60mm", "height": None}) == {
        "width": "71mm", "height": "35mm",
    }
    still = {"width": True, "height": True}
    assert page("plotSize", dragged, still, {"width": "60mm", "height": None}) == {
        "width": "60mm", "height": None,
    }
    assert page("lengthLike", 0.2, "60mm") == "1mm"
    # Written so, the plot is drawn that size; with neither again, the size a plot is.
    text = "figure: {id: f}\nnodes:\n- {id: p, kind: plot, width: 60mm, height: 4cm}\n"
    target = {"type": "node", "id": "p"}
    values = page("plotSize", dragged, free, written)
    sized = apply(text, {"do": "update", "target": target, "values": values})["text"]
    style = flexo.resolve_style("paper")
    size = plot_size(parse_figure(yaml.safe_load(sized)).node("p"), style)
    assert (size.width, size.height) == pytest.approx((71 * 72 / 25.4, 35 * 72 / 25.4))
    none = {"width": None, "height": None}
    reset = yaml.safe_load(apply(sized, {"do": "update", "target": target, "values": none})["text"])
    assert reset["nodes"] == [{"id": "p", "kind": "plot"}]
