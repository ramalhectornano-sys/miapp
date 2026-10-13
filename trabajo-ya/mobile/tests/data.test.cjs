const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const USER = '11111111-1111-4111-8111-111111111111';
const FIRST = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const SECOND = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const NEW = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const OLD_PHOTO = `${USER}/anterior.jpg`;
const asset = {
  uri: 'file:///foto.jpg', name: 'foto.jpg', mimeType: 'image/jpeg',
  file: { arrayBuffer: async () => Uint8Array.from([1, 2, 3]).buffer },
};

// Exercise the actual service code while replacing native modules and the
// Supabase transport. No real identity, file upload, or network request occurs.
function loadService(client) {
  const filename = path.join(__dirname, '../src/services/data.ts');
  const source = fs.readFileSync(filename, 'utf8');
  let code;
  try {
    const ts = require('typescript');
    code = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
  } catch (error) {
    if (error.code !== 'MODULE_NOT_FOUND') throw error;
    // Node 24 can run these transport tests before npm dependencies are present.
    // This fallback strips types; it is not a replacement for tsc validation.
    const { stripTypeScriptTypes } = require('node:module');
    const bindings = [];
    for (const item of source.matchAll(/^export (?:async )?(?:function|const) (\w+)/gm)) bindings.push(item[1]);
    code = stripTypeScriptTypes(source.replace(/^import .*;\n/gm, '').replace(/^export /gm, ''));
    code += `\nObject.assign(module.exports, { ${bindings.join(',')} });`;
    code = `const { Platform, FileSystem, Crypto, requireSession, requireSupabase, deleteResumeDocument, mapApplication } = require('test-mocks');\n${code}`;
  }
  const module = { exports: {} };
  const mocks = {
    Platform: { OS: 'web' }, FileSystem: {}, Crypto: { randomUUID: () => NEW },
    requireSession: async () => ({ user: { id: USER } }), requireSupabase: () => client,
    deleteResumeDocument: async () => ({ deleted: true }), mapApplication: row => row,
  };
  const requireMock = name => {
    if (name === 'test-mocks') return mocks;
    if (name === 'react-native') return { Platform: mocks.Platform };
    if (name === 'expo-file-system/legacy') return mocks.FileSystem;
    if (name === 'expo-crypto') return mocks.Crypto;
    if (name === './backend') return { deleteResumeDocument: mocks.deleteResumeDocument, mapApplication: mocks.mapApplication };
    if (name === './supabase') return { requireSession: mocks.requireSession, requireSupabase: mocks.requireSupabase };
    throw new Error(`Unexpected dependency: ${name}`);
  };
  vm.runInNewContext(code, { module, exports: module.exports, require: requireMock, Uint8Array, Map, Set, Date }, { filename });
  return module.exports;
}

