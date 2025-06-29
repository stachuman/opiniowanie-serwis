"""
Search configuration settings for court opinions system.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass
class SearchSettings:
    """Configuration for search functionality and result display."""
    
    # Context display settings
    show_context_by_default: bool = True
    context_length: Literal["short", "medium", "long"] = "medium"
    max_context_snippets_per_document: int = 3
    max_context_snippets_per_child: int = 2
    
    # Context snippet lengths (in characters)
    context_lengths = {
        "short": 100,
        "medium": 200,
        "long": 300
    }
    
    # Search behavior settings
    highlight_matches: bool = True
    show_match_types: bool = True  # Show icons for metadata/content/attachment matches
    show_fuzzy_scores: bool = True  # Show percentage match for fuzzy search
    
    # Performance settings
    max_search_results: int = 100
    context_cache_ttl: int = 300  # Cache context snippets for 5 minutes
    
    # Display settings
    collapsible_context: bool = True  # Allow expanding/collapsing context
    group_by_match_type: bool = False  # Group results by match type
    
    def get_context_length(self) -> int:
        """Get the configured context length in characters."""
        return self.context_lengths.get(self.context_length, 200)


# Global search settings instance
SEARCH_SETTINGS = SearchSettings()