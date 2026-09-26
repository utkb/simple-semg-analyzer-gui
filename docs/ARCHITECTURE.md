# Simple sEMG Analyzer GUI — Architecture & Design Decisions

This document describes the design of **Simple sEMG Analyzer GUI** (repository: `simple-semg-analyser-gui`), a
surface EMG (sEMG) time-domain signal processing, region-flagging, and feature-extraction
tool for bipolar single-channel recordings. Delsys Trigno is the hardware currently
available to the developer and the only format validated so far — a practical starting
point, not an architectural target. The software is designed to be device-agnostic, with
new hardware supported by adding a loader for that device's export format rather than by
changing the processing pipeline. This document reconciles decisions made across the
project's development history and supersedes any earlier internal drafts.

> **Note on code identifiers:** the codebase is written by a single Turkish-speaking
> developer/researcher and teaches a Turkish-language spine-health course. Internal
> variable and function names remain in Turkish (e.g. `dogru_akim_kaymasi_gider`,
> `bayrak`, `oznicelik`) pending a planned bulk translation pass. JSON keys (external
> data contract), this documentation, the README, and the paper are in English.
> UI labels and CSV column headers currently stay Turkish, to avoid breaking
> downstream analysis scripts already written against them — but this is a
> transitional state, not the target: both the UI and CSV output are planned to
> support Turkish and English side by side. See §15 for the plan. Protocol
> files are already English at the schema level — field names such as
> `event_name`, `duration_s`, `type`, `anchor_start` are part of the external
> data contract (§7) and are English like other JSON keys. What a researcher
> fills into those fields — event names, `description`, `notes` — is free text
> and may be in whatever language the researcher is working in; this is not
> part of the TR/EN UI plan, since there is no fixed vocabulary to translate.

---

## 1. Purpose and Scope

- **Primary purpose:** post-hoc / offline analysis GUI for surface EMG data.
- **Secondary purpose:** teaching material for a spine-health / biomechanics course.
- **Scale:** small numbers of research participants, not population-scale data — every
  processing step is designed for visual, human verification, not blind automation.
- **Hardware (current):** Delsys Trigno Discover / Trigno Avanti, 4 bipolar channels
  (bilateral sternocleidomastoid [SCM] and upper trapezius in the primary study
  protocol). This is the hardware the developer currently has access to, not a fixed
  target — see the modularity goal below.
- **Modularity goal:** the software must not be tied to one device. `loader.py` is
  built as a format dispatcher (`load_csv_otomatik()`): it auto-detects the input
  format and delegates to a per-format loader, all producing the same `EMGRecording`
  contract (§5). Supporting a new device means writing one new `_load_<format>()`
  function and registering it, never touching `pipeline.py`, `features.py`, or the
  GUI.
- **Current research protocol (example, not a target):** the developer's active
  study uses a Craniocervical Flexion Maneuver (CCFM) protocol plus a submaximal
  MVC (Maximum Voluntary Contraction) reference trial, and this document uses it
  for concrete
  examples throughout. The software is not hard-coded to it: a protocol is fully
  defined by a JSON file (§7), so a new study — present or future — is supported
  by adding a protocol file, not by changing code, the same way a new device is
  supported by adding a loader (above).

---

## 2. Design Principles

- **KISS** — no unnecessary complexity.
- **"Adequate but working beats perfect but non-functional"** — build a solid
  foundation first, add features once the base is validated against real data.
- **"One tool, one job"** — each module has a single responsibility.
- **Mandatory visual verification** — no processing step is a black box; every
  transformation is plotted and inspectable.
- **"What you see is what is reported"** — a metric computed for a region must be
  computed from the exact signal shown on screen for that region (smoothed vs. raw,
  in particular), never from a different intermediate representation.
- **Prefer established libraries** (SciPy, NumPy) over custom numerical routines,
  for scientific reproducibility.
- File-splitting decisions are based on **separation of responsibility**, not line
  count. Computation modules target 50–150 lines; GUI modules are exempt from this
  target because splitting them fragments shared state and adds artificial complexity.

---

## 3. Technology Stack

| Layer | Choice |
|---|---|
| Language | Python — chosen for its broad ecosystem of signal-processing libraries (SciPy, NumPy) and for the developer's existing fluency in it |
| GUI | CustomTkinter (a styling layer over `tkinter`; near-identical API, large visual improvement for a teaching context at negligible cost) |
| Numerical computation | NumPy, SciPy |
| Visualization | Matplotlib, embedded in CustomTkinter |
| Classification / ICA | scikit-learn (FastICA, reference method for ECG artifact removal) |
| Data storage | `gui.py`: one timestamped CSV (final processed signal) plus a same-named JSON processing recipe per save, written by `utils.py`'s `sonuc_kaydet()` into `<file>_yemg/` next to the source file (§6.5); intermediate steps are not written to disk. JSON also for protocol files. HDF5/`.npy` were considered for processed-result performance but were never adopted or needed — recordings are small (worst case ~18–37 MB for a 5-minute, 4-channel, 4000 Hz file) and are processed one file at a time with visual verification at every step, so plain-text I/O is not a bottleneck, and it keeps outputs human-readable and directly inspectable, consistent with the project's transparency principle. |
| Explicitly out of scope | PyQt6, QWebEngineView, HTML-based panels — avoided to keep the dependency footprint small and the code readable by non-programmer researchers who understand the signal-processing methodology but not necessarily a web-style UI stack |

---

## 4. Module Structure

```
simple_semg_analyzer/
│
├── loader.py        # shared core — EMGRecording (the shared data class, §5), format dispatcher
├── pipeline.py      # shared core — signal transforms (rectification, envelope,
│                    # normalization, RMS, end-frame cut). flagging.py's
│                    # _hazirla_dizi() delegates here, not a re-implementation —
│                    # a fix made in pipeline.py (e.g. the envelope-divisor fix,
│                    # §9) automatically applies in both windows. The moving-RMS
│                    # envelope (rms_hesapla with a window) is itself built on
│                    # dogrusal_zarf, so the windowing logic lives in one place.
│
├── gui.py           # Entry point — main pipeline window (conditioning steps),
│   │                 # signal visualization (ghost overlay — previous step's
│   │                 # signal shown as a faint dashed line for before/after
│   │                 # comparison; min-max decimation).
│   │                 # Run directly, no separate bootstrap module.
│   ├── filters.py    # gui.py-only — bandpass etc. (Filtering step)
│   ├── ecg.py        # gui.py-only — ECG artifact removal (ECG step); consumes
│   │                 # R-peak timestamps from sync.py when available
│   ├── dropout.py    # gui.py-only — RF dropout handling (Dropout step)
│   └── utils.py      # gui.py-only (currently) — output folder, pipeline-format
│                     # CSV writer (_csv_yaz), final CSV + recipe JSON
│                     # (sonuc_kaydet(), §6.5). adim_kaydet() (per-step
│                     # CSV+PNG) is kept but no longer called by gui.py.
│                     # Open question, not yet decided: should flagging.py's
│                     # save (markers.json + oznicelikler.csv) move here too?
│
├── flagging.py       # Standalone — region flagging & feature extraction
│   ├── detection.py  # flagging.py-only — onset/offset threshold algorithms
│   ├── protocol.py   # flagging.py-only — protocol phase/anchor resolution
│   └── features.py   # flagging.py-only — feature extraction from flagged regions
│
├── sync.py           # Polar H10 ↔ EMG time synchronization, for ECG artifacts.
│                     # Standalone, separate entry point (`python sync.py`) —
│                     # not yet integrated into gui.py. Its only planned
│                     # contract with gui.py: hand off ECG R-peak timestamps
│                     # for ecg.py's FTS step to consume.
│
└── protocols/
    ├── ccfm.json
    ├── mvc_standart.json
    ├── dinlenme_sirtustu.json
    └── dinlenme_ayakta.json
```

