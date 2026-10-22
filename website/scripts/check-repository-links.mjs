import { execFileSync } from 'node:child_process';
import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve, join } from 'node:path';
import { repositoryInfo } from '../src/lib/repository.mjs';

const repoRoot = fileURLToPath(new URL('../../', import.meta.url));
const previousRepository = 'https://github.com/RalfNick/ralf-agent';

export function checkRepositoryTargets(urls, files) {
  const problems = [];
  for (const value of new Set(urls)) {
    // Cached Markdown must not silently depend on the previous repository redirect.
    if (value === previousRepository || ['/', '?', '#'].some((separator) => value.startsWith(previousRepository + separator))) {
      problems.push(`Stale repository URL: ${value}`);
      continue;
    }
    if (!value.startsWith(`${repositoryInfo.url}/blob/`) && !value.startsWith(`${repositoryInfo.url}/tree/`)) continue;
    const suffix = value.slice(repositoryInfo.url.length + 1);
    const [kind, ref, ...parts] = suffix.split('/');
    const path = decodeURIComponent(parts.join('/').split('#')[0]);
    if (ref !== repositoryInfo.ref) problems.push(`Unpinned repository URL: ${value}`);
    else if (kind === 'blob' ? !files.has(path) : ![...files].some((file) => file.startsWith(`${path}/`)))
      problems.push(`Unpublished repository target: ${value}`);
  }
  return problems;
}

export function publishedFiles() {
  return new Set(execFileSync('git', ['ls-tree', '-r', '--name-only', repositoryInfo.ref],
    { cwd: repoRoot, encoding: 'utf8' }).trim().split('\n'));
}

async function htmlUrls(dir) {
  const urls = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) urls.push(...await htmlUrls(path));
    else if (entry.name.endsWith('.html')) {
      const html = await readFile(path, 'utf8');
      urls.push(...[...html.matchAll(/(?:href|src)="([^"]+)"/g)].map((m) => m[1].replaceAll('&amp;', '&')));
      if (/href="repo:/.test(html)) throw new Error(`Unresolved repository link in ${path}`);
    }
  }
  return urls;
}

export async function checkBuiltRepositoryLinks(dir) {
  const urls = await htmlUrls(dir);
  const problems = checkRepositoryTargets(urls, publishedFiles());
  if (problems.length) throw new Error(problems.join('\n'));
  const count = new Set(urls.filter((url) => url.startsWith(`${repositoryInfo.url}/blob/`) || url.startsWith(`${repositoryInfo.url}/tree/`))).size;
  console.log(`Repository targets: ${count} published paths checked at ${repositoryInfo.ref.slice(0, 12)}.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv.includes('--remote')) {
    const output = execFileSync('git', ['ls-remote', repositoryInfo.url, 'HEAD'],
      { cwd: repoRoot, encoding: 'utf8', env: { ...process.env, GIT_TERMINAL_PROMPT: '0' } });
    const remoteHead = output.match(/^([a-f0-9]{40})\s+HEAD/m)?.[1];
    if (!remoteHead) throw new Error('Cannot verify the remote documentation baseline.');
    execFileSync('git', ['merge-base', '--is-ancestor', repositoryInfo.ref, remoteHead], { cwd: repoRoot });
    console.log(`Published baseline verified against remote HEAD ${remoteHead.slice(0, 12)}.`);
  }
  await checkBuiltRepositoryLinks(resolve('dist'));
}
