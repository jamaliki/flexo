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
        with figure.module("m", label="Siamese network", layout="flow-right") as m:
            first = m.block("top", label="Encoder", tone="encoder", input=m.text("x1", "$x_1$"))
            second = m.block(
                "bottom", label="Encoder", tone="encoder", input=m.text("x2", "$x_2$")
            )
            m.op("distance", "$d$", inputs=[first, second])
            m.connect(first, second, line="dashed", arrow="none", label="shared weights")
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
            "m", label="Generative adversarial network", layout="flow-right"
        ) as m:
            noise = m.text("noise", "Noise $z$")
            generator = m.mlp("generator", label="Generator", input=noise)
            fake = m.block("fake", label="Fake samples", input=generator)
            real = m.block("real", label="Real samples")
            m.mlp("discriminator", label="Discriminator", inputs=[fake, real])
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
                    "w",
                    label=r"Pretrained weights $W \in \mathbb{R}^{d\times d}$",
                    tone="frozen",
                    badge="frozen",
                )
                with paths.column("adapter") as adapter:
                    down = adapter.block(
                        "a", label=r"$A = \mathcal{N}(0, \sigma^2)$", badge="trained"
                    )
                    up = adapter.block("b", label="$B = 0$", input=down, badge="trained")
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


def sprinkler(theme: str = "paper") -> Figure:
    """The sprinkler Bayesian network (Pearl 1988; Russell and Norvig, Figure 14.12)."""

    with Figure(
        "sprinkler", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.root.column("network") as network:
            cloudy = network.circle("cloudy", label="Cloudy")
            with network.row("causes") as causes:
                sprinkler = causes.circle("sprinkler", label="Sprinkler", input=cloudy)
                rain = causes.circle("rain", label="Rain", input=cloudy)
            network.circle("wet", label="Wet grass", inputs=[sprinkler, rain])
    return figure


def kalman_filter(theme: str = "paper") -> Figure:
    """The Kalman filter's predict-update cycle."""

    with Figure("kalman-filter", theme=theme) as figure:
        with figure.root.row("cycle") as cycle:
            prior = cycle.text("prior", r"$\hat{x}_0, P_0$")
            predict = cycle.block(
                "predict", label="Predict\n$\\hat{x}^-_k = A\\hat{x}_{k-1}$", input=prior
            )
            update = cycle.block(
                "update",
                label="Update\n$\\hat{x}_k = \\hat{x}^-_k + K_k(z_k - H\\hat{x}^-_k)$",
                input=predict,
            )
        figure.connect(update, predict, label=r"$k \to k+1$")
        measurement = figure.root.text("z", "measurement $z_k$")
        figure.connect(measurement, update)
    return figure


def cbow(theme: str = "paper") -> Figure:
    """Continuous bag of words (Mikolov et al. 2013, Figure 1)."""

    with Figure("cbow", width="single-column", theme=theme) as figure:
        with figure.root.row("model") as model:
            with model.column("context", label="Input") as context:
                words = [context.block(f"w{i}", label=f"$w(t{i:+d})$") for i in (-2, -1, 1, 2)]
            total = model.add("sum", inputs=words)
            with model.column("output", label="Output") as output:
                output.block("wt", label="$w(t)$", input=total)
    return figure


def distillation(theme: str = "paper") -> Figure:
    """Knowledge distillation (Hinton et al. 2015)."""

    with Figure("distillation", theme=theme) as figure:
        with figure.root.row("main") as main:
            x = main.text("x", "Input $x$")
            with main.column("models") as models:
                teacher = models.block("teacher", label="Teacher (large, frozen)", tone="frozen")
                student = models.block("student", label="Student (small)", tone="model")
            with main.column("outputs") as outputs:
                soft = outputs.block(
                    "soft", label=r"Soft targets $\sigma(z_t / T)$", input=teacher
                )
                predictions = outputs.block(
                    "predictions", label=r"Soft predictions $\sigma(z_s / T)$", input=student
                )
            main.block("loss", label="Distillation loss", inputs=[soft, predictions])
        figure.net(src=x, sinks=[teacher, student])
    return figure


def cpu_pipeline(theme: str = "paper") -> Figure:
    """The five-stage RISC pipeline with forwarding (Hennessy and Patterson)."""

    with Figure("cpu-pipeline", theme=theme) as figure:
        with figure.root.row("stages") as stages:
            fetch = stages.block("if", label="IF")
            decode = stages.block("id", label="ID", input=fetch)
            execute = stages.block("ex", label="EX", input=decode)
            memory = stages.block("mem", label="MEM", input=execute)
            write = stages.block("wb", label="WB", input=memory)
        figure.connect(memory, execute, label="forward")
        figure.connect(write, execute, label="forward")
        figure.connect(write, decode, label="write back")
    return figure


def model_view_controller(theme: str = "paper") -> Figure:
    """Model-view-controller."""

    with Figure("mvc", width="single-column", theme=theme) as figure:
        with figure.root.column("parts") as parts:
            model = parts.block("model", label="Model")
            with parts.row("front") as front:
                view = front.block("view", label="View")
                controller = front.block("controller", label="Controller")
        figure.connect(model, view, label="updates")
        figure.connect(view, controller, label="user actions")
        figure.connect(controller, model, label="manipulates")
    return figure


def load_balancer(theme: str = "paper") -> Figure:
    """A load-balanced web service."""

    with Figure("load-balancer", theme=theme) as figure:
        with figure.root.row("tiers") as tiers:
            clients = tiers.block("clients", label="Clients", tone="human")
            balancer = tiers.block("balancer", label="Load balancer", input=clients)
            with tiers.column("servers", label="App servers") as column:
                servers = [column.block(f"s{i}", label=f"server {i}") for i in range(1, 4)]
            tiers.block("database", label="Database", tone="data", inputs=servers)
        figure.net(src=balancer, sinks=servers)
    return figure


def federated_averaging(theme: str = "paper") -> Figure:
    """Federated averaging (McMahan et al. 2017)."""

    with Figure("federated-averaging", theme=theme) as figure:
        with figure.root.column("system") as system:
            server = system.block(
                "server", label=r"Server: $w \leftarrow \sum_k \frac{n_k}{n} w_k$", tone="model"
            )
            with system.row("clients") as row:
                clients = [row.block(f"c{k}", label=f"Client {k}", tone="data") for k in (1, 2, 3)]
        for client in clients:
            figure.connect(server, client)
            figure.connect(client, server, line="dashed")
    return figure


def two_tower(theme: str = "paper") -> Figure:
    """A two-tower retrieval model (Yi et al. 2019)."""

    with Figure("two-tower", width="single-column", theme=theme) as figure:
        with figure.root.column("model") as model:
            with model.row("towers") as towers:
                with towers.column("query", label="Query tower") as query:
                    user = query.block(
                        "mlp", label="MLP", input=query.text("features", "user features")
                    )
                with towers.column("candidate", label="Candidate tower") as candidate:
                    item = candidate.block(
                        "mlp", label="MLP", input=candidate.text("features", "item features")
                    )
            score = model.op("dot", ".", inputs=[user, item])
            model.text("score", "score $s(u, v)$", input=score)
    return figure


def network_stack(theme: str = "paper") -> Figure:
    """Two hosts talking through the network stack."""

    layers = ("Application", "Transport", "Network", "Link", "Physical")
    with Figure("network-stack", theme=theme) as figure:
        with figure.root.row("hosts", gap="60pt") as hosts:
            stacks = []
            for host in ("A", "B"):
                with hosts.column(host, label=f"Host {host}", equal_size=True) as column:
                    stacks.append([column.block(name.lower(), label=name) for name in layers])
        sender, receiver = stacks
        for upper, lower in itertools.pairwise(sender):
            figure.connect(upper, lower)
        for lower, upper in itertools.pairwise(reversed(receiver)):
            figure.connect(lower, upper)
        for mine, theirs in zip(sender[:-1], receiver[:-1], strict=True):
            figure.connect(mine, theirs, line="dashed", arrow="both")
        figure.connect(sender[-1], receiver[-1], label="medium")
    return figure


def batch_normalization(theme: str = "paper") -> Figure:
    """Batch normalisation as a computation graph (Ioffe and Szegedy 2015)."""

    with Figure("batch-normalization", theme=theme) as figure:
        with figure.root.row("graph") as graph:
            x = graph.text("x", "$x$")
            with graph.column("statistics") as statistics:
                mean = statistics.block("mean", label=r"$\mu_B$")
                variance = statistics.block("variance", label=r"$\sigma^2_B$")
            centred = graph.op("centre", "-", inputs=[x, mean])
            scaled = graph.op("scale", "/", inputs=[centred, variance])
            stretched = graph.op("gamma", "x", input=scaled)
            shifted = graph.add("beta", input=stretched)
            graph.text("y", "$y$", input=shifted)
        figure.net(src=x, sinks=[mean, variance])
    return figure


def skip_gram(theme: str = "paper") -> Figure:
    """Skip-gram (Mikolov et al. 2013, Figure 1)."""

    with Figure("skip-gram", width="single-column", theme=theme) as figure:
        with figure.root.row("model") as model:
            with model.column("input", label="Input") as column:
                word = column.block("wt", label="$w(t)$")
            projection = model.block("projection", label="Projection", input=word)
            with model.column("output", label="Output") as column:
                for i in (-2, -1, 1, 2):
                    column.block(f"w{i}", label=f"$w(t{i:+d})$", input=projection)
    return figure


def extract_transform_load(theme: str = "paper") -> Figure:
    """An extract-transform-load pipeline into a warehouse."""

    with Figure("etl", theme=theme) as figure:
        with figure.root.row("flow") as flow:
            with flow.column("sources", label="Sources") as column:
                sources = [
                    column.block(name.lower().replace(" ", "-"), label=name, tone="data")
                    for name in ("CRM", "Orders", "Web logs", "Payments")
                ]
            extract = flow.block("extract", label="Extract", inputs=sources)
            transform = flow.block("transform", label="Transform", input=extract)
            load = flow.block("load", label="Load", input=transform)
            warehouse = flow.block("warehouse", label="Warehouse", tone="data", input=load)
            with flow.column("consumers", label="Consumers") as column:
                for name in ("Dashboards", "ML features", "Reports"):
                    column.block(name.lower().replace(" ", "-"), label=name, input=warehouse)
    return figure


def autoencoder(theme: str = "paper") -> Figure:
    """An undercomplete autoencoder."""

    with Figure("autoencoder", theme=theme) as figure:
        with figure.root.row("network") as network:
            x = network.text("x", "$x$")
            with network.group("encoder", label="Encoder", layout="row") as encoder:
                wide = encoder.block("h1", label="512", height="80pt", input=x)
                narrow = encoder.block("h2", label="128", height="50pt", input=wide)
            code = network.block("z", label="$z$", height="24pt", tone="model", input=narrow)
            with network.group("decoder", label="Decoder", layout="row") as decoder:
                narrow = decoder.block("g1", label="128", height="50pt", input=code)
                wide = decoder.block("g2", label="512", height="80pt", input=narrow)
            network.text("reconstruction", r"$\hat{x}$", input=wide)
    return figure


def message_passing(theme: str = "paper") -> Figure:
    """One round of message passing on a small graph (Gilmer et al. 2017)."""

    with Figure(
        "message-passing", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.module("graph", label="Message passing", layout="grid", columns=3) as graph:
            centre = graph.circle("v", "$h_v$", shaded=True, at=(1, 1))
            corners = [
                graph.circle(f"u{i}", f"$h_{i}$", at=cell)
                for i, cell in enumerate(((0, 0), (0, 2), (2, 0), (2, 2)), 1)
            ]
        for neighbour in corners:
            figure.connect(neighbour, centre)
        figure.connect(corners[0], corners[1], arrow="none")
        figure.connect(corners[2], corners[3], arrow="none")
    return figure


def recurrent_network(theme: str = "paper") -> Figure:
    """A recurrent network, rolled up (Olah 2015)."""

    with Figure("recurrent-network", width="single-column", theme=theme) as figure:
        with figure.root.column("cell") as column:
            state = column.text("h", "$h_t$")
            cell = column.block("a", label="$A$", tone="model")
            x = column.text("x", "$x_t$")
        figure.connect(x, cell)
        figure.connect(cell, state)
        figure.connect(cell, cell)
    return figure


def unrolled_recurrent_network(theme: str = "paper") -> Figure:
    """A recurrent network, unrolled through time (Olah 2015)."""

    with Figure("unrolled-recurrent-network", theme=theme) as figure:
        with figure.root.grid("time", columns=4) as grid:
            cells = []
            for t in range(4):
                state = grid.text(f"h{t}", f"$h_{t}$", at=(0, t))
                cell = grid.block(f"a{t}", label="$A$", tone="model", at=(1, t))
                x = grid.text(f"x{t}", f"$x_{t}$", at=(2, t))
                figure.connect(x, cell)
                figure.connect(cell, state)
                cells.append(cell)
        for before, after in itertools.pairwise(cells):
            figure.connect(before, after)
    return figure


def markov_chain(theme: str = "paper") -> Figure:
    """A two-state Markov chain, with the chance of staying put."""

    with Figure(
        "markov-chain", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.root.row("states", gap="40pt") as states:
            sunny = states.circle("sunny", "Sunny")
            rainy = states.circle("rainy", "Rainy")
        figure.connect(sunny, rainy, label="0.1")
        figure.connect(rainy, sunny, label="0.5")
        figure.connect(sunny, sunny, label="0.9")
        figure.connect(rainy, rainy, label="0.5")
    return figure


def impala(theme: str = "paper") -> Figure:
    """IMPALA's actors and learner (Espeholt et al. 2018, Figure 1)."""

    with Figure("impala", theme=theme) as figure:
        with figure.root.row("system") as system:
            with system.column("actors", label="Actors") as column:
                actors = [column.block(f"a{k}", label=f"Actor {k}") for k in (1, 2, 3)]
            queue = system.block("queue", label="Trajectory queue", tone="data", inputs=actors)
            learner = system.block("learner", label="Learner (GPU)", tone="model", input=queue)
        figure.net(src=learner, sinks=actors, label="parameters", line="dashed")
    return figure


def class_hierarchy(theme: str = "paper") -> Figure:
    """A class hierarchy: each subclass points to the class it extends."""

    with Figure("class-hierarchy", width="single-column", theme=theme) as figure:
        with figure.root.column("classes") as column:
            base = column.block("module", label="Module")
            with column.row("subclasses") as row:
                subclasses = [
                    row.block(name.lower(), label=name) for name in ("Linear", "Conv2d", "LSTM")
                ]
        figure.merge(sinks=subclasses, dst=base)
    return figure


def decision_tree(theme: str = "paper") -> Figure:
    """A decision tree for the iris flowers."""

    with Figure("decision-tree", theme=theme) as figure:
        with figure.root.column("tree") as tree:
            root = tree.decision("root", label="petal length < 2.5?")
            with tree.row("first") as row:
                setosa = row.terminal("setosa", label="setosa")
                width = row.decision("width", label="petal width < 1.8?")
            with tree.row("second") as row:
                versicolor = row.terminal("versicolor", label="versicolor")
                virginica = row.terminal("virginica", label="virginica")
        figure.connect(root, setosa, label="yes")
        figure.connect(root, width, label="no")
        figure.connect(width, versicolor, label="yes")
        figure.connect(width, virginica, label="no")
    return figure


def neural_turing_machine(theme: str = "paper") -> Figure:
    """A Neural Turing Machine (Graves et al. 2014, Figure 1)."""

    with Figure("neural-turing-machine", width="single-column", theme=theme) as figure:
        with figure.root.column("machine") as machine:
            with machine.row("io") as io:
                x = io.text("x", "External input")
                y = io.text("y", "External output")
            controller = machine.block("controller", label="Controller", tone="model", input=x)
            with machine.row("heads") as heads:
                read = heads.block("read", label="Read heads")
                write = heads.block("write", label="Write heads")
            memory = machine.block("memory", label="Memory", tone="data", width="160pt")
        figure.connect(controller, y)
        figure.connect(controller, read)
        figure.connect(controller, write)
        figure.connect(memory, read)
        figure.connect(write, memory)
        figure.connect(read, controller)
    return figure


def react_agent(theme: str = "paper") -> Figure:
    """The ReAct loop of reasoning and acting (Yao et al. 2023)."""

    with Figure("react-agent", width="single-column", theme=theme) as figure:
        with figure.root.grid("loop", columns=2) as grid:
            model = grid.block("llm", label="Language model", tone="model", at=(0, 0))
            thought = grid.block("thought", label="Thought", at=(0, 1))
            action = grid.block("action", label="Action", at=(1, 1))
            observation = grid.block("observation", label="Observation", tone="data", at=(1, 0))
        figure.connect(model, thought)
        figure.connect(thought, action)
        figure.connect(action, observation, label="tool call")
        figure.connect(observation, model)
    return figure


def llava(theme: str = "paper") -> Figure:
    """LLaVA (Liu et al. 2023, Figure 1): an image and an instruction into one model."""

    with Figure("llava", theme=theme) as figure:
        with figure.root.column("model") as column:
            response = column.text("response", "Language response")
            language = column.block(
                "llm", label=r"Language model $f_\phi$", tone="model", width="220pt", badge="tuned"
            )
            with column.row("inputs") as inputs:
                with inputs.column("vision", reverse=True) as vision:  # flows upward
                    image = vision.text("image", "Image $X_v$")
                    encoder = vision.block(
                        "encoder",
                        label="Vision encoder",
                        tone="frozen",
                        input=image,
                        badge="frozen",
                    )
                    projection = vision.block(
                        "projection", label="Projection $W$", input=encoder, badge="trained"
                    )
                instruction = inputs.text("instruction", "Instruction $X_q$")
        figure.connect(projection, language, label="$H_v$")
        figure.connect(instruction, language, label="$H_q$")
        figure.connect(language, response)
    return figure


def code_review(theme: str = "paper") -> Figure:
    """A code-review flowchart with its loop back for fixes."""

    with Figure("code-review", width="single-column", theme=theme) as figure:
        with figure.module("review", label="Code review", layout="column") as m:
            opened = m.terminal("open", label="Open pull request")
            checks = m.decision("ci", label="CI passes?", input=opened)
            approved = m.decision("approved", label="Approved?")
            merged = m.terminal("merge", label="Merge")
            fix = m.block("fix", label="Push a fix")
        m.connect(checks, approved, label="yes")
        m.connect(approved, merged, label="yes")
        m.connect(checks, fix, label="no")
        m.connect(approved, fix, label="no")
        m.connect(fix, checks)
    return figure


def dit_block(theme: str = "paper") -> Figure:
    """A DiT block with adaLN-Zero conditioning (Peebles and Xie 2023, Figure 3)."""

    with Figure("dit-block", width="single-column", theme=theme) as figure:
        with figure.root.row("block") as block:
            with block.column("main") as main:
                x = main.text("x", "Input tokens")
                norm = main.block("norm", label="Layer norm", input=x)
                scaled = main.op("scale", "x", input=norm)
                attention = main.block("attention", label="Self-attention", input=scaled)
                gated = main.op("gate", "x", input=attention)
                total = main.add("sum", input=gated)
                main.text("y", "Output", input=total)
            with block.column("conditioning") as conditioning:
                c = conditioning.text("c", "Conditioning $c$")
                mlp = conditioning.block("mlp", label="MLP", input=c)
        figure.net(src=mlp, sinks=[scaled, gated], label=r"$\gamma, \alpha$")
        figure.residual(x, total)
    return figure


def speculative_decoding(theme: str = "paper") -> Figure:
    """Speculative decoding (Leviathan et al. 2023)."""

    with Figure("speculative-decoding", theme=theme) as figure:
        with figure.root.row("decoding") as row:
            prefix = row.text("prefix", "prefix")
            draft = row.block("draft", label="Draft model", tone="model", input=prefix)
            target = row.block("target", label="Target model", tone="model")
            verdict = row.decision("accept", label="accept?", input=target)
            row.text("tokens", "tokens", input=verdict)
        figure.connect(draft, target, label="$k$ guesses")
        figure.connect(verdict, draft, label="first rejection")
    return figure


def multi_task_learning(theme: str = "paper") -> Figure:
    """Multi-task learning with a shared encoder, written flat: ``flow`` lays it out."""

    with Figure("multi-task-learning", width="single-column", theme=theme) as figure:
        with figure.module("model", label="Multi-task learning", layout="flow") as m:
            x = m.text("x", "Input $x$")
            shared = m.block("shared", label="Shared encoder", tone="model", input=x)
            losses = []
            for index, task in enumerate(("Segmentation", "Depth", "Normals"), 1):
                head = m.block(task.lower(), label=task, input=shared)
                losses.append(m.loss(f"loss{index}", label=rf"$\mathcal{{L}}_{index}$", input=head))
            m.add("total", inputs=losses)
    return figure


def citric_acid_cycle(theme: str = "paper") -> Figure:
    """The citric acid cycle, laid round a ring with ``layout="cycle"``."""

    names = (
        "Citrate",
        "Isocitrate",
        "α-Ketoglutarate",
        "Succinyl-CoA",
        "Succinate",
        "Fumarate",
        "Malate",
        "Oxaloacetate",
    )
    with Figure("citric-acid-cycle", theme=theme) as figure:
        with figure.module("cycle", label="Citric acid cycle", layout="cycle") as m:
            steps = [m.block(f"s{index}", label=name) for index, name in enumerate(names)]
        for before, after in zip(steps, steps[1:] + steps[:1], strict=True):
            figure.connect(before, after)
    return figure


def alphazero(theme: str = "paper") -> Figure:
    """AlphaZero's training loop (Silver et al. 2018), as a ``cycle``."""

    with Figure("alphazero", width="single-column", theme=theme) as figure:
        with figure.module("loop", label="AlphaZero training", layout="cycle") as m:
            steps = [
                m.block("play", label="Self-play with MCTS"),
                m.block("games", label="Games buffer", tone="data"),
                m.block("train", label="Train network", tone="model"),
                m.block("network", label=r"Network $f_\theta$", tone="model"),
            ]
        for before, after in zip(steps, steps[1:] + steps[:1], strict=True):
            figure.connect(before, after)
    return figure


def knowledge_graph(theme: str = "paper") -> Figure:
    """A small knowledge graph: entities and labelled relations."""

    with Figure(
        "knowledge-graph", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.module("graph", label="Knowledge graph", layout="grid", columns=3) as m:
            curie = m.circle("curie", "Curie", at=(0, 0))
            radium = m.circle("radium", "Radium", at=(0, 2))
            paris = m.circle("paris", "Paris", at=(1, 1))
            nobel = m.circle("nobel", "Nobel", at=(2, 0))
        figure.connect(curie, radium, label="discovered")
        figure.connect(curie, paris, label="lived in")
        figure.connect(curie, nobel, label="won")
        figure.connect(radium, paris, label="isolated in")
    return figure


def dqn(theme: str = "paper") -> Figure:
    """Deep Q-learning with experience replay and a target network (Mnih et al. 2015)."""

    with Figure("dqn", theme=theme) as figure:
        with figure.root.row("agent") as row:
            environment = row.block("env", label="Environment", tone="data")
            replay = row.block("buffer", label="Replay buffer", tone="data", input=environment)
            with row.column("networks") as networks:
                online = networks.block("q", label=r"Q-network $Q(s, a; \theta)$", tone="model")
                target = networks.block(
                    "target", label=r"Target network $Q(s, a; \theta^-)$", tone="frozen"
                )
            loss = row.block("loss", label="TD loss", inputs=[online, target])
        figure.net(src=replay, sinks=[online, target], label="minibatch")
        figure.connect(online, environment, label=r"$\epsilon$-greedy action")
        figure.connect(online, target, label="copy every $C$ steps", line="dashed")
        figure.connect(loss, online, label=r"$\nabla_\theta$", line="dashed")
    return figure


def lda(theme: str = "paper") -> Figure:
    """Latent Dirichlet allocation in plate notation (Blei, Ng and Jordan 2003, Figure 1)."""

    with Figure(
        "lda", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.root.row("model") as model:
            alpha = model.circle("alpha", r"$\alpha$")
            with model.plate("documents", "$M$") as documents:
                theta = documents.circle("theta", r"$\theta$", input=alpha)
                with documents.plate("words", "$N$") as words:
                    z = words.circle("z", "$z$", input=theta)
                    w = words.circle("w", "$w$", shaded=True, input=z)
            beta = model.circle("beta", r"$\beta$")
        figure.connect(beta, w)
    return figure


def bidirectional_rnn(theme: str = "paper") -> Figure:
    """A bidirectional recurrent network (Schuster and Paliwal 1997; Graves 2013)."""

    with Figure("bidirectional-rnn", theme=theme) as figure:
        with figure.root.grid("time", columns=4) as grid:
            forward, backward = [], []
            for t in range(4):
                y = grid.text(f"y{t}", f"$y_{t}$", at=(0, t))
                back = grid.block(
                    f"b{t}", label=r"$\overleftarrow{h}$", tone="backward", at=(1, t)
                )
                ahead = grid.block(
                    f"f{t}", label=r"$\overrightarrow{h}$", tone="forward", at=(2, t)
                )
                x = grid.text(f"x{t}", f"$x_{t}$", at=(3, t))
                figure.connect(x, ahead)
                figure.connect(x, back)
                figure.connect(ahead, y)
                figure.connect(back, y)
                forward.append(ahead)
                backward.append(back)
        for before, after in itertools.pairwise(forward):
            figure.connect(before, after)
        for before, after in itertools.pairwise(backward):
            figure.connect(after, before)
    return figure


def bahdanau_attention(theme: str = "paper") -> Figure:
    """Sequence-to-sequence with additive attention (Bahdanau et al. 2015, Figure 1)."""

    with Figure("bahdanau-attention", theme=theme) as figure:
        with figure.root.column("model") as model:
            with model.row("decoder") as decoder:
                previous = decoder.block("s1", label="$s_{t-1}$", tone="decoder")
                state = decoder.block("s", label="$s_t$", tone="decoder", input=previous)
                decoder.text("y", "$y_t$", input=state)
            context = model.add("context")
            with model.row("encoder") as encoder:
                annotations = [
                    encoder.block(f"h{j}", label=f"$h_{j}$", tone="encoder") for j in range(1, 5)
                ]
            with model.row("inputs") as inputs:
                for j, h in enumerate(annotations, start=1):
                    inputs.text(f"x{j}", f"$x_{j}$")
                    figure.connect(f"model.inputs.x{j}", h)
        for j, h in enumerate(annotations, start=1):
            figure.connect(h, context, label=rf"$\alpha_{{t,{j}}}$")
        figure.connect(context, state, label="$c_t$")
        for before, after in itertools.pairwise(annotations):
            figure.connect(before, after)
    return figure


def cyclegan(theme: str = "paper") -> Figure:
    """CycleGAN: two mappings and their cycle consistency (Zhu et al. 2017, Figure 3)."""

    with Figure("cyclegan", theme=theme, conventions={"lines": "straight"}) as figure:
        with figure.root.row("domains", gap="60pt") as row:
            with row.column("x-side") as left:
                dx = left.block("dx", label="$D_X$", tone="discriminator")
                x = left.circle("x", "$X$")
            with row.column("y-side") as right:
                dy = right.block("dy", label="$D_Y$", tone="discriminator")
                y = right.circle("y", "$Y$")
        figure.connect(x, y, label="$G$")
        figure.connect(y, x, label="$F$")
        figure.connect(x, dx)
        figure.connect(y, dy)
    return figure


def kubernetes(theme: str = "paper") -> Figure:
    """A Kubernetes cluster: the control plane and two worker nodes."""

    with Figure("kubernetes", theme=theme) as figure:
        with figure.root.row("cluster") as cluster:
            user = cluster.text("kubectl", "kubectl")
            with cluster.module("control", label="Control plane", layout="column") as control:
                api = control.block("api", label="API server", tone="control", input=user)
                with control.row("services") as services:
                    etcd = services.block("etcd", label="etcd", tone="store")
                    scheduler = services.block("scheduler", label="Scheduler")
                    manager = services.block("manager", label="Controller manager")
            with cluster.column("workers") as workers:
                nodes = []
                for k in (1, 2):
                    with workers.module(f"node{k}", label=f"Node {k}", layout="row") as node:
                        kubelet = node.block("kubelet", label="kubelet", tone="agent")
                        node.block("pods", label="Pods", tone="pod", input=kubelet)
                        node.block("proxy", label="kube-proxy")
                    nodes.append(kubelet)
        figure.connect(api, etcd)
        figure.connect(scheduler, api)
        figure.connect(manager, api)
        for kubelet in nodes:
            figure.connect(api, kubelet)
    return figure


def perceptron(theme: str = "paper") -> Figure:
    """Rosenblatt's perceptron: weighted inputs, a sum, and a step."""

    with Figure(
        "perceptron", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.root.row("unit", gap="40pt") as unit:
            with unit.column("inputs") as inputs:
                xs = [inputs.circle(f"x{i}", f"$x_{i}$") for i in (1, 2, 3)]
                bias = inputs.circle("one", "$1$")
            total = unit.op("sum", "Σ")
            step = unit.block("step", label="step")
            unit.text("y", "$y$", input=step)
        for i, x in enumerate(xs, start=1):
            figure.connect(x, total, label=f"$w_{i}$")
        figure.connect(bias, total, label="$b$")
        figure.connect(total, step)
    return figure


def central_dogma(theme: str = "paper") -> Figure:
    """The central dogma of molecular biology (Crick 1970)."""

    with Figure("central-dogma", theme=theme) as figure:
        with figure.root.row("flow", gap="36pt") as flow:
            dna = flow.block("dna", label="DNA", tone="dna")
            rna = flow.block("rna", label="RNA", tone="rna")
            protein = flow.block("protein", label="Protein", tone="protein")
        figure.connect(dna, dna, label="replication")
        figure.connect(dna, rna, label="transcription")
        figure.connect(rna, protein, label="translation")
        figure.connect(rna, dna, label="reverse transcription", line="dashed")
    return figure


def pcr(theme: str = "paper") -> Figure:
    """The polymerase chain reaction: one cycle, repeated about thirty times."""

    with Figure("pcr", width="single-column", theme=theme) as figure:
        with figure.root.column("protocol") as protocol:
            template = protocol.text("template", "DNA template")
            with protocol.group("cycle", label="×30", layout="cycle") as cycle:
                denature = cycle.block(
                    "denature", label="Denature\n95 °C", tone="hot", input=template
                )
                anneal = cycle.block("anneal", label="Anneal\n55 °C", tone="cool", input=denature)
                extend = cycle.block("extend", label="Extend\n72 °C", tone="warm", input=anneal)
                cycle.connect(extend, denature)
            protocol.text("copies", "2³⁰ copies", input=extend)
    return figure


def git_branching(theme: str = "paper") -> Figure:
    """A feature branch and its merge, as a commit graph."""

    with Figure("git-branching", theme=theme) as figure:
        with figure.root.grid("history", columns=6) as grid:
            main = [grid.circle(f"m{i}", f"$c_{i}$", at=(0, i)) for i in (0, 1, 2, 5)]
            feature = [
                grid.circle(f"f{i}", f"$f_{i}$", tone="feature", at=(1, i)) for i in (2, 3, 4)
            ]
        for before, after in itertools.pairwise(main):
            figure.connect(before, after)
        figure.connect(main[1], feature[0])
        for before, after in itertools.pairwise(feature):
            figure.connect(before, after)
        figure.connect(feature[-1], main[-1])
    return figure


def graph_attention(theme: str = "paper") -> Figure:
    """A node attending over its neighbours (Velickovic et al. 2018, Figure 1, right)."""

    with Figure(
        "graph-attention", width="single-column", theme=theme, conventions={"lines": "straight"}
    ) as figure:
        with figure.root.grid("graph", columns=3) as grid:
            centre = grid.circle("h1", r"$\vec{h}_1$", tone="focus", at=(1, 1))
            spots = [(0, 0), (0, 2), (1, 0), (2, 0), (2, 2), (1, 2)]
            for k, spot in enumerate(spots, start=2):
                neighbour = grid.circle(f"h{k}", rf"$\vec{{h}}_{k}$", at=spot)
                figure.connect(neighbour, centre, label=rf"$\alpha_{{1{k}}}$")
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
        sprinkler,
        kalman_filter,
        cbow,
        distillation,
        cpu_pipeline,
        model_view_controller,
        load_balancer,
        federated_averaging,
        two_tower,
        network_stack,
        batch_normalization,
        skip_gram,
        extract_transform_load,
        autoencoder,
        message_passing,
        recurrent_network,
        unrolled_recurrent_network,
        markov_chain,
        impala,
        class_hierarchy,
        decision_tree,
        neural_turing_machine,
        react_agent,
        llava,
        code_review,
        dit_block,
        speculative_decoding,
        multi_task_learning,
        citric_acid_cycle,
        alphazero,
        knowledge_graph,
        dqn,
        lda,
        bidirectional_rnn,
        bahdanau_attention,
        cyclegan,
        kubernetes,
        perceptron,
        central_dogma,
        pcr,
        git_branching,
        graph_attention,
    )
}
"""Every figure here, by name."""


SKETCHED = (
    "gpt-block",
    "lstm",
    "unet",
    "lda",
    "bahdanau-attention",
    "perceptron",
    "graph-attention",
    "central-dogma",
    "pcr",
    "code-review",
    "citric-acid-cycle",
    "vision-transformer",
)
"""The figures also built in the ``sketch`` theme, for the gallery."""


def main() -> None:
    for name, make in FIGURES.items():
        themes = ("paper", "tikz", "sketch") if name in SKETCHED else ("paper", "tikz")
        for theme in themes:
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
