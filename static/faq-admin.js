/* FAQ admin form behaviour. The server remains responsible for every save. */
const category = document.querySelector("#question-category");
const programField = document.querySelector("#program-field");

function showFieldsForCategory() {
  const needsProgram = category.value === "program_specific";
  programField.hidden = !needsProgram;
}

category.addEventListener("change", showFieldsForCategory);
showFieldsForCategory();
