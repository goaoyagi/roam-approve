"""Adapter for Devin CLI/Desktop PermissionRequest hooks."""

import json
import unicodedata

from .base import AgentAdapter, ApprovalRequest, Result

ELLIPSIS = "..."

# Hiragana, katakana, CJK ideographs, Japanese punctuation and half-width
# katakana. Full-width ASCII (U+FF01-FF5E, e.g. "ｒｍ") is deliberately
# excluded so look-alike commands are flagged as "<?:n>", not "<JA:n>".
_JAPANESE_RANGES = (
    (0x3000, 0x303F),
    (0x3040, 0x30FF),
    (0x31F0, 0x31FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFF5F, 0xFFEF),
)


def _is_japanese(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _JAPANESE_RANGES)


def _tokenize(line: str) -> list[str]:
    """Split a line into display atoms; each non-ASCII run becomes one marker.

    The device font is ASCII only, so runs of non-ASCII characters are shown
    as "<JA:n>" (all Japanese) or "<?:n>" (anything else), where n is the
    number of code points, keeping the ASCII structure of the command visible.
    """
    atoms: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            label = "JA" if all(_is_japanese(c) for c in run) else "?"
            atoms.append(f"<{label}:{len(run)}>")
            run.clear()

    for char in line:
        if char.isascii():
            flush()
            atoms.append(" " if char < " " or char == "\x7f" else char)
        else:
            run.append(char)
    flush()
    return atoms


def _wrap(atoms: list[str], width: int) -> list[list[str]]:
    lines: list[list[str]] = []
    current: list[str] = []
    length = 0
    for atom in atoms:
        if current and length + len(atom) > width:
            lines.append(current)
            current, length = [], 0
        current.append(atom)
        length += len(atom)
    if current:
        lines.append(current)
    return lines


def to_ascii(text: str) -> str:
    return "".join(_tokenize(unicodedata.normalize("NFC", text)))


def summarize(text: str, width: int = 20, max_lines: int = 6) -> list[str]:
    text = unicodedata.normalize("NFC", text)
    lines: list[list[str]] = []
    for raw in text.split("\n"):
        line = raw.rstrip("\r").replace("\t", " ")
        if not line:
            continue
        lines.extend(_wrap(_tokenize(line), width))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        # Drop whole atoms so a marker such as "<JA:12>" is never cut in half.
        while last and len("".join(last)) + len(ELLIPSIS) > width:
            last.pop()
        last.append(ELLIPSIS)
    return ["".join(line) for line in lines]


class DevinCliAdapter(AgentAdapter):
    name = "devin-cli"

    def parse(self, event: dict) -> ApprovalRequest | None:
        if not isinstance(event, dict):
            return None
        tool_name = event.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            return None
        session_id = event.get("session_id")
        session = str(session_id)[:128] if session_id else "unknown"
        tool_input = event.get("tool_input")
        source = ""
        if isinstance(tool_input, dict):
            for key in ("command", "file_path"):
                value = tool_input.get(key)
                if isinstance(value, str) and value:
                    source = value
                    break
        return ApprovalRequest(
            agent=self.name,
            session_id=session,
            title=to_ascii(tool_name)[:256],
            lines=summarize(source) if source else [],
        )

    def render(self, result: Result) -> tuple[str, int]:
        if result == "approved":
            return json.dumps({"decision": "approve"}, separators=(",", ":")), 0
        if result == "rejected":
            return (
                json.dumps(
                    {"decision": "block", "reason": "Rejected on M5StickC"},
                    separators=(",", ":"),
                ),
                0,
            )
        return "", 0
