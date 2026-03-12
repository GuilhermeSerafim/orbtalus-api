import logging
import unittest

from services.text_sanitizer import sanitize_text


class TextSanitizerTests(unittest.TestCase):
    def test_removes_disallowed_control_characters(self):
        value = "abc\x00def\x7fghi\x1ejkl\n\t\r"

        sanitized = sanitize_text(value, field_name="example")

        self.assertEqual(sanitized, "abcdefghijkl\n\t\r")

    def test_logs_when_text_is_sanitized(self):
        logger = logging.getLogger("tests.text_sanitizer")

        with self.assertLogs(logger.name, level="WARNING") as captured:
            sanitized = sanitize_text(
                "rio\x00teste",
                field_name="name",
                logger=logger,
                context="unit",
            )

        self.assertEqual(sanitized, "rioteste")
        self.assertIn("unit.name", captured.output[0])
