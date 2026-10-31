#!/usr/bin/env python3
"""Build the trades job tracker demo in a Google Sheet.

Creates four tabs: Dashboard, Jobs, Lists and Settings. Jobs gets fictional demo jobs dated
around today, and the tabs get their dropdowns, colour rules, dashboard formulas and chart.
The Apps Script in apps-script/ adds the rest: the menu, the "Add a job" form, automatic
dates and the Monday summary email.

Nothing here is needed at run time. It only makes the demo (or a client's starting copy)
repeatable instead of set up by hand.
"""
import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import gspread
from gspread.utils import a1_range_to_grid_range, rowcol_to_a1

BUSINESS = "Brackenford Plumbing & Heating"
TABS = ["Dashboard", "Jobs", "Lists", "Settings"]
HEADERS = ["Job ID", "Created", "Customer", "Phone", "Address", "Job type", "Description",
           "Engineer", "Status", "Value £", "Scheduled", "Quoted on", "Completed on",
           "Invoiced on", "Paid on", "Notes"]
STATUSES = ["Enquiry", "Quoted", "Booked", "In progress", "Done", "Invoiced", "Paid", "Lost"]
JOB_TYPES = ["Boiler service", "Boiler install", "Leak / repair", "Bathroom fit",
             "Radiators", "Gas safety check", "Other"]
ENGINEERS = ["Sam", "Priya", "Tom"]
# Moving a job to one of these statuses stamps today's date in the matching column
# (the Apps Script does this; see STAMP_COLUMNS in apps-script/Logic.gs)
STAMPS = {"Quoted": "Quoted on", "Done": "Completed on", "Invoiced": "Invoiced on",
          "Paid": "Paid on"}
TEXT_COLUMNS = ["Job ID", "Customer", "Phone", "Address", "Description", "Notes"]
DATE_COLUMNS = ["Created", "Scheduled"] + list(STAMPS.values())
# label, demo value, help text. The Apps Script finds settings by label, so keep labels as-is.
SETTINGS = [
    ("Business name", BUSINESS, "Shown on the dashboard and in the summary email."),
    ("Summary email to", "", "Who gets the Monday summary. Blank = whoever turns it on."),
    ("Chase quotes after (days)", 7, "Quotes waiting at least this long go on the chase list."),
    ("Flag unpaid after (days)", 30, "Invoices unpaid for longer than this turn red."),
]
JOB_ROWS = 1000  # grid size of the Jobs tab; formats and rules cover all of it
DATE = ("DATE", "d mmm yy")
DAY = ("DATE", "ddd d mmm yy")
MONEY = ("CURRENCY", "£#,##0")
SHEETS_EPOCH = date(1899, 12, 30)
DEFAULT_CREDS = os.environ.get("GOOGLE_CREDENTIALS",
                               str(Path.home() / ".config" / "gspread" / "service_account.json"))


# --- 1. Demo data: a fictional business. Phone numbers are in Ofcom's 07700 900xxx range,
# which is reserved for TV and film and never issued. Dates are day offsets from today,
# so the demo always looks current whenever it is built. ---

def _job(customer, phone, address, job_type, description, engineer, status, value, created,
         quoted=None, scheduled=None, done=None, invoiced=None, paid=None, notes=""):
    return dict(customer=customer, phone=phone, address=address, job_type=job_type,
                description=description, engineer=engineer, status=status, value=value,
                created=created, quoted=quoted, scheduled=scheduled, done=done,
                invoiced=invoiced, paid=paid, notes=notes)


