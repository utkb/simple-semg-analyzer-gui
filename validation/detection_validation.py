"""
detection_validation.py — validation of detection.zaman_pencerelerini_bul()

Checks (2026-10-05):
  1. Known cases on square waves: window = first..last suprathreshold sample,
     0-sample error; regions touching the array ends are kept; a fully active
     array returns one window; nothing active returns [].
  2. Gap tolerance (Lidierth 1986, t3): gaps shorter than round(t3*fs) samples
     are bridged, longer ones split; t3 = 0 never bridges.
  3. Minimum duration counts samples inclusively (son - bas + 1).
  4. Invalid parameters (negative, NaN, inf) raise ValueError.
  5. Random binary-ish signals: result equals an independent, sample-by-sample
     reference implementation (state machine written from the paper's wording).

Run from the project root:  python validation/tespit_dogrulama.py
Exit code 0 = all checks passed.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from detection import zaman_pencerelerini_bul as detect  # noqa: E402

THR = 5.0
failures = []
n_checks = 0


def check(name, ok, detail=""):
    global n_checks
    n_checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def square(n, spans):
    x = np.zeros(n)
    for a, b in spans:          # b exclusive
        x[a:b] = 10.0
    return x


def win(res):
    return [(p["bas_idx"], p["son_idx"]) for p in res]


def reference(x, fs, thr, gap_s, min_s):
    """Sample-by-sample reference, independent of the vectorised code."""
    gap_n = int(round(gap_s * fs))
    min_n = int(round(min_s * fs))
    active = [abs(v) > thr for v in x]
    out, start, last, below = [], None, None, 0
    for i, a in enumerate(active):
        if a:
            if start is None:
                start = i
            last, below = i, 0
        elif start is not None:
            below += 1
            if below >= gap_n:          # gap long enough: burst ended at `last`
                out.append((start, last))
                start, below = None, 0
    if start is not None:
        out.append((start, last))
    return [w for w in out if min_n <= 0 or (w[1] - w[0] + 1) >= min_n]


for FS in (2148.1481, 1259.2593):
    print(f"\nfs = {FS} Hz")
    N = int(round(0.05 * FS))

    print(" 1. known cases")
    check("single burst -> exact bounds",
          win(detect(square(20000, [(5000, 7000)]), FS, THR)) == [(5000, 6999)])
    check("burst at array start kept",
          win(detect(square(20000, [(0, 2000), (5000, 7000)]), FS, THR))
          == [(0, 1999), (5000, 6999)])
    check("burst at array end kept",
          win(detect(square(20000, [(5000, 7000), (18000, 20000)]), FS, THR))
          == [(5000, 6999), (18000, 19999)])
    check("only burst, at start",
          win(detect(square(20000, [(0, 2000)]), FS, THR)) == [(0, 1999)])
    check("fully active array -> one window",
          win(detect(np.full(20000, 10.0), FS, THR)) == [(0, 19999)])
    check("nothing active -> []", detect(np.zeros(20000), FS, THR) == [])
    check("single active sample",
          win(detect(square(100, [(50, 51)]), FS, THR)) == [(50, 50)])
    check("negative values use |x|",
          win(detect(-square(20000, [(5000, 7000)]), FS, THR)) == [(5000, 6999)])

    print(" 2. gap tolerance (t3 = 0.05 s -> %d samples)" % N)
    for g, expect in ((N - 1, 1), (N, 2)):
        r = detect(square(20000, [(5000, 7000), (7000 + g, 9000)]), FS, THR)
        check(f"gap {g} samples -> {expect} window(s)", len(r) == expect, win(r))
    r = detect(square(20000, [(5000, 7000), (7000 + N - 1, 9000)]), FS, THR)
    check("bridged window keeps outer bounds",
          win(r) == [(5000, 8999)], win(r))
    r = detect(square(20000, [(5000, 7000), (7001, 9000)]), FS, THR, kesinti_payi_s=0)
    check("t3 = 0 -> a 1-sample gap splits", len(r) == 2, win(r))

    print(" 3. minimum duration (inclusive count)")
    m = int(round(1.0 * FS))
    check(f"burst of {m} samples, min 1 s -> kept",
          len(detect(square(20000, [(5000, 5000 + m)]), FS, THR, min_sure_s=1.0)) == 1)
    check(f"burst of {m - 1} samples, min 1 s -> dropped",
          len(detect(square(20000, [(5000, 5000 + m - 1)]), FS, THR, min_sure_s=1.0)) == 0)

    print(" 4. invalid parameters")
    for kw in ({"kesinti_payi_s": -1}, {"kesinti_payi_s": float("nan")},
               {"kesinti_payi_s": float("inf")}, {"min_sure_s": -0.1},
               {"min_sure_s": float("nan")}):
        try:
            detect(square(1000, [(10, 20)]), FS, THR, **kw)
            check(f"{kw} raises", False, "no error")
        except ValueError:
            check(f"{kw} raises", True)

    print(" 5. random signals vs reference")
    rng = np.random.default_rng(42)
    bad = 0
    for trial in range(300):
        n = int(rng.integers(50, 3000))
        # bursty signal: random runs above/below threshold
        x = np.zeros(n)
        i = 0
        while i < n:
            length = int(rng.integers(1, 3 * N))
            if rng.random() < 0.5:
                x[i:i + length] = rng.uniform(5.1, 20, size=min(length, n - i))
            i += length
        gap_s = float(rng.choice([0.0, 0.002, 0.02, 0.05, 0.1]))
        min_s = float(rng.choice([0.0, 0.01, 0.05, 0.3]))
        if win(detect(x, FS, THR, gap_s, min_s)) != reference(x, FS, THR, gap_s, min_s):
            bad += 1
    check("300 random signals match reference", bad == 0, f"{bad} mismatches")

print(f"\n{n_checks - len(failures)}/{n_checks} checks passed")
sys.exit(1 if failures else 0)
