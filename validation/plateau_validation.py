"""
plateau_validition.py — Validation of the "Ortayı Al" (plateau) step in flagging.py

Question: which samples actually enter the reported numbers?
  plateau_rms_uv (MVC denominator candidate), kok_uv (%MVC numerator),
  pencere_bas_s / pencere_son_s, kok_yuzde_mik.

How: synthetic pipeline CSVs with known content are opened in the real GUI
(flagging.BayraklamaPenceresi). "Ortayı Al" and "Kaydet" run exactly as a
user would trigger them; dialogs are answered automatically. The saved
markers.json / _oznicelikler.csv / _mvc_ref.json are then checked against an
independent re-implementation that:
  * reads the CSV with its own parser (not loader.py),
  * selects samples with np.searchsorted (not boolean time masks),
  * trims the plateau with integer arithmetic k = (n + 2) // 5,
    which equals int(round(n * 0.20)) for every integer n (checked below;
    n * 0.20 can never be exactly x.5, so round-half-to-even never applies),
  * uses closed-form ground truth where possible (ramp: sum of squares;
    square wave: RMS = amplitude).

Acceptance (validation plan, section 4): window position 0 samples off;
KOK / %MVC bit-identical to the independent computation (and within 1e-12
relative of the analytic value).

Tests
  A  Ramp x[i] = i: flag edges between samples and on samples, a flag that
     crosses the crop start, a short flag (< ~1.67 s, plateau < 1 s),
     Raw vs Envelope 200 ms view.
  B  Stepped amplitude (0.5 s slices, square wave, RMS 10, 20, 30 ... µV).
  D  Save consistency: kok_uv == plateau_rms_uv, window columns == plateau;
     bayrak_kok_uv = RMS of the whole flag (flag ∩ crop), with or without
     a plateau (column added 2026-10-05).
     Known gap (documented, not a failure): crop narrowed after Ortayı Al.
  E  %MVC with a known MVC file (3 trials) and a known task file, for
     both aggregations ("En Yüksek", "Ortalama"); meta fields.

Run from the repository root (needs a display; on a headless machine use
`xvfb-run -a python validation/ortayi_al_dogrulama.py`):
    python validation/ortayi_al_dogrulama.py
Exit code 0 = all checks passed.
"""
import json
import math
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flagging as F  # noqa: E402

FS = 2148.1481481481483          # Delsys Trigno EMG rate
T0_SAMPLE = 859                  # first sample after the 400 ms edge trim

# ---------------------------------------------------------------- reporting
FAILED = []


def check(name, ok, detail=""):
    if not ok:
        FAILED.append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def note(text):
    print(f"[NOTE] {text}")


# ------------------------------------------------- dialogs answered by script
LOG = []          # (kind, title, message)
ANSWERS = []      # queued answers for yes/no dialogs; default yes


def _ask(cls, parent, title, msg):
    LOG.append(("ask", title, msg))
    return ANSWERS.pop(0) if ANSWERS else True


F._DarkDialog.hata = classmethod(lambda c, p, t, m: LOG.append(("error", t, m)))
F._DarkDialog.bilgi = classmethod(lambda c, p, t, m: LOG.append(("info", t, m)))
F._DarkDialog.evet_hayir = classmethod(_ask)
_NEXT_FILE = []
F.filedialog.askopenfilename = lambda **kw: _NEXT_FILE.pop(0)

# ------------------------------------------------------------ synthetic data
WORK = tempfile.mkdtemp(prefix="ortayi_al_")


def time_axis(seconds):
    n = int(round(seconds * FS))
    return (np.arange(n) + T0_SAMPLE) / FS


