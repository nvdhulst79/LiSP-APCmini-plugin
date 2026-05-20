# Step 2 — Cart Layout source notes

> The 3–5 LiSP APIs the plugin needs, with file:line references against [FrancescoCeruti/linux-show-player@master](https://github.com/FrancescoCeruti/linux-show-player/tree/master).

All line numbers are against `master` (commit at time of survey — May 2026). 0.6.5 stable is close enough; differences flagged where I noticed them.

## TL;DR — the five hooks the scaffold needs

1. **Cue lookup by grid position** — [`app.layout.model.item((page, row, col))`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/model.py#L46) → returns `Cue` or raises `IndexError`.
2. **Current page** — [`app.layout.current_page()`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/layout.py#L289) → `int`. Page-change signal: `app.layout.view.currentChanged` (Qt `QTabWidget` signal).
3. **Cue lifecycle signals** — `cue.started` / `cue.stopped` / `cue.paused` / `cue.error` / `cue.interrupted` / `cue.end` on every [`Cue`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/cues/cue.py) instance, each emitting the cue itself.
4. **Detect active layout** — no live "layout-changed" signal. Subscribe to [`app.session_created`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/application.py) and [`app.session_loaded`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/application.py), then `isinstance(app.layout, CartLayout)`. Cleanup on `app.session_before_finalize`.
5. **MIDI I/O** — `get_plugin("Midi").input.new_message.connect(handler)` for inbound (handler signature `(message)` where `message` is a `mido.Message`); `get_plugin("Midi").output.send(message)` for outbound. Declare `OptDepends = ('Midi',)` in plugin metadata.

## Detail — per concern

### 1. Cue lookup by `(page, row, col)`

**Public path:** [`CartLayout.model`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/layout.py#L199) returns a [`CueCartModel`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/model.py). The model's [`item(index)`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/model.py#L46) accepts either a flat `int` index or a `(page, row, col)` tuple:

```python
# cart_layout/model.py:46-51
def item(self, index):
    index = self.flat(index)
    try:
        return self.__cues[index]
    except KeyError:
        raise IndexError("index out of range")
```

`flat(index)` ([model.py:35-44](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/model.py#L35)) is the tuple-to-int converter:

```python
def flat(self, index):
    try:
        page, row, column = index
        page *= self.__rows * self.__columns
        row *= self.__columns
        return page + row + column
    except TypeError:
        return index
```

So our handler becomes:

```python
try:
    cue = self.app.layout.model.item((page, row, col))
    cue.execute()
except IndexError:
    pass  # empty pad
```

There's also [`CartLayout.cue_at(index)`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/layout.py#L205) (1D only) and [`to_3d_index`/`to_1d_index`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/layout.py#L357-L373) for converting either direction.

**Grid dimensions** are config-driven ([layout.py:70-71](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/layout.py#L70)):

```python
self.__columns = CartLayout.Config["grid.columns"]
self.__rows = CartLayout.Config["grid.rows"]
```

We need the user to set both to **8** for the APC mk2. Not something the plugin can/should enforce — surface in docs and check at activation, warn if mismatched.

**Iterate cues on a page:** [`CueCartModel.iter_page(page)`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/model.py#L100) is a generator over cues in that page — useful for the initial full-LED-refresh pass when activating.

### 2. Current page + page-change signal

```python
# cart_layout/layout.py:285-290
def set_current_page(self, page_number):
    page_number = max(0, min(page_number, self._cart_view.count()))
    self._cart_view.setCurrentIndex(page_number)

def current_page(self):
    return self._cart_view.currentIndex()
```

The page widget is a `CartTabWidget` (a `QTabWidget` subclass), exposed via `app.layout.view`. So:

- Read current page: `app.layout.current_page()`
- Subscribe to page changes: `app.layout.view.currentChanged.connect(handler)` — Qt signal, handler signature `(int)`.

PR [#339](https://github.com/FrancescoCeruti/linux-show-player/pull/339) (merged Jan 2025) adds `go_to_page(n)`, `decrement_page()`, `increment_page()` on `CartLayout` and wires them through `LayoutAction.PreviousPage` / `NextPage` in the **Controller plugin**. Not directly used by us for v1 (single page) but worth knowing — they're the pattern for any *layout-level* MIDI mapping if/when we want to upstream the LED-feedback logic.

### 3. Cue lifecycle signals

Declared as LiSP `Signal` instances on `Cue.__init__`. Each emits `self` (the cue):

| Signal | Fires when |
|---|---|
| `started` | Cue starts playing |
| `stopped` | Cue stops (deliberate stop) |
| `paused` | Cue pauses |
| `interrupted` | Cue is interrupted |
| `end` | Cue ends naturally (playback complete) |
| `error` | Cue errors |
| `next` | Post-wait completes (chained-cue trigger) |

Plus pre/post-wait and fade-in/out signals if we want finer-grained LED state in v2.

`CueState` enum (also in `cue.py`):

```
Invalid=0, Error=1, Stop=2, Running=4, Pause=8
PreWait=16, PostWait=32, PreWait_Pause=64, PostWait_Pause=128
IsRunning=52, IsPaused=200, IsStopped=3
```

**Subscription pattern:** when a cue is added (via `_cart_model.item_added` signal — see below), wire all four lifecycle signals to one dispatch handler that does the LED update. When a cue is removed (`item_removed`), disconnect — though LiSP's `Signal` likely handles weak-refs cleanly, verify when writing the scaffold.

### Cart-model signals (keeping LED state map in sync)

[`CueCartModel`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/cart_layout/model.py) inherits from `ModelAdapter` and emits:

- `item_added(item)` — fired in `_item_added` handler at line 105.
- `item_removed(item)` — fired in `_item_removed` at line 112.
- `item_moved(old_index, new_index)` — fired by `move()` at line 76.
- `model_reset()` — fired by `_model_reset` at line 116.

Wire all four to keep the `{(row, col): cue}` map of the current page accurate as the user edits the show. **This is the reorder-safety mechanism** the primer calls out — there's no per-cue MIDI capture to break because we look up the cue at the time of the pad press, *every time*.

### 4. Detect & track active layout

[`application.py`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/application.py) defines three lifecycle signals:

- `session_created(session)` — emitted after a new session is instantiated.
- `session_loaded(session)` — emitted after a session file is loaded.
- `session_before_finalize(session)` — emitted before a session is torn down.

**There is no layout-changed signal — the layout is fixed for the lifetime of a session.** Switching layouts means opening a new session. So the activation/deactivation logic for our plugin is:

```python
# pseudo
def on_session_created_or_loaded(self, session):
    if isinstance(self.app.layout, CartLayout):
        self._activate()
    else:
        self._deactivate()  # ensure idle

def on_session_before_finalize(self, session):
    self._deactivate()
```

Access layout: `app.layout` (property returns `session.layout`).

### 5. MIDI I/O — inbound subscription, outbound send

**Inbound** ([`lisp/plugins/midi/midi_io.py:89-122`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/midi/midi_io.py#L89)):

```python
class MIDIInput(MIDIBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.alternate_mode = False
        self.new_message = Signal()
        self.new_message_alt = Signal()
    ...
    def __new_message(self, message):
        # Note On with vel 0 is translated to Note Off
        ...
        if self.alternate_mode:
            self.new_message_alt.emit(message)
        else:
            self.new_message.emit(message)
```

The base Controller plugin uses exactly this signal ([`lisp/plugins/controller/protocols/midi.py:266-275`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/controller/protocols/midi.py)):

```python
def __init__(self):
    super().__init__()
    get_plugin("Midi").input.new_message.connect(self.__new_message)

def __new_message(self, message):
    if hasattr(message, "velocity"):
        message = message.copy(velocity=0)
    self.protocol_event.emit(str(message))
```

**Outbound** ([`lisp/plugins/midi/midi_io.py:74-86`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/plugins/midi/midi_io.py#L74)):

```python
class MIDIOutput(MIDIBase):
    def send(self, message):
        if self._port is not None:
            self._port.send(message)
```

Accepts a `mido.Message`. For our LED control:

```python
import mido
get_plugin("Midi").output.send(
    mido.Message("note_on", channel=behavior_nibble, note=pad_note, velocity=color)
)
```

**Important caveat from the LiSP input layer:** `Note On vel=0` is auto-translated to `Note Off` (per the mido convention). Our handler will receive `note_off` for "key release" — usually we only care about `note_on` to fire the cue. Fine.

**Note on `Midi.received` vs `Midi.input.new_message`:** the [protocol-monitor](https://github.com/s0600204-LiSP-Plugins/protocol-monitor/blob/master/protocols/midi.py) plugin defensively checks `hasattr(midi_plugin, "received")` and falls back to `input.new_message`. The `received` signal does **not** exist in current LiSP master. Either target `input.new_message` directly and accept we may break against an unreleased refactor, or copy the `hasattr` guard for forward-compat. Recommend: copy the guard — it's cheap insurance.

**LiSP's `Signal` is not Qt's `pyqtSignal`** ([`lisp/core/signal.py`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/core/signal.py)). It has its own connection modes (one of which is `Connection.QtQueued` for cross-thread delivery into the Qt event loop). The base Controller plugin connects without a mode (so direct/sync); protocol-monitor uses `Connection.QtQueued` because it updates UI off a MIDI thread. Our handler will fire `cue.execute()` (model mutation) and send MIDI out (likely also requires Qt thread affinity for safety) — **use `Connection.QtQueued`** when connecting `new_message`, like protocol-monitor does.

## Sketch — putting it together

```python
# apc_mini_cart.py — sketch only, not final
from lisp.core.plugin import Plugin
from lisp.core.signal import Connection
from lisp.plugins import get_plugin
from lisp.plugins.cart_layout.layout import CartLayout
import mido


class ApcMiniCart(Plugin):
    Name = "APC Mini Cart"
    OptDepends = ("Midi",)

    def __init__(self, app):
        super().__init__(app)
        self._midi = get_plugin("Midi")
        self._active = False
        self._tracked = {}  # cue -> (row, col)

        self.app.session_created.connect(self._on_session_change)
        self.app.session_loaded.connect(self._on_session_change)
        self.app.session_before_finalize.connect(lambda *_: self._deactivate())

    def _on_session_change(self, *_):
        if isinstance(self.app.layout, CartLayout):
            self._activate()
        else:
            self._deactivate()

    def _activate(self):
        if self._active:
            return
        self._active = True
        self._midi.input.new_message.connect(
            self._on_midi, Connection.QtQueued
        )
        model = self.app.layout.model
        model.item_added.connect(self._on_cue_added)
        model.item_removed.connect(self._on_cue_removed)
        # ... model_reset, item_moved
        # ... currentChanged on layout.view
        self._refresh_all_leds()

    def _on_midi(self, message):
        if message.type != "note_on" or message.channel != 0:
            return
        if not (0 <= message.note <= 63):
            return
        page = self.app.layout.current_page()
        row = 7 - (message.note // 8)   # APC bottom-up → cart top-down
        col = message.note % 8
        try:
            cue = self.app.layout.model.item((page, row, col))
        except IndexError:
            return
        cue.execute()
    # ... LED feedback elided
```

## What I did NOT verify (flag for Step 3)

- **LiSP `Signal.connect` accepting `Connection.QtQueued` as second positional arg** — protocol-monitor passes it that way; assumed correct. Verify when scaffolding by importing `Connection` from `lisp.core.signal` and reading the signature.
- **Whether `CartLayout.model` is the canonical public accessor or just a leaky `@property` over `_cart_model`** — both work, prefer `.model`.
- **Behavior when grid config != 8×8.** The plugin should detect a mismatch on activation and refuse to bind, with a clear log/UI warning. Verify what `CartLayout.Config["grid.rows"]` reads from when scaffolding.
- **Thread safety of `cue.execute()` from a queued MIDI callback.** Other layout-level controllers (PR #339 page nav) do this from the same protocol pipeline, so it should be fine, but worth a smoke test.
- **`Plugin` base class API** — exact metadata fields (`Name`, `Authors`, `Description`, `OptDepends`, `Depends`) and lifecycle hooks. Read [`lisp/core/plugin.py`](https://github.com/FrancescoCeruti/linux-show-player/blob/master/lisp/core/plugin.py) before Step 3.
