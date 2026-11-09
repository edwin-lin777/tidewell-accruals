import sqlite3

import uvicorn
from fastapi import FastAPI

from seed import AGREEMENTS, BILLS, MESSAGES

# Data map (SQLite tables, one real row each)
# agreements:    {"Hale & Ostrow LLP": {"kind": "hourly", "amount_cents": 45000}}         # key = vendor
# bills:         {"MO-0915": {"vendor": "Mira Okafor", "booked_date": "2026-09-16", "amount_cents": 475000}}
# messages:      {"M-4": {"vendor": "Hale & Ostrow LLP", "received_at": "2026-10-07T08:50-04:00", "hours": 40.5, "signed_off": 0}}
# journal_lines: {(1, 1): {"date": "2026-09-16", "account": "6000", "debit_cents": 475000, "credit_cents": 0,
#                          "vendor": "Mira Okafor", "source": "bill MO-0915", "reverses_entry_id": None}}  # key = (entry_id, line_no)

DB_PATH = "tidewell.db"
app = FastAPI()

# ---- Endpoints (added in later steps) ----


# ---- Functions ----

# Opens the books fresh: recreates the 4 tables, copies seed.py into them, posts the two September bills.
# Params: none.
# Returns: None.
def load_seed():
    conn = sqlite3.connect(DB_PATH)
    for table in ["agreements", "bills", "messages", "journal_lines"]:
        conn.execute("DROP TABLE IF EXISTS " + table)
    conn.execute("CREATE TABLE agreements (vendor TEXT PRIMARY KEY, kind TEXT, amount_cents INTEGER)")
    conn.execute("CREATE TABLE bills (bill_id TEXT PRIMARY KEY, vendor TEXT, covers TEXT, booked_date TEXT, amount_cents INTEGER)")
    conn.execute("CREATE TABLE messages (message_id TEXT PRIMARY KEY, vendor TEXT, received_at TEXT, text TEXT, hours REAL, signed_off INTEGER)")
    conn.execute("CREATE TABLE journal_lines (entry_id INTEGER, line_no INTEGER, date TEXT, account TEXT, debit_cents INTEGER,"
                 " credit_cents INTEGER, vendor TEXT, source TEXT, reverses_entry_id INTEGER, PRIMARY KEY (entry_id, line_no))")
    for agreement in AGREEMENTS:
        conn.execute("INSERT INTO agreements VALUES (?, ?, ?)",
                     (agreement["vendor"], agreement["kind"], agreement["amount_cents"]))
    for bill in BILLS:
        conn.execute("INSERT INTO bills VALUES (?, ?, ?, ?, ?)",
                     (bill["bill_id"], bill["vendor"], bill["covers"], bill["booked_date"], bill["amount_cents"]))
    for message in MESSAGES:
        conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                     (message["message_id"], message["vendor"], message["received_at"], message["text"],
                      message["hours"], message["signed_off"]))
    conn.commit()
    conn.close()
    for bill in BILLS:
        bill_lines = [
            {"account": "6000", "debit_cents": bill["amount_cents"], "credit_cents": 0},
            {"account": "2000", "debit_cents": 0, "credit_cents": bill["amount_cents"]},
        ]
        save_entry(bill["booked_date"], bill_lines, bill["vendor"], "bill " + bill["bill_id"])


# The only door into the journal: refuses an entry whose debits don't equal its credits, else inserts its lines.
# Params: date "2026-09-16", lines [{"account": "6000", "debit_cents": 475000, "credit_cents": 0}, ...],
#         vendor "Mira Okafor", source "bill MO-0915", reverses None (or an entry_id like 3)
# Returns: the new entry_id, e.g. 1
def save_entry(date, lines, vendor, source, reverses=None):
    total_debits = 0
    total_credits = 0
    for line in lines:
        total_debits = total_debits + line["debit_cents"]
        total_credits = total_credits + line["credit_cents"]
    if total_debits != total_credits:
        raise ValueError("Unbalanced entry: debits " + str(total_debits) + " != credits " + str(total_credits))
    conn = sqlite3.connect(DB_PATH)
    highest_id = conn.execute("SELECT MAX(entry_id) FROM journal_lines").fetchone()[0]
    if highest_id is None:
        highest_id = 0
    entry_id = highest_id + 1
    line_no = 1
    for line in lines:
        conn.execute("INSERT INTO journal_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (entry_id, line_no, date, line["account"], line["debit_cents"], line["credit_cents"],
                      vendor, source, reverses))
        line_no = line_no + 1
    conn.commit()
    conn.close()
    return entry_id


if __name__ == "__main__":
    load_seed()
    uvicorn.run(app)
