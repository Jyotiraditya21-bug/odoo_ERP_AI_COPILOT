import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.security.injection import detect_prompt_injection


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    source: str
    chunk: int
    score: float


def _embedding(text: str, dimensions: int = 384) -> list[float]:
    """Offline-safe hashing embedding. Chroma persists/searches these supplied vectors."""
    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        position = int.from_bytes(digest[:4], "big") % dimensions
        vector[position] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _chunks(text: str, size: int = 700, overlap: int = 100) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    result: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > size:
            result.append(current)
            current = current[-overlap:] + "\n\n" + paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        result.append(current)
    return result


class PolicyIndex:
    def __init__(self, policy_dir: Path, persist_path: Path, threshold: float = 0.18):
        self.policy_dir = policy_dir
        self.persist_path = persist_path
        self.threshold = threshold
        self._memory: list[RetrievedChunk] = []
        self._collection = None

    def build(self) -> None:
        documents: list[tuple[str, int, str]] = []
        for path in sorted(self.policy_dir.glob("*.md")):
            for chunk_number, text in enumerate(_chunks(path.read_text(encoding="utf-8")), 1):
                # Poisoned passages are excluded from the index, not obeyed.
                if not detect_prompt_injection(text):
                    documents.append((path.name, chunk_number, text))
        self._memory = [
            RetrievedChunk(text, source, chunk, 0.0) for source, chunk, text in documents
        ]
        try:
            import chromadb

            self.persist_path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=str(self.persist_path),
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                "company_policies", metadata={"hnsw:space": "cosine"}
            )
            if documents:
                ids = [f"{source}:{chunk}" for source, chunk, _ in documents]
                self._collection.upsert(
                    ids=ids,
                    documents=[text for _, _, text in documents],
                    embeddings=[_embedding(text) for _, _, text in documents],
                    metadatas=[
                        {"source": source, "chunk": chunk} for source, chunk, _ in documents
                    ],
                )
        except (ImportError, OSError, ValueError):
            self._collection = None

    def search(self, query: str, limit: int = 3) -> list[RetrievedChunk]:
        if self._collection is not None:
            result = self._collection.query(query_embeddings=[_embedding(query)], n_results=limit)
            chunks = []
            for text, metadata, distance in zip(
                result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True
            ):
                score = 1.0 - float(distance)
                if score >= self.threshold:
                    chunks.append(
                        RetrievedChunk(text, str(metadata["source"]), int(metadata["chunk"]), score)
                    )
            return chunks
        query_vector = _embedding(query)
        scored = []
        for item in self._memory:
            score = sum(a * b for a, b in zip(query_vector, _embedding(item.text), strict=True))
            if score >= self.threshold:
                scored.append(RetrievedChunk(item.text, item.source, item.chunk, score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]
