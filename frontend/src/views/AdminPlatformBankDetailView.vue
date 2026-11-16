<template>
  <div class="space-y-6">
    <div>
      <router-link
        :to="{ name: 'AdminPlatformBanks' }"
        class="inline-flex items-center gap-1 text-sm text-primary-600 hover:underline dark:text-primary-400"
      >
        <ArrowLeftIcon class="h-4 w-4" />
        返回平台题库列表
      </router-link>
      <div class="mt-1 flex flex-wrap items-center gap-2">
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">
          {{ bank ? bank.name : '平台题库' }}
        </h1>
        <template v-if="bank">
          <span
            class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
            :class="bank.is_listed
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
              : 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-gray-300'"
          >{{ bank.is_listed ? '已上架' : '未上架' }}</span>
          <span
            v-if="bank.has_active_import"
            class="inline-flex rounded-full bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-700 dark:bg-sky-900/30 dark:text-sky-300"
          >导入进行中</span>
        </template>
      </div>
      <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
        平台题库独立于个人项目；草稿修订与发布互不影响。
      </p>
    </div>

    <div
      v-if="loadError"
      class="rounded-card-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-300"
    >
      <p>{{ loadError }}</p>
      <BaseButton class="mt-3" size="sm" variant="secondary" @click="reloadAll">重试</BaseButton>
    </div>

    <div v-else-if="loading" class="space-y-3">
      <SkeletonLoader type="card" :count="3" />
    </div>

    <template v-else>
      <!-- 关键数量区分 -->
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div class="rounded-card-lg bg-white p-4 text-center shadow-card dark:bg-slate-800">
          <div class="text-2xl font-bold text-gray-900 dark:text-white">{{ bank?.draft_question_count ?? 0 }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400">当前草稿题数</div>
        </div>
        <div class="rounded-card-lg bg-white p-4 text-center shadow-card dark:bg-slate-800">
          <div class="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
            {{ latestRelease?.question_count ?? 0 }}
          </div>
          <div class="text-xs text-gray-500 dark:text-gray-400">
            发布题量<template v-if="latestRelease">（v{{ latestRelease.version_number }}）</template>
          </div>
        </div>
        <div class="rounded-card-lg bg-white p-4 text-center shadow-card dark:bg-slate-800">
          <div class="text-2xl font-bold text-sky-600 dark:text-sky-400">{{ lastImportAdded }}</div>
          <div class="text-xs text-gray-500 dark:text-gray-400">最近任务实际新增</div>
        </div>
      </div>

      <!-- 草稿元数据 -->
      <section class="rounded-card-lg bg-white p-5 shadow-card dark:bg-slate-800">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">草稿信息</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              {{ bank?.description || '暂无简介' }}
            </p>
            <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
              来源 ID：{{ bank?.id }} ｜ 更新于 {{ formatDateTime(bank?.updated_at) }}
            </p>
          </div>
          <BaseButton variant="secondary" size="sm" @click="openMetaEdit">
            <PencilSquareIcon class="h-4 w-4" />
            编辑名称/简介
          </BaseButton>
        </div>
      </section>

      <!-- 发布与下架 -->
      <section class="rounded-card-lg bg-white p-5 shadow-card dark:bg-slate-800">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">发布</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              发布会把当前全部草稿冻结为新版本并上架。导入进行中或存在不合格题目时会拒绝。
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <BaseButton
              :loading="publishing"
              :disabled="publishing || unpublishing"
              @click="confirmPublish = true"
            >发布新版本</BaseButton>
            <BaseButton
              v-if="bank?.is_listed"
              variant="secondary"
              :loading="unpublishing"
              :disabled="publishing || unpublishing"
              @click="confirmUnpublish = true"
            >下架</BaseButton>
          </div>
        </div>
        <p
          v-if="publishError"
          class="mt-3 rounded-card border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-300"
        >{{ publishError }}</p>
        <p v-if="publishNotice" class="mt-3 text-sm text-emerald-600 dark:text-emerald-400">{{ publishNotice }}</p>
      </section>

      <!-- 导入 -->
      <section class="rounded-card-lg bg-white p-5 shadow-card dark:bg-slate-800">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">导入草稿</h2>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          新解析结果只写入平台草稿，不会直接公开给用户。导入任务在下方内联展示。
        </p>
        <div class="mt-4">
          <FileUpload
            :upload-url="`/admin/platform-banks/${sourceId}/import`"
            :redirect-to-job="false"
            @imported="handleImported"
          />
        </div>

        <div class="mt-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-gray-900 dark:text-white">导入任务</h3>
            <BaseButton
              variant="ghost"
              size="sm"
              :disabled="jobsLoading"
              @click="fetchJobs(generation)"
            >刷新</BaseButton>
          </div>
          <p v-if="jobsError" class="mt-2 text-sm text-rose-600 dark:text-rose-400">{{ jobsError }}</p>
          <p v-else-if="jobs.length === 0" class="mt-2 text-sm text-gray-400 dark:text-gray-500">暂无导入任务</p>
          <div v-else class="mt-2 space-y-2">
            <div
              v-for="job in jobs"
              :key="job.id"
              class="rounded-card border border-gray-200 p-3 dark:border-slate-700"
            >
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium text-gray-900 dark:text-white">
                    #{{ job.id }} {{ job.file_name }}
                  </p>
                  <p class="text-xs text-gray-400 dark:text-gray-500">
                    {{ job.file_type?.toUpperCase() }} ｜ {{ formatDateTime(job.created_at) }}
                  </p>
                </div>
                <span class="text-sm" :class="importStatusClass(job.status)">{{ importStatusLabel(job.status) }}</span>
              </div>
              <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                解析 {{ job.parsed_questions || 0 }} 题 ｜
                <span class="text-emerald-600 dark:text-emerald-400">实际新增 {{ job.actual_inserted_count ?? 0 }} 题</span> ｜
                自动跳过 {{ job.auto_skipped_questions || 0 }} 题 ｜
                待复核 {{ job.review_questions || 0 }} 题 ｜
                失败 chunk {{ job.failed_chunks || 0 }}
              </p>
              <p v-if="job.error_message" class="mt-1 text-xs text-rose-600 dark:text-rose-400">
                {{ job.error_message }}
              </p>

              <div class="mt-2 flex flex-wrap items-center gap-2">
                <BaseButton variant="ghost" size="sm" @click="toggleJobDetail(job.id)">
                  {{ expandedJobId === job.id ? '收起明细' : '查看逐题明细' }}
                </BaseButton>
                <span v-if="job.review_questions > 0" class="text-xs text-amber-600 dark:text-amber-400">
                  有 {{ job.review_questions }} 题待复核
                </span>
              </div>

              <!-- 逐题明细：包含重复与跳过记录，不只显示自动处理项 -->
              <div
                v-if="expandedJobId === job.id"
                class="mt-3 border-t border-gray-100 pt-2 dark:border-slate-700"
              >
                <p v-if="jobDetailError" class="text-xs text-rose-600 dark:text-rose-400">{{ jobDetailError }}</p>
                <p v-else-if="jobDetailLoading" class="text-xs text-gray-400 dark:text-gray-500">加载中…</p>
                <template v-else>
                  <p v-if="jobParsed.length === 0" class="text-xs text-gray-400 dark:text-gray-500">没有解析记录</p>
                  <div v-else class="max-h-80 space-y-2 overflow-y-auto">
                    <div
                      v-for="item in jobParsed"
                      :key="item.id"
                      class="rounded border border-gray-100 p-2 text-xs dark:border-slate-700"
                    >
                      <div class="flex flex-wrap items-center justify-between gap-1">
                        <span class="font-medium text-gray-700 dark:text-gray-200">
                          {{ item.source_question_no ? `#${item.source_question_no} ` : '' }}{{ item.content }}
                        </span>
                        <span :class="parsedStatusClass(item)">
                          {{ parsedStatusLabel(item) }}
                        </span>
                      </div>
                      <p v-if="item.correct_answer" class="mt-1 text-gray-500 dark:text-gray-400">
                        答案 {{ Array.isArray(item.correct_answer) ? item.correct_answer.join(',') : item.correct_answer }}
                      </p>
                      <p
                        v-if="parsedIssueLabels(item).length"
                        class="mt-1 text-amber-600 dark:text-amber-400"
                      >
                        问题：{{ parsedIssueLabels(item).join('、') }}
                      </p>
                    </div>
                  </div>

                  <!-- 待复核项：接受/跳过/重新解析 -->
                  <div v-if="jobReviewItems.length" class="mt-3">
                    <p class="mb-1 font-medium text-gray-700 dark:text-gray-200">待复核</p>
                    <div
                      v-for="item in jobReviewItems"
                      :key="item.id"
                      class="mb-2 rounded border border-amber-200 p-2 dark:border-amber-900/40"
                    >
                      <p class="text-gray-700 dark:text-gray-200">
                        {{ item.parsed_question?.content || item.before_json?.content || '（无题干）' }}
                      </p>
                      <p class="mt-1 text-gray-500 dark:text-gray-400">
                        类型 {{ item.review_type }} ｜ 严重度 {{ item.severity }}
                      </p>
                      <div class="mt-2 flex flex-wrap gap-2">
                        <BaseButton
                          size="sm"
                          :disabled="reviewBusyId === item.id"
                          @click="acceptReviewItem(job.id, item.id)"
                        >接受入库</BaseButton>
                        <BaseButton
                          variant="secondary"
                          size="sm"
                          :disabled="reviewBusyId === item.id"
                          @click="skipReviewItem(job.id, item.id)"
                        >跳过</BaseButton>
                        <BaseButton
                          variant="secondary"
                          size="sm"
                          :disabled="reviewBusyId === item.id"
                          @click="reparseReviewItem(job.id, item.id)"
                        >重新解析</BaseButton>
                      </div>
                      <p v-if="reviewError" class="mt-1 text-xs text-rose-600 dark:text-rose-400">{{ reviewError }}</p>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 草稿题 -->
      <section class="rounded-card-lg bg-white p-5 shadow-card dark:bg-slate-800">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-gray-900 dark:text-white">草稿题目</h2>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
              共 {{ draftTotal }} 题；导入进行中时服务端会拒绝增删改草稿并返回原因。
            </p>
          </div>
          <BaseButton size="sm" @click="openAdd">
            <PlusIcon class="h-4 w-4" />
            添加草稿题
          </BaseButton>
        </div>

        <p v-if="questionsError" class="mt-3 text-sm text-rose-600 dark:text-rose-400">{{ questionsError }}</p>
        <div v-else-if="questionsLoading" class="mt-3">
          <SkeletonLoader type="card" :count="2" />
        </div>
        <p v-else-if="questions.length === 0" class="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
          暂无草稿题，可上传文件或手动添加
        </p>
        <div v-else class="mt-3 space-y-3">
          <div
            v-for="(q, index) in questions"
            :key="q.id"
            class="rounded-card border border-gray-200 p-4 dark:border-slate-700"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <p class="text-sm font-medium text-gray-900 dark:text-white">
                  {{ (page - 1) * perPage + index + 1 }}. {{ q.content }}
                </p>
                <p v-if="q.content_zh" class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ q.content_zh }}</p>
                <div class="mt-2 flex flex-wrap gap-1">
                  <span
                    v-for="opt in q.options || []"
                    :key="opt.key"
                    class="rounded-md px-2 py-0.5 text-xs"
                    :class="String(q.correct_answer || '').includes(opt.key)
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                      : 'bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-gray-400'"
                  >{{ opt.key }}. {{ opt.text }}</span>
                </div>
                <p class="mt-1 text-xs text-gray-400 dark:text-gray-500">
                  {{ questionTypeLabel(q.question_type) }} ｜ 答案：{{ q.correct_answer }}
                  <template v-if="(q.source_topics || []).length">
                    ｜ 来源考点：{{ (q.source_topics || []).map(formatSourceTopic).filter(Boolean).join('、') }}
                  </template>
                </p>
              </div>
              <div class="flex flex-shrink-0 gap-1">
                <BaseButton variant="ghost" size="sm" @click="openEdit(q)">
                  <PencilSquareIcon class="h-4 w-4" />
                  编辑
                </BaseButton>
                <BaseButton
                  variant="ghost"
                  size="sm"
                  class="!text-rose-500 hover:!text-rose-700 dark:!text-rose-400"
                  @click="askDeleteQuestion(q)"
                >
                  <TrashIcon class="h-4 w-4" />
                  删除
                </BaseButton>
              </div>
            </div>
          </div>
        </div>

        <div v-if="totalPages > 1" class="mt-4 flex flex-wrap justify-center gap-2">
          <button
            v-for="p in totalPages"
            :key="p"
            class="rounded-card px-3 py-1 text-sm transition-colors"
            :class="p === page
              ? 'bg-primary-600 text-white'
              : 'bg-white text-gray-600 shadow-card hover:bg-gray-100 dark:bg-slate-800 dark:text-gray-400 dark:hover:bg-slate-700'"
            @click="page = p"
          >{{ p }}</button>
        </div>
      </section>

      <!-- 发布版本 -->
      <section class="rounded-card-lg bg-white p-5 shadow-card dark:bg-slate-800">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-white">发布版本</h2>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          历史版本只读；个人副本保留各自选用版本的题目快照。
        </p>
        <p v-if="releasesError" class="mt-3 text-sm text-rose-600 dark:text-rose-400">{{ releasesError }}</p>
        <p v-else-if="releases.length === 0" class="mt-3 text-sm text-gray-400 dark:text-gray-500">尚未发布</p>
        <div v-else class="mt-3 space-y-2">
          <div
            v-for="release in releases"
            :key="release.id"
            class="flex flex-wrap items-center justify-between gap-2 rounded-card border border-gray-200 p-3 text-sm dark:border-slate-700"
          >
            <div class="min-w-0">
              <p class="font-medium text-gray-900 dark:text-white">
                v{{ release.version_number }} {{ release.name }}
                <span
                  v-if="release.id === latestRelease?.id"
                  class="ml-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                >当前可选</span>
              </p>
              <p class="text-xs text-gray-400 dark:text-gray-500">
                {{ release.question_count }} 题 ｜ schema v{{ release.schema_version }} ｜
                {{ formatDateTime(release.created_at) }}
              </p>
            </div>
            <span class="text-xs text-gray-400 dark:text-gray-500">{{ shortId(release.id, 12) }}</span>
          </div>
        </div>
      </section>
    </template>

    <!-- 编辑草稿信息 -->
    <BaseModal :open="showMetaEdit" title="编辑草稿信息" @close="showMetaEdit = false">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">名称</label>
          <input
            v-model="metaForm.name"
            type="text"
            maxlength="200"
            class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">简介</label>
          <textarea
            v-model="metaForm.description"
            rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
          ></textarea>
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          已发布版本的名称与简介保持不变，重新发布后才生效。
        </p>
        <p v-if="metaError" class="text-sm text-rose-600 dark:text-rose-400">{{ metaError }}</p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showMetaEdit = false">取消</BaseButton>
        <BaseButton :loading="metaSaving" :disabled="metaSaving" @click="saveMeta">保存</BaseButton>
      </template>
    </BaseModal>

    <!-- 草稿题编辑 -->
    <BaseModal :open="showQuestionForm" :title="questionForm.id ? '编辑草稿题' : '添加草稿题'" maxWidth="lg" @close="showQuestionForm = false">
      <div class="space-y-4">
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">题型</label>
            <select
              v-model="questionForm.question_type"
              class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
            >
              <option value="single">单选</option>
              <option value="multiple">多选</option>
              <option value="truefalse">判断</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">正确答案（多选用逗号分隔）</label>
            <input
              v-model="questionForm.correct_answer"
              type="text"
              placeholder="A 或 A,C"
              class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
            />
          </div>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">题干</label>
          <textarea
            v-model="questionForm.content"
            rows="3"
            class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
          ></textarea>
        </div>
        <div>
          <div class="flex items-center justify-between">
            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">选项</label>
            <BaseButton variant="ghost" size="sm" @click="addOptionRow">添加选项</BaseButton>
          </div>
          <div class="mt-2 space-y-2">
            <div v-for="(option, index) in questionForm.options" :key="index" class="flex items-center gap-2">
              <input
                v-model="option.key"
                type="text"
                maxlength="4"
                placeholder="A"
                class="w-16 rounded-card border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
              />
              <input
                v-model="option.text"
                type="text"
                placeholder="选项文本"
                class="min-w-0 flex-1 rounded-card border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
              />
              <BaseButton variant="ghost" size="sm" @click="removeOptionRow(index)">移除</BaseButton>
            </div>
          </div>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 dark:text-gray-300">来源考点（逗号分隔，可留空）</label>
          <input
            v-model="questionForm.sourceTopics"
            type="text"
            placeholder="例如：隐私治理, 数据生命周期"
            class="mt-1 w-full rounded-card border border-gray-300 bg-white px-3 py-2 text-gray-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-700 dark:text-white"
          />
          <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
            来源考点只随草稿与发布版保存为描述信息，不会创建个人项目考点。
          </p>
        </div>
        <p v-if="questionFormError" class="text-sm text-rose-600 dark:text-rose-400">{{ questionFormError }}</p>
      </div>
      <template #actions>
        <BaseButton variant="secondary" @click="showQuestionForm = false">取消</BaseButton>
        <BaseButton :loading="questionSaving" :disabled="questionSaving" @click="saveQuestion">
          {{ questionForm.id ? '保存' : '添加' }}
        </BaseButton>
      </template>
    </BaseModal>

    <ConfirmDialog
      :open="confirmPublish"
      title="发布新版本"
      :message="`将当前 ${bank?.draft_question_count ?? 0} 道草稿题冻结为新版本并上架，确定继续吗？`"
      confirmText="发布"
      @confirm="publish"
      @cancel="confirmPublish = false"
    />
    <ConfirmDialog
      :open="confirmUnpublish"
      title="下架平台题库"
      message="下架后目录不再展示该来源，也不能新建副本；已有个人副本与练习记录不受影响。确定下架吗？"
      confirmText="下架"
      :danger="true"
      @confirm="unpublish"
      @cancel="confirmUnpublish = false"
    />
    <ConfirmDialog
      :open="showDeleteQuestion"
      title="删除草稿题"
      message="删除后该题不会出现在下一次发布中，确定删除吗？"
      confirmText="删除"
      :danger="true"
      @confirm="deleteQuestion"
      @cancel="showDeleteQuestion = false"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import client from '../api/client'
