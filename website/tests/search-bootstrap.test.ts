import test from 'node:test';
import assert from 'node:assert/strict';
import { createSearchBootstrap, withinDeadline } from '../src/lib/search-bootstrap.ts';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function index(search = async () => ({ results: [{ data: async () => ({ url: '/en/docs/testing/', meta: {}, excerpt: '' }) }] })) {
  let destroyed = 0;
  return { search, destroy: async () => { destroyed++; }, get destroyed() { return destroyed; } };
}

test('intent warming and dialog open share one initialization and ready instance', async () => {
  const module = deferred<any>();
  const candidate = index();
  let imports = 0;
  const loader = createSearchBootstrap(async () => { imports++; return module.promise; }, 'en');
  const warming = loader.load();
  assert.equal(loader.load(), warming);
  module.resolve({ createInstance: () => candidate });
  assert.equal(await warming, candidate);
  assert.equal(await loader.load(), candidate);
  assert.equal(imports, 1);
});

test('cold initialization can exceed twelve seconds without being discarded', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const module = deferred<any>();
  const candidate = index();
  const loader = createSearchBootstrap(async () => module.promise, 'zh');
  const loading = loader.load();
  t.mock.timers.tick(12_001);
  module.resolve({ createInstance: () => candidate });
  assert.equal(await loading, candidate);
});

test('a failed readiness probe is disposed and the next attempt imports a fresh module', async () => {
  const bad = index(async () => { throw new Error('offline'); });
  const good = index();
  const paths: string[] = [];
  const loader = createSearchBootstrap(async (path) => {
    paths.push(path);
    return { createInstance: () => paths.length === 1 ? bad : good };
  }, 'en');
  await assert.rejects(loader.load(), /offline/);
  assert.equal(bad.destroyed, 1);
  assert.equal(await loader.load(), good);
  assert.notEqual(paths[0], paths[1]);
});

test('an import resolving after timeout cannot create or resurrect an abandoned index', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const module = deferred<any>();
  let creations = 0;
  const loader = createSearchBootstrap(async () => module.promise, 'en');
  const rejected = assert.rejects(loader.load(), /timed out/);
  t.mock.timers.tick(30_001);
  await rejected;
  module.resolve({ createInstance: () => { creations++; return index(); } });
  await Promise.resolve(); await Promise.resolve();
  assert.equal(creations, 0);
});

test('reset disposes a warmed index and never reuses it on retry', async () => {
  const candidates = [index(), index()];
  let attempt = 0;
  const loader = createSearchBootstrap(async () => ({ createInstance: () => candidates[attempt++] }), 'en');
  const first = await loader.load();
  loader.reset();
  const second = await loader.load();
  assert.notEqual(first, second);
  assert.equal(candidates[0].destroyed, 1);
});

test('interactive queries still time out at twelve seconds', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const pending = deferred<void>();
  const rejected = assert.rejects(withinDeadline(pending.promise, 12_000), /timed out/);
  t.mock.timers.tick(12_001);
  await rejected;
});
