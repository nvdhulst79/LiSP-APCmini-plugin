# LiSP × APC Mini mk2 Plugin

Linux Show Player plugin giving plug-and-play APC Mini mk2 integration with the **Cart Layout**: pad press fires the cart at that grid position, pad LED reflects cue state. Zero per-cue MIDI configuration.

Full context: [documentation/primer.md](documentation/primer.md) — read this for goals, rejected alternatives, MIDI reference, proposed plugin layout, and rationale.

## Stack

- **Host:** Linux Show Player (LiSP), tracking the **`develop` branch** — Python ≥3.10 / PyQt5 / GStreamer. (Not `master` and not the v0.6.5 tag — `develop` is the only branch where pyliblo3 has been replaced with pure-Python `python-osc` via [PR #338](https://github.com/FrancescoCeruti/linux-show-player/pull/338), which is needed to build on Ubuntu 24+/Debian 13.)
- **Plugin source (canonical):** `apc_mini_cart/` inside this project folder. **Do not** edit files in LiSP's tree directly.
- **LiSP integration:** symlinked into the from-source install at `~/dev/linux-show-player/lisp/plugins/apc_mini_cart` → `<this project>/apc_mini_cart`. LiSP only scans `lisp/plugins/` at startup, so restart LiSP after adding/removing the symlink (editing inside the symlinked folder while LiSP runs is fine — LiSP doesn't hot-reload plugins anyway).
- **Symlink command** (run once after `apc_mini_cart/` exists):
  ```bash
  ln -s "/mnt/secundo/Projects/Toneel/LiSP APCmini plugin/apc_mini_cart" \
        ~/dev/linux-show-player/lisp/plugins/apc_mini_cart
  ```
- **Hardware:** Akai APC Mini mk2 (8×8 grid, MIDI Note 0–63 on Ch 0)

## Project status

Currently in **scaffold-written, live-test pending** phase. Inbound-only plugin exists in [apc_mini_cart/](apc_mini_cart/) and imports cleanly in the LiSP poetry venv; not yet exercised against real hardware.

### Progress tracker

- [x] **Step 1 — Survey existing plugins.** No prior APC/Launchpad/grid plugin exists for LiSP; closest signal is open issue [#259](https://github.com/FrancescoCeruti/linux-show-player/issues/259) with no implementation attached. Starting fresh, borrowing the MIDI subscription pattern from `protocol-monitor` and the APC mk2 LED color mapping from QLC+ feedback scripts. Full writeup: [research/existing-plugins.md](research/existing-plugins.md).
- [x] **Step 2 — Study Cart Layout source.** Five hooks identified with file:line refs against master: cue lookup is `app.layout.model.item((page, row, col))`, lifecycle signals are `cue.started/stopped/paused/error` (each emits the cue), inbound MIDI is `get_plugin("Midi").input.new_message` (not `received` — that doesn't exist in current source), outbound is `get_plugin("Midi").output.send(mido.Message)`, and layout activation is detected via `app.session_created`/`session_loaded` + `isinstance(app.layout, CartLayout)` (there is no live layout-change signal). Full writeup + sketch at [research/cart-layout-notes.md](research/cart-layout-notes.md).
- [x] **Step 3 — Write working scaffold.** Inbound-only plugin in [apc_mini_cart/](apc_mini_cart/) — `__init__.py` exports the class, [apc_mini_cart.py](apc_mini_cart/apc_mini_cart.py) holds the logic, [default.json](apc_mini_cart/default.json) enables it. Activates on `session_created`/`session_loaded` when `isinstance(app.layout, CartLayout)`, subscribes to `Midi.input.new_message` via `Connection.QtQueued`, maps APC note → `(page, row, col)` and calls `cue.execute()`. No LEDs, no settings UI, no Optional `Depends`. Verified pre-coding: `Plugin` metadata fields in [core/plugin.py:42-54](../linux-show-player/lisp/core/plugin.py#L42); `Signal.connect(slot, mode)` accepts `Connection.QtQueued` positionally ([core/signal.py:178](../linux-show-player/lisp/core/signal.py#L178)); `default.json` auto-loaded by [core/plugins_manager.py:93](../linux-show-player/lisp/core/plugins_manager.py#L93). Smoke test: `poetry run python -c "from lisp.plugins.apc_mini_cart import ApcMiniCart"` imports cleanly. **Not yet live-tested with hardware.**
- [ ] LED feedback on cue state change (idle / running / paused / error).
- [ ] Color logic (pulse for paused, blink for error).
- [ ] Settings UI: enable toggle + default colors.
- [ ] *Phase 2:* per-cue color override, fader mappings, mk1 support.

Update the boxes above as work completes. When a step finishes, summarize what was learned in a short paragraph below this list so the next session can pick up cold.

**Step 3 notes (2026-05-20).** Scaffold matches the sketch in [research/cart-layout-notes.md](research/cart-layout-notes.md) almost verbatim, with two deliberate choices: (1) `Depends = ('Midi',)` rather than `OptDepends` — without MIDI the plugin can't do anything, so make it a hard requirement; (2) session lifecycle handlers are bound methods rather than lambdas, because `lisp.core.signal.Signal` uses weakrefs and warns lambdas won't stay connected ([core/signal.py:166-171](../linux-show-player/lisp/core/signal.py#L166)). `_on_midi_message` is gated on `note_on`, channel 0, notes 0–63 — Note-On with vel=0 is auto-translated to Note-Off by `MIDIInput.__new_message` so we naturally only react to actual key-down. Empty pads (`IndexError` from `model.item`) are logged at DEBUG and silently ignored. **Live-test gate before checking Step 3 fully done:** start LiSP with a Cart Layout session at 8×8, APC mk2 plugged in, press a populated pad, confirm the right cue fires and an empty pad does nothing. If grid is not 8×8 the row/col math is wrong — config-mismatch detection deferred to Step 4 or later.

## Key technical reference (cheat sheet)

Full MIDI table in the primer. The two things you'll reach for most:

**Grid coordinate conversion** (APC note 0 = bottom-left; Cart (0,0) = top-left):
```
cart_row = 7 - (note // 8)
cart_col = note % 8
note     = (7 - cart_row) * 8 + cart_col
```

**LED control:** Note-On `9X NN VV` — `X` = behavior (0–6 solid brightness, 7–10 pulse, 11–15 blink), `NN` = pad note 0x00–0x3F, `VV` = color from 128-entry palette (0=off, 5=red, 13=yellow, 21=green, 45=blue, 87=bright green).

## Environment notes

- **LiSP must be installed from source** for plugin development (Flatpak is sandboxed; distro packages typically have no user-plugin path). See [primer.md §Installation constraint](documentation/primer.md#installation-constraint-read-before-assuming-dev-environment).
- Production deployment decision (source vs. custom Flatpak on show machine) is deferred.

## Working conventions

- Don't skip Steps 1–2. Writing the scaffold before surveying existing work risks duplicating something that already exists, and writing it before reading Cart Layout source means guessing at APIs.
- Keep research notes (`research/*.md`) in-repo so the next session can pick up without re-doing the investigation.
- v1 is intentionally narrow (grid pads + LED feedback only). Resist scope creep — fader mappings, Scene Launch, Track Buttons, Shift combos, and multi-page navigation are all out-of-scope for v1.
