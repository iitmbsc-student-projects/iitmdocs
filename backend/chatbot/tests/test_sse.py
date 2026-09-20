"""SSE record framing tests — the byte-level contract the frontend parses."""
import json

from django.test import SimpleTestCase

from chatbot.services import sse


class SseContentTests(SimpleTestCase):
    def test_content_record_and_done(self):
        out = sse.sse_content("hello world")
        self.assertTrue(out.startswith("data: "))
        self.assertTrue(out.rstrip().endswith("data: [DONE]"))
        payload = json.loads(out.split("\n\n")[0][len("data: "):])
        self.assertEqual(payload["choices"][0]["delta"]["content"], "hello world")
        self.assertNotIn("rejected", payload)

    def test_rejected_flag(self):
        out = sse.sse_content("nope", rejected=True)
        payload = json.loads(out.split("\n\n")[0][len("data: "):])
        self.assertTrue(payload["rejected"])

    def test_unicode_preserved_literal(self):
        out = sse.sse_content("फीस")
        self.assertIn("फीस", out)  # not \uXXXX escaped


class SseDocumentTests(SimpleTestCase):
    def test_document_tool_call_shape(self):
        out = sse.sse_document_records(
            [
                {
                    "filename": "fees_and_payments.md",
                    "filepath": "src/ds/fees_and_payments.md",
                    "content": "x",
                    "relevance": 0.73,
                }
            ]
        )
        payload = json.loads(out.split("\n\n")[0][len("data: "):])
        self.assertEqual(payload["role"], "assistant")
        fn = payload["choices"][0]["delta"]["tool_calls"][0]["function"]
        self.assertEqual(fn["name"], "document")
        args = json.loads(fn["arguments"])  # arguments is a JSON *string*
        self.assertEqual(args["name"], "fees_and_payments")
        self.assertEqual(args["relevance"], 0.73)
        self.assertEqual(
            args["link"],
            "https://github.com/RishavT/iitmdocs/blob/main/src/ds/fees_and_payments.md",
        )

    def test_document_without_filepath_falls_back_to_flat_src(self):
        """Objects embedded before the per-programme folders still produce a link."""
        out = sse.sse_document_records([{"filename": "fees.md", "content": "x", "relevance": 0.1}])
        payload = json.loads(out.split("\n\n")[0][len("data: "):])
        args = json.loads(payload["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"])
        self.assertEqual(args["link"], "https://github.com/RishavT/iitmdocs/blob/main/src/fees.md")

    def test_multiple_records_concatenated(self):
        out = sse.sse_document_records(
            [{"filename": "a.md", "content": "", "relevance": 0.1}, {"filename": "b.md", "content": "", "relevance": 0.2}]
        )
        self.assertEqual(out.count('"name":"document"'), 2)


class SseErrorTests(SimpleTestCase):
    def test_error_record_no_done(self):
        out = sse.sse_error("boom")
        payload = json.loads(out.split("\n\n")[0][len("data: "):])
        self.assertEqual(payload["error"]["message"], "boom")
        self.assertEqual(payload["error"]["type"], "server_error")
        self.assertNotIn("[DONE]", out)
