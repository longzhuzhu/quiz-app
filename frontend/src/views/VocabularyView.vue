<template>
  <div class="relative">
    <h1 class="mb-6 text-2xl font-bold text-gray-900 dark:text-white">单词本</h1>

    <!-- 统计卡片 -->
    <div class="mb-8 grid gap-4 md:grid-cols-3">
      <div class="rounded-card-lg bg-white dark:bg-slate-800 p-5 shadow-card hover:shadow-card-hover transition-shadow cursor-pointer"
        :class="{ 'ring-2 ring-primary-500': activeTab === 'professional' }"
        @click="activeTab = 'professional'">
        <div class="text-sm text-gray-500 dark:text-gray-400">专业词汇</div>
        <div class="mt-1 text-2xl font-bold text-primary-600 dark:text-primary-400">{{ stats.professional || 0 }}</div>
        <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">CIPT 考试核心术语</p>
      </div>
      <div class="rounded-card-lg bg-white dark:bg-slate-800 p-5 shadow-card hover:shadow-card-hover transition-shadow cursor-pointer"
        :class="{ 'ring-2 ring-primary-500': activeTab === 'personal' }"
        @click="activeTab = 'personal'">
        <div class="text-sm text-gray-500 dark:text-gray-400">我的单词本</div>
        <div class="mt-1 text-2xl font-bold text-emerald-600 dark:text-emerald-400">{{ stats.personal || 0 }}</div>
        <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">学习中收藏的单词</p>
      </div>
      <div class="rounded-card-lg bg-white dark:bg-slate-800 p-5 shadow-card hover:shadow-card-hover transition-shadow cursor-pointer"
        :class="{ 'ring-2 ring-primary-500': activeTab === 'frequent' }"
        @click="activeTab = 'frequent'">
        <div class="text-sm text-gray-500 dark:text-gray-400">高频词汇</div>
        <div class="mt-1 text-2xl font-bold text-amber-600 dark:text-amber-400">{{ frequentTotal || 0 }}</div>
        <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">{{ selectedBankName ? `${selectedBankName} 的高频词与翻译` : '按题库查看导入词频与翻译' }}</p>
      </div>
    </div>

    <!-- ========== 专业词汇 ========== -->
    <div v-if="activeTab === 'professional'">
      <div class="mb-4 flex items-center justify-between gap-2 flex-wrap">
        <h2 class="text-lg font-semibold text-gray-800 dark:text-white">专业词汇</h2>
        <div class="flex items-center gap-2">
          <BaseButton v-if="isAdmin && untranslatedCount > 0" @click="batchTranslate" :disabled="translating" size="sm">
            {{ translating ? '翻译中...' : `批量翻译（${untranslatedCount}）` }}
          </BaseButton>
          <BaseButton v-if="isAdmin" @click="importIAPP" :disabled="importing" variant="secondary" size="sm">
            {{ importing ? '导入中...' : '从 IAPP 导入' }}
          </BaseButton>
          <BaseButton v-if="isAdmin" @click="showAddForm = !showAddForm" size="sm">
            {{ showAddForm ? '取消' : '添加词汇' }}
          </BaseButton>
        </div>
      </div>

      <!-- 翻译进度 -->
      <div v-if="translating" class="mb-4 rounded-card bg-teal-50 dark:bg-teal-900/20 px-4 py-3 text-sm text-teal-700 dark:text-teal-300">
        正在批量翻译，每次 10 个... 剩余 {{ translateRemaining }} 个未翻译
      </div>

      <!-- 搜索框 -->
      <div class="mb-4">
        <input v-model="searchQuery" placeholder="搜索术语..."
          class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-4 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
      </div>

      <!-- 管理员添加表单 -->
      <div v-if="showAddForm && isAdmin" class="mb-4 rounded-card-lg bg-white dark:bg-slate-800 p-4 shadow-card">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input v-model="newWord.term" placeholder="英文术语" class="rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          <input v-model="newWord.term_zh" placeholder="中文翻译" class="rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          <input v-model="newWord.definition" placeholder="英文释义（可选）" class="rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          <input v-model="newWord.definition_zh" placeholder="中文释义（可选）" class="rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
        </div>
        <BaseButton @click="addWord('professional')" :disabled="!newWord.term.trim()" size="sm" class="mt-3">
          确认添加
        </BaseButton>
      </div>

      <div v-if="loadingPro" class="text-center text-gray-500 dark:text-gray-400 py-12">加载中...</div>
      <div v-else-if="filteredProfessional.length === 0 && searchQuery" class="py-12 text-center text-gray-400 dark:text-gray-500">
        没有找到匹配「{{ searchQuery }}」的术语
      </div>
      <div v-else-if="professionalWords.length === 0" class="py-12 text-center text-gray-400 dark:text-gray-500">暂无专业词汇</div>
      <template v-else>
        <!-- A-Z 导航条 -->
        <div class="mb-4 flex flex-wrap gap-1" v-if="!searchQuery">
          <button v-for="letter in LETTERS" :key="letter"
            @click="scrollToLetter('pro', letter)"
            :disabled="!proGrouped[letter]"
            class="w-8 h-8 rounded-md text-xs font-semibold transition-colors flex items-center justify-center"
            :class="proActiveLetter === letter
              ? 'bg-primary-600 text-white dark:bg-primary-500'
              : proGrouped[letter]
                ? 'bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-300 shadow hover:bg-primary-50 dark:hover:bg-primary-900/30 hover:text-primary-600 dark:hover:text-primary-400'
                : 'text-gray-300 dark:text-gray-600 cursor-default'">
            {{ letter }}
          </button>
        </div>
        <!-- 分组列表 -->
        <div ref="proListRef">
          <template v-for="letter in LETTERS" :key="letter">
            <div v-if="proGrouped[letter]" :ref="el => setLetterRef('pro', letter, el)">
              <!-- 字母分隔头 -->
              <div v-if="!searchQuery"
                class="sticky top-0 z-10 -mx-1 px-3 py-1.5 mb-1 mt-3 first:mt-0 bg-gray-100/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-md">
                <span class="text-sm font-bold text-primary-600 dark:text-primary-400">{{ letter }}</span>
                <span class="ml-2 text-xs text-gray-400 dark:text-gray-500">{{ proGrouped[letter].length }} 个</span>
              </div>
              <!-- 词汇卡片 -->
              <div class="space-y-2 mb-1">
                <div v-for="w in proGrouped[letter]" :key="w.id"
                  class="rounded-card-lg bg-white dark:bg-slate-800 px-5 py-4 shadow-card cursor-pointer hover:shadow-card-hover transition-shadow"
                  @click="toggleExpand(w.id)">
                  <div class="flex items-start justify-between">
                    <div class="flex-1 min-w-0">
                      <div class="flex items-baseline gap-2 flex-wrap">
                        <span class="font-semibold text-gray-900 dark:text-white">{{ w.term }}</span>
                        <span v-if="w.term_zh" class="text-sm text-emerald-600 dark:text-emerald-400">{{ w.term_zh }}</span>
                      </div>
                      <div v-if="w.definition || w.definition_zh" class="mt-1">
                        <p v-if="w.definition" class="text-sm text-gray-600 dark:text-gray-400"
                          :class="{ 'line-clamp-2': !expandedIds.has(w.id) }">{{ w.definition }}</p>
                        <p v-if="w.definition_zh" class="mt-0.5 text-sm text-emerald-600 dark:text-emerald-400"
                          :class="{ 'line-clamp-2': !expandedIds.has(w.id) }">{{ w.definition_zh }}</p>
                      </div>
                    </div>
                    <div class="ml-3 flex flex-shrink-0 items-center gap-2">
                      <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 transition-transform" :class="{ 'rotate-180': expandedIds.has(w.id) }"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                      <BaseButton v-if="isAdmin" variant="danger" size="sm" @click.stop="confirmDeleteWord(w.id, 'professional')">
                        删除
                      </BaseButton>
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
        <h2 class="text-lg font-semibold text-gray-800 dark:text-white">我的单词本</h2>
        <BaseButton @click="showAddForm = !showAddForm" size="sm">
          {{ showAddForm ? '取消' : '添加单词' }}
        </BaseButton>
      </div>

      <!-- 添加表单 -->
      <div v-if="showAddForm" class="mb-4 rounded-card-lg bg-white dark:bg-slate-800 p-4 shadow-card">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input v-model="newWord.term" placeholder="英文单词/短语" class="rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          <input v-model="newWord.term_zh" placeholder="中文翻译" class="rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          <input v-model="newWord.definition" placeholder="英文释义（可选）" class="rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          <input v-model="newWord.definition_zh" placeholder="中文释义（可选）" class="rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
        </div>
        <BaseButton @click="addWord('personal')" :disabled="!newWord.term.trim()" size="sm" class="mt-3">
          确认添加
        </BaseButton>
      </div>

      <div v-if="loadingPersonal" class="text-center text-gray-500 dark:text-gray-400 py-12">加载中...</div>
      <div v-else-if="personalWords.length === 0" class="py-12 text-center text-gray-400 dark:text-gray-500">还没有收藏单词，点击上方添加</div>
      <template v-else>
        <!-- A-Z 导航条 -->
        <div class="mb-4 flex flex-wrap gap-1">
          <button v-for="letter in LETTERS" :key="letter"
            @click="scrollToLetter('personal', letter)"
            :disabled="!personalGrouped[letter]"
            class="w-8 h-8 rounded-md text-xs font-semibold transition-colors flex items-center justify-center"
            :class="personalActiveLetter === letter
              ? 'bg-primary-600 text-white dark:bg-primary-500'
              : personalGrouped[letter]
                ? 'bg-white dark:bg-slate-800 text-gray-700 dark:text-gray-300 shadow hover:bg-primary-50 dark:hover:bg-primary-900/30 hover:text-primary-600 dark:hover:text-primary-400'
                : 'text-gray-300 dark:text-gray-600 cursor-default'">
            {{ letter }}
          </button>
        </div>
        <!-- 分组列表 -->
        <div ref="personalListRef">
          <template v-for="letter in LETTERS" :key="letter">
            <div v-if="personalGrouped[letter]" :ref="el => setLetterRef('personal', letter, el)">
              <div class="sticky top-0 z-10 -mx-1 px-3 py-1.5 mb-1 mt-3 first:mt-0 bg-gray-100/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-md">
                <span class="text-sm font-bold text-primary-600 dark:text-primary-400">{{ letter }}</span>
                <span class="ml-2 text-xs text-gray-400 dark:text-gray-500">{{ personalGrouped[letter].length }} 个</span>
              </div>
              <div class="space-y-2 mb-1">
                <div v-for="w in personalGrouped[letter]" :key="w.id"
                  class="rounded-card-lg bg-white dark:bg-slate-800 px-5 py-4 shadow-card cursor-pointer hover:shadow-card-hover transition-shadow"
                  @click="toggleExpand(w.id)">
                  <div class="flex items-start justify-between">
                    <div class="flex-1 min-w-0">
                      <div class="flex items-baseline gap-2 flex-wrap">
                        <span class="font-semibold text-gray-900 dark:text-white">{{ w.term }}</span>
                        <span v-if="w.term_zh" class="text-sm text-emerald-600 dark:text-emerald-400">{{ w.term_zh }}</span>
                      </div>
                      <div v-if="w.definition || w.definition_zh" class="mt-1">
                        <p v-if="w.definition" class="text-sm text-gray-600 dark:text-gray-400"
                          :class="{ 'line-clamp-2': !expandedIds.has(w.id) }">{{ w.definition }}</p>
                        <p v-if="w.definition_zh" class="mt-0.5 text-sm text-emerald-600 dark:text-emerald-400"
                          :class="{ 'line-clamp-2': !expandedIds.has(w.id) }">{{ w.definition_zh }}</p>
                      </div>
                    </div>
                    <div class="ml-3 flex flex-shrink-0 items-center gap-2">
                      <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 transition-transform" :class="{ 'rotate-180': expandedIds.has(w.id) }"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                      <BaseButton variant="danger" size="sm" @click.stop="confirmDeleteWord(w.id, 'personal')">
                        删除
                      </BaseButton>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>

    <!-- ========== 高频词汇 ========== -->
    <div v-if="activeTab === 'frequent'">
      <div class="mb-4 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 class="text-lg font-semibold text-gray-800 dark:text-white">高频词汇</h2>
          <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">按题库查看导入题目中的高频英文词及中文翻译</p>
        </div>
        <select
          v-model="selectedBankId"
          class="min-w-[220px] rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-4 py-2 text-sm text-gray-900 dark:text-gray-100 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
        >
          <option :value="null" disabled>请选择题库</option>
          <option v-for="bank in banks" :key="bank.id" :value="bank.id">{{ bank.name }}</option>
        </select>
      </div>

      <div v-if="banks.length === 0" class="py-12 text-center text-gray-400 dark:text-gray-500">暂无题库，请先导入题库</div>
      <div v-else-if="loadingFrequent" class="py-12 text-center text-gray-500 dark:text-gray-400">加载中...</div>
      <div v-else-if="!selectedBankId" class="py-12 text-center text-gray-400 dark:text-gray-500">请选择题库查看高频词</div>
      <template v-else>
        <div class="mb-4 rounded-card-lg bg-white dark:bg-slate-800 p-5 shadow-card">
          <div class="flex items-start justify-between gap-4">
            <div>
              <div class="text-sm text-gray-500 dark:text-gray-400">当前题库</div>
              <div class="mt-1 text-lg font-semibold text-gray-900 dark:text-white">{{ selectedBankName }}</div>
            </div>
            <div class="text-right">
              <div class="text-sm text-gray-500 dark:text-gray-400">高频词条</div>
              <div class="mt-1 text-2xl font-bold text-amber-600 dark:text-amber-400">{{ frequentTotal }}</div>
              <div class="mt-1 text-xs text-gray-400 dark:text-gray-500">仅展示前 {{ frequentTopLimit }} 个高频词</div>
            </div>
          </div>
        </div>

        <div v-if="frequentWords.length === 0" class="py-12 text-center text-gray-400 dark:text-gray-500">当前题库暂无高频词，请先重新导入题库生成词频</div>
        <div v-else>
          <div class="space-y-3">
            <div
              v-for="(item, index) in frequentWords"
              :key="item.term"
              class="rounded-card-lg bg-white dark:bg-slate-800 px-5 py-4 shadow-card hover:shadow-card-hover transition-shadow"
            >
              <div class="flex items-center gap-4">
                <div class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-amber-100 text-sm font-semibold text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                  {{ pageStartIndex + index + 1 }}
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-baseline gap-2 flex-wrap">
                    <div class="font-semibold text-gray-900 dark:text-white">{{ item.term }}</div>
                    <div v-if="item.term_zh" class="text-sm text-emerald-600 dark:text-emerald-400">{{ item.term_zh }}</div>
                  </div>
                  <div class="mt-1 text-xs text-gray-500 dark:text-gray-400">在当前题库中出现 {{ item.frequency }} 次</div>
                </div>
                <div class="rounded-full bg-amber-50 px-3 py-1 text-sm font-medium text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
                  {{ item.frequency }} 次
                </div>
              </div>
            </div>
          </div>

          <div class="mt-5 flex items-center justify-between gap-3 rounded-card-lg bg-white dark:bg-slate-800 px-5 py-4 shadow-card flex-wrap">
            <div class="text-sm text-gray-500 dark:text-gray-400">
              第 {{ frequentPage }} / {{ frequentTotalPages }} 页，共 {{ frequentTotal }} 个词条
            </div>
            <div class="flex items-center gap-2 flex-wrap justify-end">
              <label class="text-sm text-gray-500 dark:text-gray-400">跳转到</label>
              <select
                v-model.number="frequentPage"
                class="min-w-[88px] rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                :disabled="loadingFrequent || frequentTotalPages <= 1"
              >
                <option v-for="page in frequentPageOptions" :key="page" :value="page">
                  第 {{ page }} 页
                </option>
              </select>
              <BaseButton variant="secondary" size="sm" :disabled="frequentPage <= 1 || loadingFrequent" @click="changeFrequentPage(frequentPage - 1)">
                上一页
              </BaseButton>
              <BaseButton variant="secondary" size="sm" :disabled="frequentPage >= frequentTotalPages || loadingFrequent" @click="changeFrequentPage(frequentPage + 1)">
                下一页
              </BaseButton>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- 回到顶部按钮 -->
    <button v-show="showBackTop" @click="scrollToTop"
      class="fixed bottom-20 md:bottom-6 right-6 z-20 flex h-10 w-10 items-center justify-center rounded-full bg-primary-600 dark:bg-primary-500 text-white shadow-lg hover:bg-primary-700 dark:hover:bg-primary-600 transition-colors">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
      </svg>
    </button>

    <!-- 删除确认对话框 -->
    <ConfirmDialog
      :open="deleteConfirm.open"
      title="删除词汇"
      message="确定要删除这个词汇吗？"
      confirm-text="删除"
      :danger="true"
      @confirm="doDeleteWord"
      @cancel="deleteConfirm.open = false"
    />

    <!-- 导入确认对话框 -->
    <ConfirmDialog
      :open="importConfirm.open"
      title="导入词汇"
      message="从 IAPP 网站导入隐私专业词汇？已存在的术语会自动跳过。"
      confirm-text="开始导入"
      @confirm="doImportIAPP"
      @cancel="importConfirm.open = false"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useBankStore } from '../stores/bank'
