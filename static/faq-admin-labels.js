/*
 * Flow: the similarity API returns one FAQ result -> this helper creates the
 * readable label for its card -> faq-admin.js places that label beside radio.
 */

export function similarFaqLabel(item) {
  // Return the plain-text label for one similar-FAQ result card.
  const matchPercent = Math.round(item.similarity * 100);
  const source = item.has_program_specific_answers
    ? "different answers, four programme-specific answers"
    : `${item.question_category}, ${item.program_id}`;
  const exactDuplicate = item.is_exact ? " — exact duplicate" : "";
  return `${item.question} (${matchPercent}% matched; ${source})${exactDuplicate}`;
}
