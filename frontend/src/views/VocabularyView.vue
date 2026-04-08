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
          <BaseButton
            v-if="isAdmin && professionalUntranslatedCount > 0"
            @click="batchTranslate"
            :disabled="professionalJob && ['queued', 'running'].includes(professionalJob.status)"
            size="sm"
          >
            {{ professionalJob && ['queued', 'running'].includes(professionalJob.status) ? '后台执行中...' : `批量翻译（${professionalUntranslatedCount}）` }}
          </BaseButton>
          <BaseButton v-if="isAdmin" @click="importIAPP" :disabled="importing" variant="secondary" size="sm">
            {{ importing ? '导入中...' : '从 IAPP 导入' }}
          </BaseButton>
          <BaseButton v-if="isAdmin" @click="showAddForm = !showAddForm" size="sm">
            {{ showAddForm ? '取消' : '添加词汇' }}
          </BaseButton>
        </div>
      </div>

      <div
        v-if="professionalJob && ['queued', 'running', 'failed'].includes(professionalJob.status)"
        class="mb-4 rounded-card bg-teal-50 dark:bg-teal-900/20 px-4 py-3 text-sm text-teal-700 dark:text-teal-300"
      >
        <div class="font-medium">后台异步翻译，刷新页面不会中断</div>
        <div class="mt-1">{{ getJobStatusMessage(professionalJob) }}</div>
        <div class="mt-1">已处理 {{ professionalJob.progress_done }} / {{ professionalJob.progress_total }}，第 {{ professionalJob.attempt_count || 0 }} / {{ professionalJob.max_attempts }} 次</div>
      </div>

      <!-- 搜索框 -->
      <div class="mb-4">
        <input v-model="searchQuery" placeholder="搜索术语..."
          class="w-full rounded-card border border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-4 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
      </div>

      <div class="mb-4 flex flex-wrap gap-2">
        <button
          v-for="option in masteredFilterOptions"
          :key="`professional-${option.value}`"
          class="rounded-full px-3 py-1.5 text-sm font-medium transition-colors"
          :class="professionalMasteredFilter === option.value
            ? 'bg-primary-600 text-white dark:bg-primary-500'
            : 'bg-white text-gray-600 shadow-card hover:text-primary-600 dark:bg-slate-800 dark:text-gray-300 dark:hover:text-primary-400'"
          @click="professionalMasteredFilter = option.value"
        >
          {{ option.label }}
        </button>
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
                  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
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
                    <div class="flex w-full items-center gap-2 flex-wrap justify-start sm:ml-3 sm:w-auto sm:flex-shrink-0 sm:justify-end">
                      <span
                        v-if="w.is_mastered"
                        class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
                      >
                        已掌握
                      </span>
                      <BaseButton
                        v-if="w.can_mark_mastered"
                        :variant="w.is_mastered ? 'secondary' : 'primary'"
                        size="sm"
                        :loading="Boolean(vocabProgressLoading[`professional:${w.id}`])"
                        @click.stop="toggleVocabMastery(w, 'professional')"
                      >
                        {{ w.is_mastered ? '取消掌握' : '掌握' }}
                      </BaseButton>
                      <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 transition-transform" :class="{ 'rotate-180': expandedIds.has(w.id) }"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                      <BaseButton v-if="w.can_delete" variant="danger" size="sm" @click.stop="confirmDeleteWord(w.id, 'professional')">
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

      <div class="mb-4 flex flex-wrap gap-2">
        <button
          v-for="option in masteredFilterOptions"
          :key="`personal-${option.value}`"
          class="rounded-full px-3 py-1.5 text-sm font-medium transition-colors"
          :class="personalMasteredFilter === option.value
            ? 'bg-primary-600 text-white dark:bg-primary-500'
            : 'bg-white text-gray-600 shadow-card hover:text-primary-600 dark:bg-slate-800 dark:text-gray-300 dark:hover:text-primary-400'"
          @click="personalMasteredFilter = option.value"
        >
          {{ option.label }}
        </button>
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
                  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
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
                    <div class="flex w-full items-center gap-2 flex-wrap justify-start sm:ml-3 sm:w-auto sm:flex-shrink-0 sm:justify-end">
                      <span
                        v-if="w.is_mastered"
                        class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
                      >
                        已掌握
                      </span>
                      <BaseButton
                        v-if="w.can_mark_mastered"
                        :variant="w.is_mastered ? 'secondary' : 'primary'"
                        size="sm"
                        :loading="Boolean(vocabProgressLoading[`personal:${w.id}`])"
                        @click.stop="toggleVocabMastery(w, 'personal')"
                      >
                        {{ w.is_mastered ? '取消掌握' : '掌握' }}
                      </BaseButton>
                      <svg class="w-4 h-4 text-gray-300 dark:text-gray-600 transition-transform" :class="{ 'rotate-180': expandedIds.has(w.id) }"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                      <BaseButton
                        v-if="w.can_delete"
                        variant="danger"
                        size="sm"
                        @click.stop="confirmDeleteWord(w.id, 'personal')"
                      >
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

        <div class="mb-4 flex flex-wrap gap-2">
          <button
            v-for="option in masteredFilterOptions"
            :key="`frequent-${option.value}`"
            class="rounded-full px-3 py-1.5 text-sm font-medium transition-colors"
            :class="frequentMasteredFilter === option.value
              ? 'bg-primary-600 text-white dark:bg-primary-500'
              : 'bg-white text-gray-600 shadow-card hover:text-primary-600 dark:bg-slate-800 dark:text-gray-300 dark:hover:text-primary-400'"
            @click="setFrequentMasteredFilter(option.value)"
          >
            {{ option.label }}
          </button>
        </div>

        <div class="mb-4 flex items-center justify-between gap-2 flex-wrap">
          <div class="text-sm text-gray-500 dark:text-gray-400">未翻译词条：{{ frequentUntranslatedCount }}</div>
          <BaseButton
            v-if="isAdmin && selectedBankId && frequentUntranslatedCount > 0"
            size="sm"
            :disabled="frequentJob && ['queued', 'running'].includes(frequentJob.status)"
            @click="batchTranslateFrequent"
          >
            {{ frequentJob && ['queued', 'running'].includes(frequentJob.status) ? '后台执行中...' : `批量翻译（${frequentUntranslatedCount}）` }}
          </BaseButton>
        </div>

        <div
          v-if="frequentJob && ['queued', 'running', 'failed'].includes(frequentJob.status)"
          class="mb-4 rounded-card bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-700 dark:text-amber-300"
        >
          <div class="font-medium">后台异步翻译，刷新页面不会中断</div>
          <div class="mt-1">{{ getJobStatusMessage(frequentJob) }}</div>
          <div class="mt-1">已处理 {{ frequentJob.progress_done }} / {{ frequentJob.progress_total }}，第 {{ frequentJob.attempt_count || 0 }} / {{ frequentJob.max_attempts }} 次</div>
        </div>

        <div v-if="frequentWords.length === 0" class="py-12 text-center text-gray-400 dark:text-gray-500">当前题库暂无高频词，请先重新导入题库生成词频</div>
        <div v-else>
          <div class="space-y-3">
            <div
              v-for="(item, index) in frequentWords"
              :key="item.term"
              class="rounded-card-lg bg-white dark:bg-slate-800 px-5 py-4 shadow-card hover:shadow-card-hover transition-shadow"
            >
              <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
                <div class="min-w-0 flex-1">
                  <div class="flex items-baseline gap-2 flex-wrap">
                    <div class="font-semibold text-gray-900 dark:text-white">{{ item.term }}</div>
                    <div v-if="item.term_zh" class="text-sm text-emerald-600 dark:text-emerald-400">{{ item.term_zh }}</div>
                    <span class="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
                      {{ item.frequency }} 次
                    </span>
                    <span
                      v-if="item.is_mastered"
                      class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
                    >
                      已掌握
                    </span>
                  </div>
                </div>
                <div class="flex w-full flex-wrap items-center justify-start gap-2 sm:w-auto sm:justify-end">
                  <BaseButton
                    v-if="item.can_mark_mastered"
                    :variant="item.is_mastered ? 'secondary' : 'primary'"
                    size="sm"
                    :loading="Boolean(frequentProgressLoading[item.term])"
                    @click="toggleFrequentMastery(item)"
                  >
                    {{ item.is_mastered ? '已掌握' : '掌握' }}
                  </BaseButton>
                  <BaseButton
                    v-if="item.can_delete"
                    variant="danger"
                    size="sm"
                    :loading="Boolean(frequentDeleteLoading[item.term])"
                    @click="confirmDeleteWord(null, 'frequent', { term: item.term, bankId: selectedBankId })"
                  >
                    删除
                  </BaseButton>
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
import { useBackgroundJob } from '../composables/useBackgroundJob'
import BaseButton from '../components/BaseButton.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ#'.split('')

