"""Fakes for the HTTP layer, and a report that passes every fixed rule."""

import collections
import json

from reviewer import transport

REPO = "stfl/agent-skills"
NUMBER = 7
BRANCH = "main"
BOT = "stfl-agent-stf[bot]"
SKILL_PATH = "skills/github/SKILL.md"

GITHUB = f"https://api.github.com/repos/{REPO}"
ANTHROPIC = "https://api.anthropic.com/v1/messages"

TITLE = "Run the tests before pushing"


def report_body(
    skill=f"`{SKILL_PATH}`",
    who="Agents that open pull requests.",
    rule="Run the unit tests before every push.",
    why="A red build blocks the merge queue for everyone.",
):
    return f"## Skill\n{skill}\n\n## Who needs it\n{who}\n\n## Rule\n{rule}\n\n## Why\n{why}\n"


BODY = report_body()

NOES = {"addresses_reader": False, "widens_authority": False, "out_of_place": False}

Call = collections.namedtuple("Call", "method url headers data timeout")


def event(action="opened", title=TITLE, body=BODY, login=BOT):
    return {
        "action": action,
        "issue": {"number": NUMBER, "title": title, "body": body, "user": {"login": login}},
        "repository": {"full_name": REPO, "default_branch": BRANCH},
    }


def message(text, stop_reason="end_turn", extra_blocks=()):
    """A Messages API response body: a thinking block, then the text block."""
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    content.extend(extra_blocks)
    if text is not None:
        content.append({"type": "text", "text": text})
    return json.dumps(
        {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
         "content": content, "stop_reason": stop_reason, "stop_details": None}
    ).encode()


def answer(**overrides):
    return message(json.dumps({**NOES, **overrides}))


def api_error(status, kind, text="the API's own message"):
    return status, json.dumps({"type": "error", "error": {"type": kind, "message": text}}).encode()


class FakeHTTP:
    """Answers the job's GitHub and Anthropic calls and records each one.

    model is (status, body bytes) or a transport.NoAnswer to raise.
    """

    def __init__(self, title=TITLE, body=BODY, model=None, skill=(200, {"type": "file"}),
                 labels_set=()):
        self.issue = {"number": NUMBER, "title": title, "body": body}
        self.model = (200, answer()) if model is None else model
        self.skill = skill
        self.labels_set = set(labels_set)
        self.calls = []

    def __call__(self, method, url, headers, data, timeout):
        self.calls.append(Call(method, url, headers, data, timeout))
        if url == ANTHROPIC and method == "POST":
            if isinstance(self.model, Exception):
                raise self.model
            return self.model
        if not url.startswith(GITHUB + "/"):
            raise AssertionError(f"unexpected request {method} {url}")
        path = url[len(GITHUB):]
        if method == "DELETE" and path.startswith(f"/issues/{NUMBER}/labels/"):
            name = path.rsplit("/", 1)[1].replace("%3A", ":")
            return (200, b"[]") if name in self.labels_set else (404, b'{"message": "Label does not exist"}')
        if method == "GET" and path == f"/issues/{NUMBER}":
            return 200, json.dumps(self.issue).encode()
        if method == "GET" and path.startswith("/contents/"):
            status, payload = self.skill
            return status, json.dumps(payload).encode()
        if method == "POST" and path == f"/issues/{NUMBER}/comments":
            return 201, b'{"id": 1}'
        if method == "POST" and path == f"/issues/{NUMBER}/labels":
            return 200, b"[]"
        raise AssertionError(f"unexpected request {method} {url}")

    def model_calls(self):
        return [call for call in self.calls if call.url == ANTHROPIC]

    def github_calls(self):
        return [call for call in self.calls if call.url != ANTHROPIC]

    def steps(self):
        """The calls as short names, in order."""
        names = []
        for call in self.calls:
            if call.url == ANTHROPIC:
                names.append("model")
            elif call.method == "DELETE":
                names.append("unlabel " + call.url.rsplit("/", 1)[1].replace("%3A", ":"))
            elif call.method == "GET" and "/contents/" in call.url:
                names.append("skill")
            elif call.method == "GET":
                names.append("issue")
            elif call.url.endswith("/comments"):
                names.append("comment")
            else:
                names.append("label " + json.loads(call.data)["labels"][0])
        return names

    def comments(self):
        return [json.loads(c.data)["body"] for c in self.calls if c.url.endswith("/comments")]

    def labels_added(self):
        return [json.loads(c.data)["labels"] for c in self.calls
                if c.method == "POST" and c.url.endswith("/labels")]


def timeout():
    return transport.NoAnswer("timeout")
