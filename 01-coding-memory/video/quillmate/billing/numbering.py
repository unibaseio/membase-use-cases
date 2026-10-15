"""Invoice numbers for Quillmate, the invoicing app our field teams run on tablets."""


def next_invoice_number(db) -> str:
    # The highest number in the local database, plus one.
    last = db.max("invoices.number") or 0
    return f"{last + 1:06d}"