import client from '../api/client'
import { useToast } from '../composables/useToast'
import BaseButton from '../components/BaseButton.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ#'.split('')

const authStore = useAuthStore()
const bankStore = useBankStore()
const isAdmin = authStore.isAdmin
const toast = useToast()

const activeTab = ref('professional')
const stats = ref({})
const professionalWords = ref([])
const personalWords = ref([])
const banks = ref([])
const selectedBankId = ref(null)
const frequentWords = ref([])
const loadingPro = ref(false)
const loadingPersonal = ref(false)
const loadingFrequent = ref(false)
const frequentTotal = ref(0)
const frequentPage = ref(1)
const frequentPerPage = ref(20)
const frequentTotalPages = ref(1)
const frequentTopLimit = ref(5000)
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

// 删除确认状态
const deleteConfirm = reactive({ open: false, id: null, type: '' })
// 导入确认状态
const importConfirm = reactive({ open: false })

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

const selectedBankName = computed(() =>
  banks.value.find(bank => bank.id === selectedBankId.value)?.name || ''
)

const pageStartIndex = computed(() => (frequentPage.value - 1) * frequentPerPage.value)
const frequentPageOptions = computed(() =>
  Array.from({ length: frequentTotalPages.value }, (_, index) => index + 1)
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

async function fetchBanks() {
  await bankStore.fetchBanks()
  banks.value = bankStore.banks
  if (!selectedBankId.value && banks.value.length > 0) {
    selectedBankId.value = banks.value[0].id
  }
}

async function fetchFrequent() {
  if (!selectedBankId.value) {
    frequentWords.value = []
    frequentTotal.value = 0
    frequentTotalPages.value = 1
    return
  }

  loadingFrequent.value = true
  try {
    const res = await client.get('/vocab/frequent', {
      params: {
        bank_id: selectedBankId.value,
        page: frequentPage.value,
        per_page: frequentPerPage.value,
      },
    })
    frequentWords.value = res.data.items || []
    frequentTotal.value = res.data.summary?.total_terms || 0
    frequentTopLimit.value = res.data.summary?.top_terms_limit || 5000
    frequentTotalPages.value = res.data.pagination?.total_pages || 1
  } catch (e) {
    frequentWords.value = []
    frequentTotal.value = 0
    frequentTotalPages.value = 1
    toast.error(e.response?.data?.error || '加载高频词失败')
  } finally {
    loadingFrequent.value = false
  }
}

function changeFrequentPage(page) {
  if (page < 1 || page > frequentTotalPages.value || page === frequentPage.value) return
  frequentPage.value = page
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
    toast.success('词汇添加成功')
  } catch (e) {
    toast.error(e.response?.data?.error || '添加失败')
  }
}

