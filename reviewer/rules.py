"""The fixed rules. They refuse and never strip, and run before any model call.

The Markdown parsing here is not GitHub's. Wherever the two could disagree it
counts text as code only when every reading GitHub could take agrees, and
counts a line as a heading when any reading could: a false hold reaches
Stefan, a missed one reaches the daily review.
"""

import re
import string
import unicodedata

HIDDEN = "hidden character"
LENGTH = "length"
BASE64 = "base64"
MARKUP = "markup"
VERDICT = "verdict"
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
    r"|[A-Za-z][A-Za-z0-9+.-]*://"  # bare URL
    r"|(?i:www\.)"
    r"|@[A-Za-z0-9]"  # @-mention or e-mail address
)
# GitHub reads link reference definitions before code spans, so they are
# searched in text with only fenced blocks removed.
_LINK_DEFINITION = re.compile(
    r"^[ \t]*(?:(?:>|[-+*]|[0-9]{1,9}[.)])[ \t]*)*\[(?:[^\]\\]|\\[\s\S])*\]:", re.MULTILINE
)

# The reviewer's own vocabulary, which an honest report has no reason to quote.
_VERDICT = re.compile(
    r"\b(?:passed|held)\W{0,3}[0-3] ?(?:/|of|out of) ?3\b"  # verdict count
    r"|\bheld ?:"
    r"|\breview(?:er)? ?: ?(?:passed|held|escalated|infrastructure)\b"  # label name
    r"|\bsha-?256 ?[:=]|\bsha-?256\W{0,3}[0-9a-f]{16}|\b[0-9a-f]{64}\b"  # hash line or bare digest
    r"|\b(?:addresses_reader|widens_authority|out_of_place)\b"  # answer key
    # A reviewer's approval; the lookbehind spares the role "the Code Reviewer approved".
    r"|(?<!code )\breviewer (?:approved|passed|cleared)\b"
    r"|\b(?:approved|passed|cleared) by (?:the |an? )?(?:automated )?reviewer\b",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")

# CommonMark ends a line only at LF, CR or CRLF; str.splitlines() also splits
# at U+2028 and others, which would show a fence GitHub does not see.
_LINE_END = re.compile(r"\r\n|\r|\n")
_CONTAINERS = re.compile(r"(?:[ \t]+|>|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]|$))*")
_QUOTES = re.compile(r"[ \t>]*")
_FENCE_LIKE = re.compile(r"`{3,}|~{3,}")
_FENCE_OPEN = re.compile(r"(`{3,}|~{3,})(.*)")
_FENCE_CLOSE = re.compile(r"(`{3,}|~{3,})[ \t]*")
_TABLE_DELIMITER_CHARS = frozenset(" \t|:->*+.)0123456789")
_ATX = re.compile(r" {0,3}#{1,6}(?=[ \t]|$)")
_ATX_ANYWHERE = re.compile(r"#{1,6}(?:[ \t]|$)")
_ATX_CLOSE = re.compile(r"(?:^|[ \t])#+[ \t]*$")
_SETEXT_UNDERLINE = re.compile(r"(?:=+|-+)[ \t]*")
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
    if has_markup(title, fences=False) or has_markup(body):
        return MARKUP
    if any(has_verdict(text) for text in texts):
        return VERDICT
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


def has_markup(text, fences=True):
    """Whether text holds markup outside code; fences=False reads no fenced blocks."""
    lines = _lines(text)
    fenced = _fenced(lines) if fences else [False] * len(lines)
    unfenced = "\n".join("" if in_fence else line for line, in_fence in zip(lines, fenced))
    if _LINK_DEFINITION.search(unfenced):
        return True
    return _MARKUP.search(_outside_code(lines, fenced)) is not None


def has_verdict(text):
    """Whether text, code included, quotes the reviewer's verdicts, labels, hash or answer keys."""
    return _VERDICT.search(_WHITESPACE.sub(" ", text)) is not None


def form_headings(body):
    """Return the line index of each form heading, or None if the form is wrong."""
    lines = _lines(body)
    fenced = _fenced(lines)
    found = []
    for i, line in enumerate(lines):
        if fenced[i]:
            continue
        atx = _ATX.match(line)
        if atx:
            found.append((i, _ATX_CLOSE.sub("", line[atx.end() :].strip()).strip()))
        elif _may_be_atx(line) or _may_be_setext_underline(lines, fenced, i):
            return None
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


def _content(line):
    """The line after its indentation and any blockquote or list markers."""
    return line[_CONTAINERS.match(line).end() :]


def _fenced(lines):
    """Flag each line that belongs to a fenced code block, fence lines included.

    A fence line that is indented or inside a blockquote or list item may open,
    close or belong to a fence depending on the containers around it, so any
    such line makes the text count as having no fenced block at all.
    """
    if any(_FENCE_LIKE.match(_content(line)) and not _FENCE_LIKE.match(line) for line in lines):
        return [False] * len(lines)
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


def _outside_code(lines, fenced):
    """Return the lines with fenced blocks emptied and code spans blanked out.

    Code spans pair within one line. GitHub pairs them across a paragraph, which
    gives the same spans only when every line pairs all its backtick runs, so a
    block of lines holding an unpaired run counts as having no code span. In a
    block with a table, a span counts only if it is code both when the line is
    a table row (cells split at unescaped pipes) and when it is not.
    """
    out = ["" if in_fence else line for line, in_fence in zip(lines, fenced)]
    for block in _blocks(lines, fenced):
        spans = [_code_spans(lines[i]) for i in block]
        if not all(paired for _, paired in spans):
            continue
        masks = [mask for mask, _ in spans]
        if any(_is_table_delimiter(lines[i]) for i in block):
            masks = [
                [a and b for a, b in zip(mask, _cell_code_spans(lines[i]))]
                for mask, i in zip(masks, block)
            ]
        for i, mask in zip(block, masks):
            out[i] = "".join(" " if code else ch for ch, code in zip(lines[i], mask))
    return "\n".join(out)


def _blocks(lines, fenced):
    """Group the indexes of consecutive lines that are neither blank nor fenced."""
    block = []
    for i, line in enumerate(lines):
        if fenced[i] or line.strip(" \t") == "":
            if block:
                yield block
            block = []
        else:
            block.append(i)
    if block:
        yield block


def _code_spans(text):
    """Flag each character of text inside a code span; also say if every run paired."""
    mask = [False] * len(text)
    paired = True
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n and text[i + 1] in string.punctuation:
            i += 2
            continue
        if text[i] != "`":
            i += 1
            continue
        end = i
        while end < n and text[end] == "`":
            end += 1
        close = _closing_run(text, end, end - i)
        if close is None:
            paired = False
            i = end
        else:
            stop = close + (end - i)
            mask[i:stop] = [True] * (stop - i)
            i = stop
    return mask, paired


def _closing_run(text, start, length):
    k, n = start, len(text)
    while k < n:
        if text[k] != "`":
            k += 1
            continue
        end = k
        while end < n and text[end] == "`":
            end += 1
        if end - k == length:
            return k
        k = end
    return None


def _cell_code_spans(line):
    """Flag code-span characters with the line read as table cells.

    GitHub splits cells at every pipe not directly after a backslash, even
    when that backslash is itself escaped.
    """
    mask = []
    start = 0
    for i in range(len(line) + 1):
        if i == len(line) or (line[i] == "|" and (i == 0 or line[i - 1] != "\\")):
            mask += _code_spans(line[start:i])[0]
            if i < len(line):
                mask.append(False)
            start = i + 1
    return mask


def _is_table_delimiter(line):
    # GitHub accepts a delimiter row without a pipe, such as ":-".
    return "-" in line and set(line) <= _TABLE_DELIMITER_CHARS


def _may_be_atx(line):
    return _ATX_ANYWHERE.match(_content(line)) is not None


def _may_be_setext_underline(lines, fenced, i):
    # A lone "-" under a paragraph is an underline, not an empty list item.
    underline = lines[i][_QUOTES.match(lines[i]).end() :]
    if i == 0 or fenced[i - 1] or not _SETEXT_UNDERLINE.fullmatch(underline):
        return False
    above = _content(lines[i - 1])
    return above.strip(" \t") != "" and not _ATX_ANYWHERE.match(above)


def _heading_key(text):
    return "".join(text.split()).lower()
