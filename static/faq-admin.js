/*
 * Flow: choose FAQ type and write a question -> check similar FAQs -> choose
 * Add anyway or Update selected FAQ -> write/edit the required answer -> save.
 * The server validates every save and remains responsible for database writes.
 */
import { Marked } from "https://cdn.jsdelivr.net/npm/marked@13/+esm";
import DOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.2.6/+esm";
import { shouldDisableAnswerSafetyCheck } from "./faq-admin-state.js";
import { similarFaqLabel } from "./faq-admin-labels.js";

const marked = new Marked();
const category = document.querySelector("#question-category");
const programField = document.querySelector("#program-field");
const question = document.querySelector("#question");
const checkButton = document.querySelector("#check-similar");
const status = document.querySelector("#form-status");
const results = document.querySelector("#similar-results");
const program = document.querySelector("#program-id");
const addButton = document.querySelector("#add-faq");
const updateButton = document.querySelector("#update-faq");
const saveButton = document.querySelector("#save-faq");
const cancelAnswerEntryButton = document.querySelector("#cancel-answer-entry");
const answerEntry = document.querySelector("#answer-entry");
const addFlowNotice = document.querySelector("#add-flow-notice");
const questionLockInfoButton = document.querySelector("#question-lock-info");
const singleAnswerField = document.querySelector("#single-answer-field");
const differentAnswerFields = document.querySelector("#different-answer-fields");
const answerProgramField = document.querySelector("#answer-program-field");
const answerProgram = document.querySelector("#answer-program-id");
const answers = Object.fromEntries(["ds", "ae", "es", "mg"].map((programId) => [programId, document.querySelector(`#answer-${programId}`)]));
const programAnswerFields = document.querySelectorAll(".program-answer-field");
const answerSafetyButton = document.querySelector("#check-answer-safety");
const answerSafetyResults = document.querySelector("#answer-safety-results");
const answerSafetyInfoButton = document.querySelector("#answer-safety-info");
const answerSafetyNotice = document.querySelector("#answer-safety-notice");
const form = document.querySelector("#faq-form");
const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
let selectedFaqId = null;
let reviewComplete = false;
let actionMode = null;
let formBusy = false;
let addFlowNoticeExpanded = false;
let answerSafetyNoticeExpanded = false;
const safeAnswerValues = new Map();

function answerFieldsToCheck() {
  if (category.value !== "diff_answers") return [{key: "single", field: document.querySelector("#answer")}];
  const programIds = answerProgram.value === "all" ? Object.keys(answers) : [answerProgram.value];
  return programIds.map((programId) => ({key: programId, field: answers[programId]}));
}

function isAnswerSafetyApproved() {
  return actionMode !== null && answerFieldsToCheck().every(({key, field}) => safeAnswerValues.get(key) === field.value);
}

function clearAnswerSafetyReview() {
  safeAnswerValues.clear();
  answerSafetyResults.replaceChildren();
  answerSafetyResults.hidden = true;
}

function invalidateAnswerSafetyReview() {
  clearAnswerSafetyReview();
  if (!formBusy) setFormBusy(false);
}

function programmeLabel(programId) {
  return {ds: "Data Science", ae: "Aerospace Engineering", es: "Electronic Systems", mg: "Management"}[programId] || "This answer";
}

function syncInputAvailability() {
  const needsFaqType = category.value === "";
  const locksQuestionDetails = actionMode === "add";
  for (const control of form.querySelectorAll("select, textarea")) {
    const isQuestionDetail = control === category || control === program || control === question;
    control.disabled = formBusy || (needsFaqType && control !== category) || (locksQuestionDetails && isQuestionDetail);
  }
  checkButton.disabled = formBusy || needsFaqType || locksQuestionDetails;
  answerSafetyButton.hidden = actionMode === null;
  answerSafetyButton.disabled = shouldDisableAnswerSafetyCheck({
    formBusy,
    actionMode,
    answerSafetyApproved: isAnswerSafetyApproved(),
  });
  answerSafetyNotice.hidden = !answerSafetyNoticeExpanded;
  answerSafetyInfoButton.setAttribute("aria-expanded", String(answerSafetyNoticeExpanded));
  questionLockInfoButton.hidden = !locksQuestionDetails;
  addFlowNotice.hidden = !locksQuestionDetails || !addFlowNoticeExpanded;
  questionLockInfoButton.setAttribute("aria-expanded", String(locksQuestionDetails && addFlowNoticeExpanded));
}

