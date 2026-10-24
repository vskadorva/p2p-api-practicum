import { expect, test } from '@playwright/test';
import { expectSchema } from '../helpers/schema';
import {
  createFlowVendor,
  isRecord,
  requireNumber,
  requireString,
} from './flow-helpers';

test.describe('Over-invoice protection flow', () => {
  test.describe.configure({ mode: 'serial' });

  let vendorId: string;
  let poId: string;
  let invoiceId: string;
  const lineQty = 10;
  const unitPrice = 4.75;
  const invoiceTotal = 47.5;

  test('create vendor', { tag: '@e2e' }, async ({ request }) => {
    vendorId = await createFlowVendor(request, 'over-invoice');
  });

  test('create and submit purchase order', { tag: '@e2e' }, async ({ request }) => {
    const create = await request.post('/purchase-orders', {
      data: {
        vendor_id: vendorId,
        line_items: [{ sku: 'LUM-2X4-8', quantity: lineQty, unit_price: unitPrice }],
      },
    });
    expect(create.status()).toBe(201);
    const created: unknown = await create.json();
    await expectSchema(request, created, 'PurchaseOrder');
    if (!isRecord(created)) {
      throw new Error('POST /purchase-orders did not return an object');
    }
    poId = requireString(created, 'id');

    const submit = await request.post(`/purchase-orders/${poId}/submit`);
    expect(submit.status()).toBe(200);
    const submitted: unknown = await submit.json();
    await expectSchema(request, submitted, 'PurchaseOrder');
  });

  test('receive everything on the purchase order', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post(`/purchase-orders/${poId}/receive`, {
      data: { items: [{ sku: 'LUM-2X4-8', quantity: lineQty }] },
    });
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'PurchaseOrder');
    if (!isRecord(body)) {
      throw new Error('receive did not return an object');
    }
    expect(requireNumber(body, 'received_value')).toBe(invoiceTotal);
  });

  test('reject invoice for one unit more than received', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.post('/invoices', {
      data: {
        po_id: poId,
        invoice_number: `INV-over-${Date.now()}`,
        line_items: [{ sku: 'LUM-2X4-8', quantity: lineQty + 1, unit_price: unitPrice }],
      },
    });
    expect(response.status()).toBe(400);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'Error');
    if (!isRecord(body)) {
      throw new Error('400 body was not an object');
    }
    expect(body.rule).toBe('overpayment_protection');
  });

  test('exposure stays zero after rejected invoice', { tag: '@e2e' }, async ({ request }) => {
    const response = await request.get(`/vendors/${vendorId}/exposure`);
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    await expectSchema(request, body, 'VendorExposure');
    if (!isRecord(body)) {
      throw new Error('exposure did not return an object');
    }
    expect(requireNumber(body, 'open_ap_liability')).toBe(0);
    expect(body.approved_invoices).toEqual([]);
  });

  test('accept correct invoice, match, and approve', { tag: '@e2e' }, async ({ request }) => {
    const create = await request.post('/invoices', {
      data: {
        po_id: poId,
        invoice_number: `INV-ok-${Date.now()}`,
        line_items: [{ sku: 'LUM-2X4-8', quantity: lineQty, unit_price: unitPrice }],
      },
    });
    expect(create.status()).toBe(201);
    const invoice: unknown = await create.json();
    await expectSchema(request, invoice, 'Invoice');
    if (!isRecord(invoice)) {
      throw new Error('POST /invoices did not return an object');
    }
    invoiceId = requireString(invoice, 'id');
    expect(requireNumber(invoice, 'total_amount')).toBe(invoiceTotal);

    const match = await request.post(`/invoices/${invoiceId}/match`);
    expect(match.status()).toBe(200);
    const matchBody: unknown = await match.json();
    await expectSchema(request, matchBody, 'MatchResult');

    const approve = await request.post(`/invoices/${invoiceId}/approve`);
    expect(approve.status()).toBe(200);
    const approveBody: unknown = await approve.json();
    await expectSchema(request, approveBody, 'ApproveResult');
    if (!isRecord(approveBody)) {
      throw new Error('approve did not return an object');
    }
    expect(requireNumber(approveBody, 'vendor_exposure')).toBe(invoiceTotal);

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

  test('reject invoice unit price above received value with no tolerance', { tag: '@e2e' }, async ({ request }) => {
    test.fail(true, 'BUG-1: invoice at 1010 accepted when received value is 1000');

    const overVendorId = await createFlowVendor(request, 'over-invoice-value');
    const createPo = await request.post('/purchase-orders', {
      data: {
        vendor_id: overVendorId,
        line_items: [{ sku: 'LUM-2X4-8', quantity: 1, unit_price: 1000 }],
      },
    });
    expect(createPo.status()).toBe(201);
    const poBody: unknown = await createPo.json();
    if (!isRecord(poBody)) {
      throw new Error('POST /purchase-orders did not return an object');
    }
    const overPoId = requireString(poBody, 'id');

    await request.post(`/purchase-orders/${overPoId}/submit`);
    const receive = await request.post(`/purchase-orders/${overPoId}/receive`, {
      data: { items: [{ sku: 'LUM-2X4-8', quantity: 1 }] },
    });
    expect(receive.status()).toBe(200);
    const receivedPo: unknown = await receive.json();
    if (!isRecord(receivedPo)) {
      throw new Error('receive did not return an object');
    }
    expect(requireNumber(receivedPo, 'received_value')).toBe(1000);

    const invoice = await request.post('/invoices', {
      data: {
        po_id: overPoId,
        invoice_number: `INV-over-value-${Date.now()}`,
        line_items: [{ sku: 'LUM-2X4-8', quantity: 1, unit_price: 1010 }],
      },
    });
    expect(invoice.status()).toBe(400);
    const invoiceErr: unknown = await invoice.json();
    await expectSchema(request, invoiceErr, 'Error');
    if (!isRecord(invoiceErr)) {
      throw new Error('400 body was not an object');
    }
    expect(invoiceErr.rule).toBe('overpayment_protection');
  });
});
