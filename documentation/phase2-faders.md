# Phase 2 — Fader mapping design

Decisions from the 2026-05-21 design conversation. **Implemented and first-pass hardware-tested 2026-05-21.** Two design points were overturned by that test and are marked **[SUPERSEDED]** inline below: the Scene Launch *keylight* (the buttons can't dim) and *Shift-latched pan* (Shift fires built-in firmware modes, so it's unusable). Pan is now reached by a volume → pan → off tap cycle on the row's Scene Launch button. See the second-pass note in [../CLAUDE.md](../CLAUDE.md) for the full account.

## Mapping

- **Row selection via Scene Launch buttons** (the 8 buttons to the right of the 8×8 grid — notes `0x70–0x77`, single-color green LEDs; see [primer.md](primer.md#inbound-device--host)). One row active at a time; tap to select.
  - **LED scheme. [SUPERSEDED 2026-05-21 — keylight removed.]** Hardware confirmed the Scene Launch buttons ignore the brightness nibble, so the dim-unselected / bright-selected keylight idea is gone (along with the `scene_keylight` setting and the `SCENE_DIM_CHANNEL`/`SCENE_BRIGHT_CHANNEL` constants). The shipping scheme is state-only on channel 0: **unselected = off, selected-volume = solid on, selected-pan = blink.** Downside accepted: with nothing selected, no row button is lit, so they aren't findable in a blackout — the hardware offers no dimming to fix that.
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

## Pan mode

LiSP exposes per-cue stereo balance via the `AudioPan` GstMediaElement ([../linux-show-player/lisp/plugins/gst_backend/elements/audio_pan.py:26-48](../linux-show-player/lisp/plugins/gst_backend/elements/audio_pan.py#L26-L48)), with a `panorama` property in `[-1.0, +1.0]` (default `0.0`). It already has its own per-cue Settings tab ("Audio Pan"), so this is a first-class user feature. The plugin lets the operator ride pan from the faders too.

**[SUPERSEDED 2026-05-21 — Shift dropped, replaced by a tap cycle.]** The original design entered pan with a *Shift-tap* on the Scene Launch button. Hardware testing killed that: `Shift +` certain Scene Launch buttons triggers the unit's built-in firmware modes (e.g. a demo mode), so Shift can't be repurposed at all. The shipping scheme uses **repeated taps of the same row button to cycle volume → pan → off**, and a tap on a *different* row jumps straight to it in volume mode. The bullets below describe the intent (LED, takeover, detent); only the *entry gesture* changed.

- **Tap a selected volume-mode row's Scene Launch** to put it into **pan mode**. The Scene Launch LED blinks (instead of solid) to signal the modal state. Sliders for that row now ride pan instead of volume. (A further tap deselects the row entirely.)
- **A row always starts in volume mode** when freshly selected — pan is the non-default and shouldn't surprise the operator on a fresh selection.
- **Single active mode.** Selecting a different row drops the previous selection, so only one row is live at a time (the code tracks one `_current_mode`, not a per-row array).
- **Soft takeover still applies.** Same hunt-and-latch as for volume, against the cue's current `panorama` value. CC 0→127 maps linearly to `-1.0…+1.0` with `64 → 0.0`.
- **Center-detent tolerance.** 0.0 (center) is a natural snap point for pan, but non-motorized faders can't physically detent. Soften the latch around `CC == 64` with a ±1 tolerance so "near-center" captures cleanly to true center; without this, the operator will land on `0.008` and wonder why their effect isn't dead-centre.

### Caveats to surface in the UI

- **Stereo-only.** `audiopanorama` is a stereo panpot, not a multichannel azimuth pan. Fine for L/R stage rigs; doesn't position sound in surround. If anyone asks for surround positioning, that's a different element entirely.
- **7-bit CC resolution.** 128 steps across the full range is fine for coarse positioning ("voice X is stage-left"), but will quantise audibly on slow creeping pans across a long cue. Acceptable for v2.0; flag it.
- **Per-cue availability — confirmed and surfaced (2026-05-21).** `AudioPan` is **not** in LiSP's default pipeline (`["Volume", "Equalizer10", "DbMeter", "AutoSink"]`), so pan is unavailable on every cue out of the box until the user adds the element — globally via Preferences → GStreamer (applies to *new* cues only) or per-cue in its media settings. Volume, by contrast, *is* in the default pipeline, so volume mode works out of the box. To stop pan-mode silence becoming a troubleshooting black hole, the plugin now logs a `WARNING` when a row freshly enters pan mode and not one of its cues has an `AudioPan` element (`_warn_if_pan_unavailable` / `_row_has_pan`). LiSP routes `WARNING` to the status bar and bumps the log-viewer warning count, so it's discoverable without a modal. Pads that individually lack `AudioPan` still just show their normal state in pan mode (no hunting pulse) — the per-pad "this fader does nothing here" signal.

## New runtime state

- `_selected_row: int | None` — currently selected row, `None` if none.
- `_current_mode: "volume" | "pan"` — mode of the selected row, default `"volume"`. Cycled by tapping the selected row's Scene Launch button; reset to `"volume"` on every fresh row selection. *(Implemented as a single value, not the per-row `_row_mode[8]` array originally sketched — only one row is live at a time.)*
- `_slider_latched[8]: bool` — per-slider latch state, reset to all `False` on row change **and on mode change** (switching a row from volume to pan re-arms takeover against the new target value).
- `_slider_position[8]: int` — last-known physical CC value per slider, needed for the takeover crossing check (compare previous-and-current against the stored cue value).
- ~~`_shift_held`~~ — **removed 2026-05-21**; Shift is unusable on hardware (see the pan-mode note above).

No new persistent (session-file) state. Cue **pan** is the existing serialized `panorama` property; cue **volume** rides the existing serialized baseline `volume` property (the plugin originally rode the runtime `live_volume`, but that's reset to baseline on every cue stop and isn't saved — so a fader move was lost on replay; switched to the baseline `volume` on 2026-05-21).


## Possible improvements

1. ~~**Hunting indicator encoding** (hue shift vs. behavior nibble).~~ **Resolved 2026-05-21:** direction-by-color (white armed / blue push-up / magenta pull-down, slow pulse) — see the soft-takeover section above. Remaining sub-question for hardware: are blue/magenta legible enough at a glance in a dark booth, and is blue=up / magenta=down the right mnemonic, or should it be flipped / surfaced in the UI hint?
2. **Fade ramp.** Should slider moves apply instantly, or interpolate over a few ms to avoid zipper noise on coarse 7-bit CC values? Probably interpolate; LiSP's existing volume-fade machinery may already handle this.
3. **Multi-page interaction.** When the user switches Cart Layout pages, the selected row stays the same (row index is global) but the cues under it change — sliders go back to inactive on page change, same as row change.
4. **Pan-mode visual distinction on pads.** While a row is in pan mode, should the pads themselves indicate the mode somehow (e.g. a subtle hue tint, or a dim secondary color), or is the Scene Launch blink enough? Leaning "Scene Launch blink is enough" to avoid fighting the existing per-cue color palette — but worth a hardware test.
5. **Center-detent tolerance value.** ±1 CC around the center (`64`) is a starting point; may need widening to ±2 or ±3 if operators find it too easy to miss. Empirical.