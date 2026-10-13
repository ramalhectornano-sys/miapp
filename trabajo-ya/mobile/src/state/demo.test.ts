import { test } from 'node:test';
import assert from 'node:assert/strict';
import { demoChat, demoSearch, initialDemoState } from './demo.ts';

test('la demostración no contiene confirmaciones ni postulaciones enviadas', () => {
  const state = initialDemoState();
  assert.ok(state.applications.every(a => a.demo && a.status === 'pending' && !a.provider_message_id));
  assert.ok(state.searches.every(s => s.demo && !s.last_run_at && !s.next_run_at && !s.auto_apply));
});
test('interpreta el ejemplo sin habilitar envíos ni afirmar ejecución', () => {
  const result = demoChat('Buscá empleos de chofer en Rincón de los Sauces todos los días a las 9 de la mañana. Enviá mi CV.');
  assert.equal(result.proposal?.role, 'chofer');
  assert.equal(result.proposal?.city, 'Rincón de los Sauces');
  assert.equal(result.proposal?.time, '09:00');
  assert.equal(result.proposal?.mode, 'automatic');
  const search = demoSearch(result.proposal!);
  assert.equal(search.auto_apply, false);
  assert.equal(search.last_run_at, null);
});
test('agenda semanal usa días ISO y pide información que falta', () => {
  assert.deepEqual(demoChat('Buscá trabajos de electricista en Neuquén los lunes y viernes a las 14:30').proposal?.weekdays, [1,5]);
  assert.equal(demoChat('Buscá trabajos de electricista en Neuquén cada semana a las 9').proposal, undefined);
  assert.equal(demoChat('Buscá trabajos de chofer en Neuquén').proposal, undefined);
  assert.equal(demoChat('Buscá trabajos de chofer en Neuquén a las 29:90').proposal, undefined);
});
test('el estado inicial no comparte datos mutables entre sesiones', () => {
  const first = initialDemoState(); first.profile.full_name = 'Editado';
  assert.equal(initialDemoState().profile.full_name, 'Martín Pérez');
});
