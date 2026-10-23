import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runLiveAcceptance } from '../scripts/check-live.ts';

async function fixture(t: { after(fn: () => Promise<void>): void }) {
  const root = await mkdtemp(join(tmpdir(), 'relf-live-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await writeFile(join(root, 'index.html'), '<h1>Relf-Agent</h1>');
  await writeFile(join(root, '404.html'), '<h1>Missing</h1>');
  await writeFile(join(root, '_headers'), '/*\n X-Frame-Options: DENY');
  return root;
}
function response(url: string): Response {
  const parsed = new URL(url);
  if (parsed.protocol === 'http:' || parsed.hostname === 'www.relfagent.com') {
    return new Response(null, { status: 301, headers: { location: `https://relfagent.com${parsed.pathname}${parsed.search}` } });
  }
  if (parsed.pathname === '/__deployment_acceptance_missing__/') return new Response('<h1>Missing</h1>', { status: 404 });
  if (parsed.pathname === '/en/docs/quickstart') return new Response(null, { status: 308, headers: { location: '/en/docs/quickstart/' } });
  return new Response('<h1>Relf-Agent</h1>');
}

test('live acceptance checks deployed bytes, custom 404, TLS fetches and nine canonical redirects', async (t) => {
  const calls: string[] = [];
  const report = await runLiveAcceptance({ root: await fixture(t), attempts: 1, fetcher: async (url) => { calls.push(url); return response(url); } });
  assert.equal(report.assets, 1);
  assert.equal(report.redirects, 9);
  assert.equal(report.checks.length, 12);
  assert.equal(report.failures.length, 0);
  assert.ok(calls.includes('https://www.relfagent.com/en/docs/api-reference/?utm_source=deploy&probe=1'));
  assert.ok(!calls.some((url) => url.endsWith('/_headers')));
});

test('a successful HTTP status cannot conceal a stale deployment', async (t) => {
  const report = await runLiveAcceptance({ root: await fixture(t), attempts: 1, fetcher: async (url) => url === 'https://relfagent.com/' ? new Response('old site') : response(url) });
  assert.equal(report.failures.length, 1);
  assert.match(report.failures[0].error ?? '', /content differs/);
});

test('a www redirect must retain the query string', async (t) => {
  const report = await runLiveAcceptance({ root: await fixture(t), attempts: 1, fetcher: async (url) => url.includes('www.relfagent.com/en/docs/api-reference/') ? new Response(null, { status: 301, headers: { location: 'https://relfagent.com/en/docs/api-reference/' } }) : response(url) });
  assert.equal(report.failures.length, 2);
  assert.ok(report.failures.every((row) => row.error?.includes('redirect differs')));
});

test('transient fetch failure retries while retaining the final result and attempt count', async (t) => {
  let first = true;
  const report = await runLiveAcceptance({ root: await fixture(t), attempts: 2, retryDelay: 0, fetcher: async (url) => {
    if (url === 'https://relfagent.com/' && first) { first = false; throw new Error('TLS request failed'); }
    return response(url);
  } });
  assert.equal(report.failures.length, 0);
  assert.equal(report.checks.find((row) => row.url === 'https://relfagent.com/')?.attempts, 2);
});
