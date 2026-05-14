# SarcomaAI GUI — Technical Report
**Engineering Team Internal Document**
Date: May 2026 | Version 1.0 | Author: Justin Kashi

---

## 1. System Overview

SarcomaAI GUI is a full-stack clinical workstation application for onboarding new institutions into the SarcomaAI federated learning project. It enables radiologists and research coordinators to:

1. Import DICOM MRI data from local storage
2. Visually review series in a Cornerstone3D DICOM viewer
3. Label each series as T1 or T2
4. Run an anonymization and normalization pipeline that produces standardized NIfTI files for federated model training

**Stack:**
- Frontend: React 19 + Cornerstone3D 2.0, served as a static build
- Backend: Flask (single-file `App.py`, ~400 lines) + SQLite
- Pipeline: Python modules (pydicom, SimpleITK, nibabel)
- Distribution: PyInstaller `.app` / `.dmg` for macOS, `.exe` for Windows

**Current deployment:** Two institutions (MUHC, MSKCC). Scaling to additional sites.

---

## 2. Issues and Risk Assessment

### 2.1 Anonymization Gap — CRITICAL RISK

**Severity: P0 — Study-ending if triggered**

**What the pipeline does:**
`dicom_anonymize.py` scrubs 34 DICOM tags by keyword match against `sensitive_fields.json`. After scrubbing, it sets `PatientIdentityRemoved = YES` and overwrites files in place.

**What it misses:**

**A. Private tags.** DICOM allows vendors to add institution-specific tags with numeric identifiers (e.g., `(2001,0010)` on Philips IntelliSpace, `(0019,109C)` on Siemens). These have no keyword — `elem.keyword` returns an empty string — so the scrub loop silently skips them. A private tag may contain the patient name, MRN, or date of birth verbatim.

**B. Burned-in pixel PHI.** Scout/localizer images on GE Centricity and some Siemens systems overlay the patient name directly onto the pixel data as white text. Tag scrubbing has no effect on pixel values. This survives the pipeline entirely.

**C. No post-scrub verification.** The pipeline writes the anonymized file but never reads it back to verify that scrubbed fields now contain dummy values. There is no audit log of what was checked and what was found.

**D. No per-institution customization.** The scrub list is global. Institution #3 may have a private tag structure entirely different from MUHC and MSKCC. Currently there is no mechanism to extend the scrub list per-site without editing source code on every machine.

**Implication:** A file containing PHI passes through the pipeline, receives `PatientIdentityRemoved = YES`, and enters the STS dataset labeled as clean. Under PIPEDA (Canada) and HIPAA (US), any subsequent access, storage, or sharing of that file constitutes a reportable privacy breach. Ethics board approval is contingent on anonymization being complete — a confirmed breach can revoke REB approval and halt the study across all institutions.

**Proposed fix — three components:**

1. **Post-scrub readback verification**: After `anonymize_series()` completes, a second pass reads every file back and confirms every keyword in `sensitive_fields.json` now contains the dummy value. Any failure is written to an audit log and surfaced to the user before the pipeline marks the patient as complete.

2. **Private tag audit**: Enumerate all elements with odd DICOM group numbers. For each, apply a heuristic check (name-like string, date-format string, MRN-format integer). Flag any matches in the audit log for manual review.

3. **Scout/localizer detection**: Flag series where `ImageType` contains `LOCALIZER` or slice count is below 5. These require manual inspection before pipeline completion is confirmed.

4. **Per-institution field override**: During the setup wizard, allow a site coordinator to specify additional tag keywords or numeric tag codes to scrub. Stored as `anonymization_fields/{INSTITUTION}_extra_fields.json`, loaded in addition to the base list.

**Tradeoffs:** The readback pass adds processing time per patient (estimated 15–30 seconds per series depending on file count). This is acceptable given the risk profile. The private tag heuristic will produce false positives — technical field values that look like names. These require a human review step, which adds friction. The alternative (no review) is worse.

---

### 2.2 Ledger Durability — HIGH RISK

**Severity: P1 — Governance failure if triggered**

**What the ledger is:**
`.ledger_internal.csv` is the only record linking the anonymized patient ID (`PA000001`) back to the original MRN. It is a crash-tolerant CSV with row-by-row appends, stored in the STS dataset folder.

**The risks:**
- No checksum or integrity verification. Silent corruption is undetectable.
- No backup. If the workspace folder is deleted, moved, or the drive fails, the mapping is permanently lost.
- No schema versioning. If a future pipeline update adds or removes columns, old ledger files are silently misread.
- A lost ledger means: inability to trace model failures back to patients, inability to respond to patient withdrawal requests under ethics, and inability to produce audit records if challenged by the REB.

