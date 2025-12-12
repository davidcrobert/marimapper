# Refactor Plan

## Goals and guardrails
- Make package boundaries obvious (hardware vs detection vs reconstruction vs UI) so a junior dev can follow data flow without cross-referencing multiple files.
- Rewrite code to be as readable as possible and follow clear patterns, flows, and architecture.
- Reduce duplication (multiple detector/coordinator variants) and side effects; favor small, testable units with typed inputs and outputs.
- Keep the GUI thin: UI code should bind to view models or services rather than owning business logic or multiprocessing.
- Maintain CLI/GUI compatibility during the transition via shims and deprecation warnings.

## Scope note
- Treat `marimapper-gui` as the primary application. The standalone CLI is secondary and should stay working where practical, but GUI experience drives architectural choices.

## Progress tracker
- [x] Baseline and hygiene: added `docs/architecture.md`; introduced `marimapper/core` with shared models/events; recorded GUI-first scope.
- [ ] Config unification: central loader + shared CLI/GUI config path.
- [ ] Hardware layer consolidation: single camera API and LED backend adapters.
- [ ] Detection package: unified algorithms/worker/API.
- [ ] Scanning and coordinator layer: migrate scanner/coordinator/queues into pipeline.
- [ ] Reconstruction package: restructure SFM and visualization interfaces.
- [ ] GUI re-architecture: split main window into view/viewmodel/controller layers.
- [ ] CLI and scripting: unified CLI package with compatibility shims.
- [ ] Testing and quality: mirrored tests, fixtures, type-checking/linting.
- [ ] Documentation and migration: mappings, deprecations, README/help updates.

## Current pain points (observed)
- Files are scattered at the package root (for example `scanner.py`, `detector_process.py`, `unified_*`, `file_writer_process.py`) alongside empty folders (`app/`, `core/`, `reconstruction/`, `runtime/`), making intent unclear.
- Multiple detector implementations (`detector.py`, `detector_fast.py`, `detector_process.py`, `detector_worker_process.py`, `unified_detector.py`) and coordinator variants make it unclear which pipeline is authoritative.
- GUI is monolithic (`gui/main_window.py` ~80KB) and mixes UI, threading, process control, and domain logic.
- Configuration flows differ between CLI and GUI (argparse helpers versus ad-hoc JSON handling) and do not consistently use the new `camera/` abstractions.
- Multiprocessing lifecycle management and message schemas are scattered; queue usage is ad-hoc, and start-method hacks leak into business code.
- Tests exist but do not map cleanly to the current structure; there are no obvious integration tests for the unified pipeline or GUI service layer.

## Target architecture (proposed package layout)
```
marimapper/
  core/                  # Domain models and contracts
    models.py            # LED, CameraSpec, Detection, ScanResult, ReconstructionResult
    config.py            # Typed config loading and validation
    events.py            # Message and command schemas for interprocess comms
  hardware/
    camera/              # Existing camera module, split into sources and controllers
    led_backends/        # Backends with a common interface and adapters to artnet, fadecandy, wled, pixelblaze, custom
  pipeline/
    detection/           # Detection algorithms and detector worker service
    scanning/            # Coordinator, scheduler, masks, movement and dark checks
    reconstruction/      # SFM, interpolation, visualization hooks (pycolmap and open3d)
    io/                  # File writer, persistence, caching, serialization
    services.py          # Base ProcessService or Worker abstraction and lifecycle helpers
  gui/
    app.py               # QApplication or bootstrap
    views/               # QWidget and dialogs only
    viewmodels/          # Qt signals and state binding to services
    widgets/             # Reusable components (detector tiles, log, control panel, 3D)
  cli/
    main.py              # Typer or Click root; shared args in one place
    commands/            # scanner, gui, backend checks, uploads
  docs/
    architecture.md      # Diagrams and scan -> detect -> reconstruct sequence
```
Add `marimapper/compat/` shims (re-export old names) during migration.

## Phased refactor plan

1) **Baseline and hygiene** ✓ COMPLETE
   - [x] Remove committed `__pycache__` and add ignore rules; ensure `pyproject.toml` exports only the new package paths.
     - __pycache__/ already in .gitignore, no committed pycache files found
     - pyproject.toml already points to correct script paths
   - [x] Add an `architecture.md` stub and module docstrings describing responsibilities.
     - docs/architecture.md created with high-level flow and package boundaries
   - [x] Introduce `marimapper/core` with minimal `models.py` and `events.py`; migrate common type aliases from scattered files.
     - marimapper/core/ created with models.py (dataclasses for LED, Camera, Detection, Scan, Reconstruction)
     - marimapper/core/events.py created with PipelineStage, DetectionCommand, and event dataclasses
     - marimapper/core/__init__.py exports all public types

