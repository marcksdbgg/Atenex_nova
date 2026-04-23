"""Atenex Nova — Domain value objects: standardized metadata schemas."""

from typing import NotRequired, TypedDict


class BoundingBox(TypedDict, total=False):
    """Standard bounding box representation."""
    l: float
    t: float
    r: float
    b: float


class StandardMetadata(TypedDict, total=False):
    """Standard metadata contract for all memory nodes and chunks."""
    source_format: NotRequired[str]
    source_path: NotRequired[str]
    document_title: NotRequired[str]
    page_numbers: NotRequired[list[int]]
    bboxes: NotRequired[list[BoundingBox]]
    heading_path: NotRequired[list[str]]
    node_types: NotRequired[list[str]]
    source_text: NotRequired[str]
    summary: NotRequired[str]
    relation: NotRequired[str]
