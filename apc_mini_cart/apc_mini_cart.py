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

from .settings import (
    ApcMiniCartCueSettings,
    ApcMiniCartSettings,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLORS,
    TRIGGER_MODE_DEFAULT,
)

logger = logging.getLogger(__name__)

APC_GRID_NOTES = range(0, 64)
APC_CHANNEL = 0

# Scene Launch buttons (right of grid), single-color green. Assumed top-to-bottom:
# 0x70 = top row, 0x77 = bottom. Verify against hardware; flip _scene_note_to_row
# if reversed. LEDs accept VV = 0 (off), 1 (on), 2 (blink).
APC_SCENE_NOTES = range(0x70, 0x78)
APC_SHIFT_NOTE = 0x7A

# Faders 1-8 send CC 0x30..0x37; master at 0x38 is intentionally unmapped.
APC_FADER_CCS = range(0x30, 0x38)

SCENE_LED_OFF = 0
SCENE_LED_ON = 1
SCENE_LED_BLINK = 2

# APC mk2 LED behavior nibbles (Note-On channel).
BEHAVIOR_DIM = 0               # 10% solid
BEHAVIOR_FULL = 6              # 100% solid
BEHAVIOR_PULSE_QUARTER = 9     # pulse 1/4
BEHAVIOR_BLINK_SIXTEENTH = 12  # blink 1/16

COLOR_OFF = 0
COLOR_WHITE = 3

LED_OFF = (BEHAVIOR_DIM, COLOR_OFF)

IDENTIFY_MS = 1000

# Fader modes (per selected row).
ROW_MODE_VOLUME = "volume"
ROW_MODE_PAN = "pan"

# Volume mapping: CC 0..127 -> 0.0..1.0 (unity). Operators who need >unity
# should set the cue's baseline volume higher and ride it down with the fader.
VOLUME_CC_MAX = 1.0

# Pan mapping: CC 0..127 -> -1.0..+1.0 with center at CC 64. Sliders within
# +/- PAN_CENTER_TOL of CC 64 snap to exactly 0.0 (poor-man's center detent
# for the non-motorized faders).
PAN_CENTER_CC = 64
PAN_CENTER_TOL = 1


def _pad_to_note(row, col):
    return (7 - row) * 8 + col


