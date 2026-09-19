"""Production logging keeps structured chatbot records and hides HTTP noise."""

import logging

from django.test import SimpleTestCase


class HttpClientLoggingTests(SimpleTestCase):
    def test_httpx_request_logs_are_warning_only(self):
        """Routine successful HTTP calls must not print INFO request lines."""
        for logger_name in ("httpx", "httpcore"):
            logger = logging.getLogger(logger_name)
            self.assertFalse(logger.isEnabledFor(logging.INFO), logger_name)
            self.assertTrue(logger.isEnabledFor(logging.WARNING), logger_name)
