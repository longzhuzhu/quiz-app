/** 趋势图数据点短文案：只报该点自己的值，不带日期、不叠另一条线。 */

export function formatTrendPointLabel(series, value) {
  if (series === 'count') return `答题数：${Number(value) || 0}题`
  if (value == null || Number.isNaN(Number(value))) return '正确率：—'
  return `正确率：${value}%`
}

export function findNearestTrendPoint(candidates, clientX, clientY, thresholdPx) {
  let best = null
  let bestDist = Infinity
  for (const candidate of candidates) {
    const dx = candidate.clientX - clientX
    const dy = candidate.clientY - clientY
    const dist = dx * dx + dy * dy
    if (dist < bestDist) {
      bestDist = dist
      best = candidate
    }
  }
  if (!best || bestDist > thresholdPx * thresholdPx) return null
  return best
}
