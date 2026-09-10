<template>
  <div class="flex h-full flex-col rounded-xl bg-white dark:bg-slate-800 shadow-card p-5 md:p-6">
    <div class="mb-3 flex flex-wrap items-start justify-between gap-2">
      <h2 class="text-sm font-medium text-gray-900 dark:text-white">近 30 日</h2>
      <div class="flex flex-wrap items-center gap-3 text-[10px] text-gray-500 dark:text-gray-400">
        <span class="inline-flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full" :style="{ backgroundColor: COUNT_COLOR }"></span>
          答题数
        </span>
        <span class="inline-flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full" :style="{ backgroundColor: ACCURACY_COLOR }"></span>
          正确率
        </span>
      </div>
    </div>

    <div class="flex min-h-0 flex-1 flex-col">
      <div class="flex min-h-[148px] flex-1 md:min-h-0">
        <div class="flex w-7 shrink-0 flex-col justify-between py-0.5 pr-1 text-right text-[9px] leading-none text-gray-400 dark:text-gray-500">
          <span>{{ maxCount }}</span>
          <span>0</span>
        </div>
        <div
          ref="plotRef"
          class="relative min-h-0 min-w-0 flex-1"
          @pointermove="onPointerMove"
          @pointerdown="onPointerDown"
          @pointerleave="onPointerLeave"
        >
          <svg
            class="absolute inset-0 h-full w-full"
            :viewBox="`0 0 ${vbWidth} ${vbHeight}`"
            preserveAspectRatio="none"
            role="img"
            aria-label="近 30 日练习趋势图"
          >
            <line
              v-for="ratio in [0, 0.5, 1]"
              :key="'grid-' + ratio"
              x1="0"
              :x2="vbWidth"
              :y1="yAtRatio(ratio)"
              :y2="yAtRatio(ratio)"
              class="stroke-gray-100 dark:stroke-slate-700"
              stroke-width="1"
              vector-effect="non-scaling-stroke"
            />
            <path
              v-if="countArea"
              :d="countArea"
              :fill="COUNT_FILL"
            />
            <path
              v-if="countPath"
              :d="countPath"
              fill="none"
              :stroke="COUNT_COLOR"
              stroke-width="2.4"
              stroke-linejoin="round"
              stroke-linecap="round"
              vector-effect="non-scaling-stroke"
            />
            <path
              v-if="accuracyPath"
              :d="accuracyPath"
              fill="none"
              :stroke="ACCURACY_COLOR"
              stroke-width="2.4"
              stroke-linejoin="round"
              stroke-linecap="round"
              vector-effect="non-scaling-stroke"
            />
            <circle
              v-for="dot in countDots"
              :key="'c-' + dot.date"
              :cx="dot.x"
              :cy="dot.countY"
              r="3"
              :fill="COUNT_COLOR"
            />
            <circle
              v-for="dot in accuracyDots"
              :key="'a-' + dot.date"
              :cx="dot.x"
              :cy="dot.accuracyY"
              r="3"
              :fill="ACCURACY_COLOR"
            />
            <circle
              v-if="hoverPoint"
              :cx="hoverPoint.x"
              :cy="hoverPoint.y"
              r="4.5"
              :fill="hoverPoint.color"
            />
          </svg>

          <div
            v-if="hoverPoint"
            class="pointer-events-none absolute z-10 whitespace-nowrap rounded-md bg-white/95 px-2 py-1 text-[11px] leading-none text-gray-700 shadow-md dark:bg-slate-900/95 dark:text-gray-200"
            :style="tooltipStyle"
          >
            {{ hoverPoint.label }}
          </div>
        </div>
        <div class="flex w-9 shrink-0 flex-col justify-between py-0.5 pl-1 text-[9px] leading-none text-gray-400 dark:text-gray-500">
          <span>100%</span>
          <span>0%</span>
        </div>
      </div>
      <div class="mt-1 flex justify-between pl-7 pr-9 text-[9px] text-gray-400 dark:text-gray-500">
        <span>{{ firstDateLabel }}</span>
        <span>{{ lastDateLabel }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { findNearestTrendPoint, formatTrendPointLabel } from '../utils/trendPointLabel'

const COUNT_COLOR = '#2563eb'
const COUNT_FILL = 'rgba(37, 99, 235, 0.14)'
const ACCURACY_COLOR = '#ea580c'
const PAD_X = 6
const PAD_Y = 12
const HIT_RADIUS_PX = 32

const props = defineProps({
  days: { type: Array, default: () => [] },
  today: { type: String, default: '' },
})

const plotRef = ref(null)
const vbWidth = ref(400)
const vbHeight = ref(180)
const hoverTarget = ref(null)
const pinned = ref(false)
let observer = null

const normalizedDays = computed(() => (
  Array.isArray(props.days) ? props.days : []
))

const maxCount = computed(() => {
  const peak = Math.max(0, ...normalizedDays.value.map(day => Number(day?.count) || 0))
  return Math.max(peak, 1)
})

const points = computed(() => {
  const days = normalizedDays.value
  const last = Math.max(days.length - 1, 1)
  const innerW = Math.max(vbWidth.value - PAD_X * 2, 1)
  const innerH = Math.max(vbHeight.value - PAD_Y * 2, 1)
  return days.map((day, index) => {
    const count = Number(day?.count) || 0
    const accuracy = day?.accuracy == null ? null : Number(day.accuracy)
    return {
      date: day?.date || '',
      count,
      accuracy,
      x: PAD_X + (index / last) * innerW,
      countY: PAD_Y + (1 - count / maxCount.value) * innerH,
      accuracyY: accuracy == null ? null : PAD_Y + (1 - accuracy / 100) * innerH,
    }
  })
})

const countPath = computed(() => smoothPath(points.value.map(point => [point.x, point.countY])))

const countArea = computed(() => {
  const pairs = points.value.map(point => [point.x, point.countY])
  if (pairs.length < 2) return ''
  const baseline = vbHeight.value - PAD_Y
  return `${smoothPath(pairs)} L${pairs[pairs.length - 1][0]} ${baseline} L${pairs[0][0]} ${baseline} Z`
})

const accuracyPath = computed(() => (
  smoothPath(points.value
    .filter(point => point.accuracy != null)
    .map(point => [point.x, point.accuracyY]))
))

const countDots = computed(() => points.value.filter(point => point.count > 0))

const accuracyDots = computed(() => points.value.filter(point => point.accuracy != null))

const firstDateLabel = computed(() => formatShortDate(points.value[0]?.date))
const lastDateLabel = computed(() => formatShortDate(points.value[points.value.length - 1]?.date))

const hoverPoint = computed(() => {
  const target = hoverTarget.value
  if (!target) return null
  const point = points.value[target.index]
  if (!point) return null
  const isCount = target.series === 'count'
  return {
    x: point.x,
    y: isCount ? point.countY : point.accuracyY,
    color: isCount ? COUNT_COLOR : ACCURACY_COLOR,
    label: formatTrendPointLabel(target.series, isCount ? point.count : point.accuracy),
  }
})

const tooltipStyle = computed(() => {
  const point = hoverPoint.value
  if (!point) return {}
  const left = (point.x / vbWidth.value) * 100
  const top = (point.y / vbHeight.value) * 100
  const shiftX = left > 70 ? 'translateX(-100%)' : 'translateX(8px)'
  const shiftY = top < 18 ? 'translateY(10px)' : 'translateY(-140%)'
  return {
    left: `${left}%`,
    top: `${top}%`,
    transform: `${shiftX} ${shiftY}`,
  }
})

onMounted(() => {
  const el = plotRef.value
  if (!el) return
  const sync = () => {
    vbWidth.value = Math.max(el.clientWidth, 80)
    vbHeight.value = Math.max(el.clientHeight, 120)
  }
  sync()
  if (typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(sync)
  observer.observe(el)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})

function yAtRatio(ratio) {
  return PAD_Y + (1 - ratio) * Math.max(vbHeight.value - PAD_Y * 2, 1)
}

function clampY(y) {
  const min = PAD_Y
  const max = vbHeight.value - PAD_Y
  return Math.min(max, Math.max(min, y))
}

function smoothPath(pairs) {
  if (!pairs.length) return ''
  if (pairs.length === 1) return `M${pairs[0][0]} ${pairs[0][1]}`
  if (pairs.length === 2) {
    return `M${pairs[0][0]} ${pairs[0][1]} L${pairs[1][0]} ${pairs[1][1]}`
  }

  let d = `M${pairs[0][0]} ${pairs[0][1]}`
  for (let i = 0; i < pairs.length - 1; i++) {
    const p0 = pairs[Math.max(i - 1, 0)]
    const p1 = pairs[i]
    const p2 = pairs[i + 1]
    const p3 = pairs[Math.min(i + 2, pairs.length - 1)]
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = clampY(p1[1] + (p2[1] - p0[1]) / 6)
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = clampY(p2[1] - (p3[1] - p1[1]) / 6)
    d += ` C${c1x} ${c1y} ${c2x} ${c2y} ${p2[0]} ${p2[1]}`
  }
  return d
}

function formatShortDate(iso) {
  if (!iso) return ''
  const [, month, day] = String(iso).split('-')
  return `${Number(month)}/${Number(day)}`
}

function hitFromEvent(event) {
  const days = points.value
  if (!days.length) return null
  const rect = event.currentTarget.getBoundingClientRect()
  const width = Math.max(rect.width, 1)
  const height = Math.max(rect.height, 1)
  const candidates = []
  days.forEach((point, index) => {
    if (point.count > 0) {
      candidates.push({
        index,
        series: 'count',
        clientX: (point.x / vbWidth.value) * width,
        clientY: (point.countY / vbHeight.value) * height,
      })
    }
    if (point.accuracy != null) {
      candidates.push({
        index,
        series: 'accuracy',
        clientX: (point.x / vbWidth.value) * width,
        clientY: (point.accuracyY / vbHeight.value) * height,
      })
    }
  })
  const hit = findNearestTrendPoint(
    candidates,
    event.clientX - rect.left,
    event.clientY - rect.top,
    HIT_RADIUS_PX,
  )
  return hit ? { index: hit.index, series: hit.series } : null
}

function sameTarget(a, b) {
  return !!a && !!b && a.index === b.index && a.series === b.series
}

function onPointerMove(event) {
  if (event.pointerType !== 'mouse') return
  hoverTarget.value = hitFromEvent(event)
}

function onPointerDown(event) {
  const hit = hitFromEvent(event)
  if (event.pointerType === 'mouse') {
    hoverTarget.value = hit
    return
  }
  if (sameTarget(hoverTarget.value, hit)) {
    hoverTarget.value = null
    pinned.value = false
    return
  }
  hoverTarget.value = hit
  pinned.value = !!hit
}

function onPointerLeave() {
  if (pinned.value) return
  hoverTarget.value = null
}
</script>