const authStore = useAuthStore()
const bankStore = useBankStore()
const isAdmin = authStore.isAdmin
const toast = useToast()

const professionalJobState = useBackgroundJob()
const professionalJob = professionalJobState.job
const frequentJobState = useBackgroundJob()
const frequentJob = frequentJobState.job

const activeTab = ref('professional')
const stats = ref({})
const professionalWords = ref([])
const personalWords = ref([])
const professionalUntranslatedCount = ref(0)
const professionalMasteredFilter = ref('all')
const personalMasteredFilter = ref('all')
const frequentMasteredFilter = ref('all')
const banks = ref([])
const selectedBankId = ref(null)
const frequentWords = ref([])
const frequentUntranslatedCount = ref(0)
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
const searchQuery = ref('')
const expandedIds = reactive(new Set())
const newWord = reactive({ term: '', term_zh: '', definition: '', definition_zh: '' })
const proActiveLetter = ref('')
const personalActiveLetter = ref('')
const showBackTop = ref(false)
const proListRef = ref(null)
const personalListRef = ref(null)
let frequentListRequestVersion = 0
let frequentSummaryRequestVersion = 0

// 删除确认状态
const deleteConfirm = reactive({ open: false, id: null, type: '', term: '', bankId: null })
// 导入确认状态
const importConfirm = reactive({ open: false })
const vocabProgressLoading = reactive({})
const frequentProgressLoading = reactive({})
const frequentDeleteLoading = reactive({})
const masteredFilterOptions = [
  { value: 'all', label: '全部' },
  { value: 'unmastered', label: '未掌握' },
  { value: 'mastered', label: '已掌握' },
]