**Proposed fixes:**

1. Compute SHA-256 of the ledger after every pipeline run. Store in `.ledger.sha256` alongside the file.
2. On app startup, verify the checksum. If it fails, block the pipeline and alert the user.
3. After every successful pipeline run, copy the ledger to a second path (user-configurable in setup, e.g., a network share or a separate drive).
4. Add a schema version header row to the CSV so format changes are detectable programmatically.

**Tradeoffs:** Checksum verification adds negligible overhead. The backup copy requires the user to configure a second path during setup — adding one step to onboarding. This is worth requiring given the consequences of ledger loss.

---

### 2.3 DICOM Tag Variance Across Institutions — MEDIUM RISK

**Severity: P1 for each new institution onboarded**

**The problem:**
Different PACS vendors (GE Centricity, Philips IntelliSpace, Siemens Syngo, IntelePACS) produce DICOM files with different private tag structures. The current anonymization list was built against MUHC and MSKCC data. Every new institution has a different PACS with different private tags.

Additionally, some institutions use IntelePACS's built-in de-identification service. These pre-processed files may have a different tag schema than raw exports, potentially causing the pipeline to behave unexpectedly.

A related gap: the two participating institutions (MUHC, MSKCC) are hardcoded as dropdown options in `SetupWizard.jsx`. Adding Institution #3 currently requires a developer to edit the component and rebuild and redistribute the app. Institution codes and display names should be loaded from a backend config endpoint before scaling to additional sites.

**Proposed fix:**
The per-institution field override (described in 2.1) addresses this partially. Additionally, an onboarding QC step should be defined: before processing any real patients at a new site, run the anonymization audit (2.1) on a small set of test files and review the private tag report with the site coordinator. This becomes part of the standard site onboarding checklist.

**Tradeoffs:** This adds an onboarding step that requires a technically literate person to review the audit output. At current scale (2 sites) this is manageable. At 10+ sites it should be automated further.

---

### 2.4 macOS Dock Bug — MEDIUM RISK (UX)

**Severity: P2 — Affects every user on every session**

**Root cause:**
`App.py` calls `app.run()` (Flask/Werkzeug WSGI loop) on the main thread. macOS requires the main thread to run an `NSApplicationMain()` event loop for an app to register as a proper GUI application. Werkzeug's WSGI loop does not satisfy this requirement.

Result: the dock icon bounces on launch, then goes dead. No active dot, no Cmd+Q, no bring-to-front from dock. The only way to quit is Activity Monitor → kill process.

**Proposed fix — pywebview:**
Move Flask to a background thread. Place a `pywebview` WKWebView window on the main thread. pywebview's `webview.start()` call creates a proper macOS `NSApplication` event loop, satisfying macOS.

```
Current: main thread = Werkzeug loop (macOS sees no GUI app)
Fixed:   main thread = WKWebView (macOS sees proper GUI app)
         background thread = Werkzeug loop
```

**Pre-condition before committing:** Cornerstone3D must be validated inside WKWebView (Safari engine) vs. its current testing environment (Chrome). WebGL, scroll behavior, and DICOM XHR fetches should be verified. Estimated test time: 2–4 hours.

**Tradeoffs:**
- WKWebView uses Safari's rendering engine. Subtle CSS/WebGL differences from Chrome are possible and must be tested.
- Adds `pywebview` as a dependency and increases PyInstaller bundle scope slightly.
- If Cornerstone3D does not work in WKWebView, the fallback is a `rumps` menubar icon approach (app lives in the macOS menubar, frontend still opens in browser).

---

### 2.5 App Distribution — MEDIUM RISK (Ops)

**Severity: P2 — Blocks IT approval at new sites**

**Current state:**
PyInstaller bundles the entire dependency stack (Flask, SimpleITK, pyCERR, scipy, nibabel, scikit-image, pandas, itk) into a single `.dmg`. Current size is >500MB. The `pyCERR` library alone (required for N4 bias correction via CERR) contributes ~200MB.

**Problems:**
- Many hospital IT departments have policies restricting installation of executables above a size threshold.
- Large files trigger antivirus scanning, which can quarantine the app on first launch.
- Every update requires IT re-approval and re-download of the full bundle.
- Windows support exists in `build_app.bat` but the folder picker uses `tkinter.filedialog` on Windows, which does not return absolute paths reliably from inside a PyInstaller bundle.

**Proposed fixes:**

**Immediate (reduce bundle size):** Remove pyCERR from the bundle and replace the CERR-based DICOM-to-array conversion with a direct SimpleITK equivalent. SimpleITK can read DICOM series natively. pyCERR was added for this single function. Removing it eliminates ~200MB.

