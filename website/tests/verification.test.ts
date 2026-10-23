import test from 'node:test';
import assert from 'node:assert/strict';
import { runVerification, type Runner } from '../scripts/verify.ts';

test('failed checks stop before a production build or deployment preflight', () => {
  const calls: string[] = [];
  const run: Runner = (command, args) => {
    calls.push([command, ...args].join(' '));
    return { status: args.includes('docs:check') ? 1 : 0 };
  };
  assert.throws(() => runVerification({ production: true, env: { PUBLIC_SITE_URL: 'https://relfagent.com' }, run }), /docs:check/);
  assert.deepEqual(calls, ['npm run check', 'npm test', 'npm run docs:check']);
});

test('production validation rejects a missing or different origin before running anything', () => {
  let calls = 0;
  const run: Runner = () => { calls++; return { status: 0 }; };
  for (const origin of [undefined, 'https://preview.example', 'http://relfagent.com']) {
    assert.throws(() => runVerification({ production: true, env: { PUBLIC_SITE_URL: origin }, run }), /PUBLIC_SITE_URL/);
  }
  assert.equal(calls, 0);
});

test('one successful validation uses the same origin for checks, tutorials, build and dry run', () => {
  const calls: string[] = [];
  const run: Runner = (command, args, options) => {
    assert.equal(options.env.PUBLIC_SITE_URL, 'https://relfagent.com');
    assert.equal(options.env.ASTRO_TELEMETRY_DISABLED, '1');
    calls.push([command, ...args].join(' '));
    return { status: 0 };
  };
  runVerification({ production: true, env: { PUBLIC_SITE_URL: 'https://relfagent.com', PYTHON_BIN: '/verified/python' }, run });
  assert.deepEqual(calls, [
    'npm run check', 'npm test', 'npm run docs:check',
    '/verified/python scripts/check-tutorials.py', 'npm run build',
    'npm run docs:links -- --remote', 'npm run cf:check',
  ]);
  assert.ok(!calls.some((call) => call.includes('wrangler deploy')));
});
