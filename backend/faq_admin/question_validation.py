"""Question text rules for the FAQ-admin similarity check.

Flow: an admin drafts a question -> ``validate_question`` returns a
human-readable problem or ``None`` -> ``check_similar`` rejects the draft before
Ollama embeds it or Postgres is queried.

The browser mirrors these rules in ``static/faq-admin.js`` so the Check and Add
buttons stay disabled while the draft is invalid. The server stays
authoritative: the endpoint can be called directly, so the same check runs here.
"""
import re

MIN_WORDS = 5
MAX_WORDS = 30

# Printable ASCII only: letters, digits, spaces and ordinary punctuation. One
# rule rejects emoji, Unicode symbols, accented characters, every non-Latin
# script and right-to-left text, without maintaining a Unicode category table.
_ALLOWED_TEXT = re.compile(r"^[\x20-\x7E]+$")


def _collapse_whitespace(value):
    """Return one single-spaced copy of a drafted question."""
    return " ".join(value.split())


def word_count(value):
    """Return how many words a drafted question contains.

    Example: ``word_count("  How do I pay fees? ")`` returns 5.
    """
    return len(_collapse_whitespace(value).split())


def validate_question(value):
    """Return a human-readable problem with one drafted question, or ``None``.

    Example: ``validate_question("\u2705")`` returns the unsupported-characters
    message, while ``validate_question("How do I pay the fees for this term?")``
    returns ``None`` because it is plain ASCII and inside the word limits.
    """
    if not isinstance(value, str) or not value.strip():
        return "Enter a question first."

    text = _collapse_whitespace(value)
    if not _ALLOWED_TEXT.match(text):
        return (
            "Use plain English text only. Emoji, symbols, accented letters and "
            "non-Latin or right-to-left text are not supported."
        )

    count = len(text.split())
    if count < MIN_WORDS:
        return f"The question is too short. Use at least {MIN_WORDS} words."
    if count > MAX_WORDS:
        return f"The question is too long. Keep it to {MAX_WORDS} words or fewer."
    return None
