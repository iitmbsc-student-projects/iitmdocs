# First-pass comparison: AE docs and qualifier handbook

Source compared:

- Existing documents in `src/ae/`
- `May 2026 IITM BS AE Degree Programme - QUALIFIER-HANDBOOK.docx`

## Outdated or unclear information

- `src/ae/admission_paths.md` repeats the regular-entry rule and presents 2026 JEE-cycle examples without the handbook's current table wording. Consolidate the repeated text and add the handbook's JEE eligibility wording and examples.
- `src/ae/eligibility_criteria.md` and `src/ae/qualifier_registration.md` contain awkward duplicated wording for AE qualifier eligibility. Rewrite it as the handbook's two separate conditions: eligibility to apply for the qualifier and eligibility to proceed to Foundation Level.
- `src/ae/course_registration.md` and `src/ae/passing_criteria.md` state that the qualifier score is both considered and not considered as Quiz 1 without clearly separating same-term registration from subsequent-term registration. Clarify the distinction using the handbook.
- `src/ae/exam_eligibility.md` has the handbook's assignment cutoffs but omits the explicit note that in-term reattempts are provided suitably. Add that wording where it explains the two attempts.
- `src/ae/score_validity.md` has older 2026 score-validity examples. Preserve those examples as additional information and add the handbook's current Sep 2026 and Jan 2027 examples; do not treat the different examples as a source conflict.

## Missing information to add

- Add the handbook's explicit Foundation Level requirement that AE applicants must satisfy both the Physics-and-Mathematics requirement and the Class 12/equivalent requirement.
- Add the handbook's current JEE table wording: eligible candidates include JEE Main-qualified candidates eligible for JEE Advanced, or JEE Advanced-qualified candidates.
- Add the handbook's statement that the program credentials depend on courses completed and credits earned.
- Add the handbook's current score-validity examples for Sep 2026 and Jan 2027 qualifier terms.

## Genuine source conflicts

None identified in this pass. The different date examples are treated as additional examples because the handbook and existing docs do not state mutually exclusive rules.

## Planned first-pass updates

Update only the affected AE documents, preserve existing AE-related information, review each changed document's YAML front matter, and make the required first-pass commit after the edits.
