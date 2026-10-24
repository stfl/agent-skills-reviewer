"""The comment format and hash join shared with stfl/dotfiles' grade script."""

import re
import unittest

from reviewer import grade

VECTORS = (
    ("t", None, "3776096e9733584bd622e7e6417b65ba6640f8a8b809f475cd15ed5923cce3f6"),
    ("t", "a\r\nb", "442625189ec25d2182957d44bd0dd983f14b3e6e1172604fcf603e34c8851ab0"),
    ("Prüfung", "ü", "60565a8f40f5e518b0a47a6d96a6c8b682a45ca54fc1c21f31372b460ea40af9"),
)

VERDICT = re.compile(r"passed 3/3|held [012]/3|held: (?:hidden character|length|base64|markup|form|skill|edited|not graded)")


class HashTest(unittest.TestCase):
    def test_vectors(self):
        for title, body, digest in VECTORS:
            with self.subTest(title=title, body=body):
                self.assertEqual(grade.content_hash(title, body), digest)

    def test_null_body_hashes_as_empty(self):
        self.assertEqual(grade.content_hash("t", None), grade.content_hash("t", ""))

    def test_nothing_is_normalised(self):
        self.assertNotEqual(grade.content_hash("t", "b\n"), grade.content_hash("t", "b"))
        self.assertNotEqual(grade.content_hash("t", "a\r\nb"), grade.content_hash("t", "a\nb"))
        self.assertNotEqual(grade.content_hash("t ", "b"), grade.content_hash("t", "b"))

    def test_lone_surrogate_does_not_raise(self):
        self.assertRegex(grade.content_hash("t", "\ud800"), r"^[0-9a-f]{64}$")


class CommentTest(unittest.TestCase):
    def test_two_lines_one_lf_no_trailing_newline(self):
        digest = VECTORS[0][2]
        self.assertEqual(grade.comment("passed 3/3", digest), f"passed 3/3\nsha256:{digest}")

    def test_every_verdict_the_job_writes_is_in_the_contract(self):
        verdicts = [grade.PASSED, grade.EDITED, grade.NOT_GRADED]
        verdicts += [grade.held(rule) for rule in ("hidden character", "length", "base64", "markup", "form", "skill")]
        verdicts += [f"held {n}/3" for n in range(3)]
        for verdict in verdicts:
            with self.subTest(verdict=verdict):
                self.assertRegex(verdict, f"^(?:{VERDICT.pattern})$")


if __name__ == "__main__":
    unittest.main()
