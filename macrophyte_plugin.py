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

Data is stored in a GeoPackage saved alongside the project file, so records
persist across sessions.
"""

import os
from qgis.PyQt.QtCore import Qt, QTimer, QDateTime
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QToolBar
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
        self.transect_toolbar = None
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

        # One toolbar for everything
        self.transect_toolbar = self.iface.addToolBar("Estuarine Habitat Validation")
        self.transect_toolbar.setObjectName("EstuarineHabitatToolbar")

        # Panel toggle
        action = QAction(QIcon(icon_path),
                         u'Estuarine Habitat Validation',
                         self.iface.mainWindow())
        action.triggered.connect(self.toggle_panel)
        self.transect_toolbar.addAction(action)
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
        self.transect_toolbar.addSeparator()

        self.start_transect_action = QAction("▶ Start Transect",
                                             self.iface.mainWindow())
        self.start_transect_action.triggered.connect(self.start_transect)
        self.transect_toolbar.addAction(self.start_transect_action)

        self.stop_transect_action = QAction("⏹ Stop Transect",
                                            self.iface.mainWindow())
        self.stop_transect_action.triggered.connect(self.stop_transect)
        self.stop_transect_action.setEnabled(False)
        self.transect_toolbar.addAction(self.stop_transect_action)

        self.gps_watchdog.start()

    def _on_dock_visibility_changed(self, visible: bool):
        if visible:
            self._connect_gps()
        else:
            # If a transect is running when the panel closes, stop and save it
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
        if self.transect_toolbar:
            del self.transect_toolbar
            self.transect_toolbar = None
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

        # GPS must be live — the panel must be open and connected
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

        # Live rubber band on the canvas (canvas CRS)
        self.transect_rubberband = QgsRubberBand(
            self.iface.mapCanvas(), Qgis.GeometryType.Line)
        self.transect_rubberband.setColor(QColor(230, 81, 0))  # orange
        self.transect_rubberband.setWidth(3)

        # Seed with the current position
        self._append_transect_vertex(self.dock_widget.longitude,
                                     self.dock_widget.latitude)

        self.start_transect_action.setEnabled(False)
        self.stop_transect_action.setEnabled(True)
        self.iface.messageBar().pushInfo(
            "Transect", "Recording started — move along the transect.")

    def _append_transect_vertex(self, lon, lat):
        pt_wgs84 = QgsPointXY(lon, lat)
        self.transect_vertices.append(pt_wgs84)
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

        # Need at least two distinct vertices to form a line
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
            self.iface.messageBar().pushInfo(
                "Undo", "No recent point to undo.")
            return

        layer = self._get_or_create_layer()
        if not layer:
            return

        fid = self._last_point_fid(layer)
        if fid is None:
            self.iface.messageBar().pushInfo(
                "Undo", "No recent point to undo.")
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
        """Find the internal feature id (fid) for the last saved point,
        looked up by its 'id' attribute — the two aren't guaranteed equal."""
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
    # Layer management — points
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

    def _get_or_create_layer(self):
        layers = QgsProject.instance().mapLayersByName(LAYER_NAME)
        if layers:
            return layers[0]

        gpkg_path = self._gpkg_path()
        if not gpkg_path:
            return None

        if os.path.exists(gpkg_path):
            uri = f"{gpkg_path}|layername={LAYER_NAME}"
            layer = QgsVectorLayer(uri, LAYER_NAME, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                return layer
            else:
                QMessageBox.warning(
                    self.iface.mainWindow(), "Layer load failed",
                    f"Found {GPKG_FILENAME} but couldn't load the "
                    f"'{LAYER_NAME}' layer from it. Check the file isn't "
                    "corrupted or locked by another program.")
                return None

        return self._create_new_gpkg_layer(gpkg_path)

    def _create_new_gpkg_layer(self, gpkg_path):
        fields = QgsFields()
        fields.append(QgsField("id",        FIELD_INT))
        fields.append(QgsField("habitat",   FIELD_STRING))
        fields.append(QgsField("comments",  FIELD_STRING))
        fields.append(QgsField("longitude", FIELD_DOUBLE))
        fields.append(QgsField("latitude",  FIELD_DOUBLE))
        fields.append(QgsField("timestamp", FIELD_STRING))
        fields.append(QgsField("source",    FIELD_STRING))

        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = "GPKG"
        save_options.fileEncoding = "UTF-8"
        save_options.layerName = LAYER_NAME

        writer = QgsVectorFileWriter.create(
            gpkg_path,
            fields,
            Qgis.WkbType.Point,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().transformContext(),
            save_options
        )

        if writer.hasError() != QgsVectorFileWriter.NoError:
            QMessageBox.critical(
                self.iface.mainWindow(), "GeoPackage creation failed",
                f"Could not create {GPKG_FILENAME}:\n{writer.errorMessage()}")
            return None

        del writer

        uri = f"{gpkg_path}|layername={LAYER_NAME}"
        layer = QgsVectorLayer(uri, LAYER_NAME, "ogr")
        if not layer.isValid():
            QMessageBox.critical(
                self.iface.mainWindow(), "Layer load failed",
                f"Created {GPKG_FILENAME} but the layer failed to load.")
            return None

        self._apply_labelling(layer)
        QgsProject.instance().addMapLayer(layer)
        return layer

    # ------------------------------------------------------------------
    # Layer management — transects
    # ------------------------------------------------------------------

    def _get_or_create_transect_layer(self):
        layers = QgsProject.instance().mapLayersByName(TRANSECT_LAYER_NAME)
        if layers:
            return layers[0]

        gpkg_path = self._gpkg_path()
        if not gpkg_path:
            return None

        if os.path.exists(gpkg_path):
            uri = f"{gpkg_path}|layername={TRANSECT_LAYER_NAME}"
            layer = QgsVectorLayer(uri, TRANSECT_LAYER_NAME, "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                return layer

        return self._create_transect_layer(gpkg_path)

    def _create_transect_layer(self, gpkg_path):
        fields = QgsFields()
        fields.append(QgsField("id",           FIELD_INT))
        fields.append(QgsField("start_time",   FIELD_STRING))
        fields.append(QgsField("end_time",     FIELD_STRING))
        fields.append(QgsField("vertex_count", FIELD_INT))

        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = "GPKG"
        save_options.fileEncoding = "UTF-8"
        save_options.layerName = TRANSECT_LAYER_NAME
        # If the GeoPackage already exists (points layer created it),
        # append this as an additional layer rather than overwriting.
        if os.path.exists(gpkg_path):
            save_options.actionOnExistingFile = \
                QgsVectorFileWriter.CreateOrOverwriteLayer

        writer = QgsVectorFileWriter.create(
            gpkg_path,
            fields,
            Qgis.WkbType.LineString,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().transformContext(),
            save_options
        )

        if writer.hasError() != QgsVectorFileWriter.NoError:
            QMessageBox.critical(
                self.iface.mainWindow(), "Transect layer creation failed",
                f"Could not create the transect layer:\n{writer.errorMessage()}")
            return None

        del writer

        uri = f"{gpkg_path}|layername={TRANSECT_LAYER_NAME}"
        layer = QgsVectorLayer(uri, TRANSECT_LAYER_NAME, "ogr")
        if not layer.isValid():
            QMessageBox.critical(
                self.iface.mainWindow(), "Transect layer load failed",
                "Created the transect layer but it failed to load.")
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
            LAYER_NAME,
            "Default validation labelling",
            True,
            ""
        )
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
        self.last_point_id = int(next_id)   # remember for Undo
        return True