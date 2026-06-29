from abc import ABC, abstractmethod


class DiagramProvider(ABC):
    name = "provider"

    @abstractmethod
    def search(self, query, *, limit=8):
        """Return reusable DiagramCandidate objects for a search query."""


class ProviderRegistry:
    def __init__(self, providers=None):
        self.providers = list(providers or [])

    def add(self, provider):
        self.providers.append(provider)

    def search(self, queries, *, limit_per_query=8):
        for provider in self.providers:
            for query in queries:
                yield from provider.search(query, limit=limit_per_query)
