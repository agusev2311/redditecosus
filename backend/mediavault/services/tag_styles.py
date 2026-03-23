from __future__ import annotations

import json
import re

DEFAULT_GRADIENT_ANGLE = 135
DEFAULT_GRADIENT_COLORS = ["#7c3aed", "#10b981"]
MAX_GRADIENT_COLORS = 10

HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def normalize_color(value: str | None, fallback: str | None = None) -> str | None:
    candidate = (value or "").strip()
    if candidate and HEX_COLOR_RE.match(candidate):
        return candidate.lower()
    return fallback.lower() if fallback else None


def _coerce_color_list(raw_colors) -> list[str]:
    if raw_colors is None:
        return []
    if isinstance(raw_colors, str):
        raw_colors = raw_colors.strip()
        if not raw_colors:
            return []
        if raw_colors.startswith("["):
            try:
                decoded = json.loads(raw_colors)
            except json.JSONDecodeError:
                decoded = []
            if isinstance(decoded, list):
                return [str(item) for item in decoded]
        return [chunk.strip() for chunk in raw_colors.split(",")]
    if isinstance(raw_colors, (list, tuple)):
        return [str(item) for item in raw_colors]
    return []


def normalize_gradient_colors(
    raw_colors,
    fallback_start: str | None = None,
    fallback_end: str | None = None,
) -> list[str]:
    start = normalize_color(fallback_start, DEFAULT_GRADIENT_COLORS[0]) or DEFAULT_GRADIENT_COLORS[0]
    end = normalize_color(fallback_end, DEFAULT_GRADIENT_COLORS[1]) or DEFAULT_GRADIENT_COLORS[1]

    colors = [
        color
        for color in (normalize_color(candidate) for candidate in _coerce_color_list(raw_colors))
        if color
    ][:MAX_GRADIENT_COLORS]

    if not colors:
        colors = [start, end]
    elif len(colors) == 1:
        colors.append(end if colors[0] != end else start)

    return colors


def encode_gradient_colors(colors: list[str]) -> str:
    return json.dumps(colors, ensure_ascii=False)


def decode_gradient_colors(
    raw_colors,
    fallback_start: str | None = None,
    fallback_end: str | None = None,
) -> list[str]:
    return normalize_gradient_colors(raw_colors, fallback_start=fallback_start, fallback_end=fallback_end)


def normalize_gradient_angle(raw_angle) -> int:
    try:
        value = int(raw_angle)
    except (TypeError, ValueError):
        return DEFAULT_GRADIENT_ANGLE
    return max(0, min(360, value))
