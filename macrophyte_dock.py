"""
Dock panel for macrophyte field data collection.
Compact layout for scaled laptop screens.

GPS is always the live location source while the panel is open. Map-click
is a one-shot override for placing a single point somewhere unreachable —
it never disconnects GPS. Quick Capture (habitat tap saves instantly at the
GPS position) can be toggled on; arming a map-click placement suspends it
for that one point, then it resumes automatically.
"""

from qgis.PyQt.QtCore import pyqtSignal, QDateTime, QTimer, Qt
from qgis.PyQt.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                 QGridLayout, QPushButton, QLabel,
                                 QTextEdit, QGroupBox, QMessageBox,
                                 QScrollArea, QFrame, QSizePolicy)

ACTIVE_STYLE = "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; border: 1px solid #1b5e20; border-radius: 3px; }"
DEFAULT_STYLE = "QPushButton { background-color: #f0f0f0; border: 1px solid #aaa; border-radius: 3px; } QPushButton:hover { background-color: #dde; }"
ADD_STYLE = "QPushButton { background-color: #1565C0; color: white; font-weight: bold; border-radius: 4px; padding: 4px; }"
CLEAR_STYLE = "QPushButton { background-color: #c62828; color: white; border-radius: 4px; padding: 4px; }"

CLICK_ARMED_STYLE = (
    "QPushButton { background-color: #1565C0; color: white; font-weight: bold; "
    "border: 2px solid #0d47a1; border-radius: 4px; padding: 4px; }"
)
CLICK_IDLE_STYLE = (
    "QPushButton { background-color: #f0f0f0; border: 1px solid #aaa; "
    "border-radius: 4px; padding: 4px; } QPushButton:hover { background-color: #dde; }"
)
MARK_STYLE = (
    "QPushButton { background-color: #6a1b9a; color: white; font-weight: bold; "
    "border: 2px solid #4a148c; border-radius: 4px; padding: 4px; }"
)
MARK_LOCKED_STYLE = (
    "QPushButton { background-color: #2e7d32; color: white; font-weight: bold; "
    "border: 2px solid #1b5e20; border-radius: 4px; padding: 4px; }"
)
QUICK_ON_STYLE = (
    "QPushButton { background-color: #e65100; color: white; font-weight: bold; "
    "border: 2px solid #bf360c; border-radius: 4px; padding: 4px; }"
)
QUICK_PAUSED_STYLE = (
    "QPushButton { background-color: #cccccc; color: #777; font-weight: bold; "
    "border: 2px solid #aaa; border-radius: 4px; padding: 4px; }"
)

STATUS_NORMAL_STYLE = (
    "QLabel { background: #e8f5e9; border: 1px solid #a5d6a7; "
    "border-radius: 3px; padding: 3px; font-size: 9pt; }"
)
STATUS_SAVED_STYLE = (
    "QLabel { background: #bbdefb; border: 1px solid #90caf9; "
    "border-radius: 3px; padding: 3px; font-size: 9pt; }"
)
STATUS_QUICK_STYLE = (
    "QLabel { background: #fff3e0; border: 1px solid #ffcc80; "
    "border-radius: 3px; padding: 3px; font-size: 9pt; }"
)
STATUS_QUICK_SAVED_STYLE = (
    "QLabel { background: #ffe0b2; border: 1px solid #ffb74d; "
    "border-radius: 3px; padding: 3px; font-size: 9pt; }"
)
NOGPS_STYLE = (
    "QLabel { background: #ffebee; border: 1px solid #ef9a9a; color: #b71c1c; "
    "border-radius: 3px; padding: 3px; font-size: 9pt; font-weight: bold; }"
)
UNDO_STYLE = (
    "QPushButton { background-color: #00838f; color: white; font-weight: bold; "
    "border-radius: 4px; padding: 4px; } QPushButton:hover { background-color: #006064; }"
)

QUICK_DEBOUNCE_MS = 800

