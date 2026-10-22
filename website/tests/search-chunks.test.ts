import test from 'node:test';
import assert from 'node:assert/strict';
import { strictPagefindChunks } from '../scripts/strict-pagefind.mjs';

// Pagefind 1.5.2's index loader catches a failed chunk and resolves successfully.
const loader = 'async function load(){const url="index/example.pf_index";try{await fetchChunk()}catch(e){console.error(`Failed to load the index chunk ${url}:\n${e?.toString()}`);}}';

test('failed query chunks reject rather than becoming incomplete or empty results', async () => {
  const patched = strictPagefindChunks(loader);
  const load = new Function('fetchChunk', `${patched};return load`)(async () => { throw new Error('chunk unavailable'); });
  await assert.rejects(load(), /chunk unavailable/);
});

test('the compatibility guard preserves successful loads and fails closed on upstream changes', async () => {
  let loaded = false;
  const load = new Function('fetchChunk', `${strictPagefindChunks(loader)};return load`)(async () => { loaded = true; });
  await load();
  assert.equal(loaded, true);
  assert.throws(() => strictPagefindChunks('upgraded bundle without known loader'), /loader changed/);
});
