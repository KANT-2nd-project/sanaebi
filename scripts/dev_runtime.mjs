/** Local process owner: preflight once, then API/web and an optional indexer with shared dotenv. */
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export function commands(mode, watchIndex = false) {
  const uv = ['run', '--locked', '--env-file', '.env'];
  return [
    ['uv', [...uv, 'uvicorn', 'app.fastapi_main:app', '--reload', '--reload-dir', 'app', '--reload-dir', 'generation', '--host', '127.0.0.1', '--port', '8000']],
    ['npm', ['--prefix', 'web', 'run', 'dev', '--', '--hostname', '127.0.0.1', '--port', '3000']],
    ...(mode === 'rag' && watchIndex ? [['uv', [...uv, 'python', '-m', 'scripts.index_documents', '--watch']]] : []),
  ];
}

export function start() {
  const cwd = fileURLToPath(new URL('..', import.meta.url));
  const check = spawnSync('uv', ['run', '--locked', '--env-file', '.env', 'python', '-m', 'scripts.local_runtime', '--check', '--json'], { cwd, encoding: 'utf8' });
  let result;
  try { result = JSON.parse(check.stdout); } catch { /* safe generic diagnostic below */ }
  if (check.status !== 0 || !result?.ready) {
    console.error('Local runtime not ready:', result?.errors?.join(', ') || 'diagnostic failed');
    console.error('Run npm run setup:local (new database: add -- --init-documents).');
    process.exitCode = 1;
    return;
  }
  const children = new Set();
  const groups = new Set();
  let stopping = false;
  let timer;
  function stop(code) {
    if (stopping) return;
    stopping = true;
    process.exitCode = code;
    for (const child of groups) kill(child, 'SIGTERM');
    timer = setTimeout(() => {
      for (const child of groups) kill(child, 'SIGKILL');
    }, 5000);
    // Keep the parent alive until even orphaned grandchildren are reaped.
  }
  function kill(child, signal) {
    try { process.kill(-child.pid, signal); } catch (error) {
      if (error.code !== 'ESRCH') console.error('Could not stop child:', error.code);
    }
  }
  process.once('SIGINT', () => stop(130));
  process.once('SIGTERM', () => stop(143));
  for (const [command, args] of commands(result.mode, process.argv.includes('--watch-index'))) {
    const child = spawn(command, args, { cwd, stdio: 'inherit', detached: true });
    children.add(child);
    if (child.pid) groups.add(child);
    child.once('error', () => { children.delete(child); stop(1); });
    child.once('exit', (code) => {
      // The group can still contain grandchildren after the leader exits.
      kill(child, 'SIGTERM');
      children.delete(child);
      if (!stopping) stop(code || 1);

    });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) start();