import { useToast } from '../composables/useToast'
import {
  errorMessage,
  formatDateTime,
  formatSourceTopic,
  importStatusClass,
  importStatusLabel,
  isActiveImportStatus,
  questionTypeLabel,
  shortId,
} from '../utils/platformBanks'
import BaseButton from '../components/BaseButton.vue'
import BaseModal from '../components/BaseModal.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import FileUpload from '../components/FileUpload.vue'
import SkeletonLoader from '../components/SkeletonLoader.vue'
import {
  ArrowLeftIcon,
  PencilSquareIcon,
  PlusIcon,
  TrashIcon,
} from '@heroicons/vue/24/outline'

const route = useRoute()
const toast = useToast()

const sourceId = computed(() => String(route.params.sourceId || ''))
const perPage = 20

const bank = ref(null)
const loading = ref(true)
const loadError = ref('')
const jobs = ref([])
const jobsLoading = ref(false)
const jobsError = ref('')
// 逐题明细与复核：包含重复/跳过记录，不能只看自动处理项。
const expandedJobId = ref(null)
const jobParsed = ref([])
const jobReviewItems = ref([])
const jobDetailLoading = ref(false)
const jobDetailError = ref('')
const reviewBusyId = ref(null)
const reviewError = ref('')
const questions = ref([])
const questionsLoading = ref(false)
const questionsError = ref('')
const draftTotal = ref(0)
const page = ref(1)
const releases = ref([])
const releasesError = ref('')
const publishing = ref(false)
const unpublishing = ref(false)
const publishError = ref('')
const publishNotice = ref('')
const confirmPublish = ref(false)
const confirmUnpublish = ref(false)

