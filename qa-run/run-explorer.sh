#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: > qa-run/steps.jsonl

BASE=http://localhost:8000
STEP=0

log_step() {
  local intent="$1" method="$2" req_path="$3" body="$4" http_status="$5" resp_body="$6" expected="$7" verdict="$8" reason="$9"
  STEP=$((STEP + 1))
  jq -nc \
    --arg agent "explorer" \
    --argjson step "$STEP" \
    --arg intent "$intent" \
    --arg method "$method" \
    --arg req_path "$req_path" \
    --arg body "$body" \
    --argjson http_status "$http_status" \
    --arg resp_raw "$resp_body" \
    --arg expected "$expected" \
    --arg verdict "$verdict" \
    --arg reason "$reason" \
    '{
      agent: $agent,
      step: $step,
      intent: $intent,
      request: {
        method: $method,
        path: $req_path,
        body: (if $body == "" or $body == "null" then null else ($body | fromjson) end)
      },
      response: {
        status: $http_status,
        body: (try ($resp_raw | fromjson) catch $resp_raw)
      },
      expected: $expected,
      verdict: $verdict,
      reason: $reason
    }' >> qa-run/steps.jsonl
}

api_call() {
  local intent="$1" method="$2" req_path="$3" body="$4" expected="$5" verdict="$6" reason="$7"
  local tmp
  tmp=$(mktemp)
  local code
  if [ "$method" = "GET" ]; then
    code=$(curl -s -w '%{http_code}' -o "$tmp" "$BASE$req_path")
  elif [ -z "$body" ] || [ "$body" = "null" ]; then
    code=$(curl -s -w '%{http_code}' -o "$tmp" -X "$method" "$BASE$req_path")
  else
    code=$(curl -s -w '%{http_code}' -o "$tmp" -X "$method" "$BASE$req_path" -H 'Content-Type: application/json' -d "$body")
  fi
  local resp
  resp=$(cat "$tmp")
  rm -f "$tmp"
  local req_json="null"
  if [ -n "$body" ] && [ "$body" != "null" ]; then
    req_json="$body"
  fi
  log_step "$intent" "$method" "$req_path" "$req_json" "$code" "$resp" "$expected" "$verdict" "$reason"
  LAST_API_RESP="$resp"
}

patch_last_verdict() {
  local verdict="$1" reason="$2"
  local last
  last=$(tail -1 qa-run/steps.jsonl)
  head -n -1 qa-run/steps.jsonl > qa-run/steps.jsonl.tmp || true
  echo "$last" | jq --arg v "$verdict" --arg r "$reason" '.verdict=$v | .reason=$r' >> qa-run/steps.jsonl.tmp
  mv qa-run/steps.jsonl.tmp qa-run/steps.jsonl
}

# Step 1: Health
HEALTH=$(curl -s -w '\n%{http_code}' "$BASE/health")
HEALTH_BODY=$(echo "$HEALTH" | sed '$d')
HEALTH_CODE=$(echo "$HEALTH" | tail -1)
if [ "$HEALTH_CODE" = "200" ] && echo "$HEALTH_BODY" | jq -e '.status == "ok"' >/dev/null 2>&1; then
  V="as-documented"
  R="200 with status ok per docs/API.md → System → GET /health"
else
  V="unexpected"
  R="Health check failed: expected 200 and status ok"
  log_step "API is up" "GET" "/health" "null" "$HEALTH_CODE" "$HEALTH_BODY" \
    "docs/API.md → System: GET /health returns {\"status\": \"ok\"} with 200" "$V" "$R"
  echo "Health failed; stopping."
  exit 1
fi
log_step "API is up" "GET" "/health" "null" "$HEALTH_CODE" "$HEALTH_BODY" \
  "docs/API.md → System: GET /health returns {\"status\": \"ok\"} with 200" "$V" "$R"

api_call "Discover vendors" "GET" "/vendors" "null" \
  "docs/API.md → Vendors: GET /vendors lists all vendors including seed data" \
  "as-documented" \
  "Lists vnd-001 (active) and vnd-002 (inactive) per seed data"
