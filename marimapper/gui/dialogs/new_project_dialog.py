"""
Dialog for creating a new MariMapper project.

Provides a form for entering project name, location, description, and
whether to copy current scanner settings.
"""

import re
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QLabel,
)
from PyQt6.QtCore import Qt


class NewProjectDialog(QDialog):
    """Dialog for creating a new MariMapper project."""

    def __init__(self, current_project_name: str = "", parent=None):
        """
        Initialize the New Project Dialog.

        Args:
            current_project_name: Default project name suggestion
            parent: Parent widget
        """
        super().__init__(parent)

        self.project_name = ""
        self.project_location = Path.home() / "MariMapperProjects"
        self.description = ""
        self.copy_settings = True

        self._setup_ui(current_project_name)

    def _setup_ui(self, default_name: str):
        """Set up the dialog UI."""
        self.setWindowTitle("New Project")
        self.setMinimumWidth(500)

        layout = QVBoxLayout()

        # Form layout
        form_layout = QFormLayout()

        # Project name field
        self.name_edit = QLineEdit()
        self.name_edit.setText(default_name)
        self.name_edit.setPlaceholderText("e.g., Living Room LED Strip")
        self.name_edit.textChanged.connect(self._validate_inputs)
        form_layout.addRow("Project Name:", self.name_edit)

        # Project location field with browse button
        location_layout = QHBoxLayout()
        self.location_edit = QLineEdit()
        self.location_edit.setText(str(self.project_location))
        self.location_edit.textChanged.connect(self._validate_inputs)
        location_layout.addWidget(self.location_edit)

        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_location)
        location_layout.addWidget(browse_button)

        form_layout.addRow("Project Location:", location_layout)

        # Description field (optional)
        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText(
            "Optional description of this project..."
        )
        self.description_edit.setMaximumHeight(80)
        form_layout.addRow("Description:", self.description_edit)

        # Copy current settings checkbox
        self.copy_settings_checkbox = QCheckBox(
            "Copy current scanner settings to project"
        )
        self.copy_settings_checkbox.setChecked(True)
        self.copy_settings_checkbox.setToolTip(
            "If checked, the project will use your current backend, camera, "
            "and scanner configuration. Otherwise, default settings will be used."
        )
        form_layout.addRow("", self.copy_settings_checkbox)

        layout.addLayout(form_layout)

        # Validation message label
        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet("color: red;")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        # Security warning for Axis passwords
        warning_label = QLabel(
            "⚠️ Note: Axis camera passwords will be stored in plaintext "
            "in the project configuration file."
        )
        warning_label.setStyleSheet("color: #FFA500; font-size: 10px;")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        self.create_button = QPushButton("Create Project")
        self.create_button.clicked.connect(self._create_project)
        self.create_button.setDefault(True)
        button_layout.addWidget(self.create_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Initial validation
        self._validate_inputs()

    def _browse_location(self):
        """Open directory picker for project location."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Project Location",
            str(self.location_edit.text()),
            QFileDialog.Option.ShowDirsOnly
        )

        if directory:
            self.location_edit.setText(directory)

    def _validate_inputs(self):
        """
        Validate user inputs and enable/disable Create button.

        Returns:
            Tuple of (is_valid, error_message)
        """
        name = self.name_edit.text().strip()
        location = self.location_edit.text().strip()

        # Validate project name
        if not name:
            self._set_validation_error("Project name is required")
            return False

        # Check for invalid characters in project name
        if not self._is_valid_project_name(name):
            self._set_validation_error(
                "Project name contains invalid characters. "
                "Use only letters, numbers, spaces, hyphens, and underscores."
            )
            return False

        # Validate location
        if not location:
            self._set_validation_error("Project location is required")
            return False

        try:
            location_path = Path(location)
            if not location_path.is_absolute():
                self._set_validation_error("Project location must be an absolute path")
                return False
        except (ValueError, OSError):
            self._set_validation_error("Project location is not a valid path")
            return False

        # Check if project folder already exists
        project_path = location_path / self._sanitize_name(name)
        if project_path.exists() and any(project_path.iterdir()):
            self._set_validation_error(
                f"Folder '{project_path}' already exists and is not empty"
            )
            return False

        # All validations passed
        self._clear_validation_error()
        return True

    def _is_valid_project_name(self, name: str) -> bool:
        """
        Check if project name contains only valid characters.

        Args:
            name: Project name to validate

        Returns:
            True if valid
        """
        # Allow letters, numbers, spaces, hyphens, underscores
        pattern = r'^[a-zA-Z0-9\s\-_]+$'
        return bool(re.match(pattern, name))

    def _sanitize_name(self, name: str) -> str:
        """
        Convert project name to valid folder name.

        Args:
            name: Project name

        Returns:
            Sanitized folder name
        """
        # Replace spaces with underscores, remove other special chars
        sanitized = name.strip()
        sanitized = re.sub(r'\s+', '_', sanitized)
        sanitized = re.sub(r'[^\w\-]', '', sanitized)
        return sanitized

    def _set_validation_error(self, message: str):
        """
        Display validation error and disable Create button.

        Args:
            message: Error message to display
        """
        self.validation_label.setText(message)
        self.create_button.setEnabled(False)

    def _clear_validation_error(self):
        """Clear validation error and enable Create button."""
        self.validation_label.setText("")
        self.create_button.setEnabled(True)

    def _create_project(self):
        """Handle Create Project button click."""
        if not self._validate_inputs():
            return

        # Store values
        self.project_name = self.name_edit.text().strip()
        location_path = Path(self.location_edit.text().strip())
        self.project_location = location_path / self._sanitize_name(self.project_name)
        self.description = self.description_edit.toPlainText().strip()
        self.copy_settings = self.copy_settings_checkbox.isChecked()

        # Accept dialog
        self.accept()

    def get_project_config(self) -> Tuple[str, Path, str, bool]:
        """
        Get the configured project parameters.

        Returns:
            Tuple of (project_name, project_location, description, copy_settings)
        """
        return (
            self.project_name,
            self.project_location,
            self.description,
            self.copy_settings
        )