DEMO = [
    _job("Hannah Price", "900114", "3 Wren Close", "Boiler install",
         "Old back boiler, wants a combi quote", "", "Enquiry", None, -1),
    _job("Dev Patel", "900127", "41 Station Road", "Leak / repair",
         "Dripping stopcock under the stairs", "", "Enquiry", None, 0),
    _job("Brackenford Scout Hut", "900131", "Scout Hut, Green Lane", "Gas safety check",
         "Annual check, 2 heaters", "", "Enquiry", None, -3, notes="Ask for Pete"),
    _job("Margaret Ellis", "900135", "7 Orchard Way", "Boiler install",
         "Replace 20-year-old boiler with a combi", "Sam", "Quoted", 2850, -16, quoted=-12),
    _job("Tomasz Nowak", "900142", "Flat 2, 18 Market Street", "Radiators",
         "Swap 4 radiators, add TRVs", "Priya", "Quoted", 640, -11, quoted=-9),
    _job("Laura & Ben Chapman", "900158", "The Granary, Mill Lane", "Bathroom fit",
         "Full bathroom refit, customer supplying tiles", "Tom", "Quoted", 6400, -6, quoted=-3),
    _job("Riverside Dental Practice", "900149", "Unit 3, Riverside Park", "Gas safety check",
         "Gas safety check, 3 appliances", "Priya", "Quoted", 180, -4, quoted=-2),
    _job("Grace Okafor", "900163", "22 Beech Avenue", "Boiler service",
         "Annual service, combi in kitchen", "Sam", "Booked", 95, -9, quoted=-8, scheduled=1),
    _job("Arjun Mehta", "900171", "5 Kingfisher Court", "Boiler install",
         "Combi swap, flue moving to side wall", "Sam", "Booked", 3150, -30, quoted=-26,
         scheduled=3, notes="Deposit paid"),
    _job("Claire Donnelly", "900186", "64 Hill Rise", "Leak / repair",
         "Leak on kitchen waste pipe", "Tom", "Booked", 140, -2, quoted=-2, scheduled=2),
    _job("Fern Cottage Holidays", "900194", "Fern Cottage, Back Lane", "Gas safety check",
         "Landlord gas safety certificate", "Priya", "Booked", 75, -5, quoted=-5, scheduled=6,
         notes="Key in key safe"),
    _job("Peter Walsh", "900203", "9 Church View", "Radiators",
         "Bleed and balance, one cold radiator upstairs", "Tom", "Booked", 120, -7, quoted=-6,
         scheduled=-2),
    _job("Sunita Rao", "900219", "17 Meadow Drive", "Bathroom fit",
         "Shower room conversion", "Tom", "Booked", 4850, -40, quoted=-35, scheduled=10),
    _job("Bob & Linda Harris", "900226", "2 Old Forge Cottages", "Bathroom fit",
         "Bathroom refit, 5 days", "Tom", "In progress", 5900, -45, quoted=-41, scheduled=-2),
    _job("Kerry Mills", "900238", "30 Park Crescent", "Boiler install",
         "System boiler and new cylinder", "Sam", "In progress", 3400, -25, quoted=-21,
         scheduled=-1),
    _job("James Fletcher", "900241", "11 Ash Grove", "Leak / repair",
         "Burst pipe in loft, lagged afterwards", "Sam", "Done", 260, -3, quoted=-3,
         scheduled=-1, done=-1),
    _job("Olivia Grant", "900257", "8 Heron Way", "Boiler service",
         "Service plus new pressure relief valve", "Priya", "Done", 165, -12, quoted=-11,
         scheduled=-2, done=-2),
    _job("Nadia Hussain", "900263", "52 Victoria Road", "Radiators",
         "3 new radiators in the extension", "Tom", "Invoiced", 980, -60, quoted=-55,
         scheduled=-44, done=-42, invoiced=-41, notes="Reminder sent"),
    _job("Mark Thompson", "900272", "6 Brook Lane", "Boiler service",
         "Annual service", "Sam", "Invoiced", 95, -20, quoted=-19, scheduled=-13, done=-13,
         invoiced=-12),
    _job("The Old Bakery Café", "900288", "1 High Street", "Leak / repair",
         "Leak under the prep sink", "Priya", "Invoiced", 210, -8, quoted=-8, scheduled=-6,
         done=-6, invoiced=-5),
    _job("Helen Carter", "900295", "19 Elm Road", "Boiler install",
         "Combi install plus magnetic filter", "Sam", "Paid", 2650, -50, quoted=-46,
         scheduled=-20, done=-19, invoiced=-19, paid=-6),
    _job("Chris Doyle", "900301", "4 Mill Cottages", "Boiler service",
         "Annual service", "Sam", "Paid", 95, -10, quoted=-10, scheduled=-4, done=-4,
         invoiced=-4, paid=0),
    _job("Amira Saleh", "900316", "27 Linden Close", "Gas safety check",
         "Landlord certificates, 2 flats", "Priya", "Paid", 150, -18, quoted=-17,
         scheduled=-9, done=-9, invoiced=-9, paid=-3),
    _job("Gary Bennett", "900324", "13 Field View", "Radiators",
         "Powerflush and 2 radiators", "Tom", "Paid", 720, -48, quoted=-45, scheduled=-37,
         done=-36, invoiced=-36, paid=-33),
    _job("Rachel Kim", "900339", "45 Chestnut Walk", "Leak / repair",
         "Replace leaking radiator valve", "Tom", "Paid", 115, -29, quoted=-29, scheduled=-27,
         done=-27, invoiced=-27, paid=-20),
    _job("Brackenford Cricket Club", "900347", "Pavilion, Green Lane", "Other",
         "Outside tap and frost jacket", "Priya", "Paid", 185, -70, quoted=-68, scheduled=-62,
         done=-62, invoiced=-61, paid=-50),
    _job("Simon Reid", "900352", "38 Sycamore Drive", "Boiler install",
         "Combi swap", "Sam", "Lost", 2900, -35, quoted=-32, notes="Went with a cheaper quote"),
    _job("Emma Lawson", "900368", "10 Rowan Close", "Bathroom fit",
         "Full bathroom refit", "Tom", "Lost", 5200, -80, quoted=-75,
         notes="Postponed to next year"),
    _job("Ian Foster", "900374", "3 Poplar Row", "Radiators",
         "Move radiator for kitchen refit", "Tom", "Lost", 380, -22, quoted=-20,
         notes="No reply after 2 chases"),
    _job("Joanne Webb", "900385", "Unit 4, Mill Yard", "Other",
         "Commercial kitchen gas interlock", "Priya", "Lost", 1450, -40, quoted=-36,
         notes="Needs commercial gas ticket"),
]


