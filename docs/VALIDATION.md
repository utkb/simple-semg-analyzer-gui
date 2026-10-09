# Validation Protocol — Simple sEMG Analyzer GUI

Companion documents: `docs/ARCHITECTURE.md` (design and rules),
validation work plan (2026-10-03), changelogs in `docs/changelog/`.

---

## 1. Scope

**Reported measures (congress and project report):**

| Measure | Source | Level of scrutiny |
|---|---|---|
| Plateau RMS (µV) | fixed 20 % trim of a flag | A + B |
| %MVC | plateau RMS / MVC reference (`meta.mvc_aggregation`) | A + B |
| Window position (first/last sample used) | flag ∩ crop, plateau | A + B |
| Flag RMS (`bayrak_kok_uv`), flag duration, onset/offset time | detected or manual flag | A (+ B for detection) |
| Rest-phase RMS | phases inferred by "Kalanları Belirle" | A + definition in §4.6 |

**Dropout (interpolated zero blocks):** block *detection* is verified (criterion 11, level A); the quality of the interpolation is not assessed.

**Out of scope (post-congress):** MDF/MNF, comparison with Delsys
EMGworks (level C), 20–450 vs 10–500 Hz sensitivity analysis, SHA-256 of
code files.

## 2. Levels

| Level | Question | Compared | Criterion type |
|---|---|---|---|
| **A. Verification** | Does the code compute what it says? | GUI output ↔ independent script, *same input* | Numerical equality (≈ machine precision) |
| **B. Analytical validity** | Does the pipeline recover a known value? | GUI ↔ synthetic ground truth | Bias + spread |
| **C. Concurrent comparison** *(deferred)* | How and why does it differ from commercial software? | GUI ↔ Delsys | Bland–Altman, explained difference |

Level C is not a validity criterion: the commercial software applies no
offset correction, so it is not ground truth; a difference there is a
finding to explain, not a failure.

## 3. Frozen version

