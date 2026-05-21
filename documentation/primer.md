# LiSP × APC Mini mk2 Plugin — Project Primer

## Project goal

Build a **Linux Show Player (LiSP)** plugin that gives plug-and-play integration with the **Akai APC Mini mk2** controller for the **Cart Layout**, with **zero per-cue MIDI configuration**.

Press a pad → corresponding cart fires. Cue state → pad LED reflects it (color + behavior). Plug in, enable plugin, done.

## Why a plugin (and not the alternatives)

LiSP's native MIDI binding is **per-cue**: every cue gets its own MIDI message assigned via `Cue Controls > MIDI > Capture`. For 64 carts this is tedious and breaks on reorder.

Considered and rejected:
- **Manual capture per cue** — works but fragile; breaks when carts are reordered.
- **Bulk multi-edit (CTRL+SHIFT+E)** — only edits shared options, can't assign *different* notes per cue.
- **Presets** — store fixed values, would need 64 separate presets.
- **Session-file post-processing** (script the JSON) — works for triggers but doesn't help with LED feedback, and it's a one-shot per show file.

A plugin gives positional mapping, bidirectional LED feedback, reorder-safety, and zero per-cue config.

## Scope

**In scope (v1):**
- 8×8 grid pads (notes 0–63) trigger carts by `(row, col)` position on the active Cart page.
- Pad LEDs reflect cue state: idle, running, paused, error.
- Plugin auto-activates when the current layout is Cart, deactivates otherwise.
- Settings: enable toggle, default colors.

**Out of scope for v1:**
- Drum / Note modes (Ableton-centric).
- Multi-page navigation (user only needs 1 page = 64 cues).
- Per-cue custom color (nice-to-have, phase 2).
- Fader mappings (TBD, phase 2).

## APC Mini mk2 MIDI reference

Source: <https://cdn.inmusicbrands.com/akai/attachments/APC%20mini%20mk2%20-%20Communication%20Protocol%20-%20v1.0.pdf>

### Inbound (device → host)

| Element | MIDI |
|---|---|
| Clip Launch pads (8×8) | Note 0x00–0x3F, Ch 0. **Note 0 = bottom-left**, ascending L→R, B→T. |
| Track Buttons 1–8 | Note 0x64–0x6B, Ch 0 |
| Scene Launch 1–8 | Note 0x70–0x77, Ch 0 |
| Shift | Note 0x7A |
| Faders 1–8 + Master (9) | CC 0x30–0x38, Ch 0 |

### Outbound (host → device, LED control)

Pad LEDs use Note-On `9X NN VV`:
- `X` (channel nibble) = behavior:
  - `0` = 10% solid, `1` = 25%, `2` = 50%, `3` = 65%, `4` = 75%, `5` = 90%, `6` = 100% solid
  - `7–10` = pulsing (1/16, 1/8, 1/4, 1/2)
  - `11–15` = blinking (1/24, 1/16, 1/8, 1/4, 1/2)
- `NN` = pad note `0x00–0x3F`
- `VV` = velocity = color from a fixed 128-entry palette. Key values:
  - `0` = off / black
  - `3` = white
  - `5` = red
  - `13` = yellow
  - `21` = green
  - `45` = blue
  - `53` = magenta
  - `87` = bright green (`#00FF00`)
  - Full palette in the protocol PDF, page 4–5.

Track Button LEDs are single-color **red**: `90 NN VV` where `VV`: 0=off, 1=on, 2=blink.
Scene Launch LEDs are single-color **green**: same `90 NN VV` convention.

### Grid coordinate conversion

APC: note 0 = bottom-left, so row-from-bottom = `note // 8`, col = `note % 8`.
Cart: `(0,0)` = top-left.

```
cart_row = 7 - (note // 8)
cart_col = note % 8
note     = (7 - cart_row) * 8 + cart_col
```

## LiSP reference

- Repo: <https://github.com/FrancescoCeruti/linux-show-player>
- Latest stable: **0.6.5** (April 2025)
- Stack: Python 3, PyQt5, GStreamer
- Plugins live in `lisp/plugins/<plugin_name>/`
- User docs: <https://linux-show-player-users.readthedocs.io/>

