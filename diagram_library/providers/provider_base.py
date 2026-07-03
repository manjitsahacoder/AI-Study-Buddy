from abc import ABC, abstractmethod


class DiagramProvider(ABC):
    """Common interface for diagram search providers."""

    name = "provider"

    def find(self, queries, *, topic="", subject="", limit_per_query=8):
        """Return reusable DiagramCandidate objects for the current request."""
        for query in queries:
            yield from self.search(query, limit=limit_per_query)

    @abstractmethod
    def search(self, query, *, limit=8):
        """Return reusable DiagramCandidate objects for a single search query."""

    def fetch(self, candidate, cache_dir, topic):
        """Store a candidate in the local diagram cache and return the cached path."""
        from diagram_library.storage import download_and_store

        return download_and_store(candidate, cache_dir, topic)

    def metadata(self, candidate):
        """Return provider-specific metadata for future provider replacements."""
        return {}


class ProviderRegistry:
    def __init__(self, providers=None):
        self.providers = list(providers or [])

    def add(self, provider):
        self.providers.append(provider)

    def search(self, queries, *, limit_per_query=8):
        for provider in self.providers:
            for query in queries:
                yield from provider.search(query, limit=limit_per_query)

    def find_by_provider(self, queries, *, topic="", subject="", limit_per_query=8):
        for provider in self.providers:
            finder = getattr(provider, "find", None)
            if finder:
                candidates = finder(
                    queries,
                    topic=topic,
                    subject=subject,
                    limit_per_query=limit_per_query,
                )
            else:
                candidates = (
                    candidate
                    for query in queries
                    for candidate in provider.search(query, limit=limit_per_query)
                )
            yield provider, candidates