def demo_jobs(today: date) -> list:
    """Demo jobs as dicts keyed by HEADERS, oldest first, numbered J-1001 upwards."""
    def day(offset):
        return None if offset is None else today + timedelta(days=offset)

    jobs = []
    for n, j in enumerate(sorted(DEMO, key=lambda j: j["created"]), start=1001):
        jobs.append({
            "Job ID": f"J-{n}", "Created": day(j["created"]), "Customer": j["customer"],
            "Phone": f"07700 {j['phone']}", "Address": j["address"],
            "Job type": j["job_type"], "Description": j["description"],
            "Engineer": j["engineer"], "Status": j["status"], "Value £": j["value"],
            "Scheduled": day(j["scheduled"]), "Quoted on": day(j["quoted"]),
            "Completed on": day(j["done"]), "Invoiced on": day(j["invoiced"]),
            "Paid on": day(j["paid"]), "Notes": j["notes"],
        })
    return jobs


def sheet_value(v):
    """Dates go in as Sheets serial numbers (formatted by the column), blanks as ''."""
    if isinstance(v, date):
        return (v - SHEETS_EPOCH).days
    return "" if v is None else v


# --- 2. Where things live: column letters and the formulas built from them ---

def letter(header: str) -> str:
    return rowcol_to_a1(1, HEADERS.index(header) + 1)[:-1]


def jobs_col(header: str) -> str:
    """Open-ended range for one Jobs column, e.g. Jobs!$I$2:$I, so new rows are included."""
    col = letter(header)
    return f"Jobs!${col}$2:${col}"


def setting_cell(label: str) -> str:
    return f"Settings!$B${2 + [s[0] for s in SETTINGS].index(label)}"


# Dashboard layout: row numbers of each block (columns B to G)
TILE_ROW, PIPE_ROW, WIN_ROW = 4, 9, 19
NEXT7_ROW, CHASE_ROW, UNPAID_ROW = 21, 34, 47
LIST_ROWS = 10  # each list shows at most this many jobs


