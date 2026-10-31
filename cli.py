#!/usr/bin/env python3
# Author: Tim Harrison
# Created: 2026-10-21
# Updated: 2026-10-23

"""Shared command line for the pack's local dev tools (repo-only, never ships)."""

import argparse

GAME_CHOICES = ("1", "2", "3", "all", "spyro1", "spyro2", "spyro3")


def game_parser(description: str) -> argparse.ArgumentParser:
    """Return a parser carrying the shared --game option."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--game", default="all", choices=GAME_CHOICES)
    return parser
