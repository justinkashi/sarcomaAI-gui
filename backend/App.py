from flask import Flask, jsonify, request, send_file, abort, Response, send_from_directory
from flask_cors import CORS
import os
import json as _json
import subprocess
import sys
import io
import threading
import webbrowser
import pydicom
import matplotlib.pyplot as plt
from pathlib import Path
from pydicom.errors import InvalidDicomError

import shutil
import db as _db


def _bundle_base() -> Path:
    """Root of all resources — works both in development and PyInstaller bundles."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    # Dev: App.py lives in backend/, resources are one level up
    return Path(__file__).parent.parent


_BASE            = _bundle_base()
PIPELINE_DIR     = str(_BASE / 'python_pipeline')
RUNTIME_CONFIG   = str(_BASE / 'python_pipeline' / 'runtime_config.json')
pipeline_script  = str(_BASE / 'python_pipeline' / 'pipeline_new.py')
_STATIC_FOLDER   = str(_BASE / 'frontend' / 'build')

# Resolved from the workspace at /api/setup time
WORKSPACE      = None   # Path  — root workspace directory
DATA_ROOT      = None   # str   — workspace/DICOM  (the staging inbox)
SELECTION_FILE = None   # str   — workspace/selections.csv
DB_PATH        = None   # Path  — workspace/sarcomaai.db
INSTITUTION    = None   # str   — institution code e.g. '002'
STS_DATASET    = None   # Path  — workspace/processed

app = Flask(__name__, static_folder=_STATIC_FOLDER, static_url_path='')
CORS(app)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_valid_dicom_files(series_path):
    result = []
    for fname in sorted(os.listdir(series_path)):
        if fname.startswith('.'):
            continue
        fp = os.path.join(series_path, fname)
        if not os.path.isfile(fp):
            continue
        try:
            pydicom.dcmread(fp, stop_before_pixels=True)
            result.append(fname)
        except Exception:
            continue
    return result


# ---------------------------------------------------------------------------
# Setup & workspace detection
# ---------------------------------------------------------------------------

@app.route('/api/check-workspace')
def check_workspace():
    """
    Returns whether a workspace already exists at the given path.
    If it does, also returns the stored institution code so the wizard
    can pre-fill and lock the institution field.
    """
    path = request.args.get('path', '').strip()
    if not path:
        return abort(400, "Missing path")

    db_path = Path(path) / 'sarcomaai_workspace' / 'sarcomaai.db'
    if not db_path.exists():
        return jsonify({'exists': False, 'institutionCode': None})

    try:
        cfg = _db.get_config(db_path)
        return jsonify({
            'exists': True,
            'institutionCode': cfg.get('institution'),
        })
    except Exception:
        return jsonify({'exists': False, 'institutionCode': None})


@app.route('/api/setup', methods=['POST'])
def setup():
    """
    Accept workspace path + institution from the wizard.
    Creates workspace/DICOM/ and workspace/processed/ if needed.
    Auto-detects new vs existing from presence of sarcomaai.db.
    """
    global WORKSPACE, DATA_ROOT, SELECTION_FILE, DB_PATH, INSTITUTION, STS_DATASET

    data           = request.json
    workspace_path = data.get('workspacePath', '').strip()
    institution    = data.get('institution', '').strip()

    if not workspace_path or not institution:
        return abort(400, "Missing required fields: workspacePath, institution")

    workspace = Path(workspace_path) / 'sarcomaai_workspace'

    # Create subdirectories (idempotent)
    inbox     = workspace / 'NEW_DICOMS'
    processed = workspace / 'processed'
    inbox.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    # Detect new vs existing before init_db creates the file
    db_path    = workspace / 'sarcomaai.db'
    is_new     = not db_path.exists()

    _db.init_db(db_path)
    _db.save_config(
        db_path,
        institution=institution,
        workspace=str(workspace),
    )

    WORKSPACE      = workspace
    DATA_ROOT      = str(inbox)
    SELECTION_FILE = str(workspace / '.selections.csv')  # hidden — pipeline-internal only
    STS_DATASET    = processed
    INSTITUTION    = institution
    DB_PATH        = db_path

    runtime_cfg = {
        "institution":    institution,
        "dataset_path":   str(inbox),
        "sts_dataset":    str(processed),
        "selection_csv":  SELECTION_FILE,
        "is_new_dataset": is_new,
    }
    Path(RUNTIME_CONFIG).write_text(_json.dumps(runtime_cfg, indent=2))

    has_patients = any(
        os.path.isdir(os.path.join(str(inbox), f))
        for f in os.listdir(str(inbox))
        if not f.startswith('.')
    ) if inbox.exists() else False

    return jsonify({'status': 'configured', 'dataRoot': DATA_ROOT, 'hasPatients': has_patients})


# ---------------------------------------------------------------------------
# DICOM import (source → NEW_DICOMS inbox)
# ---------------------------------------------------------------------------

@app.route('/api/scan-source')
def scan_source():
    """List patient-level subfolders at a given source path."""
    path = request.args.get('path', '').strip()
    if not path:
        return abort(400, "Missing path")
    if not os.path.isdir(path):
        return abort(404, f"Path does not exist: {path}")

    folders = sorted(
        f for f in os.listdir(path)
        if os.path.isdir(os.path.join(path, f)) and not f.startswith('.')
    )
    return jsonify({'folders': folders})


@app.route('/api/import-stream')
def import_stream():
    """
    SSE stream that copies patient folders from a source directory into the
    workspace NEW_DICOMS inbox. Already-present folders are skipped.
    """
    if DATA_ROOT is None:
        return abort(400, "Not configured. Call /api/setup first.")

    source = request.args.get('source', '').strip()
    if not source or not os.path.isdir(source):
        return abort(400, "Missing or invalid source path")

    inbox = Path(DATA_ROOT)

    folders = sorted(
        f for f in os.listdir(source)
        if os.path.isdir(os.path.join(source, f)) and not f.startswith('.')
    )

    def generate():
        for folder in folders:
            src = os.path.join(source, folder)
            dst = inbox / folder
            if dst.exists():
                yield f"data: {_json.dumps({'folder': folder, 'status': 'skipped'})}\n\n"
            else:
                try:
                    shutil.copytree(src, str(dst))
                    yield f"data: {_json.dumps({'folder': folder, 'status': 'copied'})}\n\n"
                except Exception as e:
                    yield f"data: {_json.dumps({'folder': folder, 'status': 'error', 'message': str(e)})}\n\n"
        yield f"data: {_json.dumps({'done': True})}\n\n"

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Access-Control-Allow-Origin': '*',
    })


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

import queue as _queue
import importlib as _importlib
import logging as _logging


class _QueueLogHandler(_logging.Handler):
    """Forwards log records to a queue as SSE-ready dicts."""
    def __init__(self, q: _queue.Queue):
        super().__init__()
        self.q = q
        self.setFormatter(_logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))

    def emit(self, record):
        self.q.put({'line': self.format(record)})


_PIPELINE_LOGGER_NAMES = [
    '',  # root
    'pipeline_new', 'config', 'series_select', 'ledger', 'csv_utils', 'models',
    'dicom', 'dicom.dicom_anonymize', 'dicom.dicom_copy', 'dicom.dicom_tags', 'dicom.dicom_utils',
    'imaging', 'imaging.imaging_normalize', 'imaging.imaging_io', 'imaging.imaging_utils',
]


def _run_pipeline_inprocess(log_q: _queue.Queue, result: dict) -> None:
    """
    Run pipeline_new.main() in the current process (needed inside PyInstaller
    bundles where sys.executable is the app binary, not a Python interpreter).
    Config module is reloaded so it picks up the runtime_config.json written
    by /api/setup.
    """
    handler = _QueueLogHandler(log_q)
    # Attach handler + set INFO level on root AND every known pipeline logger
    # so that PyInstaller-bundled Flask can't silently filter INFO records.
    prev_states: list = []
    for name in _PIPELINE_LOGGER_NAMES:
        lg = _logging.getLogger(name)
        prev_states.append((lg, lg.level, list(lg.handlers), lg.propagate))
        lg.setLevel(_logging.INFO)
        lg.addHandler(handler)
        if name:  # non-root loggers: disable propagation to avoid duplicate lines
            lg.propagate = False
    try:
        if PIPELINE_DIR not in sys.path:
            sys.path.insert(0, PIPELINE_DIR)
        import config as _cfg_mod
        _importlib.reload(_cfg_mod)
        import pipeline_new as _pipeline_mod
        _importlib.reload(_pipeline_mod)
        _pipeline_mod.main()
        result['returncode'] = 0
    except Exception as exc:
        log_q.put({'line': f'FATAL: {exc}'})
        result['returncode'] = 1
    finally:
        for lg, prev_level, prev_handlers, prev_propagate in prev_states:
            lg.setLevel(prev_level)
            lg.removeHandler(handler)
            lg.propagate = prev_propagate
        log_q.put(None)  # sentinel — generator stops here


# ---------------------------------------------------------------------------
# Pipeline routes
# ---------------------------------------------------------------------------

@app.route('/api/run-pipeline', methods=['POST'])
def run_pipeline():
    if DATA_ROOT is None:
        return abort(400, "Not configured. Call /api/setup first.")

    pending = _db.get_pending_pairs(DB_PATH)
    _db.write_selections_csv(DB_PATH, Path(SELECTION_FILE))

    if hasattr(sys, '_MEIPASS'):
        # Bundled: run in-process (no standalone Python interpreter available)
        log_q: _queue.Queue = _queue.Queue()
        result: dict = {}
        _run_pipeline_inprocess(log_q, result)
        rc = result.get('returncode', 1)
    else:
        proc = subprocess.run(
            [sys.executable, pipeline_script],
            cwd=PIPELINE_DIR,
            capture_output=True,
            text=True,
            timeout=3600,
        )
        rc = proc.returncode

    _db.ingest_run_output(STS_DATASET, DB_PATH)
    if rc == 0 and pending:
        _db.mark_batch_processed(DB_PATH, pending)

    return jsonify({'returncode': rc, 'success': rc == 0})


@app.route('/api/run-pipeline-stream')
def run_pipeline_stream():
    if DATA_ROOT is None:
        return abort(400, "Not configured")

    pending = _db.get_pending_pairs(DB_PATH)
    _db.write_selections_csv(DB_PATH, Path(SELECTION_FILE))

    def generate():
        result: dict = {}

        if hasattr(sys, '_MEIPASS'):
            # Bundled: run pipeline in a background thread, stream via queue
            log_q: _queue.Queue = _queue.Queue()
            t = threading.Thread(
                target=_run_pipeline_inprocess, args=(log_q, result), daemon=True
            )
            t.start()
            while True:
                item = log_q.get()
                if item is None:
                    break
                yield f"data: {_json.dumps(item)}\n\n"
        else:
            # Dev: subprocess with live stdout
            process = subprocess.Popen(
                [sys.executable, pipeline_script],
                cwd=PIPELINE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in process.stdout:
                yield f"data: {_json.dumps({'line': line.rstrip()})}\n\n"
            process.wait()
            result['returncode'] = process.returncode

        _db.ingest_run_output(STS_DATASET, DB_PATH)
        rc = result.get('returncode', 1)
        if rc == 0 and pending:
            _db.mark_batch_processed(DB_PATH, pending)
        yield f"data: {_json.dumps({'done': True, 'returncode': rc})}\n\n"

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Access-Control-Allow-Origin': '*',
    })


# ---------------------------------------------------------------------------
# Patient / series tree
# ---------------------------------------------------------------------------

@app.route('/api/patients')
def list_patients():
    if DATA_ROOT is None:
        return abort(400, "Not configured. Call /api/setup first.")
    if not os.path.exists(DATA_ROOT):
        return jsonify({"error": "Invalid DATA_ROOT path"}), 404

    patients = []
    for pa_folder in sorted(os.listdir(DATA_ROOT)):
        pa_path = os.path.join(DATA_ROOT, pa_folder)
        if not os.path.isdir(pa_path):
            continue
        for st_folder in os.listdir(pa_path):
            st_path = os.path.join(pa_path, st_folder)
            if not os.path.isdir(st_path):
                continue
            for se_folder in os.listdir(st_path):
                se_path = os.path.join(st_path, se_folder)
                if not os.path.isdir(se_path):
                    continue
                for f in os.listdir(se_path):
                    file_path = os.path.join(se_path, f)
                    if not os.path.isfile(file_path):
                        continue
                    try:
                        pydicom.dcmread(file_path, stop_before_pixels=True)
                        relative_path = os.path.relpath(st_path, DATA_ROOT)
                        if relative_path not in patients:
                            patients.append(relative_path)
                        break
                    except Exception:
                        continue
    return jsonify(sorted(set(patients)))


@app.route('/api/series')
def get_series():
    if DATA_ROOT is None:
        return abort(400, "Not configured. Call /api/setup first.")

    patient     = request.args.get('patient')
    series_path = os.path.join(DATA_ROOT, patient)

    if not os.path.isdir(series_path):
        return abort(404, "Patient path not found")

    series_folders = [
        folder for folder in sorted(os.listdir(series_path))
        if os.path.isdir(os.path.join(series_path, folder))
    ]
    return jsonify(series_folders)


# ---------------------------------------------------------------------------
# DICOM serving
# ---------------------------------------------------------------------------

@app.route('/api/slice')
def get_slice():
    if DATA_ROOT is None:
        return abort(400, "Not configured. Call /api/setup first.")

    patient   = request.args.get('patient')
    series    = request.args.get('series')
    slice_idx = int(request.args.get('slice', 0))

    series_path = os.path.join(DATA_ROOT, patient, series)
    if not os.path.isdir(series_path):
        return abort(404, "Series not found")

    valid_files = _get_valid_dicom_files(series_path)
    if not valid_files:
        return abort(404, "No valid DICOM files in this series")
    if slice_idx < 0 or slice_idx >= len(valid_files):
        return abort(400, "Slice index out of bounds")

    try:
        dcm = pydicom.dcmread(os.path.join(series_path, valid_files[slice_idx]))
    except InvalidDicomError:
        return abort(415, "Invalid DICOM at this slice")

    buf = io.BytesIO()
    matplotlib = __import__('matplotlib.pyplot', fromlist=['imsave'])
    matplotlib.imsave(buf, dcm.pixel_array, cmap='gray', format='png')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


@app.route('/api/max-slice')
def get_max_slice():
    if DATA_ROOT is None:
        return abort(400, "Not configured. Call /api/setup first.")

    patient     = request.args.get('patient')
    series      = request.args.get('series')
    series_path = os.path.join(DATA_ROOT, patient, series)

    if not os.path.isdir(series_path):
        return abort(404, "Series not found")

    valid_files = _get_valid_dicom_files(series_path)
    return jsonify({'maxSlice': len(valid_files)})


@app.route('/api/dicom-file')
def get_dicom_file():
    if DATA_ROOT is None:
        return abort(400, "Not configured. Call /api/setup first.")

    patient = request.args.get('patient')
    series  = request.args.get('series')
    index   = int(request.args.get('index', 0))

    series_path = os.path.join(DATA_ROOT, patient, series)
    if not os.path.isdir(series_path):
        return abort(404, "Series not found")

    valid_files = _get_valid_dicom_files(series_path)
    if not valid_files:
        return abort(404, "No valid DICOM files in this series")
    if index < 0 or index >= len(valid_files):
        return abort(400, "Index out of bounds")

    fp       = os.path.join(series_path, valid_files[index])
    response = send_file(fp, mimetype='application/dicom')
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


@app.route('/api/series-metadata')
def get_series_metadata():
    if DATA_ROOT is None:
        return abort(400, "Not configured. Call /api/setup first.")

    patient     = request.args.get('patient')
    series      = request.args.get('series')
    series_path = os.path.join(DATA_ROOT, patient, series)

    if not os.path.isdir(series_path):
        return abort(404, "Series not found")

    valid_files = _get_valid_dicom_files(series_path)
    if not valid_files:
        return abort(404, "No valid DICOM files in this series")

    try:
        dcm = pydicom.dcmread(
            os.path.join(series_path, valid_files[0]), stop_before_pixels=True
        )
    except Exception as e:
        return abort(500, f"Failed to read DICOM header: {e}")

    def tag(attr, default=''):
        try:
            val = getattr(dcm, attr, None)
            return str(val).strip() if val is not None else default
        except Exception:
            return default

    return jsonify({
        'seriesDescription': tag('SeriesDescription'),
        'sliceCount':        len(valid_files),
        'sliceThickness':    tag('SliceThickness'),
        'acquisitionDate':   tag('AcquisitionDate') or tag('StudyDate'),
        'modality':          tag('Modality'),
    })


# ---------------------------------------------------------------------------
# Selections (DB-backed)
# ---------------------------------------------------------------------------

@app.route('/api/save-selection', methods=['POST'])
def save_selection():
    if DB_PATH is None:
        return abort(400, "Not configured. Call /api/setup first.")

    data          = request.json
    patient_study = data.get('patient')
    t1_series     = data.get('t1') or None
    t2_series     = data.get('t2') or None

    if not patient_study:
        return abort(400, "Missing patient/study")
    try:
        patient, study = patient_study.split('/')
    except ValueError:
        return abort(400, "Expected patient format 'PAxxxx/STxxxx'")

    _db.upsert_selection(DB_PATH, patient, study, t1_series, t2_series)
    return jsonify({'status': 'saved'})


@app.route('/api/get-selection')
def get_selection():
    if DB_PATH is None:
        return abort(400, "Not configured. Call /api/setup first.")

    patient_study = request.args.get('patient')
    if not patient_study:
        return abort(400, "Missing patient/study")
    try:
        patient, study = patient_study.split('/')
    except ValueError:
        return abort(400, "Expected patient format 'PAxxxx/STxxxx'")

    return jsonify(_db.get_selection(DB_PATH, patient, study))


# ---------------------------------------------------------------------------
# Ledger export
# ---------------------------------------------------------------------------

@app.route('/api/export-ledger', methods=['POST'])
def export_ledger():
    """Generate a named ledger snapshot and return it as a file download."""
    if DB_PATH is None or STS_DATASET is None:
        return abort(400, "Not configured. Call /api/setup first.")
    try:
        out_path = _db.export_ledger(DB_PATH, STS_DATASET, INSTITUTION)
    except ValueError as e:
        return abort(404, str(e))
    except Exception as e:
        return abort(500, str(e))

    return jsonify({'filename': out_path.name, 'path': str(out_path)})


# ---------------------------------------------------------------------------
# Native folder picker (macOS)
# ---------------------------------------------------------------------------

@app.route('/api/pick-folder')
def pick_folder():
    """
    Opens a native folder-picker dialog server-side and returns the selected path.
    macOS: uses osascript. Windows/Linux: uses tkinter.filedialog.
    Returns {'path': null} if the user cancels.
    """
    try:
        if sys.platform == 'darwin':
            proc = subprocess.run(
                ['osascript', '-e', 'POSIX path of (choose folder)'],
                capture_output=True, text=True, timeout=120
            )
            if proc.returncode != 0:
                return jsonify({'path': None})
            return jsonify({'path': proc.stdout.strip()})
        else:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askdirectory()
            root.destroy()
            return jsonify({'path': path or None})
    except Exception as e:
        return jsonify({'path': None, 'error': str(e)})


# ---------------------------------------------------------------------------
# React static file serving (used when Flask IS the production web server)
# ---------------------------------------------------------------------------

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    """Serve React build files; fall back to index.html for client-side routing."""
    if app.static_folder and os.path.exists(app.static_folder):
        target = os.path.join(app.static_folder, path)
        if path and os.path.exists(target):
            return send_from_directory(app.static_folder, path)
        return send_from_directory(app.static_folder, 'index.html')
    return abort(404, "React build not found — run 'npm run build' first.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

PORT = int(os.environ.get('SARCOMAAI_PORT', 5050))


def _open_browser():
    """Poll until Flask is accepting connections, then open the browser."""
    import time
    import urllib.request
    for _ in range(60):          # wait up to 30 seconds
        try:
            urllib.request.urlopen(f'http://localhost:{PORT}/', timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    webbrowser.open(f'http://localhost:{PORT}')


if __name__ == '__main__':
    is_bundled = hasattr(sys, '_MEIPASS')
    if is_bundled:
        threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False, threaded=True)
