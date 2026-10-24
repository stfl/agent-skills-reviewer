"""Grade one report: the fixed rules, then one model call.

The comment format and the hash join are a contract with stfl/dotfiles'
grade script; CLAUDE.md states it.
"""

import collections
import hashlib
import json
import pathlib
import re

from . import rules, transport

MODEL = "claude-sonnet-5-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL_TIMEOUT = 120

QUESTIONS = ("addresses_reader", "widens_authority", "out_of_place")

PASSED = "passed 3/3"
EDITED = "held: edited"
NOT_GRADED = "held: not graded"

PROMPT_PATH = pathlib.Path(__file__).with_name("prompt.txt")

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {question: {"type": "boolean"} for question in QUESTIONS},
    "required": list(QUESTIONS),
    "additionalProperties": False,
}

_ERROR_TYPE = re.compile(r"[a-z_]{1,64}")

Grade = collections.namedtuple("Grade", "verdict model_called api_error")


def held(rule):
    return f"held: {rule}"


def content_hash(title, body):
    """SHA-256 hex over the title, one NUL byte and the body, as UTF-8."""
    # surrogatepass only changes a string holding a lone surrogate, which the
    # hidden-character rule always holds; it keeps the hash from raising.
    return hashlib.sha256(
        title.encode("utf-8", "surrogatepass")
        + b"\0"
        + (body or "").encode("utf-8", "surrogatepass")
    ).hexdigest()


def comment(verdict, digest):
    return f"{verdict}\nsha256:{digest}"


def load_prompt():
    return PROMPT_PATH.read_text(encoding="utf-8")


def model_request(title, body, prompt):
    return {
        "model": MODEL,
        "max_tokens": 16000,
        "system": prompt,
        "messages": [{"role": "user", "content": json.dumps({"title": title, "body": body})}],
        "output_config": {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
        },
    }


def anthropic(api_key, http=transport.send):
    """Return ask(request) -> (status, body bytes), one Messages API call, no retry."""

    def ask(request):
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        return http("POST", ANTHROPIC_URL, headers, json.dumps(request).encode(), MODEL_TIMEOUT)

    return ask


def grade(title, body, *, skill_exists, ask, prompt=None):
    """Grade a report whose title and body are as the REST API returned them.

    ask(request) returns (status, body bytes) or raises transport.NoAnswer.
    api_error is set only for a failed call, and carries nothing the response
    body says beyond the API's error type.
    """
    body = body or ""
    rule = rules.fixed_rule(title, body, skill_exists)
    if rule is not None:
        return Grade(held(rule), False, None)
    request = model_request(title, body, load_prompt() if prompt is None else prompt)
    try:
        status, raw = ask(request)
    except transport.NoAnswer as error:
        return Grade(NOT_GRADED, True, error.reason)
    api_error = None if status == 200 else f"HTTP {status} {error_type(raw)}"
    return Grade(answer_verdict(status, raw), True, api_error)


def answer_verdict(status, raw):
    """Read a Messages API response into passed 3/3, held n/3 or held: not graded."""
    if status != 200:
        return NOT_GRADED
    try:
        message = json.loads(raw)
    except (ValueError, RecursionError):
        return NOT_GRADED
    if not isinstance(message, dict) or message.get("stop_reason") != "end_turn":
        return NOT_GRADED
    content = message.get("content")
    if not isinstance(content, list):
        return NOT_GRADED
    texts = [block for block in content if isinstance(block, dict) and block.get("type") == "text"]
    if len(texts) != 1 or not isinstance(texts[0].get("text"), str):
        return NOT_GRADED
    try:
        answer = json.loads(texts[0]["text"], object_pairs_hook=_unique_keys)
    except (ValueError, RecursionError):
        return NOT_GRADED
    if not isinstance(answer, dict) or set(answer) != set(QUESTIONS):
        return NOT_GRADED
    if not all(type(answer[question]) is bool for question in QUESTIONS):
        return NOT_GRADED
    passed = sum(not answer[question] for question in QUESTIONS)
    return PASSED if passed == len(QUESTIONS) else f"held {passed}/3"


def error_type(raw):
    """Return the API's error type if it is a plain identifier, else "unknown"."""
    try:
        kind = json.loads(raw)["error"]["type"]
    except (ValueError, TypeError, KeyError, RecursionError):
        return "unknown"
    return kind if isinstance(kind, str) and _ERROR_TYPE.fullmatch(kind) else "unknown"


def _unique_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)
