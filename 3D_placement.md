# 3D Placement Mode Plan

A focused “Placement” mode for manually positioning tricky LEDs quickly and confidently.

## UX Flow
- Entry/Exit: a prominent “Placement Mode” toggle/button (and `Esc` shortcut). Entering shows a short inline hint overlay; exiting restores previous layout.
- Layout: full-screen 3D viewport with minimal chrome; right-side compact panel for active LED info and controls; bottom thin timeline/list for quick LED selection.
- Selection: click/hover to select an LED; arrow/WASD + mouse-drag for nudging; scroll for depth (Z) when a gizmo is active.
- Gizmo: unified 3-axis transform gizmo at the LED (translate by default, toggle to rotate/scale if ever needed). Snap toggles (grid/axis/angle) with one-click buttons.
- Multi-select: optional box/lasso to select multiple LEDs and move them together (fast alignment).
- Status cues: color-coded states (selected = cyan, hovered = yellow, locked/on = magenta, unsolved/problem = red outline). Show LED ID and current coords inline near the point.
- Safety: undo/redo stack with keyboard shortcuts; “revert LED to original” quick action.
- Save/export: “Commit placement” button to persist edits to the current project and the transformed CSV.

## Controls (fast, minimal-mode)
- Mouse:
  - Left-drag empty space: orbit camera.
  - Right-drag: pan camera.
  - Shift+Left-drag on gizmo handle: constrained move along that axis.
  - Scroll: dolly; when gizmo active + Alt, adjust along Z (screen normal) for fine depth.
- Keyboard:
  - Arrow/WASD: nudge selected LED(s) in screen plane (configurable step; Shift for 10×).
  - Q/E: nudge along Z (depth).
  - G: toggle gizmo mode (translate/rotate/scale) but default stays translate.
  - S: toggle snapping; 1/2/3 to switch snap sizes.
  - Ctrl+Z / Ctrl+Y: undo/redo.
  - Tab: jump to next/prev problematic LED (see “Problem list” below).

## Data & State Model
- Keep a working copy of LED positions (`working_positions`) separate from original (`base_positions`); apply transforms non-destructively until committed.
- Maintain a per-LED metadata map: status (placed/unplaced/manual), original position, current position, last edit timestamp.
- Problem list: a derived list (e.g., missing, low confidence, outlier distance) to drive “jump to next problem” navigation.
- Selection model: single and multi-select sets; current gizmo anchor is centroid of selection.
- Undo/redo: store diffs (LED id → delta vector) per action for memory efficiency.

## Rendering & Interaction
- Use existing GLScatter/lines; add a transform gizmo (either custom GL or a simple three-axis line/arrow set with hit regions). Draw selection outline (slightly larger, transparent ring).
- Depth picking: reuse projection-based picker; ensure it ignores gizmo geometry when picking LEDs and vice versa.
- Snapping: grid in XZ plane (floor) with configurable cell size; axis snap for pure X/Y/Z moves; angle snap if rotation is ever enabled.
- Visual aids: ground/floor grid stays; add optional “orthographic lock” button to quickly align camera to top/side/front for precise placement.

## Persistence & Integration
- On commit, write updated positions to the project transform/export (`transformed_led_map_3d.csv`) and update in-memory LED objects for immediate consistency across views/table/backend.
- Provide “discard changes” to restore `working_positions` from originals for the current session.
- If the backend supports live LED control, keep the currently selected LEDs lit for context; otherwise, maintain visual highlighting only.

## Performance & Feedback
- Batch updates: during drag/nudge, update GL positions live but throttle backend LED on/off commands (if used) to avoid chatter.
- Highlight “unsaved changes” state while edits exist; show a small toast on commit or discard.
- Keep point size adaptive to zoom; keep gizmo size screen-space constant for usability.

## Implementation Steps (high level)
1) Add Placement mode toggle + layout switch (fullscreen-ish viewport, slim side panel).
2) Introduce working position buffers and per-LED meta; wire undo/redo stack with diff records.
3) Implement selection model (click/box/lasso) and gizmo rendering + picking.
4) Add movement actions: drag on gizmo, keyboard nudges, snap options; update working positions and emit refresh.
5) Add problem list navigation and status badges; keep selected LEDs lit (optional backend on/off throttle).
6) Commit/discard pipeline into project save/export; reflect changes in status table and any downstream consumers.
7) Polish: orthographic quick-views, tooltips/shortcuts overlay, and performance tuning.

## Delivery Plan (project manager view)
- **Sprint 1: Mode scaffolding & layout**
  - Add Placement Mode toggle/button and keyboard shortcut.
  - Build alternate layout (fullscreen 3D + slim side panel + bottom strip).
  - Wire entry/exit state transitions and restore prior layout.
- **Sprint 2: Data model & buffers**
  - Introduce working positions buffer, per-LED metadata, and diff-based undo/redo stack.
  - Ensure status table/3D stay in sync with working positions.
  - Persist “unsaved changes” flag and discard/commit pathways.
- **Sprint 3: Selection & picking**
  - Robust picking that distinguishes gizmo vs. points.
  - Single select, multi-select (box/lasso), selection visuals, current gizmo anchor = selection centroid.
  - Navigation shortcuts (Tab next problem, etc.).
- **Sprint 4: Gizmo & transforms**
  - Render transform gizmo with axis handles; hit testing for handles.
  - Mouse drag on handles moves selection; keyboard nudges (WASD/QE) with configurable step; snap toggles.
  - Keep gizmo screen-size constant; adaptive point size with zoom.
- **Sprint 5: Snapping & camera aids**
  - Grid/axis/angle snapping; adjustable snap sizes; on/off toggle.
  - Orthographic quick views (top/side/front) and camera reset; maintain floor/grid aids.
- **Sprint 6: Problem-driven workflow**
  - Derive “problem list” (missing/low confidence/outliers); quick navigation controls.
  - Inline badges and hints; keep selected LEDs lit via backend (throttled) if available.
- **Sprint 7: Persistence & export**
  - Commit updates into project transform and `transformed_led_map_3d.csv`.
  - Discard/revert actions; ensure downstream consumers (table/backend) get updates.
  - UX polish: toast confirmations, unsaved-changes indicator, inline help overlay.
- **Validation & perf**
  - Usability passes on input latency and pick accuracy with large point sets.
  - Stress test undo/redo memory footprint (diff-based).
  - Backend command throttling tests if live LED lighting is used during placement.
