"""
Dialog for opening an existing MariMapper project.

Provides a file browser to select a project folder and validates that it
contains a valid project.json file.
"""

from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QFileDialog, QMessageBox


class OpenProjectDialog:
    """Helper class for opening an existing project."""

    @staticmethod
    def get_project_folder(parent=None, start_dir: Optional[Path] = None) -> Optional[Path]:
        """
        Show directory picker and validate project folder.

        Args:
            parent: Parent widget for the dialog
            start_dir: Starting directory for file browser

        Returns:
            Path to valid project folder or None if cancelled/invalid
        """
        if start_dir is None:
            start_dir = Path.home() / "MariMapperProjects"

        # Ensure start directory exists
        if not start_dir.exists():
            start_dir = Path.home()

        # Show directory picker
        folder = QFileDialog.getExistingDirectory(
            parent,
            "Select Project Folder",
            str(start_dir),
            QFileDialog.Option.ShowDirsOnly
        )

        if not folder:
            # User cancelled
            return None

        project_folder = Path(folder)

        # Validate that folder contains project.json
        config_file = project_folder / "project.json"
        if not config_file.exists():
            QMessageBox.critical(
                parent,
                "Invalid Project",
                f"The selected folder does not contain a project.json file.\n\n"
                f"Please select a valid MariMapper project folder."
            )
            return None

        return project_folder