def dashboard_cells() -> dict:
    """Every Dashboard cell as {A1: value or formula}."""
    S, V, K = jobs_col("Status"), jobs_col("Value £"), jobs_col("Scheduled")
    Q, N, P = jobs_col("Quoted on"), jobs_col("Invoiced on"), jobs_col("Paid on")
    A, C, D = jobs_col("Job ID"), jobs_col("Customer"), jobs_col("Phone")
    E, F, H = jobs_col("Address"), jobs_col("Job type"), jobs_col("Engineer")
    chase, unpaid = setting_cell("Chase quotes after (days)"), setting_cell("Flag unpaid after (days)")
    next7 = f'{K},">="&TODAY(),{K},"<"&TODAY()+7'
    month = f'{P},">="&EOMONTH(TODAY(),-1)+1,{P},"<="&EOMONTH(TODAY(),0)'
    passed = f'COUNTIFS({S},"Booked",{K},"<"&TODAY())'

    def worth(expr):
        return f'="worth "&TEXT({expr},"{MONEY[1]}")'

    tiles = [
        ("Enquiries to quote", f'=COUNTIF({S},"Enquiry")',
         f'=IF(COUNTIF({S},"Enquiry")=0,"none waiting",'
         f'"oldest: "&(TODAY()-MINIFS({jobs_col("Created")},{S},"Enquiry"))&" days")'),
        ("Quotes out", f'=COUNTIF({S},"Quoted")', worth(f'SUMIF({S},"Quoted",{V})')),
        ("Booked next 7 days", f'=COUNTIFS({S},"Booked",{next7})',
         worth(f'SUMIFS({V},{S},"Booked",{next7})')),
        ("Booked, date passed", f"={passed}",
         f'=IF({passed}=0,"all up to date","update their status")'),
        ("Unpaid invoices", f'=COUNTIF({S},"Invoiced")', worth(f'SUMIF({S},"Invoiced",{V})')),
        ("Paid this month", f'=SUMIFS({V},{S},"Paid",{month})',
         f'=COUNTIFS({S},"Paid",{month})&" jobs"'),
    ]
    cells = {
        "B1": f'={setting_cell("Business name")}&" · jobs dashboard"',
        "B2": '="As of "&TEXT(TODAY(),"dddd d mmmm yyyy")',
    }
    for col, (label, value, detail) in zip("BCDEFG", tiles):
        cells[f"{col}{TILE_ROW}"] = label
        cells[f"{col}{TILE_ROW + 1}"] = value
        cells[f"{col}{TILE_ROW + 2}"] = detail

    cells[f"B{PIPE_ROW - 1}"] = "Pipeline"
    cells.update({f"B{PIPE_ROW}": "Stage", f"C{PIPE_ROW}": "Jobs", f"D{PIPE_ROW}": "Value"})
    for r, status in enumerate(STATUSES, start=PIPE_ROW + 1):
        cells[f"B{r}"] = status
        cells[f"C{r}"] = f"=COUNTIF({S},B{r})"
        cells[f"D{r}"] = f"=SUMIF({S},B{r},{V})"
    recent = f'{Q},">="&TODAY()-90'
    cells[f"B{WIN_ROW}"] = "Quote win rate, last 90 days"
    cells[f"D{WIN_ROW}"] = (f'=IFERROR(1-COUNTIFS({recent},{S},"Lost")'
                            f'/COUNTIFS({recent},{S},"<>Quoted"),"–")')

    def job_list(row, title, headings, columns, conditions, sort_col, empty):
        cells[f"B{row}"] = title
        for col, heading in zip("BCDEFG", headings):
            cells[f"{col}{row + 1}"] = heading
        picked = "{" + ",".join(columns) + "}"
        cells[f"B{row + 2}"] = (f"=IFERROR(ARRAY_CONSTRAIN(SORT(FILTER({picked},{conditions}),"
                                f'{sort_col},TRUE),{LIST_ROWS},{len(columns)}),"{empty}")')

    job_list(NEXT7_ROW, "Booked for the next 7 days",
             ["Date", "Customer", "Address", "Job type", "Engineer"], [K, C, E, F, H],
             f'{S}="Booked",{K}>=TODAY(),{K}<TODAY()+7', 1, "Nothing booked")
    job_list(CHASE_ROW, f'="Quotes to chase (waiting "&{chase}&"+ days)"',
             ["Job", "Customer", "Phone", "Value", "Quoted on", "Days waiting"],
             [A, C, D, V, Q, f"TODAY()-{Q}"],
             f'{S}="Quoted",ISNUMBER({Q}),{Q}<=TODAY()-{chase}', 5, "Nothing to chase")
    job_list(UNPAID_ROW, "Unpaid invoices",
             ["Job", "Customer", "Phone", "Value", "Invoiced on", "Days unpaid"],
             [A, C, D, V, N, f"TODAY()-{N}"],
             f'{S}="Invoiced",ISNUMBER({N})', 5, "No unpaid invoices")
    return cells