const showMetaEdit = ref(false)
const metaSaving = ref(false)
const metaError = ref('')
const metaForm = ref({ name: '', description: '' })

const showQuestionForm = ref(false)
const questionSaving = ref(false)
const questionFormError = ref('')
const questionForm = ref(emptyQuestionForm())
const showDeleteQuestion = ref(false)
const deletingQuestion = ref(null)

// 路由来源/项目切换和卸载都会递增序号，旧响应与轮询一律丢弃。
let generation = 0
let questionsSequence = 0
let suppressPageFetch = false
let unmounted = false
let pollTimer = null

const latestRelease = computed(() => bank.value?.latest_release || null)
const lastImportAdded = computed(() => {
  const job = jobs.value[0]
  // 平台任务用 inserted_new 计数的真实新增，不用可能虚报的 imported_questions。
  return job ? Number(job.actual_inserted_count ?? 0) : 0
})
const totalPages = computed(() => {
  if (draftTotal.value <= 0) return 0
  return Math.ceil(draftTotal.value / perPage)
})

function emptyQuestionForm() {
  return {
    id: null,
    question_type: 'single',
    content: '',
    correct_answer: '',
    options: [
      { key: 'A', text: '' },
      { key: 'B', text: '' },
    ],
    sourceTopics: '',
  }
}

