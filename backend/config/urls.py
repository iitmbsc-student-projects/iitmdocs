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
    path("faq-admin", faq_admin_views.page, name="faq-admin"),
    path("faq-admin/all-faqs", faq_admin_views.all_faqs, name="faq-admin-all-faqs"),
    path("faq-admin/unanswered-questions", faq_admin_views.unanswered_questions, name="faq-admin-unanswered-questions"),
    path("faq-admin/unanswered-questions/refresh", faq_admin_views.refresh_unanswered_questions_page, name="faq-admin-unanswered-questions-refresh"),
    path("faq-admin/unanswered-questions/<int:question_id>/reject", faq_admin_views.reject_unanswered_question_page, name="faq-admin-unanswered-questions-reject"),
    path("faq-admin/unanswered-questions/<int:question_id>/ai-help", faq_admin_views.temporary_ai_help_page, name="faq-admin-unanswered-questions-ai-help"),
    path("faq-admin/all-faqs/<int:faq_id>/edit", faq_admin_views.edit_all_faq, name="faq-admin-edit-all-faq"),
    path("faq-admin/all-faqs/<int:faq_id>/delete", faq_admin_views.delete_all_faq, name="faq-admin-delete-all-faq"),
    path("faq-admin/check-similar", faq_admin_views.check_similar, name="faq-admin-check-similar"),
    path("faq-admin/answer/<int:faq_id>", faq_admin_views.answer, name="faq-admin-answer"),
    path("faq-admin/check-answer-safety", faq_admin_views.check_answer_safety, name="faq-admin-check-answer-safety"),
    path("faq-admin/add", faq_admin_views.add, name="faq-admin-add"),
    path("faq-admin/update", faq_admin_views.update, name="faq-admin-update"),
    path("answer", views.AnswerView.as_view(), name="answer"),
    path("feedback", views.FeedbackView.as_view(), name="feedback"),
    path("faq/<int:faq_id>", views.FaqDetailView.as_view(), name="faq-detail"),
    path("health", views.HealthView.as_view(), name="health"),
    path("github-config", views.GithubConfigView.as_view(), name="github-config"),
    path("qa", RedirectView.as_view(url="/qa.html", query_string=True), name="qa"),
]
