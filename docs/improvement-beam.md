# Improvement Beam

## Promoted Baseline

- Candidate: coordinate-free `vertical-slice` gallery figure.
- Commit/config: compiler defaults plus semantic source residual port.
- Primary metric: zero validation errors plus editorial clarity at 180 mm.
- Guardrails: deterministic, editable, physical-size-correct output.
- Reproduction command: `uv run flexo gallery --output examples/build`.
- Last promotion: first rendered baseline, checkpoint 1.

## Current Ranking

| Rank | Beam | Type | Status | Parent | Current best / log | Next decision | Owner |
|---:|---|---|---|---|---|---|---|
| 1 | B1 | exploit | active | vertical slice | first render | singleton | primary agent |
| 2 | B2 | near-miss | active | vertical slice | native motifs | stress test | primary agent |
| 3 | B3 | structural/high-risk | promoted | vertical slice | semantic residual port | combination | primary agent |

## Active Beam Entries

### B1: Editorial spacing and hierarchy

- Type: exploit
- Status: active
- Rank: 1
- Owner: primary agent
- Parent candidate or beam: first functional baseline
- Hypothesis: a restrained spacing scale and clear container hierarchy will
  improve scan order without requiring per-figure coordinates.
- Mechanism: geometry tokens, alignment, and whitespace encode grouping.
- Exact code paths: `style.py`, `layout/lanes.py`, gallery specification.
- Current best candidate: paper spacing tokens in the vertical slice.
- Evidence for: clear hierarchy and no overflow at 180 x 47.2 mm.
- Evidence against: none.
- Next decision: singleton.
- Next exact experiment: compare compact and editorial spacing tokens on the
  same gallery geometry.
- Kill or park condition: no legibility improvement at equal overflow count.

### B2: Component visual grammar

- Type: near-miss
- Status: active
- Rank: 2
- Owner: primary agent
- Parent candidate or beam: first functional baseline
- Hypothesis: kind-specific internal primitives can improve semantic recognition
  while retaining a coherent visual language.
- Mechanism: small repeated motifs distinguish matrices, sequences, MLPs, and
  feature strips without extra labels.
- Exact code paths: `emit.py`, component registry.
- Current best candidate: restrained feature-strip, MLP, CNN, attention, and
  scientific-inset motifs.
- Evidence for: motifs distinguish operations without extra legend text.
- Evidence against: Q/K/V joins are locally dense around attention.
- Next decision: stress test.
- Next exact experiment: apply the grammar to transformer and U-Net fixtures.
- Kill or park condition: motifs harm text fit or add ambiguous detail.

### B3: Connector lane composition

- Type: structural/high-risk
- Status: promoted
- Rank: 3
- Owner: primary agent
- Parent candidate or beam: first functional baseline
- Hypothesis: semantic lanes and parallel-path nudging can produce editorial
  residual rails more reliably than shortest paths alone.
- Mechanism: protected corridors preserve long-range visual continuity.
- Exact code paths: `routing/solve.py`, `routing/nudge.py`, edge hints.
- Current best candidate: source-specific residual port plus `cryo-bottom` lane.
- Evidence for: five-vertex obstacle-free rail with deliberate departure.
- Evidence against: corridor constraints may complicate simple routes.
- Next decision: combination.
- Next exact experiment: combine semantic lanes with multi-module spacing and
  parallel residuals.
- Kill or park condition: lane hints are not deterministic or cause collisions.

## Combination Queue

| Candidate beams | Expected interaction | Why singleton evidence is sufficient | Correctness risk | Exact next test |
|---|---|---|---|---|
| B1 + B3 | spacing should create clean route corridors | pending | low | merged gallery render |
| B1 + B2 | hierarchy should prevent motifs becoming noisy | pending | low | 2x raster comparison |

## Parked And Killed Beams

None.

## Beam Checkpoints

### Checkpoint 0: repository initialization

- Promoted baseline: none.
- Ranking changes: initial three families seeded.
- Experiments since last checkpoint: none.
- Capacity added or removed: three visual-quality beams created.
- Near-misses preserved: none.
- Beams killed or parked and why: none.
- Next singleton candidates: first complete gallery baseline.
- Next combination candidates: none before singleton evidence.

### Checkpoint 1: first rendered baseline

- Promoted baseline: coordinate-free vertical slice.
- Ranking changes: B3 promoted; B1 remains the next exploit; B2 retained as a
  supported motif family requiring broader stress tests.
- Experiments since last checkpoint: integrated render and semantic residual
  port comparison.
- Capacity added or removed: none.
- Near-misses preserved: variable-font embedding works but warns in Inkscape.
- Beams killed or parked and why: none.
- Next singleton candidates: static font instances; imported inset.
- Next combination candidates: B1 spacing plus B3 lanes on multi-module figure.