// ─── 逐题明细与复核 ──────────────────────────────────────────────

function parsedIssueLabels(item) {
  // issues 是 {"issues": [code...], "details": [...]} 结构，不是数组。
  const raw = item?.issues
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (Array.isArray(raw.details)) {
    return raw.details.map((detail) => detail.detail || detail.code).filter(Boolean)
  }
  if (Array.isArray(raw.issues)) return raw.issues
  return []
}

function parsedStatusLabel(item) {
  if (item.import_status === 'imported') return '已入草稿'
  if (item.import_status === 'skipped') return '已跳过'
  if (item.review_status === 'duplicate') return '重复'
  if (item.review_status === 'pending') return '待复核'
  return item.import_status || '未知'
}

function parsedStatusClass(item) {
  const base = 'shrink-0 rounded px-1.5 py-0.5 text-[11px]'
  if (item.import_status === 'imported') return `${base} bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300`
  if (item.review_status === 'duplicate') return `${base} bg-sky-50 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300`
  if (item.import_status === 'skipped') return `${base} bg-gray-100 text-gray-600 dark:bg-slate-700 dark:text-gray-300`
  return `${base} bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300`
}

async function toggleJobDetail(jobId) {
  reviewError.value = ''
  if (expandedJobId.value === jobId) {
    expandedJobId.value = null
    return
  }
  expandedJobId.value = jobId
  jobParsed.value = []
  jobReviewItems.value = []
  await loadJobDetail(jobId)
}

