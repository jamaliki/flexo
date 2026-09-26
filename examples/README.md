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

Sixty-six figures from papers and textbooks, each a short function. They use
only plain authoring: components, the values that flow between them, and at
most one hint where the paper makes a choice that cannot be inferred. Every
one compiles with no lint diagnostics in every theme it is built in (the test
suite checks this).

| | | |
| --- | --- | --- |
| [![RLHF](build/literature/rlhf.preview.png)](build/literature/rlhf.preview.png) RLHF, three panels | | |
| [![LeNet-5](build/literature/lenet.preview.png)](build/literature/lenet.preview.png) LeNet-5 | [![LeNet-5, tikz](build/literature/lenet-tikz.preview.png)](build/literature/lenet-tikz.preview.png) LeNet-5 in `tikz` | [![Attention panels](build/literature/attention-panels.preview.png)](build/literature/attention-panels.preview.png) Scaled dot-product and multi-head attention |
| [![Inception](build/literature/inception.preview.png)](build/literature/inception.preview.png) Inception module | [![LSTM](build/literature/lstm.preview.png)](build/literature/lstm.preview.png) LSTM cell | [![Mamba](build/literature/mamba.preview.png)](build/literature/mamba.preview.png) Mamba block |
| [![GPT block](build/literature/gpt-block.preview.png)](build/literature/gpt-block.preview.png) Pre-norm Transformer block | [![Vision Transformer](build/literature/vision-transformer.preview.png)](build/literature/vision-transformer.preview.png) Vision Transformer | [![Squeeze-and-excitation](build/literature/squeeze-excitation.preview.png)](build/literature/squeeze-excitation.preview.png) Squeeze-and-excitation |
| [![Agent-environment loop](build/literature/agent-environment.preview.png)](build/literature/agent-environment.preview.png) Agent–environment loop | [![Seq2seq](build/literature/seq2seq.preview.png)](build/literature/seq2seq.preview.png) Encoder–decoder with attention | [![U-Net](build/literature/unet.preview.png)](build/literature/unet.preview.png) U-Net |
| [![MLP](build/literature/multilayer-perceptron.preview.png)](build/literature/multilayer-perceptron.preview.png) Multilayer perceptron | [![HMM](build/literature/hidden-markov-model.preview.png)](build/literature/hidden-markov-model.preview.png) Hidden Markov model | [![VAE](build/literature/variational-autoencoder.preview.png)](build/literature/variational-autoencoder.preview.png) VAE as a graphical model |
| [![CLIP](build/literature/clip.preview.png)](build/literature/clip.preview.png) CLIP | [![GAN](build/literature/gan.preview.png)](build/literature/gan.preview.png) GAN | [![Diffusion](build/literature/diffusion.preview.png)](build/literature/diffusion.preview.png) Diffusion |
| [![Siamese network](build/literature/siamese.preview.png)](build/literature/siamese.preview.png) Siamese network | [![Transformer block, tikz](build/literature/gpt-block-tikz.preview.png)](build/literature/gpt-block-tikz.preview.png) Transformer block in `tikz` | [![LSTM, tikz](build/literature/lstm-tikz.preview.png)](build/literature/lstm-tikz.preview.png) LSTM in `tikz` |
| [![AlphaFold 2](build/literature/alphafold.preview.png)](build/literature/alphafold.preview.png) AlphaFold 2 | [![BERT](build/literature/bert.preview.png)](build/literature/bert.preview.png) BERT | [![SimCLR](build/literature/simclr.preview.png)](build/literature/simclr.preview.png) SimCLR |
| [![Feature pyramid network](build/literature/feature-pyramid.preview.png)](build/literature/feature-pyramid.preview.png) Feature pyramid network | [![CI pipeline](build/literature/ci-pipeline.preview.png)](build/literature/ci-pipeline.preview.png) Continuous-integration flowchart | [![State machine](build/literature/state-machine.preview.png)](build/literature/state-machine.preview.png) State machine |
| [![Bottleneck](build/literature/bottleneck.preview.png)](build/literature/bottleneck.preview.png) Bottleneck block | [![SwiGLU](build/literature/swiglu.preview.png)](build/literature/swiglu.preview.png) SwiGLU | [![Training loop](build/literature/training-loop.preview.png)](build/literature/training-loop.preview.png) Training-loop flowchart |
| [![Feedback control loop](build/literature/feedback-control.preview.png)](build/literature/feedback-control.preview.png) Feedback control loop | [![Mixture of experts](build/literature/mixture-of-experts.preview.png)](build/literature/mixture-of-experts.preview.png) Mixture of experts | [![Faster R-CNN](build/literature/faster-rcnn.preview.png)](build/literature/faster-rcnn.preview.png) Faster R-CNN |
| [![LoRA](build/literature/lora.preview.png)](build/literature/lora.preview.png) LoRA | [![Retrieval-augmented generation](build/literature/retrieval-augmented-generation.preview.png)](build/literature/retrieval-augmented-generation.preview.png) Retrieval-augmented generation | [![Latent diffusion](build/literature/latent-diffusion.preview.png)](build/literature/latent-diffusion.preview.png) Latent diffusion |
| [![Actor–critic](build/literature/actor-critic.preview.png)](build/literature/actor-critic.preview.png) Actor–critic | [![MapReduce](build/literature/mapreduce.preview.png)](build/literature/mapreduce.preview.png) MapReduce | [![LoRA in `tikz`](build/literature/lora-tikz.preview.png)](build/literature/lora-tikz.preview.png) LoRA in `tikz` |
| [![Compiler phases and symbol table](build/literature/compiler.preview.png)](build/literature/compiler.preview.png) Compiler phases and symbol table | [![Pipelined CPU with forwarding](build/literature/cpu-pipeline.preview.png)](build/literature/cpu-pipeline.preview.png) Pipelined CPU with forwarding | [![Kalman filter](build/literature/kalman-filter.preview.png)](build/literature/kalman-filter.preview.png) Kalman filter |
| [![Sprinkler Bayesian network](build/literature/sprinkler.preview.png)](build/literature/sprinkler.preview.png) Sprinkler Bayesian network | [![CBOW](build/literature/cbow.preview.png)](build/literature/cbow.preview.png) CBOW | [![Knowledge distillation](build/literature/distillation.preview.png)](build/literature/distillation.preview.png) Knowledge distillation |
| [![Model–view–controller](build/literature/model-view-controller.preview.png)](build/literature/model-view-controller.preview.png) Model–view–controller | [![Load-balanced service](build/literature/load-balancer.preview.png)](build/literature/load-balancer.preview.png) Load-balanced service | [![Pipelined CPU in `tikz`](build/literature/cpu-pipeline-tikz.preview.png)](build/literature/cpu-pipeline-tikz.preview.png) Pipelined CPU in `tikz` |
| [![Federated averaging](build/literature/federated-averaging.preview.png)](build/literature/federated-averaging.preview.png) Federated averaging | [![Two-tower retrieval](build/literature/two-tower.preview.png)](build/literature/two-tower.preview.png) Two-tower retrieval | [![Network stack between two hosts](build/literature/network-stack.preview.png)](build/literature/network-stack.preview.png) Network stack between two hosts |
| [![Batch normalisation](build/literature/batch-normalization.preview.png)](build/literature/batch-normalization.preview.png) Batch normalisation | [![Skip-gram](build/literature/skip-gram.preview.png)](build/literature/skip-gram.preview.png) Skip-gram | [![Extract, transform, load](build/literature/extract-transform-load.preview.png)](build/literature/extract-transform-load.preview.png) Extract, transform, load |
| [![Autoencoder](build/literature/autoencoder.preview.png)](build/literature/autoencoder.preview.png) Autoencoder | [![Message passing](build/literature/message-passing.preview.png)](build/literature/message-passing.preview.png) Message passing | [![Network stack in `tikz`](build/literature/network-stack-tikz.preview.png)](build/literature/network-stack-tikz.preview.png) Network stack in `tikz` |
| [![Recurrent network with its loop](build/literature/recurrent-network.preview.png)](build/literature/recurrent-network.preview.png) Recurrent network with its loop | [![Recurrent network, unrolled](build/literature/unrolled-recurrent-network.preview.png)](build/literature/unrolled-recurrent-network.preview.png) Recurrent network, unrolled | [![Markov chain](build/literature/markov-chain.preview.png)](build/literature/markov-chain.preview.png) Markov chain |
| [![IMPALA](build/literature/impala.preview.png)](build/literature/impala.preview.png) IMPALA | [![Class hierarchy](build/literature/class-hierarchy.preview.png)](build/literature/class-hierarchy.preview.png) Class hierarchy | [![Decision tree](build/literature/decision-tree.preview.png)](build/literature/decision-tree.preview.png) Decision tree |
| [![Neural Turing Machine](build/literature/neural-turing-machine.preview.png)](build/literature/neural-turing-machine.preview.png) Neural Turing Machine | [![Markov chain in `tikz`](build/literature/markov-chain-tikz.preview.png)](build/literature/markov-chain-tikz.preview.png) Markov chain in `tikz` | [![IMPALA in `tikz`](build/literature/impala-tikz.preview.png)](build/literature/impala-tikz.preview.png) IMPALA in `tikz` |
| [![ReAct agent loop](build/literature/react-agent.preview.png)](build/literature/react-agent.preview.png) ReAct agent loop | [![LLaVA](build/literature/llava.preview.png)](build/literature/llava.preview.png) LLaVA | [![Code-review flowchart](build/literature/code-review.preview.png)](build/literature/code-review.preview.png) Code-review flowchart |
| [![DiT block](build/literature/dit-block.preview.png)](build/literature/dit-block.preview.png) DiT block | [![Speculative decoding](build/literature/speculative-decoding.preview.png)](build/literature/speculative-decoding.preview.png) Speculative decoding | [![DiT block in `tikz`](build/literature/dit-block-tikz.preview.png)](build/literature/dit-block-tikz.preview.png) DiT block in `tikz` |
| [![Multi-task learning, written flat](build/literature/multi-task-learning.preview.png)](build/literature/multi-task-learning.preview.png) Multi-task learning, written flat | [![Multi-task learning in `tikz`](build/literature/multi-task-learning-tikz.preview.png)](build/literature/multi-task-learning-tikz.preview.png) Multi-task learning in `tikz` |  |
| [![Citric acid cycle](build/literature/citric-acid-cycle.preview.png)](build/literature/citric-acid-cycle.preview.png) Citric acid cycle | [![Citric acid cycle in `tikz`](build/literature/citric-acid-cycle-tikz.preview.png)](build/literature/citric-acid-cycle-tikz.preview.png) Citric acid cycle in `tikz` |  |