function showFieldsForCategory() {
  const hasFaqType = category.value !== "";
  const needsProgram = category.value === "program_specific";
  const needsDifferentAnswers = category.value === "diff_answers";
  programField.hidden = !hasFaqType || !needsProgram;
  answerEntry.hidden = actionMode === null;
  singleAnswerField.hidden = actionMode === null || needsDifferentAnswers;
  differentAnswerFields.hidden = actionMode === null || !needsDifferentAnswers;
  answerProgramField.hidden = actionMode === null || !needsDifferentAnswers;
  for (const field of programAnswerFields) {
    field.hidden = needsDifferentAnswers && answerProgram.value !== "all" && field.dataset.programId !== answerProgram.value;
  }
  syncInputAvailability();
}

function resetActionButtons() {
  const choosingAction = actionMode === null;
  addButton.hidden = !choosingAction;
  updateButton.hidden = !choosingAction;
  saveButton.hidden = choosingAction;
  cancelAnswerEntryButton.hidden = choosingAction;
  addButton.disabled = !reviewComplete;
  updateButton.disabled = !reviewComplete || selectedFaqId === null;
}

function clearAnswerFields() {
  document.querySelector("#answer").value = "";
  for (const field of Object.values(answers)) field.value = "";
  answerProgram.value = "all";
}

function clearReviewedState() {
  selectedFaqId = null;
  reviewComplete = false;
  actionMode = null;
  addFlowNoticeExpanded = false;
  answerSafetyNoticeExpanded = false;
  clearAnswerSafetyReview();
  clearAnswerFields();
  resetActionButtons();
  results.replaceChildren();
  showFieldsForCategory();
}

function answerPayload() {
  if (category.value !== "diff_answers") return {answer: document.querySelector("#answer").value};
  return {
    answer_program_id: answerProgram.value,
    answers: Object.fromEntries(Object.entries(answers).map(([programId, field]) => [programId, field.value])),
  };
}

function setFormBusy(isBusy) {
  formBusy = isBusy;
  syncInputAvailability();
  addButton.disabled = isBusy || !reviewComplete;
  updateButton.disabled = isBusy || !reviewComplete || selectedFaqId === null;
  saveButton.disabled = isBusy || !isAnswerSafetyApproved();
  cancelAnswerEntryButton.disabled = isBusy;
}

async function startAnswerEntry(mode) {
  actionMode = mode;
  addFlowNoticeExpanded = false;
  answerSafetyNoticeExpanded = false;
  resetActionButtons();
  showFieldsForCategory();

  if (mode === "add") {
    saveButton.textContent = "Save new FAQ";
    status.textContent = "Write the answer, then check answer safety before saving the new FAQ.";
    return;
  }

  saveButton.textContent = "Save changes";
  setFormBusy(true);
  status.textContent = "Loading the selected FAQ answer…";
  try {
    const response = await fetch(`/faq-admin/answer/${selectedFaqId}`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);

    question.value = body.question;
    if (body.question_category === "diff_answers") {
      answerProgram.value = body.program_id;
      answers[body.program_id].value = body.answer;
    } else {
      document.querySelector("#answer").value = body.answer;
    }
    showFieldsForCategory();
    status.textContent = "Edit the answer, then check answer safety before saving your changes.";
  } catch (error) {
    actionMode = null;
    resetActionButtons();
    showFieldsForCategory();
    status.textContent = error.message || "Could not load the selected FAQ answer. Try again.";
  } finally {
    setFormBusy(false);
  }
}

