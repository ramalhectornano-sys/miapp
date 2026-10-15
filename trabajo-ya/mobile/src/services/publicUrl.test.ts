import { test } from 'node:test';
import assert from 'node:assert/strict';
import { publicOfferUrl } from './publicUrl.ts';

test('permite enlaces públicos de distintos portales y empresas, sin lista cerrada', () => {
  for (const url of ['https://www.linkedin.com/jobs/view/123', 'https://ar.computrabajo.com/ofertas-de-trabajo/ejemplo', 'https://empresa.com.ar/empleos/chofer?utm_source=busqueda']) assert.equal(publicOfferUrl(url), url);
});

test('rechaza direcciones privadas y esquemas que no representan una oferta pública', () => {
  for (const url of ['http://empresa.com/empleos', 'javascript:alert(1)', 'file:///tmp/cv.pdf', 'https://localhost/a', 'https://foo.internal/a', 'https://10.0.0.1/a', 'https://2130706433/a', 'https://0x7f000001/a', 'https://[::1]/a', 'https://usuario:clave@empresa.com/a', 'https://empresa.com:8443/a', 'https://empresa.com\\@localhost/a', 'https://empresa.com/\nlocalhost']) assert.equal(publicOfferUrl(url), null, url);
});

test('no abre URLs que contienen tokens ni secretos de autenticación', () => {
  for (const url of ['https://empresa.com/?access_token=privado', 'https://empresa.com/?client_secret=privado', 'https://empresa.com/?API_KEY=privado', 'https://empresa.com/#access_token=privado']) assert.equal(publicOfferUrl(url), null);
});
