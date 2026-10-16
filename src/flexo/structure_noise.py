"""A structure as a diffusion model draws it on its way: ``noise`` from 0 (the file) to 1.

Five copies of one structure at ``noise`` 1, 0.3, 0.16, 0.06 and 0 are a diffusion
model's frames at t = 100, 30, 20, 10 and 0 -- ``noise`` is t over the run's steps, so
``noise: 0.3`` is t = 30 of a hundred (or t = 15 of fifty). Each copy is one moment of
one trajectory, from a random coil to the structure in the file:

- **the prior** (noise 1): each chain a random coil with a protein's own local geometry
  -- its C-alphas the file's distance apart (3.8 Å), each turn between 85° and 135° (a
  protein's range; never straight), any dihedral -- wandering in a ball about the size of
  the chain folded, round where it ends up;
- **the folding**: windows of the chain -- 4 residues, 6, 10 ... the whole chain -- are
  each pulled to the file's shape for the same residues, laid over them (turned, never
  mirrored: a helix comes out right-handed), the short ones first, so turns and helices
  form first, a stretch of the chain at a time, then their packing. The bonds keep the
  file's lengths throughout, nothing comes closer than 3.6 Å to what it is not bonded to,
  and a helix is never squashed into a rod;
- **the pace**: each residue is brought only so near the file as ``PACE`` has it -- at
  noise 0.3 the chain is 70% as far from the file (RMS) as its prior, helices forming and
  the chain drawing in; at 0.16 a quarter, its shape there; at 0.06 a twelfth, nearly the
  file; at 0, the file itself, exactly. No residue is left behind to be hauled in at the
  end.

``fixed`` is a mol-sketch selection held exactly where the file has it -- the motif of
a motif-scaffolding run, a ligand, a target a binder is made for -- a residue whole
when any of its atoms is selected. The prior passes through the motif's C-alphas, the
rest keeps off what is held, and folds round it into place (not turned to fit: where
the file has it). Every residue moves rigidly with its C-alpha, turned as the chain is
turned there, so a side chain stays a side chain and its sticks chemically sane. A
ligand, an ion or a water not held moves rigidly with the residue nearest it: it stays
by that residue, and is where the file has it at noise 0. Each chain folds on its own,
round where it ends up: a complex is its chains' coils at noise 1, each folding into
its place.

``seed`` picks the run: every copy of a structure with the same file, ``fixed`` and
``seed`` is a moment of one trajectory. A trajectory is worked out once -- in about
half a second for 300 residues -- and kept, in memory and on disk with flexo's other
caches; a noise level then blends the snapshots either side of it.

The file's helices and strands are drawn where they have formed (where the chain's own
five residues there lie within 0.35 Å of the file's), and the rest as loops: a noised
frame never draws a helix on a coil, and at noise 0 draws what the file does.

numpy only (it comes with mol-sketch).
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import os
import re
import sys
import threading
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

VERSION = 1
"""Changed whenever trajectories are worked out differently, so those kept are worked out again."""

LEVELS = 100
"""Snapshots kept of each trajectory, evenly in noise from 1 to 0 (one each 0.01)."""

STEPS = 3
"""Steps of the folding between one kept snapshot and the next."""

BOND = 3.8
"""A protein's C-alpha-C-alpha distance, Å."""

TURN = (85.0, 135.0)
"""The prior's angle at each C-alpha, degrees: a protein's range (its median is about 95°)."""

BALL = 1.4
"""The prior's ball, in radii of gyration of the chain folded."""

CLASH = 3.6
"""How close, Å, two C-alphas not bonded may come."""

_LIMIT = {False: 4.6, True: 9.5}
"""How far apart, Å, mol-sketch draws a protein's (a nucleic acid's) trace unbroken."""

KEPT = 48
"""Trajectories kept on disk; the least recently used go first."""


def _numpy():
    import numpy as np

    return np


# -- the trajectory ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Chain:
    """One chain's trace, as it is folded: its trace atoms' positions in the file
    (``trace``, n by 3), their residue numbers, which follow on from the one before
    (``bonded``, n - 1), which are held where they are (``fixed``), whether it is a
    nucleic acid, and the points nothing of it may pass through (``around``: what is
    held of other chains, and held ligands)."""

    trace: object
    resi: object
    bonded: object
    fixed: object
    nucleic: bool = False
    around: object = None


def noise_levels():
    """The noise of each kept snapshot: 1 (the prior) to 0 (the file)."""

    return _numpy().linspace(1.0, 0.0, LEVELS + 1)


def fold(chain: Chain, seed: int, name: str = "") -> object:
    """``chain``'s trajectory: its trace at each of ``noise_levels`` (LEVELS + 1 by n by 3,
    in single precision), from the prior to the file. The same chain, seed and name (its
    chain's) give the same trajectory, bit for bit."""

    np = _numpy()
    x0 = np.asarray(chain.trace, dtype=np.float64)
    n = len(x0)
    out = np.empty((LEVELS + 1, n, 3), dtype=np.float32)
    if n < SHORTEST:
        out[:] = x0
        return out
    rng = np.random.default_rng([int(seed) & 0xFFFFFFFF, zlib.crc32(name.encode())])
    run = _Run(chain, rng)
    out[0] = run.settled(run.x)
    levels = noise_levels()
    for level in range(1, LEVELS):
        for step in range(STEPS):
            sigma = levels[level - 1] + (levels[level] - levels[level - 1]) * (step + 1) / STEPS
            run.step(float(sigma))
        out[level] = run.settled(run.x)
    out[LEVELS] = x0
    return out


def at_noise(trajectory, noise: float, shape: _Shape | None = None):
    """A trajectory's trace at ``noise``: the snapshots either side of it blended -- and,
    given the chain's ``shape``, put back in it (a blend's bonds are never longer than its
    snapshots', but may be shorter); or, where a residue swings round between the two so
    far that the blend can't be (it would pass through a straight angle), the nearer
    snapshot. Noise in hundredths is a snapshot."""

    np = _numpy()
    place = (1.0 - min(max(float(noise), 0.0), 1.0)) * LEVELS
    low = min(math.floor(place), LEVELS - 1)
    share = place - low
    a = trajectory[low].astype(np.float64)
    b = trajectory[low + 1].astype(np.float64)
    out = a + (b - a) * share
    if shape is not None and 1e-9 < share < 1 - 1e-9:
        shape.hold(out, 12)
        if not shape.holds(out):
            return (a if share < 0.5 else b).copy()
    return out


