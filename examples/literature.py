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
            with m.row("branches") as row:
                with row.column("b1") as column:
                    one = column.block("conv", label="1×1 conv")
                with row.column("b2") as column:
                    reduce3 = column.block("reduce", label="1×1 conv")
                    three = column.block("conv", label="3×3 conv", input=reduce3)
                with row.column("b3") as column:
                    reduce5 = column.block("reduce", label="1×1 conv")
                    five = column.block("conv", label="5×5 conv", input=reduce5)
                with row.column("b4") as column:
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


def lenet(theme: str = "paper") -> Figure:
    """LeNet-5 (LeCun et al. 1998, Figure 2), each layer a volume of its shape."""

    layers = (
        ("input", (1, 32, 32), "Input\n32×32", None),
        ("c1", (6, 28, 28), "C1\n6@28×28", "conv"),
        ("s2", (6, 14, 14), "S2\n6@14×14", "pool"),
        ("c3", (16, 10, 10), "C3\n16@10×10", "conv"),
        ("s4", (16, 5, 5), "S4\n16@5×5", "pool"),
        ("f5", (120, 1, 1), "F5\n120", "dense"),
        ("f6", (84, 1, 1), "F6\n84", "dense"),
        ("output", (10, 1, 1), "Output\n10", "dense"),
    )
    with Figure("lenet", theme=theme) as figure:
        with figure.module("m", label="LeNet-5") as m:
            previous = None
            for name, shape, label, tone in layers:
                previous = m.volume(name, shape, label=label, tone=tone, input=previous)
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


def alphafold(theme: str = "paper") -> Figure:
    """AlphaFold 2 (Jumper et al. 2021, Figure 1e), with its recycling loop."""

    with Figure("alphafold", theme=theme) as figure:
        with figure.module("m", label="AlphaFold 2") as m:
            sequence = m.text("sequence", "Input\nsequence")
            with m.column("representations") as column:
                msa = column.block("msa", label="MSA\nrepresentation", tone="msa")
                pair = column.block("pair", label="Pair\nrepresentation", tone="pair")
            evoformer = m.block(
                "evoformer", label="Evoformer\n(48 blocks)", tone="evoformer", inputs=[msa, pair]
            )
            structure = m.block(
                "structure", label="Structure module\n(8 blocks)", tone="structure", input=evoformer
            )
            m.text("out", "3D\nstructure", input=structure)
        figure.net(src=sequence, sinks=[msa, pair])
        m.connect(structure, msa, label="Recycling (three times)", line="dashed", via="north")
    return figure


def bert(theme: str = "paper") -> Figure:
    """BERT pre-training (Devlin et al. 2019, Figure 1)."""

    tokens = ("[CLS]", "Tok 1", "Tok 2", "[SEP]")
    outputs = ("$C$", "$T_1$", "$T_2$", "$T_{[SEP]}$")
    with Figure("bert", width="single-column", theme=theme) as figure:
        with figure.module("m", label="BERT", layout="column") as m:
            with m.row("outputs") as row:
                heads = [row.text(f"o{index}", label) for index, label in enumerate(outputs)]
            encoder = m.block(
                "encoder", label="Transformer encoder", tone="attention", width="200pt"
            )
            with m.row("embeddings") as row:
                embeddings = [
                    row.block(f"e{index}", label=f"$E_{{{index}}}$", tone="embedding")
                    for index in range(len(tokens))
                ]
            with m.row("tokens") as row:
                words = [row.text(f"t{index}", token) for index, token in enumerate(tokens)]
        for word, embedding in zip(words, embeddings, strict=True):
            m.connect(word, embedding)
        for embedding in embeddings:
            m.connect(embedding, encoder)
        for head in heads:
            m.connect(encoder, head)
    return figure


