<template>
  <div class="mb-4 rounded-xl bg-white dark:bg-slate-800 shadow-card p-5 md:p-6">
    <div class="mb-3">
      <h2 class="text-sm font-medium text-gray-900 dark:text-white">连续 {{ currentStreak }} 天</h2>
    </div>

    <div
      v-for="grid in grids"
      :key="grid.key"
      :class="['overflow-x-auto', grid.wrapperClass]"
    >
      <div class="inline-flex gap-[3px]">
        <div class="mr-1 flex flex-col gap-[3px]">
          <div class="h-3"></div>
          <div
            v-for="(label, index) in weekdayLabels"
            :key="index"
            class="h-[11px] w-3 text-[9px] leading-[11px] text-gray-400 dark:text-gray-500"
          >
            {{ label }}
          </div>
        </div>
        <div class="flex gap-[3px]">
          <div
            v-for="column in grid.columns"
            :key="column.key"
            class="flex w-[11px] flex-col gap-[3px]"
          >
            <div class="h-3 overflow-visible whitespace-nowrap text-[9px] leading-3 text-gray-400 dark:text-gray-500">
              {{ column.monthLabel }}
            </div>
            <div
              v-for="cell in column.cells"
              :key="cell.iso"
              class="h-[11px] w-[11px] rounded-[2px] cursor-default"
              :class="cellClass(cell)"
              :title="cell.future ? undefined : `${cell.iso} · ${cell.count} 题`"
            ></div>
          </div>
        </div>
      </div>
    </div>

    <div class="mt-3 flex items-center justify-end gap-1 text-[10px] text-gray-400 dark:text-gray-500">
      <span>Less</span>
      <div
        v-for="level in legendLevels"
        :key="level"
        class="h-[11px] w-[11px] rounded-[2px]"
        :class="levelClass(level)"
      ></div>
      <span>More</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatLocalDate, parseLocalDate } from '../utils/localDate'

const LEVEL_CLASSES = [
  'bg-[#ebedf0] dark:bg-[#161b22]',
  'bg-[#9be9a8] dark:bg-[#0e4429]',
  'bg-[#40c463] dark:bg-[#006d32]',
  'bg-[#30a14e] dark:bg-[#26a641]',
  'bg-[#216e39] dark:bg-[#39d353]',
]

const props = defineProps({
  days: { type: Array, default: () => [] },
  today: { type: String, default: '' },
  currentStreak: { type: Number, default: 0 },
})

const weekdayLabels = ['一', '', '三', '', '五', '', '']
const legendLevels = [0, 1, 2, 3, 4]
const monthNames = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

const countByDate = computed(() => {
  const map = new Map()
  for (const day of props.days || []) {
    if (!day?.date) continue
    map.set(day.date, Number(day.count) || 0)
  }
  return map
})

const todayIso = computed(() => props.today || formatLocalDate())

const grids = computed(() => [
  { key: 'sm', wrapperClass: 'md:hidden', columns: buildColumns(16) },
  { key: 'md', wrapperClass: 'hidden md:block', columns: buildColumns(53) },
])

function addDays(date, n) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + n)
}

function startOfWeekMonday(date) {
  const mondayOffset = (date.getDay() + 6) % 7
  return addDays(date, -mondayOffset)
}

function levelForCount(count) {
  if (count <= 0) return 0
  if (count <= 3) return 1
  if (count <= 9) return 2
  if (count <= 19) return 3
  return 4
}

function levelClass(level) {
  return LEVEL_CLASSES[level] || LEVEL_CLASSES[0]
}

function cellClass(cell) {
  if (cell.future) return 'bg-transparent'
  const classes = [levelClass(levelForCount(cell.count))]
  if (cell.isToday) classes.push('ring-1 ring-gray-600 dark:ring-gray-300')
  return classes
}

function buildColumns(weekCount) {
  const todayDate = parseLocalDate(todayIso.value)
  if (Number.isNaN(todayDate.getTime())) return []

  const lastMonday = startOfWeekMonday(todayDate)
  const firstMonday = addDays(lastMonday, -7 * (weekCount - 1))
  const columns = []

  for (let week = 0; week < weekCount; week++) {
    const weekStart = addDays(firstMonday, week * 7)
    const cells = []
    let monthLabel = ''
    for (let dow = 0; dow < 7; dow++) {
      const cellDate = addDays(weekStart, dow)
      const iso = formatLocalDate(cellDate)
      const future = cellDate > todayDate
      if (!future && cellDate.getDate() === 1) {
        monthLabel = monthNames[cellDate.getMonth()]
      }
      cells.push({
        iso,
        future,
        count: future ? 0 : (countByDate.value.get(iso) || 0),
        isToday: iso === todayIso.value,
      })
    }
    if (week === 0 && !monthLabel) {
      monthLabel = monthNames[weekStart.getMonth()]
    }

    columns.push({
      key: formatLocalDate(weekStart),
      monthLabel,
      cells,
    })
  }
  return columns
}
</script>
