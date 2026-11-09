import sqlite3
from datetime import datetime

import uvicorn
from fastapi import FastAPI

from seed import AGREEMENTS, BILLS, MESSAGES

# Data map (SQLite tables, one real row each)
# agreements:    {"Hale & Ostrow LLP": {"kind": "hourly", "amount_cents": 45000}}         # key = vendor
# bills:         {"MO-0915": {"vendor": "Mira Okafor", "booked_date": "2026-09-16", "amount_cents": 475000}}
# messages:      {"M-4": {"vendor": "Hale & Ostrow LLP", "received_at": "2026-10-07T08:50-04:00", "hours": 40.5, "signed_off": 0}}
# journal_lines: {(1, 1): {"date": "2026-09-16", "account": "6000", "debit_cents": 475000, "credit_cents": 0,
#                          "vendor": "Mira Okafor", "source": "bill MO-0915", "reverses_entry_id": None}}  # key = (entry_id, line_no)
# proposals (in memory, from propose): [{"vendor": "Mira Okafor", "status": "accrue", "amount_cents": 589000, "sources": ["M-1", "MO-0915"]}]
# net_by_account (in memory, in trial_balance): {"6000": 6836500, "2100": -5411500}  # key = account, value = debits - credits

DB_PATH = "tidewell.db"
app = FastAPI()

# ---- Endpoints ----

@app.get("/periods/2026-09/accruals")
def get_accruals(as_of: str):
    return propose(as_of)


@app.post("/accruals/{vendor}/approve")
def post_approve(vendor: str, as_of: str):
    return approve(vendor, as_of)


@app.get("/journal")
def get_journal():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT * FROM journal_lines ORDER BY entry_id, line_no").fetchall()
    conn.close()
    journal = []
    for row in rows:
        journal.append({"entry_id": row[0], "line_no": row[1], "date": row[2], "account": row[3],
                        "debit_cents": row[4], "credit_cents": row[5], "vendor": row[6],
                        "source": row[7], "reverses_entry_id": row[8]})
    return journal


@app.get("/trial-balance")
def get_trial_balance(date: str):
    return trial_balance(date)


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


# One proposal per vendor: accrue (amount + sources), no_accrual (reason), or review (what's missing).
# Params: as_of "2026-10-07T12:00-04:00"
# Returns: [{"vendor": "Mira Okafor", "status": "accrue", "amount_cents": 589000, "sources": ["M-1", "MO-0915"]}, ...]
def propose(as_of):
    conn = sqlite3.connect(DB_PATH)
    agreement_rows = conn.execute("SELECT vendor, kind, amount_cents FROM agreements").fetchall()
    conn.close()
    proposals = []
    for row in agreement_rows:
        agreement = {"vendor": row[0], "kind": row[1], "amount_cents": row[2]}
        vendor = agreement["vendor"]
        billed = already_billed_cents(vendor)
        if agreement["kind"] == "fixed" and billed["total_cents"] >= agreement["amount_cents"]:
            proposals.append({"vendor": vendor, "status": "no_accrual", "sources": billed["bill_ids"],
                              "reason": "fixed fee already booked in September bills"})
            continue
        message = latest_message(vendor, as_of)
        work_cents = september_work_cents(agreement, message)
        if work_cents is None:
            if message is None:
                reason = "no message from vendor by " + as_of
            elif agreement["kind"] == "hourly":
                reason = "latest message " + message["message_id"] + " has no hours"
            else:
                reason = "latest message " + message["message_id"] + " has no sign-off"
            proposals.append({"vendor": vendor, "status": "review", "reason": reason})
            continue
        sources = [message["message_id"]]
        for bill_id in billed["bill_ids"]:
            sources.append(bill_id)
        accrual_cents = work_cents - billed["total_cents"]
        if accrual_cents > 0:
            proposals.append({"vendor": vendor, "status": "accrue", "amount_cents": accrual_cents, "sources": sources})
        else:
            proposals.append({"vendor": vendor, "status": "no_accrual", "sources": sources,
                              "reason": "September bills already cover the work"})
    return proposals


# Finds the newest message from this vendor that had arrived by as_of. Anything later is invisible.
# Params: vendor "Hale & Ostrow LLP", as_of "2026-10-05T12:00-04:00"
# Returns: {"message_id": "M-3", "received_at": "2026-10-05T10:31-04:00", "hours": 38.5, "signed_off": False}, or None
def latest_message(vendor, as_of):
    as_of_time = datetime.fromisoformat(as_of)
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT message_id, received_at, hours, signed_off FROM messages WHERE vendor = ?",
                        (vendor,)).fetchall()
    conn.close()
    newest = None
    newest_time = None
    for row in rows:
        received_time = datetime.fromisoformat(row[1])
        if received_time > as_of_time:
            continue
        if newest_time is None or received_time > newest_time:
            newest_time = received_time
            newest = {"message_id": row[0], "received_at": row[1], "hours": row[2], "signed_off": row[3] == 1}
    return newest


