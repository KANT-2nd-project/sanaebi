"""Checkout root shared by tests, independent of discovery depth."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
