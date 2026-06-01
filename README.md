# APC Mini Cart — Linux Show Player plugin

Plug-and-play [Akai APC Mini mk2](https://www.akaipro.com/apc-mini-mk2) integration for the
**Cart Layout** in [Linux Show Player (LiSP)](https://github.com/FrancescoCeruti/linux-show-player).

Press a pad to fire the cue at that grid position; the pad's LED reflects the cue's state.
The eight faders ride per-row volume or pan with soft takeover. **No per-cue MIDI
configuration** — the 8×8 pad grid maps directly onto the visible cart page.

## Features

- **Pad → cue trigger.** Each pad fires the cue at the matching `(row, col)` of the
  currently visible cart page. Two trigger modes, set globally and overridable per cue:
  - `retrigger` (default) — interrupt and restart from the top, like a clip launcher.
  - `toggle` — LiSP's native play/stop on alternate presses.
- **LED state feedback.** Pads colour-code cue state: idle, running, paused (pulse),
  error (blink). The APC animates pulse/blink on-board, so there's no per-frame work.
- **Faders.** Pick a row with a Scene Launch button, then the eight faders control that
  row's cue **volume**; tap the same Scene button again to switch the row to **pan**.
  Soft takeover prevents value jumps — a pad pulses (blue = push up, magenta = pull down)
  until the physical fader catches the stored value.
- **Save + shut down from the device.** Hold the bottom-row **Device + Down** Track Buttons
  together for ~2 seconds to silently save the current session and power the machine off —
  meant for a headless kiosk with no keyboard. The two buttons blink while held; release
  either one to abort. Can be disabled in Preferences.
- **Preferences page** (Preferences → APC Mini Cart): default idle/running/paused/error
  colours, idle/running brightness, default pad-press behaviour, the save-and-shutdown
  toggle, and a "flash grid" identify button.
- **Per-cue overrides** (the "APC Mini" tab in a cue's settings): per-cart idle colour and
  trigger mode.
- **Zero-config activation.** The plugin binds itself whenever a Cart Layout session is
  loaded and detaches (clearing all LEDs) for any other layout.

## Requirements

- **Linux Show Player**, `develop` branch. The plugin targets `develop` specifically
  because it replaced `pyliblo3` with pure-Python `python-osc`
  ([PR #338](https://github.com/FrancescoCeruti/linux-show-player/pull/338)), which is what
  lets LiSP build on Ubuntu 24+/Debian 13. The v0.6.5 tag and `master` are **not** supported.
- Python ≥ 3.10, PyQt5, GStreamer (LiSP's own stack).
- An **Akai APC Mini mk2** (8×8 grid, MIDI Note 0–63 on channel 1).
- LiSP's built-in **MIDI** plugin (a hard dependency).

## Installation

The repository root *is* the plugin package, so installing means making it visible to LiSP
as `lisp/plugins/apc_mini_cart`. LiSP only scans `lisp/plugins/` at startup, so **restart
LiSP** after installing.

### Into an existing from-source LiSP

```bash
git clone https://github.com/nvdhulst79/LiSP-APCmini-plugin.git ~/lisp/apc-mini-cart
ln -s ~/lisp/apc-mini-cart \
      ~/path/to/linux-show-player/lisp/plugins/apc_mini_cart
```

(LiSP must be installed **from source** for plugin development — Flatpak is sandboxed and
distro packages usually have no user-plugin path.)

### Fresh machine (scripted)

For a fresh Raspberry Pi OS / Debian **Trixie** show machine there's a one-shot
installer that also builds LiSP itself and wires everything together. It doubles as the
updater (re-run it to `git pull` + reinstall):

```bash
git clone https://github.com/nvdhulst79/LiSP-APCmini-plugin.git ~/lisp/apc-mini-cart
bash ~/lisp/apc-mini-cart/deploy/install.sh
```

See [deploy/README.md](deploy/README.md) for what it does, supported targets, and the
`apt`/PyQt5 details.

## Usage

1. **Set the MIDI port.** In LiSP, open **Preferences → MIDI** and set both the input and
   output device to **`APC mini mk2 Control`** — *not* `APC mini mk2 Notes`. With the wrong
   port selected the plugin sees nothing and appears dead (see Troubleshooting).
2. Open or create a **Cart Layout** session (the plugin only binds to Cart layouts).
3. Confirm "APC Mini Cart" is enabled under **Preferences → Plugins**.
4. Populate cart pages; press pads to fire cues. Select a row with a Scene Launch button to
   use the faders.

### Save and shut down (kiosk power-off)

Hold the two bottom-row Track Buttons **Device + Down** together for ~2 seconds. The plugin
saves the current session, then powers the machine off — no keyboard needed. While you hold
the chord both buttons blink red as a confirmation countdown; release either button before
the 2 seconds are up to abort.

The session is saved over its existing file (the usual case — a show loaded from disk or a
USB stick writes straight back). A session that was never saved is written to LiSP's
last-used folder as `autosave-<timestamp>.lsp`, so a power-off never discards work.

Power-off uses `systemctl poweroff`, which on Raspberry Pi OS is permitted for the locally
logged-in user without a password. If your system needs a different command (or a
passwordless-`sudo` wrapper), set the `shutdown.command` key in the plugin config. The whole
feature can be turned off in **Preferences → APC Mini Cart → System**.

> The chord only works while a Cart Layout session is open (that's when the plugin is
> listening to the device). The bottom-row button notes follow the documented mk2 layout
> (Device, Down); if your unit reports different notes, the constants are easy to adjust.

## Configuration

| Setting | Where | Notes |
|---|---|---|
| State colours (idle/running/paused/error) | Preferences → APC Mini Cart | Limited palette: White, Red, Yellow, Green, Blue, Magenta (the APC's discrete colour set). |
| Idle / running brightness | Preferences → APC Mini Cart | 7 discrete steps (10 %–100 %); the APC's solid-brightness levels. Paused/error brightness is fixed by their animation patterns. |
| Default pad-press behaviour | Preferences → APC Mini Cart | `retrigger` or `toggle`. |
| Save + shutdown chord | Preferences → APC Mini Cart → System | Enable/disable the Device + Down hold-to-save-and-power-off. Power-off command overridable via the `shutdown.command` config key. |
| Identify (flash grid) | Preferences → APC Mini Cart | Flashes all pads white for 1 s — a quick "is it talking to the device" smoke test. |
| Per-cart idle colour | Cue settings → APC Mini tab | "Default" inherits the global colour. |
| Per-cue trigger mode | Cue settings → APC Mini tab | "Default" inherits the global mode. |

## Troubleshooting

- **The plugin does nothing / pads don't fire.** You're almost certainly bound to the wrong
  MIDI port. The mk2 exposes two ports — `APC mini mk2 Control` and `APC mini mk2 Notes`.
  The plugin needs **Control**. With "Notes" selected the pads send chromatic-keyboard MIDI
  on other channels/notes and the plugin sees nothing on channel 1, notes 0–63.
- **Pan mode does nothing.** `AudioPan` is **not** in LiSP's default GStreamer pipeline
  (`Volume, Equalizer10, DbMeter, AutoSink`), so pan is unavailable until you add the
  AudioPan element to a cue's media settings. Volume works out of the box. The plugin logs a
  warning when a row enters pan mode and none of its cues expose AudioPan.
- **Wrong layout.** The plugin only activates for the Cart Layout; any other layout clears
  the LEDs and detaches the MIDI handler.

## How it works

The Cart Layout indexes `(row, col)` from the top-left; the APC numbers pads from the
bottom-left, so the two are mirrored on the row axis:

```
cart_row = 7 - (note // 8)
cart_col = note % 8
note     = (7 - cart_row) * 8 + cart_col
```

LEDs are driven with Note-On `9X NN VV`, where `X` is the behaviour nibble
(solid brightness / pulse / blink), `NN` the pad note `0x00–0x3F`, and `VV` a colour from
the device's 128-entry palette.

Design rationale, the full MIDI reference, and rejected alternatives live in
[documentation/primer.md](documentation/primer.md); the fader design is in
[documentation/phase2-faders.md](documentation/phase2-faders.md).

## License

GPL-3.0-or-later — see [LICENSE](LICENSE). This matches Linux Show Player's own license.