def write_csv(name, t, channels):
    """Pipeline CSV as utils._csv_yaz writes it (repr = lossless)."""
    path = os.path.join(WORK, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("zaman_s\t" + "\t".join(channels) + "\n")
        f.write(f"# fs={FS}  birim=uV  adim=son\n")
        for i in range(len(t)):
            f.write("\t".join([repr(float(t[i]))]
                              + [repr(float(x[i])) for x in channels.values()]) + "\n")
    return path


def read_csv(path):
    """Independent reader (does not use loader.py)."""
    with open(path, encoding="utf-8") as f:
        names = f.readline().rstrip("\n").split("\t")[1:]
        f.readline()
        data = np.array([[float(c) for c in line.rstrip("\n").split("\t")]
                         for line in f if line.strip()])
    return data[:, 0], {n: data[:, j + 1] for j, n in enumerate(names)}


def square(t, amp):
    """±amp alternating each sample: x**2 == amp**2 exactly, RMS == amp."""
    return amp * np.where(np.arange(len(t)) % 2 == 0, 1.0, -1.0)


# ---------------------------------------------------- independent reference
def ref_window(t, start, end, crop0, crop1, trim=True):
    """First/last sample index (inclusive) of (flag ∩ crop), then the
    fixed-20 % plateau. Uses searchsorted + integer arithmetic only."""
    a, b = max(start, crop0), min(end, crop1)
    first = int(np.searchsorted(t, a, side="left"))
    last = int(np.searchsorted(t, b, side="right")) - 1
    if not trim:
        return first, last
    n = last - first + 1
    k = (n + 2) // 5
    return first + k, last - k


def rms(x):
    return float(np.sqrt(np.mean(x ** 2)))       # same formula as features/flagging


def read_features_csv(path):
    with open(path, encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t")
        rows = [dict(zip(head, line.rstrip("\n").split("\t"))) for line in f if line.strip()]
    return {(r["kanal"], r["etiket"]): r for r in rows}


# ------------------------------------------------------------------ GUI ops
_WINDOW = []


def open_window(path):
    """One GUI window for the whole run; files are opened through the same
    path a user takes (_dosya_yukle). Stale sidecar files are removed first."""
    for suffix in ("_markers.json", "_oznicelikler.csv", "_mvc_ref.json"):
        p = os.path.splitext(path)[0] + suffix
        if os.path.exists(p):
            os.remove(p)
    if not _WINDOW:
        _WINDOW.append(F.BayraklamaPenceresi(path))
    else:
        _WINDOW[0]._dosya_yukle(path)
    w = _WINDOW[0]
    w.update()
    return w


def set_crop(w, a, b):
    w.kirp_bas_giris.delete(0, "end"); w.kirp_bas_giris.insert(0, repr(a))
    w.kirp_son_giris.delete(0, "end"); w.kirp_son_giris.insert(0, repr(b))
    w._kirpma_uygula()


def set_view(w, window_ms):
    w.yumus_pencere_giris.delete(0, "end")
    if window_ms is not None:
        w.yumus_pencere_giris.insert(0, str(window_ms))
    w._yumus_uygula()


def flag(name, start, end):
    return {"event_name": name, "start_s": start, "end_s": end,
            "type": "event", "source": "manual"}


def run_ortayi_al(w):
    for flags in w.bayraklar.values():
        for b in flags:
            for field in F.PLATO_ALANLARI:
                b.pop(field, None)
    w.secili = None
    w.plato_yontem_sec.set("Sabit")
    w.plato_oran_giris.delete(0, "end")
    n0 = len(LOG)
    w._ortayi_isaretle()
    return [m for kind, title, m in LOG[n0:] if title == "Ortayı Al — Uyarılar"]


# ======================================================================
print("Rounding rule: int(round(n*0.20)) == (n+2)//5")
bad = [n for n in range(1, 2_000_001) if int(round(n * 0.20)) != (n + 2) // 5]
check("identical for n = 1 … 2,000,000 (≈ 15.5 min at 2148 Hz)", not bad, f"{len(bad)} differ")

# ======================================================================
print("\nA  Ramp x[i] = i")
t = time_axis(30.0)
ramp = np.arange(len(t), dtype=float)
CH = "Ramp (1)"
path_a = write_csv("ramp.csv", t, {CH: ramp})
t_r, ch_r = read_csv(path_a)
check("independent reader: CSV round-trip is lossless",
      np.array_equal(t_r, t) and np.array_equal(ch_r[CH], ramp))

w = open_window(path_a)
check("GUI loaded the same time axis", np.array_equal(w.kayit.time, t_r))
crop0, crop1 = 10.0, 29.0
set_crop(w, crop0, crop1)
c0, c1 = w.crop_start_s, w.crop_end_s
check("crop applied as typed", (c0, c1) == (crop0, crop1), f"{c0}–{c1}")

k_on1, k_on2 = 30000, 40000                        # flag edges ON samples
flags_a = {
    "A1 between samples": (15.00031, 19.00077),
    "A2 on samples": (float(t[k_on1]), float(t[k_on2])),
    "A3 crosses crop start": (9.5, 14.5),           # as in an old markers file
    "A4 short 1.5 s": (20.0, 21.5),
    "A5 long": (22.0, 28.0),
}
w.bayraklar[CH] = [flag(n, s, e) for n, (s, e) in flags_a.items()]
warnings = run_ortayi_al(w)
by_name = {b["event_name"]: b for b in w.bayraklar[CH]}

for name, (s, e) in flags_a.items():
    b = by_name[name]
    if name.startswith("A4"):
        continue
    i0, i1 = ref_window(t_r, s, e, c0, c1)
    got0 = int(np.searchsorted(t_r, b["plateau_start_s"]))
    got1 = int(np.searchsorted(t_r, b["plateau_end_s"]))
    exact_times = (b["plateau_start_s"] == t_r[got0]) and (b["plateau_end_s"] == t_r[got1])
    check(f"{name}: plateau = samples {i0}–{i1}",
          exact_times and (got0, got1) == (i0, i1),
          f"GUI {got0}–{got1}, offset {got0 - i0:+d}/{got1 - i1:+d} samples")
    s2 = (i1 * (i1 + 1) * (2 * i1 + 1) - (i0 - 1) * i0 * (2 * i0 - 1)) // 6
    analytic = math.sqrt(s2 / (i1 - i0 + 1))
    check(f"{name}: plateau_rms_uv bit-identical to reference, |rel| < 1e-12 vs closed form",
          b["plateau_rms_uv"] == rms(ch_r[CH][i0:i1 + 1])
          and abs(b["plateau_rms_uv"] / analytic - 1) < 1e-12,
          f"{b['plateau_rms_uv']!r} vs {analytic!r}")

f2, l2 = ref_window(t_r, *flags_a["A2 on samples"], c0, c1, trim=False)
check("A2: both flag edges included (on-sample edges are inside)",
      (f2, l2) == (k_on1, k_on2), f"{f2}–{l2}")
f3, _ = ref_window(t_r, *flags_a["A3 crosses crop start"], c0, c1, trim=False)
check("A3: plateau is 20 % of (flag ∩ crop), not of the flag",
      by_name["A3 crosses crop start"]["plateau_start_s"] > c0
      and t_r[f3] >= c0 and t_r[f3 - 1] < c0)
a4 = by_name["A4 short 1.5 s"]
check("A4: no plateau, user warned (plateau < min 1 s)",
      "plateau_start_s" not in a4 and any("A4" in m for m in warnings),
      next((m.splitlines()[-1] for m in warnings if "A4" in m), "no warning"))
note("A flag shorter than ~1/0.6 = 1.67 s gets no plateau; it is then "
     "missing from the MVC trial list (see E).")

ham = {n: {f: by_name[n].get(f) for f in F.PLATO_ALANLARI} for n in by_name}
set_view(w, 200)
run_ortayi_al(w)
zarf = {b["event_name"]: {f: b.get(f) for f in F.PLATO_ALANLARI} for b in w.bayraklar[CH]}
check("Raw vs Envelope 200 ms: all plateau fields bit-identical", ham == zarf)
set_view(w, None)
run_ortayi_al(w)

# ======================================================================
print("\nD  Save consistency (ramp file)")
w._kaydet()
rows = read_features_csv(os.path.join(WORK, "ramp_oznicelikler.csv"))
markers = json.load(open(os.path.join(WORK, "ramp_markers.json"), encoding="utf-8"))
saved = {b["event_name"]: b for b in markers["channels"][CH]}
for name, (s, e) in flags_a.items():
    r = rows[(CH, name)]
    if name.startswith("A4"):
        f0, f1 = ref_window(t_r, s, e, c0, c1, trim=False)
        check(f"{name}: window = whole flag, KOK over it",
              r["pencere"] == "tam" and r["plato_bas_s"] == ""
              and float(r["pencere_bas_s"]) == t_r[f0] and float(r["pencere_son_s"]) == t_r[f1]
              and float(r["kok_uv"]) == rms(ch_r[CH][f0:f1 + 1]))
        check(f"{name}: no plateau -> bayrak_kok_uv == kok_uv (bit-identical)",
              r["bayrak_kok_uv"] == r["kok_uv"] != "")
        continue
    b = saved[name]
    check(f"{name}: markers.json == memory, CSV kok_uv == plato_kok_uv == plateau_rms_uv, "
          "window == plateau",
          b == by_name[name] and r["pencere"] == "plato"
          and float(r["kok_uv"]) == float(r["plato_kok_uv"]) == b["plateau_rms_uv"]
          and float(r["pencere_bas_s"]) == b["plateau_start_s"]
          and float(r["pencere_son_s"]) == b["plateau_end_s"])
    f0, f1 = ref_window(t_r, s, e, c0, c1, trim=False)
    full = rms(ch_r[CH][f0:f1 + 1])
    s2 = (f1 * (f1 + 1) * (2 * f1 + 1) - (f0 - 1) * f0 * (2 * f0 - 1)) // 6
    check(f"{name}: bayrak_kok_uv = RMS of samples {f0}–{f1} (flag ∩ crop), "
          "not the plateau",
          float(r["bayrak_kok_uv"]) == full != float(r["kok_uv"])
          and abs(full / math.sqrt(s2 / (f1 - f0 + 1)) - 1) < 1e-12,
          f"{full:.3f} vs plateau {float(r['kok_uv']):.3f}")

b1 = by_name["A1 between samples"]
mid = (b1["plateau_start_s"] + b1["plateau_end_s"]) / 2
ANSWERS.append(True)                      # "flags outside the crop — apply anyway?"
set_crop(w, mid, c1)
w._kaydet()
r = read_features_csv(os.path.join(WORK, "ramp_oznicelikler.csv"))[(CH, "A1 between samples")]
gap = float(r["kok_uv"]) / float(r["plato_kok_uv"]) - 1
note(f"Known gap (documented 2026-10-04): crop narrowed into the plateau after "
     f"Ortayı Al -> kok_uv differs from plato_kok_uv by {gap * 100:+.1f} %; "
     f"pencere_bas_s = {float(r['pencere_bas_s']):.4f} ≥ crop {mid:.4f}: "
     f"{float(r['pencere_bas_s']) >= mid}. Procedure: re-run Ortayı Al.")

# ======================================================================
print("\nB  Stepped amplitude (0.5 s slices, RMS 10, 20, 30 … µV)")
t = time_axis(12.0)
slice_amp = 10.0 * (np.floor((t - t[0]) / 0.5) + 1)
x = slice_amp * np.where(np.arange(len(t)) % 2 == 0, 1.0, -1.0)
CH = "Steps (1)"
path_b = write_csv("steps.csv", t, {CH: x})
t_r, ch_r = read_csv(path_b)
w = open_window(path_b)
w.bayraklar[CH] = [flag("B1", 3.1, 7.3)]
run_ortayi_al(w)
b = w.bayraklar[CH][0]
i0, i1 = ref_window(t_r, 3.1, 7.3, w.crop_start_s, w.crop_end_s)
amps, counts = np.unique(slice_amp[i0:i1 + 1], return_counts=True)
analytic = math.sqrt(float(np.sum(amps ** 2 * counts)) / counts.sum())
check("B1: plateau KOK = closed form from slice counts",
      b["plateau_rms_uv"] == rms(ch_r[CH][i0:i1 + 1])
      and abs(b["plateau_rms_uv"] / analytic - 1) < 1e-12,
      f"{b['plateau_rms_uv']:.6f} µV, slices {amps.min():.0f}–{amps.max():.0f} µV")
note(f"B1 for the eye: plateau {b['plateau_start_s']:.3f}–{b['plateau_end_s']:.3f} s "
     f"(flag 3.1–7.3 s); the plateau band should start/end inside the "
     f"{slice_amp[i0]:.0f} and {slice_amp[i1]:.0f} µV slices.")

# ======================================================================
print("\nE  %MVC with known MVC and task files")
t = time_axis(30.0)
CH = "Muscle (1)"
mvc_trials = {"MVC1": (5.0, 9.0, 100.0), "MVC2": (13.0, 17.0, 120.0),
              "MVC3": (21.0, 25.0, 110.0), "MVC4 short": (27.0, 28.5, 500.0)}
amp = np.full(len(t), 5.0)
for s, e, a in mvc_trials.values():
    amp[(t >= s) & (t <= e)] = a
path_m = write_csv("mvc.csv", t, {CH: amp * np.where(np.arange(len(t)) % 2 == 0, 1.0, -1.0)})
w = open_window(path_m)
w.bayraklar[CH] = [flag(n, s, e) for n, (s, e, _) in mvc_trials.items()]
run_ortayi_al(w)
w._kaydet()
mvc_ref = json.load(open(os.path.join(WORK, "mvc_mvc_ref.json"), encoding="utf-8"))
got = [(d["bayrak"], d["rms_uv"]) for d in mvc_ref[CH]["denemeler"]]
check("MVC file: trials hold exactly the known RMS (100, 120, 110 µV)",
      got == [("MVC1", 100.0), ("MVC2", 120.0), ("MVC3", 110.0)], str(got))
check("MVC file: the short trial (1.5 s, 500 µV) is NOT in the list",
      all(n != "MVC4 short" for n, _ in got))
note("If the short trial were the true maximum, 'En Yüksek' would silently "
     "use the next one; only the Ortayı Al warning tells the user.")

task = {"T1": (8.0, 12.0, 30.0), "T2": (18.0, 22.0, 60.0)}
amp = np.full(len(t), 5.0)
for s, e, a in task.values():
    amp[(t >= s) & (t <= e)] = a
path_t = write_csv("task.csv", t, {CH: amp * np.where(np.arange(len(t)) % 2 == 0, 1.0, -1.0)})
w = open_window(path_t)
w.bayraklar[CH] = [flag(n, s, e) for n, (s, e, _) in task.items()]
run_ortayi_al(w)
_NEXT_FILE.append(os.path.join(WORK, "mvc_mvc_ref.json"))
w._mvc_ref_yukle()
for agg, ref in (("En Yüksek", 120.0), ("Ortalama", 110.0)):
    w.mvc_toplama_sec.set(agg)
    w._mvc_toplama_degisti(agg)
    w._kaydet()
    rows = read_features_csv(os.path.join(WORK, "task_oznicelikler.csv"))
    meta = json.load(open(os.path.join(WORK, "task_markers.json"), encoding="utf-8"))["meta"]
    for name, (_, _, a) in task.items():
        r = rows[(CH, name)]
        pct = float(r["kok_yuzde_mik"])
        check(f"{agg}: {name} %MVC = {a:g}/{ref:g}×100",
              float(r["kok_uv"]) == a and float(r["mik_ref_uv"]) == ref
              and pct == a / ref * 100 and abs(pct / (a / ref * 100) - 1) < 1e-12,
              f"{pct!r}")
    check(f"{agg}: meta.mvc_ref_file and meta.mvc_aggregation recorded",
          meta.get("mvc_ref_file") == "mvc_mvc_ref.json"
          and meta.get("mvc_aggregation") is not None,
          f"{meta.get('mvc_ref_file')}, {meta.get('mvc_aggregation')}")

# ======================================================================
unexpected = [(t_, m.splitlines()[0]) for k, t_, m in LOG if k == "error"]
check("no unexpected error dialogs", not unexpected, str(unexpected[:3]))
_WINDOW[0].destroy()
print(f"\nWork files: {WORK}")
print("RESULT:", "all checks passed" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
