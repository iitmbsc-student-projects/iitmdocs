"""Request pipeline — port of worker.js answer() + handleDirectFAQIdLookup.

Flow: prepare the conversation log -> process and yield SSE records -> finalize
the log after completion, failure, or client disconnect. The finalization path
ensures the BigQuery sink receives exactly one ``conversation_turn`` event for
every generator that starts processing.
"""
from __future__ import annotations

import asyncio
import re
import time

from ..business import (
    extract_language,
    format_db_faq_suggestions,
    generate_uuid,
    get_cannot_answer_message,
)
from . import faq
from .answer import generate_answer_async
from .logs import duration_context, measure_duration, log_duration, log_error, structured_log
from .rewrite import rewrite_query_with_source_async
from .sse import sse_content, sse_document_records, sse_error
from .weaviate import search_weaviate_async

_LANG_TAG_RE = re.compile(r"\[LANG:\w+\]", re.IGNORECASE)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def search_context_issues(document_result, faq_result):
    """Describe empty or failed retrieval sources before answer generation.

    Example: a successful FAQ result plus no documents returns
    ``["weaviate_documents_empty"]``.
    """
    documents = (document_result or {}).get("items") or []
    db_faqs = (faq_result or {}).get("items") or []
    reasons = []

    if (document_result or {}).get("error"):
        reasons.append(document_result["error"])
    elif not documents:
        reasons.append("weaviate_documents_empty")

    if (faq_result or {}).get("error"):
        reasons.append(faq_result["error"])
    elif not db_faqs:
        reasons.append("pg_faqs_empty")

    return reasons

async def retrieve_context_async(query, num_docs, document_search, faq_search):
    """Run the two independent retrieval operations without request threads.

    ``document_search`` and ``faq_search`` are async callables. Passing them in
    keeps this small concurrency helper independent from the service modules.

    Example: two searches for ``"fees"`` start together and return their
    document and FAQ results in that order.
    """
    with measure_duration("retrieval_total"):
        return await asyncio.gather(
            document_search(query, num_docs),
            faq_search(query, 5),
        )

async def answer_events_async(service_client, openai_client, question, num_docs, history, session_id, message_id, username, program_id):
    """Run the complete answer flow for one programme, with cancellable async waits."""
    start_time = time.monotonic()
    conversation_id = generate_uuid()
    log_ctx = {
        "session_id": session_id or "anonymous",
        "conversation_id": conversation_id,
        # Logged so BigQuery/Looker can separate the four bots.
        "program_id": program_id,
        "message_id": message_id or None,
        "username": username or None,
        "question": question,
        "rewritten_query": None,
        "query_source": "original",
        "rejection_reason": None,
        "documents": [],
        "db_faqs": [],
        "response": None,
        "fact_check_passed": None,
        "fact_checks": [],
        "contains_raahat": False,
        "history_length": len(history) if isinstance(history, list) else 0,
        "latency_ms": None,
        "error": None,
        "stream_status": "processing",
        "original_answer": None,
        "tokens": {
            "query_rewrite_input": 0,
            "query_rewrite_output": 0,
            "answer_generation_input": 0,
            "answer_generation_output": 0,
            "fact_check_input": 0,
            "fact_check_output": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        },
    }
    log_severity = "INFO"

    try:
        with duration_context(conversation_id):
            rewrite = await rewrite_query_with_source_async(openai_client, question, program_id)
        search_query = rewrite["query"]
        query_source = rewrite["source"]
        log_ctx["rewritten_query"] = search_query
        log_ctx["query_source"] = query_source
        rewrite_tokens = rewrite.get("tokens") or {}
        log_ctx["tokens"]["query_rewrite_input"] = rewrite_tokens.get("input", 0)
        log_ctx["tokens"]["query_rewrite_output"] = rewrite_tokens.get("output", 0)

        if query_source == "rejected":
            log_ctx["rejection_reason"] = "prompt_injection"
            log_ctx["detected_language"] = "english"
            log_ctx["fact_check_passed"] = False
            reject_message = get_cannot_answer_message("english", program_id=program_id)
            with duration_context(conversation_id):
                faq_result = await faq.search_result_async(service_client, question, 5, program_id)
            db_faqs = faq_result.get("items") or []
            log_ctx["db_faqs"] = [
                {
                    "id": item.get("id"),
                    "cosine_similarity": item.get("cosine_similarity"),
                    "question": item.get("question"),
                    "answer": item.get("answer"),
                }
                for item in db_faqs
            ]
            reject_message += format_db_faq_suggestions(db_faqs, "english")
            log_ctx["response"] = reject_message
            yield sse_content(reject_message, rejected=True)
            log_ctx["stream_status"] = "completed"
            return

        detected_language = extract_language(search_query)
        clean_query = _LANG_TAG_RE.sub("", search_query).strip()
        log_ctx["detected_language"] = detected_language

        async def document_search(query, count):
            return await search_weaviate_async(service_client, query, count, program_id)

        async def faq_search(query, count):
            return await faq.search_result_async(service_client, query, count, program_id)

        with duration_context(conversation_id):
            document_result, faq_result = await retrieve_context_async(
                clean_query,
                num_docs,
                document_search,
                faq_search,
            )
        documents = document_result.get("items") or []
        db_faqs = faq_result.get("items") or []
        log_ctx["documents"] = [
            {"filename": item.get("filename"), "relevance": item.get("relevance")}
            for item in documents
        ]
        log_ctx["db_faqs"] = [
            {
                "id": item.get("id"),
                "cosine_similarity": item.get("cosine_similarity"),
                "question": item.get("question"),
                "answer": item.get("answer"),
            }
            for item in db_faqs
        ]

        search_issues = search_context_issues(document_result, faq_result)
        if search_issues:
            log_ctx["search_result_causes"] = search_issues
            log_ctx["error"] = "; ".join(search_issues)
            log_severity = "CRITICAL"

        if not documents and not db_faqs:
            message = get_cannot_answer_message(detected_language, program_id=program_id)
            log_ctx["rejection_reason"] = "no_search_results"
            log_ctx["response"] = message
            log_ctx["error"] = "; ".join(search_issues) or "no_search_results"
            yield sse_content(message, rejected=True)
            log_ctx["stream_status"] = "completed"
            log_duration("total_query", _elapsed_ms(start_time))
            return

        if documents:
            yield sse_document_records(documents)

        with duration_context(conversation_id):
            generated = await generate_answer_async(
                openai_client,
                question,
                documents,
                db_faqs,
                history,
                detected_language,
                program_id,
            )
        log_ctx["response"] = generated["final_answer"]
        log_ctx["fact_check_passed"] = generated["fact_check_passed"]
        log_ctx["fact_checks"] = generated.get("fact_checks") or []
        log_ctx["contains_raahat"] = generated["contains_raahat"]
        log_ctx["original_answer"] = generated.get("original_answer")
        generated_tokens = generated.get("tokens") or {}
        for key in (
            "answer_generation_input",
            "answer_generation_output",
            "fact_check_input",
            "fact_check_output",
        ):
            log_ctx["tokens"][key] = generated_tokens.get(key, 0)
        log_ctx["tokens"]["total_input_tokens"] = (
            log_ctx["tokens"]["query_rewrite_input"]
            + log_ctx["tokens"]["answer_generation_input"]
            + log_ctx["tokens"]["fact_check_input"]
        )
        log_ctx["tokens"]["total_output_tokens"] = (
            log_ctx["tokens"]["query_rewrite_output"]
            + log_ctx["tokens"]["answer_generation_output"]
            + log_ctx["tokens"]["fact_check_output"]
        )
        if generated["rejection_reason"] is not None:
            log_ctx["rejection_reason"] = generated["rejection_reason"]

        yield sse_content(generated["final_answer"], rejected=generated["rejected"])
        log_ctx["stream_status"] = "completed"
        log_duration("total_query", _elapsed_ms(start_time))

    except asyncio.CancelledError:
        log_ctx["stream_status"] = "disconnected"
        log_ctx["error"] = "client_disconnected"
        raise
    except Exception as error:  # noqa: BLE001
        log_ctx["error"] = str(error)
        log_severity = "INFO"
        log_error(
            "conversation_error",
            error,
            session_id=session_id,
            conversation_id=conversation_id,
            question=question,
        )
        yield sse_error(str(error) or "An error occurred while processing your request")
        log_ctx["stream_status"] = "failed"
    finally:
        if log_ctx["stream_status"] == "processing":
            log_ctx["stream_status"] = "disconnected"
            if log_ctx["error"]:
                log_ctx["error"] += "; client_disconnected"
            else:
                log_ctx["error"] = "client_disconnected"
        log_ctx["latency_ms"] = _elapsed_ms(start_time)
        structured_log(log_severity, "conversation_turn", **log_ctx)

