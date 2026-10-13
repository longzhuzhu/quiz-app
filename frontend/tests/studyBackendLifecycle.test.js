import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'
import { startStudyBackend, stopStudyBackend } from './helpers/studyBackend.js'

function fakeChild(exitOn) {
  const child = new EventEmitter()
  Object.assign(child, { pid: 12345, exitCode: null, signalCode: null, signals: [] })
  const ended = new Promise(resolve => child.once('exit', resolve))
  child.kill = signal => {
    child.signals.push(signal)
    if (signal === exitOn) {
      queueMicrotask(() => {
        child.signalCode = signal
        child.emit('exit', null, signal)
      })
    }
    return true
  }
  return { child, ended }
}

test('测试后端优先用 SIGINT 退出，等待清理完成', async () => {
  const { child, ended } = fakeChild('SIGINT')
  await stopStudyBackend(child, ended, { graceMs: 10, termMs: 10 })
  assert.deepEqual(child.signals, ['SIGINT'])
})

test('已经退出的后端不重复发送信号', async () => {
  const { child } = fakeChild('SIGINT')
  child.exitCode = 0
  await stopStudyBackend(child, Promise.resolve(), { graceMs: 10, termMs: 10 })
  assert.deepEqual(child.signals, [])
})

test('SIGINT 超时后有界升级 SIGTERM，不无限等待', async () => {
  const { child, ended } = fakeChild('SIGTERM')
  await stopStudyBackend(child, ended, { graceMs: 5, termMs: 20 })
  assert.deepEqual(child.signals, ['SIGINT', 'SIGTERM'])
})

test('必须强制退出时显式失败，不把可能漏资源的强杀当成功', async () => {
  const { child, ended } = fakeChild('SIGKILL')
  await assert.rejects(stopStudyBackend(child, ended, { graceMs: 5, termMs: 5 }), /强制|forced|清理/)
  assert.deepEqual(child.signals, ['SIGINT', 'SIGTERM', 'SIGKILL'])
})

test('spawn 失败、没有子进程时无需发送信号', async () => {
  const { child } = fakeChild('SIGINT')
  child.pid = undefined
  await stopStudyBackend(child, Promise.resolve(), { graceMs: 10, termMs: 10 })
  assert.deepEqual(child.signals, [])
})

test('后端启动失败立即报错，收尾不悬挂', { timeout: 15000 }, async t => {
  await assert.rejects(startStudyBackend(t, { script: 'nonexistent_lifecycle_test_backend.py' }), /隔离后端启动失败/)
})
