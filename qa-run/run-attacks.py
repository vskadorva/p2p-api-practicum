#!/usr/bin/env python3
"""Run adversary attacks. Every HTTP call is a curl subprocess."""

import json
import subprocess

BASE = "http://localhost:8000"
results = []


def curl(method, path, body=None):
    cmd = ["curl", "-sS", "-w", "\n%{http_code}", "-X", method, BASE + path]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(body)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"curl {method} {path} failed: {proc.stderr}")
    text = proc.stdout
    payload, status_s = text.rsplit("\n", 1)
    status = int(status_s)
    try:
        parsed = json.loads(payload) if payload else None
    except json.JSONDecodeError:
        parsed = payload
    return status, parsed


def reset():
    status, body = curl("POST", "/admin/reset")
    if status != 200 or not isinstance(body, dict) or body.get("status") != "reset":
        raise RuntimeError(f"reset failed: {status} {body}")


def vendor(name, active=True):
    status, body = curl("POST", "/vendors", {"name": name, "active": active})
    if status != 201 or not isinstance(body, dict) or "id" not in body:
        raise RuntimeError(f"vendor {name} failed: {status} {body}")
    return body["id"], status, body


def create_po(vendor_id, lines):
    body = {"vendor_id": vendor_id, "line_items": lines}
    return curl("POST", "/purchase-orders", body), body


def submit(po_id):
    return curl("POST", f"/purchase-orders/{po_id}/submit")


def receive(po_id, items):
    body = {"items": items}
    return curl("POST", f"/purchase-orders/{po_id}/receive", body), body


def create_invoice(po_id, number, lines):
    body = {"po_id": po_id, "invoice_number": number, "line_items": lines}
    return curl("POST", "/invoices", body), body


def match(inv_id):
    return curl("POST", f"/invoices/{inv_id}/match")


def approve(inv_id):
    return curl("POST", f"/invoices/{inv_id}/approve")


def get_po(po_id):
    return curl("GET", f"/purchase-orders/{po_id}")


def get_invoice(inv_id):
    return curl("GET", f"/invoices/{inv_id}")


def exposure(vendor_id):
    return curl("GET", f"/vendors/{vendor_id}/exposure")


def record(rule, attack, method, path, req_body, status, resp, setup=None):
    item = {
        "rule": rule,
        "attack": attack,
        "request": {"method": method, "path": path, "body": req_body},
        "response": {"status": status, "body": resp},
    }
    if setup is not None:
        item["setup"] = setup
    results.append(item)
    print(f"{len(results):02d} {rule} | {attack} -> {status} {json.dumps(resp)[:240]}")


def line(sku, qty, price):
    return {"sku": sku, "quantity": qty, "unit_price": price}


def item(sku, qty):
    return {"sku": sku, "quantity": qty}


def ready_po(name, lines, active=True):
    reset()
    vid, _, vbody = vendor(name, active)
    (st, pobody), poreq = create_po(vid, lines)
    if st != 201:
        raise RuntimeError(f"po failed {st} {pobody}")
    sst, sbody = submit(pobody["id"])
    if sst != 200:
        raise RuntimeError(f"submit failed {sst} {sbody}")
    return vid, pobody["id"], {"vendor": vbody, "po": pobody, "submit": sbody}


