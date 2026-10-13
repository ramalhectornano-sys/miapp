import { test } from 'node:test';
import assert from 'node:assert/strict';
import { initialPreferenceState, isDarkTheme, preferenceReducer, readPreference } from './preference.ts';

test('restaurar una preferencia guardada mantiene el tema elegido frente a cambios del dispositivo', () => {
  for (const preference of ['light', 'dark'] as const) {
    const state = preferenceReducer(initialPreferenceState(), { type: 'hydrate', saved: preference });
    assert.equal(state.ready, true);
    assert.equal(state.preference, preference);
    assert.equal(isDarkTheme(state.preference, 'light'), preference === 'dark');
    assert.equal(isDarkTheme(state.preference, 'dark'), preference === 'dark');
  }
});

test('Según el dispositivo responde a cambios de tema y permite volver a esa opción', () => {
  let state = preferenceReducer(initialPreferenceState(), { type: 'hydrate', saved: 'system' });
  assert.equal(isDarkTheme(state.preference, 'light'), false);
  assert.equal(isDarkTheme(state.preference, 'dark'), true);
  state = preferenceReducer(state, { type: 'select', preference: 'light' });
  assert.equal(isDarkTheme(state.preference, 'dark'), false);
  state = preferenceReducer(state, { type: 'select', preference: 'system' });
  assert.equal(isDarkTheme(state.preference, 'dark'), true);
  assert.equal(isDarkTheme(state.preference, null), false);
});

test('una selección durante la carga tiene prioridad sobre el valor antiguo guardado', () => {
  let state = initialPreferenceState();
  state = preferenceReducer(state, { type: 'select', preference: 'dark' });
  state = preferenceReducer(state, { type: 'select', preference: 'light' });
  state = preferenceReducer(state, { type: 'hydrate', saved: 'dark' });
  assert.equal(state.ready, true);
  assert.equal(state.preference, 'light');
});

test('preferencias guardadas ausentes o inválidas usan el tema del dispositivo', () => {
  for (const saved of [null, undefined, '', 'oscuro', '{}', true, 0]) {
    assert.equal(readPreference(saved), 'system');
    const state = preferenceReducer(initialPreferenceState(), { type: 'hydrate', saved });
    assert.equal(state.ready, true);
    assert.equal(isDarkTheme(state.preference, 'dark'), true);
  }
});

test('initialDark sigue disponible como tema inicial cuando no hay una preferencia guardada', () => {
  assert.equal(preferenceReducer(initialPreferenceState(true), { type: 'hydrate', saved: null }).preference, 'dark');
  assert.equal(preferenceReducer(initialPreferenceState(false), { type: 'hydrate', saved: null }).preference, 'light');
  assert.equal(preferenceReducer(initialPreferenceState(true), { type: 'hydrate', saved: 'light' }).preference, 'light');
});
