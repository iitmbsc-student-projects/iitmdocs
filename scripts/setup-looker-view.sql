-- BigQuery Views for Looker Studio
-- Creates flattened views of conversation and feedback logs for easy analytics
--
-- Prerequisites:
--   1. BigQuery dataset 'chatbot_logs' exists (created by cloudbuild.yaml)
--   2. At least one conversation/feedback has been logged (creates the source table)
--
-- Usage:
--   Replace YOUR_PROJECT_ID with your GCP project ID, then run:
--   bq query --use_legacy_sql=false < scripts/setup-looker-view.sql
--
-- Or run directly in BigQuery Console

-- ============================================================================
-- View 1: Conversations
-- ============================================================================
CREATE OR REPLACE VIEW `YOUR_PROJECT_ID.chatbot_logs.conversations` AS
SELECT
  timestamp,
  -- Use JSON_VALUE for backward compatibility with older logs that may not have these fields
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.session_id') AS session_id,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.conversation_id') AS conversation_id,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.message_id') AS message_id,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.username') AS username,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.question') AS question,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.rewritten_query') AS rewritten_query,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.query_source') AS query_source,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.original_answer') AS original_answer,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.response') AS response,
  CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.latency_ms') AS INT64) AS latency_ms,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.fact_check_passed') AS fact_check_passed,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.contains_raahat') AS contains_raahat,
  CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.history_length') AS INT64) AS history_length,
  JSON_EXTRACT(TO_JSON_STRING(jsonPayload), '$.documents') AS documents,
  JSON_EXTRACT(TO_JSON_STRING(jsonPayload), '$.db_faqs') AS db_faqs,
  JSON_EXTRACT(TO_JSON_STRING(jsonPayload), '$.tokens') AS tokens,
  CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.tokens.total_input_tokens') AS INT64) AS total_input_tokens,
  CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.tokens.total_output_tokens') AS INT64) AS total_output_tokens,
  -- Derived fields for analytics
  DATE(timestamp) AS date,
  EXTRACT(HOUR FROM timestamp) AS hour,
  CASE
    WHEN CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.latency_ms') AS INT64) < 2000 THEN 'fast'
    WHEN CAST(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.latency_ms') AS INT64) < 5000 THEN 'normal'
    ELSE 'slow'
  END AS latency_category
FROM `YOUR_PROJECT_ID.chatbot_logs.run_googleapis_com_stdout_*`
WHERE jsonPayload.message = "conversation_turn";

-- ============================================================================
-- View 2: User Feedback
-- ============================================================================
CREATE OR REPLACE VIEW `YOUR_PROJECT_ID.chatbot_logs.user_feedback` AS
SELECT
  timestamp,
  -- Use JSON_VALUE for safe extraction, returns NULL for missing fields
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.session_id') AS session_id,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.message_id') AS message_id,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.question') AS question,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.response') AS response,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') AS feedback_type,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_category') AS feedback_category,
  JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_text') AS feedback_text,
  -- Derived fields for analytics
  DATE(timestamp) AS date,
  EXTRACT(HOUR FROM timestamp) AS hour,
  -- Categorize feedback for easier filtering
  CASE
    WHEN JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') = 'up' THEN 'positive'
    WHEN JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') = 'down' THEN 'negative'
    WHEN JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') = 'report' THEN 'report'
    ELSE 'unknown'
  END AS feedback_sentiment
FROM `YOUR_PROJECT_ID.chatbot_logs.run_googleapis_com_stdout_*`
WHERE jsonPayload.message = "user_feedback";

-- ============================================================================
-- View 3: Feedback Summary (aggregate statistics)
-- ============================================================================
CREATE OR REPLACE VIEW `YOUR_PROJECT_ID.chatbot_logs.feedback_summary` AS
SELECT
  DATE(timestamp) AS date,
  COUNT(*) AS total_feedback,
  COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') = 'up') AS thumbs_up,
  COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') = 'down') AS thumbs_down,
  COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') = 'report') AS reports,
  -- Satisfaction rate (thumbs up / (thumbs up + thumbs down))
  SAFE_DIVIDE(
    COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') = 'up'),
    COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_type') IN ('up', 'down'))
  ) AS satisfaction_rate,
  -- Report category breakdown
  COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_category') = 'wrong_info') AS wrong_info_reports,
  COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_category') = 'outdated') AS outdated_reports,
  COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_category') = 'unhelpful') AS unhelpful_reports,
  COUNTIF(JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.feedback_category') = 'other') AS other_reports
FROM `YOUR_PROJECT_ID.chatbot_logs.run_googleapis_com_stdout_*`
WHERE jsonPayload.message = "user_feedback"
GROUP BY date
ORDER BY date DESC;

-- ============================================================================
-- View 4: Conversations with Feedback (joined by message_id)
-- ============================================================================
CREATE OR REPLACE VIEW `YOUR_PROJECT_ID.chatbot_logs.conversations_with_feedback` AS
SELECT
  c.timestamp AS conversation_timestamp,
  c.session_id,
  c.conversation_id,
  c.message_id,
  c.username,
  c.question,
  c.rewritten_query,
  c.query_source,
  c.original_answer,
  c.response,
  c.latency_ms,
  c.fact_check_passed,
  c.contains_raahat,
  c.history_length,
  c.documents,
  c.db_faqs,
  c.tokens,
  c.total_input_tokens,
  c.total_output_tokens,
  c.latency_category,
  f.timestamp AS feedback_timestamp,
  f.feedback_type,
  f.feedback_category,
  f.feedback_text,
  f.feedback_sentiment,
  c.date,
  c.hour
FROM `YOUR_PROJECT_ID.chatbot_logs.conversations` c
LEFT JOIN `YOUR_PROJECT_ID.chatbot_logs.user_feedback` f
  ON c.message_id = f.message_id
WHERE c.message_id IS NOT NULL;