class _Run:
    """The folding of one chain, a step at a time from noise 1: windows of it -- runs of 4
    residues, of 6, of 10 ... of the whole chain -- each matched to the same residues in
    the file, turned and moved to lie best over them (so a helix comes out right-handed:
    a turn is never a mirror's). A window switches on as the noise falls to its own level
    -- the shorter, the sooner, each a little sooner or later than others its size (so
    helices form one by one, in an order the seed picks) -- and then pulls its residues to
    the file's shape, the long ones more and more gently, and no faster than ``PACE``; the
    short ones are the chain's local shape, put back after every step. Nothing comes closer
    than CLASH to what it is not bonded to (``_keep_apart``), and each bond keeps its length
    and each angle a protein's (``_Shape``)."""

    def __init__(self, chain: Chain, rng) -> None:
        np = _numpy()
        self.x0 = x0 = np.asarray(chain.trace, dtype=np.float64)
        self.n = n = len(x0)
        self.resi = resi = np.asarray(chain.resi, dtype=np.int64)
        self.bonded = bonded = np.asarray(chain.bonded, dtype=bool)
        self.fixed = fixed = np.asarray(chain.fixed, dtype=bool)
        self.free = ~fixed
        around = chain.around
        self.around = (
            np.zeros((0, 3)) if around is None else np.asarray(around, dtype=np.float64)
        ).reshape(-1, 3)
        # Held where the file has it (part of it, or what is round it), the chain arrives
        # where the file has it; held nowhere, it may arrive turned any way, and is laid
        # over the file's after.
        self.pinned = bool(fixed.any()) or len(self.around) > 0
        self.shape = _Shape(chain)
        lengths = self.shape.length
        step = float(np.median(lengths)) if len(lengths) else BOND
        self.x = _coil(rng, x0, resi, bonded, fixed, self.around, step, chain.nucleic)
        self.x[fixed] = x0[fixed]
        sizes, w = [], float(SHORTEST)
        while w < n:
            sizes.append(round(w))
            w *= WIDER
        sizes = sorted(set(sizes) | {n})
        near = [size for size in sizes if size <= LOCAL and size < n]
        far = [size for size in sizes if size not in near]
        self.near = _Windows(x0, near) if near else None
        self.far = _Windows(x0, far, absolute=n if self.pinned else None) if far else None
        span = math.log(max(n, SHORTEST + 1) / SHORTEST)
        reach = math.log(max(n / LOCAL, 1.0 + 1e-9))
        # Which stretches of the chain fold sooner, and which later: a smooth random rise and
        # fall along it, so a helix forms whole, and the helices one after another.
        knots = np.arange(0, n + KNOTS, KNOTS)
        early = np.interp(np.arange(n), knots, rng.random(len(knots)) - 0.5)
        for windows in (self.near, self.far):
            if windows is None:
                continue
            length = windows.length.astype(np.float64)
            share = np.clip(np.log(length / SHORTEST) / span, 0.0, 1.0)
            middle = (windows.start + windows.length // 2).clip(0, n - 1)
            windows.onset = ON[0] + (ON[1] - ON[0]) * share + JITTER * (1.0 - share) * early[middle]
            # The longer the window, the more gently it pulls: the chain's shape comes
            # in over the last of the way, not at once.
            further = np.clip(np.log(np.maximum(length / LOCAL, 1.0)) / reach, 0.0, 1.0)
            windows.rate = np.exp((1 - further) * math.log(PULL[0]) + further * math.log(PULL[1]))
        if self.pinned and self.far is not None:
            # Held, the chain is brought to where the file has it -- not only to its shape --
            # by its whole window alone: that comes on sooner, and pulls harder.
            whole = ~self.far.fit[self.far.kind]
            self.far.onset[whole] -= HELD[0]
            self.far.rate[whole] *= HELD[1]
        self.t = 0
        self._apart = None
        self.start = float(np.sqrt((self._off(self.x) ** 2).mean())) or 1.0

    def _off(self, x):
        """How far (Å) each residue of ``x`` is from where the file has it: laid over the
        file, or -- held somewhere -- as it is."""

        np = _numpy()
        y = x if self.pinned else _laid_over(x, self.x0)
        return np.sqrt(((y - self.x0) ** 2).sum(1))

    def step(self, sigma: float) -> None:
        np = _numpy()
        x = self.x
        u = 1.0 - sigma
        if self.far is not None:
            on = _smooth((u - self.far.onset) / RAMP)
            # The chain's shape comes in at the pace PACE sets, however fast the windows
            # would bring it: each residue they bring only so near the file as the pace has
            # it -- none left behind, to be hauled in at the end.
            ahead = self._off(x) - self.start * float(np.interp(sigma, *PACE))
            if on.any() and ahead.max() > 0:
                move = self.far.moves(x, on * self.far.rate)
                move *= np.clip(ahead / 0.5, 0.0, 1.0)[:, None]
                speed = np.sqrt((move * move).sum(1))
                move *= np.minimum(1.0, RATE / (speed + 1e-12))[:, None]
                x += move
                x[self.fixed] = self.x0[self.fixed]
        if self.near is not None:
            on = _smooth((u - self.near.onset) / RAMP)
            if on.any():
                for _ in range(PASSES):
                    move = self.near.moves(x, on, pooled=True)
                    speed = np.sqrt((move * move).sum(1))
                    x += move * np.minimum(1.0, RATE / (speed + 1e-12))[:, None]
                    x[self.fixed] = self.x0[self.fixed]
        self._keep_apart(x, sigma)
        self.shape.hold(x, HOLD)
        x[self.fixed] = self.x0[self.fixed]
        self.t += 1

    def _keep_apart(self, x, sigma: float = 1.0) -> None:
        """Every two C-alphas not bonded (nor neighbours but one) put CLASH apart -- or as far
        as the file has them, if nearer -- and each kept CLASH from what is held round it.

        Parts of the chain far apart along it may pass through each other as its shape
        comes together (``PASS``), as a diffusion model's frames do: a domain formed on the
        wrong side of another is not kept there."""

        np = _numpy()
        if self._apart is None or self.t % 5 == 0:
            i, j = _within(x, x, 8.0)
            keep = j >= i + 2
            i, j = i[keep], j[keep]
            lim = np.minimum(CLASH, np.linalg.norm(self.x0[i] - self.x0[j], axis=1) - 0.05)
            apart = np.abs(self.resi[j] - self.resi[i]) > PASS[0]
            held = (np.zeros(0, int), np.zeros(0, int), np.zeros(0))
            if len(self.around):
                k, o = _within(x, self.around, 8.0)
                keep = self.free[k]
                k, o = k[keep], o[keep]
                far = np.linalg.norm(self.x0[k] - self.around[o], axis=1) - 0.05
                held = (k, o, np.minimum(CLASH, far))
            self._apart = (i, j, lim, apart, held)
        i, j, lim, apart, (k, o, held_lim) = self._apart
        # At the very end, a loop threaded the wrong way through the chain may pass through
        # to its place, too -- so near the file by then that it is not seen to.
        near = float(np.clip(sigma / LOOSE, PASSING, 1.0))
        far = float(np.clip((sigma - PASS[2]) / (PASS[1] - PASS[2]), PASSING, 1.0))
        lim = lim * np.where(apart, min(near, far), near)
        if len(i):
            diff = x[i] - x[j]
            d = np.sqrt((diff * diff).sum(1)) + 1e-12
            over = d < lim
            if over.any():
                i, j, d, diff, lim = i[over], j[over], d[over], diff[over], lim[over]
                fix = (0.5 * (lim - d) / d)[:, None] * diff
                # (Each end half the way, or the whole way where the other is held.)
                wi = np.where(self.fixed[i], 0.0, np.where(self.fixed[j], 2.0, 1.0))[:, None]
                wj = np.where(self.fixed[j], 0.0, np.where(self.fixed[i], 2.0, 1.0))[:, None]
                _add(x, i, wi * fix)
                _add(x, j, -wj * fix)
        if len(k):
            diff = x[k] - self.around[o]
            d = np.sqrt((diff * diff).sum(1)) + 1e-12
            over = d < held_lim
            if over.any():
                _add(x, k[over], ((held_lim[over] - d[over]) / d[over])[:, None] * diff[over])

    def settled(self, x):
        """``x`` as it is kept: its bonds put back to their lengths, and -- held nowhere --
        laid over the file's trace, so it is seen from where the file is."""

        y = x.copy()
        self.shape.hold(y, 20)
        y[self.fixed] = self.x0[self.fixed]
        return y if self.pinned else _laid_over(y, self.x0)


class _Shape:
    """What of a chain's shape is kept whatever is done to it: each bond at the file's
    length, each angle within a protein's (``ANGLES``, or the file's own beyond them) --
    the distance across it, from one bonded neighbour to the other, kept within bounds --
    and what is held where it is."""

    def __init__(self, chain: Chain) -> None:
        np = _numpy()
        x0 = np.asarray(chain.trace, dtype=np.float64)
        bonded = np.asarray(chain.bonded, dtype=bool)
        self.x0 = x0
        self.fixed = fixed = np.asarray(chain.fixed, dtype=bool)
        self.bond = b = np.flatnonzero(bonded)
        self.length = np.linalg.norm(x0[b + 1] - x0[b], axis=1)
        self.angle = a = (
            np.flatnonzero(bonded[:-1] & bonded[1:]) if len(x0) >= 3 else np.zeros(0, int)
        )
        span = np.linalg.norm(x0[a + 2] - x0[a], axis=1)
        one = np.linalg.norm(x0[a + 1] - x0[a], axis=1)
        other = np.linalg.norm(x0[a + 2] - x0[a + 1], axis=1)

        def across(degrees):
            return np.sqrt(
                one * one + other * other - 2 * one * other * math.cos(math.radians(degrees))
            )

        self.low = np.minimum(across(ANGLES[0]), span)
        self.high = np.maximum(across(ANGLES[1]), span)
        self.side, self.other = one, other
        # (The widest each angle may open: a protein's, or the file's own, if wider.)
        self.widest = np.maximum(
            math.cos(math.radians(ANGLES[1])),
            -np.clip((span**2 - one**2 - other**2) / (2 * one * other + 1e-12), -1.0, 1.0),
        )

        # Each kept as a pair of points a set distance apart (or within bounds), in four
        # sets none of whose pairs share a point -- the bonds from even residues, from odd
        # ones, and the angles in two -- each set put right in turn, from where the last left
        # them: each end moved half the way, or the whole way where the other is held.
        pairs = [
            (b[b % 2 == 0], 1, self.length[b % 2 == 0], self.length[b % 2 == 0]),
            (b[b % 2 == 1], 1, self.length[b % 2 == 1], self.length[b % 2 == 1]),
            (a[a % 4 < 2], 2, self.low[a % 4 < 2], self.high[a % 4 < 2]),
            (a[a % 4 >= 2], 2, self.low[a % 4 >= 2], self.high[a % 4 >= 2]),
        ]
        self.sets = []
        for first, apart, low, high in pairs:
            second = first + apart
            mine = np.where(fixed[first], 0.0, np.where(fixed[second], 1.0, 0.5))[:, None]
            theirs = np.where(fixed[second], 0.0, np.where(fixed[first], 1.0, 0.5))[:, None]
            self.sets.append((first, second, low, high, mine, theirs))

    def holds(self, y, slack: float = 0.03) -> bool:
        """Whether ``y`` is in shape: its bonds and angles within ``slack`` Å of their
        bounds."""

        np = _numpy()
        for first, second, low, high, _, _ in self.sets:
            gap = y[second] - y[first]
            d = np.sqrt((gap * gap).sum(1))
            if len(d) and (np.any(d < low - slack) or np.any(d > high + slack)):
                return False
        return True

    def hold(self, y, sweeps: int) -> None:
        """``y`` put back in shape, in place: up to ``sweeps`` sweeps over its bonds and
        angles, until each is within a hundredth of an ångström."""

        np = _numpy()
        if not len(self.bond):
            return
        a = self.angle
        for _ in range(sweeps):
            worst = 0.0
            for first, second, low, high, mine, theirs in self.sets:
                if not len(first):
                    continue
                gap = y[second] - y[first]
                d = np.sqrt(np.einsum("ij,ij->i", gap, gap)) + 1e-12
                off = d - np.clip(d, low, high)
                worst = max(worst, float(np.abs(off).max()))
                # (No two pairs of a set share a point: each is moved on its own.)
                fix = (off / d)[:, None] * gap
                y[first] += mine * fix
                y[second] -= theirs * fix
            # An angle near straight is bent by moving its middle off the line between its
            # ends (moving the ends apart or together hardly bends it).
            if len(a):
                step = np.diff(y, axis=0)
                bond = np.sqrt(np.einsum("ij,ij->i", step, step))
                ends = step[a] + step[a + 1]
                c = np.sqrt(np.einsum("ij,ij->i", ends, ends)) + 1e-12
                one, other = bond[a], bond[a + 1]
                # (How far apart the ends may be with the bonds as they are now.)
                widest = np.sqrt(one * one + other * other + 2 * one * other * self.widest)
                straight = (c > widest + 0.01) & ~self.fixed[a + 1]
                if straight.any():
                    worst = max(worst, float((c[straight] - widest[straight]).max()))
                    self._bend(y, a[straight], ends[straight] / c[straight][:, None], straight)
            if worst < 0.01:
                break
        y[self.fixed] = self.x0[self.fixed]

    def _bend(self, y, k, along, which) -> None:
        """The middles of the angles from ``k`` moved off the lines between their ends
        (``along``), as far as the file's bonds and the widest angle set them."""

        np = _numpy()
        out = y[k + 1] - 0.5 * (y[k] + y[k + 2])
        out -= np.einsum("ij,ij->i", out, along)[:, None] * along
        size = np.sqrt(np.einsum("ij,ij->i", out, out))
        flat = size <= 1e-6
        if flat.any():
            # (On the line itself, off it to one side: any is as good.)
            axis = np.where(np.abs(along[flat, :1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]])
            out[flat] = np.cross(along[flat], axis)
            size[flat] = 0.0
        out /= np.sqrt(np.einsum("ij,ij->i", out, out))[:, None]
        reach = 0.5 * (self.side[which] + self.other[which])
        height = np.sqrt(np.maximum(reach**2 - (0.5 * self.high[which]) ** 2, 0.0))
        y[k + 1] += out * np.maximum(height - size, 0.0)[:, None]


class _Windows:
    """Runs of a chain's residues, of the sizes given (each size's runs starting every
    quarter of its length, the last at the chain's end), matched to the file's at once:
    each window's sums come from sums along the chain, and its turn from one batch of
    4 by 4 eigenvectors for the lot (``_turns``), so a pass costs as much as the chain
    is long, however many windows it has. ``absolute``: the window of that size is
    matched where the file has it, not turned to fit (a chain held somewhere arrives
    there)."""

    def __init__(self, x0, sizes, absolute: int | None = None) -> None:
        np = _numpy()
        n = len(x0)
        self.x0 = x0
        self.sizes = list(sizes)
        starts, lengths, kinds = [], [], []
        first_window = []
        for size_index, size in enumerate(self.sizes):
            stride = max(1, size // 4)
            begin = list(range(0, n - size + 1, stride))
            if begin[-1] != n - size:
                begin.append(n - size)
            first_window.append(len(starts))
            starts += begin
            lengths += [size] * len(begin)
            kinds += [size_index] * len(begin)
        self.start = np.array(starts, dtype=np.int64)
        self.kind = np.array(kinds, dtype=np.int64)
        """Which of ``sizes`` each window is."""
        self.length = np.array(lengths, dtype=np.int64)
        self.end = self.start + self.length
        # The file's sums along the chain, and each window's middle in the file.
        s0 = np.concatenate([np.zeros((1, 3)), np.cumsum(x0, axis=0)])
        self.mid0 = (s0[self.end] - s0[self.start]) / self.length[:, None]
        # For each size and residue, the first and last of that size's windows holding it.
        k = len(self.sizes)
        self.low = np.zeros((k, n), dtype=np.int64)
        self.high = np.zeros((k, n), dtype=np.int64)
        residues = np.arange(n)
        for size_index, size in enumerate(self.sizes):
            first = first_window[size_index]
            last = first_window[size_index + 1] if size_index + 1 < k else len(starts)
            begin = self.start[first:last]
            # (Windows of a size are in order of their start: those holding r start in
            # [r - size + 1, r].)
            self.low[size_index] = first + np.searchsorted(begin, residues - size + 1, "left")
            self.high[size_index] = first + np.searchsorted(begin, residues, "right") - 1
        self.count = (self.high - self.low + 1).astype(np.float64)
        self.fit = np.array([absolute is None or size != absolute for size in self.sizes])
        # Each window's turn, as a quaternion, followed from step to step (``_turns``).
        self.q = None

    def _turns(self, h):
        """Each window's best turn from its file's residues onto its own now (``h``: the
        windows' 3 by 3 sums of a x b), as Horn finds it: the quaternion of the 4 by 4
        matrix's largest eigenvalue -- a turn, never a mirror -- followed by a few steps of
        power iteration from the one found a step before (an eigensolver the first time)."""

        np = _numpy()
        sxx, sxy, sxz = h[:, 0, 0], h[:, 0, 1], h[:, 0, 2]
        syx, syy, syz = h[:, 1, 0], h[:, 1, 1], h[:, 1, 2]
        szx, szy, szz = h[:, 2, 0], h[:, 2, 1], h[:, 2, 2]
        m = np.empty((len(h), 4, 4))
        m[:, 0, 0] = sxx + syy + szz
        m[:, 0, 1] = m[:, 1, 0] = syz - szy
        m[:, 0, 2] = m[:, 2, 0] = szx - sxz
        m[:, 0, 3] = m[:, 3, 0] = sxy - syx
        m[:, 1, 1] = sxx - syy - szz
        m[:, 1, 2] = m[:, 2, 1] = sxy + syx
        m[:, 1, 3] = m[:, 3, 1] = szx + sxz
        m[:, 2, 2] = -sxx + syy - szz
        m[:, 2, 3] = m[:, 3, 2] = syz + szy
        m[:, 3, 3] = -sxx - syy + szz
        if self.q is None:
            self.q = np.linalg.eigh(m)[1][:, :, -1]
        else:
            # Shifted by the size of h, the largest eigenvalue is the largest in size; squared,
            # each step closes most of the way to it.
            shift = np.sqrt((h * h).sum((1, 2)))
            m[:, [0, 1, 2, 3], [0, 1, 2, 3]] += shift[:, None]
            m2 = m @ m
            q = self.q
            for _ in range(3):
                q = np.einsum("kij,kj->ki", m2, q)
                q /= np.sqrt((q * q).sum(1))[:, None] + 1e-300
            self.q = q
        w, x, y, z = self.q.T
        turn = np.empty((len(h), 3, 3))
        # (Row vectors: a point a of the file's window is a @ turn in the window now.)
        turn[:, 0, 0] = w * w + x * x - y * y - z * z
        turn[:, 1, 0] = 2 * (x * y - w * z)
        turn[:, 2, 0] = 2 * (x * z + w * y)
        turn[:, 0, 1] = 2 * (x * y + w * z)
        turn[:, 1, 1] = w * w - x * x + y * y - z * z
        turn[:, 2, 1] = 2 * (y * z - w * x)
        turn[:, 0, 2] = 2 * (x * z - w * y)
        turn[:, 1, 2] = 2 * (y * z + w * x)
        turn[:, 2, 2] = w * w - x * x - y * y + z * z
        return turn

    def moves(self, x, weight, pooled: bool = False):
        """How far each residue is from where its windows would have it, each window's pull
        weighted by ``weight`` (one each) -- averaged over the windows of each size holding
        it and summed over the sizes, or (``pooled``) averaged over all of them."""

        np = _numpy()
        out = np.zeros_like(x)
        if not len(self.start) or not np.any(weight > 0):
            return out
        x0 = self.x0
        s1 = np.concatenate([np.zeros((1, 3, 3)), np.cumsum(x0[:, :, None] * x[:, None, :], 0)])
        s2 = np.concatenate([np.zeros((1, 3)), np.cumsum(x, axis=0)])
        total = s2[self.end] - s2[self.start]
        mid = total / self.length[:, None]
        # Sum over a window of (file - its middle) x now.
        h = (s1[self.end] - s1[self.start]) - self.mid0[:, :, None] * total[:, None, :]
        turn = self._turns(h)
        # A window takes a residue r of the file's to r @ turn + shift; weighted, summed
        # along the windows, each residue's windows' share is a difference of two sums.
        shift = mid - np.einsum("ki,kij->kj", self.mid0, turn)
        turns = np.concatenate([np.zeros((1, 3, 3)), np.cumsum(weight[:, None, None] * turn, 0)])
        shifts = np.concatenate([np.zeros((1, 3)), np.cumsum(weight[:, None] * shift, 0)])
        weights = np.concatenate([[0.0], np.cumsum(weight)])
        low, high = self.low, self.high + 1
        pull = weights[high] - weights[low]
        summed = np.einsum("ri,krij->krj", x0, turns[high] - turns[low])
        summed += shifts[high] - shifts[low] - pull[:, :, None] * x[None]
        if not self.fit.all():
            # (A size not fitted is matched where the file has it.)
            summed[~self.fit] = pull[~self.fit][:, :, None] * (x0 - x)[None]
        if pooled:
            return summed.sum(0) / self.count.sum(0)[:, None]
        return (summed / self.count[:, :, None]).sum(0)


ON = (0.55, 0.62)
"""When the shortest windows (4 residues) and the whole chain switch on, as shares of the
way from noise 1 to noise 0: turns and helices from about noise 0.7, the whole shape from
noise 0.28."""

JITTER = 0.50
"""How much sooner or later than others its size the shortest windows switch on (the
longest, not at all), as a share of the way."""

KNOTS = 12
"""Residues between the knots of the rise and fall along the chain of when it folds."""

PACE = (
    (0.0, 0.03, 0.06, 0.1, 0.16, 0.2, 0.3, 0.45, 0.6, 1.0),
    (0.0, 0.03, 0.08, 0.14, 0.25, 0.4, 0.7, 0.9, 0.98, 1.0),
)
"""How far from the file (RMS) the chain is at most, as a share of how far its prior is, at
each noise: 70% at noise 0.3 (helices forming, the chain drawing in), a quarter at 0.16
(its shape there), a twelfth at 0.06 (nearly the file)."""

RAMP = 0.12
"""How long a window takes to switch on fully, as a share of the way."""

SHORTEST = 4
WIDER = 1.6
"""The windows: 4 residues, then each 1.6 times as long, to the whole chain."""

LOCAL = 10
"""Windows this long and shorter are the chain's local shape: put back after every step."""

PASSES = 2

PULL = (0.3, 0.2)
"""How much of the way to where a window would have them its residues are moved in a
step: windows just longer than LOCAL, and the whole chain."""

LOOSE = 0.08
PASSING = 0.3
"""Below noise LOOSE, how near two C-alphas not bonded may come falls with the noise, to
PASSING of CLASH (a loop that must pass through the chain to its place can)."""

PASS = (24, 0.45, 0.25)
"""C-alphas further apart along the chain than PASS[0] may come nearer as the noise falls
from PASS[1] to PASS[2], to PASSING of CLASH: parts of the chain pass through each other
as its shape comes together."""

HOLD = 2
"""Sweeps over the bonds and angles after each step (a snapshot kept is swept till in shape)."""

ANGLES = (80.0, 150.0)
"""The angle at each C-alpha is kept within these, degrees (or the file's own, beyond them)."""

HELD = (0.15, 2.0)
"""For a chain held somewhere: how much sooner its whole window comes on, as a share of the
way, and how many times harder it pulls."""

RATE = 0.6
"""How far, Å, a residue moves in a step at most."""


def _within(a, b, reach: float):
    """Every pair (i, j) with a[i] and b[j] nearer than ``reach``: a block of rows at a time,
    so a long chain is looked through in little memory."""

    np = _numpy()
    rows, cols = [], []
    for start in range(0, len(a), 512):
        gap = a[start : start + 512, None, :] - b[None, :, :]
        i, j = np.nonzero((gap * gap).sum(-1) < reach * reach)
        rows.append(i + start)
        cols.append(j)
    if not rows:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    return np.concatenate(rows), np.concatenate(cols)


def _smooth(t):
    np = _numpy()
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _add(grad, index, values) -> None:
    np = _numpy()
    n = len(grad)
    for k in range(3):
        grad[:, k] += np.bincount(index, weights=values[:, k], minlength=n)


def _volumes(x, q):
    """The signed volume of each four C-alphas from those at ``q``: positive for a right-handed
    turn, as an alpha helix's."""

    np = _numpy()
    a, b, c, d = x[q], x[q + 1], x[q + 2], x[q + 3]
    return np.einsum("ij,ij->i", b - a, np.cross(c - a, d - a))


def _laid_over(moving, onto):
    """``moving`` turned and moved to lie best over ``onto`` (Kabsch)."""

    np = _numpy()
    a_mid, b_mid = moving.mean(0), onto.mean(0)
    a, b = moving - a_mid, onto - b_mid
    u, _, vt = np.linalg.svd(a.T @ b)
    d = np.sign(np.linalg.det(u @ vt)) or 1.0
    turn = u @ np.diag([1.0, 1.0, d]) @ vt
    return a @ turn + b_mid


def _unit(v):
    np = _numpy()
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-12)


def _coil(rng, x0, resi, bonded, fixed, around, step, nucleic):
    """The prior: a random coil with a protein's local geometry -- each step the file's
    length, each turn within ``TURN`` (a nucleic acid's, within its own), any dihedral --
    wandering in a ball round where the chain ends up, keeping off itself and what is
    held, and passing through every fixed residue's C-alpha in as many steps as the file
    takes to reach it."""

    np = _numpy()
    n = len(x0)
    centre = x0.mean(0)
    radius = float(np.sqrt(((x0 - centre) ** 2).sum(1).mean()))
    ball = max(BALL * radius, 2.0 * step)
    lengths = np.linalg.norm(np.diff(x0, axis=0), axis=1)
    if nucleic:
        turns = _angles(x0, bonded)
        low, high = (
            (float(np.percentile(turns, 5)), float(np.percentile(turns, 95)))
            if len(turns)
            else (90.0, 160.0)
        )
    else:
        low, high = TURN
    mean, spread = (low + high) / 2.0, (high - low) / 4.0
    marks = np.flatnonzero(fixed)
    out = np.zeros((n, 3))
    tries = 48
    if fixed[0]:
        out[0] = x0[0]
    else:
        out[0] = centre + _unit(rng.standard_normal(3)) * ball * 0.5 * rng.random() ** (1 / 3)
    for i in range(1, n):
        if fixed[i]:
            out[i] = x0[i]
            continue
        length = lengths[i - 1] if bonded[i - 1] else max(lengths[i - 1], _LIMIT[nucleic] + 1.0)
        length = min(length, ball)
        if i >= 2 and bonded[i - 2]:
            back = _unit(out[i - 2] - out[i - 1])
            theta = np.radians(np.clip(rng.normal(mean, spread, tries), low, high))
            side = _unit(np.cross(back, rng.standard_normal((tries, 3))))
            steps = np.cos(theta)[:, None] * back + np.sin(theta)[:, None] * side
        else:
            steps = _unit(rng.standard_normal((tries, 3)))
        points = out[i - 1] + length * steps
        score = np.zeros(tries)
        reach = np.linalg.norm(points - centre, axis=1)
        score += np.where(reach > ball, 10.0 + reach - ball, 0.0)
        if i > 2:
            gap = points[:, None, :] - out[None, : i - 2, :]
            nearest = np.sqrt((gap * gap).sum(-1).min(1))
            score += np.where(nearest < 4.0, 5.0 + (4.0 - nearest), 0.0)
        if len(around):
            gap = points[:, None, :] - around[None, :, :]
            nearest = np.sqrt((gap * gap).sum(-1).min(1))
            score += np.where(nearest < 4.0, 5.0 + (4.0 - nearest), 0.0)
        ahead = marks[marks > i]
        if len(ahead):
            target = ahead[0]
            left = float(lengths[i:target].sum())
            far = np.linalg.norm(x0[target] - points, axis=1)
            score += 3.0 * np.maximum(0.0, far - 0.85 * left)
        out[i] = points[int(np.argmin(score))]
    return out


def _angles(x, bonded):
    np = _numpy()
    if len(x) < 3:
        return np.zeros(0)
    u, w = x[:-2] - x[1:-1], x[2:] - x[1:-1]
    cos = np.einsum("ij,ij->i", u, w) / (
        np.linalg.norm(u, axis=1) * np.linalg.norm(w, axis=1) + 1e-12
    )
    ok = bonded[:-1] & bonded[1:]
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))[ok]