function addResultCard(item) {
  const card = document.createElement("label");
  card.className = "similar-result";
  const radio = document.createElement("input");
  radio.type = "radio";
  radio.name = "selected-faq";
  radio.value = String(item.id);
  radio.addEventListener("change", () => {
    selectedFaqId = item.id;
    category.value = item.question_category;
    if (item.question_category === "program_specific") program.value = item.program_id;
    showFieldsForCategory();
    resetActionButtons();
    status.textContent = `Selected FAQ ${item.id} for update. The form now shows its FAQ type; the server will verify it again before saving.`;
  });
  const detail = document.createElement("span");
  detail.textContent = similarFaqLabel(item);
  const answerButton = document.createElement("button");
  answerButton.type = "button";
  answerButton.className = "answer-toggle";
  answerButton.textContent = "View current answer";
  const answerPreview = document.createElement("div");
  answerPreview.className = "answer-preview";
  answerPreview.hidden = true;
  let answerLoaded = false;

  answerButton.addEventListener("click", async (event) => {
    event.preventDefault();
    if (answerLoaded) {
      answerPreview.hidden = !answerPreview.hidden;
      answerButton.textContent = answerPreview.hidden ? "View current answer" : "Hide current answer";
      return;
    }

    answerButton.disabled = true;
    answerButton.textContent = "Loading answer…";
    try {
      const response = await fetch(`/faq-admin/answer/${item.id}`);
      const body = await response.json();
      if (!response.ok) throw new Error(body.error);
      // Marked creates HTML; DOMPurify removes unsafe HTML before it is shown.
      answerPreview.innerHTML = DOMPurify.sanitize(marked.parse(body.answer));
      answerPreview.hidden = false;
      answerLoaded = true;
      answerButton.textContent = "Hide current answer";
    } catch (error) {
      status.textContent = error.message || "Could not load the FAQ answer. Try again.";
      answerButton.textContent = "View current answer";
    } finally {
      answerButton.disabled = false;
    }
  });

  card.append(radio, detail, answerButton, answerPreview);
  results.append(card);
}

category.addEventListener("change", () => {
  if (category.value === "") return;
  category.querySelector('option[value=""]')?.remove();
  clearReviewedState();
});
question.addEventListener("input", clearReviewedState);
program.addEventListener("change", clearReviewedState);
answerProgram.addEventListener("change", () => {
  showFieldsForCategory();
  invalidateAnswerSafetyReview();
});
document.querySelector("#answer").addEventListener("input", invalidateAnswerSafetyReview);
for (const field of Object.values(answers)) field.addEventListener("input", invalidateAnswerSafetyReview);
questionLockInfoButton.addEventListener("click", () => {
  addFlowNoticeExpanded = !addFlowNoticeExpanded;
  syncInputAvailability();
});
answerSafetyInfoButton.addEventListener("click", () => {
  answerSafetyNoticeExpanded = !answerSafetyNoticeExpanded;
  syncInputAvailability();
});
showFieldsForCategory();

checkButton.addEventListener("click", async () => {
  setFormBusy(true);
  status.textContent = "Checking similar FAQs…";
  clearReviewedState();
  try {
    const response = await fetch("/faq-admin/check-similar", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken}, body: JSON.stringify({question: question.value, program_id: program.value})});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    const exact = body.matches.filter((item) => item.is_exact);
    status.textContent = exact.length ? "Exact duplicate found. Review it before adding a new FAQ." : body.matches.length ? "Similar FAQs found:" : "No close FAQ found. You may add this question.";
    for (const item of body.matches) addResultCard(item);
    reviewComplete = true;
    resetActionButtons();
  } catch (error) {
    status.textContent = error.message || "Could not check similar FAQs. Try again.";
  } finally { setFormBusy(false); }
});

addButton.addEventListener("click", () => startAnswerEntry("add"));

updateButton.addEventListener("click", () => {
  if (selectedFaqId !== null) startAnswerEntry("update");
});

cancelAnswerEntryButton.addEventListener("click", () => {
  actionMode = null;
  answerSafetyNoticeExpanded = false;
  clearAnswerFields();
  resetActionButtons();
  showFieldsForCategory();
  status.textContent = "Choose Add anyway or Update selected FAQ when you are ready to write an answer.";
});