# --- 3. Formatting, dropdowns, colour rules and the chart, as Sheets API requests ---

def rgb(hex_colour: str) -> dict:
    h = hex_colour.lstrip("#")
    return {k: int(h[i:i + 2], 16) / 255 for k, i in (("red", 0), ("green", 2), ("blue", 4))}


def style(sheet_id, a1, bg=None, fg=None, bold=None, size=None, align=None, number=None):
    """repeatCell request that sets only the formats given."""
    fmt, text = {}, {}
    if bg:
        fmt["backgroundColor"] = rgb(bg)
    if fg:
        text["foregroundColor"] = rgb(fg)
    if bold is not None:
        text["bold"] = bold
    if size:
        text["fontSize"] = size
    if text:
        fmt["textFormat"] = text
    if align:
        fmt["horizontalAlignment"] = align
    if number:
        fmt["numberFormat"] = {"type": number[0], "pattern": number[1]}
    return {"repeatCell": {"range": a1_range_to_grid_range(a1, sheet_id),
                           "cell": {"userEnteredFormat": fmt},
                           "fields": ",".join(f"userEnteredFormat.{k}" for k in fmt)}}


def widths(sheet_id, pixels: list) -> list:
    return [{"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}} for i, px in enumerate(pixels)]


def column_range(header) -> str:
    """Data rows of one Jobs column, e.g. I2:I1000."""
    col = letter(header)
    return f"{col}2:{col}{JOB_ROWS}"


def validation(sheet_id, a1, condition, message):
    return {"setDataValidation": {"range": a1_range_to_grid_range(a1, sheet_id), "rule": {
        "condition": condition, "strict": True, "showCustomUi": True, "inputMessage": message}}}


def colour_rule(sheet_id, a1, index, formula=None, text_eq=None, bg=None, fg=None, bold=None):
    if formula:
        condition = {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]}
    else:
        condition = {"type": "TEXT_EQ", "values": [{"userEnteredValue": text_eq}]}
    fmt = {}
    if bg:
        fmt["backgroundColor"] = rgb(bg)
    if fg or bold:
        fmt["textFormat"] = {k: v for k, v in (("foregroundColor", fg and rgb(fg)),
                                               ("bold", bold)) if v}
    return {"addConditionalFormatRule": {"index": index, "rule": {
        "ranges": [a1_range_to_grid_range(a1, sheet_id)],
        "booleanRule": {"condition": condition, "format": fmt}}}}


def note(sheet_id, a1, text):
    grid = a1_range_to_grid_range(a1, sheet_id)
    return {"updateCells": {"rows": [{"values": [{"note": text}]}], "fields": "note",
                            "start": {"sheetId": sheet_id, "rowIndex": grid["startRowIndex"],
                                      "columnIndex": grid["startColumnIndex"]}}}


STATUS_COLOURS = {"Enquiry": "#E2E8F0", "Quoted": "#FEF3C7", "Booked": "#DBEAFE",
                  "In progress": "#EDE9FE", "Done": "#CCFBF1", "Invoiced": "#FFEDD5",
                  "Paid": "#DCFCE7", "Lost": "#F1F5F9"}
DARK, MID, MUTED, PALE, RED_BG, RED = "#1E293B", "#475569", "#64748B", "#F1F5F9", "#FEE2E2", "#B91C1C"


def format_requests(ids: dict) -> list:
    """Formats that must exist before values are written (so phone numbers stay text)."""
    jobs, dash = ids["Jobs"], ids["Dashboard"]
    last = letter(HEADERS[-1])
    reqs = [style(jobs, f"A1:{last}1", bg=DARK, fg="#FFFFFF", bold=True)]
    for h in ["Job ID", "Created"] + list(STAMPS.values()):  # filled in by the script
        reqs.append(style(jobs, f"{letter(h)}1", bg=MID, fg="#FFFFFF", bold=True))
    for h in TEXT_COLUMNS:
        reqs.append(style(jobs, column_range(h), number=("TEXT", "@")))
    for h in DATE_COLUMNS:
        reqs.append(style(jobs, column_range(h), number=DAY if h == "Scheduled" else DATE))
    reqs.append(style(jobs, column_range("Value £"), number=MONEY))
    reqs += widths(jobs, [70, 80, 170, 105, 190, 120, 290, 80, 95, 75, 105, 90, 105, 95, 80, 220])
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": jobs, "gridProperties": {"frozenRowCount": 1,
                                                           "frozenColumnCount": 3}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}})

    # Dashboard: title, tiles, then four blocks
    reqs += [
        style(dash, "B1", bold=True, size=18, fg=DARK),
        style(dash, "B2", fg=MUTED),
        style(dash, f"B{TILE_ROW}:G{TILE_ROW + 2}", bg=PALE, align="CENTER"),
        style(dash, f"B{TILE_ROW}:G{TILE_ROW}", bold=True, size=9, fg=MID),
        style(dash, f"B{TILE_ROW + 1}:F{TILE_ROW + 1}", bold=True, size=20, fg=DARK,
              number=("NUMBER", "0")),
        style(dash, f"G{TILE_ROW + 1}", bold=True, size=20, fg=DARK, number=MONEY),
        style(dash, f"B{TILE_ROW + 2}:G{TILE_ROW + 2}", size=9, fg=MUTED),
        {"updateBorders": {"range": a1_range_to_grid_range(f"B{TILE_ROW}:G{TILE_ROW + 2}", dash),
                           "innerVertical": {"style": "SOLID_THICK", "color": rgb("#FFFFFF")}}},
        style(dash, f"D{PIPE_ROW + 1}:D{PIPE_ROW + len(STATUSES)}", number=MONEY),
        style(dash, f"B{WIN_ROW}:D{WIN_ROW}", bold=True),
        style(dash, f"D{WIN_ROW}", number=("PERCENT", "0%")),
        style(dash, f"B{NEXT7_ROW + 2}:B{NEXT7_ROW + 1 + LIST_ROWS}", number=DAY, align="LEFT"),
        # line number headings up with their numbers
        style(dash, f"C{PIPE_ROW}:C{PIPE_ROW + len(STATUSES)}", align="CENTER"),
        style(dash, f"D{PIPE_ROW}", align="RIGHT"),
    ]
    for row in (CHASE_ROW, UNPAID_ROW):
        first, end = row + 2, row + 1 + LIST_ROWS
        reqs += [style(dash, f"E{first}:E{end}", number=MONEY),
                 style(dash, f"F{first}:F{end}", number=DATE),
                 style(dash, f"G{row + 1}:G{end}", number=("NUMBER", "0"), align="CENTER"),
                 style(dash, f"E{row + 1}:F{row + 1}", align="RIGHT")]
    for row, last_col in ((PIPE_ROW - 1, "D"), (NEXT7_ROW, "F"), (CHASE_ROW, "G"),
                          (UNPAID_ROW, "G")):
        heading_row = row + 1
        reqs += [style(dash, f"B{row}", bold=True, size=12, fg=DARK),
                 style(dash, f"B{heading_row}:{last_col}{heading_row}", bold=True, size=9,
                       fg=MID, bg="#E2E8F0")]
    reqs += widths(dash, [20, 120, 175, 165, 120, 110, 95])
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": dash, "dimension": "ROWS", "startIndex": TILE_ROW,
                  "endIndex": TILE_ROW + 1},
        "properties": {"pixelSize": 42}, "fields": "pixelSize"}})
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": dash, "gridProperties": {"hideGridlines": True}},
        "fields": "gridProperties.hideGridlines"}})

    for name in ("Lists", "Settings"):
        reqs.append(style(ids[name], "A1:C1", bold=True, bg=PALE))
    reqs += widths(ids["Lists"], [110, 140, 110])
    reqs += widths(ids["Settings"], [200, 240, 420])
    return reqs


