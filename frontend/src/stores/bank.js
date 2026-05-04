import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '../api/client'

export const useBankStore = defineStore('bank', () => {
  const banks = ref([])
  const loading = ref(false)

  async function fetchBanks() {
    loading.value = true
    try {
      const res = await client.get('/banks')
      banks.value = res.data
    } finally {
      loading.value = false
    }
  }

  return { banks, loading, fetchBanks }
})
