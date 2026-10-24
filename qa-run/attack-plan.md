# P2P adversary attack plan

Base URL: `http://localhost:8000`. Sources: `docs/API.md` (Business rules) and `GET /openapi.json`. Live catalog checked before any attack: vendors `vnd-001` (active), `vnd-002` Old Quarry Materials (inactive), SKUs `LUM-2X4-8` (4.75), `PLY-12-4X8` (22.40), `CEM-30KG` (11.90), `REB-10MM-6` (18.25), `SCR-DECK-1LB` (9.99).

Every attack uses a new vendor (unique name) and a new PO, then `POST /admin/reset`, except where one attack needs several steps on the same PO or vendor. The four required attacks run first.

Money is dollars rounded to cents. Quantity must be greater than 0 and at most 10,000. Unit price is from 0 to 100,000. There is no overpayment tolerance.

## 1. Required four

### 1.1 Approve an invoice that was never matched — `three_way_match_gate`

- Attack: `approve unmatched invoice`
- Setup: active vendor, draft PO (`LUM-2X4-8` qty 2 @ 4.75), submit, receive 2, create invoice for the same lines. Do **not** call match.
- Decisive: `POST /invoices/{id}/approve`
- Expected: `docs/API.md` → Business rules → `three_way_match_gate`: an invoice cannot be approved until it passed the 3-way match. 400 with that `rule`.

### 1.2 Receive more than was ordered — `receive_quantity_limit`

- Attack: `receive more than ordered`
- Setup: active vendor, PO (`CEM-30KG` qty 5 @ 11.90), submit.
- Decisive: `POST /purchase-orders/{id}/receive` with quantity 8.
- Expected: `receive_quantity_limit`: received quantity never exceeds ordered quantity. 400 with that `rule`.

### 1.3 Invoice more than the received value — `overpayment_protection`

- Attack: `invoice value above received`
- Setup: active vendor, PO (`REB-10MM-6` qty 10 @ 10.00), submit, receive 4 (received value 40.00).
- Decisive: `POST /invoices` for qty 4 @ 25.00 (invoice value 100.00, line quantity not above received).
- Expected: `overpayment_protection`: everything invoiced never exceeds what was received, in total value, with no tolerance. 400 with that `rule`.

### 1.4 Purchase order for an inactive vendor — `inactive_vendor_gate`

- Attack: `po for seed inactive vendor`
- Setup: none beyond reset. Use seed `vnd-002`.
- Decisive: `POST /purchase-orders` with `vendor_id` `vnd-002`.
- Expected: `inactive_vendor_gate`: no purchase order for an inactive vendor. 400 with that `rule`.

## 2. Per-rule coverage

### `inactive_vendor_gate`

1. Required attack 1.4 (seed `vnd-002`).
2. Attack: `po for created inactive vendor`. `POST /vendors` with `active: false`, then `POST /purchase-orders` for that id. Expected: 400 `inactive_vendor_gate`.

### `receive_quantity_limit`

1. Required attack 1.2 (single delivery well over).
2. Attack: `receive one unit over`. PO qty 10, receive 11. Expected: 400 `receive_quantity_limit`.
3. Attack: `cumulative receipts exceed ordered`. PO qty 10, receive 6 (accepted), then receive 5. Expected: second call 400 `receive_quantity_limit` (limit is across all deliveries).
4. Attack: `receive zero and negative quantity`. Receive `0` and `-1` on a submitted PO. Expected: 400 `validation_error` (`docs/API.md` → Purchase orders: quantity greater than 0; OpenAPI `exclusiveMinimum: 0`). Accepting either is a breach of that limit.

### `overpayment_protection`

1. Required attack 1.3 (higher unit price, same quantity).
2. Attack: `invoice one cent over received value`. Receive qty 1 @ 10.00, invoice qty 1 @ 10.01. Expected: 400 `overpayment_protection` (no tolerance).
3. Attack: `invoice one percent over received value`. Receive qty 10 @ 10.00 (100.00), invoice qty 10 @ 10.10 (101.00). Expected: 400 `overpayment_protection`.
4. Attack: `line quantity over while total under`. Two lines: `LUM-2X4-8` qty 10 @ 1.00 and `PLY-12-4X8` qty 10 @ 10.00. Receive both in full (received value 110.00). Invoice `LUM-2X4-8` qty 11 @ 1.00 and `PLY-12-4X8` qty 9 @ 10.00 (invoice total 101.00). Expected: 400 `overpayment_protection` because per-line quantity exceeds what was received even though the invoice total is under the received value.
5. Attack: `two invoices combined exceed received`. Receive qty 10 @ 10.00 (100.00). First invoice qty 6 @ 10.00 (60.00) accepted. Second invoice qty 5 @ 10.00 (50.00) would make 110.00 invoiced. Expected: 400 `overpayment_protection` on the second invoice.
6. Attack: `invoice before any receipt`. Submit, do not receive, invoice the ordered lines. Expected: 400 `overpayment_protection` (invoiced value exceeds received value 0).
7. Attack: `underpayment is allowed`. Receive qty 1 @ 10.00, invoice qty 1 @ 9.99. Expected: 201. The rule forbids exceeding received value, not billing less.
8. Attack: `lower quantity higher price same total`. Receive qty 10 @ 5.00 (50.00), invoice qty 5 @ 10.00 (50.00). Expected: 201. Line quantity is under received and total value is equal. Docs do not require the invoice unit price to match the PO.
9. Attack: `prices offset to the same total`. Receive two lines qty 1 @ 10.00 each (20.00). Invoice one line @ 10.01 and the other @ 9.99 (total 20.00). Expected: 201. Per-line quantities do not exceed received, and total value does not exceed received value.
10. Attack: `tenth-cent prices that sum cleanly`. PO and invoice: qty 1 @ 0.10 and qty 1 @ 0.20, fully received. Expected: 201 and `total_amount` 0.30 (cents). A rejection, or a total that is not 0.30, breaks the money promise (`docs/API.md` → Basics → Money, and `overpayment_protection`).

