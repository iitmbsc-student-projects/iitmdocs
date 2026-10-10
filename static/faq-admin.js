/*
 * Flow: choose FAQ type and write a question -> check similar FAQs -> choose
 * Add anyway or Update selected FAQ -> write/edit the required answer -> save.
 * The server validates every save and remains responsible for database writes.
 */
import { Marked } from "https://cdn.jsdelivr.net/npm/marked@13/+esm";
import DOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.2.6/+esm";

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
const singleAnswerField = document.querySelector("#single-answer-field");
const differentAnswerFields = document.querySelector("#different-answer-fields");
const answerProgramField = document.querySelector("#answer-program-field");
const answerProgram = document.querySelector("#answer-program-id");
const answers = Object.fromEntries(["ds", "ae", "es", "mg"].map((programId) => [programId, document.querySelector(`#answer-${programId}`)]));
const programAnswerFields = document.querySelectorAll(".program-answer-field");
const form = document.querySelector("#faq-form");
const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
let selectedFaqId = null;
let reviewComplete = false;
let actionMode = null;

function showFieldsForCategory() {
  const needsProgram = category.value === "program_specific";
  const needsDifferentAnswers = category.value === "diff_answers";
  programField.hidden = !needsProgram;
  answerEntry.hidden = actionMode === null;
  singleAnswerField.hidden = actionMode === null || needsDifferentAnswers;
  differentAnswerFields.hidden = actionMode === null || !needsDifferentAnswers;
  answerProgramField.hidden = actionMode === null || !needsDifferentAnswers;
  for (const field of programAnswerFields) {
    field.hidden = needsDifferentAnswers && answerProgram.value !== "all" && field.dataset.programId !== answerProgram.value;
  }
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
  for (const control of form.querySelectorAll("select, textarea")) control.disabled = isBusy;
  checkButton.disabled = isBusy;
  addButton.disabled = isBusy || !reviewComplete;
  updateButton.disabled = isBusy || !reviewComplete || selectedFaqId === null;
  saveButton.disabled = isBusy;
  cancelAnswerEntryButton.disabled = isBusy;
}

async function startAnswerEntry(mode) {
  actionMode = mode;
  resetActionButtons();
  showFieldsForCategory();

  if (mode === "add") {
    saveButton.textContent = "Save new FAQ";
    status.textContent = "Write the answer, then save the new FAQ.";
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
    status.textContent = "Edit the answer, then save your changes.";
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
  detail.textContent = `${item.question} (${Math.round(item.similarity * 100)}% matched; ${item.question_category}, ${item.program_id})${item.is_exact ? " — exact duplicate" : ""}`;
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

category.addEventListener("change", clearReviewedState);
question.addEventListener("input", clearReviewedState);
program.addEventListener("change", clearReviewedState);
answerProgram.addEventListener("change", showFieldsForCategory);
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
  clearAnswerFields();
  resetActionButtons();
  showFieldsForCategory();
  status.textContent = "Choose Add anyway or Update selected FAQ when you are ready to write an answer.";
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
