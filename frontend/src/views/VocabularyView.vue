<template>
  <div class="relative">
    <h1 class="mb-6 text-2xl font-bold text-gray-900">单词本</h1>

    <!-- 统计卡片 -->
    <div class="mb-8 grid grid-cols-2 gap-4">
      <div class="rounded-lg bg-white p-5 shadow hover:shadow-md transition-shadow cursor-pointer"
        :class="{ 'ring-2 ring-indigo-500': activeTab === 'professional' }"
        @click="activeTab = 'professional'">
        <div class="text-sm text-gray-500">专业词汇</div>
        <div class="mt-1 text-2xl font-bold text-indigo-600">{{ stats.professional || 0 }}</div>
        <p class="mt-1 text-xs text-gray-400">CIPT 考试核心术语</p>
      </div>
      <div class="rounded-lg bg-white p-5 shadow hover:shadow-md transition-shadow cursor-pointer"
        :class="{ 'ring-2 ring-indigo-500': activeTab === 'personal' }"
        @click="activeTab = 'personal'">
        <div class="text-sm text-gray-500">我的单词本</div>
        <div class="mt-1 text-2xl font-bold text-emerald-600">{{ stats.personal || 0 }}</div>
        <p class="mt-1 text-xs text-gray-400">学习中收藏的单词</p>
      </div>
    </div>

    <!-- ========== 专业词汇 ========== -->
    <div v-if="activeTab === 'professional'">
      <div class="mb-4 flex items-center justify-between gap-2 flex-wrap">
        <h2 class="text-lg font-semibold text-gray-800">专业词汇</h2>
        <div class="flex items-center gap-2">
          <button v-if="isAdmin && untranslatedCount > 0" @click="batchTranslate" :disabled="translating"
            class="rounded-md bg-teal-500 px-3 py-1.5 text-sm text-white hover:bg-teal-600 disabled:opacity-50">
            {{ translating ? '翻译中...' : `批量翻译（${untranslatedCount}）` }}
          </button>
          <button v-if="isAdmin" @click="importIAPP" :disabled="importing"
            class="rounded-md bg-amber-500 px-3 py-1.5 text-sm text-white hover:bg-amber-600 disabled:opacity-50">
            {{ importing ? '导入中...' : '从 IAPP 导入' }}
          </button>
          <button v-if="isAdmin" @click="showAddForm = !showAddForm"
            class="rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-700">
            {{ showAddForm ? '取消' : '添加词汇' }}
          </button>
        </div>
      </div>

      <!-- 翻译进度 -->
      <div v-if="translating" class="mb-4 rounded-lg bg-teal-50 px-4 py-3 text-sm text-teal-700">
        正在批量翻译，每次 10 个... 剩余 {{ translateRemaining }} 个未翻译
      </div>

      <!-- 搜索框 -->
      <div class="mb-4">
        <input v-model="searchQuery" placeholder="搜索术语..."
          class="w-full rounded-md border border-gray-300 px-4 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
      </div>

      <!-- 管理员添加表单 -->
      <div v-if="showAddForm && isAdmin" class="mb-4 rounded-lg bg-white p-4 shadow">
        <div class="grid grid-cols-2 gap-3">
          <input v-model="newWord.term" placeholder="英文术语" class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          <input v-model="newWord.term_zh" placeholder="中文翻译" class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          <input v-model="newWord.definition" placeholder="英文释义（可选）" class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          <input v-model="newWord.definition_zh" placeholder="中文释义（可选）" class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
        </div>
        <button @click="addWord('professional')" :disabled="!newWord.term.trim()"
          class="mt-3 rounded-md bg-indigo-600 px-4 py-1.5 text-sm text-white hover:bg-indigo-700 disabled:opacity-50">
          确认添加
        </button>
      </div>

      <div v-if="loadingPro" class="text-center text-gray-500 py-12">加载中...</div>
      <div v-else-if="filteredProfessional.length === 0 && searchQuery" class="py-12 text-center text-gray-400">
        没有找到匹配「{{ searchQuery }}」的术语
      </div>
      <div v-else-if="professionalWords.length === 0" class="py-12 text-center text-gray-400">暂无专业词汇</div>
      <template v-else>
        <!-- A-Z 导航条 -->
        <div class="mb-4 flex flex-wrap gap-1" v-if="!searchQuery">
          <button v-for="letter in LETTERS" :key="letter"
            @click="scrollToLetter('pro', letter)"
            :disabled="!proGrouped[letter]"
            class="w-8 h-8 rounded-md text-xs font-semibold transition-colors flex items-center justify-center"
            :class="proActiveLetter === letter
              ? 'bg-indigo-600 text-white'
              : proGrouped[letter]
                ? 'bg-white text-gray-700 shadow hover:bg-indigo-50 hover:text-indigo-600'
                : 'text-gray-300 cursor-default'">
            {{ letter }}
          </button>
        </div>
        <!-- 分组列表 -->
        <div ref="proListRef">
          <template v-for="letter in LETTERS" :key="letter">
            <div v-if="proGrouped[letter]" :ref="el => setLetterRef('pro', letter, el)">
              <!-- 字母分隔头 -->
              <div v-if="!searchQuery"
                class="sticky top-0 z-10 -mx-1 px-3 py-1.5 mb-1 mt-3 first:mt-0 bg-gray-100/90 backdrop-blur-sm rounded-md">
                <span class="text-sm font-bold text-indigo-600">{{ letter }}</span>
                <span class="ml-2 text-xs text-gray-400">{{ proGrouped[letter].length }} 个</span>
              </div>
              <!-- 词汇卡片 -->
              <div class="space-y-2 mb-1">
                <div v-for="w in proGrouped[letter]" :key="w.id"
                  class="rounded-lg bg-white px-5 py-4 shadow cursor-pointer hover:shadow-md transition-shadow"
                  @click="toggleExpand(w.id)">
                  <div class="flex items-start justify-between">
                    <div class="flex-1 min-w-0">
                      <div class="flex items-baseline gap-2 flex-wrap">
                        <span class="font-semibold text-gray-900">{{ w.term }}</span>
                        <span v-if="w.term_zh" class="text-sm text-emerald-600">{{ w.term_zh }}</span>
                      </div>
                      <div v-if="w.definition || w.definition_zh" class="mt-1">
                        <p v-if="w.definition" class="text-sm text-gray-600"
                          :class="{ 'line-clamp-2': !expandedIds.has(w.id) }">{{ w.definition }}</p>
                        <p v-if="w.definition_zh" class="mt-0.5 text-sm text-emerald-600"
                          :class="{ 'line-clamp-2': !expandedIds.has(w.id) }">{{ w.definition_zh }}</p>
                      </div>
                    </div>
                    <div class="ml-3 flex flex-shrink-0 items-center gap-2">
                      <svg class="w-4 h-4 text-gray-300 transition-transform" :class="{ 'rotate-180': expandedIds.has(w.id) }"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                      <button v-if="isAdmin" @click.stop="deleteWord(w.id, 'professional')"
                        class="text-xs text-red-400 hover:text-red-600">删除</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>

    <!-- ========== 我的单词本 ========== -->
    <div v-if="activeTab === 'personal'">
      <div class="mb-4 flex items-center justify-between">
        <h2 class="text-lg font-semibold text-gray-800">我的单词本</h2>
        <button @click="showAddForm = !showAddForm"
          class="rounded-md bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700">
          {{ showAddForm ? '取消' : '添加单词' }}
        </button>
      </div>

      <!-- 添加表单 -->
      <div v-if="showAddForm" class="mb-4 rounded-lg bg-white p-4 shadow">
        <div class="grid grid-cols-2 gap-3">
          <input v-model="newWord.term" placeholder="英文单词/短语" class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          <input v-model="newWord.term_zh" placeholder="中文翻译" class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          <input v-model="newWord.definition" placeholder="英文释义（可选）" class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
          <input v-model="newWord.definition_zh" placeholder="中文释义（可选）" class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none" />
        </div>
        <button @click="addWord('personal')" :disabled="!newWord.term.trim()"
          class="mt-3 rounded-md bg-emerald-600 px-4 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-50">
          确认添加
        </button>
      </div>

      <div v-if="loadingPersonal" class="text-center text-gray-500 py-12">加载中...</div>
      <div v-else-if="personalWords.length === 0" class="py-12 text-center text-gray-400">还没有收藏单词，点击上方添加</div>
      <template v-else>
        <!-- A-Z 导航条 -->
        <div class="mb-4 flex flex-wrap gap-1">
          <button v-for="letter in LETTERS" :key="letter"
            @click="scrollToLetter('personal', letter)"
            :disabled="!personalGrouped[letter]"
            class="w-8 h-8 rounded-md text-xs font-semibold transition-colors flex items-center justify-center"
            :class="personalActiveLetter === letter
              ? 'bg-emerald-600 text-white'
              : personalGrouped[letter]
                ? 'bg-white text-gray-700 shadow hover:bg-emerald-50 hover:text-emerald-600'
                : 'text-gray-300 cursor-default'">
            {{ letter }}
          </button>
        </div>
        <!-- 分组列表 -->
        <div ref="personalListRef">
          <template v-for="letter in LETTERS" :key="letter">
            <div v-if="personalGrouped[letter]" :ref="el => setLetterRef('personal', letter, el)">
              <div class="sticky top-0 z-10 -mx-1 px-3 py-1.5 mb-1 mt-3 first:mt-0 bg-gray-100/90 backdrop-blur-sm rounded-md">
                <span class="text-sm font-bold text-emerald-600">{{ letter }}</span>
                <span class="ml-2 text-xs text-gray-400">{{ personalGrouped[letter].length }} 个</span>
              </div>
              <div class="space-y-2 mb-1">
                <div v-for="w in personalGrouped[letter]" :key="w.id"
                  class="rounded-lg bg-white px-5 py-4 shadow cursor-pointer hover:shadow-md transition-shadow"
                  @click="toggleExpand(w.id)">
                  <div class="flex items-start justify-between">
                    <div class="flex-1 min-w-0">
                      <div class="flex items-baseline gap-2 flex-wrap">
                        <span class="font-semibold text-gray-900">{{ w.term }}</span>
                        <span v-if="w.term_zh" class="text-sm text-emerald-600">{{ w.term_zh }}</span>
                      </div>
                      <div v-if="w.definition || w.definition_zh" class="mt-1">
                        <p v-if="w.definition" class="text-sm text-gray-600"
                          :class="{ 'line-clamp-2': !expandedIds.has(w.id) }">{{ w.definition }}</p>
                        <p v-if="w.definition_zh" class="mt-0.5 text-sm text-emerald-600"
                          :class="{ 'line-clamp-2': !expandedIds.has(w.id) }">{{ w.definition_zh }}</p>
                      </div>
                    </div>
                    <div class="ml-3 flex flex-shrink-0 items-center gap-2">
                      <svg class="w-4 h-4 text-gray-300 transition-transform" :class="{ 'rotate-180': expandedIds.has(w.id) }"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                      <button @click.stop="deleteWord(w.id, 'personal')"
                        class="text-xs text-red-400 hover:text-red-600">删除</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>

    <!-- 回到顶部按钮 -->
    <button v-show="showBackTop" @click="scrollToTop"
      class="fixed bottom-6 right-6 z-20 flex h-10 w-10 items-center justify-center rounded-full bg-indigo-600 text-white shadow-lg hover:bg-indigo-700 transition-colors">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
      </svg>
    </button>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useAuthStore } from '../stores/auth'
