# Invoice total up to 1% above received value is accepted despite “no tolerance”

**Rule broken:** `overpayment_protection`

**Severity:** High — the business can be invoiced, matched, and pay up to 1% more than the value of goods actually received on every PO (e.g. $10 on a $1,000 receipt).

**Basis:** executed

## Steps to reproduce

Replace `<VENDOR_ID>` and `<PO_ID>` with IDs from the responses.

```bash
curl -s -X POST localhost:8000/admin/reset

curl -s -X POST localhost:8000/vendors -H 'content-type: application/json' \
  -d '{"name":"curl-repro-overpay"}'

curl -s -X POST localhost:8000/purchase-orders -H 'content-type: application/json' \
  -d '{"vendor_id":"<VENDOR_ID>","line_items":[{"sku":"LUM-2X4-8","quantity":1,"unit_price":1000.0}]}'

curl -s -X POST localhost:8000/purchase-orders/<PO_ID>/submit

curl -s -X POST localhost:8000/purchase-orders/<PO_ID>/receive -H 'content-type: application/json' \
  -d '{"items":[{"sku":"LUM-2X4-8","quantity":1}]}'

curl -s -X POST localhost:8000/invoices -H 'content-type: application/json' \
  -d '{"po_id":"<PO_ID>","invoice_number":"INV-OVERPAY-REPRO","line_items":[{"sku":"LUM-2X4-8","quantity":1,"unit_price":1010.0}]}'
```

Executed example (2026-10-23): vendor `vnd-81f92b69`, PO `po-4337261a`, `received_value` 1000 after receive.

## Expected

From `docs/API.md` business rules table, rule 3:

> Everything invoiced on a PO never exceeds what was received: not per line quantity, and not in total value. **There is no tolerance.**

## Actual

HTTP **201** with body:

```json
{
  "id": "inv-f58e3147",
  "po_id": "po-4337261a",
  "vendor_id": "vnd-81f92b69",
  "invoice_number": "INV-OVERPAY-REPRO",
  "status": "received",
  "line_items": [{ "sku": "LUM-2X4-8", "quantity": 1, "unit_price": 1010 }],
  "total_amount": 1010,
  "matched": false,
  "partial_receipt": null
}
```

On fresh data, an invoice at **1011.00** (same qty 1, received value 1000) returns **400** with `"rule": "overpayment_protection"`, so the API enforces a hidden ceiling of about **1%** above received value, not zero tolerance.

## What this proves

Documented zero-tolerance overpayment protection is not implemented for **invoice line unit price / total value** when quantity matches what was received.

## What this does not prove

- Whether an accepted over-threshold invoice can complete match and approve (QA run showed it can on prior data; not re-run in this curl sequence).
- Behavior for cumulative overpayment across **multiple** invoices (separate attacks reported HELD for value stacking beyond 1%).
- Per-line **quantity** over-invoicing (existing API tests expect 400; still held).

## Open question

Should half-cent rounding on unit prices interact with the value cap, or is strict decimal comparison intended everywhere?
