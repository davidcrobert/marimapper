"""
3D Visualization widget for MariMapper GUI.

This widget displays the 3D LED reconstruction in an embedded Qt widget
using matplotlib's 3D plotting capabilities.
"""

import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import pyqtSlot, Qt

try:
    import matplotlib
    matplotlib.use('QtAgg')
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    from mpl_toolkits.mplot3d import Axes3D
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    FigureCanvas = None


class Visualizer3DWidget(QWidget):
    """Widget for displaying 3D LED reconstruction."""

    def __init__(self):
        """Initialize the 3D visualizer widget."""
        super().__init__()
        self.leds_3d = []
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        if not MATPLOTLIB_AVAILABLE:
            # Fallback message if matplotlib is not available
            self.label = QLabel("Matplotlib not available. Install matplotlib for 3D visualization.")
            self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.label)
            self.setLayout(layout)
            return

        # Create matplotlib figure and canvas
        self.figure = Figure(figsize=(8, 8), facecolor='#323232')
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111, projection='3d', facecolor='#323232')

        # Configure initial view
        self._setup_plot()

        layout.addWidget(self.canvas)
        self.setLayout(layout)

    def _setup_plot(self):
        """Setup the 3D plot with initial configuration."""
        if not MATPLOTLIB_AVAILABLE:
            return

        # Set background and styling
        self.ax.set_facecolor('#323232')
        self.figure.patch.set_facecolor('#323232')

        # Set labels with light color
        self.ax.set_xlabel('X', color='white')
        self.ax.set_ylabel('Y', color='white')
        self.ax.set_zlabel('Z', color='white')

        # Set tick colors
        self.ax.tick_params(colors='white')

        # Set pane colors
        self.ax.xaxis.pane.fill = False
        self.ax.yaxis.pane.fill = False
        self.ax.zaxis.pane.fill = False
        self.ax.xaxis.pane.set_edgecolor('#555555')
        self.ax.yaxis.pane.set_edgecolor('#555555')
        self.ax.zaxis.pane.set_edgecolor('#555555')

        # Set grid
        self.ax.grid(True, color='#555555', linestyle='--', linewidth=0.5)

        # Set initial view angle
        self.ax.view_init(elev=20, azim=45)

    @pyqtSlot(list)
    def update_3d_data(self, leds_3d):
        """
        Update the 3D visualization with new LED data.

        Args:
            leds_3d: List of LED3D objects containing 3D positions
        """
        if not MATPLOTLIB_AVAILABLE or leds_3d is None or len(leds_3d) == 0:
            return

        self.leds_3d = leds_3d

        # Clear previous plot
        self.ax.clear()
        self._setup_plot()

        try:
            # Extract positions and colors from LED3D objects
            positions = np.array([led.point.position for led in leds_3d])

            # Get colors if available, otherwise use default
            try:
                colors = np.array([led.get_color() for led in leds_3d])
                # Normalize colors from 0-255 to 0-1 range for matplotlib
                colors = colors / 255.0
            except:
                colors = np.array([[0.5, 0.5, 1.0] for _ in leds_3d])

            # Plot points
            self.ax.scatter(
                positions[:, 0],
                positions[:, 1],
                positions[:, 2],
                c=colors,
                s=50,
                alpha=0.8,
                edgecolors='white',
                linewidth=0.5
            )

            # Plot lines connecting sequential LEDs
            for i in range(len(leds_3d) - 1):
                led_current = leds_3d[i]
                led_next = leds_3d[i + 1]

                # Only connect if IDs are sequential
                if led_next.led_id - led_current.led_id == 1:
                    p1 = led_current.point.position
                    p2 = led_next.point.position

                    # Check distance to avoid connecting distant LEDs
                    dist = np.linalg.norm(p2 - p1)
                    avg_dist = np.mean([
                        np.linalg.norm(leds_3d[j+1].point.position - leds_3d[j].point.position)
                        for j in range(min(10, len(leds_3d)-1))
                    ])

                    if dist < avg_dist * 1.5:  # Within 150% of average distance
                        self.ax.plot(
                            [p1[0], p2[0]],
                            [p1[1], p2[1]],
                            [p1[2], p2[2]],
                            color='gray',
                            alpha=0.3,
                            linewidth=1
                        )

            # Add normals if available (as small arrows)
            try:
                normals = np.array([led.point.normal for led in leds_3d])
                # Draw normals as small arrows (scaled down)
                normal_scale = 0.2
                for i, (pos, normal) in enumerate(zip(positions, normals)):
                    if i % 5 == 0:  # Only show every 5th normal to avoid clutter
                        self.ax.quiver(
                            pos[0], pos[1], pos[2],
                            normal[0], normal[1], normal[2],
                            length=normal_scale,
                            color='cyan',
                            alpha=0.5,
                            arrow_length_ratio=0.3
                        )
            except:
                pass  # Normals not available or error

            # Set equal aspect ratio
            max_range = np.array([
                positions[:, 0].max() - positions[:, 0].min(),
                positions[:, 1].max() - positions[:, 1].min(),
                positions[:, 2].max() - positions[:, 2].min()
            ]).max() / 2.0

            mid_x = (positions[:, 0].max() + positions[:, 0].min()) * 0.5
            mid_y = (positions[:, 1].max() + positions[:, 1].min()) * 0.5
            mid_z = (positions[:, 2].max() + positions[:, 2].min()) * 0.5

            self.ax.set_xlim(mid_x - max_range, mid_x + max_range)
            self.ax.set_ylim(mid_y - max_range, mid_y + max_range)
            self.ax.set_zlim(mid_z - max_range, mid_z + max_range)

            # Redraw canvas
            self.canvas.draw()

        except Exception as e:
            print(f"Error updating 3D visualization: {e}")
            import traceback
            traceback.print_exc()
