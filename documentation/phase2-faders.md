# Phase 2 — Fader mapping design

Decisions from the 2026-05-21 design conversation, captured for when Phase 2 work begins. **Nothing here is implemented yet.**

## Mapping

- **Row selection via Scene Launch buttons** (the 8 buttons to the right of the 8×8 grid — notes `0x70–0x77`, single-color green LEDs; see [primer.md](primer.md#inbound-device--host)). One row active at a time; tap to select.
  - **LED scheme (keylight, added 2026-05-21):** by default every row button is lit *dim* so it's findable in a dark booth; the selected row is *bright* (volume mode) or *blinks* (pan mode). This needs the scene LEDs to honor the brightness nibble (the Note-On channel, as the pads do) — unverified on hardware. If a unit ignores it (dim == bright, so you can't tell the selected row in volume mode), the `scene_keylight` setting (Preferences → APC Mini Cart) turns keylight off and reverts to the original "lit only when selected" behavior: off when unselected, solid when selected-volume, blink when selected-pan. The Shift button has **no addressable LED** on the mk2, so it can't be lit at all — pan-mode arming is shown only via the selected row's blink.
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
- **Operator feedback for hunting sliders — implemented 2026-05-21 (direction by color).** Mappable pads in the selected row show a hunting indicator until their fader latches: a slow "breathing" pulse (behavior nibble 10, pulse 1/2 — slower than the 1/4 pulse used for paused) in a color that tells the operator which way to move the fader:
  - **white** = armed but untouched (position unknown — the APC doesn't report fader position until it moves, so direction can't be shown until the first nudge);
  - **blue** = fader is below the stored value → push **up** to catch;
  - **magenta** = fader is above the stored value → pull **down** to catch.
  On catch (latch) the pad snaps back to its normal cue-state color, which doubles as the "you've got it" confirmation. Unmappable pads (no Volume/AudioPan element) and pads outside the selected row keep their normal state — an unmappable pad showing its normal colour is itself the signal that its fader does nothing. **Tradeoff:** while hunting, the indicator overrides the cue-state colour on the selected row (a running cue you're about to ride won't show green until the fader catches) — acceptable because the catch guidance is what the operator needs at that moment, and the Scene Launch LED already marks the row as live.

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
- **Per-cue availability — confirmed and surfaced (2026-05-21).** `AudioPan` is **not** in LiSP's default pipeline (`["Volume", "Equalizer10", "DbMeter", "AutoSink"]`), so pan is unavailable on every cue out of the box until the user adds the element — globally via Preferences → GStreamer (applies to *new* cues only) or per-cue in its media settings. Volume, by contrast, *is* in the default pipeline, so volume mode works out of the box. To stop pan-mode silence becoming a troubleshooting black hole, the plugin now logs a `WARNING` when a row freshly enters pan mode and not one of its cues has an `AudioPan` element (`_warn_if_pan_unavailable` / `_row_has_pan`). LiSP routes `WARNING` to the status bar and bumps the log-viewer warning count, so it's discoverable without a modal. Pads that individually lack `AudioPan` still just show their normal state in pan mode (no hunting pulse) — the per-pad "this fader does nothing here" signal.

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

## Open questions for implementation time

1. **Scene Launch row ordering.** Primer lists "Scene Launch 1–8" notes `0x70–0x77` but does not specify whether button 1 is top or bottom. Verify against hardware; the Akai protocol PDF is the authority.
2. ~~**Hunting indicator encoding** (hue shift vs. behavior nibble).~~ **Resolved 2026-05-21:** direction-by-color (white armed / blue push-up / magenta pull-down, slow pulse) — see the soft-takeover section above. Remaining sub-question for hardware: are blue/magenta legible enough at a glance in a dark booth, and is blue=up / magenta=down the right mnemonic, or should it be flipped / surfaced in the UI hint?
3. **Fade ramp.** Should slider moves apply instantly, or interpolate over a few ms to avoid zipper noise on coarse 7-bit CC values? Probably interpolate; LiSP's existing volume-fade machinery may already handle this.
4. **Multi-page interaction.** When the user switches Cart Layout pages, the selected row stays the same (row index is global) but the cues under it change — sliders go back to inactive on page change, same as row change.
5. ~~**`AudioPan` availability on MediaCues.**~~ **Resolved 2026-05-21:** not in the default pipeline → unavailable until the user adds it. Plugin now warns (status bar + log) when a row enters pan mode with no `AudioPan` present anywhere in it.
6. **Pan-mode visual distinction on pads.** While a row is in pan mode, should the pads themselves indicate the mode somehow (e.g. a subtle hue tint, or a dim secondary color), or is the Scene Launch blink enough? Leaning "Scene Launch blink is enough" to avoid fighting the existing per-cue color palette — but worth a hardware test.
7. **Center-detent tolerance value.** ±1 CC around the center (`64`) is a starting point; may need widening to ±2 or ±3 if operators find it too easy to miss. Empirical.
8. **Scene Launch LED brightness support (keylight).** The dim-unselected / bright-selected keylight assumes the scene buttons honor the Note-On channel as a brightness nibble (as the pads do). Unverified. Test: with a row selected, do the unselected buttons (`SCENE_DIM_CHANNEL = 1`, 25%) look clearly dimmer than the selected one (`SCENE_BRIGHT_CHANNEL = 6`, 100%)? If they look identical, or if non-channel-0 messages are ignored entirely (buttons don't update), turn `scene_keylight` off — that path uses channel 0 only and is the verified-good original behavior. Tweak the two channel constants if 25%/100% isn't the right contrast.
