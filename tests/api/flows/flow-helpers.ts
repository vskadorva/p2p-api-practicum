import { expect, type APIRequestContext } from '@playwright/test';
import { expectSchema } from '../helpers/schema';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function requireString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== 'string') {
    throw new Error(`Expected string at ${key}`);
  }
  return value;
}

export function requireNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== 'number') {
    throw new Error(`Expected number at ${key}`);
  }
  return value;
}

export function requireBoolean(record: Record<string, unknown>, key: string): boolean {
  const value = record[key];
  if (typeof value !== 'boolean') {
    throw new Error(`Expected boolean at ${key}`);
  }
  return value;
}

export async function createFlowVendor(request: APIRequestContext, label: string): Promise<string> {
  const response = await request.post('/vendors', { data: { name: `E2E ${label} ${Date.now()}` } });
  expect(response.status()).toBe(201);
  const body: unknown = await response.json();
  await expectSchema(request, body, 'Vendor');
  if (!isRecord(body)) {
    throw new Error('POST /vendors did not return an object');
  }
  return requireString(body, 'id');
}

export function sumGlLineAmounts(lines: unknown): number {
  if (!Array.isArray(lines)) {
    throw new Error('GL lines must be an array');
  }
  let total = 0;
  for (const line of lines) {
    if (!isRecord(line)) {
      throw new Error('GL line must be an object');
    }
    total += requireNumber(line, 'amount');
  }
  return total;
}