async function loadJobDetail(jobId) {
  const requestGeneration = generation
  jobDetailLoading.value = true
  jobDetailError.value = ''
  const base = `/admin/platform-banks/${sourceId.value}/import-jobs/${jobId}`
  try {
    const [parsed, review] = await Promise.all([
      client.get(`${base}/parsed-questions`),
      client.get(`${base}/review-items`),
    ])
    if (!isCurrent(requestGeneration) || expandedJobId.value !== jobId) return
    jobParsed.value = Array.isArray(parsed.data?.questions) ? parsed.data.questions : []
    jobReviewItems.value = (Array.isArray(review.data?.items) ? review.data.items : [])
      .filter((item) => item.status === 'pending')
  } catch (e) {
    if (isCurrent(requestGeneration) && expandedJobId.value === jobId) {
      jobDetailError.value = errorMessage(e, '加载导入明细失败')
    }
  } finally {
    if (isCurrent(requestGeneration) && expandedJobId.value === jobId) jobDetailLoading.value = false
  }
}

async function runReviewAction(jobId, itemId, action, successMessage) {
  reviewBusyId.value = itemId
  reviewError.value = ''
  try {
    await client.post(
      `/admin/platform-banks/${sourceId.value}/import-jobs/${jobId}/review-items/${itemId}/${action}`,
    )
    toast.success(successMessage)
    await Promise.all([loadJobDetail(jobId), fetchQuestions(generation), fetchJobs(generation)])
  } catch (e) {
    // 服务端会给出可读原因（例如分块含已删除题目需改用追加导入）。
    reviewError.value = errorMessage(e, '复核操作失败')
  } finally {
    reviewBusyId.value = null
  }
}

