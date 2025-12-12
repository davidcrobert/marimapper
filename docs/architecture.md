# Architecture Overview

MariMapper is centered on the GUI application (`marimapper-gui`). The CLI remains supported where practical, but architectural choices optimize the GUI experience first.

## High-level flow
- **GUI**: Collects user input, starts and stops services, and presents previews and progress.
- **Scanning**: Coordinates LED backend control and detector workers, manages masks and movement/dark checks, and owns scan lifecycle state.
- **Detection**: Captures frames from cameras, thresholds to find LEDs, and emits 2D detections and metadata per view.
- **Reconstruction**: Consumes 2D detections to build 3D reconstructions, interpolation, and exports; feeds visualization.
- **IO**: Persists intermediate and final results (2D maps, 3D models, logs).

## Package boundaries (proposed)
- `core`: Domain models, configuration, and message/event schemas shared across layers.
- `hardware`: Cameras and LED backends behind stable interfaces; includes simulation/dummy backends for testing.
- `pipeline`: Scanning, detection, reconstruction, IO, and process/service lifecycle helpers.
- `gui`: Views/widgets and viewmodels/controllers that bind GUI state to pipeline services.
- `cli`: Thin wrappers that parse arguments and call the same services as the GUI.

## Interprocess communication
- Standardize message schemas (commands, events, results) via `core.events` to avoid ad-hoc tuples.
- Prefer spawn-safe initialization, minimal global side effects, and explicit lifecycle control for processes and threads.

## Migration notes
- Maintain backward compatibility through `marimapper.compat` shims while modules move.
- Document “where did it go?” mappings as modules are relocated, and deprecate legacy entrypoints incrementally.
