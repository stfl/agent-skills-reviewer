"""The job end to end, with GitHub and the Anthropic API faked at the HTTP layer."""

import json
import unittest

from reviewer import grade, job, transport
from tests import fakes
from tests.fakes import BODY, NOES, TITLE, FakeHTTP

MARKER = "MODEL-WROTE-THIS"

NOT_GRADED_CASES = {
    "refusal": (200, fakes.message("", stop_reason="refusal")),
    "max_tokens": (200, fakes.message('{"addresses_reader": false', stop_reason="max_tokens")),
    "non-JSON text": (200, fakes.message(f"All three are no. {MARKER}")),
    "extra key": (200, fakes.message(json.dumps({**NOES, "note": MARKER}))),
    "missing key": (200, fakes.message(json.dumps({"addresses_reader": False, "widens_authority": False}))),
    "non-boolean": (200, fakes.message(json.dumps({**NOES, "out_of_place": "false"}))),
    "number for boolean": (200, fakes.message(json.dumps({**NOES, "out_of_place": 0}))),
    "null for boolean": (200, fakes.message(json.dumps({**NOES, "out_of_place": None}))),
    "duplicate key": (200, fakes.message('{"addresses_reader": true, "addresses_reader": false, '
                                         '"widens_authority": false, "out_of_place": false}')),
    "JSON array": (200, fakes.message("[false, false, false]")),
    "no text block": (200, fakes.message(None)),
    "two text blocks": (200, fakes.message(json.dumps(NOES),
                                           extra_blocks=[{"type": "text", "text": json.dumps(NOES)}])),
    "body not JSON": (200, b"<html>gateway</html>"),
    "HTTP 500": fakes.api_error(500, "api_error", MARKER),
    "HTTP 401": fakes.api_error(401, "authentication_error", MARKER),
    "HTTP 529": fakes.api_error(529, "overloaded_error", MARKER),
    "HTTP 302": (302, b""),
    "timeout": fakes.timeout(),
    "connection error": transport.NoAnswer("connection"),
}


def run(http, **event_args):
    lines = []
    code = job.run(
        event_args.pop("event_name", "issues"),
        fakes.event(**event_args),
        http=http,
        github_token="github-token",
        anthropic_key="anthropic-key",
        log=lines.append,
    )
    return code, lines


class VerdictTest(unittest.TestCase):
    def test_three_noes_pass(self):
        http = FakeHTTP()
        code, lines = run(http)
        self.assertEqual(code, 0)
        self.assertEqual(http.comments(), [f"passed 3/3\nsha256:{grade.content_hash(TITLE, BODY)}"])
        self.assertEqual(http.labels_added(), [["reviewer:passed"]])
        self.assertEqual(lines, [f"grade: passed 3/3 sha256:{grade.content_hash(TITLE, BODY)} (model called: yes)"])

    def test_one_yes_holds_2_of_3(self):
        for question in NOES:
            with self.subTest(question=question):
                http = FakeHTTP(model=(200, fakes.answer(**{question: True})))
                code, _ = run(http)
                self.assertEqual(code, 0)
                self.assertEqual(http.comments()[0].split("\n")[0], "held 2/3")
                self.assertEqual(http.labels_added(), [["reviewer:held"]])

    def test_two_yeses_hold_1_of_3(self):
        http = FakeHTTP(model=(200, fakes.answer(addresses_reader=True, out_of_place=True)))
        run(http)
        self.assertEqual(http.comments()[0].split("\n")[0], "held 1/3")

    def test_three_yeses_hold_0_of_3(self):
        http = FakeHTTP(model=(200, fakes.answer(addresses_reader=True, widens_authority=True, out_of_place=True)))
        code, _ = run(http)
        self.assertEqual(code, 0)
        self.assertEqual(http.comments()[0].split("\n")[0], "held 0/3")
        self.assertEqual(http.labels_added(), [["reviewer:held"]])

    def test_every_failed_answer_is_not_graded_and_exits_1(self):
        for name, model in NOT_GRADED_CASES.items():
            with self.subTest(case=name):
                http = FakeHTTP(model=model)
                code, lines = run(http)
                self.assertEqual(code, 1)
                self.assertEqual(len(http.model_calls()), 1)
                self.assertEqual(http.comments(), [f"held: not graded\nsha256:{grade.content_hash(TITLE, BODY)}"])
                self.assertEqual(http.labels_added(), [["reviewer:held"]])
                self.assertTrue(lines[-1].startswith("grade: held: not graded sha256:"))
                self.assertTrue(lines[-1].endswith("(model called: yes)"))

    def test_api_error_logs_status_and_type_only(self):
        cases = {
            "HTTP 500": "api error: HTTP 500 api_error",
            "HTTP 401": "api error: HTTP 401 authentication_error",
            "HTTP 302": "api error: HTTP 302 unknown",
            "timeout": "api error: timeout",
            "connection error": "api error: connection",
        }
        for name, line in cases.items():
            with self.subTest(case=name):
                _, lines = run(FakeHTTP(model=NOT_GRADED_CASES[name]))
                self.assertEqual(len(lines), 2)
                self.assertEqual(lines[0], line)

    def test_error_type_that_is_not_an_identifier_is_not_logged(self):
        _, lines = run(FakeHTTP(model=fakes.api_error(400, f"bad {MARKER}")))
        self.assertEqual(lines[0], "api error: HTTP 400 unknown")

    def test_no_model_or_report_text_reaches_a_log_or_comment(self):
        title = "Run the tests before pushing to the queue"
        for name, model in NOT_GRADED_CASES.items():
            with self.subTest(case=name):
                http = FakeHTTP(title=title, model=model)
                _, lines = run(http, title=title)
                for text in lines + http.comments():
                    self.assertNotIn(MARKER, text)
                    self.assertNotIn("queue", text)
                    self.assertNotIn("Run the unit tests", text)