Key existing docs to read:
- Cart Layout: <https://linux-show-player-users.readthedocs.io/en/latest/cart_layout.html>
- Cue Controls (per-cue MIDI/OSC/keyboard — closest existing equivalent to what we're building): <https://linux-show-player-users.readthedocs.io/en/latest/plugins/cue_controls.html>
- Presets: <https://linux-show-player-users.readthedocs.io/en/latest/plugins/presets.html>

## Proposed plugin layout

```
apc_mini_cart/
├── __init__.py          # Plugin metadata + entry point
├── apc_mini_cart.py     # Main plugin class
├── led_feedback.py      # Cue state → outbound MIDI
├── color_palette.py     # APC mk2 velocity→color constants
└── settings.py          # PyQt settings UI
```

### Inbound flow

1. Register as a MIDI input handler via LiSP's existing `Midi` plugin.
2. On `note_on`, Ch 0, note 0–63:
   - Compute `(row, col)` from note.
   - Look up cue at `(current_page, row, col)` in the Cart Layout.
   - If present, call `cue.execute()` (respects each cue's default action).
3. Ignore non-grid messages for v1 (reserved for v2: Scene Launch, Track Buttons, Shift combos).

### Outbound flow (LED feedback)

1. Subscribe to cue lifecycle signals (`started`, `stopped`, `paused`, `error`).
2. Maintain a `{(row, col): cue_state}` map for the current page.
3. On state change, send Note-On to APC:
   - **Idle** (cue present, stopped) → Ch 0 (dim solid), velocity = configured idle color
   - **Running** → Ch 6 (100% solid), velocity = configured running color
   - **Paused** → Ch 9 (pulse 1/4), velocity = 13 (yellow)
   - **Error** → Ch 12 (blink 1/16), velocity = 5 (red)
4. On plugin activation: full refresh — paint all 64 pads based on cue presence.
5. On deactivation / Cart page change: blank all 64 pads first, then refresh.

### Settings

- Enable / disable toggle (under `File > Preferences > Plugins`).
- Idle color (default).
- Running color (default).
- Phase 2: per-cue color override (extends the cue edit dialog).

## Installation constraint (read before assuming dev environment)

Plugin installation path depends on how LiSP is installed:

- **Flatpak** (Flathub) — sandboxed; user-plugin install is non-trivial. Would require a custom Flatpak build.
- **Distro package** — usually no user-plugin path.
- **From source** (git clone + poetry) — easiest; drop plugin folder into `lisp/plugins/` and it loads.

**For development: install LiSP from source.** Production deployment decision (custom Flatpak vs source on show machine) deferred.

## Next steps (do them in this order)

### Step 1 — Survey existing plugins

**Don't write code before this is done.** Find out if someone already built this, or something close.

Things to check:
- `lisp/plugins/` in the LiSP repo — list every existing plugin, note any that touch MIDI controllers or layouts.
- <https://github.com/topics/linux-show-player> — third-party plugins indexed there.
- GitHub search: `linux-show-player apc`, `lisp plugin midi controller`, `lisp launchpad`, `linux-show-player cart midi`.
- LiSP Discussions tab and Issues tracker — search for related feature requests, draft PRs, work-in-progress branches.
- LiSP Gitter/Matrix chat archives if accessible.

If anything close exists (e.g. a Launchpad or generic grid-controller plugin), study it — it likely solves 60–80% of the same problem and the architecture lessons are reusable.


### Step 2 — Study Cart Layout source

Read the relevant LiSP source code end-to-end:
- `lisp/layouts/cart_layout/` (or wherever Cart Layout lives in the current source tree).
- `lisp/plugins/controller/` and `lisp/plugins/midi/` to understand how MIDI input is dispatched and how `Cue Controls` triggers `cue.execute()`.

Specifically find:
- How cues are stored per `(page, row, col)`.
- The lookup API for "get cue at position".
- Which signals fire on cue state changes.
- How an existing plugin registers a MIDI input handler.

**Deliverable:** `research/cart-layout-notes.md` — the 3–5 API calls / classes / signals the new plugin will need, with file:line references.

### Step 3 — Write working scaffold

Build the minimum that proves the architecture:
- Plugin loads, appears in `Preferences > Plugins`.
- Detects when the current layout is Cart Layout; only activates then.
- On a grid pad press, the corresponding cue fires.
- **No LED feedback yet.** Strictly inbound only.

Run a manual end-to-end test: launch LiSP with a small Cart session, press a few pads, confirm cues fire correctly with the right coordinate mapping.

After the scaffold works, iterate:
1. LED feedback on state change.
2. Color logic per state (pulse for paused, blink for error).
3. Settings UI with toggle + default colors.
4. Phase 2 features.

## References

- LiSP repo: <https://github.com/FrancescoCeruti/linux-show-player>
- LiSP user docs: <https://linux-show-player-users.readthedocs.io/>
- Cart Layout: <https://linux-show-player-users.readthedocs.io/en/latest/cart_layout.html>
- Cue Controls: <https://linux-show-player-users.readthedocs.io/en/latest/plugins/cue_controls.html>
- APC mini mk2 protocol PDF: <https://cdn.inmusicbrands.com/akai/attachments/APC%20mini%20mk2%20-%20Communication%20Protocol%20-%20v1.0.pdf>
- APC mini mk2 product page: <https://www.akaipro.com/apc-mini-mk2/>
- Bome forum mk2 reverse-engineering notes: <https://forum.bome.com/t/new-akai-pro-apc-mini-mk2-initial-led-mapping-summary/4752>
- FL Studio APC mini mk2 script (reference implementation in another host): <https://github.com/dreiekk/FL-Studio-APC-mini-mk2>