function fixture(options = {}) {
  const events = [];
  const profile = {
    user_id: USER, full_name: 'Ana Pérez', city: 'Neuquén', headline: '',
    photo_path: OLD_PHOTO, preferred_resume_id: FIRST,
  };
  const resumes = [SECOND, FIRST].map(id => ({
    id, user_id: USER, name: id, original_filename: 'cv.pdf',
    object_path: `${USER}/${id}.pdf`, mime_type: 'application/pdf', size_bytes: 3,
    created_at: '2026-10-13T09:00:00Z',
  }));
  const tables = { profiles: [profile], resume_versions: resumes };
  const client = {
    from(table) {
      const query = { operation: 'read', filters: [], payload: undefined };
      const result = () => {
        const rows = (tables[table] || []).filter(row => query.filters.every(([key, value]) => row[key] === value));
        if (query.operation === 'update' || query.operation === 'upsert') {
          events.push({ name: `db-${query.operation}`, table, payload: query.payload });
          if (options.updateError) return { data: null, error: { code: '42501', message: 'Server rejected' } };
          if (options.updateAmbiguousError) return { data: null, error: { message: 'Response lost' } };
          if (table === 'profiles') Object.assign(profile, query.payload);
          if (options.updateCommitsButErrors) return { data: null, error: { message: 'Response lost after commit' } };
          return { data: table === 'profiles' ? [{ user_id: USER }] : [], error: null };
        }
        if (options.confirmationReadError && events.some(event => event.name === 'db-update' || event.name === 'rpc')) {
          return { data: null, error: { message: 'Read failed' } };
        }
        // Each PostgREST response is a snapshot, not a live database object.
        return { data: rows.map(row => ({ ...row })), error: null };
      };
      const builder = {
        select() { return builder; },
        eq(key, value) { query.filters.push([key, value]); return builder; },
        order() { return builder; }, limit() { return builder; },
        update(payload) { query.operation = 'update'; query.payload = payload; return builder; },
        upsert(payload) { query.operation = 'upsert'; query.payload = payload; return builder; },
        maybeSingle() { const value = result(); return Promise.resolve({ ...value, data: value.data?.[0] || null }); },
        then(resolve, reject) { return Promise.resolve(result()).then(resolve, reject); },
      };
      return builder;
    },
    rpc(name, args) {
      events.push({ name: 'rpc', rpc: name, args });
      return { single: async () => {
        if (options.registerError) return { data: null, error: { code: '42501', message: 'Registration rejected' } };
        if (options.registerAmbiguousError) return { data: null, error: { message: 'Response lost' } };
        const row = { id: args.p_id, user_id: USER, name: args.p_name, original_filename: args.p_original_filename,
          object_path: args.p_object_path, mime_type: args.p_mime_type, size_bytes: args.p_size_bytes,
          created_at: '2026-10-13T09:00:00Z' };
        resumes.unshift(row); profile.preferred_resume_id = row.id;
        if (options.registerCommitsButErrors) return { data: null, error: { message: 'Response lost after commit' } };
        return { data: row, error: null };
      } };
    },
    storage: { from(bucket) { return {
      upload: async (objectPath) => { events.push({ name: 'upload', bucket, path: objectPath }); return { error: null }; },
      remove: async paths => { events.push({ name: 'remove', bucket, paths }); return { error: null }; },
      createSignedUrl: async objectPath => {
        events.push({ name: 'signed-url', bucket, path: objectPath });
        return options.signedUrlError ? { data: null, error: { message: 'URL rejected' } }
          : { data: { signedUrl: `https://private.test/${objectPath}` }, error: null };
      },
    }; } },
  };
  return { client, events, profile, resumes };
}

test('signed URL failure preserves the previous photo and does not change the profile', async () => {
  const state = fixture({ signedUrlError: true });
  await assert.rejects(loadService(state.client).uploadPhoto(asset), /fotografía anterior se conserva/);
  assert.equal(state.profile.photo_path, OLD_PHOTO);
  assert.equal(state.events.some(event => event.name === 'db-update'), false);
  assert.deepEqual(state.events.filter(event => event.name === 'remove').map(event => Array.from(event.paths)), [[`${USER}/${NEW}.jpg`]]);
});

test('photo association rejection cleans the new upload and preserves the previous photo', async () => {
  const state = fixture({ updateError: true });
  await assert.rejects(loadService(state.client).uploadPhoto(asset), /fotografía anterior se conserva/);
  assert.equal(state.profile.photo_path, OLD_PHOTO);
  assert.deepEqual(state.events.filter(event => event.name === 'remove').map(event => Array.from(event.paths)), [[`${USER}/${NEW}.jpg`]]);
});

test('a usable private URL is obtained before replacing and deleting the previous photo', async () => {
  const state = fixture();
  const uploaded = await loadService(state.client).uploadPhoto(asset);
  assert.equal(uploaded.path, `${USER}/${NEW}.jpg`);
  assert.equal(uploaded.url, `https://private.test/${USER}/${NEW}.jpg`);
  assert.equal(state.profile.photo_path, uploaded.path);
  assert.deepEqual(state.events.map(event => event.name), ['upload', 'signed-url', 'db-update', 'remove']);
  assert.deepEqual(Array.from(state.events.at(-1).paths), [OLD_PHOTO]);
});

test('a lost photo update response is recovered only after the database confirms the new path', async () => {
  const state = fixture({ updateCommitsButErrors: true });
  const uploaded = await loadService(state.client).uploadPhoto(asset);
  assert.equal(uploaded.path, state.profile.photo_path);
  assert.deepEqual(state.events.filter(event => event.name === 'remove').map(event => Array.from(event.paths)), [[OLD_PHOTO]]);
});