def rule_requests(ids: dict) -> list:
    """Dropdowns, colour rules, filter, notes, chart, protection and tab order."""
    jobs, dash, lists = ids["Jobs"], ids["Dashboard"], ids["Lists"]
    last = letter(HEADERS[-1])
    st, sched, q, inv = (letter(h) for h in ("Status", "Scheduled", "Quoted on", "Invoiced on"))
    chase = f'INDIRECT("{setting_cell("Chase quotes after (days)")}")'
    unpaid = f'INDIRECT("{setting_cell("Flag unpaid after (days)")}")'
    reqs = []

    for header, list_col in (("Status", "A"), ("Job type", "B"), ("Engineer", "C")):
        reqs.append(validation(jobs, column_range(header), {
            "type": "ONE_OF_RANGE",
            "values": [{"userEnteredValue": f"=Lists!${list_col}$2:${list_col}$50"}]},
            "Pick from the list. Edit the choices on the Lists tab."))
    for header in DATE_COLUMNS:
        reqs.append(validation(jobs, column_range(header), {"type": "DATE_IS_VALID"},
                               "Enter a date, e.g. 14/11/2026, or double-click for a calendar."))
    reqs.append(validation(jobs, column_range("Value £"), {
        "type": "NUMBER_GREATER_THAN_EQ", "values": [{"userEnteredValue": "0"}]},
        "Job value in pounds, numbers only."))

    # First matching rule wins, so the specific warnings come before the status colours
    rules = [
        dict(a1=f"A2:{last}{JOB_ROWS}", formula=f'=${st}2="Lost"', fg="#94A3B8"),
        dict(a1=column_range("Scheduled"), bg=RED_BG, fg=RED, bold=True,
             formula=f'=AND(${st}2="Booked",ISNUMBER(${sched}2),${sched}2<TODAY())'),
        dict(a1=column_range("Quoted on"), bg="#FEF3C7", bold=True,
             formula=f'=AND(${st}2="Quoted",ISNUMBER(${q}2),${q}2<=TODAY()-{chase})'),
        dict(a1=column_range("Invoiced on"), bg=RED_BG, fg=RED, bold=True,
             formula=f'=AND(${st}2="Invoiced",ISNUMBER(${inv}2),TODAY()-${inv}2>{unpaid})'),
    ] + [dict(a1=column_range("Status"), text_eq=s, bg=c) for s, c in STATUS_COLOURS.items()]
    reqs += [colour_rule(jobs, index=i, **r) for i, r in enumerate(rules)]

    passed_tile = f"E{TILE_ROW + 1}"  # the "Booked, date passed" tile
    unpaid_days = f"G{UNPAID_ROW + 2}:G{UNPAID_ROW + 1 + LIST_ROWS}"
    reqs += [
        colour_rule(dash, passed_tile, 0, formula=f"={passed_tile}>0", fg=RED),
        colour_rule(dash, unpaid_days, 1, bg=RED_BG, fg=RED, bold=True,
                    formula=f"=AND(ISNUMBER(G{UNPAID_ROW + 2}),G{UNPAID_ROW + 2}>{unpaid})"),
    ]

    reqs.append({"setBasicFilter": {"filter": {
        "range": a1_range_to_grid_range(f"A1:{last}{JOB_ROWS}", jobs)}}})
    reqs.append(note(jobs, "A1", "Filled in automatically when you add a job."))
    reqs.append(note(jobs, "B1", "Filled in automatically when you add a job."))
    for status, header in STAMPS.items():
        reqs.append(note(jobs, f"{letter(header)}1",
                         f"Filled in automatically when Status changes to {status}."))
    reqs.append(note(lists, "A1", "Keep the names Quoted, Done, Invoiced and Paid: they fill "
                                  "in the date columns. You can add new statuses below."))

    first, end = PIPE_ROW + 1, PIPE_ROW + len(STATUSES) - 1  # every stage except Lost
    reqs.append({"addChart": {"chart": {
        "spec": {"title": "Work value by stage", "basicChart": {
            "chartType": "BAR", "legendPosition": "NO_LEGEND", "headerCount": 0,
            "axis": [{"position": "BOTTOM_AXIS", "format": {"fontSize": 9}},
                     {"position": "LEFT_AXIS", "format": {"fontSize": 9}}],
            "domains": [{"domain": {"sourceRange": {"sources": [
                a1_range_to_grid_range(f"B{first}:B{end}", dash)]}}}],
            "series": [{"targetAxis": "BOTTOM_AXIS", "color": rgb("#2563EB"), "series": {
                "sourceRange": {"sources": [a1_range_to_grid_range(f"D{first}:D{end}", dash)]}}}],
        }},
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": dash, "rowIndex": PIPE_ROW - 2, "columnIndex": 4},
            "widthPixels": 370, "heightPixels": 245}}}}})

    reqs.append({"addProtectedRange": {"protectedRange": {
        "range": a1_range_to_grid_range(f"A1:{last}1", jobs), "warningOnly": True,
        "description": "Column names: the script finds columns by these names"}}})
    reqs.append({"addProtectedRange": {"protectedRange": {
        "range": {"sheetId": dash}, "warningOnly": True,
        "description": "Dashboard is all formulas"}}})
    for index, name in enumerate(TABS):
        reqs.append({"updateSheetProperties": {"properties": {"sheetId": ids[name],
                                                              "index": index},
                                               "fields": "index"}})
    return reqs