**Medium-term (restructure distribution):** Package the application as a proper Python package (`pip install sarcomaai`) with two entry points:
- `sarcomaai` — CLI mode, Flask starts, user opens browser themselves
- Desktop bundle (PyInstaller) — pywebview window, proper app experience

This separates the Python package (small, pip-installable) from the bundled app (larger, for non-technical users). The React build is included in the pip package as static files via `package_data`.

**Architecture implications:** This requires restructuring `App.py` into a Flask app factory (`server.py`) with separate entry point files (`cli.py`, `desktop.py`). The pipeline moves inside the package at `sarcomaai/pipeline/`. All internal imports must be updated. This is a moderate refactor with the highest risk concentrated in the pipeline import changes — those must be validated with full end-to-end pipeline tests before shipping.

**Tradeoffs:**
- The restructuring is internal engineering work — users see no change in behavior, only potential improvement in app size.
- The pip distribution serves technical collaborators and developers, not clinical end users. It is low priority relative to the bundle size reduction.
- Restructuring carries import-breakage risk in the pipeline. Must be tested with real DICOM data and NIfTI output verified against pre-refactor baseline before deployment.

---

### 2.6 Backend Scalability — LOW RISK (Engineering Debt)

**Severity: P3 — Affects developer velocity, not users**

`App.py` is ~400 lines and growing. It contains Flask route definitions, pipeline orchestration, SQLite helpers, DICOM file serving, SSE streaming, folder picker integration, and startup logic in one file. As MCP servers, per-institution configuration, and additional pipeline steps are added, this file will become difficult to maintain.

**Proposed fix:** Standard Flask application factory pattern with blueprints. Routes organized by domain (`routes/dicom.py`, `routes/pipeline.py`, `routes/config.py`). This is a low-urgency refactor that can be done incrementally alongside other changes.

---

### 2.7 Pipeline Error Recovery — LOW RISK (Reliability)

**Severity: P3 — Affects pipeline reliability per run**

**The problem:**
`pipeline_new.py` processes series sequentially with no per-series isolation. If an exception is raised mid-run (corrupted DICOM file, unexpected series geometry, SimpleITK failure), the entire pipeline halts. All series scheduled after the failing one are not processed in that run, with no indication to the user distinguishing series that succeeded from series that were never attempted.

**Consequences:**
- A single bad DICOM file can silently leave a batch of patients unprocessed.
- The user must re-run the pipeline to recover. Idempotency mitigates duplicate processing but does not surface which series need re-processing.
- There is no per-series error log entry that distinguishes `ERROR` from `SKIPPED`.

**Proposed fix:** Wrap each series' processing block in a try/except. On failure, write the series to the audit log as `ERROR` with the exception traceback, then continue to the next series. Emit a run summary at the end enumerating successful, failed, and skipped series counts.

**Tradeoffs:** Error recovery adds complexity to pipeline control flow. The try/except scope must be carefully bounded — catching too broadly can mask bugs that should surface and halt.

---

### 2.8 No Automated Test Suite — LOW RISK (Engineering Debt)

**Severity: P3 — Affects developer confidence on refactors**

The application has no automated tests — no unit tests for pipeline logic, no integration tests for Flask endpoints, and no frontend component tests. Validation is manual QA against the specifications in `SYSTEM_DESIGN.md` and `USER-INSTRUCTIONS.md`.

**The risk:** Manageable at two institutions with a small team. As the codebase grows (MCP servers, per-institution configuration, distribution restructure), changes to pipeline or backend carry increasing risk of silent regressions not caught until a clinical user runs a pipeline.

**Proposed fix:** A minimal test layer targeting the highest-risk paths:
- Unit tests for `dicom_anonymize.py`: verify each sensitive field is scrubbed correctly on a synthetic `pydicom.Dataset()`
- Unit tests for `imaging_normalize.py`: verify output statistics (mean ≈ 0, std ≈ 1) on a known synthetic volume
- Integration tests for Flask API endpoints using Flask's built-in test client

**Tradeoffs:** Writing tests retroactively for scientific imaging code requires realistic test fixtures (synthetic DICOM files with known tag values). These are non-trivial but feasible with `pydicom.Dataset()`. This is P3 but becomes urgent before any major refactor — in particular the package restructure in 2.5, where import path changes carry pipeline-breakage risk without a regression baseline.

---

## 3. MCP Integration Plan

Model Context Protocol (MCP) servers expose the application's data to Claude, enabling a conversational interface for querying pipeline state, patient data, and DICOM metadata. Three servers are planned, in priority order.

### 3.1 Priority 1 — DICOM QC MCP Server

