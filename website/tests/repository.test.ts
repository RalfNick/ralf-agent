import test from 'node:test';
import assert from 'node:assert/strict';
import { markdownToHtml } from 'satteri';
import { repositoryUrl, repositoryLinks } from '../src/lib/repository.mjs';
import { checkRepositoryTargets } from '../scripts/check-repository-links.mjs';

test('repository links pin the published commit and retain section fragments', () => {
  assert.equal(repositoryUrl('docs/user-input.md#receipts-restart-and-session-occupancy'),
    'https://github.com/RalfNick/relf-agent/blob/ba1c81fca67e15e70c1d51d0f4ecbbbcbbb37239/docs/user-input.md#receipts-restart-and-session-occupancy');
  assert.match(repositoryUrl('docs', 'tree'), /\/tree\/[a-f0-9]{40}\/docs$/);
});

test('repository links refuse traversal, external targets and unsupported kinds', () => {
  for (const path of ['../secret', '/docs/x.md', 'docs/../x.md', 'https://example.com', 'docs/x.md?raw=1'])
    assert.throws(() => repositoryUrl(path));
  assert.throws(() => repositoryUrl('docs/x.md', 'edit'));
});

test('rendered Markdown uses the pinned ref for inline and reference-style links', () => {
  const result = markdownToHtml('[Input](repo:docs/user-input.md) [README][readme] [External](https://example.com)\n\n[readme]: repo:README.md#installation',
    { mdastPlugins: [repositoryLinks] });
  assert.ok(result.html.includes(`href="${repositoryUrl('docs/user-input.md')}"`));
  assert.ok(result.html.includes(`href="${repositoryUrl('README.md#installation')}"`));
  assert.ok(result.html.includes('href="https://example.com"'));
  assert.ok(!result.html.includes('href="repo:'));
});

test('build validation catches missing refs and unpublished files in outgoing links', () => {
  const problems = checkRepositoryTargets([
    'https://github.com/RalfNick/relf-agent/blob/main/docs/user-input.md',
    repositoryUrl('website/src/content/guides/en/overview.md'),
    repositoryUrl('docs/user-input.md'),
    repositoryUrl('docs', 'tree'),
  ], new Set(['docs/user-input.md']));
  assert.equal(problems.length, 2);
  assert.match(problems[0], /Unpinned/);
  assert.match(problems[1], /Unpublished/);
});

test('build validation rejects cached links to the previous repository after rename', () => {
  const problems = checkRepositoryTargets([
    'https://github.com/RalfNick/ralf-agent',
    'https://github.com/RalfNick/ralf-agent/blob/0b9b6c9682c40285d91994cd831aa93d7e814bf1/docs/user-input.md',
    'https://github.com/RalfNick/ralf-agent/tree/0b9b6c9682c40285d91994cd831aa93d7e814bf1/docs',
    'https://github.com/RalfNick/ralf-agent/releases/tag/v0.1.0a2',
    'https://github.com/RalfNick/ralf-agent-extra/blob/main/docs/user-input.md',
    repositoryUrl('docs/user-input.md'),
  ], new Set(['docs/user-input.md']));
  assert.equal(problems.length, 4);
  assert.ok(problems.every((problem) => problem.startsWith('Stale repository URL:')));
});
