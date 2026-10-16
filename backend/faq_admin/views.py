"""Browser entry point for the internal FAQ-admin workflow.

Flow: an admin opens ``/faq-admin`` -> Django sends the page and CSRF cookie ->
the page checks similar questions and answer safety through same-origin routes ->
the page can call its server-validated save endpoint.

The separate ``/faq-admin/all-faqs`` page lists those stored rows inside one
collapsible section per question category.
"""
import json
from urllib.parse import urlencode

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from .safety import FaqAnswerSafetyError, check_answer_safety as review_answer_safety
from .unanswered_questions import (
    UnansweredQuestionError,
    list_accepted_unanswered_questions,
    refresh_unanswered_questions,
    reject_unanswered_question,
    save_temporary_ai_suggestion,
)
from .services import (
    FaqAdminValidationError,
    add_new_faq,
    build_answers_for_safety_check,
    find_similar_faqs,
    delete_faq_from_management,
    get_faq_answer,
    get_faq_for_management,
    list_all_faqs,
    update_faq_from_management,
    update_existing_faq,
)


FAQ_CATEGORY_LABELS = (
    ("common", "Common to all programmes"),
    ("timeline_based", "Timeline-based for all programmes"),
    ("program_specific", "Programme-specific"),
    ("diff_answers", "Same question, four different answers"),
)


def _faq_sections(faqs):
    """Put listed FAQ rows into their fixed category sections.

    Example: a row with ``question_category='common'`` appears in the Common
    section. Rows without a category remain visible in a final Uncategorised
    section, rather than disappearing from the admin page.
    """
    rows_by_category = {category: [] for category, _label in FAQ_CATEGORY_LABELS}
    uncategorised_rows = []
    for faq in faqs:
        category = faq["question_category"]
        if category in rows_by_category:
            rows_by_category[category].append(faq)
        else:
            uncategorised_rows.append(faq)

    sections = [
        {"category": category, "label": label, "faqs": rows_by_category[category]}
        for category, label in FAQ_CATEGORY_LABELS
    ]
    if uncategorised_rows:
        sections.append({"category": "uncategorised", "label": "Uncategorised", "faqs": uncategorised_rows})
    return sections


@ensure_csrf_cookie
def page(request):
    """Render the FAQ-admin form shell and issue its CSRF cookie.

    Example: ``GET /faq-admin`` returns the form before any database request.
    """
    return render(request, "faq_admin/page.html")


@require_GET
@ensure_csrf_cookie
def all_faqs(request):
    """Render every FAQ table row with separate edit and delete actions."""
    try:
        return render(request, "faq_admin/all_faqs.html", {"faq_sections": _faq_sections(list_all_faqs())})
    except Exception:
        return render(
            request,
            "faq_admin/all_faqs.html",
            {"faq_sections": [], "error": "Could not load FAQ rows. Try again."},
            status=502,
        )


def _unanswered_questions_redirect(**params):
    """Build a safe redirect back to the unanswered-question review page."""
    url = "/faq-admin/unanswered-questions"
    return redirect(f"{url}?{urlencode(params)}" if params else url)


@require_GET
@ensure_csrf_cookie
def unanswered_questions(request):
    """Render Test-log questions the admin has not rejected.

    Example: ``GET /faq-admin/unanswered-questions`` shows pending rows and a
    manual Refresh button. It never reads BigQuery until that button is used.
    """
    try:
        return render(
            request,
            "faq_admin/unanswered_questions.html",
            {
                "questions": list_accepted_unanswered_questions(),
                "notice": request.GET.get("notice"),
                "error": request.GET.get("error"),
            },
        )
    except Exception:
        return render(
            request,
            "faq_admin/unanswered_questions.html",
            {"questions": [], "error": "Could not load unanswered questions. Try again."},
            status=502,
        )


@require_POST
@csrf_protect
def refresh_unanswered_questions_page(request):
    """Run the explicit Test-log refresh, then return to the review list."""
    try:
        result = refresh_unanswered_questions()
        inserted = result["inserted_count"]
        noun = "question" if inserted == 1 else "questions"
        return _unanswered_questions_redirect(
            notice=f"Reviewed {result['log_count']} logs; added {inserted} new {noun}."
        )
    except Exception:
        return _unanswered_questions_redirect(
            error="Could not refresh Test logs. Try again."
        )


@require_POST
@csrf_protect
def reject_unanswered_question_page(request, question_id):
    """Hide a selected candidate after the admin confirms rejection in the browser."""
    try:
        reject_unanswered_question(question_id)
        return _unanswered_questions_redirect()
    except UnansweredQuestionError as exc:
        return _unanswered_questions_redirect(error=str(exc))
    except Exception:
        return _unanswered_questions_redirect(error="Could not reject this question. Try again.")


@require_POST
@csrf_protect
def temporary_ai_help_page(request, question_id):
    """Save the temporary random AI-help label for one accepted row."""
    try:
        save_temporary_ai_suggestion(question_id)
        return _unanswered_questions_redirect(notice="Temporary AI help saved.")
    except UnansweredQuestionError as exc:
        return _unanswered_questions_redirect(error=str(exc))
    except Exception:
        return _unanswered_questions_redirect(error="Could not get AI help. Try again.")


@require_http_methods(["GET", "POST"])
@csrf_protect
def edit_all_faq(request, faq_id):
    """Show and save one row from the separate all-FAQs management page."""
    if request.method == "POST":
        try:
            update_faq_from_management(faq_id, request.POST.get("question"), request.POST.get("answer"))
            return redirect("faq-admin-all-faqs")
        except FaqAdminValidationError as exc:
            faq = get_faq_for_management(faq_id)
            return render(request, "faq_admin/edit_faq.html", {"faq": faq, "error": str(exc)}, status=400)
        except Exception:
            faq = get_faq_for_management(faq_id)
            return render(request, "faq_admin/edit_faq.html", {"faq": faq, "error": "Could not update the FAQ. Try again."}, status=502)

    try:
        return render(request, "faq_admin/edit_faq.html", {"faq": get_faq_for_management(faq_id)})
    except FaqAdminValidationError as exc:
        raise Http404(str(exc)) from exc
    except Exception:
        return render(request, "faq_admin/edit_faq.html", {"error": "Could not load the FAQ. Try again."}, status=502)


@require_POST
@csrf_protect
def delete_all_faq(request, faq_id):
    """Delete one listed row after the browser confirmation prompt."""
    try:
        delete_faq_from_management(faq_id)
        return redirect("faq-admin-all-faqs")
    except FaqAdminValidationError as exc:
        raise Http404(str(exc)) from exc
    except Exception:
        return render(
            request,
            "faq_admin/all_faqs.html",
            {"faq_sections": [], "error": "Could not delete the FAQ. Try again."},
            status=502,
        )


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
async def check_answer_safety(request):
    """Review validated pending answers before the browser can enable Save."""
    try:
        pending_answers = build_answers_for_safety_check(json.loads(request.body))
        results = []
        for item in pending_answers:
            result = await review_answer_safety(item["answer"])
            results.append({"program_id": item["program_id"], **result})
        return JsonResponse({"results": results})
    except (json.JSONDecodeError, FaqAdminValidationError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except FaqAnswerSafetyError:
        return JsonResponse({"error": "Could not check answer safety. Try again."}, status=502)
    except Exception:
        return JsonResponse({"error": "Could not check answer safety. Try again."}, status=502)


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
