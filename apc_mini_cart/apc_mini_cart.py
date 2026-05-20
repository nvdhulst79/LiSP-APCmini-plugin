import logging

from lisp.core.plugin import Plugin
from lisp.core.signal import Connection
from lisp.plugins import get_plugin
from lisp.plugins.cart_layout.layout import CartLayout

logger = logging.getLogger(__name__)

APC_GRID_NOTES = range(0, 64)
APC_CHANNEL = 0


class ApcMiniCart(Plugin):
    Name = "APC Mini Cart"
    Authors = ("Niels van der Hulst",)
    Description = "Plug-and-play Akai APC Mini mk2 control for the Cart Layout."
    Depends = ("Midi",)

    def __init__(self, app):
        super().__init__(app)
        self._midi = get_plugin("Midi")
        self._active = False

        self.app.session_created.connect(
            self._on_session_change, Connection.QtQueued
        )
        self.app.session_loaded.connect(
            self._on_session_change, Connection.QtQueued
        )
        self.app.session_before_finalize.connect(
            self._on_session_finalize, Connection.QtQueued
        )

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
        self._midi.input.new_message.connect(
            self._on_midi_message, Connection.QtQueued
        )
        self._active = True
        logger.info("APC Mini Cart: activated (Cart Layout detected).")

    def _deactivate(self):
        if not self._active:
            return
        self._midi.input.new_message.disconnect(self._on_midi_message)
        self._active = False
        logger.info("APC Mini Cart: deactivated.")

    def _on_midi_message(self, message):
        if message.type != "note_on":
            return
        if message.channel != APC_CHANNEL:
            return
        if message.note not in APC_GRID_NOTES:
            return

        # APC pad note 0 is bottom-left, count rises left-to-right, bottom-up.
        # Cart Layout indexes (0, 0) as top-left.
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

        logger.debug(
            "APC Mini Cart: firing cue %r at (page=%d, row=%d, col=%d).",
            cue.name, page, row, col,
        )
        cue.execute()
