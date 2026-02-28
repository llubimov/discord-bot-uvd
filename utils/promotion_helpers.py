# -*- coding: utf-8 -*-
import re


def required_count_from_text(requirement_text: str) -> int:
    if not (requirement_text or "").strip():
        return 1
    text = requirement_text.strip()
    m_шт = re.search(r"→\s*(\d+)\s*шт\.?", text, re.IGNORECASE)
    if m_шт:
        return int(m_шт.group(1))
    if re.search(r"\d+\s*минут", text, re.IGNORECASE) or re.search(r"\d+\s*мин\b", text, re.IGNORECASE):
        return 1
    m = re.search(r"→\s*(\d+)\s*(?:шт\.?|минут)", text, re.IGNORECASE)
    return int(m.group(1)) if m else 1


def parse_thanks_lines(text: str) -> list[list]:
    result = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            n = int(parts[0])
        except ValueError:
            continue
        if n <= 0:
            continue
        url = parts[1].strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        result.append([n, url])
    return result


async def send_long(thread, body: str, header: str = ""):
    if not thread:
        return
    max_len = 1990  # Discord content limit 2000
    if header:
        body = header + "\n" + body
    lines = body.split("\n")
    chunk = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if line_len > max_len:
            if chunk:
                await thread.send("\n".join(chunk))
                chunk = []
                current_len = 0
            rest = line
            while len(rest) > max_len:
                await thread.send(rest[:max_len])
                rest = rest[max_len:]
            if rest:
                chunk.append(rest)
                current_len = len(rest) + 1
            continue
        if current_len + line_len > max_len and chunk:
            await thread.send("\n".join(chunk))
            chunk = []
            current_len = 0
        chunk.append(line)
        current_len += line_len
    if chunk:
        text = "\n".join(chunk)
        if len(text) > max_len:
            await thread.send(text[:max_len])
            await send_long(thread, text[max_len:].lstrip("\n"))
        else:
            await thread.send(text)


def normalize_thanks(thanks_links) -> list[list]:
    if not thanks_links:
        return []
    return [[int(p), str(u)] for p, u in thanks_links]