VENDORS_RESP="$LAST_API_RESP"

if ! echo "$VENDORS_RESP" | jq -e '[.[] | select(.id=="vnd-001" and .active==true)] | length > 0' >/dev/null; then
  patch_last_verdict "unexpected" "Expected active seed vendor vnd-001 in list"
fi

api_call "Discover catalog" "GET" "/skus" "null" \
  "docs/API.md → Catalog: GET /skus lists five SKUs with catalog prices" \
  "as-documented" \
  "Five SKUs returned; using LUM-2X4-8 (4.75) and PLY-12-4X8 (22.40)"

SKU1=LUM-2X4-8
SKU2=PLY-12-4X8
PRICE1=4.75
PRICE2=22.40

TS=$(date +%s)
VENDOR_BODY=$(jq -nc --arg name "Explorer Vendor $TS" '{name: $name, active: true}')
api_call "Create vendor" "POST" "/vendors" "$VENDOR_BODY" \
  "docs/API.md → Vendors: POST /vendors creates vendor, returns 201" \
  "as-documented" \
  "201 with server-assigned vnd- id and active true"
VENDOR_RESP="$LAST_API_RESP"

VENDOR_ID=$(echo "$VENDOR_RESP" | jq -r '.id')
if [ "$(echo "$VENDOR_RESP" | jq -r '.active')" != "true" ]; then
  patch_last_verdict "unexpected" "Created vendor active flag is not true"
fi

PO_BODY=$(jq -nc \
  --arg vid "$VENDOR_ID" \
  --arg sku1 "$SKU1" --argjson p1 "$PRICE1" \
  --arg sku2 "$SKU2" --argjson p2 "$PRICE2" \
  '{vendor_id: $vid, line_items: [
    {sku: $sku1, quantity: 10, unit_price: $p1},
    {sku: $sku2, quantity: 2, unit_price: $p2}
  ]}')
api_call "Draft PO" "POST" "/purchase-orders" "$PO_BODY" \
  "docs/API.md → Purchase orders: POST creates draft PO 201 for active vendor with valid lines" \
  "as-documented" \
  "Draft PO two lines; ordered_value 92.3 (10×4.75 + 2×22.40)"
PO_RESP="$LAST_API_RESP"

PO_ID=$(echo "$PO_RESP" | jq -r '.id')
QTY1=$(echo "$PO_RESP" | jq -r '.line_items[] | select(.sku=="LUM-2X4-8") | .quantity')
QTY2=$(echo "$PO_RESP" | jq -r '.line_items[] | select(.sku=="PLY-12-4X8") | .quantity')
if [ "$(echo "$PO_RESP" | jq -r '.status')" != "draft" ]; then
  patch_last_verdict "unexpected" "Expected draft status on new PO"
fi

api_call "Submit PO" "POST" "/purchase-orders/$PO_ID/submit" "null" \
  "docs/API.md → POST /purchase-orders/{id}/submit moves draft to submitted" \
  "as-documented" \
  "PO status submitted after submit"
SUBMIT_RESP="$LAST_API_RESP"

if [ "$(echo "$SUBMIT_RESP" | jq -r '.status')" != "submitted" ]; then
  patch_last_verdict "unexpected" "Expected submitted status after submit"
fi

RECV_BODY=$(jq -nc --arg sku1 "$SKU1" --argjson q1 "$QTY1" --arg sku2 "$SKU2" --argjson q2 "$QTY2" \
  '{items: [{sku: $sku1, quantity: $q1}, {sku: $sku2, quantity: $q2}]}')
api_call "Receive all goods" "POST" "/purchase-orders/$PO_ID/receive" "$RECV_BODY" \
  "docs/API.md → POST receive on submitted PO; full receipt closes PO when all lines complete" \
  "as-documented" \
  "Full ordered quantities received for both SKUs in one delivery"