def value_ranges(today: date) -> list:
    jobs = demo_jobs(today)
    lists = [["Status", "Job type", "Engineer"]]
    for i in range(max(len(STATUSES), len(JOB_TYPES), len(ENGINEERS))):
        lists.append([col[i] if i < len(col) else "" for col in (STATUSES, JOB_TYPES, ENGINEERS)])
    data = [
        {"range": "Jobs!A1", "values": [HEADERS] + [[sheet_value(j[h]) for h in HEADERS]
                                                    for j in jobs]},
        {"range": "Lists!A1", "values": lists},
        {"range": "Settings!A1", "values": [["Setting", "Value", "What it does"]]
                                           + [list(s) for s in SETTINGS]},
    ]
    data += [{"range": f"Dashboard!{a1}", "values": [[v]]} for a1, v in dashboard_cells().items()]
    return data


# --- 4. Build ---

GRID = {"Dashboard": (60, 8), "Jobs": (JOB_ROWS, len(HEADERS)), "Lists": (50, 3),
        "Settings": (20, 3)}


def build(sh, today: date, reset=False) -> None:
    existing = {ws.title: ws for ws in sh.worksheets()}
    clash = [t for t in TABS if t in existing]
    if clash and not reset:
        sys.exit(f"This sheet already has: {', '.join(clash)}. Use --reset to delete and "
                 "rebuild those tabs (anything typed in them is lost).")

    # Make the new tabs before deleting the old ones: a spreadsheet must always keep one tab
    fresh = {t: sh.add_worksheet(f"_new_{t}", rows=GRID[t][0], cols=GRID[t][1]) for t in TABS}
    for t in clash:
        sh.del_worksheet(existing[t])
    for t, ws in fresh.items():
        ws.update_title(t)
    blank = existing.get("Sheet1")
    if blank and set(existing) - {"Sheet1"} <= set(TABS) and not any(map(any, blank.get_all_values())):
        sh.del_worksheet(blank)  # the empty default tab of a brand-new spreadsheet

    ids = {t: ws.id for t, ws in fresh.items()}
    sh.update_locale("en_GB")
    sh.update_timezone("Europe/London")
    sh.batch_update({"requests": format_requests(ids)})
    sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": value_ranges(today)})
    sh.batch_update({"requests": rule_requests(ids)})


