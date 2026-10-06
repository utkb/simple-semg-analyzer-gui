"""
reproduce_session.py — reproduce a saved flagging session from its files

Given the processed CSV, its _markers.json and _oznicelikler.csv, this script
re-derives, independently of flagging.py:

  1. the envelope (moving RMS, `smoothing_ms`, shrinking edges) and the
     Öner threshold from meta.detection (method, k, baseline_s);
  2. the detected flags from meta.detection (threshold, gap tolerance,
     minimum duration) -> every stored "detected" flag must match a
     recomputed window to 0 samples. Recomputed windows with no stored
     flag are listed, not failed: a detected flag deleted by eye leaves no
     trace in markers.json.
     Detection runs on meta.detection[ch].source_channel ("apply to all
     channels" copies the source channel's flags; its threshold is a
     statistic of the source channel, not of ch).
  3. the inferred phases via protocol.fazlari_coz() -> must match the
     "inferred" flags (needs the protocol JSON; skipped if not given);
  4. the RMS of every row in _oznicelikler.csv over its window
     (pencere_bas_s..pencere_son_s) on the processed signal.

Envelope rule assumed here: n = round(smoothing_ms * fs / 1000) samples,
centred, divided by the number of samples actually inside the array
(MATLAB movmean "shrink"). If check 1/2 fails only on threshold/edges,
compare this rule with pipeline.rms_hesapla().

Usage (from the project root):
  python validation/reproduce_records.py <processed.csv> <_markers.json> \
         <_oznicelikler.csv> [protocol.json]
Exit code 0 = all checks passed.
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from loader import load_csv_otomatik                              # noqa: E402
from detection import (mad_esik, otsu_esik, baseline_esik,         # noqa: E402
                       zaman_pencerelerini_bul)
from protocol import fazlari_coz                                  # noqa: E402

failures, n_checks = [], 0


def check(name, ok, detail=""):
    global n_checks
    n_checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def envelope(x, fs, ms):
    n = max(1, int(round(ms * fs / 1000.0)))
    k = np.ones(n)
    return np.sqrt(np.convolve(x ** 2, k, "same") / np.convolve(np.ones_like(x), k, "same"))


csv_path, markers_path, oz_path = sys.argv[1:4]
protocol_path = sys.argv[4] if len(sys.argv) > 4 else None

rec = load_csv_otomatik(csv_path)
markers = json.load(open(markers_path, encoding="utf-8"))
meta = markers["meta"]
c0, c1 = meta["crop_start_s"], meta["crop_end_s"]
keep = (rec.time >= c0) & (rec.time <= c1)
t, fs = rec.time[keep], rec.fs

for ch, flags in markers["channels"].items():
    print(f"\nchannel: {ch}")
    x = rec.channels[ch][keep]
    det = (meta.get("detection") or {}).get(ch)   # key may exist with value null

    if det:
        src = det.get("source_channel") or ch
        if src != ch:
            print(f"  (detection ran on source channel {src})")
        sm = det.get("smoothing_ms")
        xs = rec.channels[src][keep]
        z = envelope(xs, fs, sm) if sm else np.abs(xs)
        print(" 1. threshold")
        if det["method"] == "manual":
            print("  (manual threshold — nothing to recompute)")
        else:
            th = {"mad": lambda: mad_esik(z, det["k"]),
                  "otsu": lambda: otsu_esik(z),
                  "baseline": lambda: baseline_esik(z, fs, det["baseline_s"], det["k"])
                  }[det["method"]]()
            check(f"{det['method']} recomputed {th:.4f} rounds to stored "
                  f"{det['threshold_uv']}", round(th, 2) == det["threshold_uv"])

        print(" 2. detected flags")
        win = zaman_pencerelerini_bul(z, fs, det["threshold_uv"],
                                      det["gap_tolerance_s"], det["min_duration_s"])
        got = [(t[w["bas_idx"]], t[w["son_idx"]]) for w in win]
        truth = [(f["start_s"], f["end_s"]) for f in flags if f["source"] == "detected"]
        got = [(float(a), float(b)) for a, b in got]
        missing = [f for f in truth if f not in got]
        check(f"all {len(truth)} stored detected flags reproduced (0 samples)",
              not missing, "" if not missing else f"not reproduced: {missing}")
        extra = [w for w in got if w not in truth]
        if extra:
            print(f"  (recomputed but not stored — deleted or replaced by hand: {extra})")
    else:
        print("  (no meta.detection for this channel — 1 and 2 skipped)")

    print(" 3. inferred phases")
    inferred = [f for f in flags if f["source"] == "inferred"]
    if protocol_path and inferred:
        prot = json.load(open(protocol_path, encoding="utf-8"))
        known = {f["event_name"]: (f["start_s"], f["end_s"])
                 for f in flags if f["source"] != "inferred"}
        solved, warnings = fazlari_coz(prot, known, c0, c1)
        for f in inferred:
            s = solved.get(f["event_name"])
            check(f"'{f['event_name']}' {f['start_s']:.4f}–{f['end_s']:.4f}",
                  s is not None and abs(s[0] - f["start_s"]) < 1e-9
                  and abs(s[1] - f["end_s"]) < 1e-9, f"solver: {s}")
        if warnings:
            print("  solver warnings:", *warnings, sep="\n    ")
    else:
        print("  (no protocol JSON given or no inferred flags — skipped)")

    print(" 4. RMS in _oznicelikler.csv")
    for row in csv.DictReader(open(oz_path, encoding="utf-8"), delimiter="\t"):
        if row["kanal"] != ch or not row["pencere_bas_s"]:
            continue
        b, s = float(row["pencere_bas_s"]), float(row["pencere_son_s"])
        rms = float(np.sqrt(np.mean(x[(t >= b) & (t <= s)] ** 2)))
        stored = float(row["kok_uv"])
        check(f"{row['etiket']}: {rms:.6f} µV", abs(rms - stored) <= 1e-12 * max(1, rms),
              f"stored {stored:.6f}")

print(f"\n{n_checks - len(failures)}/{n_checks} checks passed")
sys.exit(1 if failures else 0)
