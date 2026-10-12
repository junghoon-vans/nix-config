#!/usr/bin/env python3
"""Render an OfficeCLI PPTX preview to HTML, slide PNGs, PDF, and a contact sheet."""

import argparse
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright


def main():
    browser = sys.argv.pop(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("presentation", type=Path)
    parser.add_argument("output", type=Path, help="Directory for preview artifacts")
    args = parser.parse_args()
    presentation = args.presentation.resolve(strict=True)
    if presentation.suffix.lower() != ".pptx":
        parser.error("presentation must be a .pptx file")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    html = output / "preview.html"
    subprocess.run(
        ["officecli", "view", str(presentation), "html", "-o", str(html)], check=True
    )
    with sync_playwright() as playwright:
        with playwright.chromium.launch(executable_path=browser, headless=True) as chromium:
            page = chromium.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
            page.goto(html.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            slides = page.locator(".main .slide")
            count = slides.count()
            if not count:
                raise RuntimeError("OfficeCLI preview contains no slides")
            width, height = slides.first.evaluate(
                "el => [el.offsetWidth, el.offsetHeight]"
            )
            page.add_style_tag(content=f"""
                .sidebar, .sidebar-toggle, .toggle-zone, .page-counter,
                .file-title, .slide-label, .slide-notes {{ display: none !important; }}
                html, body {{ display: block !important; height: auto !important;
                    overflow: visible !important; background: white !important; }}
                .main {{ display: block !important; padding: 0 !important;
                    overflow: visible !important; }}
                .slide-container, .slide-wrapper {{ display: block !important;
                    width: {width}px !important; height: {height}px !important;
                    margin: 0 !important; padding: 0 !important; }}
                .slide-container {{ break-after: page; break-inside: avoid; }}
                .slide-container:last-child {{ break-after: auto; }}
                .slide {{ transform: none !important; box-shadow: none !important;
                    border-radius: 0 !important; }}
                @page {{ size: {width}px {height}px; margin: 0; }}
            """)
            for index in range(count):
                slides.nth(index).screenshot(path=str(output / f"slide-{index + 1:02d}.png"))
            page.pdf(path=str(output / "presentation.pdf"), print_background=True,
                     prefer_css_page_size=True, width=f"{width}px", height=f"{height}px",
                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    tile_width = 480
    tile_height = round(tile_width * height / width)
    columns = min(4, count)
    rows = (count + columns - 1) // columns
    with Image.new("RGB", (columns * tile_width, rows * tile_height), "#eeeeee") as sheet:
        for index in range(count):
            with Image.open(output / f"slide-{index + 1:02d}.png") as image:
                tile = ImageOps.contain(image.convert("RGB"), (tile_width, tile_height))
                sheet.paste(tile, ((index % columns) * tile_width, (index // columns) * tile_height))
        sheet.save(output / "contact-sheet.jpg", quality=90)
    print(f"Rendered {count} slides to {output}")


if __name__ == "__main__":
    main()
