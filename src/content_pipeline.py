"""
content_pipeline.py
AI Content Creator - The Manager

Responsibility:
Run every step in order, add the human review, save the result.
    1. Build the prompt   (files 1 -> 2 -> 3)
    2. Get the draft      (file 4)
    3. Human review       (feedback -> rewrite, approve)  [driven by main.py]
    4. Save the approved post in outputs/

Needs from knowledge_base.py (File 2):
    build_index(pieces)        -> index of the secondary documents
    search(index, query, k)    -> list of chunk dicts
        each chunk: {"source", "file", "heading", "text", ...}

Consultants: one folder per consultant in knowledge_base/primary/
(e.g. elif_yurdakul/ with profile PDF, past posts, services). All of that
consultant's files go into the prompt whole; they are not searched.

This module contains no prompt wording (see prompt_templates.py)
and no API code (see llm_integration.py).
"""
import json
from datetime import datetime
from pathlib import Path

from document_processor import load_knowledge_base
from prompt_templates import build_messages, build_baseline_prompt
from llm_integration import generate_content

try:
    from knowledge_base import build_index, search
except ImportError:
    build_index = search = None


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"
DRAFTS_DIR = OUTPUT_DIR / "drafts"
MAX_BRAND_VOICE_CHARS = 20000   # whole profile + services + past posts (~5k tokens)
RESEARCH_CHUNKS = 5             # secondary chunks per post

KB_NOT_READY = ("knowledge_base.py is not ready yet: it needs "
                "build_index(pieces) and search(index, query, k).")


def consultant_of(file_name):
    """'elif_yurdakul/services.md' -> 'elif_yurdakul'; a loose file 'jane_doe.pdf' -> 'jane_doe'."""
    parts = Path(file_name).parts
    return parts[0] if len(parts) > 1 else Path(file_name).stem


class ContentPipeline:

    def __init__(self, mock=False):
        self.provider = "mock" if mock else "openai"
        self.pieces = []
        self.index = None

    # --------------------------------------------------
    # 1. DOCUMENT: load files and build the index
    # --------------------------------------------------

    def prepare_knowledge_base(self):
        """Read all documents and build (or load) the search index."""
        if build_index is None or search is None:
            raise RuntimeError(KB_NOT_READY)
        self.pieces = load_knowledge_base()
        self.index = build_index(self.pieces)
        return {"pieces": len(self.pieces), "consultants": self.list_consultants()}

    def list_consultants(self):
        """Every folder in primary/ is one consultant (a loose file counts as one too)."""
        return sorted({consultant_of(p["file"]) for p in self.pieces if p["source"] == "primary"})

    def resolve_consultant(self, name):
        """Match a consultant name case-insensitively, e.g. 'Elif_Yurdakul' -> 'elif_yurdakul'."""
        for consultant in self.list_consultants():
            if consultant.lower() == name.lower():
                return consultant
        raise ValueError(f"Unknown consultant: {name}. "
                         f"Choose from: {', '.join(self.list_consultants())}")

    # --------------------------------------------------
    # 2. CONTEXT: research chunks + the consultant's own profile
    # --------------------------------------------------

    def _brand_voice(self, consultant):
        """All of this consultant's files (profile first), each piece labelled with file and heading."""
        own = [p for p in self.pieces                  # never mix consultants
               if p["source"] == "primary" and consultant_of(p["file"]) == consultant]
        own.sort(key=lambda p: Path(p["file"]).suffix != ".pdf")   # stable: keeps file order
        text = "\n\n".join(f"[{Path(p['file']).name} › {p['heading']}]\n{p['text']}" for p in own)
        return text[:MAX_BRAND_VOICE_CHARS]

    def _context(self, topic):
        """Research chunks for the topic, each labelled with its source."""
        chunks = search(self.index, topic, k=RESEARCH_CHUNKS)
        sources = [f"[S{i}] {c['file']} › {c['heading']}" for i, c in enumerate(chunks, 1)]
        context = "\n\n".join(f"{s}\n{c['text']}" for s, c in zip(sources, chunks))
        return context or "No relevant research found for this topic.", sources

    # --------------------------------------------------
    # 3. SESSION: one post, its drafts and the approval
    # --------------------------------------------------

    def start_session(self, consultant, request):
        """Prepare everything needed to write one post."""
        consultant = self.resolve_consultant(consultant)
        context, sources = self._context(request["topic"])
        name = f"{request['platform']}_{consultant}_{datetime.now():%Y%m%d-%H%M}"
        return {"name": name, "consultant": consultant, "request": dict(request),
                "brand_voice": self._brand_voice(consultant),
                "context": context, "sources": sources, "versions": []}

    def last_good_draft(self, session):
        """The latest version that generated successfully, or None."""
        good = [v for v in session["versions"] if v["status"] == "draft"]
        return good[-1] if good else None

    def run(self, session, feedback=None):
        """Generate the first draft, a retry, or a rewrite based on feedback."""
        previous = self.last_good_draft(session)
        system, user = build_messages(
            session["context"], session["request"], session["brand_voice"],
            previous_draft=previous["text"] if previous and feedback else None,
            feedback=feedback)
        result = generate_content(user, system=system, provider=self.provider)
        version = {**result,
                   "version": len(session["versions"]) + 1, "feedback": feedback,
                   "status": "draft" if result["status"] == "success" else "failed"}
        session["versions"].append(version)
        self._save_drafts(session)
        return version

    def approve(self, session):
        """Save the latest version as outputs/<platform>_<consultant>_<time>.md"""
        latest = session["versions"][-1]
        if latest["status"] != "draft":
            raise ValueError("Only a successful draft can be approved.")
        latest["status"] = "approved"
        self._save_drafts(session)
        path = OUTPUT_DIR / f"{session['name']}.md"
        path.write_text(latest["text"] + "\n", encoding="utf-8")
        return path

    def generate_baseline(self, session):
        """Generic post (no brand voice, no RAG), saved next to the drafts."""
        prompt = build_baseline_prompt(session["request"])
        result = generate_content(prompt, provider=self.provider)
        session["baseline"] = {**result, "prompt": prompt}
        self._save_drafts(session)
        if result["status"] == "success":
            path = DRAFTS_DIR / f"{session['name']}_baseline.md"
            path.write_text(result["text"] + "\n", encoding="utf-8")
            return path
        raise RuntimeError(result["error"])

    # --------------------------------------------------
    # 4. SAVE: every draft + feedback, out of sight in outputs/drafts/
    # --------------------------------------------------

    def _save_drafts(self, session):
        DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        record = {k: v for k, v in session.items() if k not in ("brand_voice", "context")}
        (DRAFTS_DIR / f"{session['name']}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


# --------------------------------------------------
# SELF-CHECK: python src/content_pipeline.py   (free, uses mock)
# --------------------------------------------------

if __name__ == "__main__":
    pipeline = ContentPipeline(mock=True)
    try:
        stats = pipeline.prepare_knowledge_base()
    except RuntimeError as error:
        raise SystemExit(f"❌ {error}")
    print(f"✅ {stats['pieces']} pieces, consultants: {stats['consultants']}")
    if stats["consultants"]:
        session = pipeline.start_session(
            stats["consultants"][0],
            {"topic": "When should companies use RAG?", "platform": "linkedin"})
        print(f"✅ Sources: {session['sources']}")
        print(f"✅ Draft status: {pipeline.run(session)['status']}")