# -- secondary structure, as mol-sketch assigns it ---------------------------------------


def assigned(trace) -> list[str]:
    """Each residue's secondary structure from its C-alphas alone, as mol-sketch assigns it
    to a structure without helix and strand records (P-SEA-like): ``H``, ``E`` or ``L``.
    ``trace`` is one chain's protein C-alphas in order (neighbours in it are neighbours,
    however far apart)."""

    np = _numpy()
    p = np.asarray(trace, dtype=np.float64)
    n = len(p)
    ss = ["L"] * n
    if n < 5:
        return ss

    def d(i, j):
        return float(np.linalg.norm(p[j] - p[i])) if 0 <= i < n and 0 <= j < n else math.nan

    def angle(i):
        u, v = p[i - 1] - p[i], p[i + 1] - p[i]
        c = float(u @ v / (np.linalg.norm(u) * np.linalg.norm(v) or 1.0))
        return math.degrees(math.acos(max(-1.0, min(1.0, c))))

    def dihedral(i):
        b1, b2, b3 = p[i] - p[i - 1], p[i + 1] - p[i], p[i + 2] - p[i + 1]
        n1, n2 = np.cross(b1, b2), np.cross(b2, b3)
        m = np.cross(n1, b2 / (np.linalg.norm(b2) or 1.0))
        return math.degrees(math.atan2(float(m @ n2), float(n1 @ n2)))

    def within(x, c, w):
        return abs(x - c) <= w  # (False for nan, as in JavaScript)

    for i in range(1, n - 1):
        d2, d3, d4 = d(i - 1, i + 1), d(i - 1, i + 2), d(i - 1, i + 3)
        tau = angle(i)
        al = dihedral(i) if i + 2 < n else math.nan
        helix = (within(d2, 5.5, 0.5) and within(d3, 5.3, 0.5) and within(d4, 6.4, 0.6)) or (
            within(tau, 89, 12) and within(al, 50, 20)
        )
        strand = (within(d2, 6.7, 0.6) and within(d3, 9.9, 0.9) and within(d4, 12.4, 1.1)) or (
            within(tau, 124, 14) and abs(al) >= 125
        )
        if helix:
            ss[i] = "H"
        elif strand:
            ss[i] = "E"
    for i in range(1, n - 1):
        if ss[i] == "L" and ss[i - 1] == ss[i + 1] and ss[i - 1] != "L":
            ss[i] = ss[i - 1]
    for kind, least in (("H", 4), ("E", 3)):
        i = 0
        while i < n:
            if ss[i] != kind:
                i += 1
                continue
            j = i
            while j < n and ss[j] == kind:
                j += 1
            if j - i < least:
                ss[i:j] = ["L"] * (j - i)
            i = j
    out = ss[:]
    for i in range(n):
        if ss[i] == "H":
            if i > 0 and ss[i - 1] == "L":
                out[i - 1] = "H"
            if i < n - 1 and ss[i + 1] == "L":
                out[i + 1] = "H"
    return out


