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

# APC mk2 LED behavior nibbles (Note-On channel).
BEHAVIOR_DIM = 0               # 10% solid
BEHAVIOR_FULL = 6              # 100% solid
BEHAVIOR_PULSE_QUARTER = 9     # pulse 1/4
BEHAVIOR_BLINK_SIXTEENTH = 12  # blink 1/16

COLOR_OFF = 0
COLOR_WHITE = 3

LED_OFF = (BEHAVIOR_DIM, COLOR_OFF)

IDENTIFY_MS = 1000


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
        self._active = False
        logger.info("APC Mini Cart: deactivated.")

    # ---- inbound: pad press -> cue.execute -----------------------------

    def _on_midi_message(self, message):
        if message.type != "note_on":
            return
        if message.channel != APC_CHANNEL:
            return
        if message.note not in APC_GRID_NOTES:
            return

        row = 7 - (message.note // 8)
        col = message.note % 8
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
        self._rebind_current_page()

    def _on_model_changed(self, *_):
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
