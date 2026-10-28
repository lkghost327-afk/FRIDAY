"""Explicit, bounded UIA text preview. Never captures pixels or reads edit values."""
from collections import deque


def accessible_text(window, limit=6000, max_nodes=300):
    pending = deque([(window, 0)])
    seen, lines, length, visited = set(), [], 0, 0
    while pending and visited < max_nodes and length < limit:
        node, depth = pending.popleft()
        visited += 1
        try:
            # Fail closed if a provider cannot state whether this subtree is private.
            if node.element_info.element.CurrentIsPassword or not node.is_visible():
                continue
            kind = node.element_info.control_type
            # Values in forms are deliberately excluded, even non-password fields.
            if kind == 'Edit':
                continue
            if kind in {'Text', 'Document', 'ListItem', 'Header', 'Hyperlink'}:
                value = str(node.element_info.name or '').strip()
                if value and value not in seen:
                    seen.add(value)
                    value = value[:limit - length]
                    lines.append(value)
                    length += len(value) + 1
            if depth < 10:
                pending.extend((child, depth + 1) for child in node.children()[:max(0, max_nodes - visited - len(pending))])
        except Exception:
            continue  # Broken providers and unknown privacy state are not readable.
    suffix = '\n[Preview limited to accessible text; it may be incomplete.]'
    return ('\n'.join(lines) if lines else 'No readable accessible text found.') + suffix
