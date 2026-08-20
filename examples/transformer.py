"""The Transformer ("Attention Is All You Need", Vaswani et al. 2017), in flexo.

Two towers side by side, each authored bottom-up as one column: terminal ->
embedding -> positional-encoding junction -> the N-times block stack. Residual
skips are ordinary edges -- the router walks them around the sublayer they
bypass -- and every Q/K/V triple is one ``fan_out`` into the attention
component's three ports.
"""

from __future__ import annotations

from pathlib import Path

from flexo import Figure, LayoutSpec, build, pt

HERE = Path(__file__).resolve().parent

BLOCK = pt(120)
"""One shared width keeps a tower's stack reading as a single spine."""

PAINTS = {
    "attention": {"fill": "#f6ddc2", "stroke": "#b07c40"},
    "add-norm": {"fill": "#eff0cd", "stroke": "#96974d"},
    "feed-forward": {"fill": "#d3e7f5", "stroke": "#49799e"},
    "embedding": {"fill": "#f7d9de", "stroke": "#af5a68"},
    "linear": {"fill": "#dedcf0", "stroke": "#6f6cab"},
    "softmax": {"fill": "#d7e9d6", "stroke": "#578a58"},
}
TERMINAL = {"fill": "#ffffff", "stroke": "#ffffff"}
"""Plain text with ports: a block painted into the canvas."""

PE_GLYPH = str(HERE / "assets" / "pe_glyph.svg")


def add_norm(tower, id):
    return tower.add_norm(id, label="Add & Norm", width=BLOCK, paint=PAINTS["add-norm"])


def io_stack(column, id, *, embedding, terminal):
    """Terminal text -> embedding -> positional-encoding junction, bottom-up."""

    with column.row(
        f"{id}-pe", gap=pt(8), align="ports", anchor="sum", role="layout"
    ) as row:
        row.node("caption", "label", label="Positional\nEncoding")
        row.image("glyph", PE_GLYPH, height=pt(22))
        sum_ = row.node("sum", "junction")
    embed = column.block(id, label=embedding, width=BLOCK, paint=PAINTS["embedding"])
    source = column.block(f"{id}-in", label=terminal, paint=TERMINAL)
    column.connect(source, embed)
    column.connect(embed, sum_)
    return sum_


def transformer() -> Figure:
    with Figure(
        "transformer",
        width="double-column",
        layout=LayoutSpec("row", gap=pt(46), align="end", padding=pt(10)),
    ) as figure:
        root = figure.root

        with root.column(
            "encoder", gap=pt(18), align="ports", role="layout"
        ) as col:
            with col.column(
                "tower",
                label="N\u00d7",
                gap=pt(14),
                padding=(pt(16), pt(16), pt(16), pt(40)),
                role="module",
                shadow=True,
            ) as tower:
                an2 = add_norm(tower, "an2")
                ff = tower.block(
                    "ff", label="Feed\nForward", width=BLOCK, paint=PAINTS["feed-forward"]
                )
                an1 = add_norm(tower, "an1")
                mha = tower.attention(
                    "mha",
                    label="Multi-Head\nAttention",
                    width=BLOCK,
                    motif=False,
                    paint=PAINTS["attention"],
                )
            enc_pe = io_stack(
                col, "input-embedding", embedding="Input\nEmbedding", terminal="Inputs"
            )

        with root.column(
            "decoder", gap=pt(18), align="ports", role="layout"
        ) as col:
            out_prob = col.block(
                "out-prob", label="Output\nProbabilities", paint=TERMINAL
            )
            softmax = col.block(
                "softmax", label="Softmax", width=BLOCK, paint=PAINTS["softmax"]
            )
            linear = col.block("linear", label="Linear", width=BLOCK, paint=PAINTS["linear"])
            with col.column(
                "tower",
                label="N\u00d7",
                title_side="right",
                gap=pt(14),
                padding=(pt(16), pt(40), pt(16), pt(16)),
                role="module",
                shadow=True,
            ) as tower:
                an5 = add_norm(tower, "an5")
                ff2 = tower.block(
                    "ff2", label="Feed\nForward", width=BLOCK, paint=PAINTS["feed-forward"]
                )
                an4 = add_norm(tower, "an4")
                xmha = tower.attention(
                    "xmha",
                    label="Multi-Head\nAttention",
                    width=BLOCK,
                    motif=False,
                    paint=PAINTS["attention"],
                )
                an3 = add_norm(tower, "an3")
                mmha = tower.attention(
                    "mmha",
                    label="Masked\nMulti-Head\nAttention",
                    width=BLOCK,
                    motif=False,
                    paint=PAINTS["attention"],
                )
            dec_pe = io_stack(
                col,
                "output-embedding",
                embedding="Output\nEmbedding",
                terminal="Outputs\n(shifted right)",
            )

        # Encoder flow: self-attention, then feed-forward, each with its skip.
        figure.net(src=enc_pe, sinks=[mha.q, mha.k, mha.v], id="enc-qkv")
        root.connect(mha, an1)
        root.connect(enc_pe, an1, id="skip1", source_port="branch", target_port="skip")
        root.connect(an1, ff)
        root.connect(ff, an2)
        root.connect(an1, an2, id="skip2", source_port="branch", target_port="skip")

        # Decoder flow: masked self-attention, cross-attention on the encoder
        # output, feed-forward -- and up through the readout.
        figure.net(src=dec_pe, sinks=[mmha.q, mmha.k, mmha.v], id="dec-qkv")
        root.connect(mmha, an3)
        root.connect(dec_pe, an3, id="skip3", source_port="branch", target_port="skip")
        figure.net(src=an2, sinks=[xmha.k, xmha.v], id="cross-kv")
        root.connect(an3, xmha.q)
        root.connect(xmha, an4)
        root.connect(an3, an4, id="skip4", source_port="branch", target_port="skip")
        root.connect(an4, ff2)
        root.connect(ff2, an5)
        root.connect(an4, an5, id="skip5", source_port="branch", target_port="skip")
        root.connect(an5, linear)
        root.connect(linear, softmax)
        root.connect(softmax, out_prob)
    return figure


def main() -> None:
    result = build(
        transformer(),
        HERE / "build",
        stem="transformer",
        formats=("editable", "png"),
        dpi=200,
    )
    print(result.summary())


if __name__ == "__main__":
    main()