def runs(ss, kind: str = "H") -> int:
    """How many runs of ``kind`` (helices, for ``H``) an assignment has."""

    count, last = 0, None
    for each in ss:
        if each == kind and last != kind:
            count += 1
        last = each
    return count


# -- a structure file, read as mol-sketch reads it ---------------------------------------


@dataclass(slots=True)
class _Group:
    """A residue (or a ligand, an ion, a water) as mol-sketch groups atoms: by chain,
    number, name and record. ``het`` as mol-sketch has it -- a HETATM residue bonded into
    its chain (a selenomethionine) is the chain's -- ``written``: whether the file writes
    it HETATM."""

    chain: str
    resi: int
    resn: str
    written: bool
    atoms: list
    kept: list
    het: bool = False
    nucleic: bool = False
    trace: int = -1


class _Molecule:
    """A PDB or mmCIF file's atoms -- its first model's, each alternate position too -- in
    the groups mol-sketch reads them in, with where each atom's coordinates are written in
    the text, so they can be written again."""

    def __init__(self, text: str) -> None:
        np = _numpy()
        self.text = text
        self.cif = bool(re.match(r"\s*data_", text)) or "_atom_site." in text
        self.lines = text.split("\n")
        self.records = False  # whether it has helix or strand records
        names, elements, coords, keys, kept, written, places = [], [], [], [], [], [], []
        if self.cif:
            self._read_cif(names, elements, coords, keys, kept, written, places)
        else:
            self._read_pdb(names, elements, coords, keys, kept, written, places)
        self.xyz = np.array(coords, dtype=np.float64).reshape(-1, 3)
        self.names = names
        self.elements = elements
        self.places = places
        groups: dict[tuple, _Group] = {}
        order: list[_Group] = []
        self.group_of = np.zeros(len(names), dtype=np.int64)
        for index, key in enumerate(keys):
            group = groups.get(key)
            if group is None:
                group = groups[key] = _Group(key[0], key[1], key[2], key[3], [], [])
                order.append(group)
            group.atoms.append(index)
            if kept[index]:
                group.kept.append(index)
        # (In the order mol-sketch meets them: by the first of their atoms it keeps.)
        order = [group for group in order if group.kept] + [g for g in order if not g.kept]
        for number, group in enumerate(order):
            self.group_of[group.atoms] = number
        self.groups = order
        self._as_mol_sketch_has_them()

    def _read_pdb(self, names, elements, coords, keys, kept, written, places) -> None:
        models = any(line.startswith("MODEL") for line in self.lines)
        inside = not models
        seen_atoms = False
        for number, line in enumerate(self.lines):
            record = line[:6].strip()
            if record in ("HELIX", "SHEET"):
                self.records = True
                continue
            if record == "MODEL":
                inside = not seen_atoms
                continue
            if record == "ENDMDL":
                if seen_atoms:
                    inside = False
                continue
            if record not in ("ATOM", "HETATM") or not inside:
                continue
            try:
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
            except ValueError:
                continue
            seen_atoms = True
            name = line[12:16].strip()
            element = line[76:78].strip().upper() or _element(name)
            resn = line[17:20].strip()
            het = record == "HETATM" or resn == "HOH"
            resi = _whole(line[22:26])
            names.append(name)
            elements.append(element)
            coords.append((x, y, z))
            keys.append((line[21:22].strip(), resi, resn, het))
            kept.append(line[16:17].strip() in ("", "A"))
            written.append(record == "HETATM")
            places.append(number)

    def _read_cif(self, names, elements, coords, keys, kept, written, places) -> None:
        loop = _cif_loop(self.lines, "_atom_site.")
        if loop is None:
            raise ValueError("The file has no atoms (no _atom_site loop).")
        columns, rows = loop
        self.cif_columns = columns

        def column(name: str) -> int:
            return columns.index(name) if name in columns else -1

        at = {
            name: column(name)
            for name in (
                "group_PDB",
                "type_symbol",
                "label_atom_id",
                "label_alt_id",
                "label_comp_id",
                "label_asym_id",
                "auth_asym_id",
                "label_seq_id",
                "auth_seq_id",
                "Cartn_x",
                "Cartn_y",
                "Cartn_z",
                "pdbx_PDB_model_num",
            )
        }
        if min(at["Cartn_x"], at["Cartn_y"], at["Cartn_z"]) < 0:
            raise ValueError("The file's atoms have no coordinates.")
        first_model = None
        for row in rows:
            value = [token for token, *_ in row]
            model = value[at["pdbx_PDB_model_num"]] if at["pdbx_PDB_model_num"] >= 0 else "1"
            if first_model is None:
                first_model = model
            if model != first_model:
                continue
            alt = value[at["label_alt_id"]] if at["label_alt_id"] >= 0 else "."
            name = value[at["label_atom_id"]]
            resn = value[at["label_comp_id"]]
            chain = (
                value[at["auth_asym_id"]] if at["auth_asym_id"] >= 0 else value[at["label_asym_id"]]
            )
            seq = value[at["auth_seq_id"]] if at["auth_seq_id"] >= 0 else value[at["label_seq_id"]]
            if seq in (".", "?"):
                seq = value[at["label_seq_id"]] if at["label_seq_id"] >= 0 else "0"
            element = (value[at["type_symbol"]] if at["type_symbol"] >= 0 else "").upper()
            if element in ("", ".", "?"):
                element = _element(name)
            group = value[at["group_PDB"]] if at["group_PDB"] >= 0 else "ATOM"
            try:
                x, y, z = (float(value[at[f"Cartn_{axis}"]]) for axis in "xyz")
            except ValueError:
                continue
            names.append(name)
            elements.append(element)
            coords.append((x, y, z))
            keys.append((chain or "", _whole(seq), resn, group == "HETATM" or resn == "HOH"))
            kept.append(alt in ("", ".", "?", "A"))
            written.append(group == "HETATM")
            places.append(row)
        self.records = any(
            line.startswith(("_struct_conf.", "_struct_sheet_range.")) for line in self.lines
        )

    def _as_mol_sketch_has_them(self) -> None:
        """Each group's ``het``, ``nucleic`` and trace atom, as mol-sketch has them."""

        from flexo.structures import _NUCLEIC

        np = _numpy()
        groups, names, xyz = self.groups, self.names, self.xyz

        def atom(group, name):
            if group is None:
                return None
            for index in group.kept:
                if names[index] == name:
                    return index
            return None

        def near(a, b, limit):
            return (
                a is not None
                and b is not None
                and float(np.sum((xyz[a] - xyz[b]) ** 2)) <= limit**2
            )

        for k, group in enumerate(groups):
            group.het = group.written or group.resn == "HOH"
            if not group.kept or not group.het or group.resn == "HOH":
                continue
            before = groups[k - 1] if k > 0 and groups[k - 1].chain == group.chain else None
            after = (
                groups[k + 1]
                if k + 1 < len(groups) and groups[k + 1].chain == group.chain
                else None
            )
            if atom(group, "CA") is not None:
                linked = near(atom(before, "C"), atom(group, "N"), 1.75) or near(
                    atom(group, "C"), atom(after, "N"), 1.75
                )
            else:
                linked = near(atom(before, "O3'"), atom(group, "P"), 1.9) or near(
                    atom(group, "O3'"), atom(after, "P"), 1.9
                )
            if linked:
                group.het = False
        for group in groups:
            if not group.kept:
                continue
            held = {names[index] for index in group.kept}
            group.nucleic = (
                not group.het
                and ("O3'" in held or "C4'" in held or group.resn in _NUCLEIC)
                and "CA" not in held
            )
            for index in group.kept:
                name = names[index]
                # (A nucleotide's trace is its P, else its C4'; an amino acid's, its CA.)
                traced = (
                    name == "P" or (group.trace < 0 and name == "C4'")
                    if group.nucleic
                    else name == "CA"
                )
                if traced:
                    group.trace = index
            if group.trace < 0 and not group.het:
                group.trace = group.kept[0]

    def written_as(self, xyz, records: list[str], heading: str) -> str:
        """The file again, its atoms at ``xyz``, its helix and strand records ``records``
        (as the format writes them) in place of its own, a residue bonded into its chain
        written as the chain's (so it stays so however far it has moved), and ``heading``
        first (so no two noised files begin alike)."""

        lines = list(self.lines)
        polymer = {
            index
            for group in self.groups
            if group.written and not group.het
            for index in group.atoms
        }
        if self.cif:
            at = {name: self.cif_columns.index(name) for name in ("Cartn_x", "Cartn_y", "Cartn_z")}
            group_column = (
                self.cif_columns.index("group_PDB") if "group_PDB" in self.cif_columns else -1
            )
            edits: dict[int, dict[int, str]] = {}
            for index, row in enumerate(self.places):
                for axis, value in zip("xyz", xyz[index], strict=True):
                    _, number, place = row[at[f"Cartn_{axis}"]]
                    edits.setdefault(number, {})[place] = f"{value:.3f}"
                if index in polymer and group_column >= 0:
                    _, number, place = row[group_column]
                    edits.setdefault(number, {})[place] = "ATOM"
            for number, changes in edits.items():
                tokens = _tokens(lines[number])
                for place, value in changes.items():
                    tokens[place] = value
                lines[number] = " ".join(tokens)
            lines = [
                re.sub(r"^(\s*)_(struct_conf|struct_sheet_range)\.", r"\1_flexo_was_\2.", line)
                for line in lines
            ]
            return "\n".join([f"# {heading}", *lines, *records, ""])
        for index, number in enumerate(self.places):
            line = lines[number]
            x, y, z = xyz[index]
            head = "ATOM  " if index in polymer else line[:6]
            lines[number] = f"{head}{line[6:30]}{x:8.3f}{y:8.3f}{z:8.3f}{line[54:]}"
        kept = [line for line in lines if line[:6].strip() not in ("HELIX", "SHEET")]
        return "\n".join([f"REMARK 250 {heading}", *records, *kept])


