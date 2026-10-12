"""Browser entry point for the internal FAQ-admin workflow.

Flow: an admin opens ``/faq-admin`` -> Django sends the page and CSRF cookie ->
the page will later call its same-origin review and save endpoints.
"""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from .services import FaqAdminValidationError, add_new_faq, find_similar_faqs, get_faq_answer, update_existing_faq


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
        return JsonResponse({"matches": find_similar_faqs(body.get("question"), body.get("program_id"))})
    except (json.JSONDecodeError, FaqAdminValidationError):
        return JsonResponse({"error": "Enter a question first."}, status=400)
    except Exception:
        return JsonResponse({"error": "Could not check similar FAQs. Try again."}, status=502)


@require_GET
def answer(request, faq_id):
    """Return one selected FAQ answer for the collapsed review card."""
    try:
        return JsonResponse(get_faq_answer(faq_id))
    except FaqAdminValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=404)
    except Exception:
        return JsonResponse({"error": "Could not load the FAQ answer. Try again."}, status=502)


@require_POST
@csrf_protect
def add(request):
    """Add a reviewed FAQ to Postgres and return its new row ids."""
    try:
        return JsonResponse({"saved_ids": add_new_faq(json.loads(request.body))})
    except (json.JSONDecodeError, FaqAdminValidationError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "Could not save the FAQ. Try again."}, status=502)


@require_POST
@csrf_protect
def update(request):
    """Update the server-identified FAQ row or different-answer group."""
    try:
        return JsonResponse(update_existing_faq(json.loads(request.body)))
    except (json.JSONDecodeError, FaqAdminValidationError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "Could not update the FAQ. Try again."}, status=502)
