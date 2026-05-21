"""Protocol-level and palette constants shared by the plugin and its UI.

Keeping these here (rather than in ``settings.py``) avoids a circular-feeling
import where the main plugin module pulls device constants out of a UI file.
The Akai APC Mini mk2 protocol reference lives in the project primer; the
short story is reproduced in the comments below.
"""

# ---------------------------------------------------------------------------
# MIDI / grid layout
# ---------------------------------------------------------------------------

# All 64 grid pads share MIDI channel 0 and use notes 0..63.
APC_CHANNEL = 0
APC_GRID_NOTES = range(0, 64)

# Grid dimensions. Hardcoded for the mk2's 8x8 — see "Deferred Step 7 scope"
# in CLAUDE.md for the planned grid-size compatibility check.
GRID_ROWS = 8
GRID_COLS = 8

# Scene Launch buttons (right of grid), single-color green. Assumed top-to-bottom:
# 0x70 = top row, 0x77 = bottom. Verify against hardware; flip _scene_note_to_row
# if reversed. LEDs accept VV = 0 (off), 1 (on), 2 (blink) only — these buttons
# have no brightness control on the mk2 (confirmed on hardware 2026-05-21).
#
# The Shift button is intentionally unused: on hardware, Shift + some Scene
# Launch buttons triggers built-in firmware modes (e.g. a demo mode), so it
# can't be repurposed safely. Fader-row mode is cycled by repeated taps instead.
APC_SCENE_NOTES = range(0x70, 0x78)

# Faders 1-8 send CC 0x30..0x37; master at 0x38 is intentionally unmapped.
APC_FADER_CCS = range(0x30, 0x38)


# ---------------------------------------------------------------------------
# LED behavior nibbles
# ---------------------------------------------------------------------------
#
# The mk2 encodes pad LED behavior in the Note-On *channel* (0..15):
#   0..6   solid, ascending brightness (10/25/50/65/75/90/100 %)
#   7..10  pulse, varying speed
#   11..15 blink, varying speed
# Velocity selects the colour from a 128-entry palette.

BEHAVIOR_DIM = 0               # 10% solid (fallback / "off-ish")
BEHAVIOR_FULL = 6              # 100% solid
BEHAVIOR_PULSE_QUARTER = 9     # pulse at 1/4
BEHAVIOR_BLINK_SIXTEENTH = 12  # blink at 1/16

# Brightness slider positions map 1:1 onto the seven solid-brightness nibbles.
BRIGHTNESS_LABELS = ["10%", "25%", "50%", "65%", "75%", "90%", "100%"]


# ---------------------------------------------------------------------------
# Scene Launch LEDs
# ---------------------------------------------------------------------------

# Scene Launch (row button) LED states. These buttons have no brightness
# control on the mk2 (confirmed on hardware 2026-05-21), so selection is shown
# purely by state: unselected = off, selected in volume mode = solid on,
# selected in pan mode = blink.
SCENE_LED_OFF = 0
SCENE_LED_ON = 1
SCENE_LED_BLINK = 2


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

COLOR_OFF = 0
COLOR_WHITE = 3

# A pad written with this (behavior, color) pair is effectively dark.
LED_OFF = (BEHAVIOR_DIM, COLOR_OFF)

# Limited APC mk2 palette exposed in the UI. Values are palette indices
# (see Akai protocol PDF p.4-5). "Default" / None means "use the plugin's
# global idle color" for per-cue overrides.
#
# IMPORTANT: every value used in DEFAULT_COLORS must appear here, otherwise
# the settings combo can't represent it: QComboBox.findData() returns -1 and
# _select_combo_value() silently falls back to index 0 (White), which then
# gets written back on save. Green is 87 (bright green #00FF00) precisely
# because that's the running default below.
PALETTE_CHOICES = [
    ("Default", None),
    ("White", 3),
    ("Red", 5),
    ("Yellow", 13),
    ("Green", 87),
    ("Blue", 45),
    ("Magenta", 53),
]

# Same list minus the "Default" entry, used by the app-level page where
# every state must resolve to a concrete colour.
APP_LEVEL_PALETTE = [
    (label, value) for label, value in PALETTE_CHOICES if value is not None
]


# ---------------------------------------------------------------------------
# Default settings (mirrored in default.json)
# ---------------------------------------------------------------------------

DEFAULT_COLORS = {
    "idle": 3,      # white
    "running": 87,  # bright green
    "paused": 13,   # yellow
    "error": 5,     # red
}

DEFAULT_BRIGHTNESS = {
    "idle": 0,     # 10%
    "running": 6,  # 100%
}


# ---------------------------------------------------------------------------
# Fader mappings
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Soft-takeover hunting indicator
# ---------------------------------------------------------------------------
#
# Painted only on mappable pads in the selected row while their fader is
# unlatched. Slow "breathing" pulse (1/2, slower than the 1/4 pulse used for
# paused) plus a color that tells the operator which way to move the fader to
# catch the stored value:
#   - armed but untouched (position unknown): white
#   - fader below the value -> push UP:        blue
#   - fader above the value -> pull DOWN:       magenta
# On catch (latch) the pad snaps back to its normal cue-state color.
HUNT_BEHAVIOR = 10        # pulse 1/2
HUNT_ARMED_COLOR = 3      # white
HUNT_UP_COLOR = 45        # blue
HUNT_DOWN_COLOR = 53      # magenta


# ---------------------------------------------------------------------------
# Pad-press trigger modes
# ---------------------------------------------------------------------------
#
#   "toggle"    -> cue.execute() (LiSP's native: start if stopped, stop if running)
#   "retrigger" -> interrupt + start (always play from the beginning)

TRIGGER_MODE_DEFAULT = "retrigger"

GLOBAL_TRIGGER_MODE_CHOICES = [
    ("Retrigger (restart from beginning)", "retrigger"),
    ("Toggle (press again to stop)", "toggle"),
]

CUE_TRIGGER_MODE_CHOICES = [
    ("Use default", None),
    ("Retrigger (restart from beginning)", "retrigger"),
    ("Toggle (press again to stop)", "toggle"),
]


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------

# Duration (milliseconds) of the "Flash grid" identify smoke test.
IDENTIFY_MS = 1000
