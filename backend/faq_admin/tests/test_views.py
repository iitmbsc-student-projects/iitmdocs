from django.test import Client, SimpleTestCase
from unittest import mock


class FaqAdminPageTests(SimpleTestCase):
    @mock.patch("faq_admin.views.list_all_unanswered_questions")
    def test_all_unanswered_questions_page_shows_every_admin_decision(self, list_questions):
        list_questions.return_value = [
            {
                "id": 7,
                "program_id": "ds",
                "original_question": "Can I use headphones during an exam?",
                "rewritten_question": "headphones exam rules",
                "rejection_reason": "fact_check_failed",
                "original_answer": "Yes.",
                "fact_check_passed": False,
                "fact_check_rejection_reason": "Unsupported.",
                "accepted_or_rejected_by_admin": "accepted",
                "ai_suggestion": "should_be_added",
                "ai_reason": "No available FAQ covers this.",
                "matching_faq_ids": [],
                "suggested_clean_question": "Can I use headphones during an exam?",
            },
            {
                "id": 8,
                "program_id": "ae",
                "original_question": "Can I bring a drone to class?",
                "rewritten_question": None,
                "rejection_reason": "fact_check_failed",
                "original_answer": None,
                "fact_check_passed": False,
                "fact_check_rejection_reason": None,
                "accepted_or_rejected_by_admin": "rejected",
                "ai_suggestion": None,
            },
            {
                "id": 9,
                "program_id": "mg",
                "original_question": "How is a project assessed?",
                "rewritten_question": None,
                "rejection_reason": "fact_check_failed",
                "original_answer": None,
                "fact_check_passed": False,
                "fact_check_rejection_reason": None,
                "accepted_or_rejected_by_admin": "completed",
                "ai_suggestion": None,
            },
        ]

        response = self.client.get("/faq-admin/all-unanswered-questions")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "All unanswered-question rows")
        self.assertContains(response, "Can I use headphones during an exam?")
        self.assertContains(response, "Can I bring a drone to class?")
        self.assertContains(response, "accepted")
        self.assertContains(response, "rejected")
        self.assertContains(response, "completed")
        self.assertContains(response, "should_be_added")
        self.assertContains(response, "No available FAQ covers this.")
        self.assertContains(response, "Clean question")
        list_questions.assert_called_once_with()

    @mock.patch("faq_admin.views.list_accepted_unanswered_questions")
    def test_unanswered_questions_page_shows_pending_admin_review_rows(self, list_questions):
        list_questions.return_value = [{
            "id": 7,
            "program_id": "ds",
            "original_question": "Can I use headphones during an exam?",
            "rewritten_question": "headphones exam rules",
            "rejection_reason": "fact_check_failed",
            "original_answer": "Yes.",
            "fact_check_passed": False,
            "fact_check_rejection_reason": "Unsupported.",
            "accepted_or_rejected_by_admin": "accepted",
            "ai_suggestion": None,
            "ai_reason": None,
            "matching_faq_ids": [],
            "suggested_clean_question": None,
        }]

        response = self.client.get("/faq-admin/unanswered-questions")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unanswered question review")
        self.assertContains(response, "Can I use headphones during an exam?")
        self.assertContains(response, "Refresh last 7 days")
        self.assertContains(response, "Get AI help for this question")
        self.assertContains(response, "Reject this question")
        self.assertContains(response, "Mark as completed")
        self.assertContains(response, "Fact-check rejection reason:")
        self.assertNotContains(response, "Rejection reason:")
        self.assertNotContains(response, "Fact checker:")

    @mock.patch("faq_admin.views.refresh_unanswered_questions")
    def test_refresh_endpoint_runs_the_manual_log_import(self, refresh_questions):
        refresh_questions.return_value = {"log_count": 3, "candidate_count": 2, "inserted_count": 1}

        response = self.client.post("/faq-admin/unanswered-questions/refresh")

        self.assertRedirects(
            response,
            "/faq-admin/unanswered-questions?notice=Reviewed+3+logs%3B+added+1+new+question.",
            fetch_redirect_response=False,
        )
        refresh_questions.assert_called_once_with()

    @mock.patch("faq_admin.views.reject_unanswered_question")
    def test_reject_endpoint_hides_the_selected_question(self, reject_question):
        response = self.client.post("/faq-admin/unanswered-questions/7/reject")

        self.assertRedirects(response, "/faq-admin/unanswered-questions", fetch_redirect_response=False)
        reject_question.assert_called_once_with(7)

    @mock.patch("faq_admin.views.complete_unanswered_question")
    def test_complete_endpoint_hides_the_selected_question(self, complete_question):
        response = self.client.post("/faq-admin/unanswered-questions/7/complete")

        self.assertRedirects(response, "/faq-admin/unanswered-questions", fetch_redirect_response=False)
        complete_question.assert_called_once_with(7)

    @mock.patch("faq_admin.views.review_unanswered_question")
    def test_ai_help_endpoint_saves_the_real_review_result(self, review_question):
        review_question.return_value = {"ai_suggestion": "should_be_added"}

        response = self.client.post("/faq-admin/unanswered-questions/7/ai-help")

        self.assertRedirects(
            response,
            "/faq-admin/unanswered-questions",
            fetch_redirect_response=False,
        )
        review_question.assert_called_once_with(7)

    def test_unanswered_question_actions_require_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post("/faq-admin/unanswered-questions/7/reject")

        self.assertEqual(response.status_code, 403)

        response = csrf_client.post("/faq-admin/unanswered-questions/7/complete")

        self.assertEqual(response.status_code, 403)

    @mock.patch("faq_admin.views.list_all_faqs")
    def test_all_faqs_page_shows_every_database_column_and_row_actions(self, list_all_faqs):
        list_all_faqs.return_value = [{
            "id": 8,
            "program_id": "ae",
            "question": "How do I pay fees?",
            "answer": "Pay before the deadline.",
            "question_category": "program_specific",
            "embedding": [0.1, 0.2],
        }]

        response = self.client.get("/faq-admin/all-faqs")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "All FAQ rows")
        self.assertContains(response, "How do I pay fees?")
        self.assertContains(response, "program_specific")
        self.assertContains(response, "/faq-admin/all-faqs/8/edit")
        self.assertContains(response, "/faq-admin/all-faqs/8/delete")
        list_all_faqs.assert_called_once_with()

    @mock.patch("faq_admin.views.list_all_faqs")
    def test_all_faqs_page_groups_rows_into_category_dropdowns(self, list_all_faqs):
        list_all_faqs.return_value = [
            {"id": 8, "program_id": "ae", "question": "AE question", "answer": "AE answer", "question_category": "program_specific", "embedding": None},
            {"id": 9, "program_id": "common", "question": "Common question", "answer": "Common answer", "question_category": "common", "embedding": None},
            {"id": 10, "program_id": "common", "question": "Old question", "answer": "Old answer", "question_category": None, "embedding": None},
        ]

        response = self.client.get("/faq-admin/all-faqs")

        self.assertContains(response, "Question category: Common to all programmes")
        self.assertContains(response, "Question category: Programme-specific")
        self.assertContains(response, "Question category: Uncategorised")
        self.assertContains(response, "Common question")
        self.assertContains(response, "AE question")
        self.assertContains(response, "Old question")

    @mock.patch("faq_admin.views.list_all_faqs", return_value=[])
    def test_all_faqs_page_sets_a_csrf_cookie_for_delete_forms(self, list_all_faqs):
        response = self.client.get("/faq-admin/all-faqs")

        self.assertIn("csrftoken", response.cookies)

    @mock.patch("faq_admin.views.delete_faq_from_management")
    @mock.patch("faq_admin.views.list_all_faqs", return_value=[])
    def test_all_faqs_delete_accepts_the_csrf_token_from_its_list_page(self, list_all_faqs, delete_faq_from_management):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.get("/faq-admin/all-faqs")
        csrf_token = csrf_client.cookies["csrftoken"].value

        response = csrf_client.post(
            "/faq-admin/all-faqs/8/delete",
            {"csrfmiddlewaretoken": csrf_token},
        )

        self.assertRedirects(response, "/faq-admin/all-faqs", fetch_redirect_response=False)
        delete_faq_from_management.assert_called_once_with(8)

    @mock.patch("faq_admin.views.get_faq_for_management")
    def test_all_faqs_edit_page_shows_the_selected_row(self, get_faq_for_management):
        get_faq_for_management.return_value = {
            "id": 8,
            "program_id": "ae",
            "question": "How do I pay fees?",
            "answer": "Pay before the deadline.",
            "question_category": "program_specific",
            "embedding": [0.1, 0.2],
        }

        response = self.client.get("/faq-admin/all-faqs/8/edit")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit FAQ row #8")
        self.assertContains(response, "Pay before the deadline.")
        self.assertContains(response, "program_specific")
        get_faq_for_management.assert_called_once_with(8)

    @mock.patch("faq_admin.views.update_faq_from_management")
    def test_all_faqs_edit_saves_the_selected_question_and_answer(self, update_faq_from_management):
        response = self.client.post(
            "/faq-admin/all-faqs/8/edit",
            {"question": "How do I pay fees now?", "answer": "Pay online."},
        )

        self.assertRedirects(response, "/faq-admin/all-faqs", fetch_redirect_response=False)
        update_faq_from_management.assert_called_once_with(8, "How do I pay fees now?", "Pay online.")

    @mock.patch("faq_admin.views.delete_faq_from_management")
    def test_all_faqs_delete_removes_the_selected_row(self, delete_faq_from_management):
        response = self.client.post("/faq-admin/all-faqs/8/delete")

        self.assertRedirects(response, "/faq-admin/all-faqs", fetch_redirect_response=False)
        delete_faq_from_management.assert_called_once_with(8)

    def test_page_opens_at_the_internal_url(self):
        response = self.client.get("/faq-admin")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FAQ Admin")
        self.assertContains(response, "Check similar FAQs")
        self.assertContains(response, "Update selected FAQ")
        self.assertContains(response, '<option value="" selected disabled>Select an FAQ type</option>')
        self.assertContains(response, 'id="program-id"')
        self.assertContains(response, 'id="program-id" name="program_id" disabled')
        self.assertContains(response, 'id="question" name="question" rows="3" disabled')
        self.assertContains(response, 'id="check-similar" class="primary-button" type="button" disabled')
        self.assertContains(response, 'id="question-lock-info"')
        self.assertContains(response, 'id="add-flow-notice" class="add-flow-notice" hidden')
        self.assertContains(response, 'id="answer-program-field"')
        self.assertContains(response, 'id="answer-entry" hidden')
        self.assertContains(response, 'id="check-answer-safety"')
        self.assertContains(response, 'id="answer-safety-results"')
        self.assertContains(response, 'id="answer-safety-info"')
        self.assertContains(response, 'id="answer-safety-notice"')
        self.assertContains(response, "/faq-admin/unanswered-questions")
        self.assertContains(response, "/faq-admin.js")

    @mock.patch("faq_admin.views.find_similar_faqs")
    def test_similarity_endpoint_returns_matching_faqs(self, find_similar_faqs):
        find_similar_faqs.return_value = [{"id": 8, "question": "How do I pay fees?", "program_id": "ds", "question_category": "program_specific", "similarity": 0.82}]

        response = self.client.post("/faq-admin/check-similar", data='{"question": "fee payment procedure", "program_id": "ds"}', content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matches"][0]["id"], 8)
        find_similar_faqs.assert_called_once_with("fee payment procedure", "ds")

    @mock.patch("faq_admin.views.add_new_faq")
    def test_add_endpoint_returns_saved_row_ids(self, add_new_faq):
        add_new_faq.return_value = [31]

        response = self.client.post("/faq-admin/add", data='{"question_category":"program_specific","program_id":"ds","question":"New FAQ?","answer":"New answer"}', content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved_ids": [31]})

    @mock.patch("faq_admin.views.review_answer_safety", new_callable=mock.AsyncMock)
    def test_answer_safety_endpoint_checks_the_validated_new_answer(self, check_answer_safety):
        check_answer_safety.return_value = {
            "likely_to_be_rejected_by_fact_checker": "no",
            "exact_line_from_fact_checker_prompt_because_of_which_rejection_is_possible": "NA",
            "suggested_answer_likely_to_pass_fact_checker": "NA",
        }

        response = self.client.post(
            "/faq-admin/check-answer-safety",
            data=(
                '{"action":"add","question_category":"program_specific",'
                '"program_id":"ds","question":"New FAQ?","answer":"New answer"}'
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["program_id"], "ds")
        self.assertEqual(response.json()["results"][0]["likely_to_be_rejected_by_fact_checker"], "no")
        check_answer_safety.assert_awaited_once_with("New answer")

    def test_answer_safety_endpoint_rejects_a_request_without_a_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(
            "/faq-admin/check-answer-safety",
            data=(
                '{"action":"add","question_category":"program_specific",'
                '"program_id":"ds","question":"New FAQ?","answer":"New answer"}'
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    @mock.patch("faq_admin.views.update_existing_faq")
    def test_update_endpoint_returns_the_rows_changed(self, update_existing_faq):
        update_existing_faq.return_value = {
            "updated_ids": [8],
            "question_category": "program_specific",
            "program_ids": ["ds"],
        }

        response = self.client.post(
            "/faq-admin/update",
            data=(
                '{"selected_faq_id":8,"question":"Updated FAQ?",'
                '"answer":"Updated answer"}'
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["updated_ids"], [8])
        update_existing_faq.assert_called_once_with(
            {"selected_faq_id": 8, "question": "Updated FAQ?", "answer": "Updated answer"}
        )

    def test_update_endpoint_rejects_a_request_without_a_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(
            "/faq-admin/update",
            data='{"selected_faq_id":8,"question":"Updated FAQ?","answer":"Updated answer"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    @mock.patch("faq_admin.views.add_new_faq")
    def test_add_endpoint_accepts_the_test_cloud_run_origin(self, add_new_faq):
        """The Test FAQ-admin page must be allowed to save back to its own URL."""
        add_new_faq.return_value = [31]
        csrf_client = Client(enforce_csrf_checks=True)
        origin = "https://iitm-chatbot-worker-140256174016.asia-south1.run.app"

        csrf_client.get("/faq-admin", secure=True)
        csrf_token = csrf_client.cookies["csrftoken"].value
        response = csrf_client.post(
            "/faq-admin/add",
            data=(
                '{"question_category":"program_specific","program_id":"ds",'
                '"question":"New FAQ?","answer":"New answer"}'
            ),
            content_type="application/json",
            secure=True,
            HTTP_ORIGIN=origin,
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"saved_ids": [31]})

    @mock.patch("faq_admin.views.get_faq_answer")
    def test_answer_endpoint_returns_one_selected_faq_answer(self, get_faq_answer):
        get_faq_answer.return_value = {
            "id": 8,
            "question": "How do I pay fees?",
            "answer": "Pay before the deadline.",
            "program_id": "ae",
            "question_category": "program_specific",
        }

        response = self.client.get("/faq-admin/answer/8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["question"], "How do I pay fees?")
        self.assertEqual(response.json()["answer"], "Pay before the deadline.")
        get_faq_answer.assert_called_once_with(8)
