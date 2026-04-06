"""Atenex Nova — Domain value objects: identifiers and enums."""

from enum import Enum
from typing import NewType
from uuid import uuid4


# --- Typed identifiers ---
CollectionId = NewType("CollectionId", str)
DocumentId = NewType("DocumentId", str)
ChunkId = NewType("ChunkId", str)
PropositionId = NewType("PropositionId", str)
QueryId = NewType("QueryId", str)
AnswerId = NewType("AnswerId", str)
CitationId = NewType("CitationId", str)
JobId = NewType("JobId", str)
NodeId = NewType("NodeId", str)


def new_id() -> str:
    """Generate a new UUID4 string id."""
    return str(uuid4())


# --- Document status state machine ---
class DocumentStatus(str, Enum):
    """Document lifecycle states.

    Transitions:
        registered → parsed → normalized → segmented → embedded → indexed → ready
        Any state → failed
    """

    REGISTERED = "registered"
    PARSED = "parsed"
    NORMALIZED = "normalized"
    SEGMENTED = "segmented"
    EMBEDDED = "embedded"
    INDEXED = "indexed"
    READY = "ready"
    FAILED = "failed"


# Valid state transitions
VALID_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.REGISTERED: {DocumentStatus.PARSED, DocumentStatus.FAILED},
    DocumentStatus.PARSED: {DocumentStatus.NORMALIZED, DocumentStatus.FAILED},
    DocumentStatus.NORMALIZED: {DocumentStatus.SEGMENTED, DocumentStatus.FAILED},
    DocumentStatus.SEGMENTED: {DocumentStatus.EMBEDDED, DocumentStatus.FAILED},
    DocumentStatus.EMBEDDED: {DocumentStatus.INDEXED, DocumentStatus.FAILED},
    DocumentStatus.INDEXED: {DocumentStatus.READY, DocumentStatus.FAILED},
    DocumentStatus.READY: {DocumentStatus.REGISTERED},  # re-ingest
    DocumentStatus.FAILED: {DocumentStatus.REGISTERED},  # retry
}


# --- Job status ---
class JobStatus(str, Enum):
    """Job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Types of background jobs."""

    PARSE_DOCUMENT = "parse_document"
    NORMALIZE_DOCUMENT = "normalize_document"
    SEGMENT_DOCUMENT = "segment_document"
    EXTRACT_PROPOSITIONS = "extract_propositions"
    EMBED_CHUNKS = "embed_chunks"
    EMBED_PROPOSITIONS = "embed_propositions"
    EMBED_SUMMARIES = "embed_summaries"
    INDEX_CHUNKS = "index_chunks"
    INDEX_VISUAL_PAGES = "index_visual_pages"
    BUILD_GRAPH = "build_graph"
    RUN_BENCHMARK = "run_benchmark"
    REBUILD_COLLECTION = "rebuild_collection"


# --- Query modes ---
class QueryMode(str, Enum):
    """Query routing modes."""

    AUTO = "auto"
    EXACT = "exact"
    FACTUAL_LOCAL = "factual_local"
    MULTI_HOP = "multi_hop"
    GLOBAL = "global"
    ARGUMENTATIVE = "argumentative"
    VISUAL = "visual"


# --- Query intent ---
class QueryIntent(str, Enum):
    """Classified query intents."""

    EXACT = "exact"
    FACTUAL = "factual"
    COMPARATIVE = "comparative"
    EXPLANATORY = "explanatory"
    ARGUMENTATIVE = "argumentative"
    GLOBAL = "global"
    VISUAL = "visual"


# --- Answer plan types ---
class AnswerPlanType(str, Enum):
    """Answer synthesis plan types."""

    DIRECT_ANSWER = "direct_answer"
    HIERARCHICAL_SYNTHESIS = "hierarchical_synthesis"
    GLOBAL_SYNTHESIS = "global_synthesis"
    ARGUMENT_SYNTHESIS = "argument_synthesis"
    VISUAL_GROUNDED_SYNTHESIS = "visual_grounded_synthesis"


# --- Answer verdict ---
class AnswerVerdict(str, Enum):
    """Verification verdict for answers."""

    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    CONFLICTING = "conflicting"


# --- Document node types ---
class NodeType(str, Enum):
    """Types of document structural nodes."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    TABLE = "table"
    TABLE_ROW = "table_row"
    TABLE_CELL = "table_cell"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    IMAGE = "image"
    FORMULA = "formula"
    CODE = "code"
    PAGE_BREAK = "page_break"


# --- Proposition kinds ---
class PropositionKind(str, Enum):
    """Types of extracted propositions."""

    FACT = "fact"
    DEFINITION = "definition"
    PROCEDURE = "procedure"
    RULE = "rule"
    CAUSAL = "causal"
    COMPARISON = "comparison"


# --- Relation types ---
class RelationType(str, Enum):
    """Types of semantic relations in the proposition graph."""

    MENTIONS = "mentions"
    DEFINES = "defines"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    ELABORATES = "elaborates"
    APPEARS_IN = "appears_in"
