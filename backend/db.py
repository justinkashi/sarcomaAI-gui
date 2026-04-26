"""
db.py — SQLite-backed state store for SarcomaAI GUI.

One database per workspace, stored at sarcomaai_workspace/sarcomaai.db.

Three tables:
  config     — institution, workspace path (persists across backend restarts)
  selections — T1/T2 series choices per patient/study, with processing status
  patients   — orig→new ID mapping + MRN written after each pipeline run

The pipeline writes a transient .pipeline_run_output.csv during processing.
After each run the backend ingests that file into `patients` and deletes it.
No other CSV files are used for state — ledger CSV is a pure on-demand export.
"""
import sqlite3
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS selections (
    patient    TEXT NOT NULL,
    study      TEXT NOT NULL,
    t1_series  TEXT NOT NULL DEFAULT '',
    t2_series  TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (patient, study)
);

CREATE TABLE IF NOT EXISTS patients (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    orig_id      TEXT NOT NULL,
    new_id       TEXT NOT NULL,
    mrn          TEXT,
    institution  TEXT NOT NULL,
    study        TEXT NOT NULL,
    series       TEXT NOT NULL,
    modality     TEXT NOT NULL,
    sts_name     TEXT,
    processed_at TEXT NOT NULL,
    UNIQUE (orig_id, study, modality)
);
"""

SELECTION_FIELDNAMES = ['Patient', 'Type', 'Study', 'Series']

# Columns used when exporting the researcher-facing ledger CSV
LEDGER_FIELDNAMES = ['Institution', 'MRN', 'Patient', 'Study', 'Series', 'Modality', 'MMNN Reference']

# Temp file written by pipeline_new.py during each run
_RUN_OUTPUT = '.pipeline_run_output.csv'


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def init_db(db_path: Path) -> None:
    """Create tables if they don't exist yet."""
    with _connect(db_path) as con:
        con.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def save_config(db_path: Path, **kwargs) -> None:
    with _connect(db_path) as con:
        con.executemany(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            list(kwargs.items()),
        )


def get_config(db_path: Path) -> Dict[str, str]:
    with _connect(db_path) as con:
        rows = con.execute("SELECT key, value FROM config").fetchall()
    return {r['key']: r['value'] for r in rows}


# ---------------------------------------------------------------------------
# Selections
# ---------------------------------------------------------------------------

def upsert_selection(db_path: Path, patient: str, study: str,
                     t1: Optional[str], t2: Optional[str]) -> None:
    """
    Save or update a T1/T2 selection. Resets status to 'pending' only when
    the series actually changes — prevents re-queuing an already-processed patient.
    """
    t1 = t1 or ''
    t2 = t2 or ''
    with _connect(db_path) as con:
        existing = con.execute(
            "SELECT t1_series, t2_series, status FROM selections WHERE patient=? AND study=?",
            (patient, study),
        ).fetchone()

        if existing and existing['status'] == 'processed':
            if existing['t1_series'] == t1 and existing['t2_series'] == t2:
                return  # No-op: same series, already processed

        con.execute(
            """INSERT INTO selections (patient, study, t1_series, t2_series, status, updated_at)
               VALUES (?, ?, ?, ?, 'pending', ?)
               ON CONFLICT(patient, study) DO UPDATE SET
                   t1_series  = excluded.t1_series,
                   t2_series  = excluded.t2_series,
                   status     = 'pending',
                   updated_at = excluded.updated_at""",
            (patient, study, t1, t2, datetime.utcnow().isoformat()),
        )


def get_selection(db_path: Path, patient: str, study: str) -> Dict:
    with _connect(db_path) as con:
        row = con.execute(
            "SELECT t1_series, t2_series, status FROM selections WHERE patient=? AND study=?",
            (patient, study),
        ).fetchone()
    if row:
        return {'t1': row['t1_series'] or None, 't2': row['t2_series'] or None, 'status': row['status']}
    return {'t1': None, 't2': None, 'status': 'pending'}


def get_pending_pairs(db_path: Path) -> List[Tuple[str, str]]:
    """Return (patient, study) pairs that have both T1+T2 and are not yet processed."""
    with _connect(db_path) as con:
        rows = con.execute(
            """SELECT patient, study FROM selections
               WHERE status = 'pending' AND t1_series != '' AND t2_series != ''""",
        ).fetchall()
    return [(r['patient'], r['study']) for r in rows]


def write_selections_csv(db_path: Path, out_path: Path) -> int:
    """Generate .selections.csv from pending DB rows for pipeline_new.py to consume."""
    with _connect(db_path) as con:
        rows = con.execute(
            """SELECT patient, study, t1_series, t2_series FROM selections
               WHERE status = 'pending' AND t1_series != '' AND t2_series != ''""",
        ).fetchall()

    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=SELECTION_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({'Patient': row['patient'], 'Type': 'T1',
                             'Study': row['study'], 'Series': row['t1_series']})
            writer.writerow({'Patient': row['patient'], 'Type': 'T2',
                             'Study': row['study'], 'Series': row['t2_series']})
    return len(rows)


def mark_batch_processed(db_path: Path, pairs: List[Tuple[str, str]]) -> None:
    now = datetime.utcnow().isoformat()
    with _connect(db_path) as con:
        con.executemany(
            "UPDATE selections SET status='processed', updated_at=? WHERE patient=? AND study=?",
            [(now, p, s) for p, s in pairs],
        )


# ---------------------------------------------------------------------------
# Pipeline run ingestion
# ---------------------------------------------------------------------------

def ingest_run_output(sts_dataset: Path, db_path: Path) -> int:
    """
    Read .pipeline_run_output.csv written by pipeline_new.py,
    insert rows into the patients table, then delete the temp file.
    Returns the number of rows ingested.
    """
    run_output = sts_dataset / _RUN_OUTPUT
    if not run_output.exists():
        return 0

    rows: list = []
    with open(run_output, newline='') as f:
        rows = list(csv.DictReader(f))

    now = datetime.utcnow().isoformat()
    with _connect(db_path) as con:
        con.executemany(
            """INSERT OR IGNORE INTO patients
               (orig_id, new_id, mrn, institution, study, series, modality, sts_name, processed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                r['OrigID'], r['NewID'], r.get('MRN'), r['Institution'],
                r['Study'], r['Series'], r['Modality'], r.get('STSName'), now,
            ) for r in rows],
        )

    run_output.unlink()
    return len(rows)


# ---------------------------------------------------------------------------
# Ledger export (pure on-demand report — no operational dependency)
# ---------------------------------------------------------------------------

def export_ledger(db_path: Path, sts_dataset: Path, institution: str) -> Path:
    """
    Query the patients table and write a researcher-named ledger snapshot:
      ledger_<institution>_<N>patients_<YYYYMMDD_HHMMSS>.csv
    Returns the output path.
    """
    with _connect(db_path) as con:
        rows = con.execute(
            """SELECT institution, mrn, new_id, study, series, modality, sts_name
               FROM patients ORDER BY new_id, modality""",
        ).fetchall()

    if not rows:
        raise ValueError("No processed patients in the database yet.")

    patient_ids = {r['new_id'] for r in rows}
    filename = (
        f"ledger_{institution}_{len(patient_ids):03d}patients"
        f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    out_path = sts_dataset / filename

    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                'Institution':    r['institution'],
                'MRN':            r['mrn'] or '',
                'Patient':        r['new_id'],
                'Study':          r['study'],
                'Series':         r['series'],
                'Modality':       r['modality'],
                'MMNN Reference': r['sts_name'] or '',
            })

    return out_path
