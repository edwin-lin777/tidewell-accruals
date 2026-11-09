# September data for Tidewell Labs, typed in from page 3 of the brief.
# Money is in integer cents. hours and signed_off were read from each message by hand.

AGREEMENTS = [
    {"vendor": "Brightline Consulting", "kind": "fixed", "amount_cents": 3000000},
    {"vendor": "Hale & Ostrow LLP", "kind": "hourly", "amount_cents": 45000},
    {"vendor": "Mira Okafor", "kind": "hourly", "amount_cents": 9500},
    {"vendor": "Copperline Security", "kind": "fixed", "amount_cents": 950000},
]

BILLS = [
    {"bill_id": "MO-0915", "vendor": "Mira Okafor", "covers": "Sep 1 to 15",
     "booked_date": "2026-09-16", "amount_cents": 475000},
    {"bill_id": "CS-4471", "vendor": "Copperline Security", "covers": "September",
     "booked_date": "2026-09-30", "amount_cents": 950000},
]

MESSAGES = [
    {"message_id": "M-1", "vendor": "Mira Okafor", "received_at": "2026-10-01T17:40-04:00",
     "text": "September 1 to 30: 112.0 hours on the scheduling API. Approved by Dana Whitfield.",
     "hours": 112.0, "signed_off": False},
    {"message_id": "M-2", "vendor": "Brightline Consulting", "received_at": "2026-10-03T14:20-04:00",
     "text": "Hi Dana, your team signed off the September milestone on September 29. We'll invoice the $30,000 mid-October.",
     "hours": None, "signed_off": True},
    {"message_id": "M-3", "vendor": "Hale & Ostrow LLP", "received_at": "2026-10-05T10:31-04:00",
     "text": "Dana, for September we recorded 38.5 hours on the vendor contract review. Invoice goes out around the 20th as usual.",
     "hours": 38.5, "signed_off": False},
    {"message_id": "M-4", "vendor": "Hale & Ostrow LLP", "received_at": "2026-10-07T08:50-04:00",
     "text": "Correction to my note on Monday: September was 40.5 hours, not 38.5. Sorry about that.",
     "hours": 40.5, "signed_off": False},
]
