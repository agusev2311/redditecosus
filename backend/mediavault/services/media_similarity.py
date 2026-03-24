from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from ..extensions import db
from ..models import MediaItem
from .storage import materialize_storage_path

DEFAULT_SIMILARITY_THRESHOLD = 85
EXHAUSTIVE_COMPARE_LIMIT = 5000
FINGERPRINT_VERSION = "02"
GLOBAL_HASH_HEX_LENGTH = 16
GRADIENT_HASH_HEX_LENGTH = 16
LOCAL_TILE_COLUMNS = 4
LOCAL_TILE_ROWS = 4
LOCAL_TILE_HASH_WIDTH = 6
LOCAL_TILE_HASH_HEIGHT = 4
LOCAL_TILE_BITS = LOCAL_TILE_HASH_WIDTH * LOCAL_TILE_HASH_HEIGHT
LOCAL_TILE_HEX_WIDTH = LOCAL_TILE_BITS // 4
LOCAL_TILE_COUNT = LOCAL_TILE_COLUMNS * LOCAL_TILE_ROWS
LOCAL_TILE_HEX_LENGTH = LOCAL_TILE_COUNT * LOCAL_TILE_HEX_WIDTH
COLOR_VECTOR_HEX_LENGTH = 6
DETAIL_LEVEL_HEX_LENGTH = 2
EXPECTED_PERCEPTUAL_HASH_LENGTH = (
    len(FINGERPRINT_VERSION)
    + GLOBAL_HASH_HEX_LENGTH
    + GRADIENT_HASH_HEX_LENGTH
    + LOCAL_TILE_HEX_LENGTH
    + COLOR_VECTOR_HEX_LENGTH
    + DETAIL_LEVEL_HEX_LENGTH
)
NORMALIZED_IMAGE_SIZE = 96
GLOBAL_HASH_IMAGE_SIZE = 32
GLOBAL_HASH_LOW_FREQUENCY_SIZE = 8
LOCAL_WEAK_TILE_SIMILARITY = 58
LOW_DETAIL_LEVEL = 26


@dataclass(frozen=True, slots=True)
class PreparedFingerprint:
    global_value: int
    gradient_value: int
    tile_values: tuple[int, ...]
    color_vector: tuple[int, int, int]
    detail_level: int
    structure_hex: str


@dataclass(frozen=True, slots=True)
class SimilarityMetrics:
    overall: int
    structure: int
    global_similarity: int
    gradient_similarity: int
    local_average: int
    local_floor: int
    color_similarity: int
    detail_similarity: int
    weak_tile_count: int
    detail_low: bool


