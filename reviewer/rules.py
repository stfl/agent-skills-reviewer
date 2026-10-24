"""The fixed rules. They refuse and never strip, and run before any model call.

Where the Markdown parsing here and GitHub's renderer could disagree, the
parsing errs toward finding markup and headings: a false hold reaches Stefan,
a missed one reaches the daily review.
"""

import re
import string
import unicodedata

HIDDEN = "hidden character"
LENGTH = "length"
BASE64 = "base64"
MARKUP = "markup"
FORM = "form"
SKILL = "skill"

MAX_TITLE = 200
MAX_BODY = 4000

FORM_HEADINGS = ("Skill", "Who needs it", "Rule", "Why")

# Default_Ignorable_Code_Point from Unicode's DerivedCoreProperties.txt, which
# unicodedata does not expose.
_DEFAULT_IGNORABLE = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)

_BASE64_RUN = re.compile(r"[A-Za-z0-9+/=_-]{100,}")

_MARKUP = re.compile(
    r"<[A-Za-z/!?]"  # HTML tag, comment or autolink
    r"|&(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#[xX][0-9A-Fa-f]+);"  # character reference
    r"|!\["  # image
    r"|\]\("  # inline link
    r"|\]\["  # full reference link
    r"|^[ \t]*(?:(?:>|[-+*]|[0-9]{1,9}[.)])[ \t]*)*\[(?:[^\]\\]|\\[\s\S])*\]:"  # link reference definition
    r"|[A-Za-z][A-Za-z0-9+.-]*://"  # bare URL
    r"|(?i:www\.)"
    r"|@[A-Za-z0-9]",  # @-mention or e-mail address
    re.MULTILINE,
)

# CommonMark ends a line only at LF, CR or CRLF; str.splitlines() also splits
# at U+2028 and others, which would show a fence GitHub does not see.
_LINE_END = re.compile(r"\r\n|\r|\n")
_FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_FENCE_CLOSE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
_TABLE_DELIMITER = re.compile(r"[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*")
_ATX_OPEN = re.compile(
    r"(?: {0,3}(?:> ?|[-+*][ \t]+|[0-9]{1,9}[.)][ \t]+))* {0,3}#{1,6}(?=[ \t]|$)"
)
_ATX_CLOSE = re.compile(r"(?:^|[ \t])#+[ \t]*$")
_SETEXT_UNDERLINE = re.compile(r" {0,3}(?:=+|-+)[ \t]*")
_NEW_SKILL = re.compile(r"new: [a-z0-9]+(?:-[a-z0-9]+)*")


def fixed_rule(title, body, skill_exists):
    """Return the name of the first fixed rule the report breaks, or None.

    skill_exists(path) answers whether path is a file on the calling
    repository's default branch; it is asked only for a well-formed path.
    """
    texts = (title, body)
    if any(is_hidden(ch) for text in texts for ch in text):
        return HIDDEN
    if len(title) > MAX_TITLE or len(body) > MAX_BODY:
        return LENGTH
    if any(_BASE64_RUN.search(text) for text in texts):
        return BASE64
    if any(_MARKUP.search(outside_code(text)) for text in texts):
        return MARKUP
    headings = form_headings(body)
    if headings is None:
        return FORM
    if not skill_ok(skill_text(body, headings), skill_exists):
        return SKILL
    return None


def is_hidden(ch):
    cp = ord(ch)
    if any(low <= cp <= high for low, high in _DEFAULT_IGNORABLE):
        return True
    category = unicodedata.category(ch)
    if category == "Cc":
        return ch not in "\n\r\t"
    return category in ("Co", "Cn", "Cs")


def outside_code(text):
    """Return text with fenced code blocks and inline code spans blanked out."""
    lines = _lines(text)
    fenced = _fenced(lines)
    pipes_split = any(_is_table_delimiter(line) for line in lines)
    return "\n".join(
        "" if in_fence else _blank_code_spans(line, pipes_split)
        for line, in_fence in zip(lines, fenced)
    )


def form_headings(body):
    """Return the line index of each form heading, or None if the form is wrong."""
    lines = _lines(body)
    fenced = _fenced(lines)
    found = []
    for i, line in enumerate(lines):
        if fenced[i]:
            continue
        if _is_setext_underline(lines, fenced, i):
            return None
        text = _atx_text(line)
        if text is not None:
            found.append((i, text))
    if [_heading_key(text) for _, text in found] != [_heading_key(h) for h in FORM_HEADINGS]:
        return None
    return [i for i, _ in found]


def skill_text(body, headings):
    """Return the text under the Skill heading, stripped."""
    lines = _lines(body)
    return "\n".join(lines[headings[0] + 1 : headings[1]]).strip()


def skill_ok(text, skill_exists):
    if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
    if _NEW_SKILL.fullmatch(text):
        return True
    return is_skill_path(text) and skill_exists(text)


def is_skill_path(text):
    segments = text.split("/")
    return segments[-1] == "SKILL.md" and all(s not in ("", ".", "..") for s in segments)


def _lines(text):
    return _LINE_END.split(text)


def _fenced(lines):
    """Flag each line that belongs to a fenced code block, fence lines included."""
    flags = []
    fence = None
    for line in lines:
        if fence is None:
            m = _FENCE_OPEN.fullmatch(line)
            # A backtick fence's info string cannot hold a backtick.
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = m.group(1)
            flags.append(fence is not None)
        else:
            flags.append(True)
            m = _FENCE_CLOSE.fullmatch(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
    return flags


def _is_table_delimiter(line):
    return "|" in line and "-" in line and _TABLE_DELIMITER.fullmatch(line) is not None


def _blank_code_spans(line, pipes_split):
    """Replace each inline code span in one line by a space.

    A span never crosses a line end, and in a document with a table it never
    crosses a pipe, since GitHub splits table cells before it finds spans.
    """
    out = []
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and i + 1 < n and line[i + 1] in string.punctuation:
            out.append(line[i : i + 2])
            i += 2
            continue
        if ch != "`":
            out.append(ch)
            i += 1
            continue
        end = i
        while end < n and line[end] == "`":
            end += 1
        close = _closing_run(line, end, end - i, pipes_split)
        if close is None:
            out.append(line[i:end])
            i = end
        else:
            out.append(" ")
            i = close + (end - i)
    return "".join(out)


def _closing_run(line, start, length, pipes_split):
    k, n = start, len(line)
    while k < n:
        if line[k] == "`":
            end = k
            while end < n and line[end] == "`":
                end += 1
            if end - k == length:
                return k
            k = end
        elif pipes_split and line[k] == "|":
            return None
        else:
            k += 1
    return None


def _atx_text(line):
    m = _ATX_OPEN.match(line)
    if not m:
        return None
    return _ATX_CLOSE.sub("", line[m.end() :].strip()).strip()


def _is_setext_underline(lines, fenced, i):
    if i == 0 or fenced[i - 1] or not _SETEXT_UNDERLINE.fullmatch(lines[i]):
        return False
    above = lines[i - 1]
    return (
        above.strip() != ""
        and _atx_text(above) is None
        and not _SETEXT_UNDERLINE.fullmatch(above)
    )


def _heading_key(text):
    return "".join(text.split()).lower()
