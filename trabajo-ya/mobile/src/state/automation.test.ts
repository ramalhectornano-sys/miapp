import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialDemoState } from './demo.ts';
import { sendingPermission } from './automation.ts';

const now = Date.parse('2026-10-12T12:00:00Z');
const search = () => ({ ...initialDemoState().searches[0]!, demo: false, auto_apply: true,
  consent_id: 'consent-example', consent_expires_at: '2026-10-13T12:00:00Z', consent_revoked_at: null });

test('los envíos diarios requieren permiso vigente y búsqueda activa', () => {
  assert.equal(sendingPermission(search(), now), 'active');
  assert.equal(sendingPermission({ ...search(), status: 'paused' }, now), 'paused');
  assert.equal(sendingPermission({ ...search(), auto_apply: false }, now), 'manual');
  assert.equal(sendingPermission({ ...search(), consent_id: null }, now), 'manual');
});
test('no se muestra un permiso activo después del vencimiento o revocación', () => {
  assert.equal(sendingPermission(search(), Date.parse(search().consent_expires_at)), 'expired');
  assert.equal(sendingPermission({ ...search(), consent_revoked_at: '2026-10-12T11:00:00Z' }, now), 'revoked');
});
test('sin evidencia del vencimiento se muestra pendiente de verificar', () => {
  assert.equal(sendingPermission({ ...search(), consent_expires_at: null }, now), 'unknown');
  assert.equal(sendingPermission({ ...search(), consent_expires_at: 'fecha inválida' }, now), 'unknown');
});
test('la demostración permanece identificada aunque tenga un permiso ilustrativo', () => {
  assert.equal(sendingPermission({ ...search(), demo: true }, now), 'demo');
});
