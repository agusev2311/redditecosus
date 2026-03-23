from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from PIL import Image, ImageOps, UnidentifiedImageError

from ..extensions import db
from ..models import MediaItem
from .storage import materialize_storage_path

DEFAULT_SIMILARITY_THRESHOLD = 88


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


def compute_perceptual_hash(source_path) -> str | None:
    try:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image).convert("L")
            return f"{_difference_hash(image):016x}{_average_hash(image):016x}"
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _compare_hashes(left: str | None, right: str | None) -> int | None:
    if not left or not right or len(left) != len(right):
        return None
    total_bits = len(left) * 4
    distance = (int(left, 16) ^ int(right, 16)).bit_count()
    return round(((total_bits - distance) / total_bits) * 100)


def _band_keys(hash_hex: str) -> list[str]:
    band_size = 4
    keys = []
    for phase in (0, 2):
        for index, offset in enumerate(range(phase, len(hash_hex) - band_size + 1, band_size)):
            keys.append(f"{phase}:{index}:{hash_hex[offset:offset + band_size]}")
    return keys


def ensure_perceptual_hashes(items: Iterable[MediaItem]) -> None:
    cache: dict[int, str | None] = {}
    changed = False

    for item in items:
        canonical = item.canonical_root
        if canonical.media_type != "image":
            continue

        if canonical.id not in cache:
            hash_value = canonical.perceptual_hash
            if not hash_value:
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
    parents = list(range(len(candidates)))
    ranks = [0] * len(candidates)

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left == root_right:
            return
        if ranks[root_left] < ranks[root_right]:
            root_left, root_right = root_right, root_left
        parents[root_right] = root_left
        if ranks[root_left] == ranks[root_right]:
            ranks[root_left] += 1

    band_map: dict[str, list[int]] = defaultdict(list)
    compared_pairs: set[tuple[int, int]] = set()
    pair_similarity: dict[tuple[int, int], int] = {}

    for current_index, item in enumerate(candidates):
        for band_key in _band_keys(item.perceptual_hash):
            for other_index in band_map[band_key]:
                pair = (other_index, current_index)
                if pair in compared_pairs:
                    continue
                compared_pairs.add(pair)
                similarity = _compare_hashes(
                    candidates[other_index].perceptual_hash,
                    item.perceptual_hash,
                )
                if similarity is None:
                    continue
                if similarity >= threshold_percent:
                    union(other_index, current_index)
                    pair_similarity[pair] = similarity
            band_map[band_key].append(current_index)

    grouped_indexes: dict[int, list[int]] = defaultdict(list)
    for index in range(len(candidates)):
        grouped_indexes[find(index)].append(index)

    groups = []
    for indexes in grouped_indexes.values():
        if len(indexes) < 2:
            continue

        best_similarity = {candidates[index].id: 100 for index in indexes}
        pair_scores = []
        for left_position, left_index in enumerate(indexes):
            for right_index in indexes[left_position + 1 :]:
                ordered = tuple(sorted((left_index, right_index)))
                similarity = pair_similarity.get(ordered)
                if similarity is None:
                    similarity = _compare_hashes(
                        candidates[left_index].perceptual_hash,
                        candidates[right_index].perceptual_hash,
                    )
                if similarity is None:
                    continue
                pair_scores.append(similarity)
                best_similarity[candidates[left_index].id] = max(
                    best_similarity[candidates[left_index].id],
                    similarity,
                )
                best_similarity[candidates[right_index].id] = max(
                    best_similarity[candidates[right_index].id],
                    similarity,
                )

        group_items = [candidates[index] for index in indexes]
        representative = group_items[0]
        groups.append(
            {
                "key": f"similar-{representative.id}",
                "count": len(group_items),
                "similarityPercent": round(sum(pair_scores) / len(pair_scores)) if pair_scores else 100,
                "items": [
                    {
                        "item": item,
                        "matchPercent": best_similarity.get(item.id, 100),
                    }
                    for item in group_items
                ],
            }
        )

    groups.sort(key=lambda group: (-group["count"], -group["similarityPercent"], group["key"]))
    return groups[:max_groups]


def similarity_percent(left: MediaItem, right: MediaItem) -> int | None:
    return _compare_hashes(left.perceptual_hash, right.perceptual_hash)
