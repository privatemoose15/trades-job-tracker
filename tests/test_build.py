from datetime import date, timedelta

import pytest

import build_sheet as b

# Month ends, a leap day and New Year: the demo must work whatever day it's built
DAYS = [date(2026, 10, 31), date(2026, 11, 1), date(2028, 2, 29), date(2027, 1, 1)]
MILESTONES = ["Created", "Quoted on", "Scheduled", "Completed on", "Invoiced on", "Paid on"]
NEEDS = {  # dates each status must have, in order; every later milestone must be blank
    "Enquiry": 1, "Quoted": 2, "Lost": 2, "Booked": 3, "In progress": 3, "Done": 4,
    "Invoiced": 5, "Paid": 6,
}


@pytest.mark.parametrize("today", DAYS)
def test_demo_dates_make_sense_for_each_status(today):
    for job in b.demo_jobs(today):
        dates = [job[m] for m in MILESTONES]
        need = NEEDS[job["Status"]]
        assert all(dates[:need]), job["Customer"]
        assert not any(dates[need:]), job["Customer"]
        assert dates[:need] == sorted(dates[:need]), job["Customer"]
        assert all(d <= today for m, d in zip(MILESTONES, dates[:need]) if m != "Scheduled")
        if job["Status"] not in ("Booked", "In progress") and job["Scheduled"]:
            assert job["Scheduled"] <= today


@pytest.mark.parametrize("today", DAYS)
def test_demo_fills_every_part_of_the_dashboard(today):
    jobs = b.demo_jobs(today)
    status = lambda s: [j for j in jobs if j["Status"] == s]
    assert {j["Status"] for j in jobs} == set(b.STATUSES)
    assert any(today <= j["Scheduled"] < today + timedelta(7) for j in status("Booked"))
    assert any(j["Scheduled"] < today for j in status("Booked"))
    assert any((today - j["Quoted on"]).days >= 7 for j in status("Quoted"))
    assert any((today - j["Invoiced on"]).days > 30 for j in status("Invoiced"))
    assert any(j["Paid on"].month == today.month and j["Paid on"].year == today.year
               for j in status("Paid"))


def test_job_numbers_follow_creation_order():
    jobs = b.demo_jobs(DAYS[0])
    assert [j["Job ID"] for j in jobs] == [f"J-{n}" for n in range(1001, 1001 + len(jobs))]
    assert [j["Created"] for j in jobs] == sorted(j["Created"] for j in jobs)


def test_demo_rows_use_valid_lists_and_reserved_phone_numbers():
    for job in b.demo_jobs(DAYS[0]):
        assert set(job) == set(b.HEADERS)
        assert job["Job type"] in b.JOB_TYPES
        assert job["Engineer"] in b.ENGINEERS + [""]
        assert job["Phone"].startswith("07700 900")  # Ofcom drama range


def test_dates_become_sheet_serial_numbers():
    assert b.sheet_value(date(2026, 10, 31)) == 46326
    assert b.sheet_value(None) == ""
    assert b.sheet_value("J-1001") == "J-1001"


def test_formulas_point_at_the_right_columns():
    assert b.letter("Status") == "I"
    assert b.jobs_col("Value £") == "Jobs!$J$2:$J"
    assert b.setting_cell("Chase quotes after (days)") == "Settings!$B$4"
    cells = b.dashboard_cells()
    assert cells["E5"] == '=COUNTIFS(Jobs!$I$2:$I,"Booked",Jobs!$K$2:$K,"<"&TODAY())'
    assert "Settings!$B$4" in cells[f"B{b.CHASE_ROW + 2}"]


def _grid_ranges(obj):
    if isinstance(obj, dict):
        if "startRowIndex" in obj:
            yield obj
        for v in obj.values():
            yield from _grid_ranges(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _grid_ranges(v)


def test_every_request_stays_inside_its_tab():
    ids = {t: i for i, t in enumerate(b.TABS)}
    requests = b.format_requests(ids) + b.rule_requests(ids)
    for r in _grid_ranges(requests):
        rows, cols = b.GRID[b.TABS[r["sheetId"]]]
        assert r["endRowIndex"] <= rows and r["endColumnIndex"] <= cols, r


def test_dashboard_lists_have_room_to_spill():
    rows, cols = b.GRID["Dashboard"]
    for a1, value in b.dashboard_cells().items():
        spill = b.LIST_ROWS if str(value).startswith("=IFERROR(ARRAY_CONSTRAIN") else 1
        assert ord(a1[0]) - ord("A") < cols and int(a1[1:]) + spill - 1 <= rows, a1


class FakeSheet:
    def __init__(self, titles):
        self._ws = [type("WS", (), {"title": t})() for t in titles]

    def worksheets(self):
        return self._ws

    def __getattr__(self, name):
        raise AssertionError(f"build() touched the sheet ({name}) before refusing")


def test_build_refuses_to_overwrite_existing_tabs_without_reset():
    with pytest.raises(SystemExit, match="--reset"):
        b.build(FakeSheet(["Sheet1", "Jobs"]), DAYS[0])
