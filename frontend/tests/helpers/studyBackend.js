import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { fileURLToPath } from 'node:url'

export async function startStudyBackend(t, { script = 'run_vocab_study_backend.py' } = {}) {
  const port = await new Promise(resolve => {
    const server = createServer()
    server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(() => resolve(port)) })
  })
  const root = fileURLToPath(new URL('../../../', import.meta.url))
  const child = spawn(`${root}.venv/bin/python`, [`${root}backend/tests/${script}`, '--port', String(port)], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] })
  let output = ''
  child.stdout.on('data', data => { output += data })
  child.stderr.on('data', data => { output += data })
  const ended = new Promise(resolve => child.once('exit', resolve))
  t.after(async () => { if (child.exitCode === null) child.kill('SIGTERM'); await ended })
  const origin = `http://127.0.0.1:${port}`
  for (let attempt = 0; attempt < 150; attempt++) {
    if (child.exitCode !== null) throw new Error(`隔离后端启动失败：${output}`)
    try { if ((await fetch(`${origin}/api/auth/me`)).status === 401) return origin } catch { /* 等待临时数据库与真实应用启动 */ }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error(`隔离后端启动超时：${output}`)
}