HABITAT_VALUE_MAP = {
    # Seagrass
    "Posidonia":     "Posidonia",
    "Sparse Pos":    "Sparse Posidonia",
    "Pos/Zost":      "Posidonia/Zostera",
    "Halophila":     "Halophila",
    "Zostera":       "Zostera",
    "Sparse Zos":    "Sparse Zostera",
    "Zost/Ruppia":   "Zostera/Ruppia",
    "Ruppia":        "Ruppia",
    "Caulerpa":      "Caulerpa",
    "Algae":         "Algae",
    "Sand":          "Sand",
    "Rock":          "Rock",
    "Wrack":         "Wrack",
    "Deep edge":     "Deep edge",
    "Boundary":      "Boundary",
    "Other":         "Other",
    "As mapped":     "As mapped",
    # Mangrove / Saltmarsh
    "Single Tree":    "Single mangrove tree",
    "Small group":    "Small group of mangroves",
    "Scattered":      "Scattered mangroves",
    "No Mangrove":    "No mangroves present",
    "Fringing":       "Fringing mangroves",
    "Widespread":     "Widespread mangroves",
    "Saltmarsh":      "Saltmarsh",
    "No Saltmrsh":    "No saltmarsh present",
}


class MacrophyteDockWidget(QWidget):

    record_requested        = pyqtSignal(dict)
    activate_tool_requested = pyqtSignal()   # arm map-click for one placement
    disarm_tool_requested   = pyqtSignal()   # disarm map-click without placing
    cancel_point_requested  = pyqtSignal()
    mark_location_requested = pyqtSignal()
    quick_capture_requested = pyqtSignal(str)
    undo_last_requested     = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.current_habitat       = ""
        self.current_habitat_label = ""
        self.longitude    = None
        self.latitude     = None
        self.marked_lon   = None
        self.marked_lat   = None
        self.coord_source = "GPS"
        self.location_locked = False
        self.has_gps = False
        self.quick_capture = False
        self.map_click_armed = False
        self._last_quick_ms = 0
        self._sg_buttons  = {}
        self._mn_buttons  = {}
        self._init_ui()

    # ------------------------------------------------------------------
    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Preferred,
                                QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(container)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        # ── Capture controls ────────────────────────────────────────
        mode_box = QGroupBox("Capture")
        mode_lay = QVBoxLayout()
        mode_lay.setSpacing(3)
        mode_lay.setContentsMargins(4, 4, 4, 4)

        # Live GPS position / no-GPS notice
        self.coord_lbl = QLabel("Waiting for GPS…")
        self.coord_lbl.setStyleSheet("font-size: 9pt; color: #444;")
        mode_lay.addWidget(self.coord_lbl)

        # Row: Mark Location + Map-click override
        loc_row = QHBoxLayout()
        loc_row.setSpacing(4)

        self.mark_btn = QPushButton("📍 Mark Location")
        self.mark_btn.setMinimumHeight(30)
        self.mark_btn.setStyleSheet(MARK_STYLE)
        self.mark_btn.clicked.connect(self._on_mark_clicked)
        loc_row.addWidget(self.mark_btn)

        self.click_btn = QPushButton("🖱 Map Click")
        self.click_btn.setMinimumHeight(30)
        self.click_btn.setStyleSheet(CLICK_IDLE_STYLE)
        self.click_btn.clicked.connect(self._on_click_toggle)
        loc_row.addWidget(self.click_btn)

        mode_lay.addLayout(loc_row)

        # Quick Capture toggle
        self.quick_btn = QPushButton("⚡ Quick: OFF")
        self.quick_btn.setCheckable(True)
        self.quick_btn.setMinimumHeight(28)
        self.quick_btn.setStyleSheet(DEFAULT_STYLE)
        self.quick_btn.clicked.connect(self._on_quick_toggle)
        mode_lay.addWidget(self.quick_btn)

        mode_box.setLayout(mode_lay)
        mode_box.setSizePolicy(QSizePolicy.Policy.Preferred,
                               QSizePolicy.Policy.Maximum)
        layout.addWidget(mode_box)

        # ── Status ───────────────────────────────────────────────────
        self.status_lbl = QLabel("No selection")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(STATUS_NORMAL_STYLE)
        layout.addWidget(self.status_lbl)

        # ── Seagrass ─────────────────────────────────────────────────
        sg_box = QGroupBox("Seagrass")
        sg_grid = QGridLayout()
        sg_grid.setSpacing(2)
        sg_grid.setContentsMargins(4, 4, 4, 4)
        seagrass_rows = [
            ["Posidonia",  "Sparse Pos",  "Pos/Zost",    "Halophila"],
            ["Zostera",    "Sparse Zos",  "Zost/Ruppia", "Ruppia"],
            ["Caulerpa",   "Algae",       "Sand",        "Rock"],
            ["Wrack",      "Deep edge",   "Boundary",    "Other"],
        ]
        for r, row in enumerate(seagrass_rows):
            for c, text in enumerate(row):
                btn = QPushButton(text)
                btn.setStyleSheet(DEFAULT_STYLE)
                btn.setMaximumHeight(26)
                btn.setMinimumHeight(26)
                btn.clicked.connect(
                    lambda checked, t=text: self._habitat_clicked(t, self._sg_buttons))
                sg_grid.addWidget(btn, r, c)
                self._sg_buttons[text] = btn

        mapped_btn = QPushButton("As mapped")
        mapped_btn.setStyleSheet(DEFAULT_STYLE)
        mapped_btn.setMaximumHeight(26)
        mapped_btn.setMinimumHeight(26)
        mapped_btn.clicked.connect(
            lambda: self._habitat_clicked("As mapped", self._sg_buttons))
        self._sg_buttons["As mapped"] = mapped_btn

        sg_clear = QPushButton("Clear")
        sg_clear.setStyleSheet(CLEAR_STYLE)
        sg_clear.setMaximumHeight(26)
        sg_clear.setMinimumHeight(26)
        sg_clear.clicked.connect(self._clear_habitat)

        sg_grid.addWidget(mapped_btn, 4, 0, 1, 2)
        sg_grid.addWidget(sg_clear,   4, 2, 1, 2)
        sg_box.setLayout(sg_grid)
        sg_box.setSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Maximum)
        layout.addWidget(sg_box)

        # ── Mangrove / Saltmarsh ─────────────────────────────────────
        mn_box = QGroupBox("Mangrove / Saltmarsh")
        mn_grid = QGridLayout()
        mn_grid.setSpacing(2)
        mn_grid.setContentsMargins(4, 4, 4, 4)
        mangrove_rows = [
            ["Single Tree", "Small group",  "Scattered", "Fringing"],
            ["Widespread",  "No Mngrves", "Saltmarsh", "No Sltmsh"],
        ]
        for r, row in enumerate(mangrove_rows):
            for c, text in enumerate(row):
                if not text:
                    continue
                btn = QPushButton(text)
                btn.setStyleSheet(DEFAULT_STYLE)
                btn.setMaximumHeight(26)
                btn.setMinimumHeight(26)
                btn.clicked.connect(
                    lambda checked, t=text: self._habitat_clicked(t, self._mn_buttons))
                mn_grid.addWidget(btn, r, c)
                self._mn_buttons[text] = btn

        mn_box.setLayout(mn_grid)
        mn_box.setSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Maximum)
        layout.addWidget(mn_box)

        # ── Comments ─────────────────────────────────────────────────
        cmt_box = QGroupBox("Comments")
        cmt_lay = QVBoxLayout()
        cmt_lay.setSpacing(2)
        cmt_lay.setContentsMargins(4, 4, 4, 4)

        self.comments_edit = QTextEdit()
        self.comments_edit.setFixedHeight(50)
        self.comments_edit.setPlaceholderText("Type or use buttons below…")
        cmt_lay.addWidget(self.comments_edit)

        for word_row in [
            ["Posidonia", "Zostera",  "Halophila", "Ruppia",  "Caulerpa"],
            ["Wrack",     "Algae",    "Rock",      "Sand",    "and"],
            ["Dense",     "Medium",   "Sparse",    "with",    "Clear"],
        ]:
            row_lay = QHBoxLayout()
            row_lay.setSpacing(2)
            for w in word_row:
                btn = QPushButton(w)
                btn.setMaximumHeight(26)
                btn.setMinimumHeight(26)
                if w == "Clear":
                    btn.setStyleSheet(CLEAR_STYLE)
                    btn.clicked.connect(self.comments_edit.clear)
                else:
                    btn.setStyleSheet(DEFAULT_STYLE)
                    btn.clicked.connect(
                        lambda checked, t=w: self._append_comment(t))
                row_lay.addWidget(btn)
            cmt_lay.addLayout(row_lay)

        cmt_box.setLayout(cmt_lay)
        cmt_box.setSizePolicy(QSizePolicy.Policy.Preferred,
                              QSizePolicy.Policy.Maximum)
        layout.addWidget(cmt_box)

        # ── Bottom buttons ───────────────────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(4)

        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.setStyleSheet(CLEAR_STYLE)
        clear_all_btn.setMaximumHeight(26)
        clear_all_btn.setMinimumHeight(26)
        clear_all_btn.clicked.connect(self.clear_all)

        cancel_point_btn = QPushButton("✕ Cancel Point")
        cancel_point_btn.setStyleSheet(CLEAR_STYLE)
        cancel_point_btn.setMaximumHeight(26)
        cancel_point_btn.setMinimumHeight(26)
        cancel_point_btn.clicked.connect(self._cancel_point)

        undo_btn = QPushButton("↩ Undo")
        undo_btn.setStyleSheet(UNDO_STYLE)
        undo_btn.setMaximumHeight(26)
        undo_btn.setMinimumHeight(26)
        undo_btn.clicked.connect(self.undo_last_requested.emit)

        add_btn = QPushButton("▶  Add Record")
        add_btn.setStyleSheet(ADD_STYLE)
        add_btn.setMinimumHeight(26)
        add_btn.clicked.connect(self._add_record)

        bottom_row.addWidget(clear_all_btn)
        bottom_row.addWidget(cancel_point_btn)
        bottom_row.addStretch()          # keeps Cancel away from the right group
        bottom_row.addWidget(undo_btn)
        bottom_row.addSpacing(12)        # gap between Undo and Add Record
        bottom_row.addWidget(add_btn)
        layout.addLayout(bottom_row)

    # ------------------------------------------------------------------
    # GPS availability
    # ------------------------------------------------------------------

    def set_gps_available(self, available: bool):
        """Called by the plugin when GPS connects or drops out entirely."""
        self.has_gps = available
        if not available:
            self.longitude = None
            self.latitude = None
            self.coord_lbl.setText("⚠ No GPS — connect via GPS Toolbar")
            self.coord_lbl.setStyleSheet(
                "font-size: 9pt; color: #b71c1c; font-weight: bold;")
        else:
            self.coord_lbl.setStyleSheet("font-size: 9pt; color: #444;")

    def set_coordinates(self, lon, lat, source="GPS"):
        """Update live position display only. Does not affect marked location."""
        self.longitude    = float(lon)
        self.latitude     = float(lat)
        self.coord_source = source
        self.has_gps = True
        self.coord_lbl.setText(f"{self.latitude:.6f}, {self.longitude:.6f}")
        self.coord_lbl.setStyleSheet("font-size: 9pt; color: #444;")

    # ------------------------------------------------------------------
    # Map-click override (one-shot)
    # ------------------------------------------------------------------

    def _on_click_toggle(self):
        if self.map_click_armed:
            # Disarm without placing — resume Quick if it was paused
            self.disarm_tool_requested.emit()
            self._set_map_click_armed(False)
        else:
            self._set_map_click_armed(True)
            self.activate_tool_requested.emit()

    def _set_map_click_armed(self, armed: bool):
        self.map_click_armed = armed
        if armed:
            self.click_btn.setText("🖱 Click map…")
            self.click_btn.setStyleSheet(CLICK_ARMED_STYLE)
            # Pause Quick Capture for this one placement
            if self.quick_capture:
                self._refresh_quick_button(paused=True)
        else:
            self.click_btn.setText("🖱 Map Click")
            self.click_btn.setStyleSheet(CLICK_IDLE_STYLE)
            # Resume Quick if it was on
            if self.quick_capture:
                self._refresh_quick_button(paused=False)
                self._show_quick_idle_status()

    # ------------------------------------------------------------------
    # Quick Capture
    # ------------------------------------------------------------------

    def _on_quick_toggle(self):
        # Don't allow toggling while a manual placement is in progress
        if self.map_click_armed:
            self.quick_btn.setChecked(self.quick_capture)
            return
        self._set_quick_capture(self.quick_btn.isChecked())

    def _set_quick_capture(self, on: bool):
        self.quick_capture = on
        self._refresh_quick_button(paused=False)
        if on:
            self._show_quick_idle_status()
        else:
            self.status_lbl.setStyleSheet(STATUS_NORMAL_STYLE)
            self._update_status()

    def _refresh_quick_button(self, paused: bool):
        self.quick_btn.setChecked(self.quick_capture)
        if not self.quick_capture:
            self.quick_btn.setText("⚡ Quick: OFF")
            self.quick_btn.setStyleSheet(DEFAULT_STYLE)
        elif paused:
            self.quick_btn.setText("⚡ Quick: paused")
            self.quick_btn.setStyleSheet(QUICK_PAUSED_STYLE)
        else:
            self.quick_btn.setText("⚡ Quick: ON")
            self.quick_btn.setStyleSheet(QUICK_ON_STYLE)

    def _show_quick_idle_status(self):
        self.status_lbl.setText("⚡ Quick Capture ON - Points auto save")
        self.status_lbl.setStyleSheet(STATUS_QUICK_STYLE)

    def quick_capture_saved(self, habitat, lat, lon):
        self.status_lbl.setText(f"⚡ Saved: {habitat}")
        self.status_lbl.setStyleSheet(STATUS_QUICK_SAVED_STYLE)
        QTimer.singleShot(1500, self._reset_quick_status)

    def _reset_quick_status(self):
        if self.quick_capture and not self.map_click_armed:
            self._show_quick_idle_status()
        elif not self.quick_capture:
            self._reset_status_style()

    # ------------------------------------------------------------------
    # Mark Location
    # ------------------------------------------------------------------

    def _on_mark_clicked(self):
        self.mark_location_requested.emit()

    def set_marked_location(self, lon, lat, source="GPS"):
        self.marked_lon = float(lon)
        self.marked_lat = float(lat)
        self.coord_source = source
        self.location_locked = True
        self.mark_btn.setText("📍 Marked ✔")
        self.mark_btn.setStyleSheet(MARK_LOCKED_STYLE)
        # A map-click placement has now set its location; disarm the tool
        # but keep the placement "in progress" until Add Record / Cancel.
        if self.map_click_armed:
            self.click_btn.setText("🖱 Map Click")
            self.click_btn.setStyleSheet(CLICK_IDLE_STYLE)

    def _reset_mark_btn(self):
        self.mark_btn.setText("📍 Mark Location")
        self.mark_btn.setStyleSheet(MARK_STYLE)

    # ------------------------------------------------------------------
    # Habitat selection
    # ------------------------------------------------------------------

    def _habitat_clicked(self, text, source_dict):
        mapped_value = HABITAT_VALUE_MAP.get(text, text)

        # Quick Capture — only when ON and not paused by a manual placement
        if self.quick_capture and not self.map_click_armed \
                and not self.location_locked:
            now = QDateTime.currentMSecsSinceEpoch()
            if now - self._last_quick_ms < QUICK_DEBOUNCE_MS:
                return
            self._last_quick_ms = now
            self.quick_capture_requested.emit(mapped_value)
            return

        for d in (self._sg_buttons, self._mn_buttons):
            for b in d.values():
                b.setStyleSheet(DEFAULT_STYLE)

        if self.current_habitat == mapped_value:
            self.current_habitat       = ""
            self.current_habitat_label = ""
        else:
            self.current_habitat       = mapped_value
            self.current_habitat_label = text
            source_dict[text].setStyleSheet(ACTIVE_STYLE)

        self._update_status()

    def _clear_habitat(self):
        self.current_habitat       = ""
        self.current_habitat_label = ""
        for d in (self._sg_buttons, self._mn_buttons):
            for b in d.values():
                b.setStyleSheet(DEFAULT_STYLE)
        self._update_status()

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def _append_comment(self, text):
        cur = self.comments_edit.toPlainText().strip()
        self.comments_edit.setText((cur + " " + text).strip())

    # ------------------------------------------------------------------
    # Clear / Cancel
    # ------------------------------------------------------------------

    def clear_all(self):
        self.current_habitat       = ""
        self.current_habitat_label = ""
        for d in (self._sg_buttons, self._mn_buttons):
            for b in d.values():
                b.setStyleSheet(DEFAULT_STYLE)
        self.comments_edit.clear()
        self._update_status()

    def _cancel_point(self):
        self.clear_all()
        self.marked_lon      = None
        self.marked_lat      = None
        self.location_locked = False
        self._reset_mark_btn()
        # End any in-progress manual placement and resume Quick
        was_armed = self.map_click_armed
        self._set_map_click_armed(False)
        self.cancel_point_requested.emit()
        if self.quick_capture:
            self._refresh_quick_button(paused=False)
            self._show_quick_idle_status()

    def _update_status(self):
        if self.quick_capture and not self.map_click_armed and not self.location_locked:
            return
        self.status_lbl.setText(
            f"Habitat: {self.current_habitat}" if self.current_habitat else "No selection")

    # ------------------------------------------------------------------
    # Save record
    # ------------------------------------------------------------------

    def _add_record(self):
        if not self.current_habitat:
            QMessageBox.warning(self, "Missing data", "Select a habitat type.")
            return
        if not self.location_locked or self.marked_lon is None:
            QMessageBox.warning(self, "No location marked",
                                "Press 'Mark Location' at the sighting spot, "
                                "or use Map Click, before adding a record.")
            return

        data = {
            'habitat':   self.current_habitat,
            'comments':  self.comments_edit.toPlainText(),
            'longitude': self.marked_lon,
            'latitude':  self.marked_lat,
            'timestamp': QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss"),
            'source':    self.coord_source,
        }
        self.record_requested.emit(data)

        self.status_lbl.setText("✔ Record saved!")
        self.status_lbl.setStyleSheet(STATUS_SAVED_STYLE)
        self.clear_all()
        self.marked_lon      = None
        self.marked_lat      = None
        self.location_locked = False
        self._reset_mark_btn()
        # End any manual placement and resume Quick
        self._set_map_click_armed(False)
        if self.quick_capture:
            QTimer.singleShot(1500, self._resume_quick_after_save)
        else:
            QTimer.singleShot(2000, self._reset_status_style)

    def _resume_quick_after_save(self):
        self._refresh_quick_button(paused=False)
        self._show_quick_idle_status()

    def _reset_status_style(self):
        self.status_lbl.setStyleSheet(STATUS_NORMAL_STYLE)
        self.status_lbl.setText("No selection")