function acceptReviewItem(jobId, itemId) {
  return runReviewAction(jobId, itemId, 'accept', '已接受并写入草稿')
}

function skipReviewItem(jobId, itemId) {
  return runReviewAction(jobId, itemId, 'skip', '已跳过该解析结果')
}

function reparseReviewItem(jobId, itemId) {
  return runReviewAction(jobId, itemId, 'reparse', '已提交重新解析')
}

function isCurrent(requestGeneration) {
  return !unmounted && requestGeneration === generation
}

async function fetchBank(requestGeneration) {
  const res = await client.get(`/admin/platform-banks/${sourceId.value}`)
  if (!isCurrent(requestGeneration)) return
  bank.value = res.data
}

async function fetchJobs(requestGeneration) {
  jobsLoading.value = true
  jobsError.value = ''
  try {
    const res = await client.get(`/admin/platform-banks/${sourceId.value}/import-jobs`)
    if (!isCurrent(requestGeneration)) return
    jobs.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    if (isCurrent(requestGeneration)) jobsError.value = errorMessage(e, '加载导入任务失败')
  } finally {
    if (isCurrent(requestGeneration)) jobsLoading.value = false
  }
}

async function fetchQuestions(requestGeneration) {
  // 分页快速切换时只保留最后一次响应，避免旧页覆盖新页。
  const requestId = ++questionsSequence
  questionsLoading.value = true
  questionsError.value = ''
  try {
    const res = await client.get(`/admin/platform-banks/${sourceId.value}/questions`, {
      params: { page: page.value, per_page: perPage },
    })
    if (!isCurrent(requestGeneration) || requestId !== questionsSequence) return
    questions.value = Array.isArray(res.data?.questions) ? res.data.questions : []
    draftTotal.value = Number(res.data?.total) || 0
  } catch (e) {
    if (isCurrent(requestGeneration) && requestId === questionsSequence) {
      questionsError.value = errorMessage(e, '加载草稿题失败')
    }
  } finally {
    if (isCurrent(requestGeneration) && requestId === questionsSequence) questionsLoading.value = false
  }
}

