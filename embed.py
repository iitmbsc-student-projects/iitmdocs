#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "weaviate-client>=4.4.0",
#     "python-dotenv>=1.0.0",
#     "psycopg[binary]>=3.1.0",
#     "SQLAlchemy>=2.0.0",
#     "pgvector>=0.3.0",
# ]
# ///

# TODO: The file is now too large. Consider splitting into multiple modules (e.g. `weaviate_utils.py`, `pg_bootstrap.py`) for better organization and maintainability. We can also just move the helper functions to seperate files and keep the main embedding logic in `embed.py` to keep it as the single entry point for the embedding process.
"""
Script to embed all files from src/ directory into Weaviate.
Supports local (Ollama) and gce (remote Ollama) modes via DEPLOYMENT_MODE env var.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import weaviate
from dotenv import load_dotenv
from sqlalchemy import inspect
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.init import AdditionalConfig, Timeout
from weaviate.classes.query import Filter

from programs import REAL_PROGRAM_IDS, validate_program_id
from pg.faq_api.orm import Base, Faq, create_pg_engine, create_session_factory, session_scope
from pg.faq_api.repository import (
    count_faqs,
    count_faqs_missing_embeddings,
    get_faqs_missing_embeddings,
    replace_seed_faqs,
    update_faq_embedding,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
OLLAMA_TIMEOUT_SECONDS = 60

# Source documents live in src/<program_id>/*.md, one folder per programme. The folder
# name is what tags each document, so a file directly in src/ is skipped.
SRC_DIRECTORY = "src"

# Seed files that must all be present under FAQ_SEED_PATH.
SHARED_SEED_FILES = ("common.json", "timeline_based.json")
DIFF_ANSWERS_SEED_FILE = "diff_answers.json"
PROGRAM_SEED_DIRECTORY = "program_specific"


def _collection_has_program_id(collection) -> bool:
    """Return True if an existing Document collection already has a program_id property.

    Used to spot a collection created before the four-programme change, which has to be
    recreated because document search filters on program_id.
    """
    properties = getattr(collection.config.get(), "properties", []) or []
    return any(getattr(prop, "name", None) == "program_id" for prop in properties)


def clear_collection(weaviate_client):
    """Delete the Document collection if it exists"""
    if weaviate_client.collections.exists("Document"):
        logger.warning("CLEAR_DB=true: Deleting existing Document collection...")
        weaviate_client.collections.delete("Document")
        logger.info("Document collection deleted. Will recreate with fresh embeddings.")
    else:
        logger.info("No existing Document collection to clear.")


def create_schema(weaviate_client, deployment_mode="local", embedding_model=None, ollama_endpoint=None):
    """Create or update the Document class schema in Weaviate"""
    # Configure vectorizer based on mode and provider
    logger.debug(f"DEPLOYMENT MODE: {deployment_mode}")
    if deployment_mode == "local":
        model = embedding_model or "bge-m3"
        logger.warning(f"EMBEDDING_MODEL: {embedding_model}")
        vectorizer_config = Configure.Vectorizer.text2vec_ollama(
            model=model,
            api_endpoint="http://ollama:11434"
        )
        expected_vectorizer = "text2vec-ollama"
    elif deployment_mode == "gce":
        # GCE mode: connect to remote Ollama on GCE VM
        model = embedding_model or "bge-m3"
        ollama_url = ollama_endpoint or os.getenv("GCE_OLLAMA_URL", "http://localhost:11434")
        vectorizer_config = Configure.Vectorizer.text2vec_ollama(
            model=model,
            api_endpoint=ollama_url
        )
        expected_vectorizer = "text2vec-ollama"
    else:
        raise ValueError(
            f"Unsupported DEPLOYMENT_MODE='{deployment_mode}'. Supported values: local, gce."
        )

    # Check if collection exists and validate vectorizer configuration
    if weaviate_client.collections.exists("Document"):
        try:
            collection = weaviate_client.collections.get("Document")
            existing_vectorizer = collection.config.get().vectorizer.value if hasattr(collection.config.get().vectorizer, 'value') else str(collection.config.get().vectorizer)

            # Only delete if vectorizer has changed
            if existing_vectorizer != expected_vectorizer:
                logger.warning(
                    f"Vectorizer mismatch! Existing: {existing_vectorizer}, Expected: {expected_vectorizer}. "
                    f"Deleting and recreating collection with {deployment_mode} embeddings. "
                    f"ALL EXISTING EMBEDDINGS WILL BE LOST."
                )
                weaviate_client.collections.delete("Document")
            elif not _collection_has_program_id(collection):
                # A collection created before the four-programme change has no
                # program_id, so document search could not be filtered by programme.
                logger.warning(
                    "Existing Document collection has no program_id property. "
                    "Deleting and recreating it for multi-programme support. "
                    "ALL EXISTING EMBEDDINGS WILL BE LOST."
                )
                weaviate_client.collections.delete("Document")
            else:
                logger.info(f"Collection exists with correct vectorizer ({expected_vectorizer}). Reusing existing collection.")
                return collection
        except Exception as e:
            logger.warning(f"Could not validate existing collection config: {e}. Recreating collection.")
            weaviate_client.collections.delete("Document")

    properties = [
        Property(name="program_id", data_type=DataType.TEXT, description="Programme this document belongs to"),
        Property(name="filename", data_type=DataType.TEXT, description="Name of the source file"),
        Property(name="filepath", data_type=DataType.TEXT, description="Full path to the source"),
        Property(name="content", data_type=DataType.TEXT, description="Content of the document"),
        Property(name="file_size", data_type=DataType.INT, description="File size in bytes"),
        Property(name="content_hash", data_type=DataType.TEXT, description="SHA256 of the content"),
        Property(name="file_extension", data_type=DataType.TEXT, description="File extension"),
    ]

    logger.info(f"Creating new Document collection with {deployment_mode} mode, {expected_vectorizer} (model: {model})")
    return weaviate_client.collections.create(
        name="Document",
        vectorizer_config=vectorizer_config,
        properties=properties,
    )


# Files to exclude from embedding (used for internal purposes, not for search)
EXCLUDED_FILES = [
    "_knowledge_base_summary.md",  # Query rewriting context - not for vector search
]


def _is_true(value: str | None) -> bool:
    """Return True if the string represents a truthy value (env-var friendly)."""
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _log_pg_env_summary() -> None:
    # Log presence only (never values for secrets).
    keys = ["PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGSSLMODE"]
    summary = {k: ("set" if os.getenv(k) else "unset") for k in keys}
    logger.info(f"[pg-bootstrap] PG env summary: {summary}")


def _create_pg_bootstrap_engine():
    """Create a SQLAlchemy engine after validating bootstrap Postgres env vars."""

    host = os.getenv("PGHOST")
    port = int(os.getenv("PGPORT", "5432"))
    db = os.getenv("PGDATABASE")
    user = os.getenv("PGUSER")
    password = os.getenv("PGPASSWORD")
    sslmode = os.getenv("PGSSLMODE")
    connect_timeout = int(os.getenv("PGCONNECT_TIMEOUT", "10"))

    missing = [k for k, v in [("PGHOST", host), ("PGDATABASE", db), ("PGUSER", user), ("PGPASSWORD", password)] if not v]
    if missing:
        _log_pg_env_summary()
        raise ValueError(f"Missing required Postgres env vars: {', '.join(missing)}")

    logger.info(f"[pg-bootstrap] Connecting to Postgres: host={host} port={port} db={db} user={user} sslmode={sslmode or '<default>'} timeout={connect_timeout}s")

    # DNS resolution logging is extremely helpful for debugging Cloud SQL private IP / VPC issues.
    try:
        addrs = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        uniq = sorted({a[4][0] for a in addrs})
        logger.info(f"[pg-bootstrap] PGHOST resolved to: {uniq}")
    except Exception as exc:
        logger.warning(f"[pg-bootstrap] Could not resolve PGHOST={host}: {exc}")

    try:
        engine = create_pg_engine()
    except Exception:
        logger.exception("[pg-bootstrap] Failed to create SQLAlchemy engine.")
        raise

    # Emit a lightweight "we are really connected" banner without leaking anything sensitive.
    try:
        with engine.connect() as conn:
            conn.close()
        logger.info(f"[pg-bootstrap] Connected. current_database={db!r} current_user={user!r}")
    except Exception as exc:
        logger.warning(f"[pg-bootstrap] Engine created but connection check failed: {exc}")

    return engine


def _ensure_faq_schema(engine) -> None:
    """Create the `faqs` table from the Faq model, recreating it if it predates program_id.

    The model in pg/faq_api/orm.py is the only definition of the table, so this is what
    creates it - there is no hand-written CREATE TABLE anywhere.

    A database seeded before the four-programme change has a `faqs` table with no
    `program_id` column. SQLAlchemy has no ALTER TABLE, and create_all() would leave the
    old table in place and then fail on insert. So we detect that case and stop, unless
    the operator opts in to dropping it.

    ASSUMPTION: pg/seed IS THE SOURCE OF TRUTH FOR FAQ ROWS. The drop is only safe
    because every row is reloaded from pg/seed immediately afterwards, and the
    embeddings are regenerated by the backfill in the same run.
    """
    inspector = inspect(engine)
    if inspector.has_table(Faq.__tablename__):
        columns = {column["name"] for column in inspector.get_columns(Faq.__tablename__)}
        if "program_id" not in columns:
            if not _is_true(os.getenv("FAQ_ALLOW_DESTRUCTIVE_MIGRATION")):
                raise RuntimeError(
                    "The faqs table predates program_id and cannot be used as-is. "
                    "Set FAQ_ALLOW_DESTRUCTIVE_MIGRATION=true to drop and recreate it "
                    "from pg/seed, or add the column manually first."
                )
            logger.warning(
                "[pg-bootstrap] Dropping legacy faqs table (no program_id) and recreating it."
            )
            Faq.__table__.drop(engine)

    Base.metadata.create_all(engine, tables=[Faq.__table__])
    logger.info("[pg-bootstrap] FAQ schema ready (created from the Faq model).")

def _clean_seed_text(value, field_name: str, file_path: str, row_index: int) -> str:
    """Return a stripped seed field, or raise ValueError naming exactly what is wrong.

    Example: _clean_seed_text("  Fees?  ", "Question", "pg/seed/common.json", 3)
    returns "Fees?".
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{file_path} row {row_index}: missing or empty {field_name}")
    return value.strip()


