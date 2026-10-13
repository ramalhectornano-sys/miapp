// Prueba SQL real en PostgreSQL embebido; instalar @electric-sql/pglite en supabase/.
import { PGlite } from '@electric-sql/pglite';
import { readFile, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const directory = path.dirname(fileURLToPath(import.meta.url));
const database = new PGlite();
try {
  await database.exec(await readFile(path.join(directory, 'bootstrap.sql'), 'utf8'));
  const migrations = (await readdir(path.join(directory, '../migrations'))).filter(name => name.endsWith('.sql')).sort();
  // Cada batería usa el contrato de su versión. 005 endurece intencionalmente
  // manual quota y freshness, por lo que los fixtures de 004 se prueban antes.
  const versionTests = {
    '202610120004_automatic_sending_policy.sql': ['security.sql', 'automatic_sending.sql'],
    '202610120005_daily_budget_and_followups.sql': ['daily_budget_and_followups.sql'],
  };
  for (const name of migrations) {
    await database.exec(await readFile(path.join(directory, '../migrations', name), 'utf8'));
    console.log(`Migración validada: ${name}`);
    for (const testName of versionTests[name] ?? []) {
      await database.exec(await readFile(path.join(directory, testName), 'utf8'));
      console.log(`Pruebas SQL superadas: ${testName}`);
    }
  }
} finally {
  await database.close();
}