class ApcMiniCart(Plugin):
    Name = "APC Mini Cart"
    Authors = ("Niels van der Hulst",)
    Description = "Plug-and-play Akai APC Mini mk2 control for the Cart Layout."
    Depends = ("Midi",)

    def __init__(self, app):
        super().__init__(app)
        self._midi = get_plugin("Midi")
        self._active = False
        self._identify_active = False
        self._cue_to_pad = {}     # id(cue) -> (row, col)
        self._tracked_cues = []   # keep refs alive; Signal uses weakrefs

        # Fader state. Only meaningful while a row is selected. _current_mode
        # resets to volume on every fresh row selection (pan is the non-default
        # and shouldn't surprise on re-select). _slider_position tracks the
        # last seen physical CC value per column; -1 = unknown until first move.
        self._selected_row = None
        self._current_mode = ROW_MODE_VOLUME
        self._slider_latched = [False] * 8
        self._slider_position = [-1] * 8
        self._shift_held = False

        # Per-cue settings. None = "use the plugin-wide default".
        Cue.apc_idle_color = Property(default=None)
        Cue.apc_trigger_mode = Property(default=None)

        AppConfigurationDialog.registerSettingsPage(
            "plugins.apc_mini_cart",
            ApcMiniCartSettings,
            ApcMiniCart.Config,
        )
        CueSettingsRegistry().add(ApcMiniCartCueSettings)

        self.app.session_created.connect(self._on_session_change, Connection.QtQueued)
        self.app.session_loaded.connect(self._on_session_change, Connection.QtQueued)
        self.app.session_before_finalize.connect(self._on_session_finalize, Connection.QtQueued)

        # Repaint when the user changes default colors in Preferences.
        ApcMiniCart.Config.changed.connect(self._on_config_changed)
        ApcMiniCart.Config.updated.connect(self._on_config_changed)

    # ---- session / layout lifecycle ------------------------------------

    def _on_session_change(self, *_):
        if isinstance(self.app.layout, CartLayout):
            self._activate()
        else:
            self._deactivate()

    def _on_session_finalize(self, *_):
        self._deactivate()

    def _activate(self):
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
        self._clear_scene_leds()
        self._rebind_current_page()
        logger.info("APC Mini Cart: activated (Cart Layout detected).")

    def _deactivate(self):
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
        self._shift_held = False
        self._active = False
        logger.info("APC Mini Cart: deactivated.")

    # ---- inbound MIDI dispatch -----------------------------------------

    def _on_midi_message(self, message):
        if message.channel != APC_CHANNEL:
            return
        if message.type == "note_on":
            note = message.note
            if note in APC_GRID_NOTES:
                self._handle_grid_press(note)
            elif note in APC_SCENE_NOTES:
                self._handle_scene_press(note)
            elif note == APC_SHIFT_NOTE:
                self._shift_held = True
        elif message.type == "note_off":
            if message.note == APC_SHIFT_NOTE:
                self._shift_held = False
        elif message.type == "control_change":
            cc = message.control
            if cc in APC_FADER_CCS:
                self._handle_fader(cc - APC_FADER_CCS[0], message.value)

    # ---- inbound: pad press -> cue.execute -----------------------------

    def _handle_grid_press(self, note):
        row = 7 - (note // 8)
        col = note % 8
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

    @staticmethod
    def _retrigger(cue):
        # cue.interrupt() and cue.start() are both @async_function in LiSP —
        # each spawns its own thread and returns immediately. Calling them
        # back-to-back races: start() often wins the state lock first, sees
        # the cue is still running, and silently returns. We bypass the
        # decorator (via __wrapped__) and run both bodies sequentially on
        # one thread so the interrupt always finishes before start runs.
        cls = type(cue)
        def task():
            cls.interrupt.__wrapped__(cue)
            cls.start.__wrapped__(cue)
        Thread(target=task, name=f"apc-retrigger-{id(cue):x}", daemon=True).start()

    def _trigger_mode_for(self, cue):
        per_cue = getattr(cue, "apc_trigger_mode", None)
        if per_cue:
            return per_cue
        return self.Config.get("trigger_mode", TRIGGER_MODE_DEFAULT)

    # ---- outbound: LED feedback ----------------------------------------

    def _on_page_changed(self, _index):
        self._invalidate_page_bindings()

    def _on_model_changed(self, *_):
        self._invalidate_page_bindings()

    def _invalidate_page_bindings(self):
        # Cues under the selected row may have changed (or the row itself
        # is empty now); re-arm soft takeover and repaint.
        self._reset_fader_latches()
        self._rebind_current_page()

    def _on_config_changed(self, *_):
        if self._active and not self._identify_active:
            self._rebind_current_page()

    def _rebind_current_page(self):
        if self._identify_active:
            return
        self._unbind_cues()
        self._clear_all_pads()
        page = self.app.layout.current_page()
        model = self.app.layout.model
        for row in range(8):
            for col in range(8):
                try:
                    cue = model.item((page, row, col))
                except IndexError:
                    continue
                self._bind_cue(cue, row, col)
                self._paint_cue(cue)

    def _bind_cue(self, cue, row, col):
        self._cue_to_pad[id(cue)] = (row, col)
        self._tracked_cues.append(cue)
        for signal in (
            cue.started, cue.stopped, cue.paused,
            cue.error, cue.end, cue.interrupted,
        ):
            signal.connect(self._on_cue_state_changed, Connection.QtQueued)
        cue.property_changed.connect(self._on_cue_property_changed, Connection.QtQueued)

    def _unbind_cues(self):
        for cue in self._tracked_cues:
            for signal in (
                cue.started, cue.stopped, cue.paused,
                cue.error, cue.end, cue.interrupted,
            ):
                try:
                    signal.disconnect(self._on_cue_state_changed)
                except Exception:
                    pass
            try:
                cue.property_changed.disconnect(self._on_cue_property_changed)
            except Exception:
                pass
        self._tracked_cues.clear()
        self._cue_to_pad.clear()

    def _on_cue_state_changed(self, cue):
        if id(cue) in self._cue_to_pad:
            self._paint_cue(cue)

    def _on_cue_property_changed(self, cue, name, _value):
        if name == "apc_idle_color" and id(cue) in self._cue_to_pad:
            self._paint_cue(cue)

    def _paint_cue(self, cue):
        if self._identify_active:
            return
        pad = self._cue_to_pad.get(id(cue))
        if pad is None:
            return
        row, col = pad
        behavior, color = self._led_for_cue(cue)
        self._send_pad(_pad_to_note(row, col), behavior, color)

    def _led_for_cue(self, cue):
        state = cue.state
        if state & CueState.Error:
            return (BEHAVIOR_BLINK_SIXTEENTH, self._color("error"))
        if state & CueState.IsPaused:
            return (BEHAVIOR_PULSE_QUARTER, self._color("paused"))
        if state & CueState.IsRunning:
            return (self._brightness("running"), self._color("running"))
        per_cue = getattr(cue, "apc_idle_color", None)
        idle = per_cue if per_cue is not None else self._color("idle")
        return (self._brightness("idle"), idle)

    def _color(self, key):
        return self.Config.get(f"colors.{key}", DEFAULT_COLORS[key])

    def _brightness(self, key):
        return self.Config.get(f"brightness.{key}", DEFAULT_BRIGHTNESS[key])

    def _clear_all_pads(self):
        behavior, color = LED_OFF
        for note in APC_GRID_NOTES:
            self._send_pad(note, behavior, color)

    def _send_pad(self, note, behavior, color):
        try:
            self._midi.output.send(
                mido.Message(
                    "note_on", channel=behavior, note=note, velocity=color,
                )
            )
        except Exception:
            logger.exception("APC Mini Cart: failed to send pad LED.")

    # ---- identify (UI smoke test) --------------------------------------

    def identify(self):
        if not self._active:
            logger.info("APC Mini Cart: identify ignored, plugin not active.")
            return
        self._identify_active = True
        for note in APC_GRID_NOTES:
            self._send_pad(note, BEHAVIOR_FULL, COLOR_WHITE)
        QTimer.singleShot(IDENTIFY_MS, self._identify_finish)

    def _identify_finish(self):
        self._identify_active = False
        if self._active:
            self._rebind_current_page()
        else:
            self._clear_all_pads()

    # ---- faders: row selection + soft takeover -------------------------

    def _handle_scene_press(self, note):
        row = self._scene_note_to_row(note)
        if self._selected_row == row:
            # Re-press of the currently selected row.
            if self._shift_held:
                # Shift+tap: toggle volume <-> pan.
                self._current_mode = (
                    ROW_MODE_PAN if self._current_mode == ROW_MODE_VOLUME
                    else ROW_MODE_VOLUME
                )
            elif self._current_mode == ROW_MODE_PAN:
                # Plain tap on a pan-mode row: back to volume (still selected).
                self._current_mode = ROW_MODE_VOLUME
            else:
                # Plain tap on a volume-mode row: deselect.
                self._selected_row = None
                self._current_mode = ROW_MODE_VOLUME
        else:
            # Different row (or none) selected: switch. Shift => pan, else volume.
            self._selected_row = row
            self._current_mode = ROW_MODE_PAN if self._shift_held else ROW_MODE_VOLUME
        self._reset_fader_latches()
        self._paint_scene_leds()

    def _handle_fader(self, col, cc_value):
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
                # the slider was on yet. Wait for a second sample.
                return
            # Crossing test in CC space: (prev - target) and (curr - target)
            # have opposite signs (or one is zero) iff the slider crossed or
            # landed on the target value.
            if (prev_cc - target_cc) * (cc_value - target_cc) > 0:
                return
            self._slider_latched[col] = True

        new_value = self._cc_to_value(cc_value, mode)
        try:
            self._write_property(element, mode, new_value)
        except Exception:
            logger.exception("APC Mini Cart: failed to write %s on cue %r.", mode, cue.name)
            return
        self._slider_position[col] = cc_value

    def _reset_fader_latches(self):
        for i in range(8):
            self._slider_latched[i] = False
            self._slider_position[i] = -1

    @staticmethod
    def _fader_element(cue, mode):
        media = getattr(cue, "media", None)
        if media is None or not hasattr(media, "element"):
            return None
        if mode == ROW_MODE_VOLUME:
            return media.element("Volume")
        return media.element("AudioPan")

    @staticmethod
    def _read_property(element, mode):
        if mode == ROW_MODE_VOLUME:
            return float(element.live_volume)
        return float(element.pan)

    @staticmethod
    def _write_property(element, mode, value):
        if mode == ROW_MODE_VOLUME:
            element.live_volume = value
        else:
            element.pan = value

    @staticmethod
    def _value_to_cc(value, mode):
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
        if mode == ROW_MODE_VOLUME:
            return cc / 127.0 * VOLUME_CC_MAX
        if abs(cc - PAN_CENTER_CC) <= PAN_CENTER_TOL:
            return 0.0
        if cc < PAN_CENTER_CC:
            return (cc - PAN_CENTER_CC) / PAN_CENTER_CC  # -1.0 .. 0
        return (cc - PAN_CENTER_CC) / (127 - PAN_CENTER_CC)  # 0 .. +1.0

    # ---- Scene Launch LEDs ---------------------------------------------

    @staticmethod
    def _scene_note_to_row(note):
        # Assumes Scene Launch 1 (top) = note 0x70; flip this mapping if
        # hardware test shows the buttons are numbered bottom-up.
        return note - APC_SCENE_NOTES[0]

    def _paint_scene_leds(self):
        for row in range(8):
            if row == self._selected_row:
                led = SCENE_LED_BLINK if self._current_mode == ROW_MODE_PAN else SCENE_LED_ON
            else:
                led = SCENE_LED_OFF
            self._send_scene_led(row, led)

    def _clear_scene_leds(self):
        for row in range(8):
            self._send_scene_led(row, SCENE_LED_OFF)

    def _send_scene_led(self, row, value):
        try:
            self._midi.output.send(
                mido.Message(
                    "note_on",
                    channel=APC_CHANNEL,
                    note=APC_SCENE_NOTES[0] + row,
                    velocity=value,
                )
            )
        except Exception:
            logger.exception("APC Mini Cart: failed to send Scene Launch LED.")
