#!/usr/bin/env python3
"""Build numbered contact sheets from rendered PDF page PNGs."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pages", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", type=int, default=5)
    parser.add_argument("--rows", type=int, default=4)
    args = parser.parse_args()

    files = sorted(args.pages.glob("page-*.png"))
    if not files:
        raise SystemExit(f"No rendered pages found in {args.pages}")
    args.output.mkdir(parents=True, exist_ok=True)
    per_sheet = args.columns * args.rows

    with Image.open(files[0]) as sample:
        width, height = sample.size
    label_height = 18

    for start in range(0, len(files), per_sheet):
        batch = files[start : start + per_sheet]
        sheet = Image.new(
            "RGB",
            (args.columns * width, args.rows * (height + label_height)),
            "white",
        )
        draw = ImageDraw.Draw(sheet)
        for offset, path in enumerate(batch):
            with Image.open(path) as page:
                page_rgb = page.convert("RGB")
            x = (offset % args.columns) * width
            y = (offset // args.columns) * (height + label_height)
            thumbnail = ImageOps.contain(page_rgb, (width, height))
            page_x = x + (width - thumbnail.width) // 2
            page_y = y + (height - thumbnail.height) // 2
            sheet.paste(thumbnail, (page_x, page_y))
            draw.text((x + 4, y + height + 2), str(start + offset + 1), fill="black")
        number = start // per_sheet + 1
        sheet.save(args.output / f"contact-{number:02d}.jpg", quality=88)

    print(f"pages={len(files)} sheets={(len(files) + per_sheet - 1) // per_sheet}")


if __name__ == "__main__":
    main()
