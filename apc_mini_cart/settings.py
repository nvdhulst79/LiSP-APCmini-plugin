from PyQt5.QtCore import Qt, QT_TRANSLATE_NOOP
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from lisp.plugins import get_plugin
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate

# Limited APC mk2 palette exposed in the UI. Values are palette indices
# (see Akai protocol PDF p.4-5). "Default" / None means "use the plugin's
# global idle color" for per-cue overrides.
PALETTE_CHOICES = [
    ("Default", None),
    ("White", 3),
    ("Red", 5),
    ("Yellow", 13),
    ("Green", 21),
    ("Blue", 45),
    ("Magenta", 53),
]

# Same list without the Default entry, used by the app-level page where
# every state needs a concrete color.
APP_LEVEL_PALETTE = [(label, value) for label, value in PALETTE_CHOICES if value is not None]

DEFAULT_COLORS = {
    "idle": 3,      # white
    "running": 87,  # bright green
    "paused": 13,   # yellow
    "error": 5,     # red
}


def _build_color_combo(parent, choices):
    combo = QComboBox(parent)
    for label, value in choices:
        combo.addItem(label, userData=value)
    return combo


def _select_combo_value(combo, value):
    idx = combo.findData(value)
    combo.setCurrentIndex(idx if idx >= 0 else 0)


class ApcMiniCartSettings(SettingsPage):
    """App-level page (Preferences -> APC Mini Cart)."""

    Name = QT_TRANSLATE_NOOP("SettingsPageName", "APC Mini Cart")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        self.colorsGroup = QGroupBox(self)
        self.colorsGroup.setLayout(QFormLayout())
        self.layout().addWidget(self.colorsGroup)

        self.idleCombo = _build_color_combo(self.colorsGroup, APP_LEVEL_PALETTE)
        self.runningCombo = _build_color_combo(self.colorsGroup, APP_LEVEL_PALETTE)
        self.pausedCombo = _build_color_combo(self.colorsGroup, APP_LEVEL_PALETTE)
        self.errorCombo = _build_color_combo(self.colorsGroup, APP_LEVEL_PALETTE)

        self.idleLabel = QLabel()
        self.runningLabel = QLabel()
        self.pausedLabel = QLabel()
        self.errorLabel = QLabel()

        form = self.colorsGroup.layout()
        form.addRow(self.idleLabel, self.idleCombo)
        form.addRow(self.runningLabel, self.runningCombo)
        form.addRow(self.pausedLabel, self.pausedCombo)
        form.addRow(self.errorLabel, self.errorCombo)

        self.identifyGroup = QGroupBox(self)
        self.identifyGroup.setLayout(QHBoxLayout())
        self.layout().addWidget(self.identifyGroup)

        self.identifyButton = QPushButton(self.identifyGroup)
        self.identifyButton.clicked.connect(self._on_identify_clicked)
        self.identifyGroup.layout().addWidget(self.identifyButton)

        self.identifyHint = QLabel(self.identifyGroup)
        self.identifyHint.setWordWrap(True)
        self.identifyGroup.layout().addWidget(self.identifyHint, stretch=1)

        self.retranslateUi()

    def retranslateUi(self):
        self.colorsGroup.setTitle(translate("ApcMiniCart", "Default LED colors"))
        self.idleLabel.setText(translate("ApcMiniCart", "Idle (cue present, stopped):"))
        self.runningLabel.setText(translate("ApcMiniCart", "Running:"))
        self.pausedLabel.setText(translate("ApcMiniCart", "Paused:"))
        self.errorLabel.setText(translate("ApcMiniCart", "Error:"))
        self.identifyGroup.setTitle(translate("ApcMiniCart", "Hardware check"))
        self.identifyButton.setText(translate("ApcMiniCart", "Flash grid"))
        self.identifyHint.setText(translate(
            "ApcMiniCart",
            "Flashes all 64 pads white for ~1 s, then restores normal state. "
            "Only works while a Cart Layout session is active.",
        ))

    def loadSettings(self, settings):
        colors = settings.get("colors", {}) if settings else {}
        _select_combo_value(self.idleCombo, colors.get("idle", DEFAULT_COLORS["idle"]))
        _select_combo_value(self.runningCombo, colors.get("running", DEFAULT_COLORS["running"]))
        _select_combo_value(self.pausedCombo, colors.get("paused", DEFAULT_COLORS["paused"]))
        _select_combo_value(self.errorCombo, colors.get("error", DEFAULT_COLORS["error"]))

    def getSettings(self):
        return {
            "colors": {
                "idle": self.idleCombo.currentData(),
                "running": self.runningCombo.currentData(),
                "paused": self.pausedCombo.currentData(),
                "error": self.errorCombo.currentData(),
            },
        }

    def _on_identify_clicked(self):
        try:
            plugin = get_plugin("ApcMiniCart")
        except Exception:
            return
        plugin.identify()


class ApcMiniCartCueSettings(SettingsPage):
    """Per-cue page added to every cue's edit dialog."""

    Name = QT_TRANSLATE_NOOP("SettingsPageName", "APC Mini")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        self.group = QGroupBox(self)
        self.group.setLayout(QFormLayout())
        self.layout().addWidget(self.group)

        self.colorLabel = QLabel()
        self.colorCombo = _build_color_combo(self.group, PALETTE_CHOICES)
        self.group.layout().addRow(self.colorLabel, self.colorCombo)

        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        self.layout().addWidget(self.hint)

        self.retranslateUi()

    def retranslateUi(self):
        self.group.setTitle(translate("ApcMiniCart", "Pad appearance"))
        self.colorLabel.setText(translate("ApcMiniCart", "Idle color:"))
        self.hint.setText(translate(
            "ApcMiniCart",
            "Overrides the pad's idle color while this cue is stopped. "
            "Running / paused / error use the plugin's global colors.",
        ))

    def enableCheck(self, enabled):
        self.setGroupEnabled(self.group, enabled)

    def loadSettings(self, settings):
        _select_combo_value(self.colorCombo, settings.get("apc_idle_color"))

    def getSettings(self):
        if not self.isGroupEnabled(self.group):
            return {}
        return {"apc_idle_color": self.colorCombo.currentData()}