def _append_seed_row(rows: list[dict], program_id: str, question: str, answer: str) -> None:
    """Add one validated FAQ row to the list being built for the database."""
    rows.append(
        {
            "program_id": validate_program_id(program_id, allow_common=True),
            "question": question,
            "answer": answer,
        }
    )


def _load_question_answer_seed_file(file_path: Path, program_id: str) -> list[dict]:
    """Load one seed file of [{"Question": ..., "Answer": ...}] rows for one programme.

    The capitalised keys are intentional - they match the spreadsheets the FAQs are
    exported from, and a lowercase key is treated as a mistake rather than accepted
    silently.

    A row where BOTH fields are blank is a spreadsheet gap: it is skipped with a
    warning. A row where only one field is blank is a real mistake and raises.
    """
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{file_path}: seed file must be a JSON array")

    rows: list[dict] = []
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(f"{file_path} row {index}: must be an object")

        question = row.get("Question")
        answer = row.get("Answer")
        blank_question = not isinstance(question, str) or not question.strip()
        blank_answer = not isinstance(answer, str) or not answer.strip()
        if blank_question and blank_answer:
            logger.warning(f"Skipping blank FAQ seed row {index} in {file_path}")
            continue

        _append_seed_row(
            rows,
            program_id,
            _clean_seed_text(question, "Question", str(file_path), index),
            _clean_seed_text(answer, "Answer", str(file_path), index),
        )
    return rows


def _load_diff_answers_seed_file(file_path: Path) -> list[dict]:
    """Load the file of questions that have a different answer in each programme.

    Shape is [{"question": ..., "answers": {"ds": ..., "es": ..., "mg": ..., "ae": ...}}]
    with lowercase keys, and it expands to one database row per programme. Every
    programme must have an answer, otherwise that bot would silently lose the question.
    """
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{file_path}: seed file must be a JSON array")

    rows: list[dict] = []
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(f"{file_path} row {index}: must be an object")

        question = _clean_seed_text(row.get("question"), "question", str(file_path), index)
        answers = row.get("answers")
        if not isinstance(answers, dict):
            raise ValueError(f"{file_path} row {index}: missing 'answers' object")

        for program_id in REAL_PROGRAM_IDS:
            answer = _clean_seed_text(
                answers.get(program_id), f"answers.{program_id}", str(file_path), index
            )
            _append_seed_row(rows, program_id, question, answer)
    return rows


def _required_seed_files(seed_directory: Path) -> list[Path]:
    """Return every seed file that must exist, in the order they are loaded."""
    files = [seed_directory / name for name in SHARED_SEED_FILES]
    files.append(seed_directory / DIFF_ANSWERS_SEED_FILE)
    files.extend(
        seed_directory / PROGRAM_SEED_DIRECTORY / f"{program_id}.json"
        for program_id in REAL_PROGRAM_IDS
    )
    return files


def _load_seed_faqs(path: str) -> list[dict]:
    """Load every FAQ seed file under `path` into rows ready for the database.

    `path` is the seed DIRECTORY (FAQ_SEED_PATH, normally "pg/seed"), not a single file.
    Expected layout:

        pg/seed/common.json                  -> program_id "common"
        pg/seed/timeline_based.json          -> program_id "common"
        pg/seed/diff_answers.json            -> one row per real programme
        pg/seed/program_specific/<id>.json   -> program_id "<id>"

    Example return value:
        [{"program_id": "common", "question": "What are the fees?", "answer": "..."}, ...]

    The same question may appear under different programmes with different answers.
    It may not appear twice under the SAME programme - that would break the
    (program_id, question) unique constraint on the faqs table, so it fails here first
    with a message naming both rows.
    """
    seed_directory = Path(path)
    if not seed_directory.is_dir():
        raise ValueError(
            f"FAQ_SEED_PATH must be a directory containing the seed files, got: {path}"
        )

    missing = [str(f) for f in _required_seed_files(seed_directory) if not f.is_file()]
    if missing:
        raise ValueError("Missing required FAQ seed files: " + ", ".join(missing))

    rows: list[dict] = []
    for name in SHARED_SEED_FILES:
        rows.extend(_load_question_answer_seed_file(seed_directory / name, "common"))
    rows.extend(_load_diff_answers_seed_file(seed_directory / DIFF_ANSWERS_SEED_FILE))
    for program_id in REAL_PROGRAM_IDS:
        rows.extend(
            _load_question_answer_seed_file(
                seed_directory / PROGRAM_SEED_DIRECTORY / f"{program_id}.json", program_id
            )
        )

    seen: dict[tuple[str, str], int] = {}
    duplicates: list[str] = []
    for index, row in enumerate(rows):
        key = (row["program_id"], " ".join(row["question"].lower().split()))
        if key in seen:
            duplicates.append(f"{row['program_id']} rows {seen[key]} and {index}: {row['question']}")
        else:
            seen[key] = index

    if duplicates:
        preview = "; ".join(duplicates[:10])
        suffix = "" if len(duplicates) <= 10 else f"; ... and {len(duplicates) - 10} more"
        raise ValueError(
            "Duplicate FAQ questions within the same programme. "
            f"Duplicates: {preview}{suffix}"
        )

    return rows

def _request_ollama_embedding(text: str, ollama_url: str, model: str) -> list[float]:
    """
    Request a single embedding vector from Ollama for the given text.

    Calls `POST {ollama_url}/api/embeddings` with JSON payload:
    `{"model": <model>, "prompt": <text>}` and returns the `embedding` list.
    """
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # Bound upstream waits so the embed job fails clearly if Ollama stalls.
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {err}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach Ollama at {ollama_url}: {exc}") from exc

    parsed = json.loads(body)
    embedding = parsed.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError("Ollama returned invalid embedding payload")
    return [float(v) for v in embedding]


def _pg_backfill_faq_embeddings(
    session_factory,
    *,
    ollama_url: str,
    model: str,
    dimension: int,
    batch_size: int,
) -> int:
    """
    Backfill missing FAQ embeddings in Postgres in small batches.

    This function looks for rows in the `faqs` table where `embedding` is NULL,
    requests an embedding vector for each row's `question` from Ollama, and then
    writes the vector back to Postgres (as a `vector` column, via pgvector).

    It repeats until no rows remain with NULL embeddings.

    Parameters
    ----------
    session_factory:
        SQLAlchemy session factory connected to the target Postgres database.
    ollama_url:
        Base URL of the Ollama server (e.g. `http://ollama:11434`).
    model:
        Ollama embedding model name (e.g. `bge-m3`).
    dimension:
        Expected embedding vector length. If Ollama returns a different length,
        the function fails fast to avoid mixing incompatible vector sizes.
    batch_size:
        Maximum number of FAQ rows to embed per iteration.

    Returns
    -------
    int
        Total number of FAQ rows updated with embeddings.
    """
    # TODO: In the replace-all seed flow, every freshly inserted FAQ starts with embedding=NULL; simplify this later by having replace_seed_faqs(...) return inserted FAQ rows and embedding those directly instead of querying for NULL embeddings after every full reload. After making this change, do the relevant modifications under teaching 4 section of the branch file `docs/branch-specific-info/use-orm-inplace-of-raw-sql.md`
    updated = 0
    batch_num = 0
    while True:
        with session_scope(session_factory) as session:
            rows = get_faqs_missing_embeddings(session, batch_size)

        if not rows:
            break

        batch_num += 1
        embedded_rows: list[tuple[int, list[float]]] = []
        for row in rows:
            # Ask Ollama for the embedding for this FAQ's question text.
            emb = _request_ollama_embedding(row.question, ollama_url, model)
            # pgvector columns require consistent dimensions across all rows.
            if len(emb) != dimension:
                raise RuntimeError(
                    f"Embedding dimension mismatch for id={row.id}: expected {dimension}, got {len(emb)}"
                )
            embedded_rows.append((row.id, emb))

        with session_scope(session_factory) as session:
            for faq_id, emb in embedded_rows:
                update_faq_embedding(session, faq_id, emb)

        updated += len(embedded_rows)
        logger.info(f"[pg-bootstrap] Backfill batch {batch_num}: embedded {len(embedded_rows)} rows (total updated: {updated})")
    return updated


def maybe_bootstrap_cloudsql_faq_db(deployment_mode: str) -> None:
    """
    Optional Cloud SQL bootstrap for Postgres-backed FAQ search.

    This is opt-in so local and GCE mode keep behaving the same unless explicitly enabled.
    """

    if not _is_true(os.getenv("ENABLE_PG_FAQ_BOOTSTRAP")):
        logger.info("PG FAQ bootstrap disabled (ENABLE_PG_FAQ_BOOTSTRAP not set to true).")
        return

    seed_path = os.getenv("FAQ_SEED_PATH", "pg/seed")

    model = os.getenv("OLLAMA_MODEL", "bge-m3")
    dimension = int(os.getenv("FAQ_EMBEDDING_DIMENSION", os.getenv("EMBEDDING_DIMENSION", "1024")))
    batch_size = int(os.getenv("FAQ_EMBEDDING_BATCH_SIZE", "50"))

    if deployment_mode == "gce":
        ollama_url = os.getenv("OLLAMA_URL") or os.getenv("GCE_OLLAMA_URL")
    else:
        ollama_url = os.getenv("OLLAMA_URL") or "http://ollama:11434"

    if not ollama_url:
        raise ValueError("Ollama URL missing: set OLLAMA_URL (or GCE_OLLAMA_URL for DEPLOYMENT_MODE=gce)")

    logger.info("[pg-bootstrap] Starting Cloud SQL FAQ bootstrap...")
    logger.info(f"[pg-bootstrap] Seed: {seed_path}")
    logger.info(f"[pg-bootstrap] Embedding: model={model}, dim={dimension}, batch={batch_size}, ollama_url={ollama_url}")

    t_all = time.monotonic()

    # Step 1: load seed.
    try:
        t0 = time.monotonic()
        rows = _load_seed_faqs(seed_path)
        logger.info(f"[pg-bootstrap] Loaded seed FAQs: rows={len(rows)} (elapsed_ms={int((time.monotonic() - t0) * 1000)})")
    except Exception:
        logger.exception(f"[pg-bootstrap] Failed to load seed file: {seed_path}")
        raise

    # Step 2: quick Ollama health check before touching the DB.
    try:
        t0 = time.monotonic()
        req = urllib.request.Request(f"{ollama_url.rstrip('/')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            _ = resp.read(256)
        logger.info(f"[pg-bootstrap] Ollama reachable at {ollama_url} (elapsed_ms={int((time.monotonic() - t0) * 1000)})")
    except Exception:
        logger.exception(f"[pg-bootstrap] Ollama is not reachable at {ollama_url}. Aborting PG bootstrap.")
        raise

    # Step 3: connect + migrate + replace seed rows + backfill.
    engine = _create_pg_bootstrap_engine()
    try:
        _ensure_faq_schema(engine)

        session_factory = create_session_factory(engine)

        try:
            with session_scope(session_factory) as session:
                before_total = count_faqs(session)
                before_null = count_faqs_missing_embeddings(session)
            logger.info(f"[pg-bootstrap] DB state before replace/backfill: faqs_total={before_total} faqs_embedding_null={before_null}")
        except Exception as exc:
            logger.warning(f"[pg-bootstrap] Could not read pre-replace counts: {exc}")

        with session_scope(session_factory) as session:
            inserted = replace_seed_faqs(session, rows)
        per_program = Counter(row["program_id"] for row in rows)
        counts = ", ".join(f"{pid}={per_program[pid]}" for pid in sorted(per_program))
        logger.info(f"[pg-bootstrap] Replaced FAQ table with {inserted} seed rows ({counts}).")

        try:
            with session_scope(session_factory) as session:
                after_total = count_faqs(session)
                after_null = count_faqs_missing_embeddings(session)
            logger.info(f"[pg-bootstrap] DB state after replace (before backfill): faqs_total={after_total} faqs_embedding_null={after_null}")
        except Exception as exc:
            logger.warning(f"[pg-bootstrap] Could not read post-replace counts: {exc}")

        backfilled = _pg_backfill_faq_embeddings(
            session_factory,
            ollama_url=ollama_url,
            model=model,
            dimension=dimension,
            batch_size=batch_size,
        )
        logger.info(f"[pg-bootstrap] Backfill complete. Newly embedded rows: {backfilled}.")

        try:
            with session_scope(session_factory) as session:
                final_null = count_faqs_missing_embeddings(session)
            logger.info(f"[pg-bootstrap] Final DB state: faqs_embedding_null={final_null}")
        except Exception as exc:
            logger.warning(f"[pg-bootstrap] Could not read final counts: {exc}")
    finally:
        engine.dispose()

    logger.info(f"[pg-bootstrap] Cloud SQL FAQ bootstrap finished OK (elapsed_ms={int((time.monotonic() - t_all) * 1000)})")


def _program_id_for_document(file_path: Path, src_path: Path):
    """Return the programme a source file belongs to, or None if it is not in one.

    The programme is the first folder under src/, so src/es/fees.md belongs to "es".
    A file directly in src/, or in a folder that is not a known programme, returns None
    and is skipped rather than being embedded without a programme.
    """
    relative_path = file_path.relative_to(src_path)
    if len(relative_path.parts) < 2:
        return None
    try:
        return validate_program_id(relative_path.parts[0])
    except ValueError:
        return None


def embed_documents(weaviate_client, src_directory: str, deployment_mode="local", embedding_model=None, ollama_endpoint=None) -> bool:
    """Embed all documents from src/<program_id>/ into Weaviate, tagged by programme."""
    collection = create_schema(weaviate_client, deployment_mode, embedding_model, ollama_endpoint)
    src_path = Path(src_directory)

    # Exclude internal files that shouldn't be in vector search
    files = [f for f in src_path.glob("**/*.md") if f.is_file() and f.name not in EXCLUDED_FILES]
    total_files = len(files)
    logger.info(f"Processing {total_files} files from {src_path.absolute()}")

    successful_embeds = 0
    skipped = 0
    failed = 0

    for idx, file_path in enumerate(files, 1):
        program_id = _program_id_for_document(file_path, src_path)
        if program_id is None:
            logger.warning(
                f"[{idx}/{total_files}] Skipping {file_path}: expected src/<program_id>/<file>.md"
            )
            skipped += 1
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, IOError) as e:
            logger.warning(f"[{idx}/{total_files}] Skipping {file_path.name}: {e}")
            skipped += 1
            continue

        try:
            doc_data = {
                "program_id": program_id,
                "filename": file_path.name,
                # Posix form so the stored path also works as a GitHub link suffix.
                "filepath": file_path.as_posix(),
                "content": content,
                "file_size": file_path.stat().st_size,
                "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "file_extension": file_path.suffix,
            }

            existing = collection.query.fetch_objects(
                filters=Filter.by_property("filepath").equal(doc_data["filepath"]), limit=1
            )

            # Log character length for tracking (success path will log later)
            content_char_length = len(content)
            logger.info(f"[{idx}/{total_files}] Processing: {file_path.name} ({content_char_length} chars)")

            if existing.objects:
                existing_doc = existing.objects[0]
                if existing_doc.properties["content_hash"] == doc_data["content_hash"]:
                    logger.info(f"[{idx}/{total_files}] Unchanged: {file_path.name}")
                    skipped += 1
                    continue
                collection.data.update(uuid=existing_doc.uuid, properties=doc_data)
                logger.info(f"[{idx}/{total_files}] Updated: {file_path.name}")
            else:
                collection.data.insert(doc_data)
                logger.info(f"[{idx}/{total_files}] Embedded: {file_path.name}")

            successful_embeds += 1
        except Exception as e:
            # LOG FULL PAYLOAD ONLY WHEN EMBEDDING FAILS
            logger.error(f"[{idx}/{total_files}] EMBEDDING FAILED for {file_path.name}")
            logger.error(f"[{idx}/{total_files}] Failed payload had {len(content)} characters")
            # logger.error(f"[{idx}/{total_files}] FULL PAYLOAD TEXT START >>>")
            # logger.error(content)
            # logger.error(f"[{idx}/{total_files}] FULL PAYLOAD TEXT END <<<")
            logger.error(f"[{idx}/{total_files}] Error: {e}")
            failed += 1
            continue

    logger.info(f"Completed: {successful_embeds} embedded, {skipped} skipped, {failed} failed (total: {total_files})")
    return True


def main():
    """Main function to run the embedding process"""
    load_dotenv()

    # Clear existing embeddings before re-embedding (default: true)
    # Set CLEAR_DB=false to keep existing embeddings and only update changed files
    clear_db = os.getenv("CLEAR_DB", "true").lower() == "true"

    # Determine embedding mode: 'local' or 'gce'
    deployment_mode = os.getenv("DEPLOYMENT_MODE", "local").lower()
    logger.info(f"Deployment mode: {deployment_mode}")

    supported_modes = {"local", "gce"}
    if deployment_mode not in supported_modes:
        raise ValueError(
            f"Unsupported DEPLOYMENT_MODE='{deployment_mode}'. Supported values: local, gce."
        )

    # Optional: bootstrap managed Postgres FAQ DB during deploy (Cloud SQL).
    # Opt-in so local/GCE runs keep behaving the same unless explicitly enabled.
    maybe_bootstrap_cloudsql_faq_db(deployment_mode)

    if clear_db:
        logger.info("Will clear existing embeddings before re-embedding (set CLEAR_DB=false to disable)")
    else:
        logger.info("CLEAR_DB=false: Keeping existing embeddings, only updating changed files")

    if deployment_mode == "local":
        # Local mode: connect to local Weaviate (no auth needed)
        weaviate_url = os.getenv("LOCAL_WEAVIATE_URL", "http://weaviate:8080")
        embedding_model = os.getenv("OLLAMA_MODEL", "bge-m3")

        logger.info(f"Connecting to local Weaviate at {weaviate_url}")
        client = weaviate.connect_to_local(
            host=weaviate_url.replace("http://", "").split(":")[0],
            port=int(weaviate_url.split(":")[-1]) if ":" in weaviate_url.split("//")[-1] else 8080,
            additional_config=AdditionalConfig(timeout=Timeout(init=600, query=600, insert=600))
        )
        if clear_db:
            clear_collection(client)
        embed_documents(client, SRC_DIRECTORY, deployment_mode, embedding_model)
        client.close()
    elif deployment_mode == "gce":
        # GCE mode: connect to remote Weaviate on GCE VM (no auth needed)
        weaviate_url = os.getenv("GCE_WEAVIATE_URL")
        ollama_url = os.getenv("GCE_OLLAMA_URL")
        embedding_model = os.getenv("OLLAMA_MODEL", "bge-m3")

        if not weaviate_url:
            raise ValueError("GCE_WEAVIATE_URL is required for GCE mode")
        if not ollama_url:
            raise ValueError("GCE_OLLAMA_URL is required for GCE mode")

        logger.info(f"Connecting to GCE Weaviate at {weaviate_url}")
        logger.info(f"Using GCE Ollama at {ollama_url}")

        # Parse the URL to get host and port
        url_parts = weaviate_url.replace("http://", "").replace("https://", "")
        host = url_parts.split(":")[0]
        port = int(url_parts.split(":")[1]) if ":" in url_parts else 8080

        # Use connect_to_custom with skip_init_checks to use REST instead of gRPC
        client = weaviate.connect_to_custom(
            http_host=host,
            http_port=port,
            http_secure=False,
            grpc_host=host,
            grpc_port=50051,
            grpc_secure=False,
            skip_init_checks=True,
            additional_config=AdditionalConfig(timeout=Timeout(init=600, query=600, insert=600))
        )
        if clear_db:
            clear_collection(client)
        embed_documents(client, SRC_DIRECTORY, deployment_mode, embedding_model, ollama_url)
        client.close()


if __name__ == "__main__":
    main()