**Purpose:** Allow Claude to inspect DICOM metadata, validate anonymization, and flag PHI risks before or after the pipeline runs.

**Location:** `sarcomaAI-gui/mcp/dicom_qc_server.py`

**Reads from:** `runtime_config.json` (paths), filesystem (DICOM files directly via pydicom)

**Tools exposed:**

| Tool | Input | Output |
|---|---|---|
| `inspect_dicom_tags` | patient_id, series_id | All non-binary tag values as keyword→value dict |
| `validate_anonymization` | patient_id | Pass/fail + list of any tags that still contain non-dummy values |
| `scan_private_tags` | patient_id, series_id | All private (numeric) tags + heuristic PHI suspicion flag |
| `check_burnin_risk` | patient_id | Series flagged as localizer/scout by ImageType or slice count |
| `get_anonymization_report` | patient_id | Aggregated report: overall pass/fail + itemized findings |

**Example queries this enables:**
- "Check anonymization on PA000012 before I run the pipeline"
- "Are there private tags we haven't seen before at this institution?"
- "Flag any scout images in the current inbox"

**Dependencies:** Requires the post-scrub audit infrastructure (2.1) to exist first, otherwise Claude is auditing a process it cannot see into.

**Implementation estimate:** 2–3 days once audit infrastructure exists.

---

### 3.2 Priority 2 — Clinical Co-pilot MCP Server

**Purpose:** Allow Claude to answer questions about workspace state, patient progress, and pipeline history in natural language.

**Location:** `sarcomaAI-gui/mcp/coordinator_server.py`

**Reads from:** `runtime_config.json`, SQLite database (read-only), `.ledger_internal.csv`

**Tools exposed:**

| Tool | Input | Output |
|---|---|---|
| `get_workspace_status` | — | Total patients, complete/incomplete studies, last pipeline run |
| `list_incomplete_studies` | — | Studies missing T1, T2, or both, with patient IDs |
| `get_series_metadata` | patient_id, study_id | Series descriptions, slice counts, thickness, modality, date |
| `query_ledger` | institution, date_after | Processed patient records (MRN column excluded from output) |
| `get_pipeline_log` | — | Recent pipeline run output, line by line with timestamps |
| `summarize_data_completeness` | — | Percentage complete, percentage errored, percentage pending |

**Example queries this enables:**
- "How many studies are we missing T2 for?"
- "What errored in the last pipeline run?"
- "Give me a summary I can send to the site coordinator"

**Implementation estimate:** 1–2 days. Simpler than Priority 1 — reads existing structured data.

---

### 3.3 Priority 3 — Federated Site Coordination MCP (Future)

**Purpose:** Each site exposes a local MCP server. A central Claude agent queries all sites and gives the lead researcher a cross-institution view of data readiness before a federated learning round.

**Blocked by:** NVFlare integration (not yet implemented). Design the local MCP server now with this in mind so adding the cross-site layer is additive rather than a rewrite.

**Tools planned:** `get_site_readiness`, `report_data_stats`, `check_fl_prerequisites`

---

## 4. Implementation Priority Order

| Priority | Item | Risk if deferred | Estimated effort |
|---|---|---|---|
| 1 | Post-scrub anonymization audit + audit log | P0 — PHI leak | 3–5 days |
| 2 | pywebview dock fix (after Cornerstone3D validation) | P2 — UX | 1–2 days |
| 3 | Ledger checksum + backup | P1 — governance | 1 day |
| 4 | Private tag audit + scout detection | P0 support | 2–3 days |
| 5 | Per-institution anonymization field override | P1 per new site | 1–2 days |
| 6 | DICOM QC MCP server | Enables QC automation | 2–3 days |
| 7 | Clinical co-pilot MCP server | Operational efficiency | 1–2 days |
| 8 | pyCERR removal (bundle size reduction) | P2 — IT friction | 2–3 days |
| 9 | Package restructure (pip distribution) | Engineering debt | 3–5 days |
| 10 | Federated site coordination MCP | Future capability | TBD |

---

## 5. What Is Not Being Changed

- React frontend components and Cornerstone3D integration — stable, no changes planned. Note: the `/api/slice` endpoint renders each DICOM slice as a PNG via matplotlib before sending to the frontend. This bypasses Cornerstone3D's native windowing and histogram capabilities — window/level adjustment, magnification, and diagnostic-grade rendering are not available. This is an accepted limitation for the series-selection use case and is not in scope for this report.
- Python pipeline logic (anonymization rules, N4 bias correction, NIfTI normalization) — correct and complete
- SQLite schema — no changes needed
- Flask route API contract — no breaking changes in any of the above proposals
- MMNN_STS model — out of scope for this report
