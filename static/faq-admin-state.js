/*
 * Flow: FAQ-admin JavaScript asks this small helper for the answer-safety
 * button state -> an accepted suggested answer keeps the button disabled -> a
 * manual answer edit clears approval and makes the button available again.
 */

export function shouldDisableAnswerSafetyCheck({formBusy, actionMode, answerSafetyApproved}) {
  // An accepted suggested answer stays approved until the admin changes it.
  return formBusy || actionMode === null || answerSafetyApproved;
}
