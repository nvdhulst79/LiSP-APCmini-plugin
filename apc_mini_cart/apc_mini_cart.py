"""Akai APC Mini mk2 <-> LiSP Cart Layout bridge.

The plugin wires the APC's 8x8 pad grid to the currently visible cart page:

* Pad press      -> fire the cue at that (row, col) on the current page.
* Cue state      -> pad LED (idle / running / paused / error), with the APC
                    handling pulse/blink animations on-board.
* Faders         -> per-row volume / pan with soft takeover; the row is picked
                    with a Scene Launch button (Shift selects pan mode).
* Preferences    -> default colours, brightness, and pad-press behavior.
* Per-cue tab    -> per-cart idle-colour and trigger-mode overrides.

Activation is tied to having a Cart Layout session loaded; any other layout
silently disables the plugin (LEDs cleared, MIDI handler detached).
"""

import logging
from threading import Thread

import mido
from PyQt5.QtCore import QTimer

from lisp.core.plugin import Plugin
from lisp.core.properties import Property
from lisp.core.signal import Connection
from lisp.cues.cue import Cue, CueState
from lisp.plugins import get_plugin
from lisp.plugins.cart_layout.layout import CartLayout
from lisp.ui.settings.app_configuration import AppConfigurationDialog
from lisp.ui.settings.cue_settings import CueSettingsRegistry

from .constants import (
    APC_CHANNEL,
    APC_FADER_CCS,
    APC_GRID_NOTES,
    APC_SCENE_NOTES,
    BEHAVIOR_BLINK_SIXTEENTH,
    BEHAVIOR_FULL,
    BEHAVIOR_PULSE_QUARTER,
    COLOR_WHITE,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLORS,
    GRID_COLS,
    GRID_ROWS,
    HUNT_ARMED_COLOR,
    HUNT_BEHAVIOR,
    HUNT_DOWN_COLOR,
    HUNT_UP_COLOR,
    IDENTIFY_MS,
    LED_OFF,
    PAN_CENTER_CC,
    PAN_CENTER_TOL,
    ROW_MODE_PAN,
    ROW_MODE_VOLUME,
    SCENE_LED_BLINK,
    SCENE_LED_OFF,
    SCENE_LED_ON,
    TRIGGER_MODE_DEFAULT,
    VOLUME_CC_MAX,
)
from .settings import ApcMiniCartCueSettings, ApcMiniCartSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------
#
# Cart Layout indexes (row, col) with (0, 0) at the top-left of the grid.
# The APC numbers its pads from the bottom-left, so the two systems are
# mirrored on the row axis only.

def _pad_to_note(row, col):
    """Cart (row, col) -> APC MIDI note number."""
    return (7 - row) * 8 + col