def _fit_to_square(image: Image.Image, size: int) -> Image.Image:
    fitted = image.convert("RGB")
    fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), (127, 127, 127))
    offset = ((size - fitted.width) // 2, (size - fitted.height) // 2)
    canvas.paste(fitted, offset)
    return canvas


def _normalized_luminance(image: Image.Image, size: int = NORMALIZED_IMAGE_SIZE) -> Image.Image:
    grayscale = ImageOps.grayscale(_fit_to_square(image, size))
    grayscale = ImageOps.autocontrast(grayscale)
    return grayscale.filter(ImageFilter.GaussianBlur(radius=0.6))


def _difference_hash(image: Image.Image, width: int = 8, height: int = 8) -> int:
    reduced = image.resize((width + 1, height), Image.Resampling.LANCZOS)
    pixels = list(reduced.getdata())
    value = 0
    stride = width + 1
    for row in range(height):
        offset = row * stride
        for column in range(width):
            value = (value << 1) | int(pixels[offset + column] >= pixels[offset + column + 1])
    return value


@lru_cache(maxsize=8)
def _dct_basis(size: int) -> tuple[tuple[tuple[float, ...], ...], tuple[float, ...]]:
    basis = tuple(
        tuple(math.cos((math.pi / size) * (index + 0.5) * frequency) for index in range(size))
        for frequency in range(size)
    )
    factors = (math.sqrt(1 / size),) + tuple(math.sqrt(2 / size) for _ in range(size - 1))
    return basis, factors


def _dct_1d(values: list[float]) -> list[float]:
    basis, factors = _dct_basis(len(values))
    return [
        factors[frequency]
        * sum(value * basis[frequency][index] for index, value in enumerate(values))
        for frequency in range(len(values))
    ]


def _dct_2d(matrix: list[list[float]]) -> list[list[float]]:
    transformed_rows = [_dct_1d(row) for row in matrix]
    width = len(transformed_rows[0])
    columns = [
        [transformed_rows[row_index][column_index] for row_index in range(len(transformed_rows))]
        for column_index in range(width)
    ]
    transformed_columns = [_dct_1d(column) for column in columns]
    return [
        [transformed_columns[column_index][row_index] for column_index in range(width)]
        for row_index in range(len(transformed_rows))
    ]


def _perceptual_hash(image: Image.Image) -> int:
    reduced = image.resize((GLOBAL_HASH_IMAGE_SIZE, GLOBAL_HASH_IMAGE_SIZE), Image.Resampling.LANCZOS)
    pixels = list(reduced.getdata())
    matrix = [
        [float(pixels[(row * GLOBAL_HASH_IMAGE_SIZE) + column]) for column in range(GLOBAL_HASH_IMAGE_SIZE)]
        for row in range(GLOBAL_HASH_IMAGE_SIZE)
    ]
    transformed = _dct_2d(matrix)
    coefficients = [
        transformed[row][column]
        for row in range(GLOBAL_HASH_LOW_FREQUENCY_SIZE)
        for column in range(GLOBAL_HASH_LOW_FREQUENCY_SIZE)
    ]
    reference_values = coefficients[1:] or coefficients
    reference = sorted(reference_values)[len(reference_values) // 2] if reference_values else 0.0
    value = 0
    for coefficient in coefficients:
        value = (value << 1) | int(coefficient >= reference)
    return value


def _local_tile_hashes(image: Image.Image) -> tuple[int, ...]:
    hashes = []
    tile_width = image.width // LOCAL_TILE_COLUMNS
    tile_height = image.height // LOCAL_TILE_ROWS
    for row in range(LOCAL_TILE_ROWS):
        for column in range(LOCAL_TILE_COLUMNS):
            left = column * tile_width
            upper = row * tile_height
            right = image.width if column == LOCAL_TILE_COLUMNS - 1 else left + tile_width
            lower = image.height if row == LOCAL_TILE_ROWS - 1 else upper + tile_height
            hashes.append(
                _difference_hash(
                    image.crop((left, upper, right, lower)),
                    width=LOCAL_TILE_HASH_WIDTH,
                    height=LOCAL_TILE_HASH_HEIGHT,
                )
            )
    return tuple(hashes)


def _normalized_color_vector(image: Image.Image) -> tuple[int, int, int]:
    reduced = _fit_to_square(image, 16).resize((4, 4), Image.Resampling.LANCZOS)
    pixels = list(reduced.getdata())
    red = sum(pixel[0] for pixel in pixels)
    green = sum(pixel[1] for pixel in pixels)
    blue = sum(pixel[2] for pixel in pixels)
    total = max(red + green + blue, 1)
    return (
        round((red / total) * 255),
        round((green / total) * 255),
        round((blue / total) * 255),
    )


def _detail_level(image: Image.Image) -> int:
    reduced = image.resize((24, 24), Image.Resampling.LANCZOS)
    pixels = list(reduced.getdata())
    width, height = reduced.size
    total_delta = 0
    samples = 0
    for row in range(height):
        offset = row * width
        for column in range(width):
            current = pixels[offset + column]
            if column + 1 < width:
                total_delta += abs(current - pixels[offset + column + 1])
                samples += 1
            if row + 1 < height:
                total_delta += abs(current - pixels[offset + width + column])
                samples += 1
    return max(0, min(255, round(total_delta / samples))) if samples else 0


def _serialize_fingerprint(
    global_hash: int,
    gradient_hash: int,
    tile_hashes: tuple[int, ...],
    color_vector: tuple[int, int, int],
    detail_level: int,
) -> str:
    return (
        FINGERPRINT_VERSION
        + f"{global_hash:0{GLOBAL_HASH_HEX_LENGTH}x}"
        + f"{gradient_hash:0{GRADIENT_HASH_HEX_LENGTH}x}"
        + "".join(f"{tile_hash:0{LOCAL_TILE_HEX_WIDTH}x}" for tile_hash in tile_hashes)
        + "".join(f"{channel:02x}" for channel in color_vector)
        + f"{detail_level:02x}"
    )


def compute_perceptual_hash(source_path) -> str | None:
    try:
        with Image.open(source_path) as image:
            image = ImageOps.exif_transpose(image)
            normalized = _normalized_luminance(image)
            return _serialize_fingerprint(
                global_hash=_perceptual_hash(normalized),
                gradient_hash=_difference_hash(
                    normalized.resize((GLOBAL_HASH_IMAGE_SIZE, GLOBAL_HASH_IMAGE_SIZE), Image.Resampling.LANCZOS)
                ),
                tile_hashes=_local_tile_hashes(normalized),
                color_vector=_normalized_color_vector(image),
                detail_level=_detail_level(normalized),
            )
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def _component_similarity(left_value: int, right_value: int, total_bits: int) -> int:
    distance = (left_value ^ right_value).bit_count()
    return round(((total_bits - distance) / total_bits) * 100)


def _color_similarity(left_color: tuple[int, int, int], right_color: tuple[int, int, int]) -> int:
    distance = sum(abs(left - right) for left, right in zip(left_color, right_color))
    max_distance = 510
    return round(((max_distance - min(distance, max_distance)) / max_distance) * 100)


def _detail_similarity(left_value: int, right_value: int) -> int:
    return round(((255 - abs(left_value - right_value)) / 255) * 100)


def _prepare_hash(hash_hex: str | None) -> PreparedFingerprint | None:
    if not hash_hex or len(hash_hex) != EXPECTED_PERCEPTUAL_HASH_LENGTH:
        return None
    if not hash_hex.startswith(FINGERPRINT_VERSION):
        return None

    cursor = len(FINGERPRINT_VERSION)
    global_hex = hash_hex[cursor : cursor + GLOBAL_HASH_HEX_LENGTH]
    cursor += GLOBAL_HASH_HEX_LENGTH
    gradient_hex = hash_hex[cursor : cursor + GRADIENT_HASH_HEX_LENGTH]
    cursor += GRADIENT_HASH_HEX_LENGTH
    tile_hex = hash_hex[cursor : cursor + LOCAL_TILE_HEX_LENGTH]
    cursor += LOCAL_TILE_HEX_LENGTH
    color_hex = hash_hex[cursor : cursor + COLOR_VECTOR_HEX_LENGTH]
    cursor += COLOR_VECTOR_HEX_LENGTH
    detail_hex = hash_hex[cursor : cursor + DETAIL_LEVEL_HEX_LENGTH]

    try:
        tile_values = tuple(
            int(tile_hex[index : index + LOCAL_TILE_HEX_WIDTH], 16)
            for index in range(0, len(tile_hex), LOCAL_TILE_HEX_WIDTH)
        )
        color_values = tuple(
            int(color_hex[index : index + 2], 16)
            for index in range(0, len(color_hex), 2)
        )
        if len(tile_values) != LOCAL_TILE_COUNT or len(color_values) != 3:
            return None
        return PreparedFingerprint(
            global_value=int(global_hex, 16),
            gradient_value=int(gradient_hex, 16),
            tile_values=tile_values,
            color_vector=(int(color_values[0]), int(color_values[1]), int(color_values[2])),
            detail_level=int(detail_hex, 16),
            structure_hex=global_hex + gradient_hex + tile_hex,
        )
    except ValueError:
        return None


def _compare_prepared_hashes(left_hash: PreparedFingerprint, right_hash: PreparedFingerprint) -> SimilarityMetrics:
    global_similarity = _component_similarity(left_hash.global_value, right_hash.global_value, 64)
    gradient_similarity = _component_similarity(left_hash.gradient_value, right_hash.gradient_value, 64)
    local_similarities = [
        _component_similarity(left_tile, right_tile, LOCAL_TILE_BITS)
        for left_tile, right_tile in zip(left_hash.tile_values, right_hash.tile_values)
    ]
    local_average = round(sum(local_similarities) / len(local_similarities))
    weakest_tiles = sorted(local_similarities)[: max(1, len(local_similarities) // 4)]
    local_floor = round(sum(weakest_tiles) / len(weakest_tiles))
    weak_tile_count = sum(1 for similarity in local_similarities if similarity < LOCAL_WEAK_TILE_SIMILARITY)
    color_similarity = _color_similarity(left_hash.color_vector, right_hash.color_vector)
    detail_similarity = _detail_similarity(left_hash.detail_level, right_hash.detail_level)
    structure = round(
        (global_similarity * 0.30)
        + (gradient_similarity * 0.25)
        + (local_average * 0.30)
        + (local_floor * 0.15)
    )
    detail_low = ((left_hash.detail_level + right_hash.detail_level) / 2) < LOW_DETAIL_LEVEL
    if detail_low:
        overall = round((structure * 0.82) + (color_similarity * 0.14) + (detail_similarity * 0.04))
    else:
        overall = round((structure * 0.95) + (color_similarity * 0.03) + (detail_similarity * 0.02))
    return SimilarityMetrics(
        overall=overall,
        structure=structure,
        global_similarity=global_similarity,
        gradient_similarity=gradient_similarity,
        local_average=local_average,
        local_floor=local_floor,
        color_similarity=color_similarity,
        detail_similarity=detail_similarity,
        weak_tile_count=weak_tile_count,
        detail_low=detail_low,
    )


def compare_perceptual_hashes(left: str | None, right: str | None) -> int | None:
    prepared_left = _prepare_hash(left)
    prepared_right = _prepare_hash(right)
    if not prepared_left or not prepared_right:
        return None
    return _compare_prepared_hashes(prepared_left, prepared_right).overall


def _passes_similarity_threshold(metrics: SimilarityMetrics, threshold_percent: int) -> bool:
    if metrics.overall < threshold_percent:
        return False
    if metrics.local_average < max(58, threshold_percent - 9):
        return False
    if metrics.local_floor < max(46, threshold_percent - 24):
        return False
    weak_tile_limit = 5 if threshold_percent <= 82 else 4 if threshold_percent <= 90 else 3
    if metrics.weak_tile_count > weak_tile_limit:
        return False
    if (
        metrics.global_similarity < max(50, threshold_percent - 18)
        and metrics.gradient_similarity < max(50, threshold_percent - 18)
    ):
        return False
    if metrics.detail_low and metrics.color_similarity < max(40, threshold_percent - 30):
        return False
    return True


def _band_keys(hash_hex: str) -> list[str]:
    prepared = _prepare_hash(hash_hex)
    if not prepared:
        return []

    structure_hex = prepared.structure_hex
    band_size = 3
    keys = []
    for phase in range(band_size):
        for index, offset in enumerate(range(phase, len(structure_hex) - band_size + 1, band_size)):
            keys.append(f"{phase}:{index}:{structure_hex[offset:offset + band_size]}")
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
            if (
                not hash_value
                or len(hash_value) != EXPECTED_PERCEPTUAL_HASH_LENGTH
                or _prepare_hash(hash_value) is None
            ):
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
    raw_candidates = [
        (item, _prepare_hash(item.perceptual_hash))
        for item in items
        if item.media_type == "image" and item.perceptual_hash
    ]
    candidates = [item for item, prepared in raw_candidates if prepared]
    prepared_hashes = [prepared for _, prepared in raw_candidates if prepared]
    if len(candidates) < 2:
        return []

    candidates.sort(key=lambda item: (item.created_at, item.id))
    paired = sorted(
        zip(candidates, prepared_hashes, strict=True),
        key=lambda entry: (entry[0].created_at, entry[0].id),
    )
    candidates = [item for item, _ in paired]
    prepared_hashes = [prepared for _, prepared in paired]

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
            for right_index in range(left_index + 1, len(candidates)):
                metrics = _compare_prepared_hashes(
                    prepared_hashes[left_index],
                    prepared_hashes[right_index],
                )
                if _passes_similarity_threshold(metrics, threshold_percent):
                    record_similarity(left_index, right_index, metrics.overall)
    else:
        band_map: dict[str, list[int]] = defaultdict(list)
        for current_index, item in enumerate(candidates):
            for band_key in _band_keys(item.perceptual_hash):
                for other_index in band_map[band_key]:
                    pair = (other_index, current_index)
                    if pair in compared_pairs:
                        continue
                    compared_pairs.add(pair)
                    metrics = _compare_prepared_hashes(
                        prepared_hashes[other_index],
                        prepared_hashes[current_index],
                    )
                    if _passes_similarity_threshold(metrics, threshold_percent):
                        record_similarity(other_index, current_index, metrics.overall)
                band_map[band_key].append(current_index)

    if not pair_similarity:
        return []

    def neighbor_average(index: int) -> float:
        scores = list(adjacency[index].values())
        return sum(scores) / len(scores) if scores else 0.0

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
    return compare_perceptual_hashes(left.perceptual_hash, right.perceptual_hash)
