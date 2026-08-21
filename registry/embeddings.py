import hashlib
import math
import os
import re
from typing import Protocol

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI


class Embedder(Protocol):
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


# Known output dimensions for common Azure OpenAI embedding deployments. Avoids an extra
# "dimension probe" embeddings.create call (~1.1s) purely to discover vector length.
KNOWN_EMBEDDING_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class HashingEmbedder:
    dimensions = 128

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class AzureOpenAIEmbedder:
    def __init__(self) -> None:
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        self.deployment = os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"]
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        self.client = AzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=api_version,
        )
        known_dimensions = KNOWN_EMBEDDING_DIMENSIONS.get(self.deployment)
        if known_dimensions is not None:
            self.dimensions = known_dimensions
        else:
            # Fall back to a live probe only for unrecognized deployments.
            probe = self.client.embeddings.create(model=self.deployment, input="dimension probe")
            self.dimensions = len(probe.data[0].embedding)

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(model=self.deployment, input=text)
        return response.data[0].embedding


def create_embedder() -> Embedder:
    if os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"):
        return AzureOpenAIEmbedder()
    return HashingEmbedder()

