from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

from mediavault.services.media_similarity import (
    DEFAULT_SIMILARITY_THRESHOLD,
    build_similar_duplicate_groups,
    compare_perceptual_hashes,
    compute_perceptual_hash,
)


@dataclass
class FakeMediaItem:
    id: int
    perceptual_hash: str
    created_at: datetime
    media_type: str = "image"
    is_duplicate: bool = False


def _hash_image(image: Image.Image, *, filename: str, image_format: str, **save_kwargs) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / filename
        image.save(path, format=image_format, **save_kwargs)
        hash_value = compute_perceptual_hash(path)
    if not hash_value:
        raise AssertionError("Fingerprint was not computed for synthetic test image")
    return hash_value


def _build_reference_image() -> Image.Image:
    image = Image.new("RGB", (640, 480), (28, 31, 38))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 616, 456), radius=24, fill=(235, 236, 240))
    draw.rectangle((54, 54, 586, 176), fill=(85, 126, 204))
    draw.ellipse((76, 214, 250, 390), fill=(234, 123, 81))
    draw.rounded_rectangle((300, 206, 566, 402), radius=18, fill=(88, 178, 122))
    draw.polygon(((160, 118), (300, 58), (432, 132), (306, 192)), fill=(246, 218, 104))
    draw.line((62, 404, 578, 92), fill=(22, 22, 30), width=12)
    draw.line((74, 102, 554, 420), fill=(247, 248, 252), width=6)
    draw.arc((336, 224, 526, 394), start=10, end=320, fill=(24, 34, 56), width=10)
    return image


def _build_color_corrected_variant() -> Image.Image:
    base = _build_reference_image()
    variant = ImageEnhance.Color(base).enhance(1.75)
    variant = ImageEnhance.Contrast(variant).enhance(1.18)
    variant = ImageEnhance.Brightness(variant).enhance(0.94)
    tint = Image.new("RGB", variant.size, (22, 6, 38))
    variant = Image.blend(variant, tint, 0.12)
    return variant.resize((560, 420), Image.Resampling.LANCZOS).resize(base.size, Image.Resampling.LANCZOS)


def _build_insert_variant(name: str) -> Image.Image:
    insert = Image.new("RGB", (420, 300), (246, 246, 242))
    draw = ImageDraw.Draw(insert)
    if name == "warm":
        draw.rectangle((0, 0, 420, 300), fill=(243, 233, 210))
        for offset in range(-180, 420, 36):
            draw.line((offset, 300, offset + 220, 0), fill=(214, 112, 88), width=18)
        draw.ellipse((120, 48, 302, 230), fill=(250, 208, 110))
        draw.rectangle((176, 160, 350, 260), fill=(92, 132, 76))
    else:
        draw.rectangle((0, 0, 420, 300), fill=(214, 230, 242))
        for row in range(0, 300, 40):
            for column in range(0, 420, 40):
                if (row + column) // 40 % 2 == 0:
                    draw.rectangle((column, row, column + 40, row + 40), fill=(88, 132, 198))
        draw.polygon(((78, 248), (216, 46), (352, 248)), fill=(246, 118, 92))
        draw.ellipse((258, 62, 386, 190), fill=(250, 244, 246))
    return insert


def _build_meme_variant(name: str) -> Image.Image:
    image = Image.new("RGB", (640, 640), (248, 248, 246))
    draw = ImageDraw.Draw(image)
    draw.rectangle((42, 42, 598, 118), fill=(22, 22, 22))
    draw.rectangle((42, 522, 598, 598), fill=(22, 22, 22))
    draw.rounded_rectangle((80, 142, 560, 498), radius=28, fill=(232, 232, 232), outline=(34, 34, 34), width=6)
    image.paste(_build_insert_variant(name), (110, 170))
    draw.rectangle((110, 170, 530, 470), outline=(34, 34, 34), width=5)
    draw.line((126, 486, 514, 486), fill=(160, 160, 160), width=8)
    return image


class MediaSimilarityTests(unittest.TestCase):
    def test_same_image_with_color_correction_stays_similar(self) -> None:
        left_hash = _hash_image(_build_reference_image(), filename="original.png", image_format="PNG")
        right_hash = _hash_image(
            _build_color_corrected_variant(),
            filename="corrected.jpg",
            image_format="JPEG",
            quality=76,
            optimize=True,
        )

        similarity = compare_perceptual_hashes(left_hash, right_hash)

        self.assertIsNotNone(similarity)
        self.assertGreaterEqual(similarity, DEFAULT_SIMILARITY_THRESHOLD)

    def test_same_meme_template_with_different_inserted_picture_is_not_grouped(self) -> None:
        left_hash = _hash_image(_build_meme_variant("warm"), filename="meme-a.png", image_format="PNG")
        right_hash = _hash_image(_build_meme_variant("cool"), filename="meme-b.png", image_format="PNG")

        similarity = compare_perceptual_hashes(left_hash, right_hash)

        self.assertIsNotNone(similarity)
        self.assertLess(similarity, DEFAULT_SIMILARITY_THRESHOLD)

    def test_group_builder_keeps_only_true_visual_duplicates(self) -> None:
        start = datetime(2026, 3, 24, 10, 0, 0)
        items = [
            FakeMediaItem(
                id=1,
                perceptual_hash=_hash_image(_build_reference_image(), filename="original.png", image_format="PNG"),
                created_at=start,
            ),
            FakeMediaItem(
                id=2,
                perceptual_hash=_hash_image(
                    _build_color_corrected_variant(),
                    filename="corrected.jpg",
                    image_format="JPEG",
                    quality=74,
                ),
                created_at=start + timedelta(seconds=1),
                is_duplicate=True,
            ),
            FakeMediaItem(
                id=3,
                perceptual_hash=_hash_image(_build_meme_variant("warm"), filename="meme-a.png", image_format="PNG"),
                created_at=start + timedelta(seconds=2),
            ),
            FakeMediaItem(
                id=4,
                perceptual_hash=_hash_image(_build_meme_variant("cool"), filename="meme-b.png", image_format="PNG"),
                created_at=start + timedelta(seconds=3),
            ),
        ]

        groups = build_similar_duplicate_groups(
            items,
            threshold_percent=DEFAULT_SIMILARITY_THRESHOLD,
            max_groups=10,
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual([entry["item"].id for entry in groups[0]["items"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
