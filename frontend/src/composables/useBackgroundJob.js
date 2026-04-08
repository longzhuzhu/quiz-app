import { onUnmounted, ref } from 'vue'
import client from '../api/client'

export function useBackgroundJob() {
  const job = ref(null)
  const polling = ref(false)
  let timerId = null

  function stopPolling() {
    if (timerId) {
      clearTimeout(timerId)
      timerId = null
    }
    polling.value = false
  }

  function clearJob() {
    stopPolling()
    job.value = null
  }

  async function fetchJob(jobId) {
    const res = await client.get(`/jobs/${jobId}`)
    job.value = res.data.job
    return job.value
  }

  function startPolling(jobId, { onFinished } = {}) {
    stopPolling()
    polling.value = true

    const tick = async () => {
      try {
        const current = await fetchJob(jobId)
        if (!current || ['completed', 'failed'].includes(current.status)) {
          polling.value = false
          if (onFinished) await onFinished(current)
          return
        }
        timerId = window.setTimeout(tick, 2000)
      } catch {
        stopPolling()
        if (job.value) {
          job.value = {
            ...job.value,
            status: 'unknown',
            status_message: '任务状态获取失败，可刷新页面后重试',
          }
        }
      }
    }

    tick()
  }

  async function createJob(payload, options = {}) {
    const res = await client.post('/jobs', payload)
    job.value = res.data.job
    if (job.value && ['queued', 'running'].includes(job.value.status)) {
      startPolling(job.value.id, options)
    } else {
      stopPolling()
    }
    return res.data
  }

  async function restoreActiveJob(params, options = {}) {
    stopPolling()
    const query = new URLSearchParams(params).toString()
    const res = await client.get(`/jobs/active?${query}`)
    job.value = res.data.job
    if (job.value && ['queued', 'running'].includes(job.value.status)) {
      startPolling(job.value.id, options)
    }
    return job.value
  }

  onUnmounted(stopPolling)

  return {
    job,
    polling,
    createJob,
    restoreActiveJob,
    stopPolling,
    clearJob,
  }
}