**Why this split:**
- `loader.py` and `pipeline.py` are the shared core: both `gui.py` and
  `flagging.py` call them directly rather than each keeping its own copy. This
  is also what keeps hardware support swappable — everything past `loader.py`
  only ever sees an `EMGRecording`, never a device-specific file format — and
  what keeps a pipeline fix (e.g. §9's envelope-divisor correction) valid in
  both windows at once, since `flagging.py`'s `_hazirla_dizi()` delegates to
  `pipeline.rms_hesapla()` (which in turn uses `pipeline.dogrusal_zarf()`)
  instead of re-implementing it.
- `flagging.py` is a standalone program (`python flagging.py [file.csv]`), not a
  module imported by `gui.py`, because it opens its own interactive window and
  belongs to a different interaction pattern than the sequential pipeline.
- `detection.py` was extracted from `flagging.py` specifically so onset/offset
  threshold logic has no GUI dependency and can also be called from the pipeline
  or from automated tests.
- `sync.py` is scoped **exclusively** to Polar H10 ↔ EMG alignment, and is not
  yet wired into `gui.py` — it currently runs as its own program. Cross-channel
  ECG cleaning (using one EMG channel's R-peaks to clean another) is a related
  but distinct problem already solved inside `ecg.py` / `gui.py`.
- `protocol.py` is separate from `loader.py` because the planned time-normalization
  interface needs protocol data without importing `flagging.py`.
- No OOP class hierarchy; the one exception is the `EMGRecording` dataclass,
  which defines the data contract every module shares. This is a deliberate
  choice, not an oversight: a flat, functional style keeps each transformation
  a plain function that takes data in and returns data out, with no hidden
  state behind an object's methods to track — easier to read, test, and debug
  independently of how experienced the reader is with Python, and a good match
  for a developer working at an early-to-intermediate level with the language,
  consistent with the KISS principle stated above.

---

## 5. Core Data Structure

```python
from dataclasses import dataclass, field
import numpy as np

@dataclass
class EMGRecording:
    channels: dict                                 # {"channel_name": np.ndarray}
    fs: float                                       # sampling frequency (Hz)
    time: np.ndarray                                # time axis (s)
    markers: list = field(default_factory=list)     # declared, currently unused (see note below)
    metadata: dict = field(default_factory=dict)    # file header info, protocol, format
```

`loader.py` constructs this object; every other module receives and returns it (or its
processed contents) unchanged in shape. `metadata` includes `"format"` (`"delsys"` or
`"pipeline"`), file path, application/datetime strings from the Delsys header, duration,
and per-channel sampling frequency.

> **Note — `markers` field is currently dead:** `loader.py`'s original docstring
> describes this field as populated by the flagging module, as a flat list of
> `{"channel": str, "start_s": float, "end_s": float}` dicts. In practice,
> `flagging.py` never writes to `EMGRecording.markers` at all: it keeps its own
> instance attribute (`self.bayraklar`, a dict keyed by channel name — see §8.2
> for its actual shape) and, on save, normalizes and writes that directly to
> `<file>_markers.json`, bypassing this field entirely. This is a design leftover,
> not a bug in the running program — but the dataclass and the code have drifted
> apart, and the field should either be removed from `EMGRecording` or actually
> wired up, rather than left declared and silently unused. Not yet decided which.
> Delsys Trigno's own native "F5" marker feature is a separate, unrelated
> capability of the Trigno software itself; it was evaluated early in the
> project and deliberately not adopted — the project's own `marked` anchor
> mechanism (§7.2) was built instead.

---

## 6. GUI Architecture (`gui.py`)

### 6.1 Layout (current)
- **Top bar:** application name, `Dosya Aç` (Open), `Kaydet` (Save — shows
  `Kaydet ●` while there are unsaved changes, §6.5), `Kaydet ve Bayrakla →`
  (Save & Flag, §8.4), `Grafiği Kaydet` (Save Plot, §6.5) and the open file
  name (left); undo-stack navigator (`← Geri Al`
  / Undo, with the current step's sequence number and short name) and three
  mutually exclusive view toggles, Frequency Spectrum, Power Spectrum and
  MNF/MDF Trend (center) — all operate outside the pipeline
  (`scipy.signal.periodogram` / `scipy.signal.welch`, 1 s window, 50 %
  overlap / 0.5 s non-overlapping epochs) and never modify
  `islenmis_kanallar`; any "Apply" or "Undo" resets the view back to the time
  domain. The MNF/MDF Trend x-axis is read from the actual time axis (epoch
  midpoints), so it stays aligned with the time-domain plot after cropping
  and end-frame cutting.
- **Left panel:** the pipeline steps themselves (§6.3), each with its own
  "Apply" button and parameter widgets.
- **Right / center:** signal plot, updated on every "Apply."
- **Undo stack:** each "Undo" press reverts one step, to the previous state —
  not directly to raw EMG — though pressing it repeatedly walks all the way
  back, since the stack is preserved down to the raw signal. The stack lives
  **in memory only**: each entry holds a full copy of the channel data plus
  that step's recipe — `{kanallar, zaman, ad, parametreler, kontrol,
  atlanan, baslik, kirpma_bas, kirpma_son}` — because some steps change
  signal length (cropping, end-frame cutting) and both the data and the time
  axis must be restored atomically. Undo is a pop from this list; nothing is
  recomputed and nothing on disk is touched. Cost: ~6 MB per step for a
  4-channel, 2148 Hz, 90 s recording.
- **Ghost overlay:** each step's plot shows the previous step's signal as a faint
  dashed line for visual before/after comparison. Steps that change the time axis
  pass a separate `ghost_time` parameter to the plotting function so ghost and
  current signals never get silently misaligned to the same axis.

### 6.2 Preview / Crop step
- **Step 1 — Preview / Crop:** appears immediately after a file is opened, before
  any other pipeline step. Two numeric entry fields (start s / end s) plus an
  "Apply" button — **not sliders**, for precise, reproducible values.
- **Crop is first-step-only.** It always cuts from the raw recording, so
  applying it after another step would silently discard that step while the
  recipe (§6.5) still listed it. The button therefore refuses to run while
  any non-crop step is in the undo stack ("undo the later steps first"), and
  re-cropping replaces the previous crop, so a recipe holds at most one crop.
  A simple region-selection tool for inspecting the power spectrum of a
  chosen segment is planned separately and is not a crop.
- Kept strictly separate from end-frame cutting (Step 6): cropping is a researcher
  decision about the recording as a whole; end-frame cutting is a technical
  necessity driven by the chosen filter's transient response.

### 6.3 Pipeline steps (left panel)
```
1. Preview / Crop                          — first step only (§6.2)
2. Dropout detection & interpolation      (dropout.py)
3. DC offset removal                      — calculated offset shown before applying
4. ECG artifact removal                   — two-stage: show peaks → apply;
                                             method, window/LP/distance/prominence/
                                             height_k/local window/polarity
5. Filtering (bandpass etc.)              — filter type, kind, cutoffs, order
6. End-frame cutting                      — length in ms, default 400 ms
```
- **Conditioning only.** Rectification, linear envelope and %MVC
  normalization were removed from `gui.py`; they are interpretation steps
  and live in `flagging.py` (§8.4). Removing them also means the GUI's
  spectral views can no longer be shown on a rectified signal.
- **No internal step numbers.** The sequence number is plain text in each
  panel label ("1." … "6."); in code, steps are identified by name
  (`kirpma`, `dropout`, `dc_offset`, `ekg`, `suzme`, `uc_cerceve` — the
  `ADIM_ETIKET` table). Earlier internal numbers (00–08, with gaps after the
  removals) and the Unicode circled digits were dropped as a second,
  confusable numbering.
- **No completion coloring.** Steps can be applied in any order and more
  than once (e.g. band-pass then notch), so "completed" coloring was
  misleading and was removed; the plot title and the recipe show what was
  actually applied.
- **Steps may repeat.** Two filtering steps in a row are two separate
  entries in the undo stack and the recipe, never an overwrite.
- **End-frame cutting has no "oto" option.** The former automatic length
  (`2·4·round(fs/20)` samples ≈ 400 ms at 2148 Hz) hard-coded filter order 4
  and a 20 Hz corner instead of reading the filter actually applied; it was
  removed. Default is 400 ms. Deriving the length from the applied filter's
  transient is an open item.

### 6.4 Downsampled visualization: min-max decimation
Plotting every sample at 1000–4000 Hz over a multi-minute recording is
unnecessarily slow and adds no visual information beyond what a coarser plot
already shows — computation always runs on the full-resolution array
regardless, only the on-screen rendering is thinned.

Three approaches were tested against each other (150 s recording, 4 channels ×
3 overlaid lines — a worst-case scenario):

| Approach | Speed | Correctness |
|---|---|---|
| Naive stride downsampling (`array[::ds]`), i.e. keeping only every `ds`-th raw sample before plotting at all | 0.43 s | ✗ — misses narrow spikes (R-peaks) whenever a spike falls between the kept samples; a genuine bug found this way |
| No manual downsampling: hand the full-resolution array straight to Matplotlib and rely on its own built-in `path.simplify` (which internally keeps the min/max per screen pixel column) | 3.63 s | ✓ — 148/148 synthetic spikes preserved, but too slow for a "worst case" recording |
| **`_minmax_seyrelt()` (chosen):** split the signal into windows and keep both the minimum *and* maximum sample of each window (not one arbitrary sample), before handing the reduced array to Matplotlib | **1.28 s** | ✓ — 148/148 spikes preserved |

The naive-stride failure and Nyquist aliasing share a root cause ("sample too
coarsely and you miss something fast-changing") but the symptom differs:
periodic signals produce false-frequency ghosts when undersampled, while a
transient spike simply vanishes probabilistically depending on where the
stride happens to land relative to it.

A fourth option, classic DSP decimation (`scipy.signal.decimate`, i.e.
anti-alias filtering before subsampling), was rejected outright rather than
benchmarked: its low-pass filter smooths and spreads out a spike's true
amplitude, so what ends up on screen is no longer the true amplitude —
violating the "what you see is what is reported" principle regardless of
speed.

`_minmax_seyrelt()` wins on both counts also considered against Matplotlib's
own simplification: same correctness, roughly 3× faster in the worst-case
benchmark above, because a general-purpose path-simplification algorithm is
more expensive than a single vectorized NumPy reshape/min/max pass. Real
recordings in this project (a few minutes at most) are far shorter than the
150 s worst case, so actual render time is well under the benchmarked figures.

**Display-only, never computed on:** `_minmax_seyrelt()`'s output is used
exclusively for `ax.plot()`. Every actual computation — RMS, MDF/MNF,
thresholding, %MVC, everything in `pipeline.py` and `features.py` — always
runs on the original, full-resolution array; the decimated array never feeds
back into any calculation.

**Uneven spacing within a window is not a violation of "what you see is what
is reported":** within one decimation window, the min and max samples don't
necessarily sit at the start and end of that window — they can come from
anywhere inside it, so the two plotted points are not evenly spaced in time.
This means the straight line Matplotlib draws between them is not a faithful
reconstruction of the true waveform shape in between. But this is true of
*any* decimation approach (naive stride and Matplotlib's own `path.simplify`
included) — it is an unavoidable consequence of showing fewer points than
exist. What matters for the transparency principle is that both plotted
points are genuine, unmodified raw samples — nothing is synthesized,
averaged, or interpolated — so the amplitude the researcher reads off the
screen is always a real value the hardware actually recorded. The principle
is about amplitude honesty, not about between-point curve smoothness, which
no plot of any downsampled signal can guarantee regardless of method.

### 6.5 Saving: final output + processing recipe

**What is written.** Nothing is written while steps are applied. `Kaydet`
(Save) writes one pair of files into `<file>_yemg/`:

```
<file>_yemg/
  P01_01_20260925-143210.csv    # final processed signal (pipeline CSV format)
  P01_01_20260925-143210.json   # processing recipe
```

The CSV keeps the format `loader._load_pipeline` already reads (tab
separated, `zaman_s` first column, original time stamps — never shifted to
0, since Polar sync and flagging anchors depend on them). Its comment line
now carries the recipe's name so the two files can be re-paired if
separated: `# fs=2148.0  adim=son  tarif=P01_01_20260925-143210.json`
(`loader` splits on whitespace and reads only `fs=` / `adim=`; the extra
key is ignored). The timestamped name means `flagging.py`'s
`markers.json` → `meta.source_file` always points at one specific
processing chain.

**Recipe content** (built from the in-memory undo stack at save time, so an
undone step can never appear in it):

```json
{
  "yazilim": {"ad": "Simple sEMG Analyzer GUI", "surum": "2026.09",
              "python": "3.11", "numpy": "2.x", "scipy": "1.x", "matplotlib": "3.x"},
  "kaynak_dosya": "P01_01_-_SCM.csv", "kaynak_yol": "/abs/path/P01_01_-_SCM.csv",
  "cikti_csv": "P01_01_20260925-143210.csv",
  "kaydedilme": "2026-09-25T14:32:10", "fs": 2148.0,
  "kanallar": ["..."], "zaman_araligi_s": [2.4, 17.6],
  "adimlar": [
    {"sira": 1, "ad": "kirpma", "baslik": "Kırpma — bas_s=2, son_s=18",
     "parametreler": {"bas_s": 2.0, "son_s": 18.0}, "atlanan": [], "kontrol": {}},
    {"sira": 4, "ad": "suzme",
     "parametreler": {"tip": "butter", "cesit": "bandstop", "alt_hz": 49.0,
                      "ust_hz": 51.0, "derece": 4},
     "atlanan": ["Trapez L"], "kontrol": {}}
  ]
}
```

- **One dictionary, three views.** Each step produces a single
  `parametreler` dict; the plot title (`_baslik_yap()`), the recipe entry
  and the `Grafiği Kaydet` file name are all derived from it. What the
  researcher reads on screen is literally what is recorded — "what you see
  is what is reported" extended to provenance. Parameter values are the
  ones passed to the processing function (e.g. `butter`, `bandstop`), not
  UI labels, so a recipe can be re-applied as written.
- **Parameters are captured at computation time**, never re-read from the
  entry boxes afterwards. For ECG, parameters freeze at "Show Peaks"; a box
  edited between "Show Peaks" and "Apply" does not change what is applied or
  recorded.
- **Automatic choices are recorded as what they are.** ECG `prominence` is
  recorded as `"oto"` (its value is computed inside `ecg.py` and not
  exposed); local window `None` as `"global"`; source channel "per channel"
  as `"kanal_basina"`; when polarity is `"oto"`, the polarity actually chosen
  is recorded per channel under `kontrol`.
- **Check values (`kontrol`)** let a re-run be verified against the saved
  run: DC — offset removed per channel (mV); dropout — block count,
  percentage and block start/end times (interpolated segments look like
  ordinary data in the final CSV otherwise); ECG — peak count and peak times
  (s) per channel. `atlanan` lists channels skipped by the channel
  checkboxes for that step.
- **Library versions** are recorded because SciPy's filter design can differ
  numerically between versions.
- **Why not per-step files (the previous design).** `adim_kaydet()` wrote
  `<no>_<name>.csv/.png` per step. It overwrote on repeated steps (a notch
  after a band-pass left only the notch), left files of undone steps on
  disk, gave `flagging.py` no single obvious input, and — the decisive
  point — recorded *that* a step ran but not *with which parameters*
  (`adim=04_suzme` says nothing about cutoffs or order). Verifiability comes
  from raw data + recipe + open code, which lets anyone regenerate every
  intermediate; intermediate files add bulk, not proof. Intermediate plots
  can still be saved by hand with `Grafiği Kaydet`, which pre-fills a file
  name from sequence number, view and parameters, e.g.
  `P01_01_05_suzme-tip-butter-cesit-bandstop-alt-hz-49-ust-hz-51-derece-4.png`.
- **Trade-offs accepted:** an unsaved session is lost if the program closes
  (re-doing it is cheap and deterministic); intermediate signals are not
  inspectable outside the program until session restore exists.

> **Planned, not yet built:**
> - **Session restore:** open raw file + recipe → re-apply steps in order →
>   rebuild the undo stack, with ghost overlays and undo available again.
>   This doubles as a reproduction test: re-computed output and check values
>   must match the saved CSV/JSON. Requires each step function to take its
>   parameters as arguments instead of reading entry boxes.
> - **SHA-256 of the source file** in the recipe, to bind it to the exact
>   raw bytes (noted for later; file name and path are recorded now).
>
> **Open question:** recipe keys are currently Turkish (`adimlar`,
> `parametreler`, …), while this document states that JSON keys are part of
> the external data contract and in English (note at top; `protocols/*.json`,
> `markers.json`). `mvc_ref.json` (§10) has the same inconsistency. To be
> decided before recipes accumulate.

---

## 7. Protocol System

Protocols are stored as JSON files in `protocols/`, auto-scanned and shown in a
dropdown. **Adding a new protocol means adding a new JSON file — no code changes.**
Invalid protocol files are shown in the dropdown with a `⚠` prefix and raise a
descriptive error dialog on selection rather than failing silently.

### 7.1 Phase schema (current)
Each protocol defines a list of **phases**, replacing an earlier
(`levels_mmhg`/`contractions`/`hold_s`) schema with no backward compatibility:

| Field | Meaning |
|---|---|
| `event_name` | Unique identifier within the protocol; used as the join key for ensemble-average time normalization. Enforced as an error if duplicated. |
| `duration_s` | Expected phase duration. |
| `type` | `preparation` / `event` / `rest` / `ending` — a **report label only**; no processing behavior is driven by this field. |
| `anchor_start`, `anchor_end` | Where the phase's boundaries come from — see below. |

**Anchor vocabulary** (closed): start ∈ `{file_start, marked, previous_end}`;
end ∈ `{duration, marked, next_start}`. Geometry is read **exclusively** from
anchors, never inferred from `type`. `ending` phases anchor to the preceding
detected event rather than to the end of the file, because recording stops after
a fixed-length timer expires, not necessarily in sync with the protocol's logical
end.

### 7.2 Synchronization
**Why this matters:** in EMG research, onset and offset timing must be
comparable — across muscles, across individuals, and across sessions.
Hardware timers are the conventional way to guarantee this, but not every
lab has access to one, and modern wireless EMG systems compound the problem:
Bluetooth transmission delay means the recording does not necessarily start
the instant the record button is pressed, for purely technical reasons on
the device side. So "recording start = t = 0" is unreliable, and every
protocol needs some way to establish a shared zero point between the
researcher's intended timeline and the actual EMG timestamps.

**Current mechanism — anchors, not a separate `sync_method` field:** the
`marked` anchor value (§7.1) *is* the synchronization mechanism now: the
researcher presses a key at a known moment and `anchor_start`/`anchor_end`
of any phase can reference that mark. Because anchoring is per-phase rather
than a single protocol-wide setting, a mark is no longer tied to being the
*first* event in the recording — any phase, including any one of several
contractions in sequence, can be the one anchored to a mark. This
generalizes what an earlier design iteration proposed as three separate,
mutually exclusive top-level methods:

| Earlier method (superseded) | Idea |
|---|---|
| `first_contraction` | Onset detection on a strong first contraction fixes t = 0; later segments align via an expected offset. |
| `manual_marker` | Researcher presses a key at a known instant (e.g. when an audio cue starts); resolves the Bluetooth delay directly. |
| `audio_file` | An audio file's own timeline as the reference. |

The `marked` anchor keeps the useful part of `manual_marker` (a key press
resolves the delay directly, no onset detection needed) while removing the
restriction that it only apply to the first event. `first_contraction`'s
automatic-onset idea is not implemented yet in the current anchor system —
it defines no automatic-detection anchor type today, but this is an open
gap rather than a closed decision against it. `audio_file` remains out of
scope, unchanged: it still requires Delsys SDK support.

### 7.3 `auto_threshold` (to be removed)
A protocol-level boolean was proposed, intended so that for a protocol like
CCFM (where the target muscle may stay silent) the flagging module's
automatic-detection option would be disabled and the researcher directed to
manual flagging. It was never wired up — all three detection methods (MAD,
Otsu, Baseline — §8.3) are always available in the UI regardless of the
loaded protocol. Decision: drop it from the schema as unnecessary — the
existing method dropdown already lets a researcher switch to manual flagging
in one or two clicks, so a separate protocol-level flag adds no real
protection, only unused complexity. Not yet done: `protocol.py` never read this field either — there is no code
to remove, only the field itself still needs to be deleted from the protocol
JSON files (`protocols/*.json`) that declare it.

---

## 8. Flagging Module (`flagging.py`)

Flagging is a standalone tool, not a page inside the main pipeline window, because
it opens an interactive window whose interaction pattern differs from the
sequential "Apply per step" pipeline. That said, this framing has shifted:
since the layer-separation work (§8.4), the interpretation steps
(rectification, envelope, %MVC normalization) actually live here too — but the interaction still
isn't linear the way `gui.py`'s numbered steps are; a researcher moves back
and forth between threshold methods, manual edits, and re-detection rather
than progressing through fixed stages in order.

> **Open question, not yet decided:** whether `flagging.py` needs its own
> undo mechanism, analogous to `gui.py`'s undo stack (§6.1). Session length
> here is short enough that this hasn't been a real problem so far, but the
> lack of an undo occasionally feels missed while working — e.g. after
> re-running detection with a different threshold. Two directions to weigh,
> to be settled once there's more usage to judge by: (1) a forward/backward
> undo-redo stack, mirroring `gui.py`; (2) logging a screenshot and the
> underlying data on every visual change (a new threshold, a new detection
> run, a manual edit), which would also directly serve the project's "what
> you see is what is reported" principle and — worth calling out for the
> JOSS submission — would give reviewers a concrete, inspectable trace of
> the tool's decisions over a session, not just its final output.
> For comparison, `gui.py` settled the same question the other way: a
> parameter recipe saved with the final output rather than a per-change
> data/screenshot log (§6.5).

### 8.1 Layout (current, three-column)
- **Upper bar:** display controls only — channel selection, crop, and the
  view selector **Ham / Doğrultulmuş / Zarf** (Raw / Rectified / Envelope)
  with its window box (ms). The view is derived on the fly from the loaded
  signal and never modifies it, so it needs no undo. Detection and threshold
  suggestion always run on the signal currently shown: |x| in the Raw and
  Rectified views (Raw draws the |x| threshold as a ± pair on the bipolar
  trace), the moving-RMS envelope in the Envelope view (§9). The window box
  applies only in the Envelope view; typing a window and pressing "Apply"
  switches to it, and a markers file with `smoothing_ms` reopens in it.
  In the Envelope view the faint background trace is the rectified signal.
  When the detection signal changes (|x| ↔ envelope, or a new window), any
  threshold is cleared rather than carried over — a threshold is a
  statistic of the signal it was computed on, and converting it with a
  fixed ratio would hide an approximation (the ARV/RMS ratio is not
  constant). Raw ↔ Rectified does not clear it: both detect on |x|.
  The former "Örtüşme" (overlap) box was removed: it was never read, and
  overlap has no meaning for a sample-by-sample envelope (§9).
- **Left panel:** action controls — automatic detection, manual flagging,
  multi-phase inference placeholders (§8.5 — operations that fill in several
  flags at once within the currently open file, not automation across files)
  — split from the upper bar in a dedicated redesign pass that also rotated
  channel labels 90° and set a 1600×900 default window size.
- **Center:** signal plot with rotated channel labels.
- **Right:** the flag table.

### 8.2 Flag data model

Based on the `_kaydet()` snippet reviewed so far, this appears to be both
`flagging.py`'s in-memory `self.bayraklar` structure (§5's note) and, after
normalization (`_bayrak_normallestir()`), what gets written to
`<file>_markers.json` when "Kaydet" is pressed.

> **TO-DO:** confirm the in-memory and on-disk shapes are actually identical
> — check the full `_kaydet()` function and a real `_markers.json` output
> against this model, not yet verified.

```
{"channel_name": [{"name": str, "start_s": float, "end_s": float,
                    "type": str, "source": str}, ...]}
```
- `source` ∈ `detected` / `manual` / `inferred`; missing values in legacy files
  default to `"unknown"`, never silently assumed to be `detected` or `manual`.
- CSV export includes matching `tip` / `kaynak` columns (headers kept Turkish
  deliberately, to avoid breaking already-written downstream scripts).
- Automatic detection preserves `manual`-sourced flags while refreshing
  `detected` and `inferred` ones.
- A `min_sure_s` (minimum duration) filter, derived from the protocol file,
  removes spurious short detections after window merging.

**Plateau fields (Stage 8 — "Ortayı İşaretle", §8.5, §10):** an `event`-type
flag may additionally carry four fields, produced in a single pass by
`_ortayi_isaretle()` / `plato_bul()`:

```
"plateau_start_s": float,   # absolute time, plateau onset
"plateau_end_s":   float,   # absolute time, plateau offset
"plateau_rule":    str,     # e.g. "sabit, her uçtan %20" / "eşik, tepenin %90'ı"
"plateau_rms_mv":  float,   # RMS of the conditioned signal over the plateau window
```

All four are present together or none are — `_bayrak_normallestir()`
preserves them across load/save round-trips but never fabricates a subset.
Once present, they become the feature window for that flag: the table,
the feature strip, and the CSV export all read from the plateau instead of
the full `start_s`–`end_s` region (`_bayrak_dizisi()` is the single point
where this fallback — plateau if present, else full region — is decided).
There is currently no way to edit an existing flag's `start_s`/`end_s` in
place (only add/delete), so the rule "moving a flag clears all four
plateau fields" has no code path that triggers it yet; if an in-place edit
feature is added later (tracked as a deferred issue — see the project's
issue tracker for the span-selector time-entry proposal, which is
deliberately scoped to *filling* the Baş/Son entry boxes and explicitly
excludes editing existing flags for exactly this reason), that feature is
responsible for clearing these four fields.

### 8.3 Detection methods (`detection.py`)
| Method | Best for | Limitation |
|---|---|---|
| MAD threshold | Low duty-cycle recordings (rest ≫ active) | Threshold drifts upward at high duty cycle |
| Otsu | Signals with two clearly separated amplitude modes | Same duty-cycle limitation as MAD |
| Baseline | Any recording with a known, well-defined rest period | Researcher must know and enter the rest duration (auto-fills from `pre_rest_s` when present in the protocol JSON) |
| *(planned)* Regression-line (De Luca) | Field-standard method | Not yet implemented |

No single method is a universal standard in the literature (Carvalho et al.,
2023, *J NeuroEngineering Rehabil* 20:141 — a 156-paper review found no gold-
standard onset-detection approach and considerable disparity in definitions
and parameters across studies, threshold-based methods included); because
visual verification is always performed downstream, the "perfection" of the
automatic method is secondary to it being transparent and adjustable.

### 8.4 Layer separation ("Work B")
An earlier design had rectification, linear envelope and normalization
split awkwardly between `gui.py` and `flagging.py`, creating a circular
dependency: the GUI's normalization step required flagging output, which in
turn depended on the GUI's processed signal. The resolved architecture splits
by **kind of work**, not step number:
- **Conditioning steps** (crop, dropout, DC offset, ECG, filtering,
  end-frame cutting) — signal-fidelity operations — stay in `gui.py` (§6.3).
- **Interpretation steps** (rectification, envelope, normalization) —
  belong in `flagging.py`, where regions are defined. **Done:** these three
  steps have been removed from `gui.py`.

**Hand-off:** `gui.py`'s `Kaydet ve Bayrakla →` button saves pending
changes (§6.5) and opens the result in `flagging.py` as a separate process.
If nothing changed since the last save, the last saved CSV is reopened
instead of writing a new timestamped copy — so flags keep landing in the
same `<csv>_markers.json`. With no steps applied, the raw file is opened
directly. The script path is built from `__file__`, not the working
directory. No pre-flight checks (e.g. "DC offset not removed") are made:
every step is visible while it is applied, and the recipe JSON records
what was and wasn't done. The two windows are independent afterwards —
the flagging session is bound to an immutable snapshot, not to later
edits in `gui.py`.

This removes the circular dependency, allows MDF/MNF to be computed correctly
from the unprocessed signal instead of a partially processed one, and enables
%MVC graphs directly inside the flagging interface instead of requiring a
CSV round-trip. Both halves of MVC work happen in `flagging.py`: plateau
RMS via "Ortayı İşaretle" (§8.5) and %MVC normalization from an imported
reference (§10).

### 8.5 Multi-phase inference and plateau marking

**"Kalanları Belirle" (Determine Remaining) — implemented (Stage 7).** Once
the researcher has added or auto-detected at least one confirmed event
(contraction), this infers the remaining, not-yet-marked phases of the
protocol from the anchor definitions in the protocol file (§7.1) — e.g. a
`rest` phase anchored `previous_end`→`next_start` is derived once its
neighboring events are known, without the researcher marking it by hand.
If no event has been added yet for a channel, that channel is skipped and
reported as "demirsiz" (anchorless) rather than guessed at.
Every inferred flag is still shown, still marked `inferred`, and still
meant to be visually checked — the button never overwrites a flag placed by
looking at the recording (`detected`/`manual`/`unknown` all win). Clipped,
skipped, or overlapping phases are reported individually after the run
rather than silently accepted. This is distinct from — and comes after —
the MAD/Otsu/Baseline detection in §8.3, which finds the events themselves
from the raw signal; "Determine Remaining" only fills in the phases around
events that are already confirmed.

**"Ortayı İşaretle" (plateau + RMS) — implemented (Stage 8).** This
replaced an earlier placeholder named "Ortala Al" (Center Crop). One
button, one click, three outcomes at once: the plateau of a contraction is
found (on the signal shown — |x| or the envelope), that plateau's RMS is
computed (always from the conditioned signal — never from the envelope; see
§10), and the result is marked visually on
the graph (a darker fill inside the flagged region — see §8.2's plateau
fields). Scope: if a flag is selected, only that flag; otherwise every
`type == "event"` flag across *all* channels, each resolved independently
against its own signal (the "apply to all channels" checkbox used
elsewhere in the panel is deliberately not read here, for the same reason
as "Kalanları Belirle": with it off, channels can carry different anchors,
and running one channel's result against another's data would be a silent
error).

Two selectable rules (`detection.py`'s `plato_bul()`):
- **`sabit`** (default, trim 20 % from each end) — a fixed fraction of the
  flagged region's duration is discarded from both ends.
- **`esik`** (default 90 % of peak) — the interval where the smoothed
  signal first rises above, and later falls below, a percentage of the
  region's own peak value.

Neither rule is fed from the protocol file (unlike `baseline_esik()`'s
`baseline_sure_s`, which corresponds to a real protocol phase) — the
plateau trim fraction has no such protocol counterpart, so it stays a UI
control with a fixed default rather than a new, protocol-schema field.
This is a different problem from the planned regression-line (De Luca)
onset detector in §8.3: De Luca looks for *where a contraction begins* in
a raw signal (hard, still unimplemented); `plato_bul()` trims the ramps of
a region *already known* to contain one (much simpler, fully implemented).
Re-running the button on a flag that already has plateau fields always
recomputes from the *original* `start_s`/`end_s` bounds, never from the
previous plateau — so repeated clicks don't compound the trim.

Visual encoding (fill color encodes `type`; border style encodes `source`;
a dashed border marks `inferred` flags) is unchanged by either feature and
covers both.

---

## 9. Signal Processing Principles

- **DC offset:** `x - mean(x)`, mandatory before any RMS computation — a small
  offset inflates RMS substantially (e.g. a −2.3 mV offset can inflate RMS by
  over 400 %). This is also why dropout handling (§4's `dropout.py`, pipeline
  Step 2) must run *before* DC offset removal (Step 3): Delsys marks lost
  samples as 0, and if those zero blocks are still present when the mean is
  computed, they pull the mean toward zero and skew the offset estimate —
  interpolating them first keeps the mean calculation honest.
- **Detrending:** unnecessary for EMG given the AC-coupled bioamplifier design;
  relevant for IMU signals (temperature/mechanical drift, integration error),
  not applied here.
- **Bandpass default:** Butterworth, order 4, 20–450 Hz — as recorded in
  earlier project notes, attributed there to SENIAM.

  > **TO-DO / caveat:** the "20–450 Hz, order 4" combination is genuinely
  > widespread in the applied literature and frequently cited as "per
  > SENIAM" (e.g. studies using this exact setup on Delsys Trigno, SENIAM
  > electrode placement included) — but the primary SENIAM report itself
  > isn't fully accessible online to confirm this is its literal, verbatim
  > recommendation rather than a convention that grew out of common
  > practice and got attributed to SENIAM along the way. One paper
  > reviewed here describes the actual SENIAM text (Stegeman & Hermens,
  > 1998) as recommending a 10–20 Hz high-pass corner specifically,
  > without necessarily prescribing 450 Hz or order 4 as a fixed package.
  > Treat "(SENIAM)" here as the field's common shorthand, not a verified
  > direct quotation from the primary source.

  All four
  filter families (low-pass, high-pass, band-pass, band-reject) are exposed in
  the GUI for teaching comparison, not just the default. Beyond order and
  cutoffs, filter *type* is also selectable — Butterworth (default), Chebyshev
  I (fixed 0.5 dB passband ripple), and Bessel (flat group delay, which
  preserves the signal's time-domain shape) — each with a distinct trade-off
  worth teaching alongside the default choice. All types are applied via
  `scipy.signal.sosfiltfilt`, i.e. forward-backward (zero-phase), so the
  filter introduces no time shift into the signal — this specific detail
  (order/cutoff *and* zero-lag application, not just order/cutoff) matches
  the field convention: a real study using the same 4th-order, 20–450 Hz
  SENIAM-aligned setup on Delsys Trigno explicitly describes it as a
  "fourth-order zero-lag Butterworth filter" for exactly this reason —
  order and cutoff alone would leave phase distortion unaddressed.
- **Linear envelope:** implemented as a moving average with a shrinking-window
  divisor at the edges (`numerator / denominator`, matching MATLAB's
  `movmean(Endpoints="shrink")`), not a fixed divisor. The earlier fixed-divisor
  implementation produced a systematic edge suppression (measured at 0.502 for
  a constant input; corrected to 1.000). If the moving-average window exceeds
  the signal length, the function raises `ValueError` rather than silently
  expanding the output — consistent with the end-frame-cutting function's
  existing behavior. Note this is a deliberate departure from `pyemgpipeline`,
  which implements the envelope as a low-pass Butterworth filter rather than a
  moving average.
- **Moving-RMS envelope (`flagging.py`'s Envelope view):** square → moving
  average (`dogrusal_zarf`) → square root. The square root is the
  "relinearizer" of Clancy et al. (2023, §4.4) and part of the RMS definition,
  not a separate step — it returns the envelope to mV. The window is
  **centered** (each output value is written to the window's middle sample,
  so the envelope has no lag), **moves one sample at a time** (k = 1, i.e.
  overlap = N − 1: one output value per input sample, same length and time
  axis as the input), and **shrinks at the edges** (each position is divided
  by the number of samples actually inside the window, never by a fixed N).
  RMS rather than ARV was chosen so that the curve, the table's RMS, the MVC
  reference and the 100 %MVC line are the same statistic: an ARV envelope
  sits ≈20 % below RMS for Gaussian-like sEMG (ARV/RMS = √(2/π) ≈ 0.80),
  which made the plotted curve disagree with the reported value. Clancy et
  al. treat ARV and RMS processors as equivalent in performance.
  *Fix:* `rms_hesapla()`'s windowed branch previously used a fixed divisor
  with zero padding — the same edge suppression already fixed in
  `dogrusal_zarf`, here pulling the first/last half-window to ≈71 % of the
  true RMS (0.500 instead of 0.707 on a unit sine). It was dormant (no
  caller used the windowed branch) until the envelope switched to RMS; it
  now delegates to `dogrusal_zarf`.
- **Envelope window:** default **50 ms**, the lower end of the 50–100 ms
  commonly recommended for general contractions (De Luca), giving the
  sharpest onsets. For sustained constant-force holds (MVC, a CCFM pressure
  step) the researcher may widen it before "Ortayı İşaretle" to steady the
  plateau search. This never changes a reported number (see below), only
  where the plateau boundaries fall. Literature ranges (Clancy et al., 2023,
  §7.3–7.4): constant force, low/moderate effort 0.5–2 s; high/maximal
  effort 0.25–1 s; force-varying or dynamic 50–300 ms. Clancy et al. note
  that the moving average is theoretically optimal only for constant-pose,
  constant-force, non-fatiguing contractions; for force-varying ones no
  filter type or cutoff is theoretically optimal and the choice is made
  empirically by overlaying envelopes from several windows. "Submaximal"
  is not the same as "time-varying": a submaximal constant hold is still a
  constant-force contraction. Adaptive (time-varying length) windows
  (Clancy, 1999) are deferred: they perform about as well as the best fixed
  window and only occasionally better.
- **Window ↔ cutoff equivalence (for comparing with studies that report a
  low-pass cutoff):** for a moving-average window of duration T,
  f_c ≈ 0.443 / T (Clancy et al., 2023, eq. 5; from f_c = 0.4429·f_s/√(N²−1)).
  50 ms ≈ 8.9 Hz, 100 ms ≈ 4.4 Hz, 250 ms ≈ 1.8 Hz. Documented here only;
  not shown in the UI (KISS).
- **The envelope locates, it never quantifies.** In `flagging.py` the
  envelope (or |x|) decides *where*: detection windows, plateau boundaries,
  and the plot. Every reported number — RMS, MDF, MNF, the plateau RMS that
  becomes the MVC reference, and %MVC — is computed from the conditioned
  signal as loaded (crop applied, nothing else), by the same function
  (`_oznicelik_bolge()`), so the view setting cannot change any output.

  Reference: Clancy, E.A., Morin, E.L., Hajian, G., Merletti, R. (2023).
  Tutorial. Surface electromyogram (sEMG) amplitude estimation: Best
  practices. *J Electromyogr Kinesiol* 72:102807.
  https://doi.org/10.1016/j.jelekin.2023.102807
- **ECG artifact removal:** cardiac artifact contamination in upper
  trapezius and SCM recordings persisted even with extra care in skin
  preparation — it isn't something electrode technique alone can eliminate,
  which matches the literature's general position that avoiding reliance on
  filtering *instead of* dedicated removal is advisable, since ECG
  contamination in recordings near the thorax is close to unavoidable by
  hardware/placement alone. This mattered especially here because the
  target use case is relaxation research: when the muscle is meant to be
  silent, even a small, otherwise-negligible ECG contribution can dominate
  what should be a near-zero baseline — unlike a strong-contraction study,
  where the same contamination would be swamped by the EMG itself and easy
  to ignore.

  **Methods tried, in order, before settling on FTS:**
  1. *30 Hz Butterworth high-pass* — the simplest option, and the one
     Drake & Callaghan (2006) found tied for best alongside template
     subtraction at 10–25 % MVC. Rejected here because ECG and sEMG spectra
     overlap substantially in upper-torso muscles specifically, so a 30 Hz
     cutoff removes real low-frequency EMG content along with the artifact.
  2. *Gating* (zeroing/interpolating a fixed window around each R-peak) —
     numerically the strongest RMS reduction measured (up to ≈55.7 % in one
     comparison), but the number is misleading: gating deletes real EMG
     inside the window rather than removing only the artifact. At 74 bpm, a
     100 ms window blanks out roughly 12 % of a recording, replacing it with
     straight-line interpolation — a serious distortion for both Fourier-
     based (MDF/MNF) and RMS-based features, not just a cosmetic issue. An
     earlier, narrower 20 ms window (covering only the R spike, not the full
     PQRST complex) reduced this cost but also its effectiveness (≈10.8 %
     reduction); widening to 100 ms improved effectiveness (≈35.6 % in that
     same test) at the cost of the data loss above. Rejected as a default
     despite its raw numbers, specifically because of this deletion.
  3. *Plain template subtraction* (one averaged template subtracted from
     every beat) — literature's frequent top performer on ARV/median-
     frequency error metrics, but fragile in this data specifically: with a
     high beat-to-beat RR-interval variability (σ ≈ 132 ms), a single
     average template didn't represent any individual beat well, leaving
     residual artifact (≈17.8–23.5 % reduction across two test recordings).
  4. *Machine-learning-based removal* (FCN-type) — outperformed template
     subtraction and high-pass filtering by roughly 4 dB in the literature,
     but rejected as a black box: it needs training data and model
     management, and gives no visually-inspectable mechanism, conflicting
     directly with the project's no-black-boxes principle.

  **Filtered Template Subtraction (FTS)** is the method that resolved the
  trade-off: instead of one fixed template, each beat gets its own template,
  derived from a 40 Hz low-pass filtered copy of the EMG signal itself (not
  an external ECG channel), windowed around that beat's own R-peak — so beat
  morphology is captured per-beat rather than assumed constant, which is
  what makes it robust to the RR-interval variability that broke plain
  template subtraction. Critically, unlike gating, it does not delete or
  flatten any samples — the full array is preserved, so it doesn't distort
  sampling or FFT-based analysis, which was the specific property being
  optimized for here (Drake & Callaghan, 2006, for the general template-
  subtraction approach; upper-trapezius adaptation per Spalding & Schleifer,
  2003). Measured on real data: FTS ≈ 39 % RMS reduction — lower than
  gating's raw number, but the deliberate trade: less numerical reduction
  in exchange for a fully intact, honestly-analyzable signal. R-peak
  detection uses a 5–40 Hz bandpass followed by `scipy.signal.find_peaks`
  with a configurable minimum distance (400 ms default) and prominence
  (auto: 0.3 × std, or manual).
  ECG removal is only meaningful during low-activation segments: during strong
  contractions, motor-unit action potentials and QRS complexes overlap too
  much in frequency and morphology to separate, so this is documented as a
  known limitation rather than treated as a bug. This isn't just a "removal
  is less effective" limitation — it's upstream of that: FTS's own R-peak
  detection (`find_peaks` on the EMG's own low-pass copy) struggles to tell
  an R-peak apart from a motor-unit action potential during strong
  contraction, so the method can't reliably find *where* to subtract, let
  alone how well. Self-referential detection (using the EMG signal to find
  its own artifact) has no fix for this from within the EMG signal alone.

  `sync.py`'s Polar H10 ECG channel (§11) addresses **half** of this — the
  *timing* half: it marks true R-peak timing directly, independent of EMG
  amplitude, so FTS can be told *when* the peak is rather than having to
  infer it from a channel where the peak is masked. It does **not** solve
  the other half — the *amplitude/shape* of the template to subtract. FTS's
  template is still derived from the EMG channel's own 40 Hz low-pass copy,
  and during a strong contraction that copy is dominated by the EMG
  envelope itself, so the true QRS amplitude is masked there too, even once
  its timing is known from Polar. The Polar channel's own ECG amplitude
  can't be substituted directly either — it's recorded from different
  electrodes, at a different gain, through different tissue conduction, so
  it doesn't correspond 1:1 to the artifact's amplitude as it actually
  appears in the contaminated EMG channel; using it would need an unsolved
  scaling/calibration step. So: `sync.py` narrows the problem to "when," not
  the whole problem — "how much to subtract" during strong contraction
  remains open. A proposed solution and validation plan for this is in §11,
  alongside `sync.py` itself, since it depends entirely on the Polar
  channel `sync.py` provides.
- **Onset/offset detection is not used for the CCFM target muscle:** the
  deep cervical flexors are the muscle of clinical interest, and the SCM
  (superficial, measured) may legitimately stay silent during a correctly
  performed maneuver. The relevant evidence is therefore *low* RMS, not an
  onset event — automatic threshold-based detection is inappropriate for this
  protocol.
- **RMS windowing for MVC reference:** a fixed central plateau epoch — a
  predetermined amount is discarded from the start and end of the contraction
  (ramp-up/ramp-down), and a single scalar RMS/mean is computed from the
  remaining middle portion. This is consistent with general isometric-EMG
  practice and sidesteps phase-shift concerns entirely, since phase shift only
  matters when producing a continuous envelope for event timing, not when
  extracting one scalar from a pre-defined window. Parameters are pre-committed
  and applied uniformly across trials, with visual overlay verification as the
  safeguard against the one residual risk (epoch edges clipping into the ramp).
  **Implemented (Stage 8)** as `plato_bul()` (`detection.py`) plus
  `flagging.py`'s "Ortayı İşaretle" button — see §8.2 and §8.5 for the two
  selectable trim rules and §10 for how the resulting RMS feeds MVC
  referencing.
- **Time normalization (planned, own interface, not yet built):** even with a
  timer, participants performing the "same" task vary in actual duration by
  tens to hundreds of milliseconds, sometimes seconds. The plan is percent-
  of-cycle normalization: mark the start and end of each trial, then
  resample each one onto a common 100-point axis (0–100 %), so trials of
  different real durations become directly comparable point-by-point and
  can be ensemble-averaged.

  > **Correction to an earlier note:** this had been recorded as running via
  > `scipy.signal.resample_poly()`, silently inside ensemble averaging. That
  > doesn't actually fit: `resample_poly()` needs a fixed rational up/down
  > ratio, suited to changing the sample rate of signals with the same
  > nominal duration — not resampling trials of *different* real lengths
  > onto a common 100-point axis. `scipy.signal.resample()` (FFT-based,
  > arbitrary length change) or interpolation (`np.interp` /
  > `scipy.interpolate`) fit the percent-of-cycle use case better. This also
  > isn't a quiet footnote inside another step — it's a planned feature with
  > its own dedicated interface, not yet built.
- **Delsys hardware dropout:** systematic ~29-sample (~13.5 ms) zero-value
  blocks were traced to a firmware version and resolved by updating to 02-04;
  recordings taken on the earlier firmware remain affected. **Distinguishing
  these from the signal's own natural zero-crossings:** real EMG is
  continuous analog noise and essentially never sits at *exactly* `0.0` for
  more than an instant, so `dropout_bul()` looks for runs of exact-zero
  samples, not near-zero ones. Exactness alone isn't quite enough — a
  genuine zero-crossing can still land on exactly one `0.0` sample by
  chance — so a minimum *consecutive* run length is also required
  (`min_uzunluk`, default 3 — confirmed from `dropout_bul()`: it groups
  zero-value indices into contiguous blocks by checking that consecutive
  indices are adjacent, i.e. gap of 1, then keeps only blocks at or above
  this length; three scattered zero samples elsewhere in the signal would
  not count). A true dropout block is far longer than that in practice
  (~29 samples, matching one wireless packet), so the length threshold is a
  comfortable margin, not a fine-tuned cutoff. `dropout.py` detects these
  blocks, marks them as NaN for honest visualization, and separately fills
  them by interpolation for processing (`scipy` filtering propagates NaN
  across an entire output, so interpolated data — not NaN-marked data — is
  what downstream steps actually receive). `dropout.py` also defines a
  standalone `dropout_maskesi_olustur()` (returns just the boolean mask,
  without the NaN-marked or interpolated array) — confirmed unused, never
  called from `gui.py`; unlike `EMGRecording.markers` (§5), this one is a
  small, self-contained function rather than a drifted data contract, so
  it's lower-stakes dead code, but still worth pruning or wiring up rather
  than leaving unreferenced.

---

## 10. MVC Normalization Flow

Two explicit stages; the Delsys-computed automatic value is deliberately not
used, in favor of researcher transparency. Concretely: Delsys's own software
doesn't expose what filtering it applies internally to produce its automatic
MVC value, and doesn't allow exporting that calibration record at all — it's
a closed number with no visible derivation. The alternative Delsys offers,
per-sensor calibration, would also have produced a different, less flexible
data shape: one MVC recording per channel, calibrated individually per
sensor, rather than one file the researcher can inspect and reprocess. So
MVC is instead recorded the same way as any regular task recording — same
file format, same pipeline, same visual verification — and the reference
value is computed here, explicitly, from that recording:

1. **Reference stage (updated, Stage 8):** load the MVC file → flag each
   contraction in `flagging.py` → run "Ortayı İşaretle" to trim ramps and
   compute each flag's plateau RMS (§8.2, §8.5) → on save, every
   `event`-type flag with a `plateau_rms_mv` is collected, grouped by
   channel, into `<recording>_mvc_ref.json`:

   ```json
   { "01 SCM R (70591)": {
       "kaynak": "P01_MVC.csv",
       "denemeler": [
         {"bayrak": "MVC1", "rms_mv": 0.0731,
          "plato_s": [5.20, 9.80], "kural": "sabit, her uçtan %20"},
         {"bayrak": "MVC2", "rms_mv": 0.0842,
          "plato_s": [15.10, 19.70], "kural": "sabit, her uçtan %20"}
       ]
     }
   }
   ```

   This file has **no aggregation** — no single "the" reference value is
   chosen here (no max, no mean). It is a deliberately raw, per-trial
   record; the file is produced whenever at least one plateau-RMS flag
   exists, and is silent (not created) otherwise. Choosing which trial(s)
   to use, and how to combine them, is left to the task stage below —
   this keeps the file a portable, inspectable summary rather than a
   second place where a normalization decision is silently made.

   **Correction (2026-09-25):** `plateau_rms_mv` used to be computed from
   the signal shown on screen. With smoothing on, that was the RMS of an
   ARV-type envelope (≈0.80 × the true RMS, window-dependent), while the
   numerator of %MVC was the true RMS — inflating %MVC by ≈25 % and making
   it depend on a display setting. The plateau is still *found* on the
   shown signal, but its RMS is now computed from the conditioned signal
   with the same function and window as the table's RMS; the two are
   bit-identical for the same flag. **`_mvc_ref.json` files produced with
   smoothing on before this fix must be regenerated.**

   *(Superseded: the original single-stage description — "load the MVC
   file → run it through the pipeline → take the maximum processed value
   per channel as the reference → store the value in a CSV" — predates
   the plateau-RMS mechanism and no longer describes the flow.)*

2. **Task stage (import + aggregation — implemented in `flagging.py`,
   Increment 4a):** load the task file → import a `<recording>_mvc_ref.json`
   produced by step 1 → *choose* an aggregate (max or mean across
   `denemeler`) → apply `%MVC = (emg / mvc_ref) × 100`, per SENIAM
   convention (0–100 output, not 0–1). Channels without a matching
   reference fall back to mV; the y-axis is scaled explicitly so the
   normalization is visually verifiable.

   Confirmed against `flagging.py`: the fallback is per channel
   (`_kok_gosterim()` — a channel without a reference stays in mV while
   others show %MVC), and the y-axis is set explicitly (ceiling at least
   100, extended if the data exceed it, with a dotted 100 %MVC line).

   > **Open gap:** the aggregate choice (max vs mean) is **not stored** in
   > any output — `_oznicelikler.csv` records the resulting reference value
   > (`mik_ref_mv`) and `kok_yuzde_mik`, but not how it was aggregated.
   > The value is reproducible from `_mvc_ref.json`, but the choice itself
   > should be written to the markers `meta` or the CSV.

---

## 11. Synchronization (`sync.py`)

Scoped exclusively to aligning EMG time with a Polar H10 ECG reference — used
when Delsys-only R-peak detection during strong contractions is unreliable
(motor-unit action potentials overlap QRS morphology). Currently a standalone
program (`python sync.py`), not yet wired into `gui.py`; the only planned
hand-off is its output R-peak timestamps, to be consumed by `ecg.py`'s FTS
step (§9) instead of `ecg.py`'s own Delsys-only R-peak detector. This fixes
*when* a beat occurred during strong contraction, not *how large* FTS's
subtracted template should be there — see §9's caveat: that half of the
problem is still open.

- **Channel-quality metric:** amplitude separation × RR-interval consistency
  ratio (coefficient-of-variation based), not amplitude alone — an
  amplitude-only metric was found to prefer a noisy artificial channel over a
  genuinely clean one.
- **Session-level control:** synchronization is triggered once per session, not
  per channel, since R-peak timing is shared across all channels.
- **Coarse-lock bug (resolved):** `kaba_kilit_bul()`'s cross-correlation call
  used `scipy.signal.correlate(..., mode="valid")`, which happened to work when
  the EMG recording was much longer than the Polar recording, but collapsed
  the correlation output to a handful of samples — and therefore picked the
  wrong lag — whenever both recordings were close to equal length. Switching
  to `mode="full"` with correct lag-axis reconstruction resolved this; measured
  residual alignment error after the fix is 2–3 ms.

### 11.1 Proposed: amplitude scaling for FTS during strong contraction (not yet built)

§9 documents that `sync.py`'s R-peak timestamps only solve *when* a beat
occurred during strong contraction, not *how large* FTS's subtracted
template should be — the template is still derived from the EMG channel's
own 40 Hz low-pass copy, which is itself swamped by the contraction's
amplitude at exactly the moments this matters most.

**Proposed approach:** in the quiet part of a recording — baseline noise
only, no muscle activity — both the Polar channel and the EMG channel show
the same heartbeat. The amplitude ratio between them there
(`r = EMG_amplitude / Polar_amplitude`) could be computed once and carried
forward as the scaling factor applied to the Polar waveform during
contraction, giving FTS a scaled template with both correct timing and an
amplitude grounded in the recording itself, rather than none at all.

**Why this might work reasonably well:** bipolar (single differential) EMG
detection suppresses ECG largely through common-mode rejection (CMRR) — ECG
arrives at the two closely-spaced electrodes as a near-identical, far-field
signal, so the differential amplifier cancels most of it the same way it
cancels other common-mode interference, which is most of why the artifact
is manageable at all rather than dominating the recording. Separately, and
for a different reason: beat-to-beat *amplitude* of the surviving artifact
tends to be fairly consistent regardless of contraction — this isn't a
consequence of CMRR, it follows from the heart's own all-or-none principle
(each cardiac depolarization either fires fully or not at all, so QRS
amplitude per beat is fairly stable). What actually changes with exertion is
heart *rate* — an autonomic/electrical control effect on inter-beat timing,
not on the amplitude of individual beats. So a scaling ratio computed once
from a quiet stretch may hold up reasonably well across the rest of the
recording, more so than the timing/interval side.

**Why it might not:** single differential detection doesn't just shrink the
ECG artifact, it distorts its shape — often only the R-spike survives
clearly, with the P and T waves largely cancelled out, so what the EMG
channel offers as a "template" is closer to an isolated spike than a full
PQRST complex. Separately, some study events (e.g. an isometric contraction
itself) are physiologically capable of shifting heart rate — but this
mainly shows up as beat-to-beat *interval* variability, not necessarily
amplitude, so it's more a concern for the timing side than for the scaling
approach proposed here.

Taken together, this looks like a reasonably promising method rather than a
solved one — plausible enough to be worth building and testing, not
something to treat as reliable before the validation below. This
is not expected to be fully correct — the ratio isn't strictly constant
through a contraction, since tissue impedance, blood flow, and
electrode-skin contact can all shift slightly as the muscle contracts — but
a partial, evidence-based correction is better than none.

**Validation plan, in two stages, before trusting it on real Polar data:**
1. *Synthetic:* the planned synthetic sEMG generator (Falla/Jull
   parameters) can inject a known-amplitude PQRST template plus a
   known-scaled "fake Polar channel," giving exact ground truth to check
   how well the method recovers the true injected amplitude.
2. *Hybrid real+real:* mixing a real, openly available ECG recording
   (e.g. PhysioNet's MIT-BIH Arrhythmia Database, the long-standing
   standard for this) into one of this project's own real contraction EMG
   recordings, at a known mixing ratio. This keeps real ECG morphology
   irregularities and real motor-unit recruitment patterns intact, while
   still controlling exactly how much artifact was added — arguably a
   stronger check than the purely synthetic case, and a standard technique
   in the field (semi-synthetic / hybrid validation).

---

## 12. Feature Extraction (`features.py`)

All functions operate on a single-channel EMG segment already cut to a
flagged region (`np.ndarray`, plus `fs` and a time axis) — never the whole
signal. Amplitude and timing features (mean, peak, IEMG, onset) need the
**rectified or enveloped** signal — peak and mean are meaningless on a raw
signal that swings through zero. Frequency features are the opposite: they
need the **filtered, unrectified** signal, because rectification is
nonlinear and adds DC, an envelope component and harmonics to the spectrum.
RMS is the same either way (√mean(|x|²) = √mean(x²)).

**Fix (2026-09-25):** `flagging.py` passed `np.abs(...)` of the region to
`frekans_ozellikleri()`, so every MDF/MNF in the table, feature strip and
`_oznicelikler.csv` came from the rectified spectrum (on a synthetic
20–450 Hz test signal: MNF 303 Hz instead of 218 Hz). The module docstring
("all functions operate on the rectified signal") is the likely origin and
was corrected. `gui.py`'s MNF/MDF trend was already computed on the
unrectified signal.

Confirmed against the real module header:

| Function | Computes |
|---|---|
| `genlik_ozellikleri()` | RMS (KOK), mean amplitude, peak, IEMG, %MVC (%MİK) |
| `zaman_ozellikleri()` | Onset time, offset time, time-to-peak |
| `frekans_ozellikleri()` | Median frequency (MDF), mean frequency (MNF), peak frequency, total power |
| `ozellik_hesapla()` | Combines all of the above into one dict, in a single call |
| `yorgunluk_indeksi()` | Multi-epoch median-frequency trend (S5, fatigue) |

**Five-question framework** these map to, guiding what gets extracted for a
flagged region:

| Question | Feature(s) |
|---|---|
| S1 — Is the muscle active? | Onset/offset detection, RMS-vs-threshold comparison |
| S2 — More or less active (than what)? | RMS, mean, IEMG comparison |
| S3 — When did it turn on/off? | Onset time, offset time, time-to-peak |
| S4 — How active? | %MVC, peak amplitude |
| S5 — Is there fatigue? | Median/mean frequency trend across multiple epochs |

**Frequency-feature epoch rule (confirmed against the function body):**
always computed on the flagged region, never on the whole signal (which
would mix contraction, rest, and noise). Welch uses a **1 s window with
50 % overlap**, so at least **2 s** is needed for two windows; epochs
**< 2 s** use a periodogram instead. The band is limited to 10–500 Hz
(capped below Nyquist) before MNF/MDF (`pipeline.mnf_mdf_hesapla()`).
An earlier revision of this section, and `features.py`'s own comments,
said 1 s; the code has always used 2 s, and the comments were corrected. Reference: Phinyomark, Thongpanja, Hu, Phukpattaranont
& Limsakul (2012), "The Usefulness of Mean and Median Frequencies in
Electromyography Analysis," *IntechOpen*, DOI: 10.5772/50639, open access at
https://www.intechopen.com/chapters/40123; and BIOPAC Application Note 118,
https://www.biopac.com/wp-content/uploads/app118.pdf.


---

## 13. Reference Libraries (design reference, not a dependency)

- **`pyemgpipeline`** (Wu et al., 2022, JOSS) — used as a checklist for step
  order, parameter defaults, and DC-offset-removal implementation. Its
  envelope implementation (Butterworth low-pass rather than moving average)
  was consulted and deliberately **not** followed — see §9. Adopting it
  wholesale (writing a GUI around it rather than a custom pipeline) was
  considered early on and rejected — it's a checklist to consult, not a
  dependency to build on, because of specific gaps relative to this
  project's needs:

  | Gap in `pyemgpipeline` | Why it mattered here |
  |---|---|
  | No ECG artifact removal | Critical for SCM/upper-trapezius recordings (§9) — not offered at all |
  | No onset/repetition detection | Already had a working, tailored implementation (§8.3) |
  | No frequency-domain features | No MDF/MNF/fatigue index (§12) — needed for the CCFM fatigue "aha moment" (§9) |
  | Delsys CSV format | Not supported; would need a custom parser regardless, undermining the point of adopting it |
  | Amplitude normalization method | Its default (Devaprakash et al., 2016 — uses all trials to bound 100 % MVC) doesn't match this project's CCFM-specific submaximal-reference approach (§10) |
  | Fixed, non-interactive pipeline | Steps can't be selectively applied/skipped/inspected mid-run the way the GUI's per-step "Apply" and visual verification require (§2, §6) |

  This table is also, directly, the "what gap does this fill" case for the
  JOSS submission: `pyemgpipeline` is itself a JOSS-published package
  covering general EMG conditioning, so the honest originality claim here
  isn't "a better generic pipeline" — it's the combination the gaps above
  point to: ECG artifact handling, Delsys-specific hardware support,
  frequency/fatigue features, and an interactive, visually-verified GUI
  workflow, aimed at CCFM-style protocols specifically.
- **`ReSurfEMG`** — used for algorithm validation.
- **`neurokit2`** — evaluated for R-peak detection and found unsuitable, since
  its algorithms assume full QRS morphology that Delsys hardware filtering has
  already removed, leaving only narrow R-peak spikes at low power; a custom
  `scipy.signal.find_peaks`-based detector was built and validated against
  real data instead.

---

## 14. Licensing and Repository

- **License:** GPL-3.0. (An earlier internal draft of this document listed MIT
  as a placeholder; GPL-3.0 is the decision that stands.)
- **Repository name:** `simple-semg-analyser-gui`.
- **Repository description:** "Surface EMG (sEMG) time-domain signal
  processing, region flagging, and feature extraction (RMS, median/mean
  frequency) for bipolar single-channel recordings." (An earlier version of
  this description named Delsys Trigno specifically; it was removed on GitHub
  to reflect the device-agnostic design goal in §1.)
- **JOSS timeline requirement:** JOSS requires at least six months of
  publicly visible, distributed commit history; a "finish privately, then
  upload" approach does not satisfy this, so the repository was made public
  immediately once `.gitignore` (excluding all participant data) was in place,
  ahead of the first substantive code commit.
- **Trademark / data-format note:** the project reads plain-text CSV exported
  by Delsys software; it does not use any Delsys API, SDK, or proprietary
  library. This was assessed as low legal risk for interoperability, on the
  same basis as existing third-party tools that read the same export format.
- **AI-assisted development disclosure:** portions of this codebase were
  implemented with AI assistance (Claude), with the researcher making design
  decisions, reviewing and correcting implementations, and directing all
  architectural choices recorded in this document. See
  `docs/ai_assisted_development.md` for the disclosure statement prepared for
  JOSS review.

---

## 15. Internationalization (Planned)

The current Turkish-only UI and CSV output (see the note at the top of this
document) is a transitional state, not the target. Planned end state: **both
Turkish and English side by side**, not an English-only rewrite.

- **CSV column headers:** the Turkish headers (`kok_mv`, `mdf_hz`, `tip`,
  `kaynak`, etc.) remain the internal/working format, so existing downstream
  analysis scripts never break. A single translation dictionary
  (`{"kok_mv": "rms_mv", "tip": "type", ...}`) is applied only at
  export/publication time to produce an English-headed copy — e.g. for the
  synthetic teaching dataset or any data shared alongside the JOSS submission.
  This needs no pipeline changes, only a lookup table and a write-time choice.
- **UI strings:** every UI string is planned to move into a `{"tr": "...",
  "en": "..."}` lookup, selected by a single language flag, rather than being
  hard-coded in `gui.py` / `flagging.py` as it is now. The authoritative source
  for English-side terminology is `semg_sozluk_ana.md` (the project's own sEMG
  terminology dictionary), since several existing terms depart deliberately
  from general-literature usage and that dictionary already documents the
  rationale for each choice.
- **Sequencing:** this is the **last** step in the JOSS-readiness plan, after
  the codebase itself is translated to English (variable/function names).
  That translation pass is planned using Zed's "Find All References" to
  locate every definition and call site — done as many small, per-file (or
  per-function) commits rather than one large rewrite, so each rename is
  independently reviewable and the commit history itself documents a
  systematic English translation pass for JOSS reviewers. Going through the
  codebase this way is also expected to surface latent bugs worth fixing
  along the way, the same way earlier passes did (§9, §11).

---

## 16. Out of Scope (Current)

- Conduction velocity (CV) estimation — requires a linear electrode array with
  known inter-electrode distance and microsecond-synchronous sampling, which
  the Trigno Avanti's single bipolar channels cannot provide; not aligned with
  the core CCFM hypothesis in any case.
- Delsys SDK-based audio-instruction synchronization (`audio_file` sync
  method).
- Real-time / online analysis.
- Reporting export (HTML/PDF).
- Multi-site or multi-user support.
- **Cross-platform packaging: dropped, in favor of documentation.** Building
  and maintaining installers (PyInstaller, py2app + notarization, and Flatpak)
  is a real, ongoing maintenance burden for a solo developer, and disproportionate 
  to the actual audience:
  this is a research/teaching tool for a specific course and a specific line
  of research, realistically reaching a population in the tens, not the
  100,000s a packaged installer would be worth building for. The plan
  instead is a thorough, step-by-step installation guide aimed at
  domain-expert, non-programmer researchers — people who understand sEMG and
  CCFM but have never run a Python script — walking through installing
  Python/dependencies and launching the GUI directly from source. No
  installer is planned.