function addSafetyResultCard(item) {
  const card = document.createElement("section");
  const rejected = item.likely_to_be_rejected_by_fact_checker === "yes";
  card.className = `answer-safety-result ${rejected ? "warning" : "safe"}`;
  const label = category.value === "diff_answers" ? `${programmeLabel(item.program_id)}: ` : "";
  const heading = document.createElement("strong");
  heading.textContent = rejected
    ? `${label}This answer may be rejected by the fact-checker.`
    : `${label}This answer is unlikely to be rejected by the fact-checker.`;
  card.append(heading);
  if (!rejected) {
    answerSafetyResults.append(card);
    return;
  }

  const rule = document.createElement("p");
  rule.textContent = `Relevant fact-checker rule: ${item.exact_line_from_fact_checker_prompt_because_of_which_rejection_is_possible}`;
  const suggestion = document.createElement("p");
  suggestion.textContent = `Suggested answer: ${item.suggested_answer_likely_to_pass_fact_checker}`;
  const useSuggestionButton = document.createElement("button");
  useSuggestionButton.type = "button";
  useSuggestionButton.className = "secondary-button";
  useSuggestionButton.textContent = "Use suggested answer";
  useSuggestionButton.addEventListener("click", () => {
    const field = item.program_id === "single" ? document.querySelector("#answer") : answers[item.program_id];
    field.value = item.suggested_answer_likely_to_pass_fact_checker;
    safeAnswerValues.set(item.program_id, field.value);
    useSuggestionButton.disabled = true;
    useSuggestionButton.textContent = "Suggested answer applied";
    setFormBusy(false);
  });
  card.append(rule, suggestion, useSuggestionButton);
  answerSafetyResults.append(card);
}

answerSafetyButton.addEventListener("click", async () => {
  const payload = actionMode === "add"
    ? {action: "add", question_category: category.value, program_id: program.value, question: question.value, ...answerPayload()}
    : {action: "update", selected_faq_id: selectedFaqId, question: question.value, ...answerPayload()};
  setFormBusy(true);
  status.textContent = "Checking answer safety…";
  clearAnswerSafetyReview();
  try {
    const response = await fetch("/faq-admin/check-answer-safety", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken}, body: JSON.stringify(payload)});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    for (const item of body.results) {
      const key = category.value === "diff_answers" ? item.program_id : "single";
      const field = key === "single" ? document.querySelector("#answer") : answers[key];
      if (item.likely_to_be_rejected_by_fact_checker === "no") safeAnswerValues.set(key, field.value);
      addSafetyResultCard({...item, program_id: key});
    }
    answerSafetyResults.hidden = false;
    status.textContent = isAnswerSafetyApproved()
      ? "Answer safety check complete. You can save this FAQ."
      : "Review the suggested answer before saving this FAQ.";
  } catch (error) {
    status.textContent = error.message || "Could not check answer safety. Try again.";
  } finally {
    setFormBusy(false);
  }
});

saveButton.addEventListener("click", async () => {
  if (actionMode === "add") {
    await saveNewFaq();
    return;
  }
  if (actionMode === "update") await saveUpdatedFaq();
});

async function saveNewFaq() {
  if (!window.confirm("Add this FAQ to the current database?")) return;
  setFormBusy(true);
  const payload = {question_category: category.value, program_id: program.value, question: question.value, ...answerPayload()};
  try {
    const response = await fetch("/faq-admin/add", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken}, body: JSON.stringify(payload)});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    status.textContent = `FAQ added. Saved row: ${body.saved_ids.join(", ")}.`;
    clearReviewedState();
  } catch (error) { status.textContent = error.message || "Could not save the FAQ. Try again."; }
  finally { setFormBusy(false); }
}

async function saveUpdatedFaq() {
  if (selectedFaqId === null) return;
  if (!window.confirm(`Update the selected FAQ (row ${selectedFaqId}) in the current database?`)) return;
  setFormBusy(true);
  const payload = {selected_faq_id: selectedFaqId, question: question.value, ...answerPayload()};
  try {
    const response = await fetch("/faq-admin/update", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken}, body: JSON.stringify(payload)});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    status.textContent = `FAQ updated (${body.question_category}; ${body.program_ids.join(", ")}). Changed row: ${body.updated_ids.join(", ")}.`;
    clearReviewedState();
  } catch (error) { status.textContent = error.message || "Could not update the FAQ. Try again."; }
  finally { setFormBusy(false); }
}
