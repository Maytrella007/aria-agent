"""
Channel-specific Markdown Formatters.

Converts ARIA's standard markdown output to each platform's native format.
ARIA generates standard markdown (from LLM output). Each platform has quirks:

- Telegram: Subset of Markdown (no headings, limited nesting)
- Discord: Full markdown, but no heading support in embeds, 2000 char limit
- Slack: mrkdwn format (different bold/italic/link syntax)

Usage:
    from core.channels.formatters import to_telegram_md, to_discord_md, to_slack_mrkdwn

    formatted = to_slack_mrkdwn("**bold** and _italic_ and [link](url)")
    # → "*bold* and _italic_ and <url|link>"
"""

import re


def to_telegram_md(text: str) -> str:
    """Convert standard markdown to Telegram MarkdownV2-safe format.

    Telegram's Markdown mode is fragile — unmatched markers break parsing.
    This converts to a safe subset:
    - **bold** → *bold*
    - Headings (# ) → *bold line*
    - Code blocks preserved
    - Links preserved
    """
    if not text:
        return text

    lines = text.split("\n")
    result = []

    for line in lines:
        # Convert headings to bold
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            result.append(f"*{heading_match.group(2)}*")
            continue

        # Convert **bold** to *bold* (Telegram uses single *)
        line = re.sub(r'\*\*(.+?)\*\*', r'*\1*', line)

        # Convert __bold__ to *bold*
        line = re.sub(r'__(.+?)__', r'*\1*', line)

        result.append(line)

    return "\n".join(result)


def to_discord_md(text: str) -> str:
    """Convert standard markdown to Discord-optimized format.

    Discord supports most standard markdown natively. Main conversions:
    - Headings → **bold** (Discord mobile doesn't render # well in some contexts)
    - Everything else passes through
    """
    if not text:
        return text

    lines = text.split("\n")
    result = []

    for line in lines:
        # Convert headings to bold (better rendering in embeds and mobile)
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            content = heading_match.group(2)
            if level <= 2:
                result.append(f"**{content}**")
            else:
                result.append(f"**{content}**")
            continue

        result.append(line)

    return "\n".join(result)


def to_slack_mrkdwn(text: str) -> str:
    """Convert standard markdown to Slack's mrkdwn format.

    Key differences from standard markdown:
    - **bold** → *bold*
    - *italic* or _italic_ → _italic_
    - ~~strike~~ → ~strike~
    - [text](url) → <url|text>
    - # heading → *heading*
    - > blockquote → > blockquote (same)
    - ```code``` → ```code``` (same)
    - `inline` → `inline` (same)
    """
    if not text:
        return text

    # Protect code blocks from conversion
    code_blocks = []
    def _save_code_block(match):
        code_blocks.append(match.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r'```[\s\S]*?```', _save_code_block, text)

    # Protect inline code
    inline_codes = []
    def _save_inline_code(match):
        inline_codes.append(match.group(0))
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    text = re.sub(r'`[^`]+`', _save_inline_code, text)

    # Convert links: [text](url) → <url|text>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', text)

    # Convert headings: # text → *text*
    text = re.sub(r'^(#{1,6})\s+(.+)$', r'*\2*', text, flags=re.MULTILINE)

    # Convert bold: **text** → *text*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    # Convert bold: __text__ → *text*
    text = re.sub(r'__(.+?)__', r'*\1*', text)

    # Convert strikethrough: ~~text~~ → ~text~
    text = re.sub(r'~~(.+?)~~', r'~\1~', text)

    # Restore code blocks
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{i}\x00", code)

    return text
