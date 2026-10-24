import { expect, test } from '@playwright/test';
import { expectSchema } from '../helpers/schema';
import {
  createFlowVendor,
  isRecord,
  requireBoolean,
  requireNumber,
  requireString,
  sumGlLineAmounts,
} from './flow-helpers';

test.describe('Full P2P flow', () => {
  test.describe.configure({ mode: 'serial' });

  let vendorId: string;
  let poId: string;
  let invoiceId: string;
  let invoiceTotal: number;

  test('create vendor', { tag: '@e2e' }, async ({ request }) => {
    vendorId = await createFlowVendor(request, 'full');
  });

  test('create purchase order with two lines', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post('/purchase-orders', {
      data: {
        vendor_id: vendorId,
        line_items: [
          { sku: 'LUM-2X4-8', quantity: 10, unit_price: 4.75 },
          { sku: 'CEM-30KG', quantity: 4, unit_price: 11.9 },
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
    expect(body.status).toBe('draft');
    expect(requireNumber(body, 'ordered_value')).toBe(95.1);
    expect(requireNumber(body, 'received_value')).toBe(0);
    expect(requireBoolean(body, 'fully_received')).toBe(false);
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

  test('receive all line items', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post(`/purchase-orders/${poId}/receive`, {
      data: {
        items: [
          { sku: 'LUM-2X4-8', quantity: 10 },
          { sku: 'CEM-30KG', quantity: 4 },
        ],
      },
    });
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'PurchaseOrder');
    if (!isRecord(body)) {
      throw new Error('receive did not return an object');
    }
    expect(body.status).toBe('closed');
    expect(requireNumber(body, 'received_value')).toBe(95.1);
    expect(requireBoolean(body, 'fully_received')).toBe(true);
  });

  test('invoice for everything received', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post('/invoices', {
      data: {
        po_id: poId,
        invoice_number: `INV-full-${Date.now()}`,
        line_items: [
          { sku: 'LUM-2X4-8', quantity: 10, unit_price: 4.75 },
          { sku: 'CEM-30KG', quantity: 4, unit_price: 11.9 },
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
    invoiceTotal = requireNumber(body, 'total_amount');
    expect(invoiceTotal).toBe(95.1);
    expect(body.status).toBe('received');
    expect(body.matched).toBe(false);
    expect(body.partial_receipt).toBeNull();
  });

  test('match with partial_receipt false', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post(`/invoices/${invoiceId}/match`);
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'MatchResult');
    if (!isRecord(body)) {
      throw new Error('match did not return an object');
    }
    expect(requireBoolean(body, 'partial_receipt')).toBe(false);
    expect(requireNumber(body, 'invoice_total')).toBe(invoiceTotal);
    expect(requireNumber(body, 'received_value')).toBe(95.1);
  });

  test('approve posts balanced ledger and updates exposure', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post(`/invoices/${invoiceId}/approve`);
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'ApproveResult');
    if (!isRecord(body)) {
      throw new Error('approve did not return an object');
    }
    expect(body.status).toBe('approved');
    expect(requireNumber(body, 'vendor_exposure')).toBe(invoiceTotal);

    const glEntry = body.gl_entry;
    if (!isRecord(glEntry)) {
      throw new Error('approve result missing gl_entry');
    }
    await expectSchema(request, glEntry, 'GlEntry');
    expect(requireBoolean(glEntry, 'balanced')).toBe(true);

    const debitTotal = sumGlLineAmounts(glEntry.debits);
    const creditTotal = sumGlLineAmounts(glEntry.credits);
    expect(debitTotal).toBe(creditTotal);
    expect(debitTotal).toBe(invoiceTotal);

    const exposureRes = await request.get(`/vendors/${vendorId}/exposure`);
    expect(exposureRes.status()).toBe(200);
    const exposure: unknown = await exposureRes.json();
    await expectSchema(request, exposure, 'VendorExposure');
    if (!isRecord(exposure)) {
      throw new Error('exposure did not return an object');
    }
    expect(requireNumber(exposure, 'open_ap_liability')).toBe(invoiceTotal);
    const approvedInvoices = exposure.approved_invoices;
    expect(Array.isArray(approvedInvoices)).toBe(true);
    if (Array.isArray(approvedInvoices)) {
      expect(approvedInvoices).toContain(invoiceId);
    }
  });
});
