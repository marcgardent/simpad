#!/usr/bin/env python3
"""
SimPulse Plugin Integrity and Contract Verification CLI.

Checks all built-in (and optionally external) plugins:
- Syntax & importability (detects broken relative/absolute imports)
- Contract conformance (SimPulsePlugin, ITabProvider, ITelemetrySubscriber, IHudWidgetProvider)
- Widget and configuration instantiation without runtime crashes
- Returns exit code 0 on success, 1 on any failure (suitable for CI/CD / pre-commit).
"""

import os
import sys
import argparse
import time
from pathlib import Path

# Ensure offscreen Qt platform for headless CI / terminals
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Ensure repository root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QSize

from simpulse_sdk import (
    SimPulsePlugin,
    PluginState,
    ITabProvider,
    ITelemetrySubscriber,
    IHudWidgetProvider,
    HudSlot,
    ChannelRequirement,
)
from simpulse.plugins.manager import PluginManager
from simpulse.core.config import ConfigManager


def verify_plugins(search_paths: list[Path], verbose: bool = False) -> bool:
    app = QApplication.instance() or QApplication(["simpulse_plugin_checker"])
    cfg = ConfigManager()
    pm = PluginManager(cfg)

    print("=" * 70)
    print("🔍 SimPulse Plugin Integrity & Contract Checker")
    print("=" * 70)

    start_time = time.perf_counter()
    pm.discover_and_load(search_paths)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    has_errors = False

    # Check for load errors
    if pm.load_errors:
        has_errors = True
        print(f"\n❌ [CRITICAL] {len(pm.load_errors)} plugin(s) failed to load:\n")
        for path, err in pm.load_errors.items():
            print(f"  • File: {path}")
            print(f"    Error:\n{err}\n")

    # Check loaded plugins
    print(f"\n📦 Successfully loaded plugins ({len(pm.plugins)} found in {elapsed_ms:.1f}ms):")
    for pid, plugin in sorted(pm.plugins.items()):
        meta = plugin.metadata
        badges = []
        if isinstance(plugin, ITabProvider):
            badges.append("Tab")
        if isinstance(plugin, ITelemetrySubscriber):
            badges.append("Telemetry")
        if isinstance(plugin, IHudWidgetProvider):
            badges.append("HUD")

        badge_str = f"[{', '.join(badges)}]" if badges else "[Core]"
        print(f"  ✓ {meta.name} (v{meta.version}) {badge_str}")
        print(f"    ID: {pid}")

        # Contract checks
        try:
            if isinstance(plugin, ITabProvider):
                title = plugin.get_tab_title()
                assert isinstance(title, str) and title.strip(), "Empty tab title"
                widget = plugin.create_tab_widget()
                assert isinstance(widget, QWidget), "create_tab_widget must return QWidget"

            if isinstance(plugin, ITelemetrySubscriber):
                reqs = plugin.get_channel_requirements()
                assert isinstance(reqs, list), "Requirements must be a list"
                for r in reqs:
                    assert isinstance(r, ChannelRequirement), "Invalid ChannelRequirement"

            if isinstance(plugin, IHudWidgetProvider):
                slot = plugin.preferred_slot
                assert isinstance(slot, HudSlot), "Invalid HudSlot"
                sz = plugin.get_hud_size()
                assert isinstance(sz, QSize) and sz.width() > 0 and sz.height() > 0, "Invalid HUD size"

        except Exception as e:
            has_errors = True
            print(f"    ❌ Contract verification failed: {e}")

    print("\n" + "=" * 70)
    if has_errors:
        print("❌ STATUS: FAILED — Plugin validation errors detected!")
        print("=" * 70)
        return False
    else:
        print("✅ STATUS: PASSED — All plugins discovered and verified successfully.")
        print("=" * 70)
        return True


def main():
    parser = argparse.ArgumentParser(description="SimPulse Plugin Verification Tool")
    parser.add_argument(
        "--dir",
        "-d",
        type=Path,
        action="append",
        help="Additional plugin search directory (defaults to simpulse/builtin_plugins)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    search_paths = args.dir or [PROJECT_ROOT / "simpulse" / "builtin_plugins"]
    success = verify_plugins(search_paths, verbose=args.verbose)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
