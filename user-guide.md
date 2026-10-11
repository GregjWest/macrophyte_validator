# Estuarine Habitat Validator — User Guide

A QGIS panel for recording estuarine habitat observations in the field — seagrass, mangrove, and saltmarsh — with live GPS capture and direct-to-GeoPackage storage.

---

## Contents

1. Before you start
2. Opening the panel
3. Understanding the panel
4. How location works
5. Recording points — detailed capture
6. Recording points — quick capture
7. Switching between quick and detailed
8. Adding comments
9. Managing points
10. Where your data goes
11. Troubleshooting

---

## 1. Before you start

Two things must be in place before the tool will record data:

**Save your QGIS project.** The tool stores observations in a GeoPackage created in the same folder as your project file. If the project has never been saved, the tool will prompt you to save first.

**Connect your GPS.** Open the GPS panel via **View → Panels → GPS Information** and connect your device there. The habitat tool reads its position from this connection — it does not connect to the GPS itself. Confirm the GPS panel is showing a live, updating position before you rely on it in the field.

[SCREENSHOT: QGIS GPS Information panel showing a live fix]

---

## 2. Opening the panel

Click the **Estuarine Habitat Validation** icon in the QGIS toolbar. The panel opens docked to the right-hand side of the window.

[SCREENSHOT: toolbar icon highlighted]

When the panel opens it connects to the GPS automatically. The live position shows at the top of the panel and updates continuously. Closing the panel returns the cursor to the normal pan tool.

[SCREENSHOT: the full panel open on the right of QGIS]

---

## 3. Understanding the panel

The panel is arranged top to bottom:

- **Capture** — the live GPS position, the Mark Location and Map Click buttons, and the Quick Capture toggle
- **Status bar** — shows your current habitat selection, or confirms a saved record
- **Seagrass** — habitat buttons for seagrass classes
- **Mangrove / Saltmarsh** — habitat buttons for mangrove and saltmarsh classes
- **Comments** — free-text field with quick-insert word buttons
- **Bottom row** — Clear All, Cancel Point, and Add Record

[SCREENSHOT: panel with each section labelled]

---

## 4. How location works

GPS is the location source at all times while the panel is open — there is no need to switch it on. The live position updates every second at the top of the panel.

For the occasional point at a location you can see but can't physically reach with the boat, use **🖱 Map Click** as a one-off override. Press it, then click the map once where the observation is — that click sets the point's location. The GPS stays connected the whole time; Map Click doesn't turn it off.

If no GPS is connected, the panel shows a notice in place of the live position. You can still record points using Map Click, and the tool will warn you rather than save a bad point if you try to Mark Location or Quick Capture without a fix.

[SCREENSHOT: capture section showing the live GPS position]

[SCREENSHOT: capture section showing the "No GPS" notice]

---

## 5. Recording points — detailed capture

This is the standard workflow, giving you full control over each point.

**Step 1 — Set the location.**
Press **📍 Mark Location** when you are at the sighting spot. The coordinates lock at that moment and the button changes to **📍 Marked ✔**. Because the location is captured when you press Mark Location — not when you save — the recorded position stays accurate even if the boat drifts while you enter the rest of the details.

For an unreachable location, press **🖱 Map Click** and click the map instead.

[SCREENSHOT: Mark Location button in its "Marked ✔" state]

**Step 2 — Select the habitat.**
Tap one button from the Seagrass or Mangrove / Saltmarsh groups. The selected button turns green and the status bar shows the full habitat name. Only one habitat can be selected per point.

[SCREENSHOT: a habitat button selected (green) with the status bar showing the name]

**Step 3 — Add comments (optional).**
Type in the Comments box, or use the quick-insert word buttons. See Section 8.

**Step 4 — Save.**
Press **▶ Add Record**. The point is written to the GeoPackage and appears on the map with its label. The form clears, ready for the next observation.

[SCREENSHOT: a saved point on the map with its label visible]

---

## 6. Recording points — quick capture

Quick Capture is for moving along a transect and recording what's present as fast as possible. It trades the safeguards of detailed capture for speed.

**To turn it on:** press **⚡ Quick**. The button turns orange and the status bar shows an orange banner confirming Quick Capture is active.

