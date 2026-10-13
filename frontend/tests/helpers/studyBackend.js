import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { fileURLToPath } from 'node:url'

async function exitedWithin(ended, milliseconds) {
  let timer
  try {
    return await Promise.race([
      ended.then(() => true),
      new Promise(resolve => { timer = setTimeout(() => resolve(false), milliseconds) }),
    ])
  } finally {
    clearTimeout(timer)
  }
}

export async function stopStudyBackend(child, ended, { graceMs = 45000, termMs = 10000 } = {}) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return
  // SIGINT 会展开 Python finally；旧版 Uvicorn 重新触发默认 SIGTERM 会跳过数据库清理。
  child.kill('SIGINT')
  if (await exitedWithin(ended, graceMs)) return
  child.kill('SIGTERM')
  if (await exitedWithin(ended, termMs)) return
  child.kill('SIGKILL')
  await exitedWithin(ended, 2000)
  throw new Error('测试后端退出超时，已强制退出；临时数据库清理未获确认，不能视为成功')
}

export async function startStudyBackend(t, { script = 'run_vocab_study_backend.py' } = {}) {
  const port = await new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port
      server.close(error => error ? reject(error) : resolve(port))
    })
  })
  const root = fileURLToPath(new URL('../../../', import.meta.url))
  const child = spawn(`${root}.venv/bin/python`, [`${root}backend/tests/${script}`, '--port', String(port)], {
    cwd: root,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, QUIZ_TEST_PARENT_PID: String(process.pid) },
  })
  let output = '', spawnError
  const capture = data => { output = (output + data).slice(-128 * 1024) }
  child.stdout.on('data', capture)
  child.stderr.on('data', capture)
  const ended = new Promise(resolve => {
    child.once('exit', resolve)
    child.once('error', error => { spawnError = error; resolve() })
  })
  let closing
  const cleanup = () => closing ??= stopStudyBackend(child, ended)
  t.after(cleanup)
  const origin = `http://127.0.0.1:${port}`
  const deadline = Date.now() + 15000
  try {
    while (Date.now() < deadline) {
      if (spawnError || child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`隔离后端启动失败：${spawnError?.message ?? output}`)
      }
      try {
        const response = await fetch(`${origin}/api/auth/me`, { signal: AbortSignal.timeout(1000) })
        await response.body?.cancel()
        if (response.status === 401) return origin
      } catch { /* 有界等待临时数据库与真实应用启动。 */ }
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    throw new Error(`隔离后端启动超时：${output}`)
  } catch (error) {
    await cleanup()
    throw error
  }
}