### `three_way_match_gate`

1. Required attack 1.1.

### `partial_receipt_flag`

1. Attack: `partial lines then match`. Multi-line PO: `LUM-2X4-8` qty 10 @ 4.75, `CEM-30KG` qty 4 @ 11.90, `SCR-DECK-1LB` qty 5 @ 9.99. Receive the short first line only (`LUM-2X4-8` qty 3), then a partial of the last line only (`SCR-DECK-1LB` qty 1). Leave `CEM-30KG` at 0. Invoice only the received quantities and prices. Match. Expected: `partial_receipt: true` (`docs/API.md` → `partial_receipt_flag`: true when any PO line is not fully received). False, or a match that pretends the PO is complete, is a breach. Also confirm `GET /invoices/{id}` keeps the same flag.
2. Attack: `full receipt flag is false`. Receive every line in full, invoice those lines, match. Expected: `partial_receipt: false`.

### `duplicate_invoice_detection`

1. Attack: `exact duplicate invoice number`. Two invoices, same vendor, same `invoice_number`. Expected: second is 400 `duplicate_invoice_detection`.
2. Attack: `invoice number differs only by case`. `INV-7` then `inv-7`. Expected: 400 `duplicate_invoice_detection`.
3. Attack: `invoice number differs only by surrounding spaces`. `INV-7` then ` INV-7 `. Expected: 400 `duplicate_invoice_detection`.
4. Attack: `same number on two vendors`. Same invoice number on two different vendors. Expected: both 201. The rule is per vendor, not global.

### `gl_balance`

1. Attack: `approval ledger balances`. Full receive, invoice, match, approve of qty 10 @ 4.75 (47.50). Expected: `gl_entry.balanced` true and the sum of debit amounts equals the sum of credit amounts equals the invoice total (`gl_balance`).
2. Attack: `ledger on tenth-cent lines`. Approve an invoice of qty 1 @ 0.10 plus qty 1 @ 0.20. Expected: balanced true, debits and credits each 0.30.
3. Attack: `half-cent unit price`. PO, receipt, and invoice qty 1 @ 1.005. Expected: amounts rounded to cents, and the posted entry balanced with debits equal to credits. An unbalanced entry is a breach. If the documents never say how a half-cent is rounded, record the rounding choice as a question only when the entry is still balanced and consistent.

### `invoice_line_validation`

1. Attack: `sku not on the po`. PO has only `LUM-2X4-8`. Invoice that PO with `CEM-30KG`. Expected: 400 `invoice_line_validation`.
2. Attack: `duplicate sku on invoice`. Invoice two lines with the same SKU. Expected: 400 `invoice_line_validation` (each SKU appears once).

### `duplicate_approval`

1. Attack: `approve twice`. Match, approve, approve again. Expected: second call 400 `duplicate_approval`.

### `workflow_gate`

1. Attack: `submit twice`. Submit a draft, then submit again. Expected: 400 `workflow_gate` (submit only a draft).
2. Attack: `receive on draft`. Receive before submit. Expected: 400 `workflow_gate` (receive only on a submitted PO).
3. Attack: `invoice on draft`. Invoice a draft PO. Expected: 400 `workflow_gate` (invoice only a submitted or closed PO).
4. Attack: `match an approved invoice`. Approve, then match again. Expected: 400 `workflow_gate` (never match an approved invoice again).
5. Attack: `invoice a closed po`. Fully receive so the PO closes, then invoice. Expected: 201. Closed POs may be invoiced. A `workflow_gate` rejection is a breach.

### `vendor_exposure_math`

1. Attack: `exposure equals one approved invoice`. After approve, `vendor_exposure` on the approve response and `GET /vendors/{id}/exposure` `open_ap_liability` both equal that invoice's `total_amount`. Expected: they match (`vendor_exposure_math`).
2. Attack: `exposure sums two approved invoices`. Two POs for the same vendor, both fully received, invoiced, matched, and approved (totals chosen so the sum is not equal to either invoice). Expected: `open_ap_liability` equals the sum of the two `total_amount` values, and `approved_invoices` lists both.

## Out of named-rule scope (still try)

- Attack: `duplicate sku on purchase order`. Docs say each SKU may appear once per PO, but that sentence is not one of the 11 rule names. Expected rejection. If the body is 400 `validation_error`, that matches the Errors table for an invalid body. If it is accepted, the written PO rule failed.
- Attack: `receive sku not on the po`. Receive endpoint: every SKU must be on the PO. Same judgement as above.

## 3. Follow-up after the first overpayment accepts

The one-cent and one-percent invoices were accepted. These extra calls, each on a fresh vendor and PO, measure the gap. Quantity on the invoice equals quantity received, so only total value is in play.

- Exactly 1% over: 101.00 on 100.00, 10.10 on 10.00, 1010.00 on 1000.00.
- One cent over a small and a large receipt: 10.01 on 10.00 (planned attack), 100.01 on 100.00, 1001.00 on 1000.00.
- Just past 1%: 10.11 on 10.00, 101.01 on 100.00, 1011.00 on 1000.00.
- Well past 1%: 102, 105, 110, 120, and 150 on 100; 11 on 10; 1100 on 1000.
- Two invoices whose quantities together equal the receipt but whose dollars do not: 50.00 then 60.00 against received value 100.00.

Expected for every one of these: `overpayment_protection` refuses any amount over the received value. There is no tolerance.
