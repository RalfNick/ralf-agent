import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';

export type Runner = (
  command: string,
  args: string[],
  options: { cwd: string; env: NodeJS.ProcessEnv },
) => { status: number | null; error?: Error };

const website = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function runVerification({
  production = false,
  env = process.env,
  run = (command, args, options) => spawnSync(command, args, { ...options, stdio: 'inherit' }),
}: { production?: boolean; env?: NodeJS.ProcessEnv; run?: Runner } = {}): void {
  if (production && env.PUBLIC_SITE_URL !== 'https://relfagent.com') {
    throw new Error('Production PUBLIC_SITE_URL must be https://relfagent.com');
  }
  const childEnv = {
    ...env,
    ASTRO_TELEMETRY_DISABLED: '1',
    WRANGLER_SEND_METRICS: 'false',
    WRANGLER_LOG_PATH: env.WRANGLER_LOG_PATH || resolve(tmpdir(), `relf-website-verify-${process.pid}.log`),
  };
  const steps: [string, string[]][] = [
    ['npm', ['run', 'check']],
    ['npm', ['test']],
    ['npm', ['run', 'docs:check']],
    [env.PYTHON_BIN || 'python3', ['scripts/check-tutorials.py']],
    ['npm', ['run', 'build']],
    ['npm', ['run', 'docs:links', '--', '--remote']],
    ['npm', ['run', 'cf:check']],
  ];
  for (const [command, args] of steps) {
    console.log(`Website verification: ${command} ${args.join(' ')}`);
    const result = run(command, args, { cwd: website, env: childEnv });
    if (result.error || result.status !== 0) {
      throw new Error(`Website verification failed: ${command} ${args.join(' ')}`, { cause: result.error });
    }
  }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try {
    if (process.argv.slice(2).some((arg) => arg !== '--production')) throw new Error('Unknown verification option');
    runVerification({ production: process.argv.includes('--production') });
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
