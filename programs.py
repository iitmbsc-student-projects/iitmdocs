"""The four IIT Madras BS programmes this chatbot serves, and the rules for them.

FLOW
----
A browser opens `/qa?program_id=es`. `static/qa.js` puts that id in the body of every
`/answer` and `/feedback` request. Django validates it here, then uses it
twice:

    request program_id="es"
      -> weaviate.search_weaviate_async  filters documents to program_id == "es"
      -> faq.search_result_async         filters FAQs to program_id IN ("es", "common")

`embed.py` uses the same ids from the other direction: it reads `src/<program_id>/*.md`
and `pg/seed/`, and writes the id onto every document and FAQ row it stores.

This module is the ONLY place the programme list lives. It sits at the repo root so
both Django (which puts the repo root on sys.path) and `embed.py` (which runs outside
Django, in its own container) can import it without duplicating the list.

TERMS
-----
program id   One of "ds", "es", "mg", "ae". Chosen by the caller, never guessed from
             the user's question.
common       A fifth id used only for storage. FAQ rows tagged "common" are shown to
             every programme. It is NOT a real programme, so a request may never ask
             for it. There is no `src/common/` folder - sharing applies to FAQs only.
"""

REAL_PROGRAM_IDS = ("ds", "es", "mg", "ae")
COMMON_PROGRAM_ID = "common"
FAQ_PROGRAM_IDS = REAL_PROGRAM_IDS + (COMMON_PROGRAM_ID,)
DEFAULT_PROGRAM_ID = "ds"

# Name and support contacts shown to the user, per programme. These are injected into
# the answer prompt, the "I cannot answer that" messages, and the fact-checker's list
# of contact details the bot is allowed to state.
PROGRAM_CONFIG = {
    "ds": {
        "name": "IIT Madras BS in Data Science and Applications",
        "website": "https://study.iitm.ac.in/ds/",
        "support_email": "support@study.iitm.ac.in",
        "support_phone": "7850999966",
    },
    "es": {
        "name": "IIT Madras BS in Electronic Systems",
        "website": "https://study.iitm.ac.in/es/",
        "support_email": "support-es@study.iitm.ac.in",
        "support_phone": "+91-9711397993",
    },
    "mg": {
        "name": "IIT Madras BS in Management and Data Science",
        "website": "https://study.iitm.ac.in/mg/",
        "support_email": "support-mg@study.iitm.ac.in",
        "support_phone": "7850999966",
    },
    "ae": {
        "name": "IIT Madras BS in Aeronautics and Space Technology",
        "website": "https://study.iitm.ac.in/ae/",
        "support_email": "support-ae@study.iitm.ac.in",
        "support_phone": "+91-9711397993",
    },
}


def validate_program_id(program_id, allow_common=False):
    """Return a cleaned program id, or raise ValueError if it is not one of ours.

    Called on every request, before the id reaches Weaviate or Postgres.

    Example:
        validate_program_id(" ES ")                    -> "es"
        validate_program_id(None)                      -> "ds"   (the default)
        validate_program_id("common")                  -> raises ValueError
        validate_program_id("common", allow_common=True) -> "common"

    Pass allow_common=True only for storage code paths such as the FAQ seed loader.
    Request handlers must leave it False, because "common" is not a real programme.
    """
    normalized = str(program_id or DEFAULT_PROGRAM_ID).strip().lower()
    allowed = FAQ_PROGRAM_IDS if allow_common else REAL_PROGRAM_IDS
    if normalized not in allowed:
        raise ValueError(
            f"Invalid program_id {program_id!r}. Allowed values: {', '.join(allowed)}"
        )
    return normalized


def faq_program_scope(program_id):
    """Return the FAQ program ids a programme is allowed to read: itself plus common.

    Example:
        faq_program_scope("es") -> ["es", "common"]

    Used by both the request path (backend/chatbot/services/faq.py) and the seeding
    path (pg/faq_api/repository.py), so the sharing rule is written down once.
    """
    return [program_id, COMMON_PROGRAM_ID]


def program_config(program_id):
    """Return the name and support contacts for one programme.

    Example:
        program_config("es")["support_email"] -> "support-es@study.iitm.ac.in"

    Falls back to the default programme rather than raising, so a display-only caller
    can never break a request. Callers that need strictness should call
    validate_program_id first.
    """
    return PROGRAM_CONFIG.get(program_id, PROGRAM_CONFIG[DEFAULT_PROGRAM_ID])