# Works out what the vendor's September work cost, from its agreement and its latest message. Pure math, no database.
# Params: agreement {"vendor": "Hale & Ostrow LLP", "kind": "hourly", "amount_cents": 45000},
#         message {"message_id": "M-4", "hours": 40.5, "signed_off": False, ...} or None
# Returns: 1822500 (cents), or None if there's nothing to go on
def september_work_cents(agreement, message):
    if message is None:
        return None
    if agreement["kind"] == "fixed":
        if message["signed_off"]:
            return agreement["amount_cents"]
        return None
    if agreement["kind"] == "hourly":
        if message["hours"] is None:
            return None
        return round(message["hours"] * agreement["amount_cents"])
    return None


# Adds up the September bills already booked for this vendor, and remembers which bills they were.
# Params: vendor "Mira Okafor"
# Returns: {"total_cents": 475000, "bill_ids": ["MO-0915"]}  (or {"total_cents": 0, "bill_ids": []})
def already_billed_cents(vendor):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT bill_id, amount_cents FROM bills WHERE vendor = ?", (vendor,)).fetchall()
    conn.close()
    total_cents = 0
    bill_ids = []
    for row in rows:
        total_cents = total_cents + row[1]
        bill_ids.append(row[0])
    return {"total_cents": total_cents, "bill_ids": bill_ids}


# Re-runs propose for one vendor; if it says accrue and nothing is posted yet, posts the Sep 30 accrual and Oct 1 reversal.
# Params: vendor "Brightline Consulting", as_of "2026-10-07T12:00-04:00"
# Returns: {"status": "posted", "accrual_entry_id": 3, "reversal_entry_id": 4, "amount_cents": 3000000}
#          or {"status": "already_posted", "entry_id": 3} or {"status": "not_posted", "reason": "..."}
def approve(vendor, as_of):
    proposal = None
    for candidate in propose(as_of):
        if candidate["vendor"] == vendor:
            proposal = candidate
    if proposal is None:
        return {"status": "not_posted", "reason": "unknown vendor"}
    if proposal["status"] != "accrue":
        return {"status": "not_posted", "reason": proposal["status"] + ": " + proposal["reason"]}
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute("SELECT entry_id FROM journal_lines WHERE vendor = ? AND date = '2026-09-30'"
                            " AND source LIKE 'accrual%'", (vendor,)).fetchone()
    conn.close()
    if existing is not None:
        return {"status": "already_posted", "entry_id": existing[0]}
    amount_cents = proposal["amount_cents"]
    records = ", ".join(proposal["sources"])
    accrual_lines = [
        {"account": "6000", "debit_cents": amount_cents, "credit_cents": 0},
        {"account": "2100", "debit_cents": 0, "credit_cents": amount_cents},
    ]
    reversal_lines = [
        {"account": "2100", "debit_cents": amount_cents, "credit_cents": 0},
        {"account": "6000", "debit_cents": 0, "credit_cents": amount_cents},
    ]
    accrual_id = save_entry("2026-09-30", accrual_lines, vendor, "accrual " + records)
    reversal_id = save_entry("2026-10-01", reversal_lines, vendor, "reversal " + records, accrual_id)
    return {"status": "posted", "accrual_entry_id": accrual_id, "reversal_entry_id": reversal_id,
            "amount_cents": amount_cents}


# Every account's balance on a date: adds up all journal lines up to that date, shows each net as a debit or a credit.
# Params: date "2026-09-30"
# Returns: {"date": "2026-09-30", "accounts": [{"account": "2000", "debit_cents": 0, "credit_cents": 1425000}, ...],
#           "total_debit_cents": 6836500, "total_credit_cents": 6836500, "balanced": True}
def trial_balance(date):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT account, debit_cents, credit_cents FROM journal_lines WHERE date <= ?",
                        (date,)).fetchall()
    conn.close()
    net_by_account = {}
    for row in rows:
        account = row[0]
        if account not in net_by_account:
            net_by_account[account] = 0
        net_by_account[account] = net_by_account[account] + row[1] - row[2]
    accounts = []
    total_debit_cents = 0
    total_credit_cents = 0
    for account in sorted(net_by_account):
        net = net_by_account[account]
        if net >= 0:
            accounts.append({"account": account, "debit_cents": net, "credit_cents": 0})
            total_debit_cents = total_debit_cents + net
        else:
            accounts.append({"account": account, "debit_cents": 0, "credit_cents": -net})
            total_credit_cents = total_credit_cents - net
    return {"date": date, "accounts": accounts, "total_debit_cents": total_debit_cents,
            "total_credit_cents": total_credit_cents, "balanced": total_debit_cents == total_credit_cents}


if __name__ == "__main__":
    load_seed()
    uvicorn.run(app)
