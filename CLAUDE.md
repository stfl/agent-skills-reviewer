# CLAUDE.md

The agent reference for agent-skills-reviewer. [README.md](README.md) is the
human primer: what the reviewer does, how a skill repository calls it and
what each comment means.

## Where things are

- `.github/workflows/review.yml`: the reusable workflow. It checks out this
  repository at `job.workflow_repository`@`job.workflow_sha`, the commit the
  caller pinned, and runs `python3 -m reviewer`.
- `reviewer/`: the job. `rules.fixed_rule` and `grade.grade` are the grading
  logic; the labelled-set eval in stfl/agent-skills-reviewer-set imports them
  and runs the same rules and prompt, so keep them importable and free of
  GitHub-event state.
- `reviewer/prompt.txt`: the system prompt, sent verbatim.
- `tests/`: `python3 -m unittest` from the repository root. GitHub and the
  Anthropic API are faked at the one HTTP function,
  `http(method, url, headers, data, timeout) -> (status, body)`.

## Constraints

- Python 3 standard library only, no `pip install`, no SDK. The only
  third-party action is `actions/checkout`, pinned by full commit SHA.
- The runner image stays pinned (`ubuntu-24.04`): its Python's Unicode
  database decides which code points are unassigned.
- No event field reaches a script through `${{ }}`; the script reads
  `$GITHUB_EVENT_PATH`.
- The fixed rules refuse and never strip. Their Markdown parsing is not
  GitHub's: text counts as code only when every reading GitHub could take
  agrees, and a line counts as a heading when any reading could. A change
  that makes more text count as code needs a test with GitHub's rendering of
  the case (`gh api markdown -f mode=gfm -f text=...`).

## Ship order

1. Push the reviewer to `main`.
2. The labelled-set eval in stfl/agent-skills-reviewer-set passes at that
   commit SHA.
3. Then the caller stubs' pins move to that SHA, in stfl/agent-skills,
   stfl/agent-dev-skills and stfl/agent-oebb-skills.

## Rerun rule

A change to the prompt, the model, the effort, the fixed rules or the report
template reruns the labelled set before any pin moves.

## Pass rule

Only three noes pass: every fixed rule clear, then a model answer that counts
(HTTP 200, `stop_reason` `end_turn`, exactly one `text` block holding a JSON
object with exactly the three keys, each a JSON boolean) with all three false.
Every other outcome holds. Loosening the pass rule, meaning anything but three
noes passing or any hold becoming a pass, takes Stefan's word. Never regrade
an edit, and never route a refusal to another model.

## No model-written text in a log or comment

No text the model wrote, and no report text, reaches a log, a comment or
Stefan; stfl/agent-dev-skills' run logs are readable by any signed-in user.
The job logs one line per grade, `grade: <verdict> sha256:<hex> (model
called: yes|no)`, and for a failed model call one more line with only the
HTTP status and the API's error `type` (or `timeout`, `connection`,
`request`). A skipped event logs nothing. An uncaught exception logs only its
type name. Comments are never edited or deleted.

## Comment and hash contract

stfl/dotfiles' grade script (bd dotfiles-um2q.20) checks each pass for
tampering by recomputing the hash in the reviewer's comment. The comment
format and the hash join below are shared with it: change one only together
with the other.

The comment body is exactly two lines joined by one LF, with no trailing
newline:

```
<verdict>
sha256:<64 lowercase hex digits>
```

`<verdict>` is one of `passed 3/3`, `held 0/3`, `held 1/3`, `held 2/3`,
`held: <rule>`, `held: edited`, `held: not graded`. In `held n/3` and
`passed 3/3`, n counts the checks passed, the questions answered no.
`<rule>` is one of `hidden character`, `length`, `base64`, `markup`, `form`,
`skill`.

The hash is SHA-256 over the title's UTF-8 bytes, one NUL byte (0x00), then
the body's UTF-8 bytes. Title and body are the strings exactly as the REST
API returned them when the job read the issue, a null body being the empty
string. Nothing is trimmed or normalised: no line-ending conversion, no
Unicode normalisation, no trailing-newline handling.

```python
hashlib.sha256(title.encode() + b"\0" + (body or "").encode()).hexdigest()
```

The join is NUL because the hidden-character rule refuses NUL in a passing
title and body, so the split between them cannot move while the hash stays
the same; with an LF it could, by moving a line between title and body. Never
compute the hash through a shell variable: `$(...)` strips trailing newlines.

Test vectors, checked by `tests/test_contract.py`:

| title | body | sha256 |
|---|---|---|
| `t` | null | `3776096e9733584bd622e7e6417b65ba6640f8a8b809f475cd15ed5923cce3f6` |
| `t` | `a\r\nb` | `442625189ec25d2182957d44bd0dd983f14b3e6e1172604fcf603e34c8851ab0` |
| `Prüfung` | `ü` | `60565a8f40f5e518b0a47a6d96a6c8b682a45ca54fc1c21f31372b460ea40af9` |
