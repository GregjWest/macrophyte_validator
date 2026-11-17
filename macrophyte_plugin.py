"""
Estuarine Habitat Validation Plugin for QGIS
Dock panel version — stays visible while mapping.

Compatible with QGIS 3.30+ (Qt5) and QGIS 4.x (Qt6).

GPS is the always-on location source while the panel is open. Map-click is a
one-shot override for placing a single point somewhere unreachable. Quick
Capture saves a point instantly at the GPS position on a habitat tap.

A transect toolbar (Start / Stop) records the GPS track as a line feature
into a Validation_Transects layer in the same GeoPackage. Every GPS fix is
recorded as a vertex; transects are auto-numbered. Recording requires the
panel to be open, since that is what establishes the GPS connection.

Undo removes the most recent point saved this session (single level,
point-only — never transects).

The GeoPackage is created with BOTH the points and transects layers the
first time either is needed, so capture order never matters. Existing
files missing a layer are self-healed on next use.

Data is stored in a GeoPackage saved alongside the project file, so records
persist across sessions.
"""

import os
from qgis.PyQt.QtCore import Qt, QTimer, QDateTime
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsApplication,
                       QgsVectorFileWriter, QgsFields, QgsField,
                       QgsMessageLog, Qgis)
from qgis.gui import (QgsMapToolEmitPoint, QgsDockWidget, QgsVertexMarker,
                      QgsRubberBand)

from .macrophyte_dock import MacrophyteDockWidget

LAYER_NAME = "Validation_Data"
TRANSECT_LAYER_NAME = "Validation_Transects"
GPKG_FILENAME = "Validation_Data.gpkg"
QML_FILENAME = "validation_style.qml"

# ----------------------------------------------------------------------
# Qt5 / Qt6 compatibility shim for field types.
# ----------------------------------------------------------------------
try:
    from qgis.PyQt.QtCore import QMetaType
    FIELD_INT    = QMetaType.Type.Int
    FIELD_STRING = QMetaType.Type.QString
    FIELD_DOUBLE = QMetaType.Type.Double
except ImportError:
    from qgis.PyQt.QtCore import QVariant
    FIELD_INT    = QVariant.Int
    FIELD_STRING = QVariant.String
    FIELD_DOUBLE = QVariant.Double


class MacrophyteDataPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = u'&Estuarine Habitat Validation'
        self.dock = None
        self.dock_widget = None
        self.point_tool = None
        self.marker = None
        self.gps_connection = None

        # Undo state — most recent point saved this session
        self.last_point_id = None

        # Transect recording state
        self.toolbar = None
        self.start_transect_action = None
        self.stop_transect_action = None
        self.transect_recording = False
        self.transect_vertices = []       # list of QgsPointXY in WGS84
        self.transect_rubberband = None
        self.transect_start_time = None

        self.gps_watchdog = QTimer()
        self.gps_watchdog.setInterval(3000)  # check every 3 seconds
        self.gps_watchdog.timeout.connect(self._check_gps_connection)

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')

        # One toolbar for the whole tool
        self.toolbar = self.iface.addToolBar("Estuarine Habitat Validation")
        self.toolbar.setObjectName("EstuarineHabitatToolbar")

        # Panel toggle
        action = QAction(QIcon(icon_path),
                         u'Estuarine Habitat Validation',
                         self.iface.mainWindow())
        action.triggered.connect(self.toggle_panel)
        self.toolbar.addAction(action)
        self.iface.addPluginToMenu(self.menu, action)
        self.actions.append(action)

        # Build dock
        self.dock_widget = MacrophyteDockWidget()
        self.dock_widget.setMinimumWidth(280)
        self.dock = QgsDockWidget("Estuarine Habitat Validation",
                                  self.iface.mainWindow())
        self.dock.setObjectName("MacrophyteDataDock")
        self.dock.setWidget(self.dock_widget)
        self.dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea |
                                  Qt.DockWidgetArea.RightDockWidgetArea)
        self.iface.mainWindow().addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        self.dock.visibilityChanged.connect(self._on_dock_visibility_changed)

        # Wire panel signals
        self.dock_widget.record_requested.connect(self.save_record)
        self.dock_widget.activate_tool_requested.connect(self._arm_map_click)
        self.dock_widget.disarm_tool_requested.connect(self._disarm_map_click)
        self.dock_widget.cancel_point_requested.connect(self._on_cancel_point)
        self.dock_widget.mark_location_requested.connect(self._mark_gps_location)
        self.dock_widget.quick_capture_requested.connect(self._quick_capture)
        self.dock_widget.undo_last_requested.connect(self._undo_last_point)

        # Map tool (one-shot map-click override)
        self.point_tool = QgsMapToolEmitPoint(self.iface.mapCanvas())
        self.point_tool.canvasClicked.connect(self._canvas_clicked)

        # Transect actions on the same toolbar
        self.toolbar.addSeparator()

        self.start_transect_action = QAction("▶ Start Transect",
                                             self.iface.mainWindow())
        self.start_transect_action.triggered.connect(self.start_transect)
        self.toolbar.addAction(self.start_transect_action)

        self.stop_transect_action = QAction("⏹ Stop Transect",
                                            self.iface.mainWindow())
        self.stop_transect_action.triggered.connect(self.stop_transect)
        self.stop_transect_action.setEnabled(False)
        self.toolbar.addAction(self.stop_transect_action)

        # Start watchdog — keeps attached to the live GPS connection
        self.gps_watchdog.start()

    def _on_dock_visibility_changed(self, visible: bool):
        if visible:
            self._connect_gps()
        else:
            if self.transect_recording:
                self.stop_transect()
            self._disarm_map_click()
            self._disconnect_gps()

    def unload(self):
        self.gps_watchdog.stop()
        if self.transect_recording:
            self._clear_transect_rubberband()
            self.transect_recording = False
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
        self._disconnect_gps()
        self._disarm_map_click()
        self._clear_pending_marker()
        if self.toolbar:
            del self.toolbar
            self.toolbar = None
        if self.dock:
            self.iface.mainWindow().removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

    # ------------------------------------------------------------------
    # Panel visibility
    # ------------------------------------------------------------------

    def toggle_panel(self):
        if self.dock.isVisible():
            self.dock.hide()
        else:
            self.dock.show()

    # ------------------------------------------------------------------
    # GPS — always on while the panel is open
    # ------------------------------------------------------------------

    def _connect_gps(self):
        registry = QgsApplication.gpsConnectionRegistry()
        connections = registry.connectionList()
        if not connections:
            self.dock_widget.set_gps_available(False)
            return
        self._disconnect_gps()
        self.gps_connection = connections[0]
        self.gps_connection.positionChanged.connect(self._on_gps_position)
        self.dock_widget.set_gps_available(True)

    def _disconnect_gps(self):
        if self.gps_connection is None:
            return
        try:
            self.gps_connection.positionChanged.disconnect(
                self._on_gps_position)
        except (RuntimeError, TypeError):
            pass
        finally:
            self.gps_connection = None

    def _check_gps_connection(self):
        if self.dock is None or not self.dock.isVisible():
            return

        registry = QgsApplication.gpsConnectionRegistry()
        connections = registry.connectionList()

        if not connections:
            if self.gps_connection is not None:
                self._disconnect_gps()
            self.dock_widget.set_gps_available(False)
            return

        current = connections[0]
        if current != self.gps_connection:
            self._disconnect_gps()
            self.gps_connection = current
            self.gps_connection.positionChanged.connect(self._on_gps_position)
            self.dock_widget.set_gps_available(True)

    def _on_gps_position(self, point):
        """Fired on every GPS fix. Updates the live display, and — if a
        transect is recording — appends a vertex and extends the track."""
        lat = point.y()
        lon = point.x()
        if lat is None or lon is None:
            return
        self.dock_widget.set_coordinates(lon, lat, source="GPS")

        if self.transect_recording:
            self._append_transect_vertex(lon, lat)

    # ------------------------------------------------------------------
    # Transect recording
    # ------------------------------------------------------------------

    def start_transect(self):
        if self.transect_recording:
            return

        if self.gps_connection is None or self.dock_widget.longitude is None:
            QMessageBox.warning(
                self.iface.mainWindow(), "No GPS",
                "A live GPS position is needed to record a transect.\n\n"
                "Make sure the habitat panel is open and the GPS is "
                "connected and showing a position, then try again.")
            return

        self.transect_vertices = []
        self.transect_start_time = QDateTime.currentDateTime()
        self.transect_recording = True

        self.transect_rubberband = QgsRubberBand(
            self.iface.mapCanvas(), Qgis.GeometryType.Line)
        self.transect_rubberband.setColor(QColor(230, 81, 0))  # orange
        self.transect_rubberband.setWidth(3)

        self._append_transect_vertex(self.dock_widget.longitude,
                                     self.dock_widget.latitude)

        self.start_transect_action.setEnabled(False)
        self.stop_transect_action.setEnabled(True)
        self.iface.messageBar().pushInfo(
            "Transect", "Recording started — move along the transect.")

    def _append_transect_vertex(self, lon, lat):
        self.transect_vertices.append(QgsPointXY(lon, lat))
        if self.transect_rubberband is not None:
            self.transect_rubberband.addPoint(self._to_canvas_crs(lon, lat))

    def stop_transect(self):
        if not self.transect_recording:
            return

        self.transect_recording = False
        self.start_transect_action.setEnabled(True)
        self.stop_transect_action.setEnabled(False)

        vertices = list(self.transect_vertices)
        self._clear_transect_rubberband()
        self.transect_vertices = []

        if len(vertices) < 2:
            self.iface.messageBar().pushWarning(
                "Transect", "Too few points recorded — transect discarded.")
            return

        end_time = QDateTime.currentDateTime()
        ok = self._save_transect(vertices, self.transect_start_time, end_time)
        if ok:
            self.iface.messageBar().pushSuccess(
                "Transect", f"Transect saved ({len(vertices)} points).")

    def _clear_transect_rubberband(self):
        if self.transect_rubberband is not None:
            self.iface.mapCanvas().scene().removeItem(self.transect_rubberband)
            self.transect_rubberband = None

    def _save_transect(self, vertices, start_time, end_time):
        layer = self._get_or_create_transect_layer()
        if not layer:
            return False

        existing_ids = []
        for f in layer.getFeatures():
            val = f['id']
            if val is not None:
                existing_ids.append(int(val))
        next_id = max(existing_ids, default=0) + 1

        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPolylineXY(vertices))
        feat.setAttribute('id', int(next_id))
        feat.setAttribute('start_time',
                          start_time.toString("yyyy-MM-dd HH:mm:ss"))
        feat.setAttribute('end_time',
                          end_time.toString("yyyy-MM-dd HH:mm:ss"))
        feat.setAttribute('vertex_count', len(vertices))

        success, added = layer.dataProvider().addFeatures([feat])
        if not success:
            QMessageBox.critical(
                self.iface.mainWindow(), "Transect save failed",
                f"Failed to add transect to layer.\n"
                f"Provider errors: {layer.dataProvider().errors()}")
            return False

        layer.updateExtents()
        layer.triggerRepaint()
        self.iface.mapCanvas().refresh()
        return True

    # ------------------------------------------------------------------
    # Undo — remove the most recent point (single level, point-only)
    # ------------------------------------------------------------------

    def _undo_last_point(self):
        if self.last_point_id is None:
            self.iface.messageBar().pushInfo("Undo", "No recent point to undo.")
            return

        layer = self._get_or_create_layer()
        if not layer:
            return

        fid = self._last_point_fid(layer)
        if fid is None:
            self.iface.messageBar().pushInfo("Undo", "No recent point to undo.")
            self.last_point_id = None
            return

        ok = layer.dataProvider().deleteFeatures([fid])
        if ok:
            layer.updateExtents()
            layer.triggerRepaint()
            self.iface.mapCanvas().refresh()
            self.iface.messageBar().pushSuccess(
                "Undo", f"Removed point #{self.last_point_id}.")
            self.last_point_id = None
        else:
            self.iface.messageBar().pushWarning(
                "Undo", "Could not remove the last point.")

    def _last_point_fid(self, layer):
        for f in layer.getFeatures():
            if f['id'] == self.last_point_id:
                return f.id()
        return None

    # ------------------------------------------------------------------
    # Map-click override (one-shot — does NOT disconnect GPS)
    # ------------------------------------------------------------------

    def _arm_map_click(self):
        self.iface.mapCanvas().setMapTool(self.point_tool)

    def _disarm_map_click(self):
        if self.iface.mapCanvas().mapTool() == self.point_tool:
            self.iface.mapCanvas().unsetMapTool(self.point_tool)

    def _canvas_clicked(self, point, button):
        self._show_pending_marker(point)

        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        if canvas_crs != wgs84:
            xform = QgsCoordinateTransform(canvas_crs, wgs84,
                                           QgsProject.instance())
            wgs84_point = xform.transform(point)
        else:
            wgs84_point = point

        self.dock_widget.set_marked_location(wgs84_point.x(), wgs84_point.y(),
                                             source="Manual")
        self._disarm_map_click()

    def _on_cancel_point(self):
        self._clear_pending_marker()
        self._disarm_map_click()

    # ------------------------------------------------------------------
    # Mark Location (GPS)
    # ------------------------------------------------------------------

    def _mark_gps_location(self):
        lon = self.dock_widget.longitude
        lat = self.dock_widget.latitude
        if lon is None or lat is None:
            QMessageBox.warning(
                self.iface.mainWindow(), "No GPS fix",
                "No GPS position available yet. Wait for a fix then try again.")
            return

        self._show_pending_marker(self._to_canvas_crs(lon, lat))
        self.dock_widget.set_marked_location(lon, lat, source="GPS")

    # ------------------------------------------------------------------
    # Quick Capture
    # ------------------------------------------------------------------

    def _quick_capture(self, habitat: str):
        lon = self.dock_widget.longitude
        lat = self.dock_widget.latitude
        if lon is None or lat is None:
            QMessageBox.warning(
                self.iface.mainWindow(), "No GPS fix",
                "No GPS position available yet. Wait for a fix then try again.")
            return

        data = {
            'habitat':   habitat,
            'comments':  '',
            'longitude': lon,
            'latitude':  lat,
            'timestamp': QDateTime.currentDateTime().toString(
                             "yyyy-MM-dd HH:mm:ss"),
            'source':    'GPS',
        }

        if self.save_record(data):
            self.dock_widget.quick_capture_saved(habitat, lat, lon)

    # ------------------------------------------------------------------
    # Pending point marker
    # ------------------------------------------------------------------

    def _to_canvas_crs(self, lon, lat):
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        point = QgsPointXY(lon, lat)
        if canvas_crs != wgs84:
            xform = QgsCoordinateTransform(wgs84, canvas_crs,
                                           QgsProject.instance())
            point = xform.transform(point)
        return point

    def _show_pending_marker(self, canvas_point):
        if self.marker is None:
            self.marker = QgsVertexMarker(self.iface.mapCanvas())
            self.marker.setIconType(QgsVertexMarker.IconType.ICON_CROSS)
            self.marker.setColor(Qt.GlobalColor.red)
            self.marker.setIconSize(14)
            self.marker.setPenWidth(3)
        self.marker.setCenter(canvas_point)
        self.marker.show()

    def _clear_pending_marker(self):
        if self.marker:
            self.iface.mapCanvas().scene().removeItem(self.marker)
            self.marker = None

    # ------------------------------------------------------------------
    # GeoPackage — both layers created together, order-independent
    # ------------------------------------------------------------------

    def _gpkg_path(self):
        """Return the GeoPackage path next to the project file, or None
        (with a warning) if the project hasn't been saved."""
        project_path = QgsProject.instance().fileName()
        if not project_path:
            QMessageBox.warning(
                self.iface.mainWindow(), "Project not saved",
                "Please save your QGIS project first, so the validation "
                "GeoPackage can be stored alongside it.")
            return None
        return os.path.join(os.path.dirname(project_path), GPKG_FILENAME)

    def _gpkg_has_layer(self, gpkg_path, layer_name):
        """True if the GeoPackage already contains the named layer."""
        probe = QgsVectorLayer(f"{gpkg_path}|layername={layer_name}",
                               "probe", "ogr")
        return probe.isValid()

    def _ensure_gpkg(self):
        """Ensure the GeoPackage exists with BOTH layers. Returns the gpkg
        path, or None if the project isn't saved. Safe to call repeatedly —
        creates only the layers that are missing, so an existing file that
        lacks a layer is self-healed."""
        gpkg_path = self._gpkg_path()
        if not gpkg_path:
            return None

        file_exists = os.path.exists(gpkg_path)

        if not file_exists or not self._gpkg_has_layer(gpkg_path, LAYER_NAME):
            if not self._write_points_layer(gpkg_path, file_exists):
                return None
            file_exists = True  # the file certainly exists now

        if not self._gpkg_has_layer(gpkg_path, TRANSECT_LAYER_NAME):
            if not self._write_transect_layer(gpkg_path, file_exists):
                return None

        return gpkg_path

    def _write_points_layer(self, gpkg_path, file_exists):
        fields = QgsFields()
        fields.append(QgsField("id",        FIELD_INT))
        fields.append(QgsField("habitat",   FIELD_STRING))
        fields.append(QgsField("comments",  FIELD_STRING))
        fields.append(QgsField("longitude", FIELD_DOUBLE))
        fields.append(QgsField("latitude",  FIELD_DOUBLE))
        fields.append(QgsField("timestamp", FIELD_STRING))
        fields.append(QgsField("source",    FIELD_STRING))

        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.fileEncoding = "UTF-8"
        opts.layerName = LAYER_NAME
        if file_exists:
            opts.actionOnExistingFile = \
                QgsVectorFileWriter.CreateOrOverwriteLayer

        writer = QgsVectorFileWriter.create(
            gpkg_path, fields, Qgis.WkbType.Point,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().transformContext(), opts)

        if writer.hasError() != QgsVectorFileWriter.NoError:
            QMessageBox.critical(
                self.iface.mainWindow(), "GeoPackage creation failed",
                f"Could not create the points layer:\n{writer.errorMessage()}")
            del writer
            return False
        del writer
        return True

    def _write_transect_layer(self, gpkg_path, file_exists):
        fields = QgsFields()
        fields.append(QgsField("id",           FIELD_INT))
        fields.append(QgsField("start_time",   FIELD_STRING))
        fields.append(QgsField("end_time",     FIELD_STRING))
        fields.append(QgsField("vertex_count", FIELD_INT))

        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.fileEncoding = "UTF-8"
        opts.layerName = TRANSECT_LAYER_NAME
        if file_exists:
            opts.actionOnExistingFile = \
                QgsVectorFileWriter.CreateOrOverwriteLayer

        writer = QgsVectorFileWriter.create(
            gpkg_path, fields, Qgis.WkbType.LineString,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().transformContext(), opts)

        if writer.hasError() != QgsVectorFileWriter.NoError:
            QMessageBox.critical(
                self.iface.mainWindow(), "Transect layer creation failed",
                f"Could not create the transect layer:\n{writer.errorMessage()}")
            del writer
            return False
        del writer
        return True

    def _get_or_create_layer(self):
        layers = QgsProject.instance().mapLayersByName(LAYER_NAME)
        if layers:
            return layers[0]

        if not self._ensure_gpkg():
            return None

        gpkg_path = self._gpkg_path()
        layer = QgsVectorLayer(f"{gpkg_path}|layername={LAYER_NAME}",
                               LAYER_NAME, "ogr")
        if not layer.isValid():
            QMessageBox.critical(
                self.iface.mainWindow(), "Layer load failed",
                f"The '{LAYER_NAME}' layer failed to load.")
            return None

        self._apply_labelling(layer)
        QgsProject.instance().addMapLayer(layer)
        return layer

    def _get_or_create_transect_layer(self):
        layers = QgsProject.instance().mapLayersByName(TRANSECT_LAYER_NAME)
        if layers:
            return layers[0]

        if not self._ensure_gpkg():
            return None

        gpkg_path = self._gpkg_path()
        layer = QgsVectorLayer(f"{gpkg_path}|layername={TRANSECT_LAYER_NAME}",
                               TRANSECT_LAYER_NAME, "ogr")
        if not layer.isValid():
            QMessageBox.critical(
                self.iface.mainWindow(), "Transect layer load failed",
                f"The '{TRANSECT_LAYER_NAME}' layer failed to load.")
            return None

        QgsProject.instance().addMapLayer(layer)
        return layer

    def _apply_labelling(self, layer):
        """Load labelling style from the plugin's QML and embed it in the
        GeoPackage so the styling travels with the data file."""
        qml_path = os.path.join(self.plugin_dir, QML_FILENAME)

        if not os.path.exists(qml_path):
            QgsMessageLog.logMessage(
                f"Style file not found: {qml_path}", "Validation",
                Qgis.Warning)
            return

        message, ok = layer.loadNamedStyle(qml_path)
        if not ok:
            QgsMessageLog.logMessage(
                f"Style load failed: {message}", "Validation", Qgis.Warning)
            return

        layer.saveStyleToDatabase(
            LAYER_NAME, "Default validation labelling", True, "")
        layer.triggerRepaint()

    # ------------------------------------------------------------------
    # Save record — points
    # ------------------------------------------------------------------

    def save_record(self, data: dict):
        layer = self._get_or_create_layer()
        if not layer:
            return False

        try:
            lon = float(data.get('longitude', 0.0))
            lat = float(data.get('latitude', 0.0))
        except (TypeError, ValueError):
            QMessageBox.critical(
                self.iface.mainWindow(), "Invalid coordinates",
                "Could not save record — longitude/latitude were not "
                "valid numbers.")
            return False

        existing_ids = []
        for f in layer.getFeatures():
            val = f['id']
            if val is not None:
                existing_ids.append(int(val))
        next_id = max(existing_ids, default=0) + 1

        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        feat.setAttribute('id', int(next_id))
        feat.setAttribute('habitat', str(data.get('habitat', '')))
        feat.setAttribute('comments', str(data.get('comments', '')))
        feat.setAttribute('longitude', lon)
        feat.setAttribute('latitude', lat)
        feat.setAttribute('timestamp', str(data.get('timestamp', '')))
        feat.setAttribute('source', str(data.get('source', '')))

        success, added = layer.dataProvider().addFeatures([feat])
        if not success:
            QMessageBox.critical(
                self.iface.mainWindow(), "Save failed",
                f"Failed to add feature to layer.\n"
                f"Provider errors: {layer.dataProvider().errors()}")
            return False

        layer.updateExtents()
        layer.triggerRepaint()
        self.iface.mapCanvas().refresh()
        self._clear_pending_marker()
        self.last_point_id = int(next_id)
        return True