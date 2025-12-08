"""
Project management system for MariMapper.

Handles creation, loading, saving, and deletion of projects. Each project contains
scans, 3D reconstructions, masks, and configuration data.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

import cv2
import numpy as np

from marimapper.file_tools import (
    get_all_2d_led_maps,
    load_3d_leds_from_file,
)
from marimapper.led import LED2D, LED3D
from marimapper.gui.utils.scanner_args_serializer import (
    serialize_scanner_args,
    deserialize_scanner_args,
    get_backend_type_from_args,
)

logger = logging.getLogger(__name__)


class Project:
    """Represents a single MariMapper project with all its data and configuration."""

    def __init__(self, base_folder: Path, config: Dict[str, Any]):
        """
        Initialize a Project instance.

        Args:
            base_folder: Root directory of the project
            config: Project configuration dictionary
        """
        self.base_folder = Path(base_folder)
        self.config = config
        self._ensure_folder_structure()

    def _ensure_folder_structure(self):
        """Create project folder structure if it doesn't exist."""
        folders = [
            self.base_folder / "scans",
            self.base_folder / "masks",
            self.base_folder / "reconstruction",
        ]
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)

    def get_scans_dir(self) -> Path:
        """Get the scans directory path."""
        return self.base_folder / "scans"

    def get_masks_dir(self) -> Path:
        """Get the masks directory path."""
        return self.base_folder / "masks"

    def get_reconstruction_dir(self) -> Path:
        """Get the reconstruction directory path."""
        return self.base_folder / "reconstruction"

    def get_config_path(self) -> Path:
        """Get the project configuration file path."""
        return self.base_folder / "project.json"

    def save(self):
        """Save project configuration to disk."""
        self.config["last_modified"] = datetime.now().isoformat()

        config_path = self.get_config_path()
        with open(config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

        logger.info(f"Project saved: {self.config['project_name']}")

    def to_scanner_args(self, output_dir: Optional[Path] = None):
        """
        Convert project configuration to ScannerArgs object.

        Args:
            output_dir: Override output directory (defaults to project scans dir)

        Returns:
            ScannerArgs object and backend_type string
        """
        if output_dir is None:
            output_dir = self.get_scans_dir()

        scanner_config = self.config.get("scanner_config", {})
        scanner_args, backend_type = deserialize_scanner_args(scanner_config, output_dir)

        return scanner_args, backend_type

    @staticmethod
    def from_scanner_args(
        name: str,
        base_folder: Path,
        scanner_args: Any,
        backend_type: str,
        description: str = ""
    ) -> "Project":
        """
        Create a new Project from ScannerArgs.

        Args:
            name: Project name
            base_folder: Project root directory
            scanner_args: Current scanner configuration
            backend_type: Backend type string
            description: Optional project description

        Returns:
            New Project instance
        """
        scanner_config = serialize_scanner_args(scanner_args, backend_type)

        config = {
            "version": "1.0",
            "project_name": name,
            "created_at": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
            "scanner_config": scanner_config,
            "metadata": {
                "description": description,
                "notes": "",
                "tags": []
            },
            "visualization": {
                "transform": {
                    "translation": [0.0, 0.0, 0.0],
                    "rotation": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0]
                }
            },
            "statistics": {
                "total_scans": 0,
                "total_leds_detected": 0,
                "last_scan_date": None,
                "reconstruction_quality": 0.0
            }
        }

        project = Project(base_folder, config)
        project.save()

        logger.info(f"Created new project: {name} at {base_folder}")
        return project