// 删除确认流程
function confirmDeleteWord(id, type) {
  deleteConfirm.id = id
  deleteConfirm.type = type
  deleteConfirm.open = true
}

async function doDeleteWord() {
  const { id, type } = deleteConfirm
  deleteConfirm.open = false
  try {
    const url = type === 'professional' ? `/vocab/professional/${id}` : `/vocab/personal/${id}`
    await client.delete(url)
    if (type === 'professional') {
      professionalWords.value = professionalWords.value.filter(w => w.id !== id)
    } else {
      personalWords.value = personalWords.value.filter(w => w.id !== id)
    }
    stats.value[type] = Math.max((stats.value[type] || 1) - 1, 0)
    toast.success('词汇已删除')
  } catch (e) {
    toast.error(e.response?.data?.error || '删除失败')
  }
}

// 导入确认流程
function importIAPP() {
  importConfirm.open = true
}

async function doImportIAPP() {
  importConfirm.open = false
  importing.value = true
  try {
    const res = await client.post('/vocab/professional/import-iapp')
    toast.success(res.data.message)
    await fetchProfessional()
    await fetchStats()
  } catch (e) {
    toast.error(e.response?.data?.error || '导入失败')
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
    toast.success('批量翻译完成')
    await fetchProfessional()
  } catch (e) {
    toast.error(e.response?.data?.error || '翻译出错，已保存已完成部分')
    await fetchProfessional()
  } finally {
    translating.value = false
  }
}

watch(activeTab, () => {
  showAddForm.value = false
})

watch(selectedBankId, () => {
  if (frequentPage.value !== 1) {
    frequentPage.value = 1
    return
  }
  fetchFrequent()
})

watch(frequentPage, fetchFrequent)

onMounted(async () => {
  await fetchBanks()
  fetchStats()
  fetchProfessional()
  fetchPersonal()
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>