2) **Config unification** ← IN PROGRESS
   - [x] Create `core/config.py` with unified configuration dataclasses
     - CameraVideoConfig, CameraControlConfig, CameraConfig (replaces camera/camera_config.py)
     - BackendConfig (consolidates backend type + args dict)
     - ScannerConfig (LED range, interpolation, thresholds, movement check, camera model)
     - MariMapperConfig (top-level: cameras list, backend, scanner)
     - All dataclasses have to_dict()/from_dict() for JSON serialization
     - Legacy converters: from_legacy_axis(), from_legacy_usb()
   - [x] Add config loader that supports both JSON files and argparse Namespace conversion
     - MariMapperConfig.from_json() / to_json() for file-based config
     - config_from_argparse() for CLI argparse.Namespace -> MariMapperConfig
   - [ ] Update CLI to use core/config.py instead of ad-hoc arg_tools
     - Requires: Extract backend-specific args from argparse properly
     - Decision: Defer to full CLI migration (Phase 8)
   - [ ] Update GUI to use core/config.py instead of scanner_args_serializer
     - Can start using MariMapperConfig for project save/load
     - Old scanner_args_serializer can be deprecated gradually
   - [x] Add migration helper for legacy CLI flags -> new config format
     - config_from_argparse() handles --axis-host, --device, --axis-hosts, --devices, etc.

   **Completed:**
   - Created core/config.py with all dataclasses
   - Exported from core/__init__.py
   - JSON serialization/deserialization working
   - Legacy arg conversion for camera configs working

   **Next steps:**
   - Document config file format in docs/
   - Add example config files
   - Start using in GUI for project persistence
   - Full CLI migration deferred to Phase 8

3) **Hardware layer consolidation**
   - Move `camera/` into `hardware/camera/` and make it the sole camera API; delete or alias legacy camera helpers once migrated.
   - Define a `LedBackend` protocol or base class; wrap artnet, fadecandy, wled, pixelblaze, and custom backends as adapters under `hardware/led_backends/`.
   - Normalize error handling and logging at this layer; add simulated or dummy backends for tests.

4) **Detection package**
   - Split detection into pure algorithms (thresholding, masking, localization) and runtime services (capture loop, command handling).
   - Replace `detector.py`, `detector_fast.py`, `detector_process.py`, `detector_worker_process.py`, and `unified_detector.py` with:
     - `detection/algorithms.py`
     - `detection/worker.py` (single implementation parameterized by camera or backends)
     - `detection/api.py` (start and stop, command enums from `core/events.py`)
   - Co-locate movement and darkness checks and mask handling; keep display and preview concerns out of workers.

5) **Scanning and coordinator layer**
   - Move `scanner.py`, `unified_coordinator.py`, `queues.py`, and `timeout_controller.py` into `pipeline/scanning/`.
   - Introduce a reusable `ProcessService` base (start, stop, join with timeouts) and a lightweight scheduler orchestrating detectors and backend.
   - Remove global start-method hacks by isolating Open3D or Qt imports and enforcing spawn at a single entrypoint.
   - Clearly define queue message schemas (reuse `core/events.py`) and document state machine (idle -> scanning -> reconstructing -> done or error).

6) **Reconstruction package**
   - Move `sfm.py`, `sfm_process.py`, and `pycolmap_tools/` into `pipeline/reconstruction/` with a single API surface.
   - Separate pure math from process execution (for example `engine.py` versus `worker.py`), and keep visualization hooks (`visualize_process.py`) behind interfaces.
   - Ensure interpolation, normals, and export live in the IO layer (`io/exporters.py`) rather than scattered helpers.

7) **GUI re-architecture**
   - Decompose `gui/main_window.py` into small controllers or viewmodels per area (cameras and detectors, control panel, log, 3D viewer).
   - Use Qt signals bound to `core/events.py` messages; GUI should talk to services through a thin adapter, not raw multiprocessing primitives.
   - Move widgets under `gui/widgets/` into `views/` versus `components/` and keep business logic in `viewmodels/`.
   - Add a GUI bootstrap (`gui/app.py`) that wires services and handles lifecycle (start and stop scanner, file writer, reconstruction).

8) **CLI and scripting**
   - Replace standalone scripts in `scripts/` with a unified CLI package (`cli/main.py` plus `commands/`).
   - Reuse shared argument builders and config loading; keep command handlers thin wrappers around service APIs.
   - Provide backward-compatible entrypoints for current console scripts; emit deprecation notices.

9) **Testing and quality**
   - Mirror package layout under `tests/` (unit for algorithms and models, integration for services, smoke for GUI and CLI).
   - Add fixtures for dummy camera and backends and recorded frames; add integration tests for multi-camera scan and reconstruction flow.
   - Add type checking (mypy or pyright) and linting to CI; enforce docstrings and typing in new modules.

10) **Documentation and migration**
   - Document end-to-end flow (scan -> detection -> reconstruction -> export) with sequence diagrams.
   - Provide a "where did it go?" mapping for moved modules and public APIs; update README and help texts.
   - Keep a migration compatibility layer (`marimapper/compat`) until external consumers switch to the new imports.

## Deliverables checklist
- New package layout created with shims for old imports.
- Central config, types, and events modules adopted by GUI and CLI.
- Single detection worker and coordinator implementation replacing legacy variants.
- GUI split into view, viewmodel, and controller layers; `main_window.py` slimmed down.
- Tests and CI updated to reflect the new structure with added integration coverage.
