"""Browser entry point for the internal FAQ-admin workflow.

Flow: an admin opens ``/faq-admin`` -> Django sends the page and CSRF cookie ->
the page will later call its same-origin review and save endpoints.
"""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from .services import FaqAdminValidationError, find_similar_faqs


@ensure_csrf_cookie
def page(request):
    """Render the FAQ-admin form shell and issue its CSRF cookie.

    Example: ``GET /faq-admin`` returns the form before any database request.
    """
    return render(request, "faq_admin/page.html")


@require_POST
def check_similar(request):
    """Embed one drafted question and return its close stored FAQ matches."""
    try:
        body = json.loads(request.body)
        return JsonResponse({"matches": find_similar_faqs(body.get("question"))})
    except (json.JSONDecodeError, FaqAdminValidationError):
        return JsonResponse({"error": "Enter a question first."}, status=400)
    except Exception:
        return JsonResponse({"error": "Could not check similar FAQs. Try again."}, status=502)
