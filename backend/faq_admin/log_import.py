"""Read recent Test conversation logs from BigQuery for FAQ-admin review.

Flow: the admin clicks Refresh -> this module reads only the last seven daily
Test export tables -> it returns plain log dictionaries ->
``unanswered_questions`` decides which ones are candidates. It never writes to
BigQuery and it never runs on the chatbot answer path.
"""
import datetime
import json


TEST_LOG_PROJECT = "temp-bq-project"
TEST_LOG_DATASET = "chatbot_logs"
TEST_LOG_TABLE_PREFIX = "run_googleapis_com_stdout_"


class TestLogImportError(RuntimeError):
    """Raised when the Test BigQuery log read cannot complete safely."""


def _daily_table_range(today):
    """Return inclusive suffixes for today and the preceding six calendar days."""
    start = today - datetime.timedelta(days=6)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def _payload_from_row(row):
    """Decode one selected BigQuery JSON payload, or ignore a malformed row."""
    try:
        payload = row["payload"]
    except (KeyError, TypeError):
        return None
    try:
        decoded = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None

    # This is the Cloud Logging event timestamp, not an application-provided
    # field in jsonPayload. It is retained only for the FAQ admin's date display.
    try:
        decoded["asked_at"] = row["asked_at"]
    except (KeyError, TypeError):
        decoded["asked_at"] = None
    return decoded


def read_last_seven_days_test_logs(client=None, today=None):
    """Return recent Test `conversation_turn` payloads as dictionaries.

    Example: passing 16 October 2026 reads tables from 10 October through 16
    October. ``client`` exists for deterministic tests; production obtains the
    normal Cloud Run service-account client only when the button is clicked.
    """
    if today is None:
        today = datetime.datetime.now(datetime.timezone.utc).date()
    start_suffix, end_suffix = _daily_table_range(today)
    table = f"{TEST_LOG_PROJECT}.{TEST_LOG_DATASET}.{TEST_LOG_TABLE_PREFIX}*"
    query = f"""
        SELECT timestamp AS asked_at, TO_JSON_STRING(jsonPayload) AS payload
        FROM `{table}`
        WHERE _TABLE_SUFFIX BETWEEN '{start_suffix}' AND '{end_suffix}'
          AND JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.message') = 'conversation_turn'
    """

    if client is None:
        try:
            from google.cloud import bigquery
        except ImportError as exc:  # pragma: no cover - exercised in deployed image
            raise TestLogImportError("BigQuery support is not installed") from exc
        client = bigquery.Client(project=TEST_LOG_PROJECT)

    try:
        rows = client.query(query).result()
    except Exception as exc:  # noqa: BLE001 - external service errors are normalized here
        raise TestLogImportError("Could not read Test conversation logs") from exc

    logs = []
    for row in rows:
        payload = _payload_from_row(row)
        if payload is not None:
            logs.append(payload)
    return logs
