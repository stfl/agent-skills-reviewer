import unittest

from reviewer import transport


class SendTest(unittest.TestCase):
    def test_header_with_a_line_break_is_no_answer(self):
        with self.assertRaises(transport.NoAnswer) as raised:
            transport.send("POST", "http://127.0.0.1:9/", {"x-api-key": "key\n"}, b"{}", 1)
        self.assertEqual(raised.exception.reason, "request")

    def test_refused_connection_is_no_answer(self):
        with self.assertRaises(transport.NoAnswer) as raised:
            transport.send("GET", "http://127.0.0.1:9/", {}, None, 1)
        self.assertEqual(raised.exception.reason, "connection")


if __name__ == "__main__":
    unittest.main()