import client from '../api/client'

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ#'.split('')

const authStore = useAuthStore()
const isAdmin = authStore.isAdmin

const activeTab = ref('professional')
const stats = ref({})
const professionalWords = ref([])
const personalWords = ref([])
const loadingPro = ref(false)
const loadingPersonal = ref(false)
const showAddForm = ref(false)
const importing = ref(false)
const translating = ref(false)
const translateRemaining = ref(0)
const searchQuery = ref('')
const expandedIds = reactive(new Set())
const newWord = reactive({ term: '', term_zh: '', definition: '', definition_zh: '' })
const proActiveLetter = ref('')
const personalActiveLetter = ref('')
const showBackTop = ref(false)
const proListRef = ref(null)
const personalListRef = ref(null)

// 字母分区 DOM 引用
const letterRefs = { pro: {}, personal: {} }
function setLetterRef(tab, letter, el) {
  if (el) letterRefs[tab][letter] = el
}

// 获取首字母
function getFirstLetter(term) {
  if (!term) return '#'
  const ch = term.charAt(0).toUpperCase()
  return ch >= 'A' && ch <= 'Z' ? ch : '#'
}

// 按字母分组
function groupByLetter(words) {
  const groups = {}
  for (const w of words) {
    const letter = getFirstLetter(w.term)
    if (!groups[letter]) groups[letter] = []
    groups[letter].push(w)
  }
  return groups
}

