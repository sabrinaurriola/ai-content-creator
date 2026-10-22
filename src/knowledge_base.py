"""Embed the Ironhack docs once, then find the most relevant chunks for a request.

Only secondary documents are indexed. The consultant's own files (primary) are small
and injected whole into the prompt (see rag_decision.md), so they are never searched.
"""
import hashlib
import json

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from document_processor import KB_DIR, chunk_for_rag, load_knowledge_base

load_dotenv(KB_DIR.parent / ".env", override=True)                                 # reads .env (the key is never printed)
client = OpenAI()                               # uses OPENAI_API_KEY from .env
EMBED_MODEL = "text-embedding-3-small"
CACHE_FILE = KB_DIR.parent / "data" / "kb_embeddings.json"


# ---------- 1. Text -> numbers ----------
def embed(texts):
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return np.array([item.embedding for item in response.data])


# ---------- 2. Build the index once, then reuse it ----------
def _fingerprint(chunks):
    """Changes whenever a secondary document changes, so the cache is rebuilt."""
    raw = json.dumps([EMBED_MODEL, chunks], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_index(pieces=None, force=False):
    """Return {"chunks", "vectors"} for the secondary documents (cached in data/)."""
    pieces = load_knowledge_base() if pieces is None else pieces
    chunks = chunk_for_rag([p for p in pieces if p["source"] == "secondary"])
    fingerprint = _fingerprint(chunks)

    if CACHE_FILE.exists() and not force:
        data = json.loads(CACHE_FILE.read_text())
        if data.get("fingerprint") == fingerprint:
            return {"chunks": data["chunks"], "vectors": np.array(data["vectors"])}

    vectors = embed([f'{c["heading"]}\n{c["text"]}' for c in chunks]) if chunks else np.zeros((0, 1))
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(
        {"model": EMBED_MODEL, "fingerprint": fingerprint,
         "chunks": chunks, "vectors": vectors.tolist()}))
    return {"chunks": chunks, "vectors": vectors}


# ---------- 3. Find the best chunks for a question ----------
def search(index, query, k=3, min_score=0.3):
    """Top-k research chunks for the query, each with its similarity score."""
    chunks, vectors = index["chunks"], index["vectors"]
    if not chunks:
        return []
    q = embed([query])[0]
    scores = vectors @ q / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(q))
    best = np.argsort(scores)[::-1][:k]
    return [{**chunks[i], "score": float(scores[i])}
            for i in best if scores[i] >= min_score]


if __name__ == "__main__":
    index = build_index()
    print(f"📚 Index: {len(index['chunks'])} chunks, {index['vectors'].shape[1]} numbers each")

    questions = [
        "What will students learn about the EU AI Act?",
        "Does the bootcamp cover RAG and AI agents?",
        "Best pizza in Berlin",                 # should find nothing useful
    ]
    for q in questions:
        print(f"\n🔎 {q}")
        results = search(index, q)
        if not results:
            print("   (no chunk above the threshold)")
        for r in results:
            print(f'   {r["score"]:.2f} | {r["file"]} | {r["heading"]}')
