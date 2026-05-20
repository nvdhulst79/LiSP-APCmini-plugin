# Step 1 — Existing-plugins survey

> Goal: before writing any code, find out whether someone has already built (or started building) an APC Mini / Launchpad / generic grid-controller plugin for LiSP — and if anything close exists, study it.

**TL;DR — start fresh, borrow patterns.** No existing LiSP plugin does grid-controller-to-Cart-Layout mapping with LED feedback. The closest signal is open issue [#259](https://github.com/FrancescoCeruti/linux-show-player/issues/259) ("Launchpad support") with no implementation attached. We will reuse the MIDI subscription pattern from `protocol-monitor` and crib the APC mk2 LED color/behavior mapping from existing QLC+ feedback scripts.

## Decision

- **Start fresh** (do not fork another plugin). Architecture borrows from below; scope is narrower than any of them.
- **Borrow patterns from**:
  - [s0600204-LiSP-Plugins/protocol-monitor](https://github.com/s0600204-LiSP-Plugins/protocol-monitor) — MIDI subscription pattern (see snippet below).
  - [s0600204-LiSP-Plugins/midi-fixture-control](https://github.com/s0600204-LiSP-Plugins/midi-fixture-control) — third-party plugin layout, settings UI, abstracted device modelling.
  - [revilo196/mk2apc_4light](https://github.com/revilo196/mk2apc_4light) and [maartenvd84/qlc_apcmini-mk2_feedback](https://github.com/maartenvd84/qlc_apcmini-mk2_feedback) — APC mk2 LED color/brightness/blink mapping (host-agnostic; cross-check against the [protocol PDF](https://cdn.inmusicbrands.com/akai/attachments/APC%20mini%20mk2%20-%20Communication%20Protocol%20-%20v1.0.pdf)).
- **Coordinate with upstream**: issue #259 is open and the maintainer (k80w, opener) framed it as "the Controller plugin needs extending." Our plugin offers a self-contained alternative; if the architecture turns out clean enough, the LED-feedback portion may eventually be a candidate for upstreaming into the Controller plugin. Out-of-scope for v1 — flag for later.

## Built-in plugins (LiSP `lisp/plugins/`)

Surveyed from <https://github.com/FrancescoCeruti/linux-show-player/tree/master/lisp/plugins>:

| Plugin | Relevance |
|---|---|
| `midi` | **Direct dependency.** Provides the MIDI input service we'll subscribe to and the output port we'll send LED messages on. |
| `controller` | **Adjacent.** Per-cue MIDI binding (the thing the user is trying to *avoid* configuring 64 times). Read its source to learn how it registers a MIDI input handler — that's the pattern we'll mirror but at the *layout* level instead of per-cue. |
| `cart_layout` | **The layout we're targeting.** Read for the cue-at-`(page, row, col)` lookup API and the current-page accessor. |
| `osc` | Not in scope but mirrors `midi` architecturally — useful comparison if `midi` source is unclear. |
| `list_layout`, `presets`, `triggers`, `action_cues`, `cache_manager`, `gst_backend`, `media_info`, `network`, `rename_cues`, `replay_gain`, `synchronizer`, `timecode` | Not relevant to this work. |

## Third-party LiSP plugins ([github.com/topics/linux-show-player](https://github.com/topics/linux-show-player))

All seven indexed third-party plugins live under [@s0600204-LiSP-Plugins](https://github.com/s0600204-LiSP-Plugins). None target grid controllers; several are architecturally useful.

| Repo | Direction | Touches Cart? | LED feedback? | Useful for us? |
|---|---|---|---|---|
| [protocol-monitor](https://github.com/s0600204-LiSP-Plugins/protocol-monitor) | inbound MIDI/OSC | no | no | **Yes — MIDI subscription pattern.** |
| [midi-fixture-control](https://github.com/s0600204-LiSP-Plugins/midi-fixture-control) | outbound MIDI | no | no | **Yes — third-party plugin layout, settings UI.** |
| [dca-plotter](https://github.com/s0600204-LiSP-Plugins/dca-plotter) | outbound MIDI | no | no | Reference only — outbound MIDI patterns. |
| [qlab-mimic](https://github.com/s0600204-LiSP-Plugins/qlab-mimic) | inbound network | no | n/a | Not relevant. |
| [aes67-monitor](https://github.com/s0600204-LiSP-Plugins/aes67-monitor), [senn-rx-monitor](https://github.com/s0600204-LiSP-Plugins/senn-rx-monitor), [lisp2scs](https://github.com/s0600204-LiSP-Plugins/lisp2scs) | unrelated | no | no | Not relevant. |

Also found, archived: [s0600204/LiSP-ListLayoutController](https://github.com/s0600204/LiSP-ListLayoutController). Mapped MIDI to List Layout playback (Go/Stop/Back/Forward). Archived Sep 2019 because *"control via MIDI voice message (beyond Note-On/Off) was implemented in the Controller plugin that comes as part of the base install of LiSP."* No Cart Layout, no LEDs. Confirms that LiSP's Controller plugin is the upstream destination for layout-level MIDI control — relevant for the future-upstreaming discussion.

## LiSP Issues / Discussions

| # | Title | Status | Relevance |
|---|---|---|---|
| [#259](https://github.com/FrancescoCeruti/linux-show-player/issues/259) | Launchpad support | **Open**, opened 2022-10-20 by k80w | **Closest prior signal.** Asks for grid controller integration with bidirectional LED feedback. Notes that this likely needs the Controller plugin extended. **No code, no PR, no fork attached.** |
| [#337](https://github.com/FrancescoCeruti/linux-show-player/issues/337) | Go to specific page (Cart Layout) via OSC/MIDI | Open | Adjacent — wants page-jump-by-name via MIDI/OSC. We don't need this for v1 (single page) but the underlying page-API is the same surface we'll use. |
| [#339](https://github.com/FrancescoCeruti/linux-show-player/issues/339) | Navigate to previous/next cart page via OSC/MIDI | **Merged** (Jan 2025) | Page-next/prev is already wired into the Controller plugin in stable LiSP. Means cart-page navigation hooks already exist — read this PR's diff to find them. |
| [#34](https://github.com/FrancescoCeruti/linux-show-player/issues/34) | Indicator for play status in list layout | — | Cue lifecycle → visual indicator request. Confirms there's appetite for state-driven UI feedback; not a blocker. |
| [#282 (discussion)](https://github.com/FrancescoCeruti/linux-show-player/discussions/282) | "Communication Via Midi" Q&A | Unanswered | Low signal. |

GitHub Discussions otherwise has nothing tagged APC / Launchpad / Akai / grid / LED feedback / cart MIDI.

## Adjacent (non-LiSP) reference implementations

These don't run inside LiSP but solve subsets of the same problem and the protocol details are reusable:

- [revilo196/mk2apc_4light](https://github.com/revilo196/mk2apc_4light) — adapts QLC+ MIDI feedback to APC Mini mk2 LEDs. Concrete LED color/behavior mapping, default + customisable. Cross-reference for our `color_palette.py`.
- [maartenvd84/qlc_apcmini-mk2_feedback](https://github.com/maartenvd84/qlc_apcmini-mk2_feedback) — fork of the above, fewer colors, more blink/dim options. Useful for understanding the trade-offs in the brightness/blink design space.
- [agraef/midizap APCmini config](https://github.com/agraef/midizap/blob/master/examples/APCmini.midizaprc) — declarative APC Mini mapping example. Confirms MIDI assignments for mk1; mk2 has the multicolor LED extensions per the protocol PDF.
- [RenWal/launchpy](https://github.com/RenWal/launchpy) — Python interface to APC Mini + PulseAudio mixer. Pure-Python `mido`-style usage, ignores LiSP. Possibly useful for prototyping outside LiSP if needed.
- [TomasHubelbauer/akai-apc-mini](https://github.com/TomasHubelbauer/akai-apc-mini) — APC Mini protocol notes. Largely subsumed by the official Akai PDF.

## Key code snippet for Step 2/3

From [protocol-monitor/protocols/midi.py](https://github.com/s0600204-LiSP-Plugins/protocol-monitor/blob/master/protocols/midi.py) — the inbound-MIDI subscription pattern we will follow. Both APIs (`received` on the Midi plugin, vs. legacy `input.new_message`) are shown; the newer `received(source, message)` is what current LiSP exposes:

```python
# Modern (LiSP 0.6.5)
if hasattr(self._midi_plugin, "received"):
    self._midi_plugin.received.connect(
        self.on_received_midi_message, Connection.QtQueued)

# Fallback (older LiSP)
else:
    self._midi_plugin.input.new_message.connect(
        self.on_new_midi_message, Connection.QtQueued)
```

The plugin is obtained via `get_plugin('Midi')` in the constructor; `OptDepends = ('Midi',)` in the plugin metadata. Use `Connection.QtQueued` for thread-safe delivery — Qt-thread invariant matters for any UI work we'll do off the back of a MIDI event.

## What this means for Step 2 (Cart Layout source study)

Concrete questions to answer next:
1. **Cue-at-position lookup.** Find the Cart Layout's accessor for "cue at `(page, row, col)`" (file:line). Likely in `lisp/plugins/cart_layout/`.
2. **Current-page accessor.** Find how the active Cart page index is exposed — and which signal fires on page change. The #339 merge added page-next/prev wiring; following that PR's diff will likely land on both.
3. **Cue lifecycle signals.** Locate `started` / `stopped` / `paused` / `error` (or whatever they're actually named in current source) on the cue/state model.
4. **Layout-change signal.** Find the signal that fires when the user switches between Cart / List layouts — we use this to activate/deactivate the plugin's MIDI handling.
5. **Confirm `Midi.received` exists in 0.6.5** (vs. legacy `input.new_message`). The fallback path in protocol-monitor is for older LiSP; verify which one we get.