const untranslatedCount = computed(() =>
  professionalWords.value.filter(w => !w.term_zh).length
)

const filteredProfessional = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return professionalWords.value
  return professionalWords.value.filter(w =>
    w.term.toLowerCase().includes(q) ||
    (w.term_zh && w.term_zh.includes(q)) ||
    (w.definition && w.definition.toLowerCase().includes(q))
  )
})

const proGrouped = computed(() => {
  if (searchQuery.value.trim()) {
    return groupByLetter(filteredProfessional.value)
  }
  return groupByLetter(professionalWords.value)
})

// 个人单词按字母排序后分组
const personalSorted = computed(() =>
  [...personalWords.value].sort((a, b) => a.term.localeCompare(b.term))
)

const personalGrouped = computed(() => groupByLetter(personalSorted.value))

// 滚动到指定字母
function scrollToLetter(tab, letter) {
  const el = letterRefs[tab][letter]
  if (!el) return
  if (tab === 'pro') proActiveLetter.value = letter
  else personalActiveLetter.value = letter
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function toggleExpand(id) {
  if (expandedIds.has(id)) expandedIds.delete(id)
  else expandedIds.add(id)
}

function resetForm() {
  newWord.term = ''
  newWord.term_zh = ''
  newWord.definition = ''
  newWord.definition_zh = ''
  showAddForm.value = false
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// 监听滚动，更新当前字母高亮和回到顶部按钮
function onScroll() {
  showBackTop.value = window.scrollY > 400
  const tab = activeTab.value === 'professional' ? 'pro' : 'personal'
  const refs = letterRefs[tab]
  let current = ''
  for (const letter of LETTERS) {
    const el = refs[letter]
    if (!el) continue
    const rect = el.getBoundingClientRect()
    if (rect.top <= 120) current = letter
  }
  if (current) {
    if (tab === 'pro') proActiveLetter.value = current
    else personalActiveLetter.value = current
  }
}

// 数据获取
async function fetchStats() {
  try {
    const res = await client.get('/vocab/stats')
    stats.value = res.data
  } catch {}
}

async function fetchProfessional() {
  loadingPro.value = true
  try {
    const res = await client.get('/vocab/professional')
    professionalWords.value = res.data
  } finally {
    loadingPro.value = false
  }
}

async function fetchPersonal() {
  loadingPersonal.value = true
  try {
    const res = await client.get('/vocab/personal')
    personalWords.value = res.data
  } finally {
    loadingPersonal.value = false
  }
}

async function addWord(type) {
  try {
    const url = type === 'professional' ? '/vocab/professional' : '/vocab/personal'
    const res = await client.post(url, { ...newWord })
    if (type === 'professional') {
      professionalWords.value.unshift(res.data)
      professionalWords.value.sort((a, b) => a.term.localeCompare(b.term))
    } else {
      personalWords.value.unshift(res.data)
    }
    stats.value[type] = (stats.value[type] || 0) + 1
    resetForm()
  } catch (e) {
    alert(e.response?.data?.error || '添加失败')
  }
}

async function deleteWord(id, type) {
  if (!confirm('确定要删除这个词汇吗？')) return
  try {
    const url = type === 'professional' ? `/vocab/professional/${id}` : `/vocab/personal/${id}`
    await client.delete(url)
    if (type === 'professional') {
      professionalWords.value = professionalWords.value.filter(w => w.id !== id)
    } else {
      personalWords.value = personalWords.value.filter(w => w.id !== id)
    }
    stats.value[type] = Math.max((stats.value[type] || 1) - 1, 0)
  } catch (e) {
    alert(e.response?.data?.error || '删除失败')
  }
}

async function importIAPP() {
  if (!confirm('从 IAPP 网站导入隐私专业词汇？已存在的术语会自动跳过。')) return
  importing.value = true
  try {
    const res = await client.post('/vocab/professional/import-iapp')
    alert(res.data.message)
    await fetchProfessional()
    await fetchStats()
  } catch (e) {
    alert(e.response?.data?.error || '导入失败')
  } finally {
    importing.value = false
  }
}

async function batchTranslate() {
  translating.value = true
  translateRemaining.value = untranslatedCount.value
  try {
    while (true) {
      const res = await client.post('/vocab/professional/batch-translate')
      translateRemaining.value = res.data.remaining
      if (res.data.remaining <= 0) break
    }
    await fetchProfessional()
  } catch (e) {
    alert(e.response?.data?.error || '翻译出错，已保存已完成部分')
    await fetchProfessional()
  } finally {
    translating.value = false
  }
}

watch(activeTab, () => {
  showAddForm.value = false
})

onMounted(() => {
  fetchStats()
  fetchProfessional()
  fetchPersonal()
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>
