"""Embed the Ironhack docs once, then find the most relevant chunks for a request."""
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
def build_index(force=False):
    if CACHE_FILE.exists() and not force:
        data = json.loads(CACHE_FILE.read_text())
        return data["chunks"], np.array(data["vectors"])

    pieces = load_knowledge_base()
    secondary = [p for p in pieces if p["source"] == "secondary"]
    chunks = chunk_for_rag(secondary)
    vectors = embed([f'{c["heading"]}\n{c["text"]}' for c in chunks])

    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(
        {"model": EMBED_MODEL, "chunks": chunks, "vectors": vectors.tolist()}))
    return chunks, vectors


# ---------- 3. Find the best chunks for a question ----------
def search(query, chunks, vectors, top_k=3, min_score=0.3):
    q = embed([query])[0]
    scores = vectors @ q / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(q))
    best = np.argsort(scores)[::-1][:top_k]
    return [{**chunks[i], "score": float(scores[i])}
            for i in best if scores[i] >= min_score]


# ---------- 4. The consultant profile is injected whole, not searched ----------
def get_profile_context(pieces):
    return "\n\n".join(f'### {p["heading"]}\n{p["text"]}'
                       for p in pieces if p["source"] == "primary")


if __name__ == "__main__":
    chunks, vectors = build_index()
    print(f"📚 Index: {len(chunks)} chunks, {vectors.shape[1]} numbers each")

    questions = [
        "What will students learn about the EU AI Act?",
        "Does the bootcamp cover RAG and AI agents?",
        "Best pizza in Berlin",                 # should find nothing useful
    ]
    for q in questions:
        print(f"\n🔎 {q}")
        results = search(q, chunks, vectors)
        if not results:
            print("   (no chunk above the threshold)")
        for r in results:
            print(f'   {r["score"]:.2f} | {r["file"]} | {r["heading"]}')