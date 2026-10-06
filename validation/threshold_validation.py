"""
threshold_validition.py — validation of the threshold functions in detection.py

Question asked: does each function compute what its docstring says?
(Whether the threshold is *appropriate* for a recording is judged by eye
in the GUI and is out of scope here.)

  1. mad_esik      — equals median + k * scipy MAD(scale='normal');
                     on Gaussian noise approximates mean + k*SD.
  2. otsu_esik     — compared with an independent vectorised NumPy
                     implementation of Otsu's criterion (256 bins);
                     on bimodal mixtures lies between the modes.
  3. baseline_esik — equals mean + k*SD(ddof=1) of the first int(N*fs)
                     samples; samples after the baseline have no effect;
                     invalid durations / k raise ValueError.

Independent references: SciPy and a short NumPy Otsu written here
(SciPy has no Otsu function; scikit-image is deliberately not required),
not detection.py code.
Run from the project root:  python validation/esik_dogrulama.py
Exit code 0 = all checks passed.
"""
import os
import sys

import numpy as np
from scipy.stats import median_abs_deviation

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from detection import mad_esik, otsu_esik, baseline_esik  # noqa: E402

FS = 2148.1481
rng = np.random.default_rng(7)
failures, n_checks = [], 0


def check(name, ok, detail=""):
    global n_checks
    n_checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def otsu_referans(x, nbins=256):
    """Otsu by the textbook definition, vectorised over all candidate splits.

    Split t puts histogram bins 0..t in class 0. Between-class variance
    w0*w1*(m0-m1)^2; first maximum wins. Returns the centre of bin t
    (the usual convention); detection.otsu_esik returns the left edge.
    """
    hist, edges = np.histogram(x, bins=nbins)
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist).astype(float)
    w1 = hist.sum() - w0
    s0 = np.cumsum(hist * centres)
    ok = (w0 > 0) & (w1 > 0)
    m0 = np.where(ok, s0 / np.where(ok, w0, 1), 0.0)
    m1 = np.where(ok, (s0[-1] - s0) / np.where(ok, w1, 1), 0.0)
    var = np.where(ok, w0 * w1 * (m0 - m1) ** 2, -1.0)
    t = int(np.argmax(var))
    return float(centres[t]), float(edges[1] - edges[0])


def raises(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


# ---------------------------------------------------------------- MAD
print("1. mad_esik")
for k in (0.0, 1.0, 3.0, 5.0):
    x = rng.normal(10, 2, 200_000)
    ref = np.median(x) + k * median_abs_deviation(x, scale="normal")
    got = mad_esik(x, k)
    check(f"k={k}: equals SciPy reference", abs(got - ref) < 1e-6 * max(1, abs(ref)),
          f"{got:.6f} vs {ref:.6f}")
x = rng.normal(10, 2, 1_000_000)
got = mad_esik(x, 3)
check("Gaussian(10, 2), k=3 -> ~16 (mean + 3 SD)", abs(got - 16) < 0.05, f"{got:.3f}")
check("k < 0 raises", raises(lambda: mad_esik(x, -1)))
check("NaN in input -> NaN threshold (documented below)",
      np.isnan(mad_esik(np.array([1.0, np.nan, 3.0]), 3)))

# ---------------------------------------------------------------- Otsu
print("2. otsu_esik")
for lo, hi, w in ((5, 100, 0.5), (5, 100, 0.8), (2, 30, 0.6)):
    x = np.concatenate((rng.normal(lo, lo * 0.2, int(200_000 * w)),
                        rng.normal(hi, hi * 0.1, int(200_000 * (1 - w)))))
    got = otsu_esik(x)
    ref, bin_w = otsu_referans(x)
    diff_bins = (got - ref) / bin_w
    check(f"modes {lo}/{hi}, rest share {w:.0%}: equals reference minus half a bin",
          abs(diff_bins + 0.5) < 1e-6, f"{got:.2f} vs {ref:.2f} ({diff_bins:+.2f} bins)")
    check(f"modes {lo}/{hi}: threshold between the modes", lo < got < hi, f"{got:.2f}")
# Fully separated modes: every threshold in the empty gap splits the classes
# identically, so Otsu's criterion is flat there. Both implementations take
# the first maximum, i.e. just above the upper end of the low (rest) mode —
# not the visual middle of the gap. (A first version of this script expected
# ~30; that expectation was wrong, the reference gives the same ~14.)
x = np.concatenate((rng.normal(10, 1, 100_000), rng.normal(50, 1, 100_000)))
got = otsu_esik(x)
ref, bin_w = otsu_referans(x)
top_low = x[x < 30].max()
check("separated modes 10/50: equals reference minus half a bin",
      abs(got - ref + bin_w / 2) < 1e-6, f"{got:.2f} vs {ref:.2f}")
check("separated modes 10/50: at the top of the low mode, not mid-gap",
      abs(got - top_low) <= 2 * bin_w, f"{got:.2f}, low mode max {top_low:.2f}")

# ---------------------------------------------------------------- Baseline
print("3. baseline_esik")
x = np.concatenate((rng.normal(5, 1, int(10 * FS)), rng.normal(200, 50, int(20 * FS))))
for N, k in ((5.0, 3.0), (2.5, 1.0), (5.0, 0.0), (10.0, 2.0)):
    n = int(N * FS)
    ref = np.mean(x[:n]) + k * np.std(x[:n], ddof=1)
    got = baseline_esik(x, FS, N, k)
    check(f"N={N}s k={k}: equals mean + k*SD(ddof=1)", abs(got - ref) < 1e-9, f"{got:.6f}")
y = x.copy()
y[int(5 * FS):] = 1e6
check("samples after the baseline have no effect",
      baseline_esik(y, FS, 5.0, 3.0) == baseline_esik(x, FS, 5.0, 3.0))
check("baseline longer than array raises", raises(lambda: baseline_esik(x, FS, 31.0, 3)))
check("baseline of 0 s raises", raises(lambda: baseline_esik(x, FS, 0.0, 3)))
check("baseline of 1 sample raises", raises(lambda: baseline_esik(x, FS, 1.5 / FS, 3)))
check("negative baseline raises", raises(lambda: baseline_esik(x, FS, -1.0, 3)))
check("NaN baseline raises", raises(lambda: baseline_esik(x, FS, float("nan"), 3)))
check("k < 0 raises", raises(lambda: baseline_esik(x, FS, 5.0, -1)))

print(f"\n{n_checks - len(failures)}/{n_checks} checks passed")
sys.exit(1 if failures else 0)
