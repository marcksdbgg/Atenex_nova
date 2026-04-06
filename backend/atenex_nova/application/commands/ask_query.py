"""Ask query command."""

from dataclasses import dataclass


@dataclass(slots=True)
class AskQueryCommand:
    collection_id: str
    query: str
    mode: str = "auto"
    generation_profile: str = "standard"