async def direct_faq_events_async(faq_id, question, session_id, message_id, username, program_id):
    """Run the direct-FAQ shortcut with the existing SSE and log contract."""
    start_time = time.monotonic()
    conversation_id = generate_uuid()
    log_ctx = {
        "session_id": session_id or "anonymous",
        "conversation_id": conversation_id,
        "program_id": program_id,
        "message_id": message_id or None,
        "username": username or None,
        "question": question,
        "rewritten_query": None,
        "query_source": "faq_direct_id",
        "rejection_reason": None,
        "documents": [{"id": str(faq_id), "relevance": "1"}],
        "response": None,
        "fact_check_passed": True,
        "contains_raahat": False,
        "history_length": 0,
        "latency_ms": None,
        "error": None,
        "detected_language": "english",
    }
    cannot_answer = get_cannot_answer_message("english", program_id=program_id)
    try:
        with duration_context(conversation_id), measure_duration("pg_faq_direct_lookup"):
            row = await faq.get_faq_async(faq_id, program_id)
        if row is None:
            log_ctx["error"] = "PG FAQ lookup failed: 404"
            log_ctx["response"] = cannot_answer
            log_ctx["latency_ms"] = _elapsed_ms(start_time)
            structured_log("INFO", "conversation_turn", **log_ctx)
            yield sse_content(cannot_answer, rejected=True)
            return

        formatted = f"### {row['question']}\n\n{row['answer']}"
        log_ctx["response"] = formatted
        log_ctx["latency_ms"] = _elapsed_ms(start_time)
        structured_log("INFO", "conversation_turn", **log_ctx)
        yield sse_content(formatted)
    except asyncio.CancelledError:
        log_ctx["error"] = "client_disconnected"
        log_ctx["latency_ms"] = _elapsed_ms(start_time)
        structured_log("INFO", "conversation_turn", **log_ctx)
        raise
    except Exception as error:  # noqa: BLE001
        log_ctx["error"] = str(error)
        log_ctx["response"] = cannot_answer
        log_ctx["latency_ms"] = _elapsed_ms(start_time)
        structured_log("ERROR", "conversation_turn", **log_ctx)
        yield sse_content(cannot_answer, rejected=True)
