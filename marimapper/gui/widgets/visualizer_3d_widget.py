"""
3D Visualization widget for MariMapper GUI using pyqtgraph.

This version provides hover highlighting (bright pink) and click-to-toggle LEDs.
"""

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QVector4D, QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

IMPORT_ERROR_MSG = None
try:
    import pyqtgraph as pg
    from pyqtgraph.opengl import (
        GLViewWidget,
        GLScatterPlotItem,
        GLLinePlotItem,
        GLGridItem,
        GLMeshItem,
        MeshData,
    )
    try:
        from pyqtgraph.opengl import GLTextItem
    except Exception:
        try:
            from pyqtgraph.opengl.items.GLTextItem import GLTextItem
        except Exception:
            GLTextItem = None
    PG_AVAILABLE = True
except Exception as e:
    PG_AVAILABLE = False
    IMPORT_ERROR_MSG = str(e)
    GLViewWidget = None
    GLScatterPlotItem = None
    GLLinePlotItem = None
    GLGridItem = None
    GLMeshItem = None
    MeshData = None
    GLTextItem = None


if PG_AVAILABLE:
    class UnclampedGLViewWidget(GLViewWidget):
        """Drop the default elevation clamp so we can orbit past +/-90°."""

        def orbit(self, azim, elev):
            # Allow full rotation without the usual [-90, 90] elevation clamp.
            self.opts["azimuth"] = (self.opts.get("azimuth", 0) + azim) % 360
            self.opts["elevation"] = (self.opts.get("elevation", 0) + elev) % 360
            self.update()


