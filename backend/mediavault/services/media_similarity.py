from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from PIL import Image, ImageOps, UnidentifiedImageError

from ..extensions import db
from ..models import MediaItem
from .storage import materialize_storage_path

DEFAULT_SIMILARITY_THRESHOLD = 90
EXHAUSTIVE_COMPARE_LIMIT = 6000
EXPECTED_PERCEPTUAL_HASH_LENGTH = 44


def _average_hash(image: Image.Image) -> int:
    reduced = image.resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(reduced.getdata())
    average = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= average)
    return value


def _difference_hash(image: Image.Image) -> int:
    reduced = image.resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(reduced.getdata())
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column] >= pixels[offset + column + 1])
    return value


def _color_hash(image: Image.Image) -> int:
    reduced = image.resize((4, 4), Image.Resampling.LANCZOS).convert("RGB")
    pixels = list(reduced.getdata())
    average_red = sum(pixel[0] for pixel in pixels) / len(pixels)
    average_green = sum(pixel[1] for pixel in pixels) / len(pixels)
    average_blue = sum(pixel[2] for pixel in pixels) / len(pixels)

    value = 0
    for red, green, blue in pixels:
        value = (value << 1) | int(red >= average_red)
        value = (value << 1) | int(green >= average_green)
        value = (value << 1) | int(blue >= average_blue)
    return value


def compute_perceptual_hash(source_path) -> str | None:
    try:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            grayscale = image.convert("L")
            return (
                f"{_difference_hash(grayscale):016x}"
                f"{_average_hash(grayscale):016x}"
                f"{_color_hash(image):012x}"
            )
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _compare_hashes(left: str | None, right: str | None) -> int | None:
    if not left or not right or len(left) != len(right):
        return None
    total_bits = len(left) * 4
    distance = (int(left, 16) ^ int(right, 16)).bit_count()
    return round(((total_bits - distance) / total_bits) * 100)


def _band_keys(hash_hex: str) -> list[str]:
    band_size = 2
    keys = []
    for phase in (0, 1):
        for index, offset in enumerate(range(phase, len(hash_hex) - band_size + 1, band_size)):
            keys.append(f"{phase}:{index}:{hash_hex[offset:offset + band_size]}")
    return keys


def _compare_hash_ints(left_hash: int, right_hash: int, total_bits: int) -> int:
    distance = (left_hash ^ right_hash).bit_count()
    return round(((total_bits - distance) / total_bits) * 100)


def ensure_perceptual_hashes(items: Iterable[MediaItem]) -> None:
    cache: dict[int, str | None] = {}
    changed = False

    for item in items:
        canonical = item.canonical_root
        if canonical.media_type != "image":
            continue

        if canonical.id not in cache:
            hash_value = canonical.perceptual_hash
            if not hash_value or len(hash_value) != EXPECTED_PERCEPTUAL_HASH_LENGTH:
                source_relative = canonical.preview_path or canonical.storage_path
                with materialize_storage_path(source_relative, canonical.is_encrypted) as source_path:
                    hash_value = compute_perceptual_hash(source_path)
                canonical.perceptual_hash = hash_value
                changed = True
            cache[canonical.id] = hash_value

        if item.perceptual_hash != cache[canonical.id]:
            item.perceptual_hash = cache[canonical.id]
            changed = True

    if changed:
        db.session.commit()


def build_similar_duplicate_groups(
    items: Iterable[MediaItem],
    threshold_percent: int = DEFAULT_SIMILARITY_THRESHOLD,
    max_groups: int = 100,
) -> list[dict]:
    threshold_percent = max(50, min(100, int(threshold_percent)))
    candidates = [item for item in items if item.media_type == "image" and item.perceptual_hash]
    if len(candidates) < 2:
        return []

    candidates.sort(key=lambda item: (item.created_at, item.id))
    hash_ints = [int(item.perceptual_hash, 16) for item in candidates]
    total_bits = len(candidates[0].perceptual_hash) * 4

    pair_similarity: dict[tuple[int, int], int] = {}
    adjacency: list[dict[int, int]] = [dict() for _ in candidates]
    compared_pairs: set[tuple[int, int]] = set()

    def record_similarity(left_index: int, right_index: int, similarity: int) -> None:
        ordered = tuple(sorted((left_index, right_index)))
        pair_similarity[ordered] = similarity
        adjacency[left_index][right_index] = similarity
        adjacency[right_index][left_index] = similarity

    if len(candidates) <= EXHAUSTIVE_COMPARE_LIMIT:
        for left_index in range(len(candidates)):
            left_hash = hash_ints[left_index]
            for right_index in range(left_index + 1, len(candidates)):
                similarity = _compare_hash_ints(left_hash, hash_ints[right_index], total_bits)
                if similarity >= threshold_percent:
                    record_similarity(left_index, right_index, similarity)
    else:
        band_map: dict[str, list[int]] = defaultdict(list)
        for current_index, item in enumerate(candidates):
            for band_key in _band_keys(item.perceptual_hash):
                for other_index in band_map[band_key]:
                    pair = (other_index, current_index)
                    if pair in compared_pairs:
                        continue
                    compared_pairs.add(pair)
                    similarity = _compare_hash_ints(
                        hash_ints[other_index],
                        hash_ints[current_index],
                        total_bits,
                    )
                    if similarity >= threshold_percent:
                        record_similarity(other_index, current_index, similarity)
                band_map[band_key].append(current_index)

    if not pair_similarity:
        return []

    def neighbor_average(index: int) -> float:
        scores = list(adjacency[index].values())
        return sum(scores) / len(scores) if scores else 0

    ordered_indexes = sorted(
        range(len(candidates)),
        key=lambda index: (
            -len(adjacency[index]),
            -neighbor_average(index),
            candidates[index].is_duplicate,
            candidates[index].created_at,
            candidates[index].id,
        ),
    )

    groups = []
    used_indexes: set[int] = set()

    for anchor_index in ordered_indexes:
        if anchor_index in used_indexes:
            continue

        neighbor_entries = [
            (neighbor_index, similarity)
            for neighbor_index, similarity in adjacency[anchor_index].items()
            if neighbor_index not in used_indexes
        ]
        if not neighbor_entries:
            continue

        neighbor_entries.sort(
            key=lambda entry: (
                -entry[1],
                candidates[entry[0]].is_duplicate,
                candidates[entry[0]].created_at,
                candidates[entry[0]].id,
            )
        )

        representative = candidates[anchor_index]
        member_indexes = [anchor_index]
        member_scores = {representative.id: 100}
        similarity_scores = []

        for neighbor_index, similarity in neighbor_entries:
            member_indexes.append(neighbor_index)
            member_scores[candidates[neighbor_index].id] = similarity
            similarity_scores.append(similarity)

        if len(member_indexes) < 2:
            continue

        used_indexes.update(member_indexes)
        ordered_group_items = [representative] + [candidates[index] for index, _ in neighbor_entries]
        groups.append(
            {
                "key": f"similar-{representative.id}",
                "count": len(ordered_group_items),
                "similarityPercent": round(sum(similarity_scores) / len(similarity_scores))
                if similarity_scores
                else 100,
                "items": [
                    {
                        "item": item,
                        "matchPercent": member_scores.get(item.id, 100),
                    }
                    for item in ordered_group_items
                ],
            }
        )

    groups.sort(key=lambda group: (-group["count"], -group["similarityPercent"], group["key"]))
    return groups[:max_groups]


def similarity_percent(left: MediaItem, right: MediaItem) -> int | None:
    return _compare_hashes(left.perceptual_hash, right.perceptual_hash)