[SCREENSHOT: panel with Quick Capture on — orange button and banner]

**How it works:** tap any habitat button and a point is saved immediately at your current GPS position, with no comment. There is no Mark Location step and no Add Record step — one tap is the whole action. The point appears on the map with its label straight away.

**Things to know:**

- Quick Capture uses the live GPS position. If there's no fix, the tool warns you instead of saving a bad point.
- Points captured this way have no comments — there is no opportunity to add them.
- A brief delay prevents an accidental double-tap from recording two points.
- Because a single tap records a point, take care not to click a habitat button unintentionally while this mode is on.

---

## 7. Switching between quick and detailed

You can move between rapid and considered recording without turning anything off.

While Quick Capture is on, if you press **🖱 Map Click** to place a single considered point at an unreachable spot, Quick Capture **pauses** — the button greys out and shows "paused". Complete that point as you would in detailed capture (click the map, select a habitat, add comments, Add Record), and Quick Capture resumes automatically. Pressing **✕ Cancel Point** also resumes it.

The panel layout stays the same throughout, so nothing moves under your finger as you switch.

[SCREENSHOT: Quick Capture button in its greyed "paused" state]

---

## 8. Adding comments

The Comments box accepts free text. Below it, quick-insert buttons add common terms with a single tap — species names, density terms (Dense, Medium, Sparse), and substrate words. Each tap appends the word to whatever is already in the box.

The **Clear** button in the comment area clears the text in the comments box.

Comments are combined with the habitat name in the point's map label — for example, a Posidonia point with the comment "Dense patch" is labelled *Posidonia Dense patch*.

[SCREENSHOT: comments box with text and the quick-insert buttons below]

---

## 9. Managing points

| Button | Effect |
| --- | --- |
| **Clear** (in the Seagrass group) | Clears the habitat selection only. Location and comments are untouched. |
| **Clear All** | Clears the habitat selection and the comments, but keeps the marked location. Use this to re-enter details for the same spot. |
| **✕ Cancel Point** | Abandons the current point entirely — clears the habitat, comments, and the marked location. GPS keeps running, and Quick Capture resumes if it was paused. |

---

## 10. Where your data goes

All observations are saved to a GeoPackage named **Validation_Data.gpkg**, created in the same folder as your QGIS project.

Each record stores:

| Field | Content |
| --- | --- |
| habitat | The full habitat description |
| comments | Your free text and quick-insert terms |
| longitude / latitude | The recorded position (WGS84) |
| timestamp | The date and time of the record |
| source | Whether the point came from GPS or a map click |

The data is written immediately on each save, so nothing is lost if QGIS closes unexpectedly. When you reopen the project on a later field day, the existing points load automatically and new observations are added to the same file.

Point labels combine the habitat and comment, styled for readability on aerial imagery. The styling is stored inside the GeoPackage, so it travels with the data if the file is opened elsewhere or shared with a colleague.

---

## 11. Troubleshooting

**"Please save your QGIS project first."**
The project has not been saved to disk. Save it, then try again.

**The panel shows "No GPS".**
No active GPS connection was found. Open **View → Panels → GPS Information**, connect your device there, and confirm it shows a live position. The panel picks it up automatically within a few seconds. You can still record points using Map Click in the meantime.

**The live position isn't updating.**
If you disabled and re-enabled the GPS in QGIS, the tool reconnects automatically within a few seconds. If it still isn't updating, check the GPS Information panel is showing a live fix — the tool can only display what QGIS itself is receiving.

**"No GPS fix" when pressing Mark Location or a Quick Capture button.**
No position is available yet. Wait for the GPS to acquire a fix (visible in the panel's live position line) and try again.

**A habitat button records a point instantly instead of highlighting.**
Quick Capture is on. Turn it off with the **⚡ Quick** button to return to detailed capture.

**The Quick Capture button is greyed and says "paused".**
You've started a manual Map Click placement while Quick Capture was on. Finish that point (Add Record) or press Cancel Point, and Quick Capture resumes automatically.

**Points aren't appearing on the map.**
Confirm the project is saved and that the Validation_Data layer is present in the Layers panel. The layer is created the first time you save a record, not when the panel opens.