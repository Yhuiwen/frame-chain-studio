# Phase 3D-1 frontend runtime review

Phase 3D-1R restored the production SQLite database from the trusted 0026 backup before UI work continued. The accidentally migrated 0028 database is retained under the ignored `.run/database-recovery/` area for incident evidence.

UI review now starts through `scripts/dev-ui-review.ps1`. It creates a unique ignored `.run/ui-review/` directory with separate database, storage, logs, PID records, screenshots, and Fake Provider configuration. The entry point rejects run roots outside the isolated review directory and clears the TOAPIS API key for child processes.

Reviewed routes include the project list, empty and populated project details, Continuity Library, Usage/Budget, Provider Settings, Tasks, Scripts, Shot Spec, Visual Review, and the unknown-route page. Browser checks use 1440×900, 1280×720, and 390×844 viewports. Screenshots and machine-readable browser results remain in the ignored run directory and are not committed.

The focused UI changes standardize page width, spacing, typography, cards, media containment, long-text wrapping, table containment, and mobile stacking. User-visible mojibake in the project workflow was corrected, Provider and project-detail horizontal overflow was removed, and an explicit 404 state was added.

Known limitations:

- The isolated smoke data does not reproduce the historical paid Provider verification Run; production data is never copied into the UI environment.
- Visual Review is checked in its safe empty state. Existing unit tests cover its multi-dimensional production-gate semantics.
- Complex drag-and-drop editing remains desktop-first, while mobile guarantees basic readability and reachable navigation.
- Automated subject geometry, color/material drift analysis, and model-assisted visual review remain future work and are not implemented here.
