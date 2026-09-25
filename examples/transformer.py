"""The Transformer ("Attention Is All You Need", Vaswani et al. 2017), in flexo.

Written the way you would describe it: two towers, each a column read bottom-up,
residuals named where they join (``skip=``), and the positional encoding as the
addition it is. No colours, ports, padding or routing hints are needed: the
theme colours each kind of block, every arrow finds its own side, and the
router makes room for the residuals it has to draw.

The one authored port table is the cross-attention's, because the paper puts
the encoder's V and K on the left and the decoder's own Q on the right, and
that order is a choice rather than something to infer.
"""

from __future__ import annotations

from pathlib import Path

from flexo import Figure, PortSpec, Side, VectorPreset, build

HERE = Path(__file__).resolve().parent

QKV = {
    "q": VectorPreset("#9a6fb8", "1x3"),
    "k": VectorPreset("#c9853d", "1x3"),
    "v": VectorPreset("#4f9b8f", "1x3"),
}
"""One colour per value; ``attention(vectors=...)`` grows the glyphs under its ports."""

CROSS_PORTS = (
    PortSpec("v", Side.SOUTH, 0.24, adaptive=True, auto_side=True),
    PortSpec("k", Side.SOUTH, 0.5, adaptive=True, auto_side=True),
    PortSpec("q", Side.SOUTH, 0.76, adaptive=True, auto_side=True),
    PortSpec("output", Side.NORTH, 0.5, adaptive=True, auto_side=True),
)


def embed(column, id, *, label, terminal):
    """The positional encoding added in, over the embedding, over the terminal words.

    A column lays its children out top to bottom, and this stack reads upward,
    so it is written top first and wired afterwards.
    """

    with column.row(f"{id}-pe", gap="8pt", role="layout") as row:
        row.text("caption", "Positional\nEncoding")
        wave = row.op("wave", "~")
        total = row.add("sum", input=wave)
    embedding = column.block(id, label=label, tone="embedding", width="110pt")
    words = column.text(f"{id}-in", terminal)
    column.connect(words, embedding)
    column.connect(embedding, total)
    return total


def transformer(theme: str = "paper") -> Figure:
    with Figure("transformer", width="double-column", theme=theme) as figure:
        with figure.root.row("towers", gap="30pt", align="end", role="layout") as towers:
            with towers.column("encoder", gap="18pt", role="layout") as encoder:
                with encoder.column("tower", label="N\u00d7", gap="14pt", role="module") as tower:
                    an2 = tower.add_norm("an2", label="Add & Norm", width="110pt")
                    ff = tower.mlp("ff", label="Feed\nForward", motif=False, width="110pt")
                    an1 = tower.add_norm("an1", label="Add & Norm", width="110pt")
                    mha = tower.attention(
                        "mha", label="Multi-Head\nAttention", motif=False,
                        width="110pt", vectors=QKV,
                    )
                source = embed(encoder, "input-embedding", label="Input\nEmbedding",
                               terminal="Inputs")

            with towers.column("decoder", gap="18pt", role="layout") as decoder:
                probabilities = decoder.text("out-prob", "Output\nProbabilities")
                softmax = decoder.block("softmax", label="Softmax", tone="softmax",
                                        width="110pt")
                linear = decoder.block("linear", label="Linear", tone="linear",
                                       width="110pt")
                with decoder.column("tower", label="N\u00d7", title_side="right", gap="14pt",
                                    role="module") as tower:
                    an5 = tower.add_norm("an5", label="Add & Norm", width="110pt")
                    ff2 = tower.mlp("ff2", label="Feed\nForward", motif=False, width="110pt")
                    an4 = tower.add_norm("an4", label="Add & Norm", width="110pt")
                    cross = tower.attention(
                        "xmha", label="Multi-Head\nAttention", motif=False,
                        width="110pt", vectors=QKV, ports=CROSS_PORTS,
                    )
                    an3 = tower.add_norm("an3", label="Add & Norm", width="110pt")
                    masked = tower.attention(
                        "mmha", label="Masked\nMulti-Head\nAttention", motif=False,
                        width="110pt", vectors=QKV,
                    )
                target = embed(decoder, "output-embedding", label="Output\nEmbedding",
                               terminal="Outputs\n(shifted right)")

        root = figure.root
        # Encoder: self-attention and feed-forward, each with its residual.
        figure.net(src=source, sinks=[mha.q, mha.k, mha.v])
        root.connect(mha, an1)
        root.connect(source, an1, target_port="skip")
        root.connect(an1, ff)
        root.connect(ff, an2)
        root.connect(an1, an2, target_port="skip")
        # Decoder: masked self-attention, cross-attention on the encoder output,
        # feed-forward, and up through the readout.
        figure.net(src=target, sinks=[masked.q, masked.k, masked.v])
        root.connect(masked, an3)
        root.connect(target, an3, target_port="skip")
        figure.net(src=an2, sinks=[cross.k, cross.v])
        root.connect(an3, cross.q)
        root.connect(cross, an4)
        root.connect(an3, an4, target_port="skip")
        root.connect(an4, ff2)
        root.connect(ff2, an5)
        root.connect(an4, an5, target_port="skip")
        root.connect(an5, linear)
        root.connect(linear, softmax)
        root.connect(softmax, probabilities)
    return figure


def main() -> None:
    for theme in ("paper", "tikz"):
        result = build(
            transformer(theme),
            HERE / "build",
            stem="transformer" if theme == "paper" else f"transformer-{theme}",
            formats=("editable", "png"),
            dpi=200,
        )
        print(result.summary())


if __name__ == "__main__":
    main()
