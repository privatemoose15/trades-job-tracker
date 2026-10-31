#!/usr/bin/env python3
"""Build the demo into a real Google Sheet and check what Google calculated.

Every number and list on the Dashboard tab is worked out again here, straight from the
demo data, and compared with the values Google Sheets produced from the formulas.
The four tabs are left in place to look at, unless --cleanup is given.

Usage: python tests/live_check.py SHEET_ID [--cleanup]
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_sheet as b  # noqa: E402
from gspread.utils import ValueRenderOption  # noqa: E402

CHASE, UNPAID = 7, 30


def expected(today: date):
    jobs = b.demo_jobs(today)

    def of(status):
        return [j for j in jobs if j["Status"] == status]

    def value(js):
        return sum(j["Value £"] or 0 for j in js)

    def worth(js):
        return f"worth £{value(js):,}"

    serial = b.sheet_value
    next7 = sorted((j for j in of("Booked") if today <= j["Scheduled"] < today + timedelta(7)),
                   key=lambda j: j["Scheduled"])
    passed = [j for j in of("Booked") if j["Scheduled"] < today]
    paid = [j for j in of("Paid")
            if (j["Paid on"].year, j["Paid on"].month) == (today.year, today.month)]
    recent = [j for j in jobs if j["Quoted on"] and j["Quoted on"] >= today - timedelta(90)]
    decided = [j for j in recent if j["Status"] != "Quoted"]
    lost = [j for j in recent if j["Status"] == "Lost"]
    chase = sorted((j for j in of("Quoted") if (today - j["Quoted on"]).days >= CHASE),
                   key=lambda j: j["Quoted on"])
    unpaid = sorted(of("Invoiced"), key=lambda j: j["Invoiced on"])
    oldest = (today - min(j["Created"] for j in of("Enquiry"))).days

    cells = {
        "B5": len(of("Enquiry")), "B6": f"oldest: {oldest} days",
        "C5": len(of("Quoted")), "C6": worth(of("Quoted")),
        "D5": len(next7), "D6": worth(next7),
        "E5": len(passed), "E6": "update their status" if passed else "all up to date",
        "F5": len(of("Invoiced")), "F6": worth(of("Invoiced")),
        "G5": value(paid), "G6": f"{len(paid)} jobs",
        f"D{b.WIN_ROW}": round(1 - len(lost) / len(decided), 6),
    }
    for r, status in enumerate(b.STATUSES, start=b.PIPE_ROW + 1):
        cells[f"C{r}"] = len(of(status))
        cells[f"D{r}"] = value(of(status))

    lists = {
        b.NEXT7_ROW: [[serial(j["Scheduled"]), j["Customer"], j["Address"], j["Job type"],
                       j["Engineer"]] for j in next7],
        b.CHASE_ROW: [[j["Job ID"], j["Customer"], j["Phone"], j["Value £"],
                       serial(j["Quoted on"]), (today - j["Quoted on"]).days] for j in chase],
        b.UNPAID_ROW: [[j["Job ID"], j["Customer"], j["Phone"], j["Value £"],
                        serial(j["Invoiced on"]), (today - j["Invoiced on"]).days]
                       for j in unpaid],
    }
    return jobs, cells, lists


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet_id")
    ap.add_argument("--creds", default=b.DEFAULT_CREDS)
    ap.add_argument("--cleanup", action="store_true", help="delete the four tabs afterwards")
    args = ap.parse_args()

    today = date.today()
    sh = b.open_spreadsheet(args.creds, args.sheet_id)
    b.build(sh, today, reset=True)
    jobs, cells, lists = expected(today)
    failures = []

    def check(name, got, want):
        ok = got == want or (isinstance(want, float) and abs(float(got) - want) < 1e-6)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f": got {got!r}, want {want!r}"))
        if not ok:
            failures.append(name)

    unformatted = ValueRenderOption.unformatted
    grid = sh.worksheet("Dashboard").get_all_values(value_render_option=unformatted)

    def at(a1):
        return grid[int(a1[1:]) - 1][ord(a1[0]) - ord("A")]

    for a1, want in cells.items():
        label = at(f"{a1[0]}{b.TILE_ROW}") if int(a1[1:]) in (b.TILE_ROW + 1, b.TILE_ROW + 2) \
            else at(f"B{a1[1:]}")
        check(f"Dashboard {a1} ({label})", at(a1), want)

    for row, want in lists.items():
        width = len(want[0]) if want else 1
        got = [r[1:1 + width] for r in grid[row + 1:row + 1 + b.LIST_ROWS] if r[1] != ""]
        check(f"Dashboard list '{at(f'B{row}')}' ({len(want)} jobs)", got, want)

    rows = sh.worksheet("Jobs").get_all_values(value_render_option=unformatted)
    check("Jobs tab matches the demo data", rows[1:len(jobs) + 1],
          [[b.sheet_value(j[h]) for h in b.HEADERS] for j in jobs])
    check("Phone numbers stay text", rows[1][b.HEADERS.index("Phone")], jobs[0]["Phone"])

    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(title,index),conditionalFormats,"
                                              "charts,protectedRanges,basicFilter)"})
    tabs = {s["properties"]["title"]: s for s in meta["sheets"]}
    check("Tab order", [t for t in sorted(tabs, key=lambda t: tabs[t]["properties"]["index"])
                        if t in b.TABS], b.TABS)
    check("Jobs colour rules", len(tabs["Jobs"].get("conditionalFormats", [])),
          4 + len(b.STATUS_COLOURS))
    check("Jobs filter", "basicFilter" in tabs["Jobs"], True)
    check("Dashboard chart", len(tabs["Dashboard"].get("charts", [])), 1)
    check("Protected (warning-only) ranges",
          sum(len(tabs[t].get("protectedRanges", [])) for t in ("Jobs", "Dashboard")), 2)

    if args.cleanup:
        for t in b.TABS:
            sh.del_worksheet(sh.worksheet(t))
        print("Cleaned up: deleted the four tabs.")
    print(f"\n{len(failures)} failed" if failures else "\nAll checks passed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
