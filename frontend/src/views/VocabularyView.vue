<template>
  <div>
    <template v-if="route.query.mode === 'manage'">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
        <router-link :to="overviewPath" class="inline-flex min-h-12 items-center gap-2 text-primary-600 dark:text-primary-400">
          <ArrowLeftIcon class="h-5 w-5" aria-hidden="true" />返回来源选择
        </router-link>
        <router-link :to="studyLink" class="inline-flex min-h-12 items-center rounded-button bg-primary-600 px-4 text-white">卡片学习</router-link>
      </div>
      <VocabularyManageView :key="route.params.examSlug" :scope="manageScope" :bank-id="manageBank" @scope="updateScope" @bank="updateBank" />
    </template>
    <VocabularyOverview v-else :key="route.params.examSlug" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeftIcon } from '@heroicons/vue/24/outline'
import VocabularyManageView from './VocabularyManageView.vue'
import VocabularyOverview from '../components/VocabularyOverview.vue'
import { examPath } from '../utils/examRoutes'

const route = useRoute(), router = useRouter()
const overviewPath = computed(() => examPath(route.params.examSlug, 'vocab'))
const manageScope = computed(() => ['personal', 'exam_personal', 'frequent'].includes(route.query.scope) ? route.query.scope : 'exam_personal')
const manageBank = computed(() => /^[1-9]\d*$/.test(route.query.bank_id || '') ? Number(route.query.bank_id) : null)
const studyLink = computed(() => manageScope.value === 'frequent' && !manageBank.value ? overviewPath.value : {
  name: 'ExamVocabularyStudy', params: { examSlug: route.params.examSlug },
  query: { scope: manageScope.value, mastery: 'unmastered', ...(manageScope.value === 'frequent' ? { bank_id: String(manageBank.value) } : {}) },
})
function updateScope(scope) { router.replace({ path: overviewPath.value, query: { mode: 'manage', scope, ...(scope === 'frequent' && manageBank.value ? { bank_id: String(manageBank.value) } : {}) } }) }
function updateBank(bankId) { if (manageScope.value === 'frequent') router.replace({ path: overviewPath.value, query: { mode: 'manage', scope: 'frequent', bank_id: String(bankId) } }) }
</script>