class Visualizer3DWidget(QWidget):
    """Widget for displaying 3D LED reconstruction with interactive highlighting."""

    led_clicked = pyqtSignal(int)
    key_pressed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.leds_3d = []
        self.active_led_ids: set[int] = set()
        self.hover_index: int | None = None
        self.scatter: GLScatterPlotItem | None = None
        self.lines: GLLinePlotItem | None = None
        self.floor_grid: GLGridItem | None = None
        self.floor_labels: list = []
        self.origin_marker: GLMeshItem | None = None
        self.axis_gizmo: GLLinePlotItem | None = None
        self.floor_marks: GLLinePlotItem | None = None
        self.id_to_index: dict[int, int] = {}
        self.base_positions: np.ndarray | None = None
        self.working_positions: np.ndarray | None = None
        self.base_normals: np.ndarray | None = None
        self.working_normals: np.ndarray | None = None
        self.current_transform = {
            "translation": (0.0, 0.0, 0.0),
            "rotation": (0.0, 0.0, 0.0),  # degrees
            "scale": (1.0, 1.0, 1.0),
        }
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        if not PG_AVAILABLE:
            msg = "pyqtgraph 3D backend not available."
            if IMPORT_ERROR_MSG:
                msg += f" ({IMPORT_ERROR_MSG})"
            msg += " Install pyqtgraph with OpenGL extras: pip install pyqtgraph PyOpenGL PyOpenGL_accelerate"
            label = QLabel(msg)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            self.setLayout(layout)
            return

        # Configure global pyqtgraph aesthetics
        pg.setConfigOptions(antialias=True)

        self.view = UnclampedGLViewWidget()
        self.view.setBackgroundColor((50, 50, 50))
        self.view.opts['distance'] = 20
        self.view.orbit(45, 20)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view.setMouseTracking(True)
        self._home_view = {
            "azimuth": self.view.opts.get("azimuth", 45),
            "elevation": self.view.opts.get("elevation", 20),
            "distance": self.view.opts.get("distance", 20),
            "center": self.view.opts.get("center"),
        }

        self.hint_label = QLabel("")
        self.hint_label.setVisible(False)
        self.hint_label.setStyleSheet(
            "QLabel { color: #f2f2f2; background: rgba(0,0,0,150); padding: 6px 8px; "
            "border-radius: 6px; font-size: 11px; }"
        )
        self.hint_label.setMaximumHeight(28)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.hint_label.setWordWrap(False)

        layout.addWidget(self.hint_label)
        layout.addWidget(self.view)
        self.setLayout(layout)

        # Route mouse events for hover/pick handling
        self.view.mouseMoveEvent = self._wrapped_mouse_move(self.view.mouseMoveEvent)
        self.view.mousePressEvent = self._wrapped_mouse_press(self.view.mousePressEvent)
        self.view.keyPressEvent = self._wrapped_key_press(self.view.keyPressEvent)

        self._add_floor()
        self._add_origin_marker()
        self._add_axis_gizmo()

    def _wrapped_mouse_move(self, original_handler):
        def handler(ev):
            self._handle_hover(ev)
            return original_handler(ev)
        return handler

    def _wrapped_mouse_press(self, original_handler):
        def handler(ev):
            self._handle_click(ev)
            return original_handler(ev)
        return handler

    def _wrapped_key_press(self, original_handler):
        def handler(ev):
            try:
                if ev.text().lower() == "h":
                    self._reset_home_view()
                    return
            except Exception:
                pass
            # Bubble key events so parent containers can react (e.g., placement nudges)
            try:
                self.key_pressed.emit(ev)
            except Exception:
                pass
            return original_handler(ev)
        return handler

    def _reset_home_view(self):
        """Return camera to the startup 'home' view."""
        if not PG_AVAILABLE or not hasattr(self, "view"):
            return
        center = self._home_view.get("center", None)
        if center is not None:
            self.view.opts["center"] = center
        self.view.setCameraPosition(
            distance=self._home_view.get("distance", 20),
            azimuth=self._home_view.get("azimuth", 45),
            elevation=self._home_view.get("elevation", 20),
        )
        self.view.update()

    def _base_positions_array(self):
        if self.base_positions is not None:
            return self.base_positions
        if not self.leds_3d:
            return np.zeros((0, 3), dtype=float)
        return np.array([led.point.position for led in self.leds_3d], dtype=float)

    def _working_positions_array(self):
        if self.working_positions is not None:
            return self.working_positions
        return self._base_positions_array()

    def _base_normals_array(self):
        if self.base_normals is not None:
            return self.base_normals
        if not self.leds_3d:
            return np.zeros((0, 3), dtype=float)
        return np.array([led.point.normal for led in self.leds_3d], dtype=float)

    def _working_normals_array(self):
        if self.working_normals is not None:
            return self.working_normals
        return self._base_normals_array()

    def _positions_array(self):
        """Current (transformed) positions for display/picking."""
        return self._to_view_space(self._transformed_positions())

    def _to_view_space(self, points: np.ndarray) -> np.ndarray:
        """Map world coords (x, y-up, z-depth) into GL's z-up view space."""
        if points is None or points.size == 0:
            return np.zeros((0, 3), dtype=float)
        pts = np.asarray(points, dtype=float)
        # Support both single-point and Nx3 arrays
        if pts.ndim == 1:
            pts = pts.reshape(1, 3)
        view_pts = pts[..., [0, 2, 1]]
        view_pts[..., 1] *= -1.0  # flip depth so +Z in world goes away from camera
        return view_pts.reshape(points.shape)

    def _colors_array(self, highlight=None):
        colors = []
        for i, led in enumerate(self.leds_3d):
            if led.led_id in self.active_led_ids:
                base = np.array([1.0, 0.0, 1.0])  # active pink
            else:
                try:
                    base = np.array(led.get_color()) / 255.0
                except Exception:
                    base = np.array([0.5, 0.5, 1.0])
            if highlight is not None and i == highlight:
                base = np.array([1.0, 0.2, 1.0])  # hover highlight
            colors.append(np.r_[base, 1.0])  # RGBA
        return np.array(colors, dtype=float) if colors else np.zeros((0, 4), dtype=float)

    def _apply_transform(self, points: np.ndarray) -> np.ndarray:
        """Apply current transform to point array (Nx3)."""
        if points.size == 0:
            return points

        # Scale
        sx, sy, sz = self.current_transform["scale"]
        scaled = points * np.array([sx, sy, sz])

        # Rotation (degrees to radians)
        rx, ry, rz = [np.deg2rad(v) for v in self.current_transform["rotation"]]
        cx, sx_sin = np.cos(rx), np.sin(rx)
        cy, sy_sin = np.cos(ry), np.sin(ry)
        cz, sz_sin = np.cos(rz), np.sin(rz)

        rx_mat = np.array([[1, 0, 0], [0, cx, -sx_sin], [0, sx_sin, cx]])
        ry_mat = np.array([[cy, 0, sy_sin], [0, 1, 0], [-sy_sin, 0, cy]])
        rz_mat = np.array([[cz, -sz_sin, 0], [sz_sin, cz, 0], [0, 0, 1]])

        # Apply in X->Y->Z order: Rz * Ry * Rx * p
        rot_mat = rz_mat @ ry_mat @ rx_mat
        rotated = scaled @ rot_mat.T

        # Translation
        tx, ty, tz = self.current_transform["translation"]
        translated = rotated + np.array([tx, ty, tz])
        return translated

    def _transformed_positions(self) -> np.ndarray:
        return self._apply_transform(self._working_positions_array())

    def _transformed_normals(self) -> np.ndarray:
        normals = self._working_normals_array()
        if normals.size == 0:
            return normals
        # Rotate normals, do not translate or scale (assume uniform scale)
        rx, ry, rz = [np.deg2rad(v) for v in self.current_transform["rotation"]]
        cx, sx_sin = np.cos(rx), np.sin(rx)
        cy, sy_sin = np.cos(ry), np.sin(ry)
        cz, sz_sin = np.cos(rz), np.sin(rz)
        rx_mat = np.array([[1, 0, 0], [0, cx, -sx_sin], [0, sx_sin, cx]])
        ry_mat = np.array([[cy, 0, sy_sin], [0, 1, 0], [-sy_sin, 0, cy]])
        rz_mat = np.array([[cz, -sz_sin, 0], [sz_sin, cz, 0], [0, 0, 1]])
        rot_mat = rz_mat @ ry_mat @ rx_mat
        return normals @ rot_mat.T

    def _point_size_from_scale(self) -> float:
        """Derive point size from average scale (clamped to a sensible range)."""
        sx, sy, sz = self.current_transform.get("scale", (1.0, 1.0, 1.0))
        avg_scale = max(0.01, (float(sx) + float(sy) + float(sz)) / 3.0)
        return max(0.2, min(5.0, 1.0 * avg_scale))

    def _refresh_view(self):
        if not PG_AVAILABLE or self.leds_3d is None or len(self.leds_3d) == 0:
            return

        pos = self._positions_array()
        colors = self._colors_array(highlight=self.hover_index)
        point_size = self._point_size_from_scale()

        if self.scatter is None:
            self.scatter = GLScatterPlotItem(pos=pos, color=colors, size=point_size, pxMode=False)
            self.view.addItem(self.scatter)
        else:
            self.scatter.setData(pos=pos, color=colors, size=point_size)

        # Draw sequential LED connections (optional aesthetic)
        self._update_lines(pos)

    def _add_floor(self):
        """Add a simple floor grid and cardinal labels around the origin."""
        if not PG_AVAILABLE or GLGridItem is None:
            return

        # Grid in the X/Z plane with Y as up (mapped into GL z-up view space)
        grid = GLGridItem()
        grid.setSize(x=20, y=20)
        grid.setSpacing(x=1, y=1)
        grid.translate(0, 0, 0)
        grid.setDepthValue(10)  # draw behind points
        self.view.addItem(grid)
        self.floor_grid = grid

        if GLTextItem is None:
            return  # text labels unavailable on this pyqtgraph version

        labels = []
        for text, world_pos in [
            ("N", (0, 0, 10)),
            ("S", (0, 0, -10)),
            ("E", (10, 0, 0)),
            ("W", (-10, 0, 0)),
        ]:
            gl_pos = tuple(self._to_view_space(np.array(world_pos, dtype=float)))
            labels.append((text, gl_pos))
        font = QFont()
        font.setPointSize(14)
        for text, pos in labels:
            item = GLTextItem(text=text, color=(0.8, 0.8, 0.8, 0.9), font=font, pos=pos)
            self.view.addItem(item)
            self.floor_labels.append(item)

        # Add subtle floor direction marks (short ticks toward N/E/S/W)
        mark_len = 1.5
        marks_world = []
        directions = [(0, 8, 0, mark_len), (0, -8, 0, -mark_len), (8, 0, mark_len, 0), (-8, 0, -mark_len, 0)]
        for dx, dz, ox, oz in directions:
            start = np.array([dx, 0.0, dz], dtype=float)
            end = np.array([dx + ox, 0.0, dz + oz], dtype=float)
            marks_world.extend([start, end])
        marks_view = self._to_view_space(np.array(marks_world, dtype=float))
        colors = np.array([[0.7, 0.7, 0.7, 0.6]] * len(marks_world), dtype=float)
        self.floor_marks = GLLinePlotItem(pos=marks_view, color=colors, width=2, antialias=True, mode='lines')
        self.view.addItem(self.floor_marks)

    def _add_origin_marker(self):
        """Add a small sphere at the origin to mark (0,0,0)."""
        if not PG_AVAILABLE or GLMeshItem is None or MeshData is None:
            return
        sphere_md = MeshData.sphere(rows=16, cols=32, radius=0.3)
        sphere = GLMeshItem(
            meshdata=sphere_md,
            smooth=True,
            color=(1.0, 0.85, 0.2, 1.0),  # warm yellow to differentiate
            shader="shaded",
        )
        sphere.setGLOptions("opaque")
        self.view.addItem(sphere)
        self.origin_marker = sphere

    def _add_axis_gizmo(self):
        """Add small RGB axis lines at the origin to show orientation."""
        if not PG_AVAILABLE:
            return
        axis_len = 1.5
        axes_world = np.array(
            [
                [0, 0, 0], [axis_len, 0, 0],  # +X red
                [0, 0, 0], [0, axis_len, 0],  # +Y green (up)
                [0, 0, 0], [0, 0, axis_len],  # +Z blue (depth forward)
            ],
            dtype=float,
        )
        axes_view = self._to_view_space(axes_world)
        colors = np.array(
            [
                [1.0, 0.1, 0.1, 1.0],
                [1.0, 0.1, 0.1, 1.0],
                [0.2, 1.0, 0.2, 1.0],
                [0.2, 1.0, 0.2, 1.0],
                [0.2, 0.4, 1.0, 1.0],
                [0.2, 0.4, 1.0, 1.0],
            ],
            dtype=float,
        )
        gizmo = GLLinePlotItem(pos=axes_view, color=colors, width=3, antialias=True, mode='lines')
        gizmo.translate(0, 0, 0)
        self.view.addItem(gizmo)
        self.axis_gizmo = gizmo

    @pyqtSlot(list)
    def update_3d_data(self, leds_3d):
        if not PG_AVAILABLE or leds_3d is None or len(leds_3d) == 0:
            return

        self.leds_3d = leds_3d
        self.hover_index = None
        self.base_positions = np.array([led.point.position for led in leds_3d], dtype=float)
        self.base_normals = np.array([led.point.normal for led in leds_3d], dtype=float)
        self.id_to_index = {led.led_id: i for i, led in enumerate(leds_3d)}
        # Working copies to support placement mode edits without losing originals
        self.working_positions = np.array(self.base_positions, copy=True)
        self.working_normals = np.array(self.base_normals, copy=True)

        self._refresh_view()

    def _update_lines(self, positions: np.ndarray | None = None):
        if not PG_AVAILABLE or not self.leds_3d:
            return

        segments = []
        colors = []
        pos = positions if positions is not None else self._positions_array()
        for i in range(len(self.leds_3d) - 1):
            cur = self.leds_3d[i]
            nxt = self.leds_3d[i + 1]
            if nxt.led_id - cur.led_id == 1:
                # simple distance gating
                dist = np.linalg.norm(pos[i] - pos[i + 1])
                # compute local average distance on first handful
                sample = min(10, len(pos) - 1)
                avg = np.mean([np.linalg.norm(pos[j] - pos[j + 1]) for j in range(sample)])
                if dist < avg * 1.5:
                    segments.append(pos[i])
                    segments.append(pos[i + 1])
                    colors.append([0.6, 0.6, 0.6, 0.3])
                    colors.append([0.6, 0.6, 0.6, 0.3])

        if not segments:
            return

        seg_arr = np.array(segments, dtype=float)
        color_arr = np.array(colors, dtype=float)

        if self.lines is None:
            self.lines = GLLinePlotItem(
                pos=seg_arr,
                color=color_arr,
                width=1,
                antialias=True,
                mode='lines',
            )
            self.view.addItem(self.lines)
        else:
            self.lines.setData(pos=seg_arr, color=color_arr)

    def _handle_hover(self, ev):
        """Find nearest point in screen space and highlight it."""
        if not PG_AVAILABLE or self.scatter is None or not self.leds_3d:
            return

        idx = self._pick_index(ev, verbose=False)
        if idx != self.hover_index:
            self.hover_index = idx
            self.scatter.setData(color=self._colors_array(highlight=self.hover_index))

    def _handle_click(self, ev):
        """Emit led_clicked when a point is clicked."""
        if not PG_AVAILABLE or self.scatter is None or not self.leds_3d:
            return

        idx = self._pick_index(ev, verbose=True)
        if idx is not None and 0 <= idx < len(self.leds_3d):
            led_id = self.leds_3d[idx].led_id
            self.led_clicked.emit(led_id)

    def _pick_index(self, ev, verbose=False):
        """Screen-space nearest-neighbor picking using Qt matrices."""
        if not PG_AVAILABLE or not self.leds_3d:
            return None

        pts = self._positions_array()
        if len(pts) == 0:
            return None

        try:
            viewport = self.view.getViewport()
            proj = self.view.projectionMatrix(viewport, viewport)
            view = self.view.viewMatrix()
            mvp = proj * view
        except Exception as e:
            if verbose:
                print(f"Visualizer3DWidget: pick failed, matrix error {e}")
            return None

        dpr = float(self.view.devicePixelRatioF())
        width = max(1.0, self.view.width() * dpr)
        height = max(1.0, self.view.height() * dpr)

        screen_pts = np.full((len(pts), 2), np.nan, dtype=float)
        valid = np.zeros(len(pts), dtype=bool)

        for i, p in enumerate(pts):
            v = mvp * QVector4D(float(p[0]), float(p[1]), float(p[2]), 1.0)
            w = v.w()
            if w == 0:
                continue
            x_ndc = v.x() / w
            y_ndc = v.y() / w
            screen_pts[i, 0] = (x_ndc + 1.0) * 0.5 * width
            screen_pts[i, 1] = (1.0 - y_ndc) * 0.5 * height
            valid[i] = True

        if not valid.any():
            if verbose:
                print("Visualizer3DWidget: pick failed, no valid projected points")
            return None

        mouse = np.array([ev.position().x() * dpr, ev.position().y() * dpr])
        diffs = screen_pts - mouse
        dists = np.linalg.norm(diffs, axis=1)
        dists[~valid] = np.inf

        if not np.isfinite(dists).any():
            if verbose:
                print("Visualizer3DWidget: pick failed, no finite distances")
            return None

        nearest = int(np.argmin(dists))
        min_dist = dists[nearest]
        if verbose:
            print(f"Visualizer3DWidget: pick min_dist_px={min_dist:.2f} idx={nearest} mouse={mouse}")
        if min_dist < 30.0:  # pixel radius
            return nearest
        if verbose:
            print(f"Visualizer3DWidget: pick ignored, min_dist_px {min_dist:.2f} > 30")
        return None

    @pyqtSlot(object)
    def set_active_leds(self, led_ids):
        """Update which LEDs are currently active (turned on)."""
        if not PG_AVAILABLE:
            return
        try:
            self.active_led_ids = set(led_ids)
        except Exception:
            self.active_led_ids = set()
        self._refresh_view()

    @pyqtSlot(dict)
    def set_transform(
        self,
        transform: dict | None = None,
        translation=None,
        rotation=None,
        scale=None,
        **kwargs,
    ):
        """Update the transform used to display the point cloud.

        Accepts either a transform dictionary or individual keyword args for
        translation/rotation/scale so callers can use both styles.
        """
        if transform is None:
            # Fill from current values, then overwrite any provided pieces.
            transform = dict(self.current_transform)
            if translation is not None:
                transform["translation"] = translation
            if rotation is not None:
                transform["rotation"] = rotation
            if scale is not None:
                transform["scale"] = scale
        self.current_transform = transform
        self._refresh_view()

    def set_working_positions(self, positions: np.ndarray | None):
        """Set working positions (world space) used for display/exports."""
        if positions is None:
            self.working_positions = None
        else:
            self.working_positions = np.array(positions, dtype=float, copy=True)
        self._refresh_view()

    def reset_working_positions(self):
        """Restore working positions from base/original positions."""
        if self.base_positions is None:
            return
        self.working_positions = np.array(self.base_positions, copy=True)
        self._refresh_view()

    def nudge_working_leds(self, led_ids: set[int], delta: tuple[float, float, float]) -> bool:
        """Nudge selected LEDs in working buffer by delta (world space)."""
        if self.working_positions is None or not led_ids:
            return False
        moved = False
        positions = np.array(self.working_positions, copy=True)
        for led_id in led_ids:
            idx = self.id_to_index.get(led_id)
            if idx is None or idx >= len(positions):
                continue
            positions[idx] = positions[idx] + np.array(delta, dtype=float)
            moved = True
        if moved:
            self.set_working_positions(positions)
        return moved

    def export_transformed_leds(self):
        """Return transformed led data arrays (ids, positions, normals, errors) or None."""
        if not self.leds_3d or self.base_positions is None:
            return None
        ids = [led.led_id for led in self.leds_3d]
        positions = self._transformed_positions()
        normals = self._transformed_normals()
        errors = np.array([getattr(led.point, "error", 0.0) for led in self.leds_3d], dtype=float)
        return ids, positions, normals, errors

    def set_hint_text(self, text: str | None):
        """Show or hide the hint banner above the view."""
        if text:
            self.hint_label.setText(text)
            self.hint_label.setVisible(True)
        else:
            self.hint_label.clear()
            self.hint_label.setVisible(False)
