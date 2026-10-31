"""Render dependency pins as data, never as Markdown supplied by upstream."""

import html
from urllib.parse import quote, urlsplit


def cell(value):
    if value is None:
        return "Not present / metadata unavailable"
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(f"\\u{ord(char):04x}" if ord(char) < 32 and char != "\n" else char for char in text)
    text = html.escape(text, quote=True)
    # Entities preserve visible data without allowing table, code, or link injection.
    for character in "|`[]*_~\\":
        text = text.replace(character, f"&#{ord(character)};")
    return text.replace("\n", "<br>")


def render_table(rows):
    lines = [
        "| Dependency | Previous version / pin | Next version / pin | Change | Compare |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        url = row.get("compare")
        link = "—"
        try:
            target = urlsplit(url) if url else None
        except ValueError:
            target = None
        if target and target.scheme == "https" and target.netloc == "github.com":
            link = f"[Compare]({quote(url, safe='/:.%-_~')})"
        lines.append("| " + " | ".join([
            cell(row["dependency"]), cell(row.get("previous")), cell(row.get("next")),
            cell(row.get("change", "Updated")), link,
        ]) + " |")
    if not rows:
        lines.append("| — | — | — | No dependency pin changes | — |")
    return "\n".join(lines)
