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


class Visualizer3DWidget(QWidget):
    """Widget for displaying 3D LED reconstruction with interactive highlighting."""

    led_clicked = pyqtSignal(int)

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
        self.base_positions: np.ndarray | None = None
        self.base_normals: np.ndarray | None = None
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

        self.view = GLViewWidget()
        self.view.setBackgroundColor((50, 50, 50))
        self.view.opts['distance'] = 20
        self.view.orbit(45, 20)
        self.view.setMouseTracking(True)

        layout.addWidget(self.view)
        self.setLayout(layout)

        # Route mouse events for hover/pick handling
        self.view.mouseMoveEvent = self._wrapped_mouse_move(self.view.mouseMoveEvent)
        self.view.mousePressEvent = self._wrapped_mouse_press(self.view.mousePressEvent)

        self._add_floor()
        self._add_origin_marker()

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

    def _base_positions_array(self):
        if self.base_positions is not None:
            return self.base_positions
        if not self.leds_3d:
            return np.zeros((0, 3), dtype=float)
        return np.array([led.point.position for led in self.leds_3d], dtype=float)

    def _base_normals_array(self):
        if self.base_normals is not None:
            return self.base_normals
        if not self.leds_3d:
            return np.zeros((0, 3), dtype=float)
        return np.array([led.point.normal for led in self.leds_3d], dtype=float)

    def _positions_array(self):
        """Current (transformed) positions for display/picking."""
        return self._transformed_positions()

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
        return self._apply_transform(self._base_positions_array())

    def _transformed_normals(self) -> np.ndarray:
        normals = self._base_normals_array()
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

        pos = self._transformed_positions()
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

        # Grid in the X/Z plane with Y as up
        grid = GLGridItem()
        grid.setSize(x=20, y=20)
        grid.setSpacing(x=1, y=1)
        grid.translate(0, 0, 0)
        grid.rotate(90, 1, 0, 0)
        grid.setDepthValue(10)  # draw behind points
        self.view.addItem(grid)
        self.floor_grid = grid

        if GLTextItem is None:
            return  # text labels unavailable on this pyqtgraph version

        labels = [
            ("N", (0, 0, 10)),
            ("S", (0, 0, -10)),
            ("E", (10, 0, 0)),
            ("W", (-10, 0, 0)),
        ]
        font = QFont()
        font.setPointSize(14)
        for text, pos in labels:
            item = GLTextItem(text=text, color=(0.8, 0.8, 0.8, 0.9), font=font, pos=pos)
            self.view.addItem(item)
            self.floor_labels.append(item)

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

    @pyqtSlot(list)
    def update_3d_data(self, leds_3d):
        if not PG_AVAILABLE or leds_3d is None or len(leds_3d) == 0:
            return

        self.leds_3d = leds_3d
        self.hover_index = None
        self.base_positions = np.array([led.point.position for led in leds_3d], dtype=float)
        self.base_normals = np.array([led.point.normal for led in leds_3d], dtype=float)

        self._refresh_view()

    def _update_lines(self, positions: np.ndarray | None = None):
        if not PG_AVAILABLE or not self.leds_3d:
            return

        segments = []
        colors = []
        pos = positions if positions is not None else self._transformed_positions()
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
        if self.scatter is not None:
            self.scatter.setData(color=self._colors_array(highlight=self.hover_index))

    @pyqtSlot(dict)
    def set_transform(self, transform: dict):
        """Update the transform used to display the point cloud."""
        self.current_transform = transform
        self._refresh_view()

    def export_transformed_leds(self):
        """Return transformed led data arrays (ids, positions, normals, errors) or None."""
        if not self.leds_3d or self.base_positions is None:
            return None
        ids = [led.led_id for led in self.leds_3d]
        positions = self._transformed_positions()
        normals = self._transformed_normals()
        errors = np.array([getattr(led.point, "error", 0.0) for led in self.leds_3d], dtype=float)
        return ids, positions, normals, errors
