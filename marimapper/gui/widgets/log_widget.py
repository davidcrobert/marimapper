"""
Log widget for MariMapper GUI.

Displays status messages and logs with color-coding by severity.
"""

from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton
from PyQt6.QtCore import pyqtSlot
from PyQt6.QtGui import QTextCursor


class LogWidget(QWidget):
    """Widget for displaying log messages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Text edit for log display
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumHeight(150)

        # Set monospace font for better log readability
        font = self.text_edit.font()
        font.setFamily("Courier New")
        font.setPointSize(9)
        self.text_edit.setFont(font)

        layout.addWidget(self.text_edit)

        # Clear button
        clear_button = QPushButton("Clear Log")
        clear_button.clicked.connect(self.clear_log)
        layout.addWidget(clear_button)

        self.setLayout(layout)

        # Add initial message
        self.add_message("info", "MariMapper GUI initialized")

    @pyqtSlot(str, str)
    def add_message(self, level: str, message: str):
        """
        Add a log message with color coding.

        Args:
            level: Message level ('info', 'warning', 'error')
            message: The message text
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Color mapping for different levels
        color_map = {
            "info": "black",
            "warning": "orange",
            "error": "red",
            "success": "green",
        }

        color = color_map.get(level.lower(), "black")

        # Format the message with HTML for color
        formatted_message = (
            f'<span style="color: gray;">[{timestamp}]</span> '
            f'<span style="color: {color};"><b>{level.upper()}:</b> {message}</span>'
        )

        # Append to text edit
        self.text_edit.append(formatted_message)

        # Auto-scroll to bottom
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)

    @pyqtSlot()
    def clear_log(self):
        """Clear all log messages."""
        self.text_edit.clear()
        self.add_message("info", "Log cleared")

    def log_info(self, message: str):
        """Convenience method for info messages."""
        self.add_message("info", message)

    def log_warning(self, message: str):
        """Convenience method for warning messages."""
        self.add_message("warning", message)

    def log_error(self, message: str):
        """Convenience method for error messages."""
        self.add_message("error", message)

    def log_success(self, message: str):
        """Convenience method for success messages."""
        self.add_message("success", message)