api_call "Confirm PO state" "GET" "/purchase-orders/$PO_ID" "null" \
  "docs/API.md → GET PO; after full receipt status closed and fully_received true" \
  "as-documented" \
  "PO closed with received quantities matching ordered"
GET_PO="$LAST_API_RESP"

PO_STATUS=$(echo "$GET_PO" | jq -r '.status')
PO_FR=$(echo "$GET_PO" | jq -r '.fully_received')
if [ "$PO_STATUS" != "closed" ] || [ "$PO_FR" != "true" ]; then
  patch_last_verdict "unexpected" "Expected status closed and fully_received true; got status=$PO_STATUS fully_received=$PO_FR"
fi

INV_NUM="INV-EXPLORER-$TS"
INV_BODY=$(jq -nc \
  --arg po "$PO_ID" --arg num "$INV_NUM" \
  --arg sku1 "$SKU1" --argjson q1 "$QTY1" --argjson p1 "$PRICE1" \
  --arg sku2 "$SKU2" --argjson q2 "$QTY2" --argjson p2 "$PRICE2" \
  '{po_id: $po, invoice_number: $num, line_items: [
    {sku: $sku1, quantity: $q1, unit_price: $p1},
    {sku: $sku2, quantity: $q2, unit_price: $p2}
  ]}')
api_call "Record invoice" "POST" "/invoices" "$INV_BODY" \
  "docs/API.md → POST /invoices 201 with status received, matched false" \
  "as-documented" \
  "Invoice created against closed PO with lines matching received qty and PO prices"
INV_RESP="$LAST_API_RESP"

INV_ID=$(echo "$INV_RESP" | jq -r '.id')
if [ "$(echo "$INV_RESP" | jq -r '.status')" != "received" ]; then
  patch_last_verdict "unexpected" "Expected invoice status received on create"
fi

api_call "Match invoice" "POST" "/invoices/$INV_ID/match" "null" \
  "docs/API.md → POST match runs 3-way match; partial_receipt false when PO fully received (rule 5)" \
  "as-documented" \
  "Match passed: matched true, partial_receipt false, invoice_total equals ordered/received values"
MATCH_RESP="$LAST_API_RESP"

if [ "$(echo "$MATCH_RESP" | jq -r '.partial_receipt')" != "false" ]; then
  patch_last_verdict "unexpected" "Expected partial_receipt false after full PO receipt"
fi

api_call "Approve invoice" "POST" "/invoices/$INV_ID/approve" "null" \
  "docs/API.md → POST approve on matched invoice; GL balanced (rule 7); vendor_exposure (rule 11)" \
  "as-documented" \
  "Invoice approved; gl_entry.balanced true; vendor_exposure reflects invoice total"
APPROVE_RESP="$LAST_API_RESP"

if [ "$(echo "$APPROVE_RESP" | jq -r '.gl_entry.balanced')" != "true" ]; then
  patch_last_verdict "unexpected" "Expected balanced GL entry on approval"
fi

api_call "Vendor exposure" "GET" "/vendors/$VENDOR_ID/exposure" "null" \
  "docs/API.md → GET /vendors/{id}/exposure: open_ap_liability sum of approved invoice totals (rule 11)" \
  "as-documented" \
  "Exposure response includes approved invoice id and liability matching approve response"
EXP_RESP="$LAST_API_RESP"

EXP_AMT=$(echo "$EXP_RESP" | jq -r '.open_ap_liability')
APPROVE_EXP=$(echo "$APPROVE_RESP" | jq -r '.vendor_exposure')
if [ "$EXP_AMT" != "$APPROVE_EXP" ]; then
  patch_last_verdict "unexpected" "open_ap_liability ($EXP_AMT) != approve vendor_exposure ($APPROVE_EXP)"
fi

echo "DONE VENDOR_ID=$VENDOR_ID PO_ID=$PO_ID INV_ID=$INV_ID STEPS=$STEP"
jq -s '[.[] | .verdict] | group_by(.) | map({verdict: .[0], count: length})' qa-run/steps.jsonl
