<template>
  <section ref="card" class="study-card" :class="{ 'study-card-interactive': canInteract }" aria-label="单词卡"
    :tabindex="item && !loading ? 0 : -1" :aria-describedby="hintId" :aria-busy="loading || animating" :aria-disabled="!canInteract"
    @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="cancelInteraction"
    @contextmenu="cancelInteraction" @dblclick="cancelInteraction" @scroll.capture.passive="cancelInteraction"
    @click="accessibleClick" @keydown="keydown">
    <div ref="content" class="study-card-content">
      <div v-if="loading" class="study-card-body study-card-front" role="status">正在加载单词…</div>
      <div v-else-if="!displayedItem" class="study-card-body study-card-front"><p>当前词条尚未加载成功，请重试。</p></div>
      <div v-else :key="displayedIdentity + ':' + displayedFlipped" class="study-card-body" :class="{ 'study-card-front': !displayedFlipped }">
        <template v-if="!displayedFlipped">
          <p class="mb-5 text-xs font-medium tracking-widest text-gray-500 dark:text-gray-400">先回忆，再核对</p>
          <h2 lang="en" class="study-word text-gray-900 dark:text-white">{{ displayedItem.content.term }}</h2>
        </template>
        <template v-else>
          <p lang="en" class="mb-5 break-words text-lg font-semibold text-gray-500 dark:text-gray-400">{{ displayedItem.content.term }}</p>
          <h2 v-if="translation" class="mb-5 whitespace-pre-wrap break-words text-2xl font-bold leading-relaxed text-gray-900 dark:text-white">{{ translation }}</h2>
          <p v-if="chineseDefinition && chineseDefinition !== translation" class="whitespace-pre-wrap break-words text-base leading-7 text-gray-700 dark:text-gray-200">{{ chineseDefinition }}</p>
          <p v-if="!hasChinese" class="mb-4 rounded-button bg-amber-50 p-3 text-sm leading-relaxed text-amber-800 dark:bg-amber-900/20 dark:text-amber-200">{{ englishDefinition ? '当前缺少中文内容，以下为已有英文释义。' : '当前仅有英文词条，暂无翻译或释义。你仍可自行判断或跳过。' }}</p>
          <p v-if="englishDefinition" lang="en" class="whitespace-pre-wrap break-words text-base leading-7 text-gray-700 dark:text-gray-200" :class="{ 'mt-6': hasChinese }">{{ englishDefinition }}</p>
        </template>
      </div>
      <div class="study-card-meta">
        <span v-if="displayedItem?.content.frequency != null" class="text-xs text-gray-500 dark:text-gray-400">出现 {{ displayedItem.content.frequency }} 次</span>
        <span :id="hintId" class="text-xs text-gray-500 dark:text-gray-400" aria-live="polite">{{ displayedFlipped ? '点击卡片返回英文' : '点击卡片查看中文' }}<span class="sr-only">，也可按 Enter 或空格翻面</span></span>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, useId, watch } from 'vue'

const props = defineProps({ item: { type: Object, default: null }, identity: { type: String, default: null }, position: { type: Number, default: 0 }, flipped: Boolean, loading: Boolean, disabled: Boolean })
const emit = defineEmits(['flip', 'navigate', 'transition'])
const card = ref(null)
const content = ref(null)
const hintId = useId()
const displayedItem = shallowRef(props.item)
const displayedIdentity = ref(props.identity)
const displayedFlipped = ref(props.flipped)
const animating = ref(false)
const canNavigate = computed(() => !!props.item && !props.disabled && !props.loading)
const canInteract = computed(() => canNavigate.value && !animating.value)
const cardIdentity = computed(() => props.identity)
const text = value => typeof value === 'string' ? value.trim() : ''
const translation = computed(() => text(displayedItem.value?.content.term_zh))
const chineseDefinition = computed(() => text(displayedItem.value?.content.definition_zh))
const englishDefinition = computed(() => text(displayedItem.value?.content.definition))
const hasChinese = computed(() => !!(translation.value || chineseDefinition.value))
let pointer = null
let clickTimer = null
let pendingDirection = 0
watch(animating, value => emit('transition', value), { flush: 'sync' })
const selection = () => !!window.getSelection()?.toString()
const control = target => target instanceof Element && !!target.closest('button,a,input,textarea,select,summary,details,[data-no-flip],[contenteditable="true"]')
function cancelPointer() { pointer = null }
function cancelInteraction() { cancelPointer(); clearTimeout(clickTimer); clickTimer = null }
function requestFlip() {
  cancelInteraction()
  if (!canInteract.value || selection()) return
  // 同一帧内的连续输入只提交一次；焦点留在稳定的卡片外壳，不跟随内容重建。
  animating.value = true
  card.value?.focus({ preventScroll: true })
  emit('flip')
}
function keydown(event) {
  if (event.target !== card.value || !['Enter', ' '].includes(event.key)
    || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  event.preventDefault()
  if (!event.repeat) requestFlip()
}
function accessibleClick(event) {
  // 指针点击已由 pointerup 处理；保留读屏器发出的无指针 click。
  if (event.detail === 0 && !control(event.target)) requestFlip()
}
function pointerDown(event) {
  cancelInteraction()
  if (!event.isPrimary || event.button !== 0 || !canNavigate.value || control(event.target) || selection()) return
  pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, time: performance.now(), moved: false, direction: null,
    edge: event.clientX < 24 || event.clientX > window.innerWidth - 24 }
}
function pointerMove(event) {
  if (!pointer || pointer.id !== event.pointerId) return
  const x = Math.abs(event.clientX - pointer.x), y = Math.abs(event.clientY - pointer.y)
  if (Math.max(x, y) > 10) {
    pointer.moved = true
    pointer.direction ||= x >= y * 1.5 ? 'horizontal' : 'vertical'
  }
}
function pointerUp(event) {
  const start = pointer
  if (!start || start.id !== event.pointerId) return
  pointerMove(event); cancelPointer()
  if (!canNavigate.value || selection() || control(event.target)) return
  const dx = event.clientX - start.x, dy = event.clientY - start.y
  if (!start.edge && start.direction === 'horizontal' && Math.abs(dx) >= 60 && Math.abs(dx) >= Math.abs(dy) * 1.5) emit('navigate', dx < 0 ? 1 : -1)
  else if (!start.moved && performance.now() - start.time <= 350) {
    // 鼠标点击文字稍等双击选词；点击留白和触屏轻点立即响应。
    if (event.pointerType === 'mouse' && event.target.closest('h2,p,span')) clickTimer = setTimeout(requestFlip, 250)
    else requestFlip()
  }
}

