import assert from 'node:assert/strict'
import { findNearestTrendPoint, formatTrendPointLabel } from './trendPointLabel.js'

assert.equal(formatTrendPointLabel('count', 20), '答题数：20题')
assert.equal(formatTrendPointLabel('count', 0), '答题数：0题')
assert.equal(formatTrendPointLabel('accuracy', 80), '正确率：80%')
assert.equal(formatTrendPointLabel('accuracy', null), '正确率：—')

const countPoint = { series: 'count', clientX: 100, clientY: 10 }
const accuracyPoint = { series: 'accuracy', clientX: 100, clientY: 80 }
const candidates = [countPoint, accuracyPoint]

assert.equal(findNearestTrendPoint(candidates, 102, 12, 32), countPoint)
assert.equal(findNearestTrendPoint(candidates, 98, 82, 32), accuracyPoint)
assert.equal(findNearestTrendPoint(candidates, 200, 200, 32), null)

console.log('trendPointLabel tests passed')
