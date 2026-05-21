# This file is part of the APC Mini Cart plugin for Linux Show Player.
#
# Copyright (C) 2026 Niels van der Hulst
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. There is NO WARRANTY, to the extent permitted by law.
# See the GNU General Public License (LICENSE) for details.

"""Preferences and per-cue settings pages for the APC Mini Cart plugin.

Two pages are exposed:

* :class:`ApcMiniCartSettings` — app-level page reached from
  ``Preferences -> APC Mini Cart``. Lets the user set default state colours,
  per-state brightness, pad-press behaviour, and run a hardware smoke test.
* :class:`ApcMiniCartCueSettings` — per-cue ``APC Mini`` tab. Lets the user
  override the idle colour and trigger mode on a single cart.

Both pages share helpers at the top of the file. All protocol constants
(palette indices, brightness labels, defaults) live in
:mod:`apc_mini_cart.constants`.
"""

import logging

from PyQt5.QtCore import Qt, QT_TRANSLATE_NOOP
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from lisp.plugins import get_plugin
from lisp.ui.settings.pages import SettingsPage
from lisp.ui.ui_utils import translate

from .constants import (
    APP_LEVEL_PALETTE,
    BRIGHTNESS_LABELS,
    CUE_TRIGGER_MODE_CHOICES,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLORS,
    GLOBAL_TRIGGER_MODE_CHOICES,
    PALETTE_CHOICES,
    TRIGGER_MODE_DEFAULT,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Widget helpers
# ---------------------------------------------------------------------------

def _build_combo(parent, choices):
    """Build a ``QComboBox`` from a list of ``(label, value)`` tuples.

    The value is stashed on each item via ``userData`` so callers can read
    it back with ``combo.currentData()``.
    """
    combo = QComboBox(parent)
    for label, value in choices:
        combo.addItem(label, userData=value)
    return combo


def _select_combo_value(combo, value):
    """Select the combo item whose ``userData`` equals ``value``.

    When no item matches we fall back to index 0 and *warn*: saving will then
    overwrite the stored value with that entry, which is silent data loss. The
    warning makes a palette/default mismatch (see PALETTE_CHOICES) visible
    instead of mysterious.
    """
    idx = combo.findData(value)
    if idx < 0:
        logger.warning(
            "APC Mini Cart: settings value %r not in combo choices; "
            "defaulting to first entry. This will overwrite it on save.",
            value,
        )
        idx = 0
    combo.setCurrentIndex(idx)


def _build_brightness_row(parent):
    """Build a discrete brightness slider with a percentage label.

    Returns ``(row_layout, slider, value_label)``. The slider snaps to the
    seven valid solid-brightness nibbles; the label shows the matching
    ``BRIGHTNESS_LABELS`` entry and updates live as the user drags.
    """
    slider = QSlider(Qt.Horizontal, parent)
    slider.setRange(0, len(BRIGHTNESS_LABELS) - 1)
    slider.setSingleStep(1)
    slider.setPageStep(1)
    slider.setTickPosition(QSlider.TicksBelow)
    slider.setTickInterval(1)

    value_label = QLabel(parent)
    value_label.setMinimumWidth(40)
    value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    slider.valueChanged.connect(
        lambda v: value_label.setText(BRIGHTNESS_LABELS[v])
    )

    row = QHBoxLayout()
    row.addWidget(slider, stretch=1)
    row.addWidget(value_label)
    return row, slider, value_label


# ---------------------------------------------------------------------------
# App-level page (Preferences -> APC Mini Cart)
# ---------------------------------------------------------------------------

class ApcMiniCartSettings(SettingsPage):
    """App-level preferences page for the plugin."""

    Name = QT_TRANSLATE_NOOP("SettingsPageName", "APC Mini Cart")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        self._build_colors_group()
        self._build_behavior_group()
        self._build_brightness_group()
        self._build_identify_group()

        self.retranslateUi()

    # -- group construction ------------------------------------------------

    def _build_colors_group(self):
        """Default colour combos for each cue state."""
        self.colorsGroup = QGroupBox(self)
        self.colorsGroup.setLayout(QFormLayout())
        self.layout().addWidget(self.colorsGroup)

        self.idleCombo = _build_combo(self.colorsGroup, APP_LEVEL_PALETTE)
        self.runningCombo = _build_combo(self.colorsGroup, APP_LEVEL_PALETTE)
        self.pausedCombo = _build_combo(self.colorsGroup, APP_LEVEL_PALETTE)
        self.errorCombo = _build_combo(self.colorsGroup, APP_LEVEL_PALETTE)

        self.idleLabel = QLabel()
        self.runningLabel = QLabel()
        self.pausedLabel = QLabel()
        self.errorLabel = QLabel()

        form = self.colorsGroup.layout()
        form.addRow(self.idleLabel, self.idleCombo)
        form.addRow(self.runningLabel, self.runningCombo)
        form.addRow(self.pausedLabel, self.pausedCombo)
        form.addRow(self.errorLabel, self.errorCombo)

    def _build_behavior_group(self):
        """Global pad-press behaviour (toggle vs. retrigger)."""
        self.behaviorGroup = QGroupBox(self)
        self.behaviorGroup.setLayout(QFormLayout())
        self.layout().addWidget(self.behaviorGroup)

        self.triggerModeCombo = _build_combo(
            self.behaviorGroup, GLOBAL_TRIGGER_MODE_CHOICES
        )
        self.triggerModeLabel = QLabel()
        self.behaviorGroup.layout().addRow(self.triggerModeLabel, self.triggerModeCombo)

    def _build_brightness_group(self):
        """Discrete brightness sliders for idle and running states."""
        self.brightnessGroup = QGroupBox(self)
        self.brightnessGroup.setLayout(QFormLayout())
        self.layout().addWidget(self.brightnessGroup)

        idleRow, self.idleBrightnessSlider, self.idleBrightnessValue = (
            _build_brightness_row(self.brightnessGroup)
        )
        runningRow, self.runningBrightnessSlider, self.runningBrightnessValue = (
            _build_brightness_row(self.brightnessGroup)
        )

        self.idleBrightnessLabel = QLabel()
        self.runningBrightnessLabel = QLabel()
        self.brightnessHint = QLabel()
        self.brightnessHint.setWordWrap(True)

        bform = self.brightnessGroup.layout()
        bform.addRow(self.idleBrightnessLabel, idleRow)
        bform.addRow(self.runningBrightnessLabel, runningRow)
        bform.addRow(self.brightnessHint)

    def _build_identify_group(self):
        """The ``Flash grid`` smoke-test button."""
        self.identifyGroup = QGroupBox(self)
        self.identifyGroup.setLayout(QHBoxLayout())
        self.layout().addWidget(self.identifyGroup)

        self.identifyButton = QPushButton(self.identifyGroup)
        self.identifyButton.clicked.connect(self._on_identify_clicked)
        self.identifyGroup.layout().addWidget(self.identifyButton)

        self.identifyHint = QLabel(self.identifyGroup)
        self.identifyHint.setWordWrap(True)
        self.identifyGroup.layout().addWidget(self.identifyHint, stretch=1)

    # -- translation -------------------------------------------------------

    def retranslateUi(self):
        """Re-apply translated labels. Called on construction and language change."""
        self.colorsGroup.setTitle(translate("ApcMiniCart", "Default LED colors"))
        self.idleLabel.setText(translate("ApcMiniCart", "Idle (cue present, stopped):"))
        self.runningLabel.setText(translate("ApcMiniCart", "Running:"))
        self.pausedLabel.setText(translate("ApcMiniCart", "Paused:"))
        self.errorLabel.setText(translate("ApcMiniCart", "Error:"))
        self.behaviorGroup.setTitle(translate("ApcMiniCart", "Pad press behavior"))
        self.triggerModeLabel.setText(translate("ApcMiniCart", "Default action:"))
        self.brightnessGroup.setTitle(translate("ApcMiniCart", "Brightness"))
        self.idleBrightnessLabel.setText(translate("ApcMiniCart", "Idle:"))
        self.runningBrightnessLabel.setText(translate("ApcMiniCart", "Running:"))
        self.brightnessHint.setText(translate(
            "ApcMiniCart",
            "Paused (pulse) and error (blink) use the device's built-in "
            "animations — their brightness is fixed by the hardware.",
        ))
        self.identifyGroup.setTitle(translate("ApcMiniCart", "Hardware check"))
        self.identifyButton.setText(translate("ApcMiniCart", "Flash grid"))
        self.identifyHint.setText(translate(
            "ApcMiniCart",
            "Flashes all 64 pads white for ~1 s, then restores normal state. "
            "Only works while a Cart Layout session is active.",
        ))

    # -- load / save -------------------------------------------------------

    def loadSettings(self, settings):
        """Populate widgets from the plugin's persisted config dict."""
        colors = settings.get("colors", {}) if settings else {}
        _select_combo_value(self.idleCombo, colors.get("idle", DEFAULT_COLORS["idle"]))
        _select_combo_value(self.runningCombo, colors.get("running", DEFAULT_COLORS["running"]))
        _select_combo_value(self.pausedCombo, colors.get("paused", DEFAULT_COLORS["paused"]))
        _select_combo_value(self.errorCombo, colors.get("error", DEFAULT_COLORS["error"]))

        _select_combo_value(
            self.triggerModeCombo,
            (settings or {}).get("trigger_mode", TRIGGER_MODE_DEFAULT),
        )

        brightness = settings.get("brightness", {}) if settings else {}
        self.idleBrightnessSlider.setValue(brightness.get("idle", DEFAULT_BRIGHTNESS["idle"]))
        self.runningBrightnessSlider.setValue(brightness.get("running", DEFAULT_BRIGHTNESS["running"]))
        # Force value-label refresh in case the slider was already at the
        # loaded value (valueChanged only fires when the value changes).
        self.idleBrightnessValue.setText(BRIGHTNESS_LABELS[self.idleBrightnessSlider.value()])
        self.runningBrightnessValue.setText(BRIGHTNESS_LABELS[self.runningBrightnessSlider.value()])

    def getSettings(self):
        """Serialize the page's widgets back into a config dict."""
        return {
            "colors": {
                "idle": self.idleCombo.currentData(),
                "running": self.runningCombo.currentData(),
                "paused": self.pausedCombo.currentData(),
                "error": self.errorCombo.currentData(),
            },
            "brightness": {
                "idle": self.idleBrightnessSlider.value(),
                "running": self.runningBrightnessSlider.value(),
            },
            "trigger_mode": self.triggerModeCombo.currentData(),
        }

    # -- actions -----------------------------------------------------------

    def _on_identify_clicked(self):
        """Trigger the plugin's identify smoke test."""
        try:
            plugin = get_plugin("ApcMiniCart")
        except Exception:
            return
        plugin.identify()


# ---------------------------------------------------------------------------
# Per-cue page (APC Mini tab on each cue's edit dialog)
# ---------------------------------------------------------------------------

class ApcMiniCartCueSettings(SettingsPage):
    """Per-cue overrides: idle colour and pad-press action."""

    Name = QT_TRANSLATE_NOOP("SettingsPageName", "APC Mini")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLayout(QVBoxLayout())
        self.layout().setAlignment(Qt.AlignTop)

        self.group = QGroupBox(self)
        self.group.setLayout(QFormLayout())
        self.layout().addWidget(self.group)

        self.colorLabel = QLabel()
        self.colorCombo = _build_combo(self.group, PALETTE_CHOICES)
        self.group.layout().addRow(self.colorLabel, self.colorCombo)

        self.triggerModeLabel = QLabel()
        self.triggerModeCombo = _build_combo(self.group, CUE_TRIGGER_MODE_CHOICES)
        self.group.layout().addRow(self.triggerModeLabel, self.triggerModeCombo)

        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        self.layout().addWidget(self.hint)

        self.retranslateUi()

    def retranslateUi(self):
        """Re-apply translated labels."""
        self.group.setTitle(translate("ApcMiniCart", "Pad behavior"))
        self.colorLabel.setText(translate("ApcMiniCart", "Idle color:"))
        self.triggerModeLabel.setText(translate("ApcMiniCart", "Pad action:"))
        self.hint.setText(translate(
            "ApcMiniCart",
            "Idle color overrides the global idle color while this cue is stopped. "
            "Pad action overrides the global pad-press behavior for this cue. "
            "Running / paused / error use the plugin's global colors.",
        ))

    def enableCheck(self, enabled):
        """Toggle the group's enabled state from LiSP's cue-settings UI."""
        self.setGroupEnabled(self.group, enabled)

    def loadSettings(self, settings):
        """Populate combos from a cue's persisted properties."""
        _select_combo_value(self.colorCombo, settings.get("apc_idle_color"))
        _select_combo_value(self.triggerModeCombo, settings.get("apc_trigger_mode"))

    def getSettings(self):
        """Serialize combo selections back into cue properties.

        Returns an empty dict when the group is disabled so LiSP doesn't
        overwrite the cue's existing values.
        """
        if not self.isGroupEnabled(self.group):
            return {}
        return {
            "apc_idle_color": self.colorCombo.currentData(),
            "apc_trigger_mode": self.triggerModeCombo.currentData(),
        }