def _whole(text: str) -> int:
    """A number as JavaScript's parseInt reads it: its leading digits (0 if none)."""

    found = re.match(r"\s*([+-]?\d+)", text)
    return int(found.group(1)) if found else 0


def _element(name: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", name).upper()
    return letters[:1] if len(letters) > 1 and letters not in _COVALENT else letters


_COVALENT = frozenset(
    {"H", "C", "N", "O", "S", "P", "F", "CL", "BR", "I", "SE", "ZN", "MG", "CA", "FE", "NA", "K"}
)


_TOKEN = re.compile(r"""'(?:[^']|'(?=\S))*'(?=\s|$)|"(?:[^"]|"(?=\S))*"(?=\s|$)|\S+""")


def _tokens(line: str) -> list[str]:
    """A line of an mmCIF loop's values, as written (quotes kept): split at spaces, or --
    where it has quotes -- as mol-sketch splits it, a quoted value kept whole."""

    return _TOKEN.findall(line) if "'" in line or '"' in line else line.split()


def _cif_loop(lines: list[str], prefix: str):
    """The first loop of a category in an mmCIF file, as mol-sketch reads loops (a line at
    a time, values with quotes kept whole): its columns, and its rows -- each value with
    the line it is on and which value of that line it is."""

    number = 0
    total = len(lines)
    while number < total:
        if not lines[number].startswith("loop_"):
            number += 1
            continue
        number += 1
        names = []
        while number < total and lines[number].strip().startswith("_"):
            names.append(lines[number].strip().split()[0])
            number += 1
        if not names or not names[0].startswith(prefix):
            continue
        columns = [name.split(".", 1)[1] for name in names]
        width = len(columns)
        rows, row = [], []
        while number < total:
            line = lines[number]
            if line.startswith(("#", "loop_", "_", "data_")):
                break
            if line.startswith(";"):
                raise ValueError("A value of the file's atoms runs over several lines.")
            for place, token in enumerate(_tokens(line)):
                if len(token) > 1 and token[0] in "'\"" and token[-1] == token[0]:
                    token = token[1:-1]
                row.append((token, number, place))
                if len(row) == width:
                    rows.append(row)
                    row = []
            number += 1
        return columns, rows
    return None


# -- a structure noised -------------------------------------------------------------------


Key = tuple[str, int, str]
"""A residue as a selection picks it: its chain, number and name."""


class _Noised:
    """A structure's trajectory: every chain's, with ``fixed`` (residue keys) held and
    ``seed`` picking the run -- and how each of its atoms moves with it."""

    def __init__(self, molecule: _Molecule, digest: str, seed: int, fixed: frozenset) -> None:
        np = _numpy()
        self.molecule = molecule
        self.seed = seed
        groups = molecule.groups
        xyz = molecule.xyz
        self.held = np.array([(g.chain, g.resi, g.resn) in fixed for g in groups], dtype=bool)
        # Each chain's trace: its residues with a trace atom, by number.
        chains: dict[str, list[int]] = {}
        for number, group in enumerate(groups):
            if group.trace >= 0 and not group.het:
                chains.setdefault(group.chain, []).append(number)
        self.chains = []
        for name, members in chains.items():
            members.sort(key=lambda k: groups[k].resi)
            trace = xyz[[groups[k].trace for k in members]]
            resi = np.array([groups[k].resi for k in members])
            nucleic = np.array([groups[k].nucleic for k in members])
            gap = np.linalg.norm(np.diff(trace, axis=0), axis=1)
            limit = np.where(nucleic[:-1] | nucleic[1:], _LIMIT[True], _LIMIT[False])
            bonded = (gap <= limit) & (np.diff(resi) <= 2) & (nucleic[:-1] == nucleic[1:])
            fixed_here = self.held[members]
            # What it may not pass through: what is held of other chains, and held ligands.
            around = [
                xyz[groups[k].trace]
                for k in range(len(groups))
                if self.held[k]
                and groups[k].trace >= 0
                and not groups[k].het
                and groups[k].chain != name
            ] + [
                xyz[index]
                for k in range(len(groups))
                if self.held[k] and groups[k].het
                for index in groups[k].kept
                if molecule.elements[index] != "H"
            ]
            chain = Chain(
                trace,
                resi,
                bonded,
                fixed_here,
                bool(nucleic.mean() > 0.5),
                np.array(around).reshape(-1, 3) if around else None,
            )
            self.chains.append((name, members, chain))
        self.shapes = [_Shape(chain) for _, _, chain in self.chains]
        self.trajectories = [
            _trajectory(chain, seed, name, f"{digest}|{sorted(fixed)}")
            for name, members, chain in self.chains
        ]
        # Each group not of a trace moves with the trace residue nearest it (by its nearest
        # atom), unless it is held.
        self.carrier = np.full(len(groups), -1, dtype=np.int64)
        traced = [k for _, members, _ in self.chains for k in members]
        self.carrier[traced] = np.arange(len(traced))
        loose = np.flatnonzero(self.carrier < 0)
        if traced and len(loose):
            points = xyz[[groups[k].trace for k in traced]]
            owner, which = [], []
            for k in loose.tolist():
                for index in groups[k].kept or groups[k].atoms:
                    owner.append(k)
                    which.append(index)
            nearest = np.empty(len(which), dtype=np.int64)
            distance = np.empty(len(which))
            for start in range(0, len(which), 2048):
                chunk = xyz[which[start : start + 2048]]
                d2 = ((chunk[:, None, :] - points[None, :, :]) ** 2).sum(-1)
                nearest[start : start + 2048] = d2.argmin(1)
                distance[start : start + 2048] = d2.min(1)
            # (A group goes with the residue its nearest atom is nearest.)
            order = np.lexsort((distance, owner))
            owner_sorted = np.asarray(owner)[order]
            first = np.concatenate([[True], owner_sorted[1:] != owner_sorted[:-1]])
            self.carrier[owner_sorted[first]] = nearest[order][first]
        self.file_ss = [self._file_ss(name, members) for name, members, _ in self.chains]

    def _file_ss(self, name: str, members: list[int]) -> list[str]:
        """The file's helices and strands along a chain's trace, as mol-sketch draws the
        file: from its records, or from its C-alphas."""

        molecule = self.molecule
        groups = molecule.groups
        if molecule.records:
            spans = _records(molecule)
            out = []
            for k in members:
                kind = "L"
                for what, chain, low, high in spans:
                    if chain == name and low <= groups[k].resi <= high and not groups[k].nucleic:
                        kind = "E" if what == "E" or kind == "E" else "H"
                out.append(kind)
            return out
        # (mol-sketch assigns a chain's protein residues in the file's order.)
        protein = [k for k in members if not groups[k].nucleic]
        in_order = sorted(protein)
        assigned_ss = dict(
            zip(in_order, assigned(molecule.xyz[[groups[k].trace for k in in_order]]), strict=True)
        )
        return [assigned_ss.get(k, "L") for k in members]

    def at(self, noise: float):
        """Every atom's position at ``noise``, and the helix and strand records to draw it
        with: (chain, kind, first residue, last residue)."""

        np = _numpy()
        molecule = self.molecule
        groups = molecule.groups
        if noise <= 0:
            noise = 0.0  # (the file itself: its own coordinates, not the trajectory's copy)
        traces, olds = [], []
        for (_, _, chain), trajectory, shape in zip(
            self.chains, self.trajectories, self.shapes, strict=True
        ):
            old = np.asarray(chain.trace, dtype=np.float64)
            traces.append(old.copy() if noise == 0 else at_noise(trajectory, noise, shape))
            olds.append(old)
        if not traces:
            return molecule.xyz.copy(), []
        turns = np.concatenate(
            [
                _turns_along(old, new, chain.bonded)
                for old, new, (_, _, chain) in zip(olds, traces, self.chains, strict=True)
            ]
        )
        old_all = np.concatenate(olds)
        new_all = np.concatenate(traces)
        carrier = self.carrier[molecule.group_of]
        held = self.held[molecule.group_of] | (carrier < 0)
        slot = np.where(held, 0, carrier)
        out = molecule.xyz.copy()
        moving = ~held & (noise > 0)
        if moving.any():
            s = slot[moving]
            out[moving] = (
                np.einsum("ki,kij->kj", molecule.xyz[moving] - old_all[s], turns[s]) + new_all[s]
            )
        records = []
        for (name, members, chain), new, old, file_ss in zip(
            self.chains, traces, olds, self.file_ss, strict=True
        ):
            formed = _formed(old, new, chain.bonded)
            ss = [kind if ok else "L" for kind, ok in zip(file_ss, formed, strict=True)]
            for kind, low, high in _spans(ss):
                records.append((name, kind, groups[members[low]], groups[members[high]]))
        return out, records

    def text(self, noise: float) -> str:
        """The file at ``noise``, as mol-sketch reads it."""

        xyz, spans = self.at(noise)
        molecule = self.molecule
        heading = f"flexo noise {noise:.4f} seed {self.seed} {id(self):x}"
        return molecule.written_as(xyz, _written_records(molecule, spans), heading)


def _turns_along(old, new, bonded):
    """How each residue of a chain is turned at ``new`` from the file's ``old``: the turn
    of the frame its C-alpha and its neighbours' make (row vectors: ``(atom - C-alpha) @ turn``). A
    residue at an end, or by a break, takes its neighbour's; one with none is not turned."""

    np = _numpy()
    n = len(old)
    turns = np.repeat(np.eye(3)[None], n, axis=0)
    if n < 3:
        return turns
    before = np.concatenate([[False], bonded])
    after = np.concatenate([bonded, [False]])
    middle = np.flatnonzero(before & after)
    if not len(middle):
        return turns

    def frames(x):
        p, c, q = x[middle - 1], x[middle], x[middle + 1]
        e1 = _unit(q - p)
        bend = 2 * c - p - q
        e2 = bend - (bend * e1).sum(1)[:, None] * e1
        size = np.sqrt((e2 * e2).sum(1))
        e2 = e2 / (size[:, None] + 1e-12)
        e3 = np.cross(e1, e2)
        return np.stack([e1, e2, e3], axis=2), size

    f0, s0 = frames(old)
    f1, s1 = frames(new)
    good = (s0 > 1e-3) & (s1 > 1e-3)
    turn = f0 @ np.transpose(f1, (0, 2, 1))
    turns[middle[good]] = turn[good]
    known = np.zeros(n, dtype=bool)
    known[middle[good]] = True
    # Ends and the residues by a break take the turn of the bonded neighbour that has one.
    for k in np.flatnonzero(~known):
        for other in (k - 1, k + 1):
            linked = 0 <= other < n and bonded[min(k, other)] and known[other]
            if linked:
                turns[k] = turns[other]
                break
    return turns


FORMED = 0.35
"""How near, Å (the RMS of five C-alphas laid over the file's), a residue's own stretch of the
chain must be to the file's for its helix or strand to be drawn."""


def _formed(old, new, bonded):
    """Whether each residue's stretch of chain -- itself and two each side, bonded -- is the
    file's shape, within FORMED."""

    np = _numpy()
    n = len(old)
    out = np.zeros(n, dtype=bool)
    if n < 5:
        return out
    link = np.concatenate([[0], np.cumsum(~bonded)])
    start = np.arange(n - 4)
    whole = link[start + 4] == link[start]
    if not whole.any():
        return out
    index = start[whole][:, None] + np.arange(5)
    a = old[index] - old[index].mean(1, keepdims=True)
    b = new[index] - new[index].mean(1, keepdims=True)
    h = np.einsum("kwi,kwj->kij", a, b)
    sv = np.linalg.svd(h, compute_uv=False)
    sign = np.sign(np.linalg.det(h))
    best = sv[:, 0] + sv[:, 1] + np.where(sign < 0, -sv[:, 2], sv[:, 2])
    rms2 = np.maximum((a * a).sum((1, 2)) + (b * b).sum((1, 2)) - 2 * best, 0.0) / 5
    close = np.sqrt(rms2) <= FORMED
    out[start[whole][close] + 2] = True
    # (The two at each end of a stretch formed are formed if the stretch beside them is.)
    for shift in (1, 2):
        out[start[whole][close] + 2 - shift] = True
        out[start[whole][close] + 2 + shift] = True
    return out


def _spans(ss):
    """The runs of helix and strand in an assignment -- helices of 4 residues or more,
    strands of 3 or more, as mol-sketch keeps them -- as (kind, first, last)."""

    out = []
    k, n = 0, len(ss)
    while k < n:
        kind = ss[k]
        j = k
        while j < n and ss[j] == kind:
            j += 1
        if kind in ("H", "E") and j - k >= (4 if kind == "H" else 3):
            out.append((kind, k, j - 1))
        k = j
    return out


def _records(molecule: _Molecule):
    """A file's helix and strand records as mol-sketch reads them: (kind, chain, first,
    last)."""

    out = []
    if molecule.cif:
        for prefix, kind in (("_struct_conf.", "H"), ("_struct_sheet_range.", "E")):
            loop = _cif_loop(molecule.lines, prefix)
            if loop is None:
                continue
            columns, rows = loop

            def column(*names, columns=columns):
                return next((columns.index(name) for name in names if name in columns), -1)

            chain = column("beg_auth_asym_id", "beg_label_asym_id")
            first = column("beg_auth_seq_id", "beg_label_seq_id")
            last = column("end_auth_seq_id", "end_label_seq_id")
            what = column("conf_type_id")
            for row in rows:
                value = [token for token, *_ in row]
                if kind == "H" and what >= 0 and not value[what].startswith("HELX"):
                    continue
                if min(chain, first, last) < 0:
                    continue
                out.append((kind, value[chain], _whole(value[first]), _whole(value[last])))
        return out
    for line in molecule.lines:
        if line.startswith("HELIX"):
            out.append(("H", line[19:20].strip(), _whole(line[21:25]), _whole(line[33:37])))
        elif line.startswith("SHEET"):
            out.append(("E", line[21:22].strip(), _whole(line[22:26]), _whole(line[33:37])))
    return out


def _written_records(molecule: _Molecule, spans) -> list[str]:
    """Helix and strand records for ``spans`` -- (chain, kind, first group, last group) --
    as the file's format writes them; with none, one naming no residue (so the frame is all
    loops: mol-sketch would otherwise find helices of its own in a coil)."""

    if not spans:
        chain = molecule.groups[0].chain if molecule.groups else "A"
        spans = [
            (
                chain,
                "H",
                _Group(chain, -9999, "UNK", False, [], []),
                _Group(chain, -9998, "UNK", False, [], []),
            )
        ]
    if molecule.cif:
        helices = [span for span in spans if span[1] == "H"]
        strands = [span for span in spans if span[1] == "E"]
        lines = []
        if helices:
            lines += [
                "loop_",
                *(
                    f"_struct_conf.{name}"
                    for name in (
                        "conf_type_id",
                        "id",
                        "beg_auth_comp_id",
                        "beg_auth_asym_id",
                        "beg_auth_seq_id",
                        "end_auth_comp_id",
                        "end_auth_asym_id",
                        "end_auth_seq_id",
                    )
                ),
            ]
            lines += [
                f"HELX_P HELX_P{k + 1} {a.resn} {chain} {a.resi} {b.resn} {chain} {b.resi}"
                for k, (chain, _, a, b) in enumerate(helices)
            ]
            lines.append("#")
        if strands:
            lines += [
                "loop_",
                *(
                    f"_struct_sheet_range.{name}"
                    for name in (
                        "sheet_id",
                        "id",
                        "beg_auth_comp_id",
                        "beg_auth_asym_id",
                        "beg_auth_seq_id",
                        "end_auth_comp_id",
                        "end_auth_asym_id",
                        "end_auth_seq_id",
                    )
                ),
            ]
            lines += [
                f"S{k + 1} 1 {a.resn} {chain} {a.resi} {b.resn} {chain} {b.resi}"
                for k, (chain, _, a, b) in enumerate(strands)
            ]
            lines.append("#")
        return lines
    lines = []
    helix = strand = 0
    for chain, kind, a, b in spans:
        ends = (
            f"{a.resn[:3]:>3} {chain[:1]:1} {a.resi:>4}",
            f"{b.resn[:3]:>3} {chain[:1]:1} {b.resi:>4}",
        )
        if kind == "H":
            helix += 1
            line = f"HELIX  {helix:>3} {helix:>3} {ends[0]}  {ends[1]}  1"
            lines.append(f"{line:<71}{b.resi - a.resi + 1:>5}")
        else:
            strand += 1
            lines.append(
                f"SHEET  {1:>3} S{strand:<2} 1 {ends[0][:3]} {chain[:1]:1}{a.resi:>4}  "
                f"{b.resn[:3]:>3} {chain[:1]:1}{b.resi:>4}  0"
            )
    return lines


# -- kept: in memory, and on disk with flexo's other caches -------------------------------


_LOCK = threading.RLock()
_KEPT_RUNS: OrderedDict[str, object] = OrderedDict()
_KEPT_NOISED: OrderedDict[tuple, _Noised] = OrderedDict()
_KEPT_MOLECULES: OrderedDict[str, _Molecule] = OrderedDict()


def _cache_folder() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "flexo" / "noise"


def _trajectory(chain: Chain, seed: int, name: str, what: str):
    """``chain``'s trajectory, worked out once: kept in memory, and on disk by what it is
    worked out from (the file, the chain, ``seed``, what is held; ``what`` says the file
    and what is held)."""

    np = _numpy()
    named = f"{VERSION}|{LEVELS}|{what}|{name}|{int(seed)}"
    key = hashlib.sha256(named.encode()).hexdigest()[:32]
    with _LOCK:
        found = _KEPT_RUNS.get(key)
        if found is not None:
            _KEPT_RUNS.move_to_end(key)
            return found
    kept = _cache_folder() / f"{key}.npy"
    trajectory = None
    try:
        trajectory = np.load(kept, allow_pickle=False)
        if trajectory.shape != (LEVELS + 1, len(chain.trace), 3):
            trajectory = None
        else:
            os.utime(kept)  # read now: kept the longest
    except (OSError, ValueError):
        trajectory = None
    if trajectory is None:
        trajectory = fold(chain, seed, name)
        try:
            kept.parent.mkdir(parents=True, exist_ok=True)
            others = sorted(kept.parent.glob("*.npy"), key=lambda item: item.stat().st_mtime)
            for old in others[: max(0, len(others) - KEPT + 1)]:
                old.unlink(missing_ok=True)
            partial = kept.with_suffix(".saving")
            with partial.open("wb") as handle:
                np.save(handle, trajectory, allow_pickle=False)
            partial.replace(kept)
        except OSError:
            pass  # a cache that cannot be written is only slower
    with _LOCK:
        _KEPT_RUNS[key] = trajectory
        while len(_KEPT_RUNS) > 32:
            _KEPT_RUNS.popitem(last=False)
    return trajectory


def noised(text: str, seed: int = 0, fixed: frozenset = frozenset()):
    """A structure's trajectory, from the text of its file (PDB or mmCIF), ``seed`` and
    the residues held (``fixed``: (chain, number, name) keys): ``.text(noise)`` is the
    file at that noise."""

    digest = hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()
    key = (digest, int(seed), fixed)
    with _LOCK:
        found = _KEPT_NOISED.get(key)
        if found is not None:
            _KEPT_NOISED.move_to_end(key)
            return found
        molecule = _KEPT_MOLECULES.get(digest)
    if molecule is None:
        molecule = _Molecule(text)
    result = _Noised(molecule, digest, int(seed), fixed)
    with _LOCK:
        _KEPT_MOLECULES[digest] = molecule
        while len(_KEPT_MOLECULES) > 4:
            _KEPT_MOLECULES.popitem(last=False)
        _KEPT_NOISED[key] = result
        while len(_KEPT_NOISED) > 8:
            _KEPT_NOISED.popitem(last=False)
    return result


# -- drawn by mol-sketch ------------------------------------------------------------------


def fixed_residues(source: str, stamp: float, selection: str) -> frozenset:
    """The residues a ``fixed`` selection holds, as (chain, number, name): every one with an
    atom it selects, as mol-sketch reads the selection (a _BadSelection where it can't)."""

    from flexo.structures import _atoms, _selection

    if not selection.strip() or selection.strip().lower() == "none":
        return frozenset()
    test = _selection(selection)
    return frozenset(
        (atom.chain, atom.resi, atom.resn) for atom in _atoms(source, stamp) if test(atom)
    )


@dataclass(frozen=True, slots=True)
class Drawn:
    """A structure noised, read into mol-sketch: its ``figure``, and ``turn``, which takes
    a point of mol-sketch's scene for it to the scene of the file (mol-sketch turns each
    molecule it reads to its own principal axes: the noised one would be seen from
    elsewhere than the file, but for this)."""

    figure: object
    turn: tuple

    def view(self, yaw: float, pitch: float, roll: float) -> dict[str, float]:
        """The turn to draw the noised molecule at for it to be seen as the file is at
        ``yaw``, ``pitch`` and ``roll``."""

        np = _numpy()
        wanted = _camera(yaw, pitch, roll) @ np.array(self.turn)
        pitched = math.degrees(math.asin(max(-1.0, min(1.0, float(wanted[2, 1])))))
        if abs(wanted[2, 1]) < 1 - 1e-9:
            turned = math.degrees(math.atan2(-wanted[2, 0], wanted[2, 2]))
            rolled = math.degrees(math.atan2(-wanted[0, 1], wanted[1, 1]))
        else:  # (Looking straight down: the yaw and the roll are one turn.)
            turned = 0.0
            rolled = math.degrees(math.atan2(wanted[1, 0], wanted[0, 0]))
        return {"yaw": turned, "pitch": pitched, "roll": rolled}

    def in_file_frame(self, point):
        """A point of the noised molecule's scene, in the file's."""

        np = _numpy()
        return (np.array(self.turn) @ np.asarray(point, dtype=np.float64)).tolist()

    def as_seen(self, shown: dict, view: dict) -> dict:
        """What the studio draws while the noised structure is dragged round
        (``structures._view``), as the file is seen: every point in the file's scene, the
        turn the structure's own."""

        def turned(points):
            return [[round(value, 2) for value in self.in_file_frame(point)] for point in points]

        out = dict(shown)
        out["camera"] = {
            **shown["camera"],
            **{name: float(view.get(name, 0.0)) for name in ("yaw", "pitch", "roll")},
        }
        out["centre"] = [round(value, 3) for value in self.in_file_frame(shown["centre"])]
        out["fit"] = turned(shown["fit"])
        out["chains"] = [turned(chain) for chain in shown["chains"]]
        out["atoms"] = [[*turned([atom[:3]])[0], *atom[3:]] for atom in shown["atoms"]]
        return out


def _camera(yaw: float, pitch: float, roll: float):
    """mol-sketch's turn of a scene for its camera: about y by the yaw, x by the pitch,
    then z by the roll."""

    np = _numpy()
    a, b, c = (math.radians(value) for value in (yaw, pitch, roll))
    turn_y = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    turn_x = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    turn_z = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return turn_z @ turn_x @ turn_y


_DRAWN: OrderedDict[tuple, Drawn] = OrderedDict()
_BASES: dict[str, object] = {}

DRAWN_KEPT = 12
"""Noised molecules kept read into mol-sketch; the least recently drawn are let go."""


def _base(figure):
    """The turn mol-sketch gives a molecule it reads (its principal axes), as a 3 by 3."""

    np = _numpy()
    from molsketch._engine import engine

    found = _BASES.get(figure._ref)
    if found is None:
        base = engine().call("engineConfig", figure._spec())["camera"]["base"]
        found = _BASES[figure._ref] = np.array(base, dtype=np.float64).reshape(4, 4)[:3, :3].T
    return found


def drawn(loaded, noise: float, seed: int, fixed: frozenset) -> Drawn:
    """The molecule mol-sketch has read (``loaded``) at ``noise``, read into mol-sketch in
    its turn (a scene, a ValueError: only a structure read from its coordinates is
    noised). The caller holds mol-sketch (structures._one_at_a_time)."""

    import molsketch as ms
    from molsketch._engine import engine

    source = getattr(loaded, "_input", None) or {}
    if "text" not in source:
        raise ValueError("Only a structure read from its coordinates can be noised.")
    key = (loaded._ref, round(float(noise), 6), int(seed), fixed)
    found = _DRAWN.get(key)
    if found is not None:
        _DRAWN.move_to_end(key)
        return found
    trajectory = noised(source["text"], seed, fixed)
    text = trajectory.text(noise)
    figure = ms.load(text, name=loaded.name, format="cif" if trajectory.molecule.cif else "pdb")
    turn = _base(loaded) @ _base(figure).T
    found = _DRAWN[key] = Drawn(figure, tuple(map(tuple, turn.tolist())))
    while len(_DRAWN) > DRAWN_KEPT:
        _, old = _DRAWN.popitem(last=False)
        _BASES.pop(old.figure._ref, None)
        # (An engine since let go holds nothing to let go of.)
        with contextlib.suppress(Exception):
            engine().call("drop", old.figure._ref)
    return found


def forget() -> None:
    """Every noised molecule let go of (mol-sketch's engine was, so they are not in it)."""

    _DRAWN.clear()
    _BASES.clear()
