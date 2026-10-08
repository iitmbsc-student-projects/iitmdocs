/* FAQ admin form behaviour. The server remains responsible for every save. */
const category = document.querySelector("#question-category");
const programField = document.querySelector("#program-field");
const question = document.querySelector("#question");
const checkButton = document.querySelector("#check-similar");
const status = document.querySelector("#form-status");
const results = document.querySelector("#similar-results");

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
    const response = await fetch("/faq-admin/check-similar", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question: question.value})});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    status.textContent = body.matches.length ? "Similar FAQs found:" : "No close FAQ found. You may add this question.";
    for (const item of body.matches) {
      const row = document.createElement("p");
      row.textContent = `${item.question} (${Math.round(item.similarity * 100)}% matched; ${item.question_category}, ${item.program_id})`;
      results.append(row);
    }
  } catch (error) {
    status.textContent = error.message || "Could not check similar FAQs. Try again.";
  } finally { checkButton.disabled = false; }
});
