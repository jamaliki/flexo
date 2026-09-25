# Examples

Each script runs from the repository root and writes an editable SVG and a
preview PNG into `build/`:

```bash
uv run python examples/literature.py
uv run python examples/transformer.py
uv run python examples/vertical_slice.py
uv run python examples/attention_module.py
uv run python examples/modelangelo_gnn.py
```

## [`vertical_slice.py`](vertical_slice.py)

The acceptance figure, plus [`vertical_slice.yaml`](vertical_slice.yaml) — the
same figure as interchange, to show that the Python builder and the YAML schema
are one thing.

[![vertical slice](build/vertical-slice.preview.png)](build/vertical-slice.preview.png)

## [`attention_module.py`](attention_module.py)

A dark attention panel from palette overrides alone: `VectorPreset` glyphs, a
reserved grid lane holding the attention corridor open, and `rail_at`/`joint`
placing the merge. Its presets name no `order`, so every glyph takes the
default — shades permuted per column, reading as a feature vector.

[![attention module](build/attention-module.preview.png)](build/attention-module.preview.png)

The same panel with `order="ramp"` — every colour kept, run light-to-dark
instead, so each glyph reads as a gradient. A ramp claims the cells are
*ordered*, which is why it is asked for by name rather than defaulted to.

[![attention module, ramped](build/attention-module-ramp.preview.png)](build/attention-module-ramp.preview.png)

## [`modelangelo_gnn.py`](modelangelo_gnn.py)

The ModelAngelo GNN panel: band rows on a shared spine, three port-aligned module
grids, and a five-head readout that recycles into the top. Authored in
[`flexo/gallery.py`](../src/flexo/gallery.py).

[![ModelAngelo GNN](build/modelangelo-gnn.preview.png)](build/modelangelo-gnn.preview.png)

## [`transformer.py`](transformer.py)

The Transformer from "Attention Is All You Need" (Vaswani et al. 2017): two
towers written bottom-up, each residual named where it joins (`skip=`), the
Q/K/V glyphs grown by `attention(vectors=...)`, and the positional encoding as
the addition it is (`op("~")` into `add`). Built in the `paper` and `tikz`
themes.

![transformer](build/transformer.preview.png)

## [`literature.py`](literature.py)

Twenty-three figures from papers and textbooks, each a short function. They use
only plain authoring: components, the values that flow between them, and at
most one hint where the paper makes a choice that cannot be inferred. Every
one compiles with no lint diagnostics in every theme it is built in (the test
suite checks this).

| | | |
| --- | --- | --- |
| [![LeNet-5](build/literature/lenet.preview.png)](build/literature/lenet.preview.png) LeNet-5 | [![LeNet-5, tikz](build/literature/lenet-tikz.preview.png)](build/literature/lenet-tikz.preview.png) LeNet-5 in `tikz` | [![Attention panels](build/literature/attention-panels.preview.png)](build/literature/attention-panels.preview.png) Scaled dot-product and multi-head attention |
| [![Inception](build/literature/inception.preview.png)](build/literature/inception.preview.png) Inception module | [![LSTM](build/literature/lstm.preview.png)](build/literature/lstm.preview.png) LSTM cell | [![Mamba](build/literature/mamba.preview.png)](build/literature/mamba.preview.png) Mamba block |
| [![GPT block](build/literature/gpt-block.preview.png)](build/literature/gpt-block.preview.png) Pre-norm Transformer block | [![Vision Transformer](build/literature/vision-transformer.preview.png)](build/literature/vision-transformer.preview.png) Vision Transformer | [![Squeeze-and-excitation](build/literature/squeeze-excitation.preview.png)](build/literature/squeeze-excitation.preview.png) Squeeze-and-excitation |
| [![Agent-environment loop](build/literature/agent-environment.preview.png)](build/literature/agent-environment.preview.png) Agent–environment loop | [![Seq2seq](build/literature/seq2seq.preview.png)](build/literature/seq2seq.preview.png) Encoder–decoder with attention | [![U-Net](build/literature/unet.preview.png)](build/literature/unet.preview.png) U-Net |
| [![MLP](build/literature/multilayer-perceptron.preview.png)](build/literature/multilayer-perceptron.preview.png) Multilayer perceptron | [![HMM](build/literature/hidden-markov-model.preview.png)](build/literature/hidden-markov-model.preview.png) Hidden Markov model | [![VAE](build/literature/variational-autoencoder.preview.png)](build/literature/variational-autoencoder.preview.png) VAE as a graphical model |
| [![CLIP](build/literature/clip.preview.png)](build/literature/clip.preview.png) CLIP | [![GAN](build/literature/gan.preview.png)](build/literature/gan.preview.png) GAN | [![Diffusion](build/literature/diffusion.preview.png)](build/literature/diffusion.preview.png) Diffusion |
| [![Siamese network](build/literature/siamese.preview.png)](build/literature/siamese.preview.png) Siamese network | [![Transformer block, tikz](build/literature/gpt-block-tikz.preview.png)](build/literature/gpt-block-tikz.preview.png) Transformer block in `tikz` | [![LSTM, tikz](build/literature/lstm-tikz.preview.png)](build/literature/lstm-tikz.preview.png) LSTM in `tikz` |
| [![AlphaFold 2](build/literature/alphafold.preview.png)](build/literature/alphafold.preview.png) AlphaFold 2 | [![BERT](build/literature/bert.preview.png)](build/literature/bert.preview.png) BERT | |
| [![Bottleneck](build/literature/bottleneck.preview.png)](build/literature/bottleneck.preview.png) Bottleneck block | [![SwiGLU](build/literature/swiglu.preview.png)](build/literature/swiglu.preview.png) SwiGLU | [![Training loop](build/literature/training-loop.preview.png)](build/literature/training-loop.preview.png) Training-loop flowchart |
