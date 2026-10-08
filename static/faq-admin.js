/* FAQ admin form behaviour. The server remains responsible for every save. */
const category = document.querySelector("#question-category");
const programField = document.querySelector("#program-field");
const question = document.querySelector("#question");
const checkButton = document.querySelector("#check-similar");
const status = document.querySelector("#form-status");
const results = document.querySelector("#similar-results");
const program = document.querySelector("#program-id");
const addButton = document.querySelector("#add-faq");

function showFieldsForCategory() {
  const needsProgram = category.value === "program_specific";
  programField.hidden = !needsProgram;
}

category.addEventListener("change", showFieldsForCategory);
showFieldsForCategory();

checkButton.addEventListener("click", async () => {
  checkButton.disabled = true;
  status.textContent = "Checking similar FAQs…";
  results.replaceChildren();
  try {
    const response = await fetch("/faq-admin/check-similar", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question: question.value, program_id: program.value})});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    const exact = body.matches.filter((item) => item.is_exact);
    status.textContent = exact.length ? "Exact duplicate found. Review it before adding a new FAQ." : body.matches.length ? "Similar FAQs found:" : "No close FAQ found. You may add this question.";
    for (const item of body.matches) {
      const row = document.createElement("p");
      row.textContent = `${item.question} (${Math.round(item.similarity * 100)}% matched; ${item.question_category}, ${item.program_id})${item.is_exact ? " — exact duplicate" : ""}`;
      results.append(row);
    }
    addButton.disabled = false;
  } catch (error) {
    status.textContent = error.message || "Could not check similar FAQs. Try again.";
  } finally { checkButton.disabled = false; }
});

addButton.addEventListener("click", async () => {
  if (!window.confirm("Add this FAQ to the current database?")) return;
  addButton.disabled = true;
  const payload = {question_category: category.value, program_id: program.value, question: question.value, answer: document.querySelector("#answer").value};
  try {
    const response = await fetch("/faq-admin/add", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    status.textContent = `FAQ added. Saved row: ${body.saved_ids.join(", ")}.`;
    results.replaceChildren();
  } catch (error) { status.textContent = error.message || "Could not save the FAQ. Try again."; }
});