- Tag: **v2026.10-validation** · commit: the commit this tag points to
  (`git rev-parse --short "v2026.10-validation^{commit}"`) · date: 2026-10-06.
  (The hash is not written here: a file cannot contain the hash of the commit
  that contains it. Every session's `meta.software.commit` must equal it.)
- Every processing session records tag + commit. From this version on,
  `markers.json → meta.software` stores version and commit automatically;
  the recipe JSON stores its own `yazilim` block.
- A bug found during processing does **not** change the version: it is
  logged and processing continues; reprocessing happens after the congress.

## 4. Fixed rules (decided before results)

These rules define what the numbers *are*; any independent script must use
them exactly.

### 4.1 Signal and time
- Times are on the raw file's time axis; cropping never resets time.
- Window selection: `(t >= start) & (t <= end)`, both ends included.
- Amplitude unit: µV everywhere (loader converts once).
- Filter: Butterworth, design order 4, 20–450 Hz, `sosfiltfilt`
  (−6 dB at the cut-offs). Hardware band 10–850 Hz; the analysis band is
  reported with every resting RMS.
- End-frame cut: 400 ms after filtering.

### 4.2 Envelope (display, detection threshold, plateau search)
- Moving RMS: square → centred moving mean → square root; step 1 sample;
  divisor shrinks at the edges.
- Window length in samples: `max(1, int(round(ms · fs / 1000)))`
  (50 ms ↔ 107 samples at 2148.15 Hz).
- The envelope never enters a reported RMS (fixed plateau rule is
  bit-identical across the four views).

### 4.3 Plateau and %MVC
- Plateau: fixed, 20 % trimmed from each end of the flag ∩ crop;
  trim count `int(round(n · 0.20)) == (n + 2) // 5` (no double-rounding
  case at 20 %).
- MVC flags must be **≥ 2 s** (below ≈ 1.67 s there is no plateau and the
  trial drops out of the MVC reference with a warning only); the warning
  must be read before saving.
- %MVC denominator: `meta.mvc_ref_file` + `meta.mvc_aggregation`
  (max or mean), from the unrounded RMS.

### 4.4 Crop
- Crop **before** flagging. If the crop is later narrowed into a flag,
  re-run "Ortayı Al"; in the CSV `pencere_bas_s ≠ plato_bas_s` reveals it.
- Changing the crop or the envelope window resets the detection threshold
  (the threshold is a statistic of the shown signal).

### 4.5 Detection (Tespit Et)
- Bounds: first / last supra-threshold sample of the shown signal
  (Lidierth 1986). Gaps shorter than the gap tolerance t₃
  (`gap_tolerance_s`, default 0.05 s; 0 = off) are bridged; bounds never
  move. Minimum duration: `son − bas + 1 ≥ round(min_s · fs)`.
- A region touching the crop boundary yields a flag at that boundary.
- "Apply to all channels": detection runs on one channel and its flags are
  copied to the others; `meta.detection[ch].source_channel` names it. The
  threshold is then a statistic of the source channel only.
- `dual_threshold: true` only records that the minimum duration is on
  (amplitude threshold + duration threshold). It adds no rule beyond
  `min_duration_s` and is not Bonato's double-threshold detector.
- A detected flag may be deleted by eye; deletions are not recorded in
  `markers.json`.
- Threshold: **chosen per recording and per channel**, by eye. Baseline
  noise cannot be controlled — it differs between participants and even
  between re-applications of the same electrode on the same person — and
  residual ECG differs between channels, so no single threshold, and no
  single k, fits all recordings (the developer's own SCM R recording
  needed k = 20 against a default of 3).
  Procedure: Öner with the channel's method (default: baseline + k·SD
  over the protocol's rest phase) → adjust k (or the threshold) until the
  flags start/end at the departure from / return to baseline (§4.6) →
  Tespit Et → correct bounds by eye if needed.
- What is recorded (`meta.detection`, per channel): method, k, baseline
  duration, threshold, gap tolerance, minimum duration, envelope window;
  a threshold typed by hand is recorded as `method: "manual"`.
- What is reported, per channel: method; distribution of k (median,
  range) and of the threshold in µV; number of manual thresholds; number
  of flags with manually corrected bounds. Wording: *"Contraction onsets
  and offsets were detected with a [method] threshold whose multiplier k
  was set per recording and channel by visual inspection (median k = …,
  range …); bounds were verified visually."*
- Every flag remains editable by eye; manual edits are recorded as
  `source: "manual"`.

### 4.6 Rest phases
- Inferred from protocol anchors (`protocol.fazlari_coz`): measured ends
  (flags, crop start) take precedence; expected durations fill the rest.
- A duration-anchored first phase (e.g. "Resting", 30 s) covers only the
  first N s of the crop; time up to the first marked event is unassigned.
- **Reported rest RMS = RMS of the whole inferred phase** (no trim).
  Rationale: contractions are found first, with ON = the point where the
  signal starts to rise from the baseline noise and OFF = the point where
  it returns to a baseline level; "Kalanları Belirle" runs afterwards.
  The ramps then belong to the contraction, and what remains in the rest
  phase is the baseline — including incomplete relaxation, which is a
  finding in its own right, not contamination.
- Consequence: flag bounds must sit at the departure from / return to the
  baseline. If a high threshold is needed (e.g. ECG residue) and the
  automatic bounds fall later/earlier than that, the bounds are corrected
  by eye before "Kalanları Belirle" (recorded as `source: "manual"`).

## 5. Acceptance criteria

| # | Comparison | Measure | Criterion |
|---|---|---|---|
| 1 | GUI ↔ Feature Script, same input | RMS, %MVC | relative difference < 0.01 %; any larger difference explained |
| 2 | GUI ↔ Pre-processing Script | pre-processed signal | max absolute difference per sample < 0.01 µV |
| 3 | Position-marked synthetic signal (step, ramp) | first/last sample used | identical to the flag times (0 samples) |
| 4 | Saved session ↔ re-derivation from its files (`reproduce_records.py`) | Öner threshold, detected flags, inferred phases, row RMS | threshold rounds to stored value; every stored detected flag and every phase 0 samples (recomputed windows without a stored flag = deleted by hand, listed); RMS identical |
| 5 | Sine, ground truth | RMS | < 0.5 % |
| 6 | Shaped noise, 20 seeds | RMS bias | < 1 % (filter power loss corrected via theoretical \|H(f)\|²) |
| 7 | Known-RMS MVC file + task file | %MVC | < 0.5 % |
| 8 | ECG contamination (rest level) | RMS error after FTS | reported; < 10 % treated as acceptable in the literature |
| 9 | Real data, 12 participants | GUI ↔ Feature Script | Bland–Altman bias + limits of agreement, largest difference |
| 10 | DC offset test (+20 µV) | RMS recovery after correction | reported |
| 11 | Dropout blocks found independently in the raw channel ↔ blocks in the recipe JSON (`dropout_validation.py`) | first/last sample of each block, per channel | 0 samples difference |

Synthetic ground truth for RMS is the value *before* filtering; keep the
spectrum inside the pass band or correct with |H(f)|².

## 6. Evidence already obtained (before freeze)

Unit-level verification run on the frozen code; scripts in `validation/`.

| Script | Scope | Result |
|---|---|---|
| `display_validation.py` | RMS unbiased; fixed plateau bit-identical in four views | pass (2026-10-05) |
| `plateau_validation.py` | plateau position 0 samples; RMS, %MVC bit-identical; meta fields | 31/31 (2026-10-05) |
| `detection_validation.py` | detection rules, 300 random signals vs independent reference | 40/40 (2026-10-05) |
| `threshold_validation.py` | MAD vs SciPy, Otsu vs independent NumPy reference, baseline vs mean + k·SD | 26/26 (2026-10-06) |
| `dropout_validation.py` | criterion 11 on CCFM_1 (raw Delsys file + recipe), 4 channels, 75 blocks of 29/58 samples | 8/8 (2026-10-06) |
| `reproduce_records.py` | criterion 4 (§5) on three own recordings (P04: threshold, flags, phases, RMS; P01: RMS rows, no stored detection; CCFM_1: 4 channels, detection on a source channel) | 9/9, 44/44 (2026-10-06); CCFM_1 with source channel and two hand-deleted windows: 56/56 (2026-10-06) |

Supporting tools (not evidence; no pass/fail): `loader_validation.py` prints an independent reading of real Delsys files next to the loader's output (time columns, fs, NaN, ×1000 unit); `dropout_examination.py` counts all-zero blocks by length; `dropout_rate.py` holds the dropout functions used by `dropout_validation.py` and later by the Feature Script.

Known, accepted properties: Otsu returns the valley bin's left edge (half
a bin below the usual bin-centre convention); with separated modes the Otsu threshold sits
just above the rest mode. sure_s is written rounded to 4 decimals; the Feature Script compares it to end − start within 0.5·10⁻⁴ s.

## 7. Analysis and reporting

- Agreement statistics in JASP (Bland–Altman, largest absolute difference).
- Every table states: tag + commit, number of recordings, rule set (§4).
- Limitations stated explicitly: one device, one muscle group, unsolved
  half of the ECG problem (cross-channel removal during contraction),
  no accepted tolerance in the literature for feature agreement between
  EMG software (our pre-specified criteria answer this gap).

## 8. Amendments

| Date | Change | Reason | Before/after results seen |
|---|---|---|---|
| — | — | — | — |