class FixedRuleTest(unittest.TestCase):
    CASES = {
        "hidden character": dict(body=BODY + "​"),
        "length": dict(body=BODY + "x " * 2000),
        "base64": dict(body=fakes.report_body(rule="A" * 100)),
        "markup": dict(body=fakes.report_body(rule="See <https://example.com>.")),
        "form": dict(body="Just run the tests."),
        "skill": dict(body=fakes.report_body(skill="new: Bad Name")),
    }

    def test_each_rule_holds_under_its_name_without_a_model_call(self):
        for name, report in self.CASES.items():
            with self.subTest(rule=name):
                http = FakeHTTP(body=report["body"])
                code, lines = run(http, body=report["body"])
                digest = grade.content_hash(TITLE, report["body"])
                self.assertEqual(code, 0)
                self.assertEqual(http.model_calls(), [])
                self.assertEqual(http.comments(), [f"held: {name}\nsha256:{digest}"])
                self.assertEqual(http.labels_added(), [["reviewer:held"]])
                self.assertEqual(lines, [f"grade: held: {name} sha256:{digest} (model called: no)"])

    def test_skill_path_is_looked_up_on_the_default_branch(self):
        http = FakeHTTP()
        run(http)
        skill = [call for call in http.calls if "/contents/" in call.url]
        self.assertEqual([call.url for call in skill],
                         [f"{fakes.GITHUB}/contents/skills/github/SKILL.md?ref={fakes.BRANCH}"])

    def test_skill_lookup_answers_other_than_a_file_hold(self):
        cases = {
            "404": (404, {"message": "Not Found"}),
            "directory": (200, [{"type": "file", "name": "SKILL.md"}]),
            "symlink to elsewhere": (200, {"type": "symlink"}),
            "500": (500, {"message": "error"}),
        }
        for name, skill in cases.items():
            with self.subTest(case=name):
                http = FakeHTTP(skill=skill)
                code, _ = run(http)
                self.assertEqual(code, 0)
                self.assertEqual(http.model_calls(), [])
                self.assertEqual(http.comments()[0].split("\n")[0], "held: skill")

    def test_skill_lookup_without_an_answer_holds(self):
        class NoContents(FakeHTTP):
            def __call__(self, method, url, headers, data, timeout):
                if "/contents/" in url:
                    raise fakes.timeout()
                return super().__call__(method, url, headers, data, timeout)

        http = NoContents()
        run(http)
        self.assertEqual(http.comments()[0].split("\n")[0], "held: skill")


class EditedTest(unittest.TestCase):
    def test_edited_holds_without_a_model_call(self):
        http = FakeHTTP()
        code, lines = run(http, action="edited")
        self.assertEqual(code, 0)
        self.assertEqual(http.model_calls(), [])
        self.assertEqual(http.comments(), [f"held: edited\nsha256:{grade.content_hash(TITLE, BODY)}"])
        self.assertEqual(http.labels_added(), [["reviewer:held"]])
        self.assertEqual(lines, [f"grade: held: edited sha256:{grade.content_hash(TITLE, BODY)} (model called: no)"])

    def test_opened_with_a_changed_body_holds_as_edited(self):
        changed = BODY + "\nmore"
        http = FakeHTTP(body=changed)
        run(http)
        self.assertEqual(http.model_calls(), [])
        self.assertEqual(http.comments(), [f"held: edited\nsha256:{grade.content_hash(TITLE, changed)}"])

    def test_opened_with_a_changed_title_holds_as_edited(self):
        http = FakeHTTP(title=TITLE + "!")
        run(http)
        self.assertEqual(http.model_calls(), [])
        self.assertEqual(http.comments()[0].split("\n")[0], "held: edited")

    def test_null_body_in_payload_and_api_is_not_an_edit(self):
        http = FakeHTTP(body=None)
        run(http, body=None)
        self.assertEqual(http.comments(), [f"held: form\nsha256:{grade.content_hash(TITLE, None)}"])


