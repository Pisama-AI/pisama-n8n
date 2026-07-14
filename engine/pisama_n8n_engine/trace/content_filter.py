# VENDORED from the pisama monorepo by scripts/extract_from_monorepo.py — do not edit here.
"""Content filtering for ingestion modes.

Provides trace_only stripping of content fields from state_delta dictionaries,
preserving only structural/metadata fields needed for monitoring.
"""

from typing import Optional

VALID_INGESTION_MODES = {"full", "trace_only"}
DEFAULT_INGESTION_MODE = "full"


def resolve_ingestion_mode(
    entity_mode: Optional[str],
    instance_mode: Optional[str],
) -> str:
    """Resolve effective ingestion mode from entity override and instance default.

    Priority: entity_mode > instance_mode > "full"
    """
    if entity_mode and entity_mode in VALID_INGESTION_MODES:
        return entity_mode
    if instance_mode and instance_mode in VALID_INGESTION_MODES:
        return instance_mode
    return DEFAULT_INGESTION_MODE


def strip_content_fields(state_delta: dict, content_keys: list[str]) -> dict:
    """Remove content fields from state_delta, keeping only structural metadata.

    Sets content keys to None (rather than removing them) to preserve key
    presence for schema consistency and to signal intentional stripping
    to downstream detection algorithms.
    """
    result = {}
    for key, value in state_delta.items():
        if key in content_keys:
            result[key] = None
        else:
            result[key] = value
    return result
