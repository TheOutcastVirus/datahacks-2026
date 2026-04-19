import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const MAX_BUFFER_BYTES = 1024 * 1024;

type OrthogonalResult = {
  stdout: string;
  stderr: string;
};

export class OrthogonalCliError extends Error {
  stdout: string;
  stderr: string;

  constructor(message: string, stdout = '', stderr = '') {
    super(message);
    this.name = 'OrthogonalCliError';
    this.stdout = stdout;
    this.stderr = stderr;
  }
}

async function runOrthCommand(args: string[]) {
  try {
    const result = (await execFileAsync('orth', args, {
      cwd: process.cwd(),
      env: process.env,
      timeout: 30_000,
      maxBuffer: MAX_BUFFER_BYTES,
    })) as OrthogonalResult;

    return {
      stdout: result.stdout.trim(),
      stderr: result.stderr.trim(),
    };
  } catch (error) {
    const stdout =
      error && typeof error === 'object' && 'stdout' in error && typeof error.stdout === 'string'
        ? error.stdout.trim()
        : '';
    const stderr =
      error && typeof error === 'object' && 'stderr' in error && typeof error.stderr === 'string'
        ? error.stderr.trim()
        : '';
    const message =
      error instanceof Error ? error.message : 'Orthogonal CLI command failed.';

    throw new OrthogonalCliError(message, stdout, stderr);
  }
}

export function getOrthogonalSetupMessage(error: OrthogonalCliError) {
  const combined = `${error.stdout}\n${error.stderr}\n${error.message}`;

  if (/Not authenticated/i.test(combined)) {
    return 'Orthogonal is not authenticated. Run `orth login` in the project root, then retry.';
  }

  if (/spawn orth ENOENT/i.test(combined)) {
    return 'Orthogonal CLI is not installed on this machine. Install `@orth/cli` globally first.';
  }

  return combined.trim() || 'Orthogonal CLI request failed.';
}

export async function searchOrthogonalCapabilities(task: string) {
  const [skillSearch, apiSearch] = await Promise.all([
    runOrthCommand(['skills', 'search', task]),
    runOrthCommand(['api', 'search', task]),
  ]);

  return {
    skillSearch: skillSearch.stdout || skillSearch.stderr,
    apiSearch: apiSearch.stdout || apiSearch.stderr,
  };
}

export async function scrapeWithOrthogonal(url: string) {
  const { stdout, stderr } = await runOrthCommand([
    'run',
    'olostep',
    '/v1/scrapes',
    '-b',
    JSON.stringify({ url_to_scrape: url }),
  ]);

  return stdout || stderr;
}
