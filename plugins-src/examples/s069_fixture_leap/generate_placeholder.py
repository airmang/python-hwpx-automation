#!/usr/bin/env python3
"""Reproduce the visible placeholder defect used by the installed fixture demo."""
from pathlib import Path

from PIL import Image, ImageDraw


path = Path(__file__).with_name("page-2-placeholder.png")
image = Image.open(path).convert("RGB")
draw = ImageDraw.Draw(image)
draw.rectangle((190, 720, 1010, 850), outline=(210, 80, 20), width=8)
draw.text((230, 765), "REMOVE SAMPLE TEXT", fill=(210, 80, 20))
image.save(path, format="PNG", optimize=False, compress_level=9)
