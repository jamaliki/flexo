"""The figure page's edits, made to the figure file's own words: parts added, connected,
renamed, gathered, moved, and removed, the file keeping its comments and reading as a figure."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from test_studio import call

from flexo.compiler import compile_figure
from flexo.studio.figure_edit import EditError, apply, model
from flexo.studio.figure_kind import SAMPLE_FIGURE, FigureKind, parse
from flexo.studio.figure_parts import catalogue
from flexo.studio.server import start


@pytest.fixture(autouse=True)
def _sessions(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path_factory.mktemp("run")))


def edit(text: str, **action: object) -> tuple[str, list[str]]:
    result = apply(text, action)
    return result["text"], result["select"]


def data(text: str) -> dict:
    return yaml.safe_load(text)


def edges(text: str) -> list[tuple[str, str]]:
    return [(item["from"], item["to"]) for item in data(text).get("edges") or []]


def test_a_part_added_after_another_is_fed_from_it_and_the_comments_stay() -> None:
    text, chosen = edit(SAMPLE_FIGURE, do="add", kind="mlp", after="encoder", source="encoder")
    assert chosen == ["mlp"]
    assert text.startswith("# A flexo figure")
    ids = [node["id"] for node in data(text)["nodes"]]
    # A file of nodes alone stacks them as listed: the new one comes right after.
    assert ids == ["x", "encoder", "mlp", "y"]
    assert ("encoder", "mlp") in edges(text)
    compile_figure(parse(text, Path.cwd()))


def test_a_part_added_into_a_chain_takes_its_place_in_the_line() -> None:
    # Between encoder and y: encoder's line to y now runs through the new part.
    text, _ = edit(SAMPLE_FIGURE, do="add", kind="mlp", after="encoder", source="encoder")
    assert edges(text) == [("x", "encoder"), ("encoder", "mlp"), ("mlp", "y")]
    compile_figure(parse(text, Path.cwd()))
    # Unless asked not to; and at the end of the chain there is no line to go into.
    text, _ = edit(
        SAMPLE_FIGURE, do="add", kind="mlp", after="encoder", source="encoder", splice=False
    )
    assert edges(text) == [("x", "encoder"), ("encoder", "y"), ("encoder", "mlp")]
    text, _ = edit(SAMPLE_FIGURE, do="add", kind="mlp", after="y", source="y")
    assert edges(text) == [("x", "encoder"), ("encoder", "y"), ("y", "mlp")]
    # A decision's lines are its branches: a part added after it is a branch of its own,
    # the "yes" left as it was.
    flow = (
        "figure: {id: flow}\nnodes:\n- {id: start, kind: terminal, label: Start}\n"
        "- {id: check, kind: decision, label: 'Done?'}\n- {id: end, kind: terminal, label: End}\n"
        "edges:\n- {from: start, to: check}\n- {from: check, to: end, label: 'yes'}\n"
    )
    text, chosen = edit(flow, do="add", kind="block", after="check", source="check")
    lines = data(text)["edges"]
    assert [(line["from"], line["to"], line.get("label")) for line in lines] == [
        ("start", "check", None),
        ("check", "end", "yes"),
        ("check", chosen[0], None),
    ]
    # Two lines out of a part: which one it would go into is not known, so it is only fed.
    text, _ = edit(SAMPLE_FIGURE, do="connect", source="encoder", target="x")
    text, _ = edit(text, do="add", kind="mlp", after="encoder", source="encoder")
    assert ("encoder", "y") in edges(text) and ("encoder", "mlp") in edges(text)


def test_every_part_in_the_palette_can_be_added_and_drawn(tmp_path: Path) -> None:
    (tmp_path / "picture.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30">'
        '<rect width="40" height="30" fill="#4a7"/></svg>'
    )
    for kind, part in catalogue()["parts"].items():
        if part.get("unavailable") or kind == "structure":
            continue
        node = {"properties": {"source": "picture.svg"}} if part.get("needs_file") else None
        result = apply(
            SAMPLE_FIGURE,
            {"do": "add", "kind": kind, "after": "encoder", "source": "encoder", "node": node},
            base=tmp_path,
        )
        compile_figure(parse(result["text"], tmp_path))


def test_gathering_writes_the_root_the_file_only_implied() -> None:
    text, chosen = edit(SAMPLE_FIGURE, do="gather", ids=["encoder", "y"], layout="row")
    groups = {group["id"]: group for group in data(text)["groups"]}
    assert chosen == ["row"]
    assert groups["root"]["children"] == ["x", "row"]
    assert groups["row"] == {"id": "row", "children": ["encoder", "y"], "layout": {"kind": "row"}}
    text, chosen = edit(text, do="gather", ids=["row"], layout="row", role="module")
    module = next(group for group in data(text)["groups"] if group["id"] == chosen[0])
    assert module["role"] == "module" and module["label"] == "Module"
    with pytest.raises(EditError, match="same row, column or group"):
        edit(text, do="gather", ids=["x", "encoder"], layout="column")


def test_a_rename_follows_the_part_everywhere_it_is_named() -> None:
    text, _ = edit(SAMPLE_FIGURE, do="gather", ids=["encoder"], layout="row")
    text += "nets:\n- id: fan\n  kind: fan-out\n  sources: [x]\n  targets: [encoder.input, y]\n"
    text, chosen = edit(text, do="rename", id="encoder", to="backbone")
    assert chosen == ["backbone"]
    assert ("x", "backbone") in edges(text) and ("backbone", "y") in edges(text)
    assert data(text)["nets"][0]["targets"] == ["backbone.input", "y"]
    assert "backbone" in next(g for g in data(text)["groups"] if g["id"] == "row")["children"]
    with pytest.raises(EditError, match="already in use"):
        edit(text, do="rename", id="x", to="y")
    with pytest.raises(EditError, match="can\u2019t be used as a name"):
        edit(text, do="rename", id="x", to="2x")


def test_only_a_part_just_added_is_named_for_its_first_words() -> None:
    text, (made,) = edit(SAMPLE_FIGURE, do="add", kind="block", after="encoder", source="encoder")
    assert made == "block"
    # Its first words, typed as it is added (the page says so: no words before them).
    target = {"type": "node", "id": made}
    words = {"label": "3D refinement"}
    text, chosen = edit(text, do="update", target=target, values=words, name="")
    assert chosen == ["refinement-3d"]
    assert ("encoder", "refinement-3d") in edges(text)
    # A long label makes an id cut between words, and not after "and".
    text, (made,) = edit(text, do="add", kind="block")
    words = {"label": "Motion correction and CTF estimation"}
    target = {"type": "node", "id": made}
    text, chosen = edit(text, do="update", target=target, values=words, name="")
    assert chosen == ["motion-correction"]


def test_a_shapes_id_stays_whatever_its_words_become() -> None:
    # Others may know a shape by its id (a person, an agent, a line, an export): words
    # typed over its words never change it -- not even the first flow chart's own step's.
    text = (
        "figure:\n  id: chart\nnodes:\n- id: step\n  label: Step\n"
        "- id: check\n  kind: decision\n  label: Done?\nedges:\n- from: step\n  to: check\n"
    )
    step = {"type": "node", "id": "step"}
    text, chosen = edit(text, do="update", target=step, values={"label": "Mix CA"}, name="Step")
    assert chosen == ["step"]
    check = {"type": "node", "id": "check"}
    text, chosen = edit(text, do="update", target=check, values={"label": "Tubes formed?"})
    assert chosen == ["check"]
    assert edges(text) == [("step", "check")]
    # Two people typing in one label, each sending what they typed over: both kept, one
    # shape.
    text, _ = edit(text, do="update", target=step, values={"label": "Mix CA alice"}, was="Mix CA")
    bob = {"label": "Mix bob CA"}
    text, chosen = edit(text, do="update", target=step, values=bob, was="Mix CA")
    assert chosen == ["step"] and [n["id"] for n in data(text)["nodes"]] == ["step", "check"]
    assert data(text)["nodes"][0]["label"] == "Mix bob CA alice"


def test_a_part_added_has_no_words_but_those_given_and_a_new_file_one_empty_shape(
    tmp_path: Path,
) -> None:
    # Never a sample word to be drawn: the editor shows what a part is until it is named.
    text, (made,) = edit(SAMPLE_FIGURE, do="add", kind="decision", after="encoder")
    added = next(node for node in data(text)["nodes"] if node["id"] == made)
    assert made == "decision" and "label" not in added
    text, (named,) = edit(text, do="add", kind="block", node={"label": "Pooling"})
    assert named == "pooling"
    # A protein starts with no example's domains.
    text, (protein,) = edit(text, do="add", kind="protein")
    made = next(node for node in data(text)["nodes"] if node["id"] == protein)
    assert "features" not in made["properties"]
    # A structure named only for its file is named for what the file holds.
    (tmp_path / "capsid.pdb").write_text(
        f"{'HEADER    VIRAL PROTEIN':<62}1A8O\nCOMPND   2 MOLECULE: HIV CAPSID;\n"
    )
    node = {"label": "capsid", "properties": {"source": "capsid.pdb"}}
    result = apply(SAMPLE_FIGURE, {"do": "add", "kind": "structure", "node": node}, base=tmp_path)
    [structure] = [n for n in data(result["text"])["nodes"] if n.get("kind") == "structure"]
    assert structure["label"] == "HIV capsid (1A8O)"
    # A new figure file is one shape with no words (its id kept as its words are typed).
    starter = FigureKind().new(tmp_path / "Pipeline.yaml")["text"]
    assert [node["id"] for node in data(starter)["nodes"]] == ["shape"]
    assert "label" not in data(starter)["nodes"][0]
    shape = {"type": "node", "id": "shape"}
    text, chosen = edit(starter, do="update", target=shape, values={"label": "Encoder"}, was="")
    assert chosen == ["shape"]


def test_a_line_is_known_by_its_ends_when_lines_before_it_come_and_go() -> None:
    # Someone takes the first line away while the second's words are typed: they still go
    # on the second, known now by its new number.
    text, _ = edit(SAMPLE_FIGURE, do="delete", ids=["edge.1.x-to-encoder"])
    line = {"type": "edge", "id": "edge.2.encoder-to-y"}
    text, chosen = edit(text, do="update", target=line, values={"label": "features"})
    assert chosen == ["edge.1.encoder-to-y"]
    assert data(text)["edges"] == [{"from": "encoder", "to": "y", "label": "features"}]
    # A line gone is said as the parts it joined, never by its id.
    text, _ = edit(text, do="delete", ids=["edge.1.encoder-to-y"])
    with pytest.raises(EditError, match="The line from “Encoder” to “Output \\$y\\$” is gone"):
        edit(text, do="update", target=line, values={"label": "again"})


def test_deleting_a_part_takes_its_lines_and_an_emptied_group_with_it() -> None:
    text, _ = edit(SAMPLE_FIGURE, do="gather", ids=["encoder"], layout="row")
    text, _ = edit(text, do="delete", ids=["encoder"])
    assert edges(text) == []
    assert [group["id"] for group in data(text)["groups"]] == ["root"]
    assert "encoder" not in data(text)["groups"][0]["children"]
    with pytest.raises(EditError, match="can\u2019t be deleted"):
        edit(text, do="delete", ids=["root"])


def test_a_part_goes_on_a_line_of_its_own_centred_under_a_row() -> None:
    steps = (
        "figure: {id: steps}\nnodes:\n- {id: a, label: A}\n- {id: b, label: B}\n"
        "- {id: c, label: C}\n- {id: score, kind: decision, label: Score}\n"
        "groups:\n- {id: root, layout: {kind: row, gap: 18pt, padding: 6pt}, "
        "children: [a, b, c, score]}\n"
        "edges:\n- {from: a, to: b}\n- {from: b, to: c}\n- {from: c, to: score}\n"
        "- {from: a, to: score}\n"
    )
    text, chosen = edit(steps, do="move", id="score", line="below")
    assert chosen == ["score"]
    groups = {group["id"]: group for group in data(text)["groups"]}
    # The root keeps its frame; its steps keep their row, with no frame of its own.
    assert groups["root"] == {
        "id": "root",
        "children": ["row", "score"],
        "layout": {"kind": "column", "align": "center", "padding": "6pt"},
    }
    assert groups["row"]["children"] == ["a", "b", "c"]
    assert groups["row"]["layout"] == {"kind": "row", "gap": "18pt"}
    assert groups["row"]["role"] == "layout"
    compile_figure(parse(text, Path.cwd()))
    # Over the row now: the root runs down already, so it goes in it, first.
    text, _ = edit(text, do="move", id="a", line="above", of="row")
    assert {group["id"]: group for group in data(text)["groups"]}["root"]["children"] == [
        "a",
        "row",
        "score",
    ]
    compile_figure(parse(text, Path.cwd()))
    with pytest.raises(EditError, match="isn\u2019t a valid position"):
        edit(steps, do="move", id="score", line="inside")


def test_a_part_let_go_beside_one_in_a_column_goes_side_by_side_with_it() -> None:
    column = (
        "figure: {id: column}\nnodes:\n- {id: a, label: A}\n"
        "- {id: cloud, kind: cloud, label: Feed}\n- {id: db, kind: database, label: Orders DB}\n"
        "groups:\n- {id: root, layout: {kind: column}, children: [a, cloud, db]}\n"
    )
    text, chosen = edit(column, do="move", id="db", line="right", of="cloud")
    assert chosen == ["db"]
    groups = {group["id"]: group for group in data(text)["groups"]}
    assert groups["root"]["children"] == ["a", "row"]
    # (Lined up by their lines, as a part and what it leads to are.)
    assert groups["row"] == {
        "id": "row",
        "children": ["cloud", "db"],
        "layout": {"kind": "row", "align": "ports"},
        "role": "layout",
    }
    compile_figure(parse(text, Path.cwd()))
    # Left of a part in that row: it runs across already, so it goes in it, first.
    text, _ = edit(text, do="move", id="a", line="left", of="cloud")
    groups = {group["id"]: group for group in data(text)["groups"]}
    assert groups["root"]["children"] == ["row"]
    assert groups["row"]["children"] == ["a", "cloud", "db"]
    with pytest.raises(EditError, match="no group or part named"):
        edit(column, do="move", id="db", line="right", of="gone")


def test_parts_copied_from_one_figure_are_pasted_into_another_with_their_lines() -> None:
    copied = {
        "top": ["encoder", "y"],
        "nodes": [
            {"id": "encoder", "kind": "block", "label": "Encoder", "ports": ["input", "output"]},
            {"id": "y", "kind": "text", "label": "Output"},
        ],
        "edges": [
            {"id": "edge.2.encoder-to-y", "from": "encoder", "to": "y"},
            {"from": "x", "to": "encoder"},  # to a part not copied: left behind
        ],
    }
    text, chosen = edit(SAMPLE_FIGURE, do="paste", after="x", **copied)
    # The ids it has already are not taken again; the pasted come after x, in order.
    assert chosen == ["encoder-2", "y-2"]
    assert [node["id"] for node in data(text)["nodes"]] == ["x", "encoder-2", "y-2", "encoder", "y"]
    assert ("encoder-2", "y-2") in edges(text) and ("x", "encoder-2") not in edges(text)
    assert "ports" not in data(text)["nodes"][1]
    compile_figure(parse(text, Path.cwd()))
    with pytest.raises(EditError, match="nothing to paste"):
        edit(SAMPLE_FIGURE, do="paste", top=["gone"], nodes=[])


def test_a_line_is_found_by_the_id_the_drawing_gives_it() -> None:
    text, _ = edit(SAMPLE_FIGURE, do="delete", ids=["edge.2.encoder-to-y"])
    assert edges(text) == [("x", "encoder")]


def test_lines_land_where_a_part_takes_them() -> None:
    text, _ = edit(SAMPLE_FIGURE, do="add", kind="concat", after="encoder")
    text, _ = edit(text, do="connect", source="x", target="concat")
    text, _ = edit(text, do="connect", source="encoder", target="concat")
    assert {("x", "concat.input1"), ("encoder", "concat.input2")} <= set(edges(text))
    text, _ = edit(text, do="add", kind="attention", after="y", source="y")
    net = data(text)["nets"][0]
    assert net["sources"] == ["y"] and net["targets"] == [f"attention.{p}" for p in "qkv"]
    with pytest.raises(EditError, match="already connected"):
        edit(text, do="connect", source="x", target="encoder")
    with pytest.raises(EditError, match="itself"):
        edit(text, do="connect", source="x", target="x")
    compile_figure(parse(text, Path.cwd()))


def test_updates_set_and_clear_keys_and_a_new_kind_keeps_what_it_can() -> None:
    target = {"type": "node", "id": "encoder"}
    text, _ = edit(SAMPLE_FIGURE, do="update", target=target, values={"properties.badge": "frozen"})
    encoder = data(text)["nodes"][1]
    assert encoder["properties"] == {"tone": "encoder", "badge": "frozen"}
    text, _ = edit(text, do="update", target=target, values={"kind": "protein"})
    encoder = data(text)["nodes"][1]
    assert list(encoder)[:3] == ["id", "kind", "label"]  # the kind written under the id
    assert encoder["properties"]["tone"] == "encoder" and encoder["properties"]["length"] == 300
    text, _ = edit(text, do="update", target=target, values={"kind": "block", "label": ""})
    encoder = data(text)["nodes"][1]
    assert encoder == {"id": "encoder", "properties": {"tone": "encoder", "badge": "frozen"}}
    edge = {"type": "edge", "id": "edge.2.encoder-to-y"}
    text, _ = edit(text, do="update", target=edge, values={"head": "inhibition"})
    text, _ = edit(text, do="update", target=edge, values={"arrow": "reversible"})
    assert data(text)["edges"][1] == {"from": "encoder", "to": "y", "arrow": "reversible"}
    text, _ = edit(text, do="update", target={"type": "figure"}, values={"figure.style": "tikz"})
    assert data(text)["figure"]["style"] == "tikz"


def test_parts_move_between_groups_and_step_among_their_siblings() -> None:
    text, _ = edit(SAMPLE_FIGURE, do="gather", ids=["encoder"], layout="column")
    text, _ = edit(text, do="move", id="y", parent="column", index=0)
    groups = {group["id"]: group for group in data(text)["groups"]}
    assert groups["column"]["children"] == ["y", "encoder"]
    text, _ = edit(text, do="step", id="y", delta=1)
    text, _ = edit(text, do="ungroup", id="column")
    assert data(text)["groups"][0]["children"] == ["x", "encoder", "y"]
    with pytest.raises(EditError, match="inside itself"):
        edit(text, do="move", id="root", parent="root")


def test_duplicating_a_group_copies_its_parts_and_the_lines_between_them() -> None:
    text, _ = edit(SAMPLE_FIGURE, do="gather", ids=["encoder", "y"], layout="row")
    text, chosen = edit(text, do="duplicate", ids=["row"])
    assert chosen == ["row-2"]
    assert ("encoder-2", "y-2") in edges(text)
    compile_figure(parse(text, Path.cwd()))


def test_an_edit_that_would_break_the_figure_is_refused_and_one_already_broken_is_kept() -> None:
    with pytest.raises(EditError, match="Unknown figure edit"):
        edit(SAMPLE_FIGURE, do="explode")
    broken = SAMPLE_FIGURE.replace("to: encoder", "to: nowhere")
    text, _ = edit(broken, do="add", kind="block")  # the file was broken before: made anyway
    assert "- id: block" in text


def test_the_model_names_lines_as_the_drawing_does_and_marks_the_implied_root() -> None:
    found = model(SAMPLE_FIGURE)
    assert found is not None
    assert [edge["id"] for edge in found["edges"]] == ["edge.1.x-to-encoder", "edge.2.encoder-to-y"]
    assert found["groups"][-1] == {
        "id": "root",
        "children": ["x", "encoder", "y"],
        "layout": {"kind": "column"},
        "implied": True,
    }
    assert found["nodes"][1]["ports"] == ["input", "output"]
    assert model("nodes: [") is None


def test_an_indented_file_keeps_its_indentation() -> None:
    indented = (
        SAMPLE_FIGURE.replace("\n- ", "\n  - ")
        .replace("\n  ", "\n    ")
        .replace("\n    - ", "\n  - ")
    )
    text, _ = edit(indented, do="add", kind="block")
    assert "\n  - id: block" in text


@pytest.fixture
def served(tmp_path: Path) -> Iterator[tuple[str, object]]:
    (tmp_path / "figure.yaml").write_text(SAMPLE_FIGURE, encoding="utf-8")
    server, workspace = start(tmp_path / "figure.yaml", browser=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", workspace
    finally:
        workspace.close()
        server.shutdown()
        server.server_close()


def test_the_page_asks_the_server_for_an_edit_and_gets_the_file_and_its_model(served) -> None:
    base, workspace = served
    token = workspace.token
    status, opened = call(f"{base}/api/open?file=figure.yaml", token)
    assert status == 200 and "editor" in opened["catalog"]
    action = {"do": "add", "kind": "protein", "after": "encoder", "source": "encoder"}
    body = {"file": "figure.yaml", "document": opened["document"], "action": action}
    status, result = call(f"{base}/api/act", token, body)
    assert status == 200 and result["select"] == ["protein"]
    assert any(node["id"] == "protein" for node in result["model"]["nodes"])
    status, failed = call(
        f"{base}/api/act", token, {**body, "action": {"do": "rename", "id": "x", "to": "y"}}
    )
    assert status == 400 and "already in use" in failed["error"]
    status, drawn = call(
        f"{base}/api/draw", token, {"file": "figure.yaml", "document": result["document"]}
    )
    assert status == 200 and drawn["info"]["model"]["nodes"][2]["kind"] == "protein"


def test_a_picture_beside_the_figure_is_found_when_it_is_drawn(tmp_path: Path) -> None:
    (tmp_path / "art").mkdir()
    (tmp_path / "art" / "logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        '<circle cx="10" cy="10" r="8"/></svg>'
    )
    text = apply(
        SAMPLE_FIGURE,
        {"do": "add", "kind": "image", "node": {"properties": {"source": "art/logo.svg"}}},
        base=tmp_path,
    )["text"]
    drawing = FigureKind().draw({"text": text}, tmp_path)
    assert drawing.pages and not [m for m in drawing.messages if m.severity == "error"]


def test_reading_changes_nothing_and_a_figure_inside_another_document_is_edited_as_data() -> None:
    from flexo.studio.figure_edit import apply_to_data

    result = apply(SAMPLE_FIGURE, {"do": "read"})
    assert result == {"text": SAMPLE_FIGURE, "select": []}
    inline = yaml.safe_load(SAMPLE_FIGURE)
    made = apply_to_data(inline, {"do": "rename", "id": "encoder", "to": "backbone"})
    assert made["select"] == ["backbone"]
    assert [node["id"] for node in made["data"]["nodes"]] == ["x", "backbone", "y"]
    assert [node["id"] for node in made["model"]["nodes"]] == ["x", "backbone", "y"]
    assert inline["nodes"][1]["id"] == "encoder"


def test_a_word_yaml_could_read_as_a_flag_or_number_stays_a_word() -> None:
    from flexo.studio.figure_edit import apply_to_data

    data = {"figure": {"id": "f"}, "nodes": [{"id": "a", "label": "A"}]}
    for word in ("Yes", "no", "Off", "on", "12", "null"):
        action = {"do": "update", "target": {"type": "node", "id": "a"}, "values": {"label": word}}
        assert apply_to_data(data, action)["data"]["nodes"][0]["label"] == word


def test_a_merge_that_keeps_a_line_to_a_shape_deleted_is_mended() -> None:
    from flexo.studio.merge import merge3

    base = {
        "figure": {"id": "f"},
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
        "groups": [
            {"id": "root", "layout": {"kind": "row"}, "children": ["a", "b", "d", "box"]},
            {"id": "box", "layout": {"kind": "column"}, "children": ["c"]},
        ],
    }
    # Here lines are drawn to c, and a fan-out to b and c; there, c is deleted.
    ours = {
        **base,
        "edges": [{"from": "a", "to": "b"}, {"from": "d", "to": "c"}],
        "nets": [{"id": "n", "kind": "fan-out", "sources": ["a"], "targets": ["b", "c"]}],
    }
    theirs = {
        "figure": {"id": "f"},
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "d"}],
        "groups": [
            {"id": "root", "layout": {"kind": "row"}, "children": ["a", "b", "d", "box"]},
            {"id": "box", "layout": {"kind": "column"}, "children": []},
        ],
    }
    merged = FigureKind().mended(merge3(base, ours, theirs))
    # The line to c goes; the fan-out left one target is a line; the emptied group goes.
    assert merged["edges"] == [{"from": "a", "to": "b"}, {"from": "a", "to": "b"}]
    assert "nets" not in merged
    assert [group["id"] for group in merged["groups"]] == ["root"]
    assert merged["groups"][0]["children"] == ["a", "b", "d"]
    compile_figure(parse(yaml.safe_dump(merged), Path.cwd()))


def test_deleting_one_end_of_a_fan_out_of_two_leaves_a_line() -> None:
    text = (
        "figure: {id: f}\nnodes:\n- {id: a}\n- {id: b}\n- {id: c}\n"
        "groups:\n- {id: root, layout: {kind: row}, children: [a, b, c]}\n"
        "nets:\n- {id: n, kind: fan-out, sources: [a], targets: [b, c], label: splits}\n"
    )
    text, _ = edit(text, do="delete", ids=["c"])
    assert "nets" not in data(text)
    assert data(text)["edges"] == [{"from": "a", "to": "b", "label": "splits"}]
    compile_figure(parse(text, Path.cwd()))


def test_a_row_folded_to_fit_is_written_as_seen_and_only_the_part_moved_moves() -> None:
    nodes = "".join(f"- id: {name}\n  label: {name.upper()}\n" for name in "abcdef")
    pairs = zip("abcde", "bcdef", strict=True)
    edges = "".join(f"- from: {one}\n  to: {two}\n" for one, two in pairs)
    text = f"figure:\n  id: flow\nnodes:\n{nodes}edges:\n{edges}"
    # Seen folded onto two lines, the second run back: written so, lined up at their ends.
    seen = [["a", "b", "c"], ["f", "e", "d"]]
    arranged = apply(
        text, {"do": "arrange", "id": "root", "kind": "row", "lines": seen, "align": "end"}
    )
    first, second = arranged["select"]
    groups = {group["id"]: group for group in yaml.safe_load(arranged["text"])["groups"]}
    assert groups["root"]["children"] == [first, second]
    assert groups["root"]["layout"]["kind"] == "column"
    assert groups["root"]["layout"]["align"] == "end"
    assert groups[first]["children"] == ["a", "b", "c"]
    assert groups[second]["children"] == ["f", "e", "d"]
    # Then the part dragged goes under another, and nothing else moves.
    moved = apply(arranged["text"], {"do": "move", "id": "f", "line": "below", "of": "b"})
    groups = {group["id"]: group for group in yaml.safe_load(moved["text"])["groups"]}
    assert groups[second]["children"] == ["e", "d"]
    pair = groups[first]["children"][1]
    assert groups[first]["children"] == ["a", pair, "c"] and groups[pair]["children"] == ["b", "f"]
    # Parts the figure no longer has (another's edit meanwhile) are not written over.
    with pytest.raises(EditError):
        apply(text, {"do": "arrange", "id": "root", "kind": "row", "lines": [["a", "b"], seen[1]]})


def test_a_part_put_into_a_line_and_taken_out_at_once_leaves_the_line_as_it_was() -> None:
    text = "figure:\n  id: f\nnodes:\n- id: a\n  label: A\n- id: b\n  label: B\n"
    text += "edges:\n- from: a\n  to: b\n  label: 'yes'\n"
    added = apply(text, {"do": "add", "kind": "text", "after": "a", "source": "a"})
    (made,) = added["select"]
    back = apply(added["text"], {"do": "delete", "ids": [made], "rejoin": True})
    assert yaml.safe_load(back["text"]) == yaml.safe_load(text)
    # Deleted as a person deletes it, its lines go with it.
    gone = apply(added["text"], {"do": "delete", "ids": [made]})
    assert "edges" not in yaml.safe_load(gone["text"])


def test_a_branch_goes_on_a_line_of_its_own_beside_its_part_and_taken_out_leaves_the_file() -> None:
    text = "figure:\n  id: f\nnodes:\n- id: start\n  label: Start\n- id: ask\n  kind: decision\n"
    text += "  label: Ready?\n- id: go\n  label: Go\nedges:\n- from: start\n  to: ask\n"
    text += "- from: ask\n  to: go\n  label: 'yes'\n"
    # A decision's other outcome: beside it (the flow runs down), joined to it, not put
    # into the line on to "Go".
    first = apply(text, {"do": "add", "kind": "block", "after": "ask", "source": "ask",
                         "line": "right", "of": "ask"})
    (made,) = first["select"]
    data = yaml.safe_load(first["text"])
    groups = {group["id"]: group for group in data["groups"]}
    pair = next(group for group in groups.values() if group["children"] == ["ask", made])
    assert pair["layout"] == {"kind": "row", "align": "ports"}
    assert groups["root"]["children"] == ["start", pair["id"], "go"]
    assert ("ask", "go") in edges(first["text"]) and ("ask", made) in edges(first["text"])
    compile_figure(parse(first["text"], Path.cwd()))
    # A third goes beside the second, not between the decision and it.
    second = apply(first["text"], {"do": "add", "kind": "block", "after": "ask", "source": "ask",
                                   "line": "below", "of": made})
    (other,) = second["select"]
    inner = [group for group in yaml.safe_load(second["text"])["groups"]
             if group["children"] == [made, other]]
    assert inner and inner[0]["layout"]["kind"] == "column"
    # Taken out at once (left empty), each leaves the file as it was before it.
    back = apply(second["text"], {"do": "delete", "ids": [other], "rejoin": True})
    assert back["text"] == first["text"]
    back = apply(first["text"], {"do": "delete", "ids": [made], "rejoin": True})
    assert back["text"] == text
    # Not joined to it, a shape goes beside its part all the same: never between two parts
    # a line joins.
    alone = apply(text, {"do": "add", "kind": "block", "after": "ask", "line": "right",
                         "of": "ask"})
    assert edges(alone["text"]) == edges(text)


def test_activity_says_what_a_figure_edit_did_not_which_line_of_its_file() -> None:
    kind = FigureKind()

    def said(action: dict) -> list[str]:
        after = apply(SAMPLE_FIGURE, action)["text"]
        return [note["text"] for note in kind.describe({"text": SAMPLE_FIGURE}, {"text": after})]

    # A part put into a line: added, the line it went into not said to be taken away.
    assert said({"do": "add", "kind": "block", "after": "encoder", "source": "encoder",
                 "node": {"label": "Cache"}}) == ["added “Cache”"]
    assert said({"do": "update", "target": {"type": "node", "id": "encoder"},
                 "values": {"label": "Big encoder"}}) == [
        "renamed “Encoder” to “Big encoder”"]
    assert said({"do": "delete", "ids": ["encoder"]}) == ["deleted “Encoder”"]
    assert said({"do": "connect", "source": "x", "target": "y"})[0].startswith("connected ")
    assert said({"do": "move", "id": "y", "parent": "root", "index": 0})[0].startswith("moved ")
    # A file that does not read as a figure is said by its line, as before.
    notes = kind.describe({"text": "a: [b"}, {"text": "a: [c"})
    assert notes[0]["where"] == {"line": 1, "label": "line 1"}


def test_a_line_to_a_shape_there_is_none_of_is_left_out_and_said() -> None:
    from flexo.studio.figure_edit import mend

    text = "figure:\n  id: f\nnodes:\n- id: a\n  label: A\n- id: b\n  label: B\nedges:\n"
    text += "- from: a\n  to: b\n- from: b\n  to: nowhere\n"
    drawing = FigureKind().draw({"text": text}, Path.cwd())
    assert drawing.pages, "the rest of the figure is drawn"
    assert [message.text for message in drawing.messages] == [
        "A line to “nowhere” has no shape to go to."]
    # Two edits merged: a line kept to a shape one deleted goes; one to a shape there never
    # was is the person's to put right, and stays to be said.
    data = yaml.safe_load(text)
    assert not mend(data, before={"a", "b"}) and len(data["edges"]) == 2
    assert mend(data, before={"a", "b", "nowhere"}) and len(data["edges"]) == 1


def test_a_part_put_under_one_in_an_arranged_row_keeps_that_one_level_with_the_row() -> None:
    # "Tumble" beside the decision (a row arranged so, centred); "Turn" put under "Tumble":
    # the two lined up by their lines, so "Tumble" stays level with the decision.
    text = "figure:\n  id: f\nnodes:\n- id: ask\n  kind: decision\n  label: Rising?\n"
    text += "- id: tumble\n  label: Tumble\n- id: turn\n  label: Turn\nedges:\n"
    text += "- from: ask\n  to: tumble\n- from: tumble\n  to: turn\ngroups:\n"
    text += "- id: root\n  layout: {kind: column}\n  children: [row, turn]\n"
    text += "- id: row\n  layout: {kind: row, align: center}\n  role: layout\n"
    text += "  children: [ask, tumble]\n"
    moved, _ = edit(text, do="move", id="turn", line="below", of="tumble")
    groups = {group["id"]: group for group in data(moved)["groups"]}
    assert groups["row"]["layout"]["align"] == "ports"
    compiled = compile_figure(parse(moved, Path.cwd()))
    nodes = compiled.fitted.nodes
    middle = {node.measured.spec.id: node.bounds.y + node.bounds.height / 2 for node in nodes}
    assert abs(middle["ask"] - middle["tumble"]) < 1.0



def test_a_shape_put_in_no_group_is_drawn_at_the_end_of_the_root() -> None:
    from flexo.serialization import parse_figure

    text = "figure:\n  id: f\nnodes:\n- id: a\n  label: A\n- id: b\n  label: B\n"
    text += "- id: extra\n  label: Log it\ngroups:\n- id: root\n  layout: {kind: row}\n"
    text += "  children: [a, b]\n"
    spec = parse_figure(yaml.safe_load(text))
    root = next(group for group in spec.groups if group.id == "root")
    assert root.children == ("a", "b", "extra")
    compile_figure(spec)
    # The editor lists it where it is drawn.
    root = next(group for group in model(text)["groups"] if group["id"] == "root")
    assert root["children"] == ["a", "b", "extra"]


def test_a_figure_file_with_a_shape_that_cannot_be_drawn_exports_with_a_plain_box(
    tmp_path: Path,
) -> None:
    from flexo.studio.figure_kind import figure_changes

    text = "figure:\n  id: bad\nnodes:\n- id: p\n  kind: protein\n  label: Spike\n"
    text += "- id: q\n  label: Next\nedges:\n- from: p\n  to: q\n"
    kind = FigureKind()
    written = kind.export({"text": text}, tmp_path, "bad", ["png"], into=tmp_path / "out")
    assert written and all(path.exists() for path in written)
    assert kind.export_notes == [
        "“Spike” is drawn as a plain box: a protein needs its length in residues."
    ]
    # And a figure in another document (a deck's) is said by what changed in it.
    before = yaml.safe_load(SAMPLE_FIGURE)
    after = yaml.safe_load(SAMPLE_FIGURE)
    after["nodes"].append({"id": "extra", "label": "Extra step"})
    assert figure_changes(before, after) == ["added “Extra step”"]


def test_a_structure_that_cannot_be_downloaded_is_an_answer_not_a_failed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flexo.structures as structures

    def unreachable(identifier: str) -> str:
        raise ValueError("PDB can't be reached: no network.")

    monkeypatch.setattr(structures, "fetch_structure", unreachable)
    action = {"do": "structure-fetch", "id": "1UBQ"}
    answer = FigureKind().act({"text": SAMPLE_FIGURE}, action, Path.cwd())
    assert answer["failed"] == "PDB can't be reached: no network." and "id" not in answer


def test_a_shape_found_wanting_as_it_is_drawn_is_a_plain_box_the_rest_drawn(tmp_path: Path) -> None:
    text = (
        "figure:\n  id: f\nnodes:\n"
        "- {id: p, kind: plasmid, label: pUC19, properties: {length: -5}}\n"
        "- {id: t, kind: tree, label: Tree, properties: {newick: '((A,B'}}\n"
        "- {id: q, label: Next}\n"
        "edges:\n- {from: p, to: q}\n- {from: q, to: zz}\n"
    )
    drawing = FigureKind().draw({"text": text, "suffix": ".yaml"}, tmp_path)
    (page,) = drawing.pages
    assert "Next" in page.svg and "pUC19" in page.svg
    # Each said where it is: the shape and the field it is about, the line by its id.
    said = {(message.where, message.code) for message in drawing.messages}
    assert {("p", "genetics.plasmid.length"), ("t", "tree.newick"), ("edge.2.q-to-zz", "")} <= said
    kind = FigureKind()
    document = {"text": text, "suffix": ".yaml"}
    written = kind.export(document, tmp_path, "f", ["pdf"], into=tmp_path / "out")
    assert [path.suffix for path in written] == [".pdf"]
    note = "“pUC19” is drawn as a plain box: a plasmid of -5 bp is too short to draw."
    assert note in kind.export_notes


def test_each_part_is_stood_in_at_the_size_it_is_drawn() -> None:
    parts = catalogue()["parts"]
    # In ems of the figure's words: a circle smaller than a block, a decision wider.
    assert parts["circle"]["size"][0] < parts["block"]["size"][0] < parts["decision"]["size"][0]


def test_a_timeline_asked_for_too_short_an_axis_keeps_its_times_apart() -> None:
    from flexo.layout.measure import measure_figure
    from flexo.serialization import parse_figure

    def width(**extra) -> float:
        events = [{"at": 0, "label": "Seed"}, {"at": 24, "label": "Harvest"}]
        props = {"events": events, "unit": "h", **extra}
        node = {"id": "t", "kind": "timeline", "properties": props}
        spec = parse_figure({"figure": {"id": "t"}, "nodes": [node]})
        return measure_figure(spec).nodes[0].intrinsic_size.width

    # 24 (points, not hours) would set its times one over another: it is as wide as they need.
    assert width(length=24) > 100 and width(length=400) > 400


def test_a_shape_is_lined_up_under_a_part_and_placed_afresh_when_moved() -> None:
    text = (
        "figure:\n  id: f\nnodes:\n"
        + "".join(f"- {{id: {name}, label: {name.upper()}}}\n" for name in "abcde")
        + "groups:\n"
        "- {id: root, layout: {kind: column, align: center}, children: [row, e]}\n"
        "- {id: row, layout: {kind: row}, children: [a, b, c, d]}\n"
    )
    under = apply(text, {"do": "align", "id": "e", "with": "b"})
    store = next(node for node in yaml.safe_load(under["text"])["nodes"] if node["id"] == "e")
    assert store["align_with"] == "b" and under["select"] == ["e"]
    # Renamed, the part it lines up with is followed; deleted, it is placed as its group places it.
    renamed = apply(under["text"], {"do": "rename", "id": "b", "to": "beta"})
    assert "align_with: beta" in renamed["text"]
    gone = apply(renamed["text"], {"do": "delete", "ids": ["beta"]})
    assert "align_with" not in gone["text"]
    # Moved elsewhere, too; and back to its group's own place by "with" left out.
    moved = apply(under["text"], {"do": "move", "id": "e", "parent": "row", "index": 0})
    assert "align_with" not in moved["text"]
    assert "align_with" not in apply(under["text"], {"do": "align", "id": "e"})["text"]
    with pytest.raises(EditError, match="line it up with"):
        apply(text, {"do": "align", "id": "e", "with": "nowhere"})
