# Crop Window and Markers Schema (flagging.py)

**Date:** 2026-09-12
**File:** `flagging.py`
**Related:** pipeline migration ("conditioning" vs. "interpretation" step split), see `ARCHITECTURE.md` §8.4.

## Summary

`flagging.py` now has its own crop window, independent of `gui.py`'s
Step 00 preview-crop. It excludes a chosen time range (electrode
settling, envelope edge effects, etc.) from threshold suggestion,
detection, phase inference, and the contractions table — without
ever modifying the loaded recording itself. The `_markers.json` file
this module writes now stores that window (and a few other view
settings) so it is restored automatically the next time the same
recording is opened.

## Before → After

**Crop window**
- Before: did not exist. All analysis always used the full recording.
- After: `self.crop_start_s` / `self.crop_end_s` — always real second
  values, no sentinel for "no crop" (a crop of `[0, recording end]`
  *is* "no crop"). Never mutates `self.kayit.channels` / `.time`; every
  consumer re-derives the cropped view from these two numbers on
  demand via `_kirpilmis_veri()`, so no undo stack is needed.

**Single access point**
- Before: each function that needed the channel arrays and time axis
  read `self.kayit.channels` / `self.kayit.time` directly.
- After: any code that needs cropped data calls
  `_kirpilmis_veri() -> (channels: dict, time: np.ndarray)`, which
  returns both together, cropped consistently. This matters because
  index→time conversion (e.g. converting a detected window's array
  index back into seconds) breaks silently if the channel array and
  the time axis it's converted against don't come from the same
  (cropped or uncropped) source.

**`_markers.json` schema**
- Before: the file's root was the channel dict directly —
  `{"<channel name>": [<flag>, ...], ...}`.
- After: the root is `{"meta": {...}, "channels": {...}}`.
  `channels` is the same per-channel flag list as before. `meta`
  holds `source_file`, `protocol_name` (or `null`), `smoothing_ms`,
  `crop_start_s`, `crop_end_s`, `created` (ISO timestamp). On load,
  `smoothing_ms` and `crop_start_s`/`crop_end_s` are written back into
  their entry boxes automatically, clamped to the current recording's
  actual duration.
- **Breaking change:** a `_markers.json` written before this change
  has no `"meta"` key at the root and is no longer read. Opening one
  now shows a clear error instead of silently loading; the flags in
  it are not recovered automatically — re-mark and re-save.

**Contractions table**
- Added two columns, "Pencere Baş (s)" / "Pencere Son (s)": the
  intersection of a flag's own window (full bounds, or its plateau if
  one was marked) with the crop window — i.e. what the KOK/MDF/MNF
  values in that row actually came from. "Baş (s)" / "Son (s)" keep
  showing the flag's own bounds unchanged, so a flag placed across the
  crop boundary still shows the discrepancy at a glance.
- Fixed a layout bug found while adding these: the table frame had no
  `grid_propagate(False)`, so it silently grew to fit its content
  instead of respecting its fixed width. A horizontal scrollbar was
  added alongside the existing vertical one.

**Graph**
- A flag's shaded region is now clipped to the crop window before
  drawing, instead of being drawn at its raw start/end. Previously a
  flag straddling the crop boundary looked like it fully spanned its
  raw bounds even though only the intersection was ever used in any
  calculation — this violated the "what you see is what is reported"
  principle (`ARCHITECTURE.md` §2).

## Not changed

- `gui.py`'s own Step 00 preview-crop — separate mechanism, untouched.
- `protocol.py` — untouched. `fazlari_coz()` already took its time
  bounds as plain parameters, so passing it the crop window instead
  of the recording's raw start/end was enough; no anchor-resolution
  code needed to change.
- Per-flag field migration (`etiket`/`bas_s`/`son_s` → `event_name`/
  `start_s`/`end_s`) via `_bayrak_normallestir()` — unrelated to the
  root-level schema change above and still works the same way.
