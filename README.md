# QGIS Estuarine Habitat Validator

A QGIS dock panel plugin for field validation of estuarine macrophyte habitats — seagrass, mangrove, and saltmarsh — with live GPS support and persistent GeoPackage storage.

Developed for coastal habitat mapping in NSW estuaries.

---

## Features

- Dockable panel that stays visible while mapping
- Single habitat selection across Seagrass and Mangrove/Saltmarsh button groups
- GPS as the always-on location source, with a one-shot map-click override for locations that can't be physically reached
- Detailed capture (Mark Location → select habitat → add comments → save) for considered observations
- Quick Capture mode for rapid transect recording — a habitat tap saves a point instantly at the GPS position
- Quick Capture and detailed capture coexist: arming a map-click placement pauses Quick for that one point, then resumes automatically
- Explicit Mark Location step captures the position at the moment of sighting, preventing spatial drift while attributes are entered
- Automatic GPS reconnection if the connection is disabled and re-enabled in QGIS
- Persistent no-GPS notice when no device is connected, with per-action warnings if GPS is required
- Free-text comments with quick-insert word buttons (species, density, substrate)
- Habitat values recorded using full descriptive terms via a lookup dictionary
- Points saved immediately to a GeoPackage alongside the QGIS project file
- Layer persists across sessions — reloads automatically on subsequent field days
- Point labelling styled from a bundled QML and embedded in the GeoPackage, so styling travels with the data
- Pending point marker on the map canvas before committing a record
- Cursor restores to the default pan tool when the panel is closed

---

## Requirements

- QGIS 3.30 or later, including QGIS 4.x (single codebase supports both Qt5 and Qt6 builds)
- Python 3.x (bundled with QGIS)
- A GPS device connected via the QGIS GPS Panel for live GPS capture

Tested on QGIS 3.44 LTR (Qt5) and QGIS 4.x (Qt6) on Windows.

---

## Installation

### Method 1 — Install from ZIP

1. Download or clone this repository
2. Zip the folder contents so the zip contains these files at the root:
   - `__init__.py`
   - `macrophyte_plugin.py`
   - `macrophyte_dock.py`
   - `metadata.txt`
   - `icon.png`
   - `validation_style.qml`
3. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**
4. Browse to the zip file and click **Install Plugin**
5. Enable the plugin in the **Installed** tab

### Method 2 — Manual installation

Copy the plugin folder directly to your QGIS plugins directory. Note that QGIS 4 uses a separate profile folder (`QGIS4`) from QGIS 3 (`QGIS3`):

- **Windows (QGIS 3):** `C:\Users\<username>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
- **Windows (QGIS 4):** `C:\Users\<username>\AppData\Roaming\QGIS\QGIS4\profiles\default\python\plugins\`
- **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- **macOS:** `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

Restart QGIS and enable the plugin under **Plugins → Manage and Install Plugins → Installed**.

---

## Usage

### Setup

1. Save your QGIS project file — the plugin stores data in a GeoPackage (`Validation_Data.gpkg`) created alongside the `.qgz` project file
2. Connect your GPS device via **View → Panels → GPS Information** — the plugin reads its position from this connection
3. Click the **Estuarine Habitat Validation** toolbar icon to open the panel

When the panel opens it connects to the GPS automatically and shows the live position. GPS stays on the whole time the panel is open. If no GPS is connected, the panel shows a notice and remains usable for map-click placement.

### Location sources

| Source | How it works |
| --- | --- |
| **GPS** (default) | The panel shows your current position, updating continuously. Mark Location and Quick Capture both use this. |
| **Map Click** | A one-shot override for a single point somewhere you can't reach. Press **🖱 Map Click**, click the map once, and the location is set from that click. GPS stays connected throughout. |

### Detailed capture

The standard workflow, giving full control over each point:

1. Press **📍 Mark Location** at the sighting spot (or use Map Click for an unreachable location). The coordinates lock at that moment, so boat drift during data entry doesn't affect accuracy.
2. Select a habitat from the Seagrass or Mangrove/Saltmarsh buttons
3. Optionally add comments
4. Press **▶ Add Record** — the point is saved and appears on the map with its label

### Quick Capture

For rapid transect recording. Press **⚡ Quick** to turn it on; a habitat tap then saves a point instantly at the current GPS position, with no comment. Press it again to turn it off.

Quick Capture and detailed capture work together — if you press **🖱 Map Click** while Quick is on, Quick pauses (shown greyed as "paused") for that single manual placement, then resumes automatically once you save or cancel the point.

### Buttons

| Button | Action |
| --- | --- |
| **📍 Mark Location** | Locks the current GPS position for a detailed-capture point |
| **🖱 Map Click** | Arms a one-shot map click to place a single point at an unreachable location |
| **⚡ Quick** | Toggles Quick Capture (GPS position, instant save on habitat tap) |
| **Clear** (seagrass group) | Clears the habitat selection only |
| **Clear All** | Clears habitat and comments, keeps the marked location |
| **✕ Cancel Point** | Abandons the current point entirely, including the marked location. GPS keeps running. |
| **▶ Add Record** | Saves the point to the GeoPackage |

---

## Data

Points are saved to `Validation_Data.gpkg` in the same folder as the QGIS project file.

| Field | Type | Content |
| --- | --- | --- |
| id | Integer | Auto-incrementing record ID |
| habitat | String | Full habitat description (e.g. `Sparse Posidonia`) |
| comments | String | Free text and quick-insert terms |
| longitude | Double | WGS84 longitude |
| latitude | Double | WGS84 latitude |
| timestamp | String | Date and time of record (yyyy-MM-dd HH:mm:ss) |
| source | String | `GPS` or `Manual` |

The layer reloads automatically when the project is reopened on subsequent field days.

---

## Label styling

Point labels combine the `habitat` and `comments` fields (e.g. `Posidonia Dense patch`, or just `Posidonia` when there is no comment).

The label appearance is defined in `validation_style.qml`, bundled with the plugin. When a new `Validation_Data.gpkg` is created, this style is loaded and embedded into the GeoPackage itself (in its `layer_styles` table), so the styling travels with the data file.

To change the label appearance, edit the layer's labelling in **Layer Properties → Labels**, then **Style → Save Style → As QGIS QML File**, saving over `validation_style.qml` in the plugin folder. New GeoPackages will pick up the revised style.

---

## Habitat lookup

Button labels are kept short for field use. The full descriptive value recorded in the `habitat` field is defined in `HABITAT_VALUE_MAP` in `macrophyte_dock.py`. Edit this dictionary to customise habitat terminology without changing the button layout.

---

## Development

Built with PyQGIS. The codebase targets both Qt5 (QGIS 3.30+) and Qt6 (QGIS 4.x) — enums use the fully-qualified scoped form that works on both, and a small compatibility shim handles the `QVariant` → `QMetaType` field-type change.

For development, open the repo folder in VSCode.

> **Note:** restart QGIS rather than using Plugin Reloader when changing anything that touches signal connections, the dock, or GPS handling. Plugin Reloader can leave stale object references that cause hard-to-diagnose behaviour; a full restart avoids this.

Contributions and issues welcome via GitHub.

---

## Licence

MIT License — free to use, modify, and distribute.