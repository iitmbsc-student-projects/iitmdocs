"""URL routing for the chatbot backend.

Public contract (must match the old Worker + FAQ API byte-for-byte):
  POST /answer        -> SSE stream (text/event-stream)
  POST /feedback      -> JSON
  GET  /faq/<int:id>  -> JSON  (direct FAQ lookup)
  GET  /health        -> {"ok": true}
  GET  /github-config -> browser-safe reference document configuration
Everything else (GET /, /qa.html, /qa.js, ...) is served by the ASGI static layer.
"""
from django.urls import path
from django.views.generic import RedirectView

from chatbot import views
from faq_admin import views as faq_admin_views

urlpatterns = [
    # Main internal page for drafting, checking, and saving FAQ changes.
    path("faq-admin", faq_admin_views.page, name="faq-admin"),
    # Read-only list of every FAQ row, grouped by question category.
    path("faq-admin/all-faqs", faq_admin_views.all_faqs, name="faq-admin-all-faqs"),
    # Read-only audit list of accepted and rejected unanswered-question rows.
    path("faq-admin/all-unanswered-questions", faq_admin_views.all_unanswered_questions, name="faq-admin-all-unanswered-questions"),
    # Action page for pending unanswered questions imported from Test logs.
    path("faq-admin/unanswered-questions", faq_admin_views.unanswered_questions, name="faq-admin-unanswered-questions"),
    # Manual import of eligible questions from the previous seven days of Test logs.
    path("faq-admin/unanswered-questions/refresh", faq_admin_views.refresh_unanswered_questions_page, name="faq-admin-unanswered-questions-refresh"),
    # Hide one unanswered-question row after the admin rejects it.
    path("faq-admin/unanswered-questions/<int:question_id>/reject", faq_admin_views.reject_unanswered_question_page, name="faq-admin-unanswered-questions-reject"),
    # Ask AI whether one unanswered question needs an FAQ, then save its review.
    path("faq-admin/unanswered-questions/<int:question_id>/ai-help", faq_admin_views.ai_help_page, name="faq-admin-unanswered-questions-ai-help"),
    # Display and save edits to a selected FAQ database row.
    path("faq-admin/all-faqs/<int:faq_id>/edit", faq_admin_views.edit_all_faq, name="faq-admin-edit-all-faq"),
    # Permanently delete a selected FAQ database row.
    path("faq-admin/all-faqs/<int:faq_id>/delete", faq_admin_views.delete_all_faq, name="faq-admin-delete-all-faq"),
    # Return nearby FAQ questions for a drafted FAQ question.
    path("faq-admin/check-similar", faq_admin_views.check_similar, name="faq-admin-check-similar"),
    # Return one FAQ answer for an on-page similar-question preview.
    path("faq-admin/answer/<int:faq_id>", faq_admin_views.answer, name="faq-admin-answer"),
    # Check a drafted answer against fact-checker rules before it is saved.
    path("faq-admin/check-answer-safety", faq_admin_views.check_answer_safety, name="faq-admin-check-answer-safety"),
    # Save a new FAQ after the browser-side review flow completes.
    path("faq-admin/add", faq_admin_views.add, name="faq-admin-add"),
    # Save edits to an existing FAQ selected from a similarity result.
    path("faq-admin/update", faq_admin_views.update, name="faq-admin-update"),
    # Stream the chatbot's answer to a user question.
    path("answer", views.AnswerView.as_view(), name="answer"),
    # Record user feedback for a completed chatbot answer.
    path("feedback", views.FeedbackView.as_view(), name="feedback"),
    # Return one FAQ directly when a client already knows its database ID.
    path("faq/<int:faq_id>", views.FaqDetailView.as_view(), name="faq-detail"),
    # Health endpoint used by deployment and availability checks.
    path("health", views.HealthView.as_view(), name="health"),
    # Return browser-safe configuration for GitHub reference documents.
    path("github-config", views.GithubConfigView.as_view(), name="github-config"),
    # Redirect the legacy QA route to its static browser page.
    path("qa", RedirectView.as_view(url="/qa.html", query_string=True), name="qa"),
]