test('an ambiguous photo update cannot trigger deletion of either private image', async () => {
  const state = fixture({ updateAmbiguousError: true });
  await assert.rejects(loadService(state.client).uploadPhoto(asset), /No se pudo confirmar/);
  assert.equal(state.events.some(event => event.name === 'remove'), false);
});

test('a failed photo confirmation preserves the new image even after a server rejection', async () => {
  const state = fixture({ updateError: true, confirmationReadError: true });
  await assert.rejects(loadService(state.client).uploadPhoto(asset), /No se pudo confirmar/);
  assert.equal(state.events.some(event => event.name === 'remove'), false);
});

test('saving an older text draft cannot overwrite the current photo or primary CV', async () => {
  const state = fixture();
  const saved = await loadService(state.client).saveProfile({ full_name: 'Ana actualizada', city: 'Zapala',
    headline: 'Chofer', photo_path: `${USER}/borrada.jpg`, experiences: [], credentials: [], references: [] });
  const write = state.events.find(event => event.name === 'db-upsert');
  assert.equal(Object.hasOwn(write.payload, 'photo_path'), false);
  assert.equal(Object.hasOwn(write.payload, 'preferred_resume_id'), false);
  assert.equal(saved.full_name, 'Ana actualizada');
  assert.equal(saved.photo_path, OLD_PHOTO);
  assert.equal(state.profile.preferred_resume_id, FIRST);
});

test('the account primary CV is loaded after recreating the service, even when it is older', async () => {
  const state = fixture();
  await loadService(state.client).makeDefaultResume(FIRST);
  const loaded = await loadService(state.client).loadState();
  assert.equal(loaded.resumes.find(resume => resume.is_default).id, FIRST);
  assert.equal(state.events.find(event => event.name === 'db-update').payload.preferred_resume_id, FIRST);
});

test('an absent primary CV falls back to the newest stored version', async () => {
  const state = fixture(); state.profile.preferred_resume_id = null;
  const loaded = await loadService(state.client).loadState();
  assert.equal(loaded.resumes.find(resume => resume.is_default).id, SECOND);
});

test('resume registration selects the primary CV through the transactional RPC', async () => {
  const state = fixture();
  const uploaded = await loadService(state.client).uploadResume({ ...asset, name: 'Chofer.pdf' });
  assert.equal(uploaded.id, NEW); assert.equal(uploaded.is_default, true);
  assert.equal(state.profile.preferred_resume_id, NEW);
  const rpc = state.events.find(event => event.name === 'rpc');
  assert.equal(rpc.rpc, 'register_resume_version');
  assert.equal(rpc.args.p_object_path, `${USER}/${NEW}.pdf`);
  assert.equal(rpc.args.p_size_bytes, 3);
});

test('resume registration failure cleans the uploaded object and retains the primary CV', async () => {
  const state = fixture({ registerError: true });
  await assert.rejects(loadService(state.client).uploadResume({ ...asset, name: 'Chofer.pdf' }), /se retiró el archivo/);
  assert.equal(state.profile.preferred_resume_id, FIRST);
  assert.deepEqual(state.events.filter(event => event.name === 'remove').map(event => Array.from(event.paths)), [[`${USER}/${NEW}.pdf`]]);
});

test('a lost registration response preserves and recovers the CV confirmed in the account', async () => {
  const state = fixture({ registerCommitsButErrors: true });
  const uploaded = await loadService(state.client).uploadResume({ ...asset, name: 'Chofer.pdf' });
  assert.equal(uploaded.id, NEW); assert.equal(uploaded.is_default, true);
  assert.equal(state.events.some(event => event.name === 'remove'), false);
});

test('an ambiguous registration does not delete an upload while its commit is uncertain', async () => {
  const state = fixture({ registerAmbiguousError: true });
  await assert.rejects(loadService(state.client).uploadResume({ ...asset, name: 'Chofer.pdf' }), /No se pudo confirmar/);
  assert.equal(state.events.some(event => event.name === 'remove'), false);
});

test('an unreadable registration confirmation preserves the CV for reconciliation', async () => {
  const state = fixture({ registerError: true, confirmationReadError: true });
  await assert.rejects(loadService(state.client).uploadResume({ ...asset, name: 'Chofer.pdf' }), /No se pudo confirmar/);
  assert.equal(state.events.some(event => event.name === 'remove'), false);
});
