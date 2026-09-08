const MODE_LABELS = {
  sequential: '顺序练习',
  random: '随机练习',
  exam: '模拟考试',
  wrong_practice: '错题练习',
  topic: '专项练习',
}

export function modeLabel(mode) {
  return MODE_LABELS[mode] || '练习'
}

/** 会话的模式描述；专项练习补上所练考点，未分类的专项显示为「未分类」 */
export function sessionModeLabel(session) {
  const label = modeLabel(session?.mode)
  if (session?.mode !== 'topic') return label
  return `${label} · ${session.topic_short_name || '未分类'}`
}
