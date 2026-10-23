import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, relative } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const origin = 'https://relfagent.com';
const hash = (data: Uint8Array) => createHash('sha256').update(data).digest('hex');
type Fetcher = (url: string, options?: RequestInit) => Promise<Response>;
interface Check { url: string; status?: number; attempts: number; passed: boolean; error?: string; sha256?: string }
interface Target { url: string; status: number[]; body?: Uint8Array; location?: string }

/** Verify the exact dist that Wrangler just published; default fetch verifies HTTPS certificates. */
export async function runLiveAcceptance({
  root = resolve('dist'), fetcher = fetch, attempts = 3, retryDelay = 1_000,
}: { root?: string; fetcher?: Fetcher; attempts?: number; retryDelay?: number } = {}) {
  const files = (await readdir(root, { recursive: true, withFileTypes: true }))
    .filter((entry) => entry.isFile() && !['_headers', '404.html'].includes(entry.name))
    .map((entry) => resolve(entry.parentPath, entry.name)).sort();
  const targets: Target[] = await Promise.all(files.map(async (file) => {
    const path = '/' + relative(root, file).replaceAll('\\', '/');
    return { url: origin + (path.endsWith('/index.html') ? path.slice(0, -10) : path), status: [200], body: await readFile(file) };
  }));
  for (const from of ['http://relfagent.com', 'http://www.relfagent.com', 'https://www.relfagent.com']) {
    for (const path of ['/', '/en/docs/api-reference/?utm_source=deploy&probe=1', '/zh/docs/quickstart/?q=approval%20resume&x=1']) {
      targets.push({ url: from + path, status: [301], location: origin + path });
    }
  }
  targets.push({ url: origin + '/__deployment_acceptance_missing__/', status: [404], body: await readFile(resolve(root, '404.html')) });
  targets.push({ url: origin + '/en/docs/quickstart', status: [301, 307, 308], location: origin + '/en/docs/quickstart/' });
  async function check(target: Target): Promise<Check> {
    let row: Check = { url: target.url, attempts: 0, passed: false };
    for (let attempt = 1; attempt <= attempts; attempt++) {
      row = { url: target.url, attempts: attempt, passed: false };
      let response: Response | undefined;
      try {
        response = await fetcher(target.url, { redirect: 'manual', signal: AbortSignal.timeout(20_000) });
        row.status = response.status;
        if (!target.status.includes(response.status)) throw new Error(`unexpected HTTP ${response.status}`);
        if (target.location) {
          const location = response.headers.get('location');
          if (!location || new URL(location, target.url).href !== target.location) throw new Error('redirect differs (path/query must be preserved)');
          await response.body?.cancel();
        } else {
          const body = new Uint8Array(await response.arrayBuffer());
          row.sha256 = hash(body);
          if (target.body && row.sha256 !== hash(target.body)) throw new Error('deployed content differs from this build');
        }
        row.passed = true;
        return row;
      } catch (error) {
        row.error = error instanceof Error ? error.message : String(error);
        if (attempt < attempts) await new Promise((done) => setTimeout(done, retryDelay));
      } finally {
        if (response?.body && !response.bodyUsed) await response.body.cancel().catch(() => {});
      }
    }
    return row;
  }
  let cursor = 0;
  const checks: Check[] = new Array(targets.length);
  await Promise.all(Array.from({ length: Math.min(4, targets.length) }, async () => {
    for (;;) {
      const i = cursor++;
      if (i >= targets.length) return;
      checks[i] = await check(targets[i]);
    }
  }));
  return { origin, assets: files.length, redirects: 9, checks, failures: checks.filter((row) => !row.passed) };
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try {
    if (process.env.PUBLIC_SITE_URL !== origin) throw new Error(`Production PUBLIC_SITE_URL must be ${origin}`);
    const report = { source_commit: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), checked_at: new Date().toISOString(), ...await runLiveAcceptance() };
    await mkdir('.wrangler', { recursive: true });
    await writeFile('.wrangler/live-acceptance.json', JSON.stringify(report, null, 2) + '\n');
    console.log('LIVE_ACCEPTANCE_META ' + JSON.stringify({ source_commit: report.source_commit, checked_at: report.checked_at, assets: report.assets, redirects: report.redirects }));
    for (const check of report.checks) console.log('LIVE_ACCEPTANCE_CHECK ' + JSON.stringify(check));
    console.log(`Live acceptance: ${report.assets} assets, ${report.redirects} redirects, custom 404 and trailing slash; ${report.failures.length} failures.`);
    if (report.failures.length) { console.error(JSON.stringify(report.failures, null, 2)); process.exitCode = 1; }
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