def run():
    # 1. three_way_match_gate — approve unmatched
    try:
        vid, po_id, setup = ready_po("Adv Match Gate", [line("LUM-2X4-8", 2, 4.75)])
        (rst, rbody), _ = receive(po_id, [item("LUM-2X4-8", 2)])
        if rst != 200:
            raise RuntimeError(f"receive {rst} {rbody}")
        (ist, ibody), ireq = create_invoice(po_id, "INV-UNMATCHED", [line("LUM-2X4-8", 2, 4.75)])
        if ist != 201:
            raise RuntimeError(f"invoice {ist} {ibody}")
        ast, abody = approve(ibody["id"])
        record(
            "three_way_match_gate",
            "approve unmatched invoice",
            "POST",
            f"/invoices/{ibody['id']}/approve",
            None,
            ast,
            abody,
            {"receive_status": rst, "invoice_status": ibody.get("status"), "matched": ibody.get("matched")},
        )
    except Exception as exc:
        record("three_way_match_gate", "approve unmatched invoice", "POST", "/invoices/{id}/approve", None, 0, {"error": str(exc)})

    # 2. receive more than ordered
    try:
        vid, po_id, setup = ready_po("Adv Receive Over", [line("CEM-30KG", 5, 11.90)])
        (st, body), req = receive(po_id, [item("CEM-30KG", 8)])
        record(
            "receive_quantity_limit",
            "receive more than ordered",
            "POST",
            f"/purchase-orders/{po_id}/receive",
            req,
            st,
            body,
        )
    except Exception as exc:
        record("receive_quantity_limit", "receive more than ordered", "POST", "/receive", None, 0, {"error": str(exc)})

    # 3. invoice value above received
    try:
        vid, po_id, setup = ready_po("Adv Overpay Value", [line("REB-10MM-6", 10, 10.00)])
        (rst, rbody), rreq = receive(po_id, [item("REB-10MM-6", 4)])
        (st, body), req = create_invoice(po_id, "INV-OVER-VALUE", [line("REB-10MM-6", 4, 25.00)])
        record(
            "overpayment_protection",
            "invoice value above received",
            "POST",
            "/invoices",
            req,
            st,
            body,
            {"receive_status": rst, "receive": rbody},
        )
    except Exception as exc:
        record("overpayment_protection", "invoice value above received", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 4. inactive seed vendor
    try:
        reset()
        req = {"vendor_id": "vnd-002", "line_items": [line("LUM-2X4-8", 1, 4.75)]}
        st, body = curl("POST", "/purchase-orders", req)
        record(
            "inactive_vendor_gate",
            "po for seed inactive vendor",
            "POST",
            "/purchase-orders",
            req,
            st,
            body,
        )
    except Exception as exc:
        record("inactive_vendor_gate", "po for seed inactive vendor", "POST", "/purchase-orders", None, 0, {"error": str(exc)})

    # 5. created inactive vendor
    try:
        reset()
        vid, vst, vbody = vendor("Adv Inactive Created", active=False)
        req = {"vendor_id": vid, "line_items": [line("LUM-2X4-8", 1, 4.75)]}
        st, body = curl("POST", "/purchase-orders", req)
        record(
            "inactive_vendor_gate",
            "po for created inactive vendor",
            "POST",
            "/purchase-orders",
            req,
            st,
            body,
            {"vendor_create": vbody, "vendor_status": vst},
        )
    except Exception as exc:
        record("inactive_vendor_gate", "po for created inactive vendor", "POST", "/purchase-orders", None, 0, {"error": str(exc)})

    # 6. one unit over
    try:
        vid, po_id, setup = ready_po("Adv One Unit Over", [line("LUM-2X4-8", 10, 4.75)])
        (st, body), req = receive(po_id, [item("LUM-2X4-8", 11)])
        record("receive_quantity_limit", "receive one unit over", "POST", f"/purchase-orders/{po_id}/receive", req, st, body)
    except Exception as exc:
        record("receive_quantity_limit", "receive one unit over", "POST", "/receive", None, 0, {"error": str(exc)})

    # 7. cumulative
    try:
        vid, po_id, setup = ready_po("Adv Cumulative Receive", [line("SCR-DECK-1LB", 10, 9.99)])
        (st1, body1), req1 = receive(po_id, [item("SCR-DECK-1LB", 6)])
        (st2, body2), req2 = receive(po_id, [item("SCR-DECK-1LB", 5)])
        record(
            "receive_quantity_limit",
            "cumulative receipts exceed ordered",
            "POST",
            f"/purchase-orders/{po_id}/receive",
            req2,
            st2,
            body2,
            {"first_receive_status": st1, "first_receive": body1, "first_request": req1},
        )
    except Exception as exc:
        record("receive_quantity_limit", "cumulative receipts exceed ordered", "POST", "/receive", None, 0, {"error": str(exc)})

    # 8. zero quantity
    try:
        vid, po_id, setup = ready_po("Adv Zero Receive", [line("CEM-30KG", 4, 11.90)])
        (st, body), req = receive(po_id, [item("CEM-30KG", 0)])
        record("receive_quantity_limit", "receive zero quantity", "POST", f"/purchase-orders/{po_id}/receive", req, st, body)
    except Exception as exc:
        record("receive_quantity_limit", "receive zero quantity", "POST", "/receive", None, 0, {"error": str(exc)})

    # 9. negative quantity
    try:
        vid, po_id, setup = ready_po("Adv Negative Receive", [line("CEM-30KG", 4, 11.90)])
        (st, body), req = receive(po_id, [item("CEM-30KG", -1)])
        record("receive_quantity_limit", "receive negative quantity", "POST", f"/purchase-orders/{po_id}/receive", req, st, body)
    except Exception as exc:
        record("receive_quantity_limit", "receive negative quantity", "POST", "/receive", None, 0, {"error": str(exc)})

    # 10. one cent over
    try:
        vid, po_id, setup = ready_po("Adv One Cent", [line("LUM-2X4-8", 1, 10.00)])
        (rst, rbody), _ = receive(po_id, [item("LUM-2X4-8", 1)])
        (st, body), req = create_invoice(po_id, "INV-ONE-CENT", [line("LUM-2X4-8", 1, 10.01)])
        record(
            "overpayment_protection",
            "invoice one cent over received value",
            "POST",
            "/invoices",
            req,
            st,
            body,
            {"receive_status": rst, "received_value": rbody.get("received_value") if isinstance(rbody, dict) else rbody},
        )
    except Exception as exc:
        record("overpayment_protection", "invoice one cent over received value", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 11. one percent over
    try:
        vid, po_id, setup = ready_po("Adv One Percent", [line("PLY-12-4X8", 10, 10.00)])
        receive(po_id, [item("PLY-12-4X8", 10)])
        (st, body), req = create_invoice(po_id, "INV-ONE-PCT", [line("PLY-12-4X8", 10, 10.10)])
        record("overpayment_protection", "invoice one percent over received value", "POST", "/invoices", req, st, body)
    except Exception as exc:
        record("overpayment_protection", "invoice one percent over received value", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 12. line qty over, total under
    try:
        lines = [line("LUM-2X4-8", 10, 1.00), line("PLY-12-4X8", 10, 10.00)]
        vid, po_id, setup = ready_po("Adv Line Qty Over", lines)
        (rst, rbody), _ = receive(po_id, [item("LUM-2X4-8", 10), item("PLY-12-4X8", 10)])
        inv_lines = [line("LUM-2X4-8", 11, 1.00), line("PLY-12-4X8", 9, 10.00)]
        (st, body), req = create_invoice(po_id, "INV-LINE-QTY", inv_lines)
        record(
            "overpayment_protection",
            "line quantity over while total under",
            "POST",
            "/invoices",
            req,
            st,
            body,
            {"receive_status": rst, "received_value": rbody.get("received_value") if isinstance(rbody, dict) else rbody},
        )
    except Exception as exc:
        record("overpayment_protection", "line quantity over while total under", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 13. two invoices combined
    try:
        vid, po_id, setup = ready_po("Adv Two Invoices", [line("CEM-30KG", 10, 10.00)])
        receive(po_id, [item("CEM-30KG", 10)])
        (st1, body1), req1 = create_invoice(po_id, "INV-PART-A", [line("CEM-30KG", 6, 10.00)])
        (st2, body2), req2 = create_invoice(po_id, "INV-PART-B", [line("CEM-30KG", 5, 10.00)])
        record(
            "overpayment_protection",
            "two invoices combined exceed received",
            "POST",
            "/invoices",
            req2,
            st2,
            body2,
            {"first_status": st1, "first_invoice": body1, "first_request": req1},
        )
    except Exception as exc:
        record("overpayment_protection", "two invoices combined exceed received", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 14. invoice before receipt
    try:
        vid, po_id, setup = ready_po("Adv Invoice Before Receipt", [line("REB-10MM-6", 3, 18.25)])
        (st, body), req = create_invoice(po_id, "INV-NO-RECEIPT", [line("REB-10MM-6", 3, 18.25)])
        record("overpayment_protection", "invoice before any receipt", "POST", "/invoices", req, st, body)
    except Exception as exc:
        record("overpayment_protection", "invoice before any receipt", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 15. underpayment allowed
    try:
        vid, po_id, setup = ready_po("Adv Underpay", [line("LUM-2X4-8", 1, 10.00)])
        receive(po_id, [item("LUM-2X4-8", 1)])
        (st, body), req = create_invoice(po_id, "INV-UNDER", [line("LUM-2X4-8", 1, 9.99)])
        record("overpayment_protection", "underpayment is allowed", "POST", "/invoices", req, st, body)
    except Exception as exc:
        record("overpayment_protection", "underpayment is allowed", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 16. lower qty higher price same total
    try:
        vid, po_id, setup = ready_po("Adv Price Reshape", [line("SCR-DECK-1LB", 10, 5.00)])
        receive(po_id, [item("SCR-DECK-1LB", 10)])
        (st, body), req = create_invoice(po_id, "INV-RESHAPE", [line("SCR-DECK-1LB", 5, 10.00)])
        record("overpayment_protection", "lower quantity higher price same total", "POST", "/invoices", req, st, body)
    except Exception as exc:
        record("overpayment_protection", "lower quantity higher price same total", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 17. prices offset to same total
    try:
        lines = [line("LUM-2X4-8", 1, 10.00), line("CEM-30KG", 1, 10.00)]
        vid, po_id, setup = ready_po("Adv Price Offset", lines)
        (rst, rbody), _ = receive(po_id, [item("LUM-2X4-8", 1), item("CEM-30KG", 1)])
        inv_lines = [line("LUM-2X4-8", 1, 10.01), line("CEM-30KG", 1, 9.99)]
        (st, body), req = create_invoice(po_id, "INV-OFFSET", inv_lines)
        record(
            "overpayment_protection",
            "prices offset to the same total",
            "POST",
            "/invoices",
            req,
            st,
            body,
            {"received_value": rbody.get("received_value") if isinstance(rbody, dict) else rbody},
        )
    except Exception as exc:
        record("overpayment_protection", "prices offset to the same total", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 18. tenth-cent prices
    try:
        lines = [line("LUM-2X4-8", 1, 0.10), line("PLY-12-4X8", 1, 0.20)]
        vid, po_id, setup = ready_po("Adv Tenth Cent", lines)
        (rst, rbody), _ = receive(po_id, [item("LUM-2X4-8", 1), item("PLY-12-4X8", 1)])
        (st, body), req = create_invoice(po_id, "INV-TENTH", lines)
        record(
            "overpayment_protection",
            "tenth-cent prices that sum cleanly",
            "POST",
            "/invoices",
            req,
            st,
            body,
            {
                "po_ordered_value": setup["po"].get("ordered_value"),
                "received_value": rbody.get("received_value") if isinstance(rbody, dict) else rbody,
                "receive_status": rst,
            },
        )
    except Exception as exc:
        record("overpayment_protection", "tenth-cent prices that sum cleanly", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 19. partial receipt flag
    try:
        lines = [line("LUM-2X4-8", 10, 4.75), line("CEM-30KG", 4, 11.90), line("SCR-DECK-1LB", 5, 9.99)]
        vid, po_id, setup = ready_po("Adv Partial Flag", lines)
        (r1, b1), q1 = receive(po_id, [item("LUM-2X4-8", 3)])
        (r2, b2), q2 = receive(po_id, [item("SCR-DECK-1LB", 1)])
        inv_lines = [line("LUM-2X4-8", 3, 4.75), line("SCR-DECK-1LB", 1, 9.99)]
        (ist, ibody), ireq = create_invoice(po_id, "INV-PARTIAL", inv_lines)
        if ist != 201:
            raise RuntimeError(f"invoice {ist} {ibody}")
        mst, mbody = match(ibody["id"])
        gst, gbody = get_invoice(ibody["id"])
        pst, pbody = get_po(po_id)
        record(
            "partial_receipt_flag",
            "partial lines then match",
            "POST",
            f"/invoices/{ibody['id']}/match",
            None,
            mst,
            mbody,
            {
                "first_receive": {"status": r1, "body": b1},
                "second_receive": {"status": r2, "body": b2},
                "invoice": ibody,
                "get_invoice_status": gst,
                "get_invoice": gbody,
                "po_after": pbody,
            },
        )
    except Exception as exc:
        record("partial_receipt_flag", "partial lines then match", "POST", "/match", None, 0, {"error": str(exc)})

    # 20. full receipt flag false
    try:
        lines = [line("CEM-30KG", 2, 11.90), line("REB-10MM-6", 1, 18.25)]
        vid, po_id, setup = ready_po("Adv Full Flag", lines)
        (rst, rbody), _ = receive(po_id, [item("CEM-30KG", 2), item("REB-10MM-6", 1)])
        (ist, ibody), _ = create_invoice(po_id, "INV-FULL", lines)
        if ist != 201:
            raise RuntimeError(f"invoice {ist} {ibody}")
        mst, mbody = match(ibody["id"])
        gst, gbody = get_invoice(ibody["id"])
        record(
            "partial_receipt_flag",
            "full receipt flag is false",
            "POST",
            f"/invoices/{ibody['id']}/match",
            None,
            mst,
            mbody,
            {
                "po_status": rbody.get("status") if isinstance(rbody, dict) else None,
                "fully_received": rbody.get("fully_received") if isinstance(rbody, dict) else None,
                "get_invoice": gbody,
            },
        )
    except Exception as exc:
        record("partial_receipt_flag", "full receipt flag is false", "POST", "/match", None, 0, {"error": str(exc)})

    # 21. exact duplicate invoice number
    try:
        vid, po_id, setup = ready_po("Adv Dup Exact", [line("LUM-2X4-8", 4, 4.75)])
        receive(po_id, [item("LUM-2X4-8", 4)])
        (st1, body1), req1 = create_invoice(po_id, "INV-7", [line("LUM-2X4-8", 2, 4.75)])
        (st2, body2), req2 = create_invoice(po_id, "INV-7", [line("LUM-2X4-8", 1, 4.75)])
        record(
            "duplicate_invoice_detection",
            "exact duplicate invoice number",
            "POST",
            "/invoices",
            req2,
            st2,
            body2,
            {"first_status": st1, "first_invoice": body1},
        )
    except Exception as exc:
        record("duplicate_invoice_detection", "exact duplicate invoice number", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 22. case
    try:
        vid, po_id, setup = ready_po("Adv Dup Case", [line("PLY-12-4X8", 4, 22.40)])
        receive(po_id, [item("PLY-12-4X8", 4)])
        (st1, body1), _ = create_invoice(po_id, "INV-7", [line("PLY-12-4X8", 1, 22.40)])
        (st2, body2), req2 = create_invoice(po_id, "inv-7", [line("PLY-12-4X8", 1, 22.40)])
        record(
            "duplicate_invoice_detection",
            "invoice number differs only by case",
            "POST",
            "/invoices",
            req2,
            st2,
            body2,
            {"first_status": st1, "first_number": "INV-7"},
        )
    except Exception as exc:
        record("duplicate_invoice_detection", "invoice number differs only by case", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 23. spaces
    try:
        vid, po_id, setup = ready_po("Adv Dup Space", [line("CEM-30KG", 4, 11.90)])
        receive(po_id, [item("CEM-30KG", 4)])
        (st1, body1), _ = create_invoice(po_id, "INV-7", [line("CEM-30KG", 1, 11.90)])
        (st2, body2), req2 = create_invoice(po_id, " INV-7 ", [line("CEM-30KG", 1, 11.90)])
        record(
            "duplicate_invoice_detection",
            "invoice number differs only by surrounding spaces",
            "POST",
            "/invoices",
            req2,
            st2,
            body2,
            {"first_status": st1},
        )
    except Exception as exc:
        record("duplicate_invoice_detection", "invoice number differs only by surrounding spaces", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 24. same number two vendors
    try:
        reset()
        vid_a, _, va = vendor("Adv Dup Vendor A")
        vid_b, _, vb = vendor("Adv Dup Vendor B")
        (sta, pa), _ = create_po(vid_a, [line("LUM-2X4-8", 2, 4.75)])
        (stb, pb), _ = create_po(vid_b, [line("LUM-2X4-8", 2, 4.75)])
        if sta != 201 or stb != 201:
            raise RuntimeError(f"po {sta} {pa} {stb} {pb}")
        submit(pa["id"])
        submit(pb["id"])
        receive(pa["id"], [item("LUM-2X4-8", 2)])
        receive(pb["id"], [item("LUM-2X4-8", 2)])
        (st1, body1), req1 = create_invoice(pa["id"], "INV-SAME", [line("LUM-2X4-8", 2, 4.75)])
        (st2, body2), req2 = create_invoice(pb["id"], "INV-SAME", [line("LUM-2X4-8", 2, 4.75)])
        record(
            "duplicate_invoice_detection",
            "same number on two vendors",
            "POST",
            "/invoices",
            req2,
            st2,
            body2,
            {"first_vendor_status": st1, "first_invoice": body1, "vendors": [vid_a, vid_b]},
        )
    except Exception as exc:
        record("duplicate_invoice_detection", "same number on two vendors", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 25. gl balance standard
    try:
        vid, po_id, setup = ready_po("Adv GL Standard", [line("LUM-2X4-8", 10, 4.75)])
        receive(po_id, [item("LUM-2X4-8", 10)])
        (ist, ibody), ireq = create_invoice(po_id, "INV-GL", [line("LUM-2X4-8", 10, 4.75)])
        if ist != 201:
            raise RuntimeError(f"invoice {ist} {ibody}")
        mst, mbody = match(ibody["id"])
        ast, abody = approve(ibody["id"])
        record(
            "gl_balance",
            "approval ledger balances",
            "POST",
            f"/invoices/{ibody['id']}/approve",
            None,
            ast,
            abody,
            {"invoice_total": ibody.get("total_amount"), "match": mbody, "match_status": mst},
        )
    except Exception as exc:
        record("gl_balance", "approval ledger balances", "POST", "/approve", None, 0, {"error": str(exc)})

    # 26. gl tenth cent
    try:
        lines = [line("LUM-2X4-8", 1, 0.10), line("PLY-12-4X8", 1, 0.20)]
        vid, po_id, setup = ready_po("Adv GL Tenth", lines)
        receive(po_id, [item("LUM-2X4-8", 1), item("PLY-12-4X8", 1)])
        (ist, ibody), _ = create_invoice(po_id, "INV-GL-TENTH", lines)
        if ist != 201:
            raise RuntimeError(f"invoice {ist} {ibody}")
        match(ibody["id"])
        ast, abody = approve(ibody["id"])
        record(
            "gl_balance",
            "ledger on tenth-cent lines",
            "POST",
            f"/invoices/{ibody['id']}/approve",
            None,
            ast,
            abody,
            {"invoice": ibody, "ordered_value": setup["po"].get("ordered_value")},
        )
    except Exception as exc:
        record("gl_balance", "ledger on tenth-cent lines", "POST", "/approve", None, 0, {"error": str(exc)})

    # 27. half-cent
    try:
        lines = [line("CEM-30KG", 1, 1.005)]
        reset()
        vid, _, _ = vendor("Adv Half Cent")
        (pst, pbody), poreq = create_po(vid, lines)
        record_setup_po = {"po_status": pst, "po": pbody}
        if pst == 201:
            submit(pbody["id"])
            (rst, rbody), _ = receive(pbody["id"], [item("CEM-30KG", 1)])
            record_setup_po["receive_status"] = rst
            record_setup_po["receive"] = rbody
            (ist, ibody), ireq = create_invoice(pbody["id"], "INV-HALF", lines)
            record_setup_po["invoice_status"] = ist
            record_setup_po["invoice"] = ibody
            if ist == 201:
                mst, mbody = match(ibody["id"])
                record_setup_po["match_status"] = mst
                record_setup_po["match"] = mbody
                ast, abody = approve(ibody["id"])
                record(
                    "gl_balance",
                    "half-cent unit price",
                    "POST",
                    f"/invoices/{ibody['id']}/approve",
                    None,
                    ast,
                    abody,
                    record_setup_po,
                )
            else:
                record("gl_balance", "half-cent unit price", "POST", "/invoices", ireq, ist, ibody, record_setup_po)
        else:
            record("gl_balance", "half-cent unit price", "POST", "/purchase-orders", poreq, pst, pbody, record_setup_po)
    except Exception as exc:
        record("gl_balance", "half-cent unit price", "POST", "/approve", None, 0, {"error": str(exc)})

    # 28. sku not on po
    try:
        vid, po_id, setup = ready_po("Adv Sku Missing", [line("LUM-2X4-8", 2, 4.75)])
        receive(po_id, [item("LUM-2X4-8", 2)])
        (st, body), req = create_invoice(po_id, "INV-BAD-SKU", [line("CEM-30KG", 1, 11.90)])
        record("invoice_line_validation", "sku not on the po", "POST", "/invoices", req, st, body)
    except Exception as exc:
        record("invoice_line_validation", "sku not on the po", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 29. duplicate sku on invoice
    try:
        vid, po_id, setup = ready_po("Adv Dup Sku Inv", [line("LUM-2X4-8", 5, 4.75)])
        receive(po_id, [item("LUM-2X4-8", 5)])
        inv_lines = [line("LUM-2X4-8", 1, 4.75), line("LUM-2X4-8", 1, 4.75)]
        (st, body), req = create_invoice(po_id, "INV-DUP-SKU", inv_lines)
        record("invoice_line_validation", "duplicate sku on invoice", "POST", "/invoices", req, st, body)
    except Exception as exc:
        record("invoice_line_validation", "duplicate sku on invoice", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 30. approve twice
    try:
        vid, po_id, setup = ready_po("Adv Approve Twice", [line("REB-10MM-6", 1, 18.25)])
        receive(po_id, [item("REB-10MM-6", 1)])
        (ist, ibody), _ = create_invoice(po_id, "INV-TWICE", [line("REB-10MM-6", 1, 18.25)])
        if ist != 201:
            raise RuntimeError(f"invoice {ist} {ibody}")
        match(ibody["id"])
        ast1, abody1 = approve(ibody["id"])
        ast2, abody2 = approve(ibody["id"])
        record(
            "duplicate_approval",
            "approve twice",
            "POST",
            f"/invoices/{ibody['id']}/approve",
            None,
            ast2,
            abody2,
            {"first_approve_status": ast1, "first_approve": abody1},
        )
    except Exception as exc:
        record("duplicate_approval", "approve twice", "POST", "/approve", None, 0, {"error": str(exc)})

    # 31. submit twice
    try:
        reset()
        vid, _, _ = vendor("Adv Submit Twice")
        (pst, pbody), _ = create_po(vid, [line("LUM-2X4-8", 1, 4.75)])
        if pst != 201:
            raise RuntimeError(f"po {pst} {pbody}")
        st1, b1 = submit(pbody["id"])
        st2, b2 = submit(pbody["id"])
        record(
            "workflow_gate",
            "submit twice",
            "POST",
            f"/purchase-orders/{pbody['id']}/submit",
            None,
            st2,
            b2,
            {"first_status": st1, "first_body": b1},
        )
    except Exception as exc:
        record("workflow_gate", "submit twice", "POST", "/submit", None, 0, {"error": str(exc)})

    # 32. receive on draft
    try:
        reset()
        vid, _, _ = vendor("Adv Receive Draft")
        (pst, pbody), _ = create_po(vid, [line("CEM-30KG", 2, 11.90)])
        if pst != 201:
            raise RuntimeError(f"po {pst} {pbody}")
        (st, body), req = receive(pbody["id"], [item("CEM-30KG", 1)])
        record(
            "workflow_gate",
            "receive on draft",
            "POST",
            f"/purchase-orders/{pbody['id']}/receive",
            req,
            st,
            body,
            {"po_status": pbody.get("status")},
        )
    except Exception as exc:
        record("workflow_gate", "receive on draft", "POST", "/receive", None, 0, {"error": str(exc)})

    # 33. invoice on draft
    try:
        reset()
        vid, _, _ = vendor("Adv Invoice Draft")
        (pst, pbody), _ = create_po(vid, [line("SCR-DECK-1LB", 1, 9.99)])
        if pst != 201:
            raise RuntimeError(f"po {pst} {pbody}")
        (st, body), req = create_invoice(pbody["id"], "INV-DRAFT", [line("SCR-DECK-1LB", 1, 9.99)])
        record(
            "workflow_gate",
            "invoice on draft",
            "POST",
            "/invoices",
            req,
            st,
            body,
            {"po_status": pbody.get("status")},
        )
    except Exception as exc:
        record("workflow_gate", "invoice on draft", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 34. match approved
    try:
        vid, po_id, setup = ready_po("Adv Match Approved", [line("LUM-2X4-8", 1, 4.75)])
        receive(po_id, [item("LUM-2X4-8", 1)])
        (ist, ibody), _ = create_invoice(po_id, "INV-REMATCH", [line("LUM-2X4-8", 1, 4.75)])
        if ist != 201:
            raise RuntimeError(f"invoice {ist} {ibody}")
        match(ibody["id"])
        ast, abody = approve(ibody["id"])
        mst, mbody = match(ibody["id"])
        record(
            "workflow_gate",
            "match an approved invoice",
            "POST",
            f"/invoices/{ibody['id']}/match",
            None,
            mst,
            mbody,
            {"approve_status": ast, "approve": abody},
        )
    except Exception as exc:
        record("workflow_gate", "match an approved invoice", "POST", "/match", None, 0, {"error": str(exc)})

    # 35. invoice a closed po
    try:
        vid, po_id, setup = ready_po("Adv Invoice Closed", [line("PLY-12-4X8", 1, 22.40)])
        (rst, rbody), _ = receive(po_id, [item("PLY-12-4X8", 1)])
        (st, body), req = create_invoice(po_id, "INV-CLOSED", [line("PLY-12-4X8", 1, 22.40)])
        record(
            "workflow_gate",
            "invoice a closed po",
            "POST",
            "/invoices",
            req,
            st,
            body,
            {"po_after_receive": rbody},
        )
    except Exception as exc:
        record("workflow_gate", "invoice a closed po", "POST", "/invoices", None, 0, {"error": str(exc)})

    # 36. exposure one invoice
    try:
        vid, po_id, setup = ready_po("Adv Exposure One", [line("CEM-30KG", 4, 11.90)])
        receive(po_id, [item("CEM-30KG", 4)])
        (ist, ibody), _ = create_invoice(po_id, "INV-EXP-1", [line("CEM-30KG", 4, 11.90)])
        if ist != 201:
            raise RuntimeError(f"invoice {ist} {ibody}")
        match(ibody["id"])
        ast, abody = approve(ibody["id"])
        est, ebody = exposure(vid)
        record(
            "vendor_exposure_math",
            "exposure equals one approved invoice",
            "GET",
            f"/vendors/{vid}/exposure",
            None,
            est,
            ebody,
            {"approve_status": ast, "approve": abody, "invoice_total": ibody.get("total_amount"), "invoice_id": ibody.get("id")},
        )
    except Exception as exc:
        record("vendor_exposure_math", "exposure equals one approved invoice", "GET", "/exposure", None, 0, {"error": str(exc)})

    # 37. exposure two invoices
    try:
        reset()
        vid, _, _ = vendor("Adv Exposure Two")
        totals = []
        approve_bodies = []
        invoice_ids = []
        for idx, (sku, qty, price, number) in enumerate(
            [("LUM-2X4-8", 2, 4.75, "INV-EXP-A"), ("REB-10MM-6", 1, 18.25, "INV-EXP-B")],
            start=1,
        ):
            (pst, pbody), _ = create_po(vid, [line(sku, qty, price)])
            if pst != 201:
                raise RuntimeError(f"po {pst} {pbody}")
            submit(pbody["id"])
            receive(pbody["id"], [item(sku, qty)])
            (ist, ibody), _ = create_invoice(pbody["id"], number, [line(sku, qty, price)])
            if ist != 201:
                raise RuntimeError(f"invoice {ist} {ibody}")
            match(ibody["id"])
            ast, abody = approve(ibody["id"])
            totals.append(ibody.get("total_amount"))
            approve_bodies.append({"status": ast, "body": abody})
            invoice_ids.append(ibody.get("id"))
        est, ebody = exposure(vid)
        record(
            "vendor_exposure_math",
            "exposure sums two approved invoices",
            "GET",
            f"/vendors/{vid}/exposure",
            None,
            est,
            ebody,
            {"invoice_totals": totals, "invoice_ids": invoice_ids, "approvals": approve_bodies},
        )
    except Exception as exc:
        record("vendor_exposure_math", "exposure sums two approved invoices", "GET", "/exposure", None, 0, {"error": str(exc)})

    # 38. duplicate sku on PO
    try:
        reset()
        vid, _, _ = vendor("Adv Dup Sku PO")
        req = {"vendor_id": vid, "line_items": [line("LUM-2X4-8", 1, 4.75), line("LUM-2X4-8", 2, 4.75)]}
        st, body = curl("POST", "/purchase-orders", req)
        record("invoice_line_validation", "duplicate sku on purchase order", "POST", "/purchase-orders", req, st, body)
    except Exception as exc:
        record("invoice_line_validation", "duplicate sku on purchase order", "POST", "/purchase-orders", None, 0, {"error": str(exc)})

    # 39. receive sku not on po
    try:
        vid, po_id, setup = ready_po("Adv Receive Unknown Sku", [line("LUM-2X4-8", 2, 4.75)])
        (st, body), req = receive(po_id, [item("CEM-30KG", 1)])
        record("receive_quantity_limit", "receive sku not on the po", "POST", f"/purchase-orders/{po_id}/receive", req, st, body)
    except Exception as exc:
        record("receive_quantity_limit", "receive sku not on the po", "POST", "/receive", None, 0, {"error": str(exc)})

    # negative unit price (validation)
    try:
        reset()
        vid, _, _ = vendor("Adv Negative Price")
        req = {"vendor_id": vid, "line_items": [line("LUM-2X4-8", 1, -1)]}
        st, body = curl("POST", "/purchase-orders", req)
        record("overpayment_protection", "negative unit price", "POST", "/purchase-orders", req, st, body)
    except Exception as exc:
        record("overpayment_protection", "negative unit price", "POST", "/purchase-orders", None, 0, {"error": str(exc)})

    # zero quantity on PO
    try:
        reset()
        vid, _, _ = vendor("Adv Zero Qty PO")
        req = {"vendor_id": vid, "line_items": [line("LUM-2X4-8", 0, 4.75)]}
        st, body = curl("POST", "/purchase-orders", req)
        record("receive_quantity_limit", "zero quantity on purchase order", "POST", "/purchase-orders", req, st, body)
    except Exception as exc:
        record("receive_quantity_limit", "zero quantity on purchase order", "POST", "/purchase-orders", None, 0, {"error": str(exc)})


if __name__ == "__main__":
    run()
    with open("qa-run/attack-raw.json", "w") as fh:
        json.dump(results, fh, indent=2)
        fh.write("\n")
    print(f"WROTE {len(results)} attacks")
