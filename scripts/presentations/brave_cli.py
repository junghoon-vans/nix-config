#!/usr/bin/env python3
"""Run OfficeCLI's Chromium screenshot/DOM requests through the installed Brave app."""

import argparse
import os
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright


def main():
    executable = sys.argv.pop(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--dump-dom", action="store_true")
    parser.add_argument("--window-size", default="1600,1200")
    parser.add_argument("--force-device-scale-factor", type=float, default=1)
    parser.add_argument("--virtual-time-budget", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=30000)
    parser.add_argument("--default-background-color")
    parser.add_argument("url")
    args, browser_args = parser.parse_known_args()
    if not os.access(executable, os.X_OK):
        parser.error(f"Brave Browser is required at {executable}; no fallback browser will be downloaded")
    if not args.screenshot and not args.dump_dom:
        parser.error("OfficeCLI must request a screenshot or DOM output")
    width, height = map(int, args.window_size.split(","))
    with sync_playwright() as playwright:
        with playwright.chromium.launch(
            executable_path=executable, headless=True, args=browser_args,
            timeout=args.timeout,
        ) as brave:
            page = brave.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=args.force_device_scale_factor,
            )
            # OfficeCLI clip requests report their measured bounds through console output.
            page.on("console", lambda message: print(message.text, file=sys.stderr))
            page.goto(args.url, wait_until="load", timeout=args.timeout)
            page.evaluate("document.fonts.ready")
            if args.virtual_time_budget:
                page.wait_for_timeout(args.virtual_time_budget)
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                if args.default_background_color:
                    rgba = args.default_background_color
                    if len(rgba) != 8:
                        parser.error("background color must have eight RGBA hex digits")
                    red, green, blue, alpha = (int(rgba[i:i + 2], 16) for i in range(0, 8, 2))
                    page.context.new_cdp_session(page).send(
                        "Emulation.setDefaultBackgroundColorOverride",
                        {"color": {"r": red, "g": green, "b": blue, "a": alpha / 255}},
                    )
                page.screenshot(
                    path=str(args.screenshot),
                    omit_background=args.default_background_color == "00000000",
                )
            if args.dump_dom:
                print(page.content())


if __name__ == "__main__":
    main()
