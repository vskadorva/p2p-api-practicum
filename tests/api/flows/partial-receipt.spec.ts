import { expect, test } from '@playwright/test';
import { expectSchema } from '../helpers/schema';
import {
  createFlowVendor,
  isRecord,
  requireBoolean,
  requireNumber,
  requireString,
} from './flow-helpers';

test.describe('Partial receipt flow', () => {
  test.describe.configure({ mode: 'serial' });

  let vendorId: string;
  let poId: string;
  let invoiceId: string;
  const orderedValue = 95.1;
  const receivedValue = 71.3;

  test('create vendor', { tag: '@e2e' }, async ({ request }) => {
    vendorId = await createFlowVendor(request, 'partial');
  });

  test('create purchase order with two lines', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post('/purchase-orders', {
      data: {
        vendor_id: vendorId,
        line_items: [
          { sku: 'CEM-30KG', quantity: 4, unit_price: 11.9 },
          { sku: 'LUM-2X4-8', quantity: 10, unit_price: 4.75 },
        ],
      },
    });
    expect(response.status()).toBe(201);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'PurchaseOrder');
    if (!isRecord(body)) {
      throw new Error('POST /purchase-orders did not return an object');
    }
    poId = requireString(body, 'id');
    expect(requireNumber(body, 'ordered_value')).toBe(orderedValue);
  });

  test('submit purchase order', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post(`/purchase-orders/${poId}/submit`);
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'PurchaseOrder');
    if (!isRecord(body)) {
      throw new Error('submit did not return an object');
    }
    expect(body.status).toBe('submitted');
  });

  test('receive first line in full and part of the second', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post(`/purchase-orders/${poId}/receive`, {
      data: {
        items: [
          { sku: 'CEM-30KG', quantity: 2 },
          { sku: 'LUM-2X4-8', quantity: 10 },
        ],
      },
    });
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'PurchaseOrder');
    if (!isRecord(body)) {
      throw new Error('receive did not return an object');
    }
    expect(body.status).toBe('submitted');
    expect(requireBoolean(body, 'fully_received')).toBe(false);
    expect(requireNumber(body, 'received_value')).toBe(receivedValue);
  });

  test('invoice only what was received', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post('/invoices', {
      data: {
        po_id: poId,
        invoice_number: `INV-partial-${Date.now()}`,
        line_items: [
          { sku: 'CEM-30KG', quantity: 2, unit_price: 11.9 },
          { sku: 'LUM-2X4-8', quantity: 10, unit_price: 4.75 },
        ],
      },
    });
    expect(response.status()).toBe(201);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'Invoice');
    if (!isRecord(body)) {
      throw new Error('POST /invoices did not return an object');
    }
    invoiceId = requireString(body, 'id');
    expect(requireNumber(body, 'total_amount')).toBe(receivedValue);
  });

  test('match with partial_receipt true', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post(`/invoices/${invoiceId}/match`);
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'MatchResult');
    if (!isRecord(body)) {
      throw new Error('match did not return an object');
    }
    expect(requireBoolean(body, 'partial_receipt')).toBe(true);
    expect(requireNumber(body, 'ordered_value')).toBe(orderedValue);
    expect(requireNumber(body, 'received_value')).toBe(receivedValue);
    expect(requireNumber(body, 'invoice_total')).toBe(receivedValue);
  });

  test('approve and exposure reflects received value not ordered', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post(`/invoices/${invoiceId}/approve`);
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'ApproveResult');
    if (!isRecord(body)) {
      throw new Error('approve did not return an object');
    }
    expect(requireNumber(body, 'vendor_exposure')).toBe(receivedValue);
    expect(requireNumber(body, 'vendor_exposure')).not.toBe(orderedValue);

    const exposureRes = await request.get(`/vendors/${vendorId}/exposure`);
    expect(exposureRes.status()).toBe(200);
    const exposure: unknown = await exposureRes.json();
    await expectSchema(request, exposure, 'VendorExposure');
    if (!isRecord(exposure)) {
      throw new Error('exposure did not return an object');
    }
    expect(requireNumber(exposure, 'open_ap_liability')).toBe(receivedValue);
  });
});
