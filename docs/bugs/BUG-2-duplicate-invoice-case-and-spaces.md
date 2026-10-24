# Duplicate invoice numbers differ only by case or spaces are accepted

**Rule broken:** `duplicate_invoice_detection`

**Severity:** High — the same vendor bill can be recorded multiple times (e.g. `INV-7`, `inv-7`, and ` INV-7 ` all at $22.40 → $67.20 liability for one $22.40 bill) until cumulative invoicing hits other limits.

**Basis:** executed

## Steps to reproduce

Replace `<VENDOR_ID>` and `<PO_ID>` with IDs from the responses.

```bash
curl -s -X POST localhost:8000/admin/reset

curl -s -X POST localhost:8000/vendors -H 'content-type: application/json' \
  -d '{"name":"curl-repro-dup"}'

curl -s -X POST localhost:8000/purchase-orders -H 'content-type: application/json' \
  -d '{"vendor_id":"<VENDOR_ID>","line_items":[{"sku":"PLY-12-4X8","quantity":4,"unit_price":22.4}]}'

curl -s -X POST localhost:8000/purchase-orders/<PO_ID>/submit

curl -s -X POST localhost:8000/purchase-orders/<PO_ID>/receive -H 'content-type: application/json' \
  -d '{"items":[{"sku":"PLY-12-4X8","quantity":4}]}'

curl -s -X POST localhost:8000/invoices -H 'content-type: application/json' \
  -d '{"po_id":"<PO_ID>","invoice_number":"INV-7","line_items":[{"sku":"PLY-12-4X8","quantity":1,"unit_price":22.4}]}'

curl -s -X POST localhost:8000/invoices -H 'content-type: application/json' \
  -d '{"po_id":"<PO_ID>","invoice_number":"inv-7","line_items":[{"sku":"PLY-12-4X8","quantity":1,"unit_price":22.4}]}'

curl -s -X POST localhost:8000/invoices -H 'content-type: application/json' \
  -d '{"po_id":"<PO_ID>","invoice_number":" INV-7 ","line_items":[{"sku":"PLY-12-4X8","quantity":1,"unit_price":22.4}]}'
```

Executed example (2026-10-23): vendor `vnd-081cb798`, PO `po-42330cbf`.

## Expected

From `docs/API.md` business rules table, rule 6:

> A vendor cannot submit the same invoice number twice. Numbers are compared ignoring upper or lower case and surrounding spaces, so `INV-7`, `inv-7` and ` INV-7 ` are the same number.

Second and third `POST /invoices` should return **400** with `"rule": "duplicate_invoice_detection"`.

## Actual

First request: **201**, `"invoice_number": "INV-7"`, `"total_amount": 22.4`.

Second request (`inv-7`): **201**:

```json
{
  "id": "inv-69981d5c",
  "po_id": "po-42330cbf",
  "vendor_id": "vnd-081cb798",
  "invoice_number": "inv-7",
  "status": "received",
  "line_items": [{ "sku": "PLY-12-4X8", "quantity": 1, "unit_price": 22.4 }],
  "total_amount": 22.4,
  "matched": false,
  "partial_receipt": null
}
```

Third request (` INV-7 `): **201**, stored `"invoice_number": " INV-7 "` (spaces preserved).

An exact repeat of `INV-7` on the same vendor still returns **400** `duplicate_invoice_detection` (held in adversarial run).

## What this proves

Normalization for case and surrounding spaces is not applied when detecting duplicate invoice numbers for a vendor.

## What this does not prove

- Whether duplicate **case/spaced** copies can all be matched and approved (not exercised in this curl sequence).
- Cross-vendor duplicate numbers (documented as allowed; adversarial run HELD).

## Open question

Should normalized invoice numbers be stored canonically (e.g. trimmed, case-folded) in responses, or only used for equality checks?
