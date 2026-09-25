# ruff: noqa: RUF001, SIM117 -- figure text uses real symbols; nesting mirrors the figure.
"""Figures from the literature, each written the way its paper describes it.

Every figure here is plain authoring: components, the values that flow between
them, and at most one hint where a paper makes a choice that cannot be
inferred (``via=`` for a feedback loop, a ``row`` for a value that enters from
the side). No coordinates, colours, ports, or padding. Run this file to build
them all into ``examples/build/literature``.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path

from flexo import Figure, build

HERE = Path(__file__).resolve().parent


def inception(theme: str = "paper") -> Figure:
    """The Inception module (Szegedy et al. 2015, Figure 2b)."""

    with Figure("inception", theme=theme) as figure:
        with figure.module("m", label="Inception module", layout="column") as m:
            previous = m.block("previous", label="Previous layer")
            with m.row("branches", role="layout") as row:
                with row.column("b1", role="layout") as column:
                    one = column.block("conv", label="1×1 conv")
                with row.column("b2", role="layout") as column:
                    reduce3 = column.block("reduce", label="1×1 conv")
                    three = column.block("conv", label="3×3 conv", input=reduce3)
                with row.column("b3", role="layout") as column:
                    reduce5 = column.block("reduce", label="1×1 conv")
                    five = column.block("conv", label="5×5 conv", input=reduce5)
                with row.column("b4", role="layout") as column:
                    pool = column.block("pool", label="3×3 max pool")
                    project = column.block("conv", label="1×1 conv", input=pool)
            concat = m.block("concat", label="Filter concatenation")
        figure.net(src=previous, sinks=[one, reduce3, reduce5, pool])
        figure.merge(sinks=[one, three, five, project], dst=concat)
    return figure


def bottleneck(theme: str = "paper") -> Figure:
    """A bottleneck residual block (He et al. 2016, Figure 5)."""

    with Figure("bottleneck", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Bottleneck block", layout="column") as m:
            x = m.text("x", "256-d")
            reduce = m.block("reduce", label="1×1, 64", input=x)
            conv = m.block("conv", label="3×3, 64", input=reduce)
            expand = m.block("expand", label="1×1, 256", input=conv)
            total = m.add("sum", inputs=[expand, x])
            m.text("relu", "ReLU", input=total)
    return figure


def squeeze_excitation(theme: str = "paper") -> Figure:
    """A squeeze-and-excitation block on a residual branch (Hu et al. 2018)."""

    with Figure("se", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Squeeze-and-excitation", layout="column") as m:
            x = m.text("x", "$X$")
            residual = m.block("residual", label="Residual", input=x)
            pool = m.block("pool", label="Global pooling", input=residual)
            fc1 = m.block("fc1", label="FC", input=pool)
            relu = m.block("relu", label="ReLU", input=fc1)
            fc2 = m.block("fc2", label="FC", input=relu)
            gate = m.block("gate", label="Sigmoid", input=fc2)
            scaled = m.multiply("scale", inputs=[gate, residual])
            total = m.add("sum", inputs=[scaled, x])
            m.text("y", r"$\tilde{X}$", input=total)
    return figure


def lstm(theme: str = "paper") -> Figure:
    """An LSTM cell (Hochreiter and Schmidhuber 1997), drawn after Olah (2015)."""

    with Figure("lstm", theme=theme) as figure:
        with figure.module("m", label="LSTM cell", layout="grid", columns=5) as m:
            c_previous = m.text("c-prev", "$c_{t-1}$", at=(0, 0))
            forget = m.multiply("forget", at=(0, 1))
            total = m.add("total", at=(0, 2))
            c_next = m.text("c-next", "$c_t$", at=(0, 4))
            f = m.block("f", label=r"$\sigma$", tone="gate", at=(2, 1))
            i = m.block("i", label=r"$\sigma$", tone="gate", at=(2, 2))
            g = m.block("g", label="tanh", tone="act", at=(1, 2))
            o = m.block("o", label=r"$\sigma$", tone="gate", at=(2, 3))
            write = m.multiply("write", at=(1, 3))
            squash = m.block("squash", label="tanh", tone="act", at=(1, 4))
            read = m.multiply("read", at=(2, 4))
            h = m.text("h", "$h_t$", at=(3, 4))
            x = m.text("x", "$x_t$, $h_{t-1}$", at=(3, 0))
        figure.net(src=x, sinks=[f, i, g, o])
        m.connect(c_previous, forget)
        m.connect(f, forget)
        m.connect(forget, total)
        m.connect(i, write)
        m.connect(g, write)
        m.connect(write, total)
        figure.net(src=total, sinks=[c_next, squash])
        m.connect(squash, read)
        m.connect(o, read)
        m.connect(read, h)
    return figure


def vision_transformer(theme: str = "paper") -> Figure:
    """The Vision Transformer (Dosovitskiy et al. 2021, Figure 1)."""

    with Figure("vit", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Vision Transformer", layout="column") as m:
            patches = m.text("patches", "Image patches")
            projection = m.block("proj", label="Linear projection", tone="embedding", input=patches)
            with m.row("pe", role="layout") as row:
                position = row.text("pos", "Position embedding")
                total = row.add("sum", inputs=[projection, position])
            encoder = m.block("encoder", label="Transformer encoder", tone="attention", input=total)
            head = m.mlp("head", label="MLP head", input=encoder)
            m.text("class", "Class", input=head)
    return figure


def gpt_block(theme: str = "paper") -> Figure:
    """A pre-norm decoder block (Radford et al. 2019)."""

    with Figure("gpt", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Transformer block", layout="column") as m:
            x = m.text("x", "$x$")
            norm1 = m.block("ln1", label="LayerNorm", tone="norm", input=x)
            attention = m.attention("attn", label="Masked self-attention", input=norm1)
            first = m.add("add1", inputs=[attention, x])
            norm2 = m.block("ln2", label="LayerNorm", tone="norm", input=first)
            mlp = m.mlp("mlp", label="MLP", input=norm2)
            second = m.add("add2", inputs=[mlp, first])
            m.text("y", "$y$", input=second)
    return figure


def mamba(theme: str = "paper") -> Figure:
    """The Mamba block (Gu and Dao 2023, Figure 3)."""

    with Figure("mamba", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Mamba block", layout="column") as m:
            x = m.text("x", "$x$")
            with m.row("paths", role="layout") as row:
                with row.column("main", role="layout") as column:
                    project = column.block("proj", label="Linear")
                    conv = column.block("conv", label="Conv", input=project)
                    act = column.block("act", label="SiLU", input=conv)
                    ssm = column.block("ssm", label="SSM", tone="attention", input=act)
                with row.column("gate", role="layout") as column:
                    gate_project = column.block("proj", label="Linear")
                    gate = column.block("act", label="SiLU", input=gate_project)
            product = m.multiply("product", inputs=[ssm, gate])
            out = m.block("out", label="Linear", input=product)
            m.text("y", "$y$", input=out)
        figure.net(src=x, sinks=[project, gate_project])
    return figure


def swiglu(theme: str = "paper") -> Figure:
    """A SwiGLU feed-forward layer (Shazeer 2020)."""

    with Figure("swiglu", width="single-column", theme=theme) as figure:
        with figure.module("m", label="SwiGLU feed-forward", layout="column") as m:
            x = m.text("x", "$x$")
            with m.row("projections", role="layout") as row:
                w = row.block("w", label="$W$")
                v = row.block("v", label="$V$")
            swish = m.block("swish", label="Swish", input=w)
            product = m.multiply("product", inputs=[swish, v])
            out = m.block("out", label="$W_2$", input=product)
            m.text("y", "$y$", input=out)
        figure.net(src=x, sinks=[w, v])
    return figure


def seq2seq(theme: str = "paper") -> Figure:
    """An encoder-decoder with attention (Bahdanau et al. 2015)."""

    with Figure("seq2seq", theme=theme) as figure:
        with figure.module("m", label="Encoder–decoder with attention", layout="column") as m:
            with m.row("decoder", role="layout") as row:
                s1 = row.block("s1", label="$s_1$", tone="decoder")
                s2 = row.block("s2", label="$s_2$", tone="decoder", input=s1)
                s3 = row.block("s3", label="$s_3$", tone="decoder", input=s2)
            context = m.op("context", "Σ")
            with m.row("encoder", role="layout") as row:
                states = [row.block("h1", label="$h_1$", tone="encoder")]
                for index in (2, 3, 4):
                    states.append(
                        row.block(
                            f"h{index}", label=f"$h_{index}$", tone="encoder", input=states[-1]
                        )
                    )
        figure.merge(sinks=states, dst=context)
        m.connect(context, s3, label="$c_3$")
    return figure


def unet(theme: str = "paper") -> Figure:
    """U-Net (Ronneberger et al. 2015), one block per resolution."""

    with Figure("unet", width="single-column", theme=theme) as figure:
        with figure.module("m", label="U-Net", layout="grid", columns=3) as m:
            e1 = m.block("e1", label="64", tone="encoder", at=(0, 0))
            e2 = m.block("e2", label="128", tone="encoder", input=e1, at=(1, 0))
            e3 = m.block("e3", label="256", tone="encoder", input=e2, at=(2, 0))
            bottom = m.block("bottom", label="512", tone="bottleneck", input=e3, at=(3, 1))
            d3 = m.block("d3", label="256", tone="decoder", input=bottom, at=(2, 2))
            d2 = m.block("d2", label="128", tone="decoder", input=d3, at=(1, 2))
            d1 = m.block("d1", label="64", tone="decoder", input=d2, at=(0, 2))
            for encoder, decoder in ((e1, d1), (e2, d2), (e3, d3)):
                m.connect(encoder, decoder, role="residual", label="copy")
    return figure


def agent_environment(theme: str = "paper") -> Figure:
    """The agent-environment loop (Sutton and Barto 2018, Figure 3.1)."""

    with Figure("rl", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Agent–environment interface", layout="column") as m:
            agent = m.block("agent", label="Agent", tone="agent")
            environment = m.block("environment", label="Environment", tone="environment")
            m.connect(agent, environment, label="action $A_t$", via="east")
            m.connect(environment, agent, label="state $S_{t+1}$", via="west")
            m.connect(environment, agent, label="reward $R_{t+1}$", via="west")
    return figure


def multilayer_perceptron(theme: str = "paper") -> Figure:
    """The textbook fully connected network."""

    with Figure(
        "mlp", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.module("m", label="Multilayer perceptron", column_gap="36pt") as m:
            layers = []
            for name, size, symbol in (
                ("in", 3, "x"),
                ("h1", 4, "h"),
                ("h2", 4, "h"),
                ("out", 2, "y"),
            ):
                with m.column(name, role="layout") as column:
                    layers.append(
                        [
                            column.circle(f"n{index}", f"${symbol}_{index}$", tone=symbol)
                            for index in range(1, size + 1)
                        ]
                    )
            for sources, targets in itertools.pairwise(layers):
                m.connect_all(sources, targets)
    return figure


def hidden_markov_model(theme: str = "paper") -> Figure:
    """A hidden Markov model: hidden states over observed emissions."""

    with Figure("hmm", theme=theme, conventions={"lines": "straight"}) as figure:
        with figure.module("m", label="Hidden Markov model", layout="grid", columns=4) as m:
            states = [m.circle(f"z{t}", f"$z_{t}$", at=(0, t - 1)) for t in range(1, 5)]
            observed = [
                m.circle(f"x{t}", f"$x_{t}$", shaded=True, at=(1, t - 1)) for t in range(1, 5)
            ]
        for before, after in itertools.pairwise(states):
            m.connect(before, after)
        for state, emission in zip(states, observed, strict=True):
            m.connect(state, emission)
    return figure


def variational_autoencoder(theme: str = "paper") -> Figure:
    """The VAE as a graphical model (Kingma and Welling 2014, Figure 1)."""

    with Figure(
        "pgm", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.module("m", label="Variational autoencoder", layout="grid", columns=3) as m:
            phi = m.circle("phi", r"$\phi$", at=(0, 0))
            z = m.circle("z", "$z$", at=(0, 1))
            theta = m.circle("theta", r"$\theta$", at=(0, 2))
            x = m.circle("x", "$x$", shaded=True, at=(1, 1))
        m.connect(z, x)
        m.connect(theta, z)
        m.connect(theta, x)
        m.connect(x, z, role="residual")
        m.connect(phi, z, role="residual")
    return figure


def clip(theme: str = "paper") -> Figure:
    """Contrastive language-image pre-training (Radford et al. 2021, Figure 1)."""

    with Figure("clip", theme=theme) as figure:
        with figure.module("m", label="Contrastive pre-training") as m:
            with m.grid("encoders", columns=2, role="layout") as grid:
                text = grid.text("text", "Text")
                text_encoder = grid.block(
                    "text-encoder", label="Text encoder", tone="text", input=text
                )
                image = grid.text("image", "Image")
                image_encoder = grid.block(
                    "image-encoder", label="Image encoder", tone="image", input=image
                )
            similarity = m.matrix(
                "similarity", label="Similarity", inputs=[text_encoder, image_encoder]
            )
            m.loss("loss", label="Contrastive loss", input=similarity)
    return figure


def gan(theme: str = "paper") -> Figure:
    """A generative adversarial network (Goodfellow et al. 2014)."""

    with Figure("gan", theme=theme) as figure:
        with figure.module(
            "m", label="Generative adversarial network", layout="grid", columns=4
        ) as m:
            noise = m.text("noise", "Noise $z$", at=(0, 0))
            generator = m.mlp("generator", label="Generator", input=noise, at=(0, 1))
            fake = m.block("fake", label="Fake samples", input=generator, at=(0, 2))
            real = m.block("real", label="Real samples", at=(1, 2))
            m.mlp("discriminator", label="Discriminator", inputs=[fake, real], at=(0, 3))
    return figure


def diffusion(theme: str = "paper") -> Figure:
    """The forward and reverse processes of a diffusion model (Ho et al. 2020, Figure 2)."""

    with Figure("ddpm", theme=theme) as figure:
        with figure.module("m", label="Denoising diffusion") as m:
            chain = [
                m.block("xT", label="$x_T$"),
                m.text("dots1", "···"),
                m.block("xt", label="$x_t$"),
                m.block("xs", label="$x_{t-1}$"),
                m.text("dots2", "···"),
                m.block("x0", label="$x_0$"),
            ]
            for before, after in itertools.pairwise(chain):
                m.connect(
                    before, after, label=r"$p_\theta(x_{t-1} | x_t)$" if before is chain[2] else ""
                )
            m.connect(chain[3], chain[2], label="$q(x_t | x_{t-1})$")
    return figure


def training_loop(theme: str = "paper") -> Figure:
    """A flowchart: the loop every training script runs."""

    with Figure("train", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Training loop", layout="column") as m:
            start = m.terminal("start", label="Start")
            load = m.block("load", label="Load a batch", input=start)
            forward = m.block("forward", label="Forward pass", input=load)
            loss = m.block("loss", label="Compute loss", input=forward)
            step = m.block("step", label="Update weights", input=loss)
            done = m.decision("done", label="Converged?", input=step)
            stop = m.terminal("stop", label="Stop")
        m.connect(done, stop, label="yes")
        m.connect(done, load, label="no")
    return figure


FIGURES: dict[str, Callable[[str], Figure]] = {
    make.__name__.replace("_", "-"): make
    for make in (
        inception,
        bottleneck,
        squeeze_excitation,
        lstm,
        vision_transformer,
        gpt_block,
        mamba,
        swiglu,
        seq2seq,
        unet,
        agent_environment,
        multilayer_perceptron,
        hidden_markov_model,
        variational_autoencoder,
        clip,
        gan,
        diffusion,
        training_loop,
    )
}
"""Every figure here, by name."""


def main() -> None:
    for name, make in FIGURES.items():
        for theme in ("paper", "tikz"):
            result = build(
                make(theme),
                HERE / "build" / "literature",
                stem=name if theme == "paper" else f"{name}-{theme}",
                formats=("editable", "png"),
                dpi=200,
            )
            print(result.summary())


if __name__ == "__main__":
    main()
