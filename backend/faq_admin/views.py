"""Browser entry point for the internal FAQ-admin workflow.

Flow: an admin opens ``/faq-admin`` -> Django sends the page and CSRF cookie ->
the page will later call its same-origin review and save endpoints.
"""
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def page(request):
    """Render the FAQ-admin form shell and issue its CSRF cookie.

    Example: ``GET /faq-admin`` returns the form before any database request.
    """
    return render(request, "faq_admin/page.html")
