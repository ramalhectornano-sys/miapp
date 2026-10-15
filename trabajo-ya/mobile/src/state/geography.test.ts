import { test } from 'node:test';
import assert from 'node:assert/strict';
import { locationQueryKey, radiusLabel, sameSearchConfiguration, validGeoCandidate, validRadius } from './geography.ts';
import type { GeoCandidate, JobSearch, SearchProposal } from '../types';

// Coordinates are deliberately absent: a UI test must not supply a locality's
// supposed coordinates or stand in for a live geographic-provider check.
const proposal: SearchProposal = { title: 'Chofer en Rincón', role: 'Chofer', city: 'Rincón de los Sauces', province: 'Neuquén', country: 'Argentina', radius_km: 100, frequency: 'daily', time: '09:00', timezone: 'America/Argentina/Buenos_Aires', weekdays: [1], mode: 'manual' };
const search: JobSearch = { id: 'example-search', name: proposal.title, roles: [proposal.role], cities: [proposal.city], province: proposal.province, country: proposal.country, radius_km: 100, schedule_time: '09:00:00', timezone: proposal.timezone, frequency: 'daily', weekdays: [1], status: 'enabled', auto_apply: false, next_run_at: null };

test('un radio inválido o vacío no se convierte silenciosamente en una distancia', () => {
  assert.equal(validRadius(Number.NaN), false);
  for (const radius of [-1, 1001, Number.POSITIVE_INFINITY, 25.5]) assert.equal(validRadius(radius), false);
  for (const radius of [0, 10, 100, 1000]) assert.equal(validRadius(radius), true);
  assert.match(radiusLabel(100), /línea recta/);
  assert.match(radiusLabel(Number.NaN), /corregir/);
});

test('búsquedas con distinto radio o localidades homónimas no se confunden con una ya guardada', () => {
  assert.equal(sameSearchConfiguration(search, proposal), true);
  assert.equal(sameSearchConfiguration(search, { ...proposal, radius_km: 25 }), false);
  assert.equal(sameSearchConfiguration(search, { ...proposal, province: 'Mendoza' }), false);
  assert.equal(sameSearchConfiguration(search, { ...proposal, country: 'Chile' }), false);
  assert.equal(sameSearchConfiguration({ ...search, location_id: 'locality-a' }, { ...proposal, location_id: 'locality-b' }), false);
});

test('una localidad seleccionada se reconoce después de que el servidor normalice su nombre', () => {
  assert.equal(sameSearchConfiguration({ ...search, province: 'NEUQUEN', country: 'Argentina', location_id: 'locality-a' }, { ...proposal, province: '', location_id: 'locality-a' }), true);
  assert.equal(sameSearchConfiguration({ ...search, province: 'NEUQUEN' }, proposal), true);
});

test('editar país, provincia o localidad invalida la identidad de la comprobación anterior', () => {
  assert.notEqual(locationQueryKey(proposal), locationQueryKey({ ...proposal, province: 'Mendoza' }));
  assert.notEqual(locationQueryKey(proposal), locationQueryKey({ ...proposal, country: '' }));
  assert.notEqual(locationQueryKey(proposal), locationQueryKey({ ...proposal, city: 'Otra localidad' }));
});

test('no se seleccionan coincidencias sin identidad, ubicación o coordenadas numéricas válidas', () => {
  assert.equal(validGeoCandidate({ id: '', city: 'Sin validar', province: 'Sin validar', country: 'Argentina', latitude: 0, longitude: 0 } as GeoCandidate), false);
  assert.equal(validGeoCandidate({ id: 'invalid', city: 'Sin validar', province: 'Sin validar', country: 'Argentina', latitude: Number.NaN, longitude: 0 } as GeoCandidate), false);
  assert.equal(validGeoCandidate({ id: 'invalid', city: 'Sin validar', province: '', country: 'Argentina', latitude: 200, longitude: 0 } as GeoCandidate), false);
});