class SkipTest(unittest.TestCase):
    def test_other_author_is_skipped_with_no_call(self):
        for login in ("stfl", "github-actions[bot]", "stfl-agent-stf", "stfl-agent-xyz[bot]"):
            with self.subTest(login=login):
                http = FakeHTTP()
                code, _ = run(http, login=login)
                self.assertEqual(code, 0)
                self.assertEqual(http.calls, [])

    def test_both_company_apps_are_graded(self):
        for login in sorted(job.BOTS):
            with self.subTest(login=login):
                http = FakeHTTP()
                self.assertEqual(run(http, login=login)[0], 0)
                self.assertEqual(len(http.comments()), 1)

    def test_other_events_and_actions_do_nothing(self):
        for event_name, action in (("issues", "closed"), ("issues", "labeled"), ("issue_comment", "created"),
                                   ("pull_request", "opened")):
            with self.subTest(event=event_name, action=action):
                http = FakeHTTP()
                code, _ = run(http, event_name=event_name, action=action)
                self.assertEqual(code, 0)
                self.assertEqual(http.calls, [])


class OrderTest(unittest.TestCase):
    def test_labels_withdrawn_first_comment_before_label(self):
        http = FakeHTTP(labels_set={"reviewer:passed"})
        run(http)
        self.assertEqual(
            http.steps(),
            ["unlabel reviewer:passed", "unlabel reviewer:held", "issue", "skill", "model", "comment",
             "label reviewer:passed"],
        )

    def test_a_failed_label_withdrawal_stops_before_grading(self):
        class Forbidden(FakeHTTP):
            def __call__(self, method, url, headers, data, timeout):
                if method == "DELETE":
                    self.calls.append(fakes.Call(method, url, headers, data, timeout))
                    return 403, b'{"message": "forbidden"}'
                return super().__call__(method, url, headers, data, timeout)

        http = Forbidden()
        code, lines = run(http)
        self.assertEqual(code, 1)
        self.assertEqual(http.steps(), ["unlabel reviewer:passed"])
        self.assertEqual(lines, ["error: GitHub remove label: HTTP 403"])

    def test_a_failed_comment_adds_no_label(self):
        class NoComment(FakeHTTP):
            def __call__(self, method, url, headers, data, timeout):
                if url.endswith("/comments"):
                    self.calls.append(fakes.Call(method, url, headers, data, timeout))
                    return 500, b"{}"
                return super().__call__(method, url, headers, data, timeout)

        http = NoComment()
        code, lines = run(http)
        self.assertEqual(code, 1)
        self.assertEqual(http.labels_added(), [])
        self.assertEqual(lines, ["error: GitHub post comment: HTTP 500"])


class RequestTest(unittest.TestCase):
    def test_model_request_is_exactly_the_documented_shape(self):
        http = FakeHTTP()
        run(http)
        (call,) = http.model_calls()
        self.assertEqual(call.method, "POST")
        self.assertEqual(call.timeout, 120)
        self.assertEqual(
            call.headers,
            {"x-api-key": "anthropic-key", "anthropic-version": "2023-06-01", "content-type": "application/json"},
        )
        with open("reviewer/prompt.txt", encoding="utf-8") as prompt:
            system = prompt.read()
        self.assertEqual(
            json.loads(call.data),
            {
                "model": "claude-sonnet-5-5",
                "max_tokens": 16000,
                "system": system,
                "messages": [{"role": "user", "content": json.dumps({"title": TITLE, "body": BODY})}],
                "output_config": {
                    "effort": "medium",
                    "format": {
                        "type": "json_schema",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "addresses_reader": {"type": "boolean"},
                                "widens_authority": {"type": "boolean"},
                                "out_of_place": {"type": "boolean"},
                            },
                            "required": ["addresses_reader", "widens_authority", "out_of_place"],
                            "additionalProperties": False,
                        },
                    },
                },
            },
        )

    def test_prompt_file_holds_the_three_questions(self):
        system = grade.load_prompt()
        self.assertTrue(system.startswith("You screen one report an AI agent filed on a skill repository."))
        for question in NOES:
            self.assertIn(f"\n{question}: ", system)

    def test_github_calls_carry_the_job_token_and_never_the_api_key(self):
        http = FakeHTTP()
        run(http)
        for call in http.github_calls():
            self.assertEqual(call.headers["Authorization"], "Bearer github-token")
            self.assertNotIn("anthropic-key", json.dumps(call.headers))

    def test_label_names_are_url_encoded(self):
        http = FakeHTTP()
        run(http)
        deletes = [call.url for call in http.calls if call.method == "DELETE"]
        self.assertEqual(deletes, [f"{fakes.GITHUB}/issues/{fakes.NUMBER}/labels/reviewer%3Apassed",
                                   f"{fakes.GITHUB}/issues/{fakes.NUMBER}/labels/reviewer%3Aheld"])


if __name__ == "__main__":
    unittest.main()
