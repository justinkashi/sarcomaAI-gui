"""
test_ledger.py — Tests for ledger.py

Verifies that the ledger:
- Creates an empty file with the correct header
- Appends rows correctly and can be read back
- Handles multiple appends without duplicating the header
"""

import csv
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "python_pipeline"))

from ledger import write_empty_ledger, append_ledger_row
from constants import LEDGER_HEADER


# A valid row in ledger order: Institution, MRN, Patient, Study, Series, Modality, MMNN Reference
SAMPLE_ROW = ["002", "MRN999", "PA000001", "ST000001", "SE000001", "t1", "sts.002.000001.t1"]


class TestWriteEmptyLedger:

    def test_creates_file(self, tmp_path):
        ledger = tmp_path / ".ledger_internal.csv"
        write_empty_ledger(ledger)
        assert ledger.exists()

    def test_header_matches_constant(self, tmp_path):
        ledger = tmp_path / ".ledger_internal.csv"
        write_empty_ledger(ledger)
        with ledger.open() as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == LEDGER_HEADER

    def test_no_data_rows_after_init(self, tmp_path):
        ledger = tmp_path / ".ledger_internal.csv"
        write_empty_ledger(ledger)
        with ledger.open() as f:
            rows = list(csv.reader(f))
        assert len(rows) == 1  # header only


class TestAppendLedgerRow:

    def test_row_appended_correctly(self, tmp_path):
        ledger = tmp_path / ".ledger_internal.csv"
        write_empty_ledger(ledger)
        append_ledger_row(ledger, SAMPLE_ROW)
        with ledger.open() as f:
            rows = list(csv.reader(f))
        assert len(rows) == 2  # header + 1 data row
        assert rows[1] == SAMPLE_ROW

    def test_multiple_rows_no_extra_headers(self, tmp_path):
        ledger = tmp_path / ".ledger_internal.csv"
        write_empty_ledger(ledger)
        for i in range(3):
            row = ["002", f"MRN{i}", f"PA00000{i+1}", "ST000001", "SE000001", "t1", f"sts.002.00000{i+1}.t1"]
            append_ledger_row(ledger, row)
        with ledger.open() as f:
            rows = list(csv.reader(f))
        assert len(rows) == 4  # 1 header + 3 data rows
        assert rows[0] == LEDGER_HEADER

    def test_row_order_preserved(self, tmp_path):
        ledger = tmp_path / ".ledger_internal.csv"
        write_empty_ledger(ledger)
        ids = ["PA000001", "PA000002", "PA000003"]
        for pa_id in ids:
            append_ledger_row(ledger, ["002", "MRN", pa_id, "ST", "SE", "t1", "ref"])
        with ledger.open() as f:
            data_rows = list(csv.reader(f))[1:]  # skip header
        assert [r[2] for r in data_rows] == ids

    def test_existing_rows_not_overwritten(self, tmp_path):
        ledger = tmp_path / ".ledger_internal.csv"
        write_empty_ledger(ledger)
        append_ledger_row(ledger, ["002", "MRN1", "PA000001", "ST", "SE", "t1", "ref1"])
        append_ledger_row(ledger, ["002", "MRN2", "PA000002", "ST", "SE", "t2", "ref2"])
        with ledger.open() as f:
            data_rows = list(csv.reader(f))[1:]
        assert data_rows[0][2] == "PA000001"
        assert data_rows[1][2] == "PA000002"
