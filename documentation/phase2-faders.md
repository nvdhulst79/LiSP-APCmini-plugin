# Phase 2 — Fader mapping design

Decisions from the 2026-05-21 design conversation, captured for when Phase 2 work begins. **Nothing here is implemented yet.**

## Mapping

- **Row selection via Scene Launch buttons** (the 8 buttons to the right of the 8×8 grid — notes `0x70–0x77`, single-color green LEDs; see [primer.md](primer.md#inbound-device--host)). One row active at a time; tap to select. The selected Scene Launch LED lights to indicate the active row.
- **The 8 channel faders below the grid** (CC `0x30–0x37`) map 1:1 to the 8 columns of the selected row. Slider N controls the cue at `(selected_row, N)` on the current page.
- **No master fader control.** The 9th (master) fader at CC `0x38` is intentionally unmapped — master output is handled externally on the mixer/console, and the plugin does not duplicate that knob.
- **No row selected ⇒ sliders do nothing.** Explicit selection is the whole point of the design; we do not want sliders silently riding cues when no row is lit. Inactive is the safe default; auto-follow (e.g. "row of the most-recently-triggered cue") was rejected as too magical for a show context.

## Why not the alternatives

Considered and rejected on 2026-05-21:

- **Column volumes** (slider N = volume of all cues in column N) — cues in the same column have no semantic relationship in a cart layout, so the grouping is arbitrary. User push-back was decisive.
- **Auto-assign to recently-triggered cues** (mixer-style dynamic binding) — mapping shifts under the operator's fingers; unsafe in a cued show.
- **Pad-press selects, single fader rides selected** — viable but adds a modal state and conflicts with the existing "pad press fires cue" semantics. Would need Shift or a dedicated select button.
- **User-grouped buses** (per-cue group assignment, sliders = group masters) — most flexible, most config; pulls the plugin from "zero-config" toward "another routing layer." Reserved for later if anyone asks.

The row+column scheme gets per-cue control with one button-press of context, and the physical geometry (Scene Launch button → row of pads → row of sliders below) is obvious without explanation.

## Soft takeover (pickup mode) — required

The mk2's faders are not motorized. On row select, slider positions will not match the newly-selected cues' stored volumes; without takeover, the first touch would jump volumes.

- On row select, each slider is **inactive** until its physical position crosses through the cue's current stored volume — then it **latches** and starts driving the cue.
- Latching is per-slider, not per-row: within a row, some sliders may already be latched while others are still hunting.
- On row change (or deselect), all sliders revert to inactive.
- **Operator feedback for hunting sliders.** The corresponding pad LED should indicate which way to push to catch the value. Two candidate encodings:
  - *Hue shift:* tint pad slightly one color when slider is below, another when above. Risk: conflicts with the existing idle/running/paused/error palette and the per-cue idle-color override.
  - *Behavior nibble:* keep the cue's normal color but switch to a slow pulse/blink while hunting. Cleaner, doesn't fight the palette, also works on mk1 (monochrome LEDs).
  Lean toward the behavior-nibble approach — exact pattern (pulse vs. blink, speed) TBD when implemented.

## Pan mode (Shift-latched)

LiSP exposes per-cue stereo balance via the `AudioPan` GstMediaElement ([../linux-show-player/lisp/plugins/gst_backend/elements/audio_pan.py:26-48](../linux-show-player/lisp/plugins/gst_backend/elements/audio_pan.py#L26-L48)), with a `panorama` property in `[-1.0, +1.0]` (default `0.0`). It already has its own per-cue Settings tab ("Audio Pan"), so this is a first-class user feature. The plugin should let the operator ride pan from the faders too.

- **Shift-tap a Scene Launch** to put that row into **pan mode**. The Scene Launch LED blinks (instead of solid) to signal the modal state. Sliders for that row now ride pan instead of volume.
- **Plain tap of the same Scene Launch** (or Shift-tap again) returns the row to **volume mode**.
- **Per-row mode.** One row can be in pan mode while another freshly-selected row is in volume mode. Mode is sticky per row until explicitly toggled or the row is deselected. (On deselect → re-select, the row reverts to volume mode — pan is the non-default and shouldn't surprise the operator on a fresh selection.)
- **Why latched, not momentary.** Momentary Shift means the operator must hold the button while making careful adjustments — fatiguing, and prevents two-handing the fader. Latched Shift+Scene Launch is one tap to enter, one tap to leave, hands free in between.
- **Soft takeover still applies.** Same hunt-and-latch as for volume, against the cue's current `panorama` value. CC 0→127 maps linearly to `-1.0…+1.0` with `64 → 0.0`.
- **Center-detent tolerance.** 0.0 (center) is a natural snap point for pan, but non-motorized faders can't physically detent. Soften the latch around `CC == 64` with a ±1 tolerance so "near-center" captures cleanly to true center; without this, the operator will land on `0.008` and wonder why their effect isn't dead-centre.

### Caveats to surface in the UI

- **Stereo-only.** `audiopanorama` is a stereo panpot, not a multichannel azimuth pan. Fine for L/R stage rigs; doesn't position sound in surround. If anyone asks for surround positioning, that's a different element entirely.
- **7-bit CC resolution.** 128 steps across the full range is fine for coarse positioning ("voice X is stage-left"), but will quantise audibly on slow creeping pans across a long cue. Acceptable for v2.0; flag it.
- **Per-cue availability.** Whether `AudioPan` is in a given cue's pipeline by default needs verifying (see Open questions). If absent, the row's pad LEDs in pan mode should show the "unmappable" indicator for those cells, exactly like the volume-side handling of cues with no volume property.

## New runtime state

- `_selected_row: int | None` — currently selected row, `None` if none.
- `_row_mode[8]: "volume" | "pan"` — per-row mode, default `"volume"`. Reset to `"volume"` on row deselect; toggled by Shift+Scene Launch tap.
- `_slider_latched[8]: bool` — per-slider latch state, reset to all `False` on row change **and on mode change** (switching a row from volume to pan re-arms takeover against the new target value).
- `_slider_position[8]: int` — last-known physical CC value per slider, needed for the takeover crossing check (compare previous-and-current against the stored cue value).
- `_shift_held: bool` — tracks Shift (note `0x7A`) down/up so we can distinguish "Shift-tap on Scene Launch" from "plain tap on Scene Launch."

No new persistent (session-file) state. Cue volume and pan are both existing LiSP properties.

## Cue-side compatibility

Neither volume nor pan is uniform across cue types — needs re-verifying when work begins:

- **Volume.** `MediaCue` exposes volume via its `MediaElement` chain (typically `Volume` element). `CollectionCue`, `CommandCue`, control cues, etc. have no volume concept.
- **Pan.** `MediaCue` *may* have `AudioPan` in its pipeline — needs verifying whether it's added by default or opt-in per cue. Even on a MediaCue, pan can be absent.
- The plugin should detect mappability per cue, **per mode**. A cue can be mappable in volume mode and not in pan mode (or vice versa, though that's unlikely). For unmappable cells, the slider stays inactive and the pad LED shows the "unmappable" indicator (likely: cue's normal idle color, no hunting pattern — sliders simply don't engage when that pad is in the selected row in that mode).

## Out of scope for this round

- **Per-cue "lock from fader" toggle** (operator marks a cue as not-fader-controllable). Niche; skip until asked.
- **Track Buttons** (the 8 buttons below the grid, notes `0x64–0x6B`) — no use case yet; leave unmapped.
- **Shift modal combos** — orthogonal feature; carry separately.
- **mk1 support** — same 9-fader layout, but monochrome pad LEDs make the hunting-hint scheme need an alternate encoding (probably blink-rate). Defer until anyone actually has a mk1.

## Open questions for implementation time

1. **Scene Launch row ordering.** Primer lists "Scene Launch 1–8" notes `0x70–0x77` but does not specify whether button 1 is top or bottom. Verify against hardware; the Akai protocol PDF is the authority.
2. **Hunting indicator encoding** (hue shift vs. behavior nibble — see above).
3. **Fade ramp.** Should slider moves apply instantly, or interpolate over a few ms to avoid zipper noise on coarse 7-bit CC values? Probably interpolate; LiSP's existing volume-fade machinery may already handle this.
4. **Multi-page interaction.** When the user switches Cart Layout pages, the selected row stays the same (row index is global) but the cues under it change — sliders go back to inactive on page change, same as row change.
5. **`AudioPan` availability on MediaCues.** Is it added to every MediaCue's pipeline by default, or only when the user explicitly enables it in the cue settings? Determines whether the pan-mode "unmappable" indicator is a common sight or an edge case.
6. **Pan-mode visual distinction on pads.** While a row is in pan mode, should the pads themselves indicate the mode somehow (e.g. a subtle hue tint, or a dim secondary color), or is the Scene Launch blink enough? Leaning "Scene Launch blink is enough" to avoid fighting the existing per-cue color palette — but worth a hardware test.
7. **Center-detent tolerance value.** ±1 CC around the center (`64`) is a starting point; may need widening to ±2 or ±3 if operators find it too easy to miss. Empirical.
