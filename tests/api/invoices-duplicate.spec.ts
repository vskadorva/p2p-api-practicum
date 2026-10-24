import { expect, test } from '@playwright/test';
import { expectSchema } from './helpers/schema';
import {
  createFlowVendor,
  isRecord,
  requireString,
} from './flows/flow-helpers';

test.describe('Duplicate invoice detection', () => {
  test.describe.configure({ mode: 'serial' });

  let vendorId: string;
  let poId: string;

  test('prepare vendor and fully received PO', { tag: '@e2e' }, async ({ request }) => {
    vendorId = await createFlowVendor(request, 'dup-invoice');
    const createPo = await request.post('/purchase-orders', {
      data: {
        vendor_id: vendorId,
        line_items: [{ sku: 'PLY-12-4X8', quantity: 4, unit_price: 22.4 }],
      },
    });
    expect(createPo.status()).toBe(201);
    const poBody: unknown = await createPo.json();
    await expectSchema(request, poBody, 'PurchaseOrder');
    if (!isRecord(poBody)) {
      throw new Error('POST /purchase-orders did not return an object');
    }
    poId = requireString(poBody, 'id');

    await request.post(`/purchase-orders/${poId}/submit`);
    const receive = await request.post(`/purchase-orders/${poId}/receive`, {
      data: { items: [{ sku: 'PLY-12-4X8', quantity: 4 }] },
    });
    expect(receive.status()).toBe(200);
  });

  test('reject second invoice when number differs only by case', { tag: '@e2e' }, async ({ request }) => {
    test.fail(true, 'BUG-2: inv-7 accepted after INV-7 for same vendor');

    const first = await request.post('/invoices', {
      data: {
        po_id: poId,
        invoice_number: 'INV-7',
        line_items: [{ sku: 'PLY-12-4X8', quantity: 1, unit_price: 22.4 }],
      },
    });
    expect(first.status()).toBe(201);

    const second = await request.post('/invoices', {
      data: {
        po_id: poId,
        invoice_number: 'inv-7',
        line_items: [{ sku: 'PLY-12-4X8', quantity: 1, unit_price: 22.4 }],
      },
    });
    expect(second.status()).toBe(400);
    const body: unknown = await second.json();
    await expectSchema(request, body, 'Error');
    if (!isRecord(body)) {
      throw new Error('400 body was not an object');
    }
    expect(body.rule).toBe('duplicate_invoice_detection');
  });

  test('reject invoice when number differs only by surrounding spaces', { tag: '@e2e' }, async ({ request }) => {
    test.fail(true, 'BUG-2: spaced INV-7 accepted after INV-7 for same vendor');

    const suffix = Date.now();
    const first = await request.post('/invoices', {
      data: {
        po_id: poId,
        invoice_number: `INV-SPC-${suffix}`,
        line_items: [{ sku: 'PLY-12-4X8', quantity: 1, unit_price: 22.4 }],
      },
    });
    expect(first.status()).toBe(201);

    const second = await request.post('/invoices', {
      data: {
        po_id: poId,
        invoice_number: ` INV-SPC-${suffix} `,
        line_items: [{ sku: 'PLY-12-4X8', quantity: 1, unit_price: 22.4 }],
      },
    });
    expect(second.status()).toBe(400);
    const body: unknown = await second.json();
    await expectSchema(request, body, 'Error');
    if (!isRecord(body)) {
      throw new Error('400 body was not an object');
    }
    expect(body.rule).toBe('duplicate_invoice_detection');
  });
});