def vision_transformer(theme: str = "paper") -> Figure:
    """The Vision Transformer (Dosovitskiy et al. 2021, Figure 1)."""

    with Figure("vit", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Vision Transformer", layout="column") as m:
            patches = m.text("patches", "Image patches")
            projection = m.block("proj", label="Linear projection", tone="embedding", input=patches)
            with m.row("pe") as row:
                position = row.text("pos", "Position embedding")
                total = row.add("sum", inputs=[projection, position])
            encoder = m.block("encoder", label="Transformer encoder", tone="attention", input=total)
            head = m.mlp("head", label="MLP head", input=encoder)
            m.text("class", "Class", input=head)
    return figure


def attention_panels(theme: str = "paper") -> Figure:
    """Scaled dot-product and multi-head attention (Vaswani et al. 2017, Figure 2)."""

    with Figure("attention", theme=theme) as figure:
        with figure.root.row("panels") as panels:
            with panels.group("a", label="Scaled dot-product attention", layout="column") as a:
                with a.row("inputs") as row:
                    q = row.text("q", "Q")
                    k = row.text("k", "K")
                    v = row.text("v", "V")
                scores = a.block("scores", label="MatMul", inputs=[q, k])
                scale = a.block("scale", label="Scale", input=scores)
                mask = a.block("mask", label="Mask (opt.)", input=scale)
                softmax = a.block("softmax", label="SoftMax", input=mask)
                a.block("weighted", label="MatMul", inputs=[softmax, v])
            with panels.group("b", label="Multi-head attention", layout="column") as b:
                with b.row("inputs") as row:
                    inputs = [row.text(name.lower(), name) for name in ("V", "K", "Q")]
                with b.row("projections") as row:
                    projections = [
                        row.block(f"linear-{index}", label="Linear", input=value)
                        for index, value in enumerate(inputs)
                    ]
                heads = b.block(
                    "heads",
                    label="Scaled dot-product attention",
                    tone="attention",
                    inputs=projections,
                )
                concat = b.block("concat", label="Concat", input=heads)
                b.block("out", label="Linear", input=concat)
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
            with m.row("paths") as row:
                with row.column("main") as column:
                    project = column.block("proj", label="Linear")
                    conv = column.block("conv", label="Conv", input=project)
                    act = column.block("act", label="SiLU", input=conv)
                    ssm = column.block("ssm", label="SSM", tone="attention", input=act)
                with row.column("gate") as column:
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
            with m.row("projections") as row:
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
            with m.row("decoder") as row:
                s1 = row.block("s1", label="$s_1$", tone="decoder")
                s2 = row.block("s2", label="$s_2$", tone="decoder", input=s1)
                s3 = row.block("s3", label="$s_3$", tone="decoder", input=s2)
            context = m.op("context", "Σ")
            with m.row("encoder") as row:
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
                with m.column(name) as column:
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
        # The inference model, dashed as in the paper.
        m.connect(x, z, line="dashed")
        m.connect(phi, z, line="dashed")
    return figure


def siamese(theme: str = "paper") -> Figure:
    """A Siamese network: two encoders sharing weights (Bromley et al. 1993)."""

    with Figure("siamese", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Siamese network", layout="grid", columns=3) as m:
            first = m.text("x1", "$x_1$", at=(0, 0))
            second = m.text("x2", "$x_2$", at=(1, 0))
            top = m.block("top", label="Encoder", tone="encoder", input=first, at=(0, 1))
            bottom = m.block("bottom", label="Encoder", tone="encoder", input=second, at=(1, 1))
            distance = m.op("distance", "$d$", at=(0, 2))
        m.connect(top, distance)
        m.connect(bottom, distance)
        m.connect(top, bottom, line="dashed", arrow="none", label="shared weights")
    return figure


def simclr(theme: str = "paper") -> Figure:
    """SimCLR (Chen et al. 2020, Figure 2): two views, one agreement."""

    with Figure("simclr", width="single-column", theme=theme) as figure:
        with figure.module("m", label="SimCLR", layout="column") as m:
            x = m.text("x", "$x$")
            with m.row("views") as row:
                first = row.text("first", r"$\tilde{x}_i$")
                second = row.text("second", r"$\tilde{x}_j$")
            with m.row("encoders") as row:
                h_first = row.block("first", label=r"$f(\cdot)$", tone="encoder", input=first)
                h_second = row.block("second", label=r"$f(\cdot)$", tone="encoder", input=second)
            with m.row("heads") as row:
                z_first = row.block("first", label=r"$g(\cdot)$", tone="head", input=h_first)
                z_second = row.block("second", label=r"$g(\cdot)$", tone="head", input=h_second)
            m.loss("agreement", label="Maximize agreement", inputs=[z_first, z_second])
        m.connect(x, first, label=r"$t \sim \mathcal{T}$")
        m.connect(x, second, label=r"$t' \sim \mathcal{T}$")
    return figure


def feature_pyramid(theme: str = "paper") -> Figure:
    """A feature pyramid network (Lin et al. 2017, Figure 3)."""

    with Figure("fpn", width="single-column", theme=theme) as figure:
        with figure.module("m", label="Feature pyramid network", layout="grid", columns=3) as m:
            c5 = m.block("c5", label="$C_5$", tone="backbone", at=(0, 0))
            c4 = m.block("c4", label="$C_4$", tone="backbone", at=(1, 0))
            c3 = m.block("c3", label="$C_3$", tone="backbone", at=(2, 0))
            p5 = m.block("p5", label="$P_5$", tone="pyramid", at=(0, 2))
            sum4 = m.add("sum4", at=(1, 1))
            p4 = m.block("p4", label="$P_4$", tone="pyramid", input=sum4, at=(1, 2))
            sum3 = m.add("sum3", at=(2, 1))
            m.block("p3", label="$P_3$", tone="pyramid", input=sum3, at=(2, 2))
        m.connect(c3, c4)
        m.connect(c4, c5)
        m.connect(c5, p5, label="1×1")
        m.connect(c4, sum4, label="1×1")
        m.connect(c3, sum3, label="1×1")
        m.connect(p5, sum4, label="2× up")
        m.connect(p4, sum3, label="2× up")
    return figure


def clip(theme: str = "paper") -> Figure:
    """Contrastive language-image pre-training (Radford et al. 2021, Figure 1)."""

    with Figure("clip", theme=theme) as figure:
        with figure.module("m", label="Contrastive pre-training") as m:
            with m.grid("encoders", columns=2) as grid:
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


def rlhf(theme: str = "paper") -> Figure:
    """Reinforcement learning from human feedback (Ouyang et al. 2022, Figure 2)."""

    steps = {
        "Step 1: supervised fine-tuning": (
            ("A prompt is sampled from the prompt dataset", "data"),
            ("A labeler demonstrates the desired output", "human"),
            ("The demonstration fine-tunes the model with supervised learning", "model"),
        ),
        "Step 2: reward model": (
            ("A prompt and several model outputs are sampled", "data"),
            ("A labeler ranks the outputs from best to worst", "human"),
            ("The ranking trains the reward model", "model"),
        ),
        "Step 3: reinforcement learning": (
            ("A new prompt is sampled from the dataset", "data"),
            ("The policy generates an output", "model"),
            ("The reward model scores the output", "model"),
            ("The reward updates the policy with PPO", "model"),
        ),
    }
    with Figure("rlhf", theme=theme) as figure:
        with figure.root.row("steps", gap="18pt") as row:
            for index, (title, boxes) in enumerate(steps.items(), 1):
                with row.group(
                    f"step{index}", label=title, layout="column", equal_size=True
                ) as step:
                    previous = None
                    for position, (words, tone) in enumerate(boxes):
                        previous = step.block(
                            f"b{position}", label=words, tone=tone, input=previous
                        )
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


def state_machine(theme: str = "paper") -> Figure:
    """A state machine: states as circles, transitions as labelled straight lines."""

    with Figure("states", theme=theme, conventions={"lines": "straight"}) as figure:
        with figure.module("m", label="Connection states", layout="grid", columns=3) as m:
            closed = m.circle("closed", "Closed", at=(0, 0))
            sent = m.circle("sent", "SYN sent", at=(0, 1))
            established = m.circle("established", "Established", shaded=True, at=(0, 2))
            waiting = m.circle("waiting", "FIN wait", at=(1, 1))
        m.connect(closed, sent, label="connect")
        m.connect(sent, established, label="SYN-ACK")
        m.connect(established, waiting, label="close")
        m.connect(waiting, closed, label="ACK")
        m.connect(sent, closed, label="timeout")
    return figure


def ci_pipeline(theme: str = "paper") -> Figure:
    """A continuous-integration flowchart, with its loop back on failure."""

    with Figure("ci", theme=theme) as figure:
        with figure.module("m", label="Continuous integration") as m:
            build = m.block(
                "build", label="Build", tone="build", input=m.terminal("push", label="Push")
            )
            with m.column("checks") as column:
                checks = [
                    column.block(name, label=label, tone="check")
                    for name, label in (
                        ("unit", "Unit tests"),
                        ("lint", "Lint"),
                        ("types", "Type check"),
                    )
                ]
            ok = m.decision("ok", label="All green?")
            deploy = m.terminal("deploy", label="Deploy")
        figure.net(src=build, sinks=checks)
        figure.merge(sinks=checks, dst=ok)
        m.connect(ok, deploy, label="yes")
        m.connect(ok, build, label="no", line="dashed")
    return figure


def feedback_control(theme: str = "paper") -> Figure:
    """A feedback control loop, as in any control textbook."""

    with Figure("feedback-control", theme=theme) as figure:
        with figure.root.row("loop") as loop:
            reference = loop.text("r", "$r(t)$")
            error = loop.add("error", input=reference)
            controller = loop.block("controller", label="PID controller", input=error)
            plant = loop.block("plant", label="Plant", input=controller)
            loop.text("y", "$y(t)$", input=plant)
        figure.connect(plant, error, label="$-y$")
    return figure


def faster_rcnn(theme: str = "paper") -> Figure:
    """Faster R-CNN (Ren et al. 2015, Figure 2)."""

    with Figure("faster-rcnn", width="single-column", theme=theme) as figure:
        with figure.module("detector", label="Faster R-CNN", layout="column") as m:
            image = m.text("image", "image")
            convolutions = m.block("conv", label="conv layers", input=image)
            maps = m.block("maps", label="feature maps", tone="data", input=convolutions)
            proposals = m.block("rpn", label="Region Proposal Network")
            pooling = m.block("roi", label="RoI pooling")
            m.block("classifier", label="classifier", input=pooling)
        figure.net(src=maps, sinks=[proposals, pooling])
        figure.connect(proposals, pooling, label="proposals")
    return figure


def mixture_of_experts(theme: str = "paper") -> Figure:
    """A sparse mixture-of-experts layer (Fedus et al. 2022, Figure 2)."""

    with Figure("mixture-of-experts", theme=theme) as figure:
        with figure.module("switch", label="Switch layer", layout="column") as m:
            x = m.text("x", "$x$")
            router = m.block("router", label="Router", input=x)
            with m.row("experts") as row:
                experts = [row.block(f"e{i}", label=f"FFN {i}") for i in range(1, 5)]
            total = m.add("sum", inputs=experts)
            m.text("y", "$y$", input=total)
        figure.net(src=router, sinks=experts, label="$p_i(x)$")
    return figure


def lora(theme: str = "paper") -> Figure:
    """Low-rank adaptation (Hu et al. 2021, Figure 1)."""

    with Figure("lora", width="single-column", theme=theme) as figure:
        with figure.module("lora", label="LoRA", layout="column") as m:
            x = m.text("x", "$x$")
            with m.row("paths") as paths:
                frozen = paths.block(
                    "w", label=r"Pretrained weights $W \in \mathbb{R}^{d\times d}$", tone="frozen"
                )
                with paths.column("adapter") as adapter:
                    down = adapter.block("a", label=r"$A = \mathcal{N}(0, \sigma^2)$")
                    up = adapter.block("b", label="$B = 0$", input=down)
            total = m.add("sum", inputs=[frozen, up])
            m.text("h", "$h$", input=total)
        figure.net(src=x, sinks=[frozen, down])
    return figure


def retrieval_augmented_generation(theme: str = "paper") -> Figure:
    """Retrieval-augmented generation (Lewis et al. 2020, Figure 1)."""

    with Figure("rag", theme=theme) as figure:
        with figure.root.row("flow") as flow:
            query = flow.text("query", "Query $x$")
            encoder = flow.block("encoder", label="Query encoder $q(x)$", input=query)
            with flow.column("retriever", label="Retriever") as retriever:
                search = retriever.block("mips", label="MIPS", input=encoder)
                index = retriever.block("index", label="Document index $d(z)$", tone="data")
            generator = flow.block("generator", label=r"Generator $p_\theta$", tone="model")
            flow.text("answer", "Answer $y$", input=generator)
        figure.connect(index, search)
        figure.connect(search, generator, label="top-$k$ documents")
        figure.connect(query, generator)
    return figure


def latent_diffusion(theme: str = "paper") -> Figure:
    """Latent diffusion (Rombach et al. 2022, Figure 3)."""

    with Figure("latent-diffusion", theme=theme) as figure:
        with figure.root.row("spaces") as spaces:
            with spaces.column("pixel", label="Pixel space") as pixel:
                x = pixel.text("x", "$x$")
                encoder = pixel.block("encoder", label=r"$\mathcal{E}$", input=x)
                decoder = pixel.block("decoder", label=r"$\mathcal{D}$")
                pixel.text("reconstruction", r"$\tilde{x}$", input=decoder)
            with spaces.column("latent", label="Latent space") as latent:
                noising = latent.block("diffusion", label="Diffusion process", input=encoder)
                denoiser = latent.block(
                    "unet", label=r"Denoising U-Net $\epsilon_\theta$", input=noising
                )
            with spaces.column("conditioning", label="Conditioning") as conditioning:
                text = conditioning.text("text", "Text")
                condition = conditioning.block("tau", label=r"$\tau_\theta$", input=text)
        figure.connect(denoiser, decoder)
        figure.connect(condition, denoiser, label="cross-attention")
    return figure


def actor_critic(theme: str = "paper") -> Figure:
    """Actor-critic (Sutton and Barto 2018, Figure 6.15 of the first edition)."""

    with Figure("actor-critic", theme=theme) as figure:
        with figure.root.column("loop") as loop:
            with loop.group("agent", label="Agent", layout="row") as agent:
                actor = agent.block("actor", label="Actor (policy)")
                critic = agent.block("critic", label="Critic (value)")
            environment = loop.block("environment", label="Environment", tone="data")
        figure.connect(actor, environment, label="action")
        figure.connect(environment, critic, label="state, reward")
        figure.connect(environment, actor, label="state")
        figure.connect(critic, actor, label="TD error")
    return figure


def mapreduce(theme: str = "paper") -> Figure:
    """MapReduce execution (Dean and Ghemawat 2004, Figure 1)."""

    with Figure("mapreduce", theme=theme) as figure:
        with figure.root.row("stages") as stages:
            with stages.column("inputs", label="Input files") as inputs:
                splits = [
                    inputs.block(f"split{k}", label=f"split {k}", tone="data") for k in range(3)
                ]
            with stages.column("map", label="Map phase") as map_phase:
                mappers = [
                    map_phase.block(f"m{k}", label="worker", input=split)
                    for k, split in enumerate(splits)
                ]
            with stages.column("reduce", label="Reduce phase") as reduce_phase:
                reducers = [reduce_phase.block(f"r{k}", label="worker") for k in range(2)]
            with stages.column("outputs", label="Output files") as outputs:
                for k, reducer in enumerate(reducers):
                    outputs.block(f"out{k}", label=f"output {k}", tone="data", input=reducer)
        figure.connect_all(mappers, reducers, shape="straight")
    return figure


def compiler(theme: str = "paper") -> Figure:
    """The phases of a compiler and the symbol table they share (Aho et al., Figure 1.6)."""

    with Figure("compiler", theme=theme) as figure:
        with figure.root.row("main") as main:
            with main.column("phases") as column:
                source = column.text("source", "character stream")
                phases = []
                for index, name in enumerate(
                    (
                        "Lexical analyzer",
                        "Syntax analyzer",
                        "Semantic analyzer",
                        "Intermediate code generator",
                        "Code optimizer",
                        "Code generator",
                    )
                ):
                    source = column.block(f"phase{index}", label=name, input=source)
                    phases.append(source)
                column.text("target", "target machine code", input=source)
            table = main.block("table", label="Symbol table", tone="data")
        for phase in phases:
            figure.connect(phase, table, arrow="none", line="dotted")
    return figure


FIGURES: dict[str, Callable[[str], Figure]] = {
    make.__name__.replace("_", "-"): make
    for make in (
        inception,
        lenet,
        bottleneck,
        squeeze_excitation,
        lstm,
        vision_transformer,
        attention_panels,
        bert,
        alphafold,
        gpt_block,
        mamba,
        swiglu,
        seq2seq,
        unet,
        agent_environment,
        multilayer_perceptron,
        hidden_markov_model,
        variational_autoencoder,
        siamese,
        simclr,
        feature_pyramid,
        clip,
        gan,
        diffusion,
        rlhf,
        training_loop,
        ci_pipeline,
        state_machine,
        feedback_control,
        faster_rcnn,
        mixture_of_experts,
        lora,
        retrieval_augmented_generation,
        latent_diffusion,
        actor_critic,
        mapreduce,
        compiler,
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