def _note_to_pad(note):
    """APC MIDI note number -> Cart (row, col)."""
    return 7 - (note // 8), note % 8


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class ApcMiniCart(Plugin):
    """Plug-and-play APC Mini mk2 integration for the LiSP Cart Layout."""

    Name = "APC Mini Cart"
    Authors = ("Niels van der Hulst",)
    Description = "Plug-and-play Akai APC Mini mk2 control for the Cart Layout."
    Depends = ("Midi",)

    def __init__(self, app):
        super().__init__(app)
        self._midi = get_plugin("Midi")

        # Runtime state.
        self._active = False           # bound to a CartLayout session?
        self._identify_active = False  # smoke-test flash in progress?
        self._cue_to_pad = {}          # id(cue) -> (row, col) on visible page
        self._tracked_cues = []        # strong refs; Signal slots are weakref'd

        # Fader state. Only meaningful while a row is selected. A Scene Launch
        # tap cycles the selected row through volume -> pan -> off; selecting a
        # different row starts it in volume mode. _slider_position tracks the
        # last seen physical CC value per column; -1 = unknown until first move.
        self._selected_row = None
        self._current_mode = ROW_MODE_VOLUME
        self._slider_latched = [False] * GRID_COLS
        self._slider_position = [-1] * GRID_COLS

        # Per-cue properties (None = "use the plugin-wide default").
        # Registered on the class so they serialize with the session file.
        Cue.apc_idle_color = Property(default=None)
        Cue.apc_trigger_mode = Property(default=None)

        # Settings pages.
        AppConfigurationDialog.registerSettingsPage(
            "plugins.apc_mini_cart",
            ApcMiniCartSettings,
            ApcMiniCart.Config,
        )
        CueSettingsRegistry().add(ApcMiniCartCueSettings)

        # Session lifecycle. Use QtQueued so handlers always run on the
        # Qt thread regardless of which thread fired the signal.
        self.app.session_created.connect(self._on_session_change, Connection.QtQueued)
        self.app.session_loaded.connect(self._on_session_change, Connection.QtQueued)
        self.app.session_before_finalize.connect(self._on_session_finalize, Connection.QtQueued)

        # Repaint when the user changes preferences.
        ApcMiniCart.Config.changed.connect(self._on_config_changed)
        ApcMiniCart.Config.updated.connect(self._on_config_changed)

    # ------------------------------------------------------------------ #
    # Session / layout lifecycle                                         #
    # ------------------------------------------------------------------ #

    def _on_session_change(self, *_):
        """Activate or deactivate depending on the current layout type."""
        if isinstance(self.app.layout, CartLayout):
            self._activate()
        else:
            self._deactivate()

    def _on_session_finalize(self, *_):
        """Always tear down before a session is unloaded."""
        self._deactivate()

    def _activate(self):
        """Subscribe to MIDI + model events and paint the visible page."""
        if self._active:
            return
        self._active = True

        self._midi.input.new_message.connect(self._on_midi_message, Connection.QtQueued)

        model = self.app.layout.model
        model.item_added.connect(self._on_model_changed, Connection.QtQueued)
        model.item_removed.connect(self._on_model_changed, Connection.QtQueued)
        model.item_moved.connect(self._on_model_changed, Connection.QtQueued)
        model.model_reset.connect(self._on_model_changed, Connection.QtQueued)

        self.app.layout.view.currentChanged.connect(self._on_page_changed)

        self._paint_scene_leds()
        self._rebind_current_page()
        logger.info("APC Mini Cart: activated (Cart Layout detected).")

    def _deactivate(self):
        """Detach all signals, blank the grid, and reset state."""
        if not self._active:
            return

        self._unbind_cues()

        try:
            self.app.layout.view.currentChanged.disconnect(self._on_page_changed)
        except (TypeError, RuntimeError):
            pass

        model = self.app.layout.model
        for signal in (
            model.item_added, model.item_removed,
            model.item_moved, model.model_reset,
        ):
            signal.disconnect(self._on_model_changed)

        self._midi.input.new_message.disconnect(self._on_midi_message)
        self._clear_all_pads()
        self._clear_scene_leds()
        self._selected_row = None
        self._current_mode = ROW_MODE_VOLUME
        self._reset_fader_latches()
        self._active = False
        logger.info("APC Mini Cart: deactivated.")

    def _on_config_changed(self, *_):
        """Repaint when colours/brightness change in Preferences.

        Scene Launch LEDs depend only on the current fader selection, not on
        any config value, so they don't need repainting here.
        """
        if self._active and not self._identify_active:
            self._rebind_current_page()

    # ------------------------------------------------------------------ #
    # Inbound MIDI dispatch                                              #
    # ------------------------------------------------------------------ #

    def _on_midi_message(self, message):
        """Route an inbound message to the grid, scene, or fader handler.

        Everything is gated on channel 0. Grid pads fire cues, Scene Launch
        notes select/cycle a fader row, and the eight mapped fader CCs drive
        volume/pan. The Shift button is deliberately ignored (its hardware
        combos can't be repurposed — see APC_SCENE_NOTES in constants).
        """
        if message.channel != APC_CHANNEL:
            return
        if message.type == "note_on":
            note = message.note
            if note in APC_GRID_NOTES:
                self._handle_grid_press(note)
            elif note in APC_SCENE_NOTES:
                self._handle_scene_press(note)
        elif message.type == "control_change":
            cc = message.control
            if cc in APC_FADER_CCS:
                self._handle_fader(cc - APC_FADER_CCS[0], message.value)

    # ------------------------------------------------------------------ #
    # Inbound: pad press -> cue dispatch                                #
    # ------------------------------------------------------------------ #

    def _handle_grid_press(self, note):
        """Fire the cue at the pressed pad's (row, col) on the current page.

        Empty pads (no cue at that coordinate) are silently logged at DEBUG.
        """
        row, col = _note_to_pad(note)
        page = self.app.layout.current_page()

        try:
            cue = self.app.layout.model.item((page, row, col))
        except IndexError:
            logger.debug(
                "APC Mini Cart: pad (page=%d, row=%d, col=%d) is empty.",
                page, row, col,
            )
            return

        mode = self._trigger_mode_for(cue)
        logger.debug(
            "APC Mini Cart: firing cue %r at (page=%d, row=%d, col=%d) mode=%s.",
            cue.name, page, row, col, mode,
        )
        if mode == "retrigger":
            self._retrigger(cue)
        else:
            cue.execute()

    def _trigger_mode_for(self, cue):
        """Resolve the effective trigger mode for ``cue``.

        Per-cue override wins; otherwise the global Config value; otherwise
        the hardcoded default.
        """
        per_cue = getattr(cue, "apc_trigger_mode", None)
        if per_cue:
            return per_cue
        return self.Config.get("trigger_mode", TRIGGER_MODE_DEFAULT)

    @staticmethod
    def _retrigger(cue):
        """Interrupt then restart ``cue`` on a single worker thread.

        ``cue.interrupt()`` and ``cue.start()`` are both decorated with
        ``@async_function`` in LiSP — each spawns its own thread and returns
        immediately. Calling them back-to-back races on the cue state lock:
        ``start()`` often wins, sees the cue still running, and silently
        returns. We bypass the decorator (via ``__wrapped__``) and run both
        bodies sequentially on one thread so interrupt-then-start is ordered
        correctly. See [[project_lisp_async_function]].
        """
        cls = type(cue)

        def task():
            cls.interrupt.__wrapped__(cue)
            cls.start.__wrapped__(cue)

        Thread(target=task, name=f"apc-retrigger-{id(cue):x}", daemon=True).start()

    # ------------------------------------------------------------------ #
    # Outbound: LED feedback                                            #
    # ------------------------------------------------------------------ #

    def _on_page_changed(self, _index):
        """Cart page changed -> re-arm soft takeover and repaint."""
        self._invalidate_page_bindings()

    def _on_model_changed(self, *_):
        """Cue added/removed/moved -> re-arm soft takeover and repaint."""
        self._invalidate_page_bindings()

    def _invalidate_page_bindings(self):
        """Re-arm soft takeover and rebind/repaint the visible page.

        Cues under the selected row may have changed (or the row itself is
        empty now), so latches are reset before the repaint.
        """
        self._reset_fader_latches()
        self._rebind_current_page()

    def _rebind_current_page(self):
        """Disconnect all cue handlers, clear the grid, then rebind+paint.

        Re-subscribing the whole visible page on every model event (rather
        than diffing) is intentional: 64 pads is trivial, and it sidesteps
        a class of bugs around stale ``cue -> (row, col)`` entries after
        moves/reorders.
        """
        if self._identify_active:
            return

        self._unbind_cues()
        self._clear_all_pads()

        page = self.app.layout.current_page()
        model = self.app.layout.model
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                try:
                    cue = model.item((page, row, col))
                except IndexError:
                    continue
                self._bind_cue(cue, row, col)
                self._paint_cue(cue)

    def _bind_cue(self, cue, row, col):
        """Subscribe to ``cue``'s lifecycle + property signals."""
        self._cue_to_pad[id(cue)] = (row, col)
        self._tracked_cues.append(cue)
        for signal in (
            cue.started, cue.stopped, cue.paused,
            cue.error, cue.end, cue.interrupted,
        ):
            signal.connect(self._on_cue_state_changed, Connection.QtQueued)
        cue.property_changed.connect(self._on_cue_property_changed, Connection.QtQueued)

    def _unbind_cues(self):
        """Reverse :meth:`_bind_cue` for every tracked cue."""
        for cue in self._tracked_cues:
            for signal in (
                cue.started, cue.stopped, cue.paused,
                cue.error, cue.end, cue.interrupted,
            ):
                try:
                    signal.disconnect(self._on_cue_state_changed)
                except (TypeError, RuntimeError, ValueError):
                    pass
            try:
                cue.property_changed.disconnect(self._on_cue_property_changed)
            except (TypeError, RuntimeError, ValueError):
                pass
        self._tracked_cues.clear()
        self._cue_to_pad.clear()

    def _on_cue_state_changed(self, cue):
        """A cue's lifecycle signal fired -> repaint its pad."""
        if id(cue) in self._cue_to_pad:
            self._paint_cue(cue)

    def _on_cue_property_changed(self, cue, name, _value):
        """Repaint only when the per-cue idle-colour override actually changes.

        ``property_changed`` fires for *every* property write (name, fade
        times, everything), so filter aggressively to avoid 64 repaints
        whenever the user types in another field.
        """
        if name == "apc_idle_color" and id(cue) in self._cue_to_pad:
            self._paint_cue(cue)

    def _paint_cue(self, cue):
        """Send the (behavior, color) pair appropriate for ``cue``'s pad."""
        if self._identify_active:
            return
        pad = self._cue_to_pad.get(id(cue))
        if pad is None:
            return
        row, col = pad
        behavior, color = self._led_for_pad(cue, row, col)
        self._send_pad(_pad_to_note(row, col), behavior, color)

    def _led_for_pad(self, cue, row, col):
        """Resolve a pad's (behavior, color), accounting for fader hunting.

        While a row is selected, its mappable pads show the hunting indicator
        until their fader latches; everything else uses the normal cue state.
        """
        if self._selected_row == row and not self._slider_latched[col]:
            element = self._fader_element(cue, self._current_mode)
            if element is not None:
                return self._hunting_led(element, col)
        return self._led_for_cue(cue)

    def _hunting_led(self, element, col):
        """Soft-takeover indicator: which way to move the fader to catch the value."""
        pos = self._slider_position[col]
        if pos < 0:
            # Fader not touched since arming: position unknown, no direction yet.
            return (HUNT_BEHAVIOR, HUNT_ARMED_COLOR)
        try:
            target = self._read_property(element, self._current_mode)
        except Exception:
            return (HUNT_BEHAVIOR, HUNT_ARMED_COLOR)
        target_cc = self._value_to_cc(target, self._current_mode)
        color = HUNT_UP_COLOR if pos < target_cc else HUNT_DOWN_COLOR
        return (HUNT_BEHAVIOR, color)

    def _led_for_cue(self, cue):
        """Resolve a cue's current state to a (behavior, color) tuple."""
        state = cue.state
        if state & CueState.Error:
            return (BEHAVIOR_BLINK_SIXTEENTH, self._color("error"))
        if state & CueState.IsPaused:
            return (BEHAVIOR_PULSE_QUARTER, self._color("paused"))
        if state & CueState.IsRunning:
            return (self._brightness("running"), self._color("running"))
        # Idle — per-cue override beats the global default.
        per_cue = getattr(cue, "apc_idle_color", None)
        idle = per_cue if per_cue is not None else self._color("idle")
        return (self._brightness("idle"), idle)

    def _color(self, key):
        """Look up a state colour (Preferences -> hardcoded default)."""
        return self.Config.get(f"colors.{key}", DEFAULT_COLORS[key])

    def _brightness(self, key):
        """Look up a state brightness nibble (Preferences -> default)."""
        return self.Config.get(f"brightness.{key}", DEFAULT_BRIGHTNESS[key])

    def _clear_all_pads(self):
        """Blank all 64 pads (used on deactivate and before rebind)."""
        behavior, color = LED_OFF
        for note in APC_GRID_NOTES:
            self._send_pad(note, behavior, color)

    def _send_pad(self, note, behavior, color):
        """Send a single Note-On to the APC, encoding LED state.

        The APC encodes pad LED state in three fields: ``channel`` = behavior
        nibble, ``note`` = pad index, ``velocity`` = colour palette index.
        """
        try:
            self._midi.output.send(
                mido.Message(
                    "note_on", channel=behavior, note=note, velocity=color,
                )
            )
        except Exception:
            logger.exception("APC Mini Cart: failed to send pad LED.")

    # ------------------------------------------------------------------ #
    # Identify (UI smoke test)                                          #
    # ------------------------------------------------------------------ #

    def identify(self):
        """Flash every pad solid white for ``IDENTIFY_MS`` ms.

        Used as a "is the cable plugged into the right port?" smoke test from
        the Preferences page. While the flash is active ``_paint_cue`` and
        ``_rebind_current_page`` no-op so concurrent cue events don't fight
        the all-white write.
        """
        if not self._active:
            logger.info("APC Mini Cart: identify ignored, plugin not active.")
            return
        self._identify_active = True
        for note in APC_GRID_NOTES:
            self._send_pad(note, BEHAVIOR_FULL, COLOR_WHITE)
        QTimer.singleShot(IDENTIFY_MS, self._identify_finish)

    def _identify_finish(self):
        """Restore normal grid state after the identify flash window."""
        self._identify_active = False
        if self._active:
            self._rebind_current_page()
        else:
            self._clear_all_pads()

    # ------------------------------------------------------------------ #
    # Faders: row selection + soft takeover                             #
    # ------------------------------------------------------------------ #

    def _handle_scene_press(self, note):
        """Cycle the fader row from a Scene Launch button press.

        Repeated taps of the same row cycle volume -> pan -> off. Tapping a
        different row jumps straight to that row in volume mode (so the prior
        row deselects). This three-state cycle replaces the old Shift-to-arm-pan
        scheme, which had to go because Shift + Scene Launch fires built-in
        hardware modes.
        """
        row = self._scene_note_to_row(note)
        prev_row, prev_mode = self._selected_row, self._current_mode
        if self._selected_row != row:
            # Different row (or none) selected: select it in volume mode.
            self._selected_row = row
            self._current_mode = ROW_MODE_VOLUME
        elif self._current_mode == ROW_MODE_VOLUME:
            # Same row, volume -> pan.
            self._current_mode = ROW_MODE_PAN
        else:
            # Same row, pan -> off (deselect).
            self._selected_row = None
            self._current_mode = ROW_MODE_VOLUME
        self._reset_fader_latches()
        self._repaint_tracked()
        self._paint_scene_leds()
        self._warn_if_pan_unavailable(prev_row, prev_mode)

    def _warn_if_pan_unavailable(self, prev_row, prev_mode):
        """Warn when pan mode is freshly entered for a row that can't pan.

        Only when this press freshly *enters* pan mode for a row, and not a
        single cue in that row has an Audio Pan element. AudioPan is not in
        LiSP's default GStreamer pipeline, so this is the common "pan does
        nothing" footgun. Surfaces in the status bar + log viewer.
        """
        entered_pan = (
            self._selected_row is not None
            and self._current_mode == ROW_MODE_PAN
            and (prev_row != self._selected_row or prev_mode != ROW_MODE_PAN)
        )
        if entered_pan and not self._row_has_pan(self._selected_row):
            logger.warning(
                "APC Mini Cart: pan mode has no effect — no cue in this row "
                "has an Audio Pan element. Add 'Audio Pan' to the pipeline in "
                "Preferences → GStreamer (new cues) or in the cue's media "
                "settings (existing cues)."
            )

    def _row_has_pan(self, row):
        """True if any cue in ``row`` on the current page has an AudioPan element."""
        page = self.app.layout.current_page()
        model = self.app.layout.model
        for col in range(GRID_COLS):
            try:
                cue = model.item((page, row, col))
            except IndexError:
                continue
            if self._fader_element(cue, ROW_MODE_PAN) is not None:
                return True
        return False

    def _handle_fader(self, col, cc_value):
        """Apply a fader CC to the selected row's cue at ``col`` (soft takeover)."""
        if self._selected_row is None:
            return
        row = self._selected_row
        page = self.app.layout.current_page()
        try:
            cue = self.app.layout.model.item((page, row, col))
        except IndexError:
            return

        mode = self._current_mode
        element = self._fader_element(cue, mode)
        if element is None:
            # Cue lacks Volume/AudioPan in its pipeline; slider stays inert
            # (no audible effect, no surprise on the next row selection).
            return

        try:
            target_value = self._read_property(element, mode)
        except Exception:
            logger.exception("APC Mini Cart: failed to read %s on cue %r.", mode, cue.name)
            return
        target_cc = self._value_to_cc(target_value, mode)

        if not self._slider_latched[col]:
            prev_cc = self._slider_position[col]
            self._slider_position[col] = cc_value
            if prev_cc < 0:
                # First CC since arming: we don't know which side of target
                # the slider was on yet. Wait for a second sample, but repaint
                # now that position is known so the pad shows the catch direction.
                self._paint_cue(cue)
                return
            # Crossing test in CC space: (prev - target) and (curr - target)
            # have opposite signs (or one is zero) iff the slider crossed or
            # landed on the target value.
            if (prev_cc - target_cc) * (cc_value - target_cc) > 0:
                return
            # Caught: latch and repaint to snap the pad back to its cue state.
            self._slider_latched[col] = True
            self._paint_cue(cue)

        new_value = self._cc_to_value(cc_value, mode)
        try:
            self._write_property(element, mode, new_value)
        except Exception:
            logger.exception("APC Mini Cart: failed to write %s on cue %r.", mode, cue.name)
            return
        self._slider_position[col] = cc_value

    def _reset_fader_latches(self):
        """Drop every fader's latch + last-known position (re-arms soft takeover)."""
        for i in range(GRID_COLS):
            self._slider_latched[i] = False
            self._slider_position[i] = -1

    def _repaint_tracked(self):
        """Repaint every bound pad.

        Used after a row change so hunting indicators appear on the newly
        selected row and clear from any previously selected one.
        """
        for cue in self._tracked_cues:
            self._paint_cue(cue)

    @staticmethod
    def _fader_element(cue, mode):
        """Return the cue's Volume / AudioPan media element for ``mode``, or None."""
        media = getattr(cue, "media", None)
        if media is None or not hasattr(media, "element"):
            return None
        if mode == ROW_MODE_VOLUME:
            return media.element("Volume")
        return media.element("AudioPan")

    @staticmethod
    def _read_property(element, mode):
        """Read the current volume / pan value off a media element.

        Volume reads the *baseline* ``volume`` (see :meth:`_write_property`),
        so soft-takeover hunts toward the value we actually persist.
        """
        if mode == ROW_MODE_VOLUME:
            return float(element.volume)
        return float(element.pan)

    @staticmethod
    def _write_property(element, mode, value):
        """Write a volume / pan value to a media element.

        Volume mode writes the *baseline* ``volume`` property, not the runtime
        ``live_volume`` we used to ride. ``live_volume`` is reset to the
        baseline on every cue ``stop()`` (Volume.stop in the gst backend), so
        a fader move only held until the next replay — the cue came back at its
        configured volume. Writing the baseline instead:
          * persists across replays and is saved into the session file;
          * keeps the Cart widget's volume slider in sync (it repaints from
            ``changed("volume")``, the baseline-property signal);
          * is still heard live — it ``set_property``'s the same gst element.
        Pan has no live/baseline split, so it is written directly.
        """
        if mode == ROW_MODE_VOLUME:
            element.volume = value
        else:
            element.pan = value

    @staticmethod
    def _value_to_cc(value, mode):
        """Map a volume (0..1) or pan (-1..1) value to a CC position (0..127)."""
        if mode == ROW_MODE_VOLUME:
            v = max(0.0, min(VOLUME_CC_MAX, value))
            return int(round(v / VOLUME_CC_MAX * 127))
        p = max(-1.0, min(1.0, value))
        if p < 0:
            return int(round((p + 1.0) * PAN_CENTER_CC))
        if p > 0:
            return PAN_CENTER_CC + int(round(p * (127 - PAN_CENTER_CC)))
        return PAN_CENTER_CC

    @staticmethod
    def _cc_to_value(cc, mode):
        """Map a CC position (0..127) to a volume (0..1) or pan (-1..1) value."""
        if mode == ROW_MODE_VOLUME:
            return cc / 127.0 * VOLUME_CC_MAX
        if abs(cc - PAN_CENTER_CC) <= PAN_CENTER_TOL:
            return 0.0
        if cc < PAN_CENTER_CC:
            return (cc - PAN_CENTER_CC) / PAN_CENTER_CC  # -1.0 .. 0
        return (cc - PAN_CENTER_CC) / (127 - PAN_CENTER_CC)  # 0 .. +1.0

    # ------------------------------------------------------------------ #
    # Scene Launch LEDs                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _scene_note_to_row(note):
        """Map a Scene Launch note to a grid row.

        Assumes Scene Launch 1 (top) = note 0x70; flip this mapping if a
        hardware test shows the buttons are numbered bottom-up.
        """
        return note - APC_SCENE_NOTES[0]

    def _paint_scene_leds(self):
        """Repaint all Scene Launch LEDs for the current selection."""
        for row in range(GRID_ROWS):
            self._send_scene_led(row, self._scene_led_state(row))

    def _scene_led_state(self, row):
        """Return the LED state (off / on / blink) for one Scene Launch button.

        These buttons have no brightness control, so selection is shown by
        state alone: unselected = off, selected-volume = solid on, selected-pan
        = blink.
        """
        if row != self._selected_row:
            return SCENE_LED_OFF
        if self._current_mode == ROW_MODE_PAN:
            return SCENE_LED_BLINK
        return SCENE_LED_ON

    def _clear_scene_leds(self):
        """Blank all Scene Launch LEDs."""
        for row in range(GRID_ROWS):
            self._send_scene_led(row, SCENE_LED_OFF)

    def _send_scene_led(self, row, velocity):
        """Send a single Scene Launch Note-On (velocity = 0 off / 1 on / 2 blink)."""
        try:
            self._midi.output.send(
                mido.Message(
                    "note_on",
                    channel=APC_CHANNEL,
                    note=APC_SCENE_NOTES[0] + row,
                    velocity=velocity,
                )
            )
        except Exception:
            logger.exception("APC Mini Cart: failed to send Scene Launch LED.")
