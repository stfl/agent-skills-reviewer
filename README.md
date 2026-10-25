# agent-skills-reviewer

The first check on every report a Company App files as an issue on a stfl
skill repository.

Agents of the Paperclip companies file reports, lessons for a shared skill, as
issues through their Company Apps `stfl-agent-stf[bot]` and
`stfl-agent-sev[bot]`. When such an issue is opened, the reviewer grades it,
posts one comment with its verdict and labels the issue `reviewer:passed` or
`reviewer:held`.

## A filter, not a boundary

Report text comes from agents that read untrusted input, so it may carry
prompt injection. The reviewer holds anything odd before the daily review, a
later and separate model pass, reads it, and every hold reaches Stefan. A pass
says only that nothing tripped the filter. Whether the rule is right, how long
it is and how the title reads are for the daily review.

## How a report is graded

1. **Fixed rules**, before any model call. They refuse and never strip: hidden
   or invisible characters, an over-long title or body, base64-like runs,
   Markdown or HTML markup outside code spans, the reviewer's own verdict
   vocabulary anywhere in the title or body (code included), a body that is
   not the report form (headings `Skill`, `Who needs it`, `Rule`, `Why`), and
   a `Skill` that is neither `new: <name>` nor an existing `SKILL.md` on the
   repository's default branch.
2. **One model call** to Claude Sonnet 5.5, which answers three yes-or-no
   questions about the report (see [`reviewer/prompt.txt`](reviewer/prompt.txt)).
   Only three noes pass.

An edited report is never graded again: an edit holds it.

## Calling it from a skill repository

Each skill repository carries a caller stub that runs on `issues` `opened` and
`edited`, pins this workflow by full commit SHA and passes the secret as
`ANTHROPIC_API_KEY`. A stub looks like this:

```yaml
name: reviewer
on:
  issues:
    types: [opened, edited]
jobs:
  review:
    if: >-
      github.event.issue.user.login == 'stfl-agent-stf[bot]' ||
      github.event.issue.user.login == 'stfl-agent-sev[bot]'
    permissions:
      issues: write
      contents: read
    uses: stfl/agent-skills-reviewer/.github/workflows/review.yml@<full commit SHA>
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

The reviewer checks out its own code at exactly the pinned commit, so moving
the pin is the only way a skill repository picks up a change.

## What each comment means

Every comment is two lines: the verdict, then `sha256:` and the hash of the
title and body that were graded. The job's token posts it, so its author is
`github-actions[bot]`.

| Verdict | Label | Meaning |
|---|---|---|
| `passed 3/3` | `reviewer:passed` | No fixed rule fired and the model answered no to all three questions. |
| `held 2/3`, `held 1/3`, `held 0/3` | `reviewer:held` | The model answered yes to one or more questions; the number counts the noes. |
| `held: hidden character`, `held: length`, `held: base64`, `held: markup`, `held: verdict`, `held: form`, `held: skill` | `reviewer:held` | That fixed rule fired; the model was not called. `held: verdict` means the report quotes a verdict, a label, the hash line or an answer key, which an honest report has no reason to do. |
| `held: edited` | `reviewer:held` | The report was edited, or changed between filing and grading. |
| `held: not graded` | `reviewer:held` | The model call gave no usable answer. If the API failed (a timeout, a connection error, a non-200 status), the run shows red: re-run it. If the model answered out of form (a refusal, a cut-off or malformed answer), the run stays green and the hold is final: never re-run it, since a re-run hands an attacker a second try. |

## Tests

```sh
python3 -m unittest
```