class ProjectManager:
    """Manages MariMapper project lifecycle: create, load, delete, save."""

    def __init__(self):
        """Initialize ProjectManager."""
        self.active_project: Optional[Project] = None
        self.projects_root: Path = Path.home() / "MariMapperProjects"
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def create_project(
        self,
        name: str,
        base_folder: Path,
        scanner_args: Any,
        backend_type: str,
        description: str = ""
    ) -> Project:
        """
        Create a new project.

        Args:
            name: Project name
            base_folder: Project root directory
            scanner_args: Current scanner configuration
            backend_type: Backend type string
            description: Optional project description

        Returns:
            New Project instance

        Raises:
            FileExistsError: If project folder already exists and is not empty
        """
        base_folder = Path(base_folder)

        # Check if folder exists and is not empty
        if base_folder.exists():
            if any(base_folder.iterdir()):
                raise FileExistsError(
                    f"Project folder '{base_folder}' already exists and is not empty"
                )

        # Create project
        project = Project.from_scanner_args(
            name, base_folder, scanner_args, backend_type, description
        )

        logger.info(f"Project created: {name}")
        return project

    def load_project(self, project_folder: Path) -> Project:
        """
        Load an existing project from disk.

        Args:
            project_folder: Path to project root directory

        Returns:
            Loaded Project instance

        Raises:
            FileNotFoundError: If project.json doesn't exist
            json.JSONDecodeError: If project.json is corrupted
            ValueError: If project configuration is invalid
        """
        project_folder = Path(project_folder)
        config_path = project_folder / "project.json"

        if not config_path.exists():
            raise FileNotFoundError(
                f"No project.json found in '{project_folder}'"
            )

        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Corrupted project configuration: {e.msg}",
                e.doc,
                e.pos
            )

        # Validate required fields
        required_fields = ["version", "project_name", "scanner_config"]
        missing_fields = [f for f in required_fields if f not in config]
        if missing_fields:
            raise ValueError(
                f"Invalid project configuration: missing fields {missing_fields}"
            )

        project = Project(project_folder, config)
        logger.info(f"Project loaded: {config['project_name']}")
        return project

    def save_project(self, project: Project):
        """
        Save project configuration to disk.

        Args:
            project: Project to save
        """
        project.save()

    def delete_project(self, project: Project):
        """
        Delete project folder and all its contents.

        Args:
            project: Project to delete

        Raises:
            FileNotFoundError: If project folder doesn't exist
        """
        if not project.base_folder.exists():
            raise FileNotFoundError(
                f"Project folder '{project.base_folder}' does not exist"
            )

        # Delete entire project folder
        shutil.rmtree(project.base_folder)

        # If this was the active project, clear it
        if self.active_project == project:
            self.active_project = None

        logger.info(f"Project deleted: {project.config['project_name']}")

    def set_active_project(self, project: Optional[Project]):
        """
        Set the active project.

        Args:
            project: Project to set as active (or None to clear)
        """
        self.active_project = project
        if project:
            logger.info(f"Active project set: {project.config['project_name']}")
        else:
            logger.info("Active project cleared")

    def get_active_project(self) -> Optional[Project]:
        """
        Get the currently active project.

        Returns:
            Active project or None
        """
        return self.active_project

    def is_project_active(self) -> bool:
        """
        Check if a project is currently active.

        Returns:
            True if a project is active
        """
        return self.active_project is not None

    def close_project(self):
        """Close the active project (save and clear)."""
        if self.active_project:
            self.save_project(self.active_project)
            project_name = self.active_project.config['project_name']
            self.active_project = None
            logger.info(f"Project closed: {project_name}")

    # File path helpers (delegate to active project)

    def get_scans_dir(self) -> Optional[Path]:
        """Get scans directory of active project."""
        if self.active_project:
            return self.active_project.get_scans_dir()
        return None

    def get_masks_dir(self) -> Optional[Path]:
        """Get masks directory of active project."""
        if self.active_project:
            return self.active_project.get_masks_dir()
        return None

    def get_reconstruction_dir(self) -> Optional[Path]:
        """Get reconstruction directory of active project."""
        if self.active_project:
            return self.active_project.get_reconstruction_dir()
        return None

    # Data loading methods

    def load_all_2d_scans(self) -> List[LED2D]:
        """
        Load all 2D scans from active project.

        Returns:
            List of LED2D objects (empty if no active project)
        """
        if not self.active_project:
            return []

        scans_dir = self.active_project.get_scans_dir()
        if not scans_dir.exists():
            return []

        leds = get_all_2d_led_maps(scans_dir)
        logger.info(f"Loaded {len(leds)} 2D detections from project")
        return leds

    def load_3d_reconstruction(self) -> Optional[List[LED3D]]:
        """
        Load 3D reconstruction from active project.

        Returns:
            List of LED3D objects or None if not found
        """
        if not self.active_project:
            return None

        reconstruction_path = (
            self.active_project.get_reconstruction_dir() / "led_map_3d.csv"
        )

        if not reconstruction_path.exists():
            logger.debug("No 3D reconstruction found in project")
            return None

        leds = load_3d_leds_from_file(reconstruction_path)
        if leds:
            logger.info(f"Loaded {len(leds)} 3D points from project")
        return leds

    def load_masks(self) -> Dict[int, tuple[np.ndarray, Dict[str, Any]]]:
        """
        Load all detection masks from active project.

        Returns:
            Dictionary mapping camera index to (mask array, metadata dict)
        """
        if not self.active_project:
            return {}

        masks_dir = self.active_project.get_masks_dir()
        if not masks_dir.exists():
            return {}

        loaded_masks = {}

        # Find all mask PNG files
        mask_files = sorted(masks_dir.glob("detection_mask_*.png"))

        for mask_file in mask_files:
            # Extract camera index from filename: detection_mask_0.png -> 0
            try:
                camera_index = int(mask_file.stem.split("_")[-1])
            except (ValueError, IndexError):
                logger.warning(f"Could not parse camera index from {mask_file.name}")
                continue

            # Load mask image
            mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                logger.warning(f"Could not load mask image: {mask_file}")
                continue

            # Load metadata
            metadata_file = mask_file.with_suffix(".json")
            metadata = {}
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                except json.JSONDecodeError:
                    logger.warning(f"Could not load mask metadata: {metadata_file}")

            loaded_masks[camera_index] = (mask, metadata)

        logger.info(f"Loaded {len(loaded_masks)} detection masks from project")
        return loaded_masks

    def get_transform(self) -> Optional[Dict[str, Any]]:
        """
        Get visualization transform from active project.

        Returns:
            Transform dictionary or None
        """
        if not self.active_project:
            return None

        return self.active_project.config.get("visualization", {}).get("transform")

    def set_transform(self, transform: Dict[str, Any]):
        """
        Save visualization transform to active project.

        Args:
            transform: Transform dictionary with translation, rotation, scale
        """
        if not self.active_project:
            return

        if "visualization" not in self.active_project.config:
            self.active_project.config["visualization"] = {}

        self.active_project.config["visualization"]["transform"] = transform
        self.save_project(self.active_project)

    # Discovery methods

    def list_projects(self) -> List[Path]:
        """
        List all projects in the default projects root.

        Returns:
            List of project folder paths
        """
        return self.find_projects_in_directory(self.projects_root)

    def find_projects_in_directory(self, directory: Path) -> List[Path]:
        """
        Find all valid projects in a directory.

        Args:
            directory: Directory to search

        Returns:
            List of project folder paths
        """
        directory = Path(directory)
        if not directory.exists():
            return []

        projects = []
        for item in directory.iterdir():
            if item.is_dir() and (item / "project.json").exists():
                projects.append(item)

        return sorted(projects)
