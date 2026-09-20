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

urlpatterns = [
    path("answer", views.AnswerView.as_view(), name="answer"),
    path("feedback", views.FeedbackView.as_view(), name="feedback"),
    path("faq/<int:faq_id>", views.FaqDetailView.as_view(), name="faq-detail"),
    path("health", views.HealthView.as_view(), name="health"),
    path("github-config", views.GithubConfigView.as_view(), name="github-config"),
    path("qa", RedirectView.as_view(url="/qa.html", query_string=True), name="qa"),
]
