let activeStudy = null
let generation = 0

export function studyGeneration() { return generation }
export function registerActiveStudy(study) {
  activeStudy = study
  return () => { if (activeStudy === study) activeStudy = null }
}
export async function waitForStudySave() { await activeStudy?.waitForSave() }
export async function prepareStudyContextChange() {
  const previous = activeStudy
  await previous?.suspendForContextChange()
  return () => previous?.resumeAfterContextFailure()
}
export function invalidateStudyAccount() {
  generation++
  const previous = activeStudy
  activeStudy = null
  return previous?.dispose({ clearAccount: true })
}
