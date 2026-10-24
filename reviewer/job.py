"""The reviewer job: one issues event in, one comment and one label out."""

import json
import urllib.parse

from . import grade as grading
from . import transport

BOTS = frozenset({"stfl-agent-stf[bot]", "stfl-agent-sev[bot]"})
ACTIONS = frozenset({"opened", "edited"})

LABEL_PASSED = "reviewer:passed"
LABEL_HELD = "reviewer:held"

GITHUB_API = "https://api.github.com"
GITHUB_TIMEOUT = 30


class GitHubError(Exception):
    def __init__(self, step, detail):
        super().__init__(step, detail)
        self.step = step
        self.detail = detail


class GitHub:
    """The REST calls the job makes on the calling repository."""

    def __init__(self, http, token, repo, api=GITHUB_API):
        self._http = http
        self._token = token
        self._base = f"{api}/repos/{repo}"

    def remove_label(self, number, label):
        self._call("remove label", "DELETE", f"/issues/{number}/labels/{_quote(label)}", ok=(200, 404))

    def issue(self, number):
        """Return the issue's (title, body), a null body as the empty string."""
        raw = self._call("read issue", "GET", f"/issues/{number}")
        try:
            issue = json.loads(raw)
            title, body = issue["title"], issue["body"]
        except (ValueError, TypeError, KeyError, RecursionError):
            raise GitHubError("read issue", "unexpected answer") from None
        if body is None:
            body = ""
        if not isinstance(title, str) or not isinstance(body, str):
            raise GitHubError("read issue", "unexpected answer")
        return title, body

    def is_file(self, path, ref):
        try:
            raw = self._call("read skill", "GET", f"/contents/{_quote(path, safe='/')}?ref={_quote(ref)}")
            answer = json.loads(raw)
        except (GitHubError, ValueError, RecursionError):
            return False
        return isinstance(answer, dict) and answer.get("type") == "file"

    def comment(self, number, body):
        self._call("post comment", "POST", f"/issues/{number}/comments", {"body": body}, ok=(201,))

    def add_label(self, number, label):
        self._call("add label", "POST", f"/issues/{number}/labels", {"labels": [label]})

    def _call(self, step, method, path, payload=None, ok=(200,)):
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "agent-skills-reviewer",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode()
        try:
            status, raw = self._http(method, self._base + path, headers, data, GITHUB_TIMEOUT)
        except transport.NoAnswer as error:
            raise GitHubError(step, error.reason) from None
        if status not in ok:
            raise GitHubError(step, f"HTTP {status}")
        return raw


def run(event_name, event, *, http, github_token, anthropic_key, log, github_api=GITHUB_API):
    """Grade the report an issues event names; return the exit code."""
    action = event.get("action")
    if event_name != "issues" or action not in ACTIONS:
        log("skip: not an issues opened or edited event")
        return 0
    issue = event["issue"]
    if (issue.get("user") or {}).get("login") not in BOTS:
        log("skip: author is not a Company App")
        return 0

    repository = event["repository"]
    number = issue["number"]
    github = GitHub(http, github_token, repository["full_name"], github_api)
    try:
        for label in (LABEL_PASSED, LABEL_HELD):
            github.remove_label(number, label)
        title, body = github.issue(number)
        if action == "edited" or (title, body) != (issue["title"], issue["body"] or ""):
            result = grading.Grade(grading.EDITED, False, None)
        else:
            result = grading.grade(
                title,
                body,
                skill_exists=lambda path: github.is_file(path, repository["default_branch"]),
                ask=grading.anthropic(anthropic_key, http),
            )
        if result.api_error is not None:
            log(f"api error: {result.api_error}")
        digest = grading.content_hash(title, body)
        github.comment(number, grading.comment(result.verdict, digest))
        github.add_label(number, LABEL_PASSED if result.verdict == grading.PASSED else LABEL_HELD)
    except GitHubError as error:
        log(f"error: GitHub {error.step}: {error.detail}")
        return 1

    called = "yes" if result.model_called else "no"
    log(f"grade: {result.verdict} sha256:{digest} (model called: {called})")
    return 1 if result.verdict == grading.NOT_GRADED else 0


def _quote(text, safe=""):
    return urllib.parse.quote(text, safe=safe)