def open_spreadsheet(creds: str, sheet_id: str):
    try:
        return gspread.service_account(filename=creds).open_by_key(sheet_id)
    except FileNotFoundError:
        sys.exit(f"No Google credentials at '{creds}'. See README: 'Google setup'.")
    except gspread.SpreadsheetNotFound:
        sys.exit("Sheet not found. Check --sheet-id, and share the sheet (Editor) with the "
                 "service account's client_email from the credentials JSON.")


def main():
    ap = argparse.ArgumentParser(description="Build the trades job tracker demo in a Google Sheet.")
    ap.add_argument("--sheet-id", required=True, help="the long ID in the sheet's URL")
    ap.add_argument("--creds", default=DEFAULT_CREDS, help="service account JSON key")
    ap.add_argument("--reset", action="store_true",
                    help="delete and rebuild the Dashboard, Jobs, Lists and Settings tabs")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today(),
                    help="date the demo data is built around (default: today)")
    args = ap.parse_args()

    sh = open_spreadsheet(args.creds, args.sheet_id)
    build(sh, args.today, reset=args.reset)
    print(f"Built {', '.join(TABS)} with {len(DEMO)} demo jobs in '{sh.title}'.\n"
          f"Open: https://docs.google.com/spreadsheets/d/{args.sheet_id}")


if __name__ == "__main__":
    main()