async function fetchReleases(requestGeneration) {
  releasesError.value = ''
  try {
    const res = await client.get(`/admin/platform-banks/${sourceId.value}/releases`)
    if (!isCurrent(requestGeneration)) return
    releases.value = Array.isArray(res.data) ? res.data : []
  } catch (e) {
    if (isCurrent(requestGeneration)) releasesError.value = errorMessage(e, '加载发布版本失败')
  }
}

async function reloadAll() {
  const requestGeneration = ++generation
  stopPolling()
  loading.value = true
  loadError.value = ''
  try {
    await fetchBank(requestGeneration)
    await Promise.all([
      fetchJobs(requestGeneration),
      fetchQuestions(requestGeneration),
      fetchReleases(requestGeneration),
    ])
  } catch (e) {
    if (isCurrent(requestGeneration)) loadError.value = errorMessage(e, '加载平台题库失败')
  } finally {
    if (isCurrent(requestGeneration)) loading.value = false
  }
  // 有活动导入时继续轮询任务计数与草稿量，所有回调都校验当前序号。
  if (isCurrent(requestGeneration)) schedulePolling(requestGeneration)
}

function schedulePolling(requestGeneration) {
  stopPolling()
  if (!isCurrent(requestGeneration)) return
  const active = jobs.value.some((job) => isActiveImportStatus(job.status))
  if (!active) return
  pollTimer = window.setTimeout(async () => {
    if (!isCurrent(requestGeneration)) return
    await Promise.all([
      fetchJobs(requestGeneration),
      fetchBank(requestGeneration).catch(() => {}),
      fetchQuestions(requestGeneration),
    ])
    if (isCurrent(requestGeneration)) schedulePolling(requestGeneration)
  }, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function handleImported() {
  publishError.value = ''
  publishNotice.value = ''
  const requestGeneration = generation
  Promise.all([
    fetchJobs(requestGeneration),
    fetchBank(requestGeneration).catch(() => {}),
  ]).then(() => {
    if (isCurrent(requestGeneration)) schedulePolling(requestGeneration)
  })
}

function openMetaEdit() {
  metaForm.value = { name: bank.value?.name || '', description: bank.value?.description || '' }
  metaError.value = ''
  showMetaEdit.value = true
}

async function saveMeta() {
  if (metaSaving.value) return
  const name = metaForm.value.name.trim()
  if (!name) {
    metaError.value = '请填写名称'
    return
  }
  const requestGeneration = generation
  metaSaving.value = true
  metaError.value = ''
  try {
    await client.put(`/admin/platform-banks/${sourceId.value}`, {
      name,
      description: metaForm.value.description.trim() || null,
    })
    if (!isCurrent(requestGeneration)) return
    showMetaEdit.value = false
    toast.success('草稿信息已更新')
    await fetchBank(requestGeneration)
  } catch (e) {
    if (isCurrent(requestGeneration)) metaError.value = errorMessage(e, '更新草稿信息失败')
  } finally {
    if (isCurrent(requestGeneration)) metaSaving.value = false
  }
}

async function publish() {
  confirmPublish.value = false
  // 双击确认或重复触发时只发一次请求。
  if (publishing.value) return
  const requestGeneration = generation
  publishing.value = true
  publishError.value = ''
  publishNotice.value = ''
  try {
    const res = await client.post(`/admin/platform-banks/${sourceId.value}/publish`)
    if (!isCurrent(requestGeneration)) return
    publishNotice.value = `已发布 v${res.data.version_number}（${res.data.question_count} 题）`
    toast.success('平台题库已发布')
    await Promise.all([
      fetchBank(requestGeneration).catch(() => {}),
      fetchReleases(requestGeneration),
    ])
  } catch (e) {
    if (isCurrent(requestGeneration)) publishError.value = errorMessage(e, '发布失败')
  } finally {
    if (isCurrent(requestGeneration)) publishing.value = false
  }
}

async function unpublish() {
  confirmUnpublish.value = false
  if (unpublishing.value) return
  const requestGeneration = generation
  unpublishing.value = true
  publishError.value = ''
  publishNotice.value = ''
  try {
    await client.post(`/admin/platform-banks/${sourceId.value}/unpublish`)
    if (!isCurrent(requestGeneration)) return
    publishNotice.value = '已下架，目录不再展示该来源'
    toast.success('平台题库已下架')
    await fetchBank(requestGeneration).catch(() => {})
  } catch (e) {
    if (isCurrent(requestGeneration)) publishError.value = errorMessage(e, '下架失败')
  } finally {
    if (isCurrent(requestGeneration)) unpublishing.value = false
  }
}

function openAdd() {
  questionForm.value = emptyQuestionForm()
  questionFormError.value = ''
  showQuestionForm.value = true
}

function openEdit(question) {
  questionForm.value = {
    id: question.id,
    question_type: question.question_type || 'single',
    content: question.content || '',
    correct_answer: question.correct_answer || '',
    options: (question.options || []).map((option) => ({ key: option.key, text: option.text })),
    sourceTopics: (question.source_topics || []).map(formatSourceTopic).filter(Boolean).join(', '),
  }
  questionFormError.value = ''
  showQuestionForm.value = true
}

function addOptionRow() {
  const usedKeys = questionForm.value.options.map((option) => String(option.key).toUpperCase())
  const nextKey = ['A', 'B', 'C', 'D', 'E', 'F'].find((key) => !usedKeys.includes(key))
  questionForm.value.options.push({ key: nextKey || '', text: '' })
}

function removeOptionRow(index) {
  questionForm.value.options.splice(index, 1)
}

function parseSourceTopics(text) {
  const items = String(text || '')
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
  return items.length ? items : null
}

async function saveQuestion() {
  if (questionSaving.value) return
  const options = questionForm.value.options
    .map((option) => ({ key: String(option.key || '').trim(), text: String(option.text || '').trim() }))
    .filter((option) => option.key && option.text)
  if (!questionForm.value.content.trim()) {
    questionFormError.value = '请填写题干'
    return
  }
  if (options.length < 2) {
    questionFormError.value = '至少需要两个有效选项'
    return
  }
  if (!questionForm.value.correct_answer.trim()) {
    questionFormError.value = '请填写正确答案'
    return
  }

  const requestGeneration = generation
  const payload = {
    question_type: questionForm.value.question_type,
    content: questionForm.value.content.trim(),
    options,
    correct_answer: questionForm.value.correct_answer.trim(),
    source_topics: parseSourceTopics(questionForm.value.sourceTopics),
  }

  questionSaving.value = true
  questionFormError.value = ''
  try {
    if (questionForm.value.id) {
      await client.put(
        `/admin/platform-banks/${sourceId.value}/questions/${questionForm.value.id}`,
        payload,
      )
    } else {
      await client.post(`/admin/platform-banks/${sourceId.value}/questions`, payload)
    }
    if (!isCurrent(requestGeneration)) return
    showQuestionForm.value = false
    toast.success(questionForm.value.id ? '草稿题已更新' : '草稿题已添加')
    await Promise.all([
      fetchQuestions(requestGeneration),
      fetchBank(requestGeneration).catch(() => {}),
    ])
  } catch (e) {
    if (isCurrent(requestGeneration)) questionFormError.value = errorMessage(e, '保存草稿题失败')
  } finally {
    if (isCurrent(requestGeneration)) questionSaving.value = false
  }
}

function askDeleteQuestion(question) {
  deletingQuestion.value = question
  showDeleteQuestion.value = true
}

async function deleteQuestion() {
  showDeleteQuestion.value = false
  const target = deletingQuestion.value
  deletingQuestion.value = null
  if (!target) return
  const requestGeneration = generation
  try {
    await client.delete(`/admin/platform-banks/${sourceId.value}/questions/${target.id}`)
    if (!isCurrent(requestGeneration)) return
    toast.success('草稿题已删除')
    if (questions.value.length === 1 && page.value > 1) page.value -= 1
    else await fetchQuestions(requestGeneration)
    await fetchBank(requestGeneration).catch(() => {})
  } catch (e) {
    if (isCurrent(requestGeneration)) toast.error(errorMessage(e, '删除草稿题失败'))
  }
}

watch(page, () => {
  // 来源切换时由 reloadAll 统一拉取，避免重复请求。
  if (suppressPageFetch) {
    suppressPageFetch = false
    return
  }
  fetchQuestions(generation)
})

// 同一路由组件在来源之间切换时重新初始化，避免旧来源的数据/轮询残留。
watch(sourceId, (next, previous) => {
  if (!next || next === previous) return
  if (page.value !== 1) suppressPageFetch = true
  page.value = 1
  bank.value = null
  jobs.value = []
  questions.value = []
  draftTotal.value = 0
  releases.value = []
  publishError.value = ''
  publishNotice.value = ''
  reloadAll()
})

onMounted(reloadAll)
onUnmounted(() => {
  unmounted = true
  generation += 1
  stopPolling()
})
</script>
