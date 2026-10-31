"""Trace agent-visible inputs to their source records."""
from pydantic import BaseModel, ConfigDict, Field


class ItemProvenance(BaseModel):
    """Source path, zero-based sample index, and permitted fields used."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    source_file: str
    record_index: int = Field(ge=0)
    fields_used: list[str]
