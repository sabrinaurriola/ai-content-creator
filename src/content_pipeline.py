"""
content_pipeline.py
AI Content Creator - The Manager

Responsibility:
Coordinate Files 1-4 through five stages:
    Document -> Monitor -> Brief -> Publish -> Iterate
and save every version (plus a generic baseline) for comparison.

Expected interface from knowledge_base.py (File 2):
    build_index(pieces)                          -> index
        (should reuse a saved index when documents have not changed)
    search(index, query, k, source, consultant)  -> list of chunk dicts
        each chunk: {"source", "file", "heading", "text", ...}
Until those exist, a simple keyword search below is used instead.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from document_processor import load_knowledge_base, chunk_for_rag
from prompt_templates import build_prompt
from llm_integration import generate_content

try:
    from knowledge_base import build_index, search
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "content"
MAX_BRAND_VOICE_CHARS = 3000
BRAND_SECTIONS = ["Header", "Summary", "Top Skills", "Experience", "Certifications"]


# --------------------------------------------------
# 0. TEMPORARY RETRIEVER (until knowledge_base.py is ready)
# --------------------------------------------------

def _words(text):
    return set(re.findall(r"[a-z]{3,}", text.lower()))


def _keyword_search(chunks, query, k=5, source=None, consultant=None):
    """Rank chunks by how many query words they share. Not semantic."""
    query_words = _words(query)
    candidates = [c for c in chunks
                  if (source is None or c["source"] == source)
                  and (consultant is None or c["file"] == consultant)]
    scored = [(len(query_words & _words(c["heading"] + " " + c["text"])), c)
              for c in candidates]
    return [c for score, c in sorted(scored, key=lambda x: -x[0]) if score > 0][:k]


# --------------------------------------------------
# 1. DOCUMENT: load files and build the index once
# --------------------------------------------------

class ContentPipeline:

    def __init__(self, provider=None, model=None):
        self.provider = provider
        self.model = model
        self.pieces = []
        self.chunks = []
        self.index = None

    def prepare_knowledge_base(self):
        """Read all documents and build (or load) the search index."""
        self.pieces = load_knowledge_base()
        secondary = [p for p in self.pieces if p["source"] == "secondary"]
        self.chunks = chunk_for_rag(secondary)
        if RAG_AVAILABLE:
            self.index = build_index(self.pieces)
        return {"pieces": len(self.pieces), "rag_chunks": len(self.chunks),
                "consultants": self.list_consultants(), "rag": RAG_AVAILABLE}

    def list_consultants(self):
        """Every file in primary/ is one consultant profile."""
        return sorted({p["file"] for p in self.pieces if p["source"] == "primary"})

    # --------------------------------------------------
    # 2. MONITOR: suggest topics from the research documents
    # --------------------------------------------------

    def suggest_topics(self, n=8):
        """Use section headings of secondary documents as topic ideas."""
        headings = []
        for p in self.pieces:
            if p["source"] == "secondary" and p["heading"] not in ("Intro", *headings):
                headings.append(p["heading"])
        return headings[:n]

    # --------------------------------------------------
    # 3. BRIEF: retrieve context + brand voice for one request
    # --------------------------------------------------

    def _retrieve(self, query, k, source, consultant=None):
        if RAG_AVAILABLE:
            return search(self.index, query, k=k, source=source, consultant=consultant)
        pool = self.chunks if source == "secondary" else \
            [p for p in self.pieces if p["source"] == "primary"]
        return _keyword_search(pool, query, k, source, consultant)

    def _brand_voice(self, consultant, topic):
        """Consultant's core profile sections + their pieces most relevant to the topic."""
        own = [p for p in self.pieces if p["file"] == consultant]
        if not own:
            raise ValueError(f"Unknown consultant: {consultant}. "
                             f"Choose from: {self.list_consultants()}")
        core = [p for p in own if p["heading"] in BRAND_SECTIONS]
        relevant = self._retrieve(topic, k=3, source="primary", consultant=consultant)
        selected, seen = [], set()
        for p in core + relevant:
            key = (p["heading"], p["text"][:50])
            if key not in seen:
                seen.add(key)
                selected.append(f"[{p['heading']}]\n{p['text']}")
        return "\n\n".join(selected)[:MAX_BRAND_VOICE_CHARS]

    def create_brief(self, consultant, request, k=5):
        """Return everything the Prompt Builder needs, with source references."""
        topic = request.get("topic", "").strip()
        if not topic:
            raise ValueError("A content topic is required.")
        chunks = self._retrieve(topic, k=k, source="secondary")
        context = "\n\n".join(f"[S{i}] {c['file']} › {c['heading']}\n{c['text']}"
                              for i, c in enumerate(chunks, 1))
        return {
            "consultant": consultant,
            "request": dict(request),
            "brand_voice": self._brand_voice(consultant, topic),
            "context": context or "No relevant research found for this topic.",
            "sources": [f"[S{i}] {c['file']} › {c['heading']}" for i, c in enumerate(chunks, 1)],
        }

    # --------------------------------------------------
    # 4. PUBLISH: generate a draft (always needs human approval)
    # --------------------------------------------------

    def generate_draft(self, brief, feedback=None, previous_draft=None):
        request = dict(brief["request"])
        if feedback and previous_draft:
            request["additional_instructions"] = (
                f"{request.get('additional_instructions', '')}\n\n"
                f"Revise this previous draft:\n---\n{previous_draft}\n---\n"
                f"Apply this reviewer feedback: {feedback}\n"
                "Keep what works; change only what the feedback asks for."
            ).strip()
        prompt = build_prompt(brief["context"], request, brief["brand_voice"])
        result = generate_content(prompt, provider=self.provider, model=self.model)
        result["prompt"] = prompt
        return result

    # --------------------------------------------------
    # 5. ITERATE + SAVE: versions, feedback, approval
    # --------------------------------------------------

    def start_session(self, consultant, request):
        """Create a folder for this post: outputs/content/<date>_<topic>/"""
        slug = re.sub(r"[^a-z0-9]+", "-", request["topic"].lower()).strip("-")[:40]
        folder = OUTPUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{slug}"
        folder.mkdir(parents=True, exist_ok=True)
        brief = self.create_brief(consultant, request)
        return {"folder": folder, "brief": brief, "versions": []}

    def run(self, session, feedback=None):
        """Generate the first draft, or a revision when feedback is given."""
        previous = session["versions"][-1]["text"] if session["versions"] else None
        result = self.generate_draft(session["brief"], feedback, previous)
        version = {**result,                       # model, tokens, cost, text...
                   "version": len(session["versions"]) + 1, "feedback": feedback,
                   "status": "draft" if result["status"] == "success" else "failed"}
        session["versions"].append(version)
        self._save(session)
        return version

    def approve(self, session):
        """Mark the latest successful version as approved for publication."""
        latest = session["versions"][-1]
        if latest["status"] != "draft":
            raise ValueError("Only a successful draft can be approved.")
        latest["status"] = "approved"
        self._save(session)
        (session["folder"] / "approved.md").write_text(latest["text"], encoding="utf-8")
        return latest

    def generate_baseline(self, session):
        """Generic post with no brand voice and no RAG, for uniqueness comparison."""
        req = session["brief"]["request"]
        prompt = (f"Write a {req.get('platform', 'linkedin')} post about: {req['topic']}. "
                  f"Audience: {req.get('audience', 'general audience')}.")
        result = generate_content(prompt, provider=self.provider, model=self.model)
        session["baseline"] = {**result, "prompt": prompt}
        self._save(session)
        if result["status"] == "success":
            (session["folder"] / "baseline_generic.md").write_text(result["text"], encoding="utf-8")
        return result

    def _save(self, session):
        folder = session["folder"]
        for v in session["versions"]:
            if v["text"]:
                (folder / f"v{v['version']}.md").write_text(v["text"], encoding="utf-8")
        record = {k: v for k, v in session.items() if k != "folder"}
        (folder / "session.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")