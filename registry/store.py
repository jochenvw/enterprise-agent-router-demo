import json
import math
import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from azure.core.credentials import AzureKeyCredential, TokenCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from registry.models import CapabilityDocument


class CapabilityStore(Protocol):
    def replace(self, documents: list[CapabilityDocument]) -> None: ...

    def search(
        self, query: str, embedding: list[float], top: int = 5
    ) -> list[tuple[CapabilityDocument, float]]: ...


class LocalCapabilityStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).with_name("index.json")

    def replace(self, documents: list[CapabilityDocument]) -> None:
        payload = [document.model_dump() for document in documents]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def search(
        self, query: str, embedding: list[float], top: int = 5
    ) -> list[tuple[CapabilityDocument, float]]:
        if not self.path.exists():
            raise RuntimeError("Capability index is missing. Run 'uv run index-agents' first.")
        documents = [
            CapabilityDocument.model_validate(item)
            for item in json.loads(self.path.read_text(encoding="utf-8"))
        ]
        query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        results = []
        for document in documents:
            lexical = _lexical_score(query_tokens, document)
            cosine = sum(a * b for a, b in zip(embedding, document.embedding, strict=False))
            score = 0.65 * lexical + 0.35 * cosine + _ownership_rerank(query, document)
            results.append((document, score))
        return sorted(results, key=lambda item: item[1], reverse=True)[:top]


class AzureSearchCapabilityStore:
    def __init__(self, dimensions: int, credential: TokenCredential | None = None) -> None:
        endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
        self.index_name = os.getenv("AZURE_SEARCH_INDEX_NAME", "agent-capabilities")
        search_key = os.getenv("AZURE_SEARCH_ADMIN_KEY")
        credential = AzureKeyCredential(search_key) if search_key else credential or DefaultAzureCredential()
        self.index_client = SearchIndexClient(endpoint, credential)
        self.search_client = SearchClient(endpoint, self.index_name, credential)
        self.dimensions = dimensions

    def replace(self, documents: list[CapabilityDocument]) -> None:
        with suppress(ResourceNotFoundError):
            self.index_client.delete_index(self.index_name)
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="agent_id", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="agent_name", type=SearchFieldDataType.String),
            SimpleField(name="skill_id", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="skill_name", type=SearchFieldDataType.String),
            SearchableField(name="description", type=SearchFieldDataType.String),
            SearchField(
                name="examples",
                type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                searchable=True,
            ),
            SearchField(
                name="owns",
                type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                searchable=True,
            ),
            SearchField(
                name="does_not_own",
                type=SearchFieldDataType.Collection(SearchFieldDataType.String),
                searchable=True,
            ),
            SimpleField(name="endpoint", type=SearchFieldDataType.String),
            SimpleField(name="base_url", type=SearchFieldDataType.String),
            SimpleField(name="agent_card_json", type=SearchFieldDataType.String),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self.dimensions,
                vector_search_profile_name="capability-vector-profile",
            ),
        ]
        index = SearchIndex(
            name=self.index_name,
            fields=fields,
            vector_search=VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(name="capability-hnsw")],
                profiles=[
                    VectorSearchProfile(
                        name="capability-vector-profile",
                        algorithm_configuration_name="capability-hnsw",
                    )
                ],
            ),
        )
        self.index_client.create_or_update_index(index)
        self.search_client.upload_documents(
            [document.model_dump(exclude={"search_score"}) for document in documents]
        )

    def search(
        self, query: str, embedding: list[float], top: int = 5
    ) -> list[tuple[CapabilityDocument, float]]:
        # Retrieve a wider candidate pool than `top` before reranking: the ownership/boundary
        # rerank can promote a document that Azure AI Search's raw hybrid score ranked below
        # `top`, so truncating before rerank could silently drop the correct agent. See
        # docs/perf-journal.md, Experiment 11.
        fetch_top = max(top * 4, 20)
        vector_query = VectorizedQuery(
            vector=embedding,
            k_nearest_neighbors=fetch_top,
            fields="embedding",
        )
        results = self.search_client.search(
            search_text=query,
            search_fields=["agent_name", "skill_name", "description", "examples", "owns"],
            vector_queries=[vector_query],
            select=[
                "id",
                "agent_id",
                "agent_name",
                "skill_id",
                "skill_name",
                "description",
                "examples",
                "owns",
                "does_not_own",
                "endpoint",
                "base_url",
                "agent_card_json",
            ],
            top=fetch_top,
        )
        output = []
        for result in results:
            payload = {key: value for key, value in result.items() if not key.startswith("@search")}
            payload["embedding"] = []
            score = float(result.get("@search.score", 0.0))
            payload["search_score"] = score
            output.append((CapabilityDocument.model_validate(payload), score))
        maximum = max((score for _, score in output), default=1.0) or 1.0
        reranked = [
            (document, math.tanh(score / maximum) + _ownership_rerank(query, document))
            for document, score in output
        ]
        return sorted(reranked, key=lambda item: item[1], reverse=True)[:top]


def create_store(dimensions: int) -> CapabilityStore:
    if os.getenv("AZURE_SEARCH_ENDPOINT"):
        return AzureSearchCapabilityStore(dimensions)
    return LocalCapabilityStore()


def _lexical_score(query_tokens: set[str], document: CapabilityDocument) -> float:
    text_tokens = set(re.findall(r"[a-z0-9]+", document.searchable_text.lower()))
    return len(query_tokens & text_tokens) / max(len(query_tokens), 1)


def _ownership_rerank(query: str, document: CapabilityDocument) -> float:
    normalized_query = query.lower()
    ownership_boost = sum(0.25 for phrase in document.owns if phrase.lower() in normalized_query)
    boundary_penalty = sum(0.2 for phrase in document.does_not_own if phrase.lower() in normalized_query)
    return ownership_boost - boundary_penalty