// 字母分区 DOM 引用
const letterRefs = { pro: {}, personal: {} }
function setLetterRef(tab, letter, el) {
  if (el) letterRefs[tab][letter] = el
}

// 获取首字母
function wordNeedsTranslation(word) {
  if (!word?.term_zh?.trim()) return true
  if (word?.definition?.trim() && !word?.definition_zh?.trim()) return true
  return false
}

function getFailedJobMessage(job) {
  const baseMessage = job?.status_message?.trim() || '任务已自动执行 3 次仍失败'
  if (baseMessage.includes('可重新点击继续翻译剩余未翻译内容')) {
    return baseMessage
  }
  return `${baseMessage}，可重新点击继续翻译剩余未翻译内容`
}

function getJobStatusMessage(job) {
  if (!job) return '任务正在后台执行，可离开页面后稍后回来查看'
  if (job.status === 'failed') return getFailedJobMessage(job)
  return job.status_message || '任务正在后台执行，可离开页面后稍后回来查看'
}

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

const selectedBankName = computed(() =>
  banks.value.find(bank => bank.id === selectedBankId.value)?.name || ''
)

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
    const res = await client.get('/vocab/professional', {
      params: buildMasteredFilterParams(professionalMasteredFilter.value),
    })
    professionalWords.value = res.data
  } finally {
    loadingPro.value = false
  }
}

async function refreshProfessionalTranslationCount() {
  try {
    const res = await client.get('/vocab/professional')
    professionalUntranslatedCount.value = (res.data || []).filter(wordNeedsTranslation).length
  } catch {}
}

async function fetchPersonal() {
  loadingPersonal.value = true
  try {
    const res = await client.get('/vocab/personal', {
      params: buildMasteredFilterParams(personalMasteredFilter.value),
    })
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
    frequentUntranslatedCount.value = 0
    return
  }

  const bankId = selectedBankId.value
  const page = frequentPage.value
  const masteredFilter = frequentMasteredFilter.value
  const requestVersion = ++frequentListRequestVersion
  loadingFrequent.value = true
  try {
    const res = await client.get('/vocab/frequent', {
      params: {
        bank_id: bankId,
        page,
        per_page: frequentPerPage.value,
        ...buildMasteredFilterParams(masteredFilter),
      },
    })

    if (
      requestVersion !== frequentListRequestVersion ||
      bankId !== selectedBankId.value ||
      page !== frequentPage.value ||
      masteredFilter !== frequentMasteredFilter.value
    ) {
      return
    }

    const nextItems = res.data.items || []
    const nextTotal = res.data.summary?.total_terms || 0
    const nextTotalPages = res.data.pagination?.total_pages || 1
    if (nextItems.length === 0 && page > 1 && nextTotalPages < page) {
      frequentPage.value = nextTotalPages
      return
    }
    frequentWords.value = nextItems
    frequentTotal.value = nextTotal
    frequentTopLimit.value = res.data.summary?.top_terms_limit || 5000
    frequentTotalPages.value = nextTotalPages
  } catch (e) {
    if (
      requestVersion !== frequentListRequestVersion ||
      bankId !== selectedBankId.value ||
      page !== frequentPage.value ||
      masteredFilter !== frequentMasteredFilter.value
    ) {
      return
    }

    frequentWords.value = []
    frequentTotal.value = 0
    frequentTotalPages.value = 1
    toast.error(e.response?.data?.error || '加载高频词失败')
  } finally {
    if (
      requestVersion === frequentListRequestVersion &&
      bankId === selectedBankId.value &&
      page === frequentPage.value &&
      masteredFilter === frequentMasteredFilter.value
    ) {
      loadingFrequent.value = false
    }
  }
}

async function refreshFrequentTranslationCount(bankId = selectedBankId.value) {
  if (!bankId) {
    frequentUntranslatedCount.value = 0
    return 0
  }

  const requestVersion = ++frequentSummaryRequestVersion
  try {
    const res = await client.get('/vocab/frequent', {
      params: {
        bank_id: bankId,
        page: 1,
        per_page: 1,
      },
    })

    if (requestVersion !== frequentSummaryRequestVersion || bankId !== selectedBankId.value) {
      return null
    }

    frequentUntranslatedCount.value = res.data.summary?.untranslated_terms || 0
    return frequentUntranslatedCount.value
  } catch {
    if (requestVersion !== frequentSummaryRequestVersion || bankId !== selectedBankId.value) {
      return null
    }

    frequentUntranslatedCount.value = 0
    return 0
  }
}

async function toggleVocabMastery(item, type) {
  const nextState = !item.is_mastered
  const loadingKey = `${type}:${item.id}`
  vocabProgressLoading[loadingKey] = true
  try {
    const res = await client.put(`/vocab/items/${item.id}/progress`, {
      is_mastered: nextState,
    })
    if (type === 'professional') {
      await fetchProfessional()
    } else {
      await fetchPersonal()
    }
    toast.success(res.data.message || (nextState ? '已标记为掌握' : '已取消掌握'))
  } catch (e) {
    toast.error(e.response?.data?.error || '更新掌握状态失败')
  } finally {
    vocabProgressLoading[loadingKey] = false
  }
}

async function toggleFrequentMastery(item) {
  const nextState = !item.is_mastered
  frequentProgressLoading[item.term] = true
  try {
    const res = await client.put('/vocab/frequent-items/progress', {
      bank_id: selectedBankId.value,
      term: item.term,
      is_mastered: nextState,
    })
    await fetchFrequent()
    toast.success(res.data.message || (nextState ? '已标记为掌握' : '已取消掌握'))
  } catch (e) {
    toast.error(e.response?.data?.error || '更新掌握状态失败')
  } finally {
    frequentProgressLoading[item.term] = false
  }
}

function changeFrequentPage(page) {
  if (page < 1 || page > frequentTotalPages.value || page === frequentPage.value) return
  frequentPage.value = page
}

function setFrequentMasteredFilter(value) {
  if (frequentMasteredFilter.value === value) return
  frequentMasteredFilter.value = value
}

async function addWord(type) {
  try {
    const url = type === 'professional' ? '/vocab/professional' : '/vocab/personal'
    const res = await client.post(url, { ...newWord })
    if (type === 'professional') {
      professionalWords.value.unshift(res.data)
      professionalWords.value.sort((a, b) => a.term.localeCompare(b.term))
      professionalUntranslatedCount.value += wordNeedsTranslation(res.data) ? 1 : 0
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
function confirmDeleteWord(id, type, options = {}) {
  deleteConfirm.id = id
  deleteConfirm.type = type
  deleteConfirm.term = options.term || ''
  deleteConfirm.bankId = options.bankId || null
  deleteConfirm.open = true
}

async function doDeleteWord() {
  const { id, type, term, bankId } = deleteConfirm
  deleteConfirm.open = false
  try {
    if (type === 'frequent') {
      frequentDeleteLoading[term] = true
      await client.delete('/vocab/frequent-items', {
        params: {
          bank_id: bankId,
          term,
        },
      })
      await Promise.all([fetchFrequent(), refreshFrequentTranslationCount(bankId)])
    } else {
      const url = type === 'professional' ? `/vocab/professional/${id}` : `/vocab/personal/${id}`
      await client.delete(url)
      if (type === 'professional') {
        const removedWord = professionalWords.value.find(w => w.id === id)
        professionalWords.value = professionalWords.value.filter(w => w.id !== id)
        if (removedWord && wordNeedsTranslation(removedWord)) {
          professionalUntranslatedCount.value = Math.max(professionalUntranslatedCount.value - 1, 0)
        }
      } else {
        personalWords.value = personalWords.value.filter(w => w.id !== id)
      }
      stats.value[type] = Math.max((stats.value[type] || 1) - 1, 0)
    }
    if (type !== 'frequent') {
      toast.success('词汇已删除')
    } else {
      toast.success('词汇已删除')
    }
  } catch (e) {
    toast.error(e.response?.data?.error || '删除失败')
  } finally {
    if (type === 'frequent' && term) {
      frequentDeleteLoading[term] = false
    }
    deleteConfirm.id = null
    deleteConfirm.type = ''
    deleteConfirm.term = ''
    deleteConfirm.bankId = null
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
    await refreshProfessionalTranslationCount()
    await fetchStats()
  } catch (e) {
    toast.error(e.response?.data?.error || '导入失败')
  } finally {
    importing.value = false
  }
}

async function batchTranslate() {
  try {
    const result = await professionalJobState.createJob(
      { job_type: 'professional_vocab_translate' },
      {
        onFinished: async (job) => {
          await fetchProfessional()
          await refreshProfessionalTranslationCount()
          if (job?.status === 'completed') {
            toast.success('任务完成，已自动刷新未翻译数量')
          } else if (job?.status === 'failed') {
            toast.error(getFailedJobMessage(job))
          }
        },
      },
    )

    if (!result) return

    if (result.result === 'no_work') {
      toast.success(result.message)
      await fetchProfessional()
      await refreshProfessionalTranslationCount()
      return
    }
    if (result.result === 'created') {
      toast.success('后台异步翻译已启动，刷新页面不会中断')
    } else if (result.result === 'existing') {
      toast.success(result.message || '已复用现有后台任务，刷新页面不会中断')
    }
  } catch (e) {
    toast.error(e.response?.data?.error || '创建后台翻译任务失败')
  }
}

async function restoreProfessionalJob() {
  try {
    await professionalJobState.restoreActiveJob(
      { job_type: 'professional_vocab_translate' },
      {
        onFinished: async (job) => {
          await fetchProfessional()
          await refreshProfessionalTranslationCount()
          if (job?.status === 'failed') {
            toast.error(getFailedJobMessage(job))
          }
        },
      },
    )
  } catch {}
}

async function batchTranslateFrequent() {
  if (!selectedBankId.value) return

  try {
    const result = await frequentJobState.createJob(
      { job_type: 'bank_frequent_translate', bank_id: selectedBankId.value },
      {
        onFinished: async (job) => {
          await Promise.all([fetchFrequent(), refreshFrequentTranslationCount()])
          if (job?.status === 'completed') {
            toast.success('任务完成，已自动刷新未翻译数量')
          } else if (job?.status === 'failed') {
            toast.error(getFailedJobMessage(job))
          }
        },
      },
    )

    if (!result) return

    if (result.result === 'no_work') {
      toast.success(result.message)
      await Promise.all([fetchFrequent(), refreshFrequentTranslationCount()])
      return
    }
    if (result.result === 'created') {
      toast.success('高频词后台翻译已启动，刷新页面不会中断')
    } else if (result.result === 'existing') {
      toast.success(result.message || '已复用现有后台任务，刷新页面不会中断')
    }
  } catch (e) {
    toast.error(e.response?.data?.error || '创建高频词后台任务失败')
  }
}

async function restoreFrequentJob() {
  if (!selectedBankId.value) {
    frequentJobState.clearJob()
    return
  }

  try {
    await frequentJobState.restoreActiveJob(
      { job_type: 'bank_frequent_translate', bank_id: selectedBankId.value },
      {
        onFinished: async (job) => {
          await Promise.all([fetchFrequent(), refreshFrequentTranslationCount()])
          if (job?.status === 'failed') {
            toast.error(getFailedJobMessage(job))
          }
        },
      },
    )
  } catch {}
}

watch(activeTab, () => {
  showAddForm.value = false
})

watch(professionalMasteredFilter, fetchProfessional)
watch(personalMasteredFilter, fetchPersonal)

watch(selectedBankId, async () => {
  if (!selectedBankId.value) {
    frequentJobState.clearJob()
    await fetchFrequent()
    await refreshFrequentTranslationCount()
    return
  }

  const restorePromise = restoreFrequentJob()
  const countPromise = refreshFrequentTranslationCount()

  if (frequentPage.value !== 1) {
    frequentPage.value = 1
    await Promise.all([restorePromise, countPromise])
    return
  }

  await Promise.all([fetchFrequent(), restorePromise, countPromise])
})

watch(frequentMasteredFilter, () => {
  if (frequentPage.value !== 1) {
    frequentPage.value = 1
    return
  }
  fetchFrequent()
})

watch(frequentPage, fetchFrequent)

onMounted(async () => {
  await fetchBanks()
  await fetchStats()
  await fetchProfessional()
  await refreshProfessionalTranslationCount()
  await fetchPersonal()
  await restoreProfessionalJob()
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})

function buildMasteredFilterParams(filterValue) {
  if (filterValue === 'mastered') {
    return { mastered: true }
  }
  if (filterValue === 'unmastered') {
    return { mastered: false }
  }
  return {}
}
</script>