watch([() => props.flipped, cardIdentity, () => props.loading, () => props.item, () => props.position], async (
  [flipped, identity, loading, item, position], [previousFlipped, previousIdentity, previousLoading, previousItem, previousPosition], onCleanup,
) => {
  cancelInteraction()
  let cancelled = false
  let animation = null
  onCleanup(() => { cancelled = true; animation?.cancel() })
  const changedWord = identity !== previousIdentity
  if (changedWord) pendingDirection = previousIdentity ? Math.sign(position - previousPosition) : 0
  const direction = pendingDirection
  const syncContent = () => {
    displayedItem.value = item
    displayedIdentity.value = identity
    displayedFlipped.value = flipped
  }
  // 缓存未命中时先显示加载状态，保留方向，正文到达后只播放入场。
  if (loading || !item || !card.value?.animate) {
    syncContent()
    animating.value = false
    return
  }
  if (direction && !window.matchMedia('(prefers-reduced-motion: reduce)').matches && content.value?.animate) {
    animating.value = true
    pendingDirection = 0
    try {
      // 固定卡片外壳与焦点，只移动内部内容，避免窄屏横向溢出及与翻转争抢 transform。
      if (displayedItem.value && displayedIdentity.value !== identity) {
        animation = content.value.animate([
          { transform: 'translateX(0)', opacity: 1 },
          { transform: `translateX(${-direction * 32}px)`, opacity: 0 },
        ], { duration: 100, easing: 'ease-in', fill: 'forwards' })
        await animation.finished
        if (cancelled) return
      }
      syncContent()
      await nextTick()
      if (cancelled) return
      animation?.cancel()
      animation = content.value.animate([
        { transform: `translateX(${direction * 32}px)`, opacity: 0 },
        { transform: 'translateX(0)', opacity: 1 },
      ], { duration: 140, easing: 'cubic-bezier(0.16, 1, 0.3, 1)', fill: 'forwards' })
      await animation.finished
    } catch (error) {
      if (!cancelled && error.name !== 'AbortError') throw error
    } finally {
      if (!cancelled) { syncContent(); animating.value = false; animation?.cancel() }
    }
    return
  }
  pendingDirection = 0
  displayedItem.value = item
  displayedIdentity.value = identity
  if (changedWord || previousLoading || !previousItem || flipped === previousFlipped) {
    syncContent()
    animating.value = false
    return
  }
  animating.value = true
  const flipDirection = flipped ? 1 : -1
  // 转向侧面时轻微后撤，避免透视放大后的卡片压住顶部进度与底部操作。
  const transform = angle => `perspective(1800px) rotateY(${angle}deg) scale(${1 - Math.abs(angle) / 360})`
  try {
    animation = card.value.animate([{ transform: transform(0) }, { transform: transform(flipDirection * 90) }], { duration: 160, easing: 'ease-in', fill: 'forwards' })
    await animation.finished
    if (cancelled) return
    // 只渲染当前面，在卡片侧立时替换；不预埋隐藏答案，也不让文字转成镜像。
    displayedFlipped.value = flipped
    await nextTick()
    if (cancelled) return
    animation.cancel()
    animation = card.value.animate([{ transform: transform(-flipDirection * 90) }, { transform: transform(0) }], { duration: 160, easing: 'ease-out', fill: 'forwards' })
    await animation.finished
  } catch (error) {
    // 切词或离页会取消 finished Promise；只有当前卡片能完成内容切换。
    if (!cancelled && error.name !== 'AbortError') throw error
  } finally {
    if (!cancelled) {
      displayedFlipped.value = flipped
      animating.value = false
      animation?.cancel()
    }
  }
})
onBeforeUnmount(() => { cancelInteraction(); emit('transition', false) })
</script>
