# Improvement Beam

## Promoted Baseline

- Candidate: repository initialization; no rendered baseline.
- Commit/config: pending first checkpoint.
- Primary metric: zero validation errors plus visual editorial quality.
- Guardrails: deterministic, editable, physical-size-correct output.
- Reproduction command: `uv run flexo gallery --output examples/build`.
- Last promotion: none.

## Current Ranking

| Rank | Beam | Type | Status | Parent | Current best / log | Next decision | Owner |
|---:|---|---|---|---|---|---|---|
| 1 | B1 | exploit | active | baseline | none | singleton | primary agent |
| 2 | B2 | near-miss | active | baseline | none | singleton | primary agent |
| 3 | B3 | structural/high-risk | active | baseline | none | singleton | primary agent |

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
- Current best candidate: none.
- Evidence for: pending baseline render.
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
- Current best candidate: none.
- Evidence for: pending baseline render.
- Evidence against: visual clutter is the primary risk.
- Next decision: singleton.
- Next exact experiment: render generic blocks versus restrained kind motifs.
- Kill or park condition: motifs harm text fit or add ambiguous detail.

### B3: Connector lane composition

- Type: structural/high-risk
- Status: active
- Rank: 3
- Owner: primary agent
- Parent candidate or beam: first functional baseline
- Hypothesis: semantic lanes and parallel-path nudging can produce editorial
  residual rails more reliably than shortest paths alone.
- Mechanism: protected corridors preserve long-range visual continuity.
- Exact code paths: `routing/solve.py`, `routing/nudge.py`, edge hints.
- Current best candidate: none.
- Evidence for: pending baseline route fixture.
- Evidence against: corridor constraints may complicate simple routes.
- Next decision: singleton.
- Next exact experiment: compare automatic residual routing with a named
  bottom-lane hint on the acceptance figure.
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
