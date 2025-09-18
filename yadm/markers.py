"""Marker classes representing special attribute states."""

from __future__ import annotations


class Marker:
    """Base marker type used for sentinel values."""


class AttributeNotSet(Marker):
    """Marker for attributes that have not been set."""


class NotLoaded(Marker):
    """Marker for attributes that have not been loaded."""
