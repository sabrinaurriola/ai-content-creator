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
(profile.pdf, past_posts, services, github.md; see consultant_profile.py).
All of that consultant's files go into the prompt whole; they are not searched.
voice.md is used as the default tone instead.

This module contains no prompt wording (see prompt_templates.py)
and no API code (see llm_integration.py).
"""
import json
import re
from datetime import datetime
from pathlib import Path

from document_processor import load_knowledge_base
from prompt_templates import (build_messages, build_baseline_prompt, build_search_query_prompt,
                              build_anchor_prompt)
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
MAX_BRAND_VOICE_CHARS = 24000   # profile + services + past posts + GitHub (~6k tokens)
RESEARCH_CHUNKS = 5             # secondary chunks per post
STRONG_SCORE = 0.30             # similarity for "relevant" research
RELATED_SCORE = 0.20            # below this a chunk is unrelated and never sent
VOICE_FILE = "voice.md"         # the consultant's own tone description
FILE_ORDER = ["profile", "services", "past_posts", "github"]   # if too long, the end is cut

NO_MATCH = ("No research matches the topic \"{topic}\" (searched for: \"{query}\"). "
            "No draft was written. Check the spelling or rephrase the topic, "
            "or pick one the Ironhack documents cover.")

KB_NOT_READY = ("knowledge_base.py is not ready yet: it needs "
                "build_index(pieces) and search(index, query, k).")


def consultant_of(file_name):
    """'elif_yurdakul/services.md' -> 'elif_yurdakul'; a loose file 'jane_doe.pdf' -> 'jane_doe'."""
    parts = Path(file_name).parts
    return parts[0] if len(parts) > 1 else Path(file_name).stem


def _file_rank(file_name):
    """Position of a file in FILE_ORDER (unknown files go last)."""
    stem = Path(file_name).stem
    return next((i for i, prefix in enumerate(FILE_ORDER) if stem.startswith(prefix)),
                len(FILE_ORDER))


class ContentPipeline:

    def __init__(self, mock=False):
        self.provider = "mock" if mock else "openai"     # default; a session can override it
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
        if not self.index["chunks"]:                     # never write without research documents
            raise RuntimeError("No research documents found in knowledge_base/secondary/.")
        return {"pieces": len(self.pieces), "consultants": self.list_consultants()}

    def forget_consultant(self, consultant):
        """Drop a consultant's pieces from memory (their folder was deleted)."""
        self.pieces = [p for p in self.pieces
                       if not (p["source"] == "primary" and consultant_of(p["file"]) == consultant)]

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

    def _own_pieces(self, consultant):
        """This consultant's pieces only (never mix consultants)."""
        return [p for p in self.pieces
                if p["source"] == "primary" and consultant_of(p["file"]) == consultant]

    def voice_description(self, consultant):
        """The consultant's saved tone (voice.md), or '' if there is none."""
        return "\n".join(p["text"] for p in self._own_pieces(consultant)
                         if Path(p["file"]).name == VOICE_FILE)

    def _brand_voice(self, consultant):
        """All of this consultant's files in FILE_ORDER, each piece labelled with file and heading."""
        own = [p for p in self._own_pieces(consultant) if Path(p["file"]).name != VOICE_FILE]
        own.sort(key=lambda p: _file_rank(p["file"]))      # stable: keeps order inside a file
        text = "\n\n".join(f"[{Path(p['file']).name} › {p['heading']}]\n{p['text']}" for p in own)
        return text[:MAX_BRAND_VOICE_CHARS]

    def _search_query(self, topic, provider):
        """Fix typos and expand short topics before searching ('sbersucurity' -> 'cybersecurity').
        Mock: the topic as typed. If the call fails, the topic as typed."""
        if provider == "mock":
            return topic
        system, user = build_search_query_prompt(topic)
        result = generate_content(user, system=system, provider=provider,
                                  max_tokens=40, temperature=0)
        query = result["text"].strip().strip('"') if result["status"] == "success" else ""
        return query or topic

    def _anchors(self, consultant, brand_voice, topic, provider):
        """2-3 exact quotes from the consultant's material that fit the topic.
        Every quote is checked against the files; invented ones are dropped.
        Fallback (mock, failed call, nothing valid): the start of their profile Summary."""
        def norm(text):                                  # ignore spacing: PDFs often lose it
            return re.sub(r"\s+", "", text).strip('"“”-•').lower()
        anchors = []
        if provider != "mock":
            system, user = build_anchor_prompt(brand_voice, topic)
            result = generate_content(user, system=system, provider=provider,
                                      max_tokens=200, temperature=0)
            if result["status"] == "success":
                source = norm(brand_voice)
                for line in result["text"].splitlines():
                    quote = re.sub(r"\s+", " ", line).strip(' "“”-•')
                    if len(quote) > 15 and norm(quote) in source:
                        anchors.append(quote)
        if not anchors:
            summary = [p["text"] for p in self._own_pieces(consultant) if p["heading"] == "Summary"]
            if summary:
                text = re.sub(r"\s+", " ", summary[0])
                anchors = [re.sub(r"([.!?])(?=[A-Z])", r"\1 ", text)[:300]]
        return anchors[:3]

    def _context(self, topic):
        """Research chunks for the topic, labelled with source and strength.
        Returns (context, sources, number of strong matches). A failed search stops the
        post with an error: it never silently continues without research."""
        try:
            chunks = search(self.index, topic, k=RESEARCH_CHUNKS, min_score=RELATED_SCORE)
        except Exception as error:
            raise RuntimeError(f"Could not search the research documents ({error}). "
                               "No draft was written; please try again.") from error
        sources = []
        for i, c in enumerate(chunks, 1):
            label = "" if c["score"] >= STRONG_SCORE else " (loosely related)"
            sources.append(f"[S{i}] {c['file']} › {c['heading']}{label}")
        strong = sum(c["score"] >= STRONG_SCORE for c in chunks)
        context = "\n\n".join(f"{s}\n{c['text']}" for s, c in zip(sources, chunks))
        return context or "No relevant research found for this topic.", sources, strong

    # --------------------------------------------------
    # 3. SESSION: one post, its drafts and the approval
    # --------------------------------------------------

    def start_session(self, consultant, request, provider=None):
        """Prepare everything needed to write one post.
        Stops (ValueError) when no research matches: a post is never written without data."""
        provider = provider or self.provider
        consultant = self.resolve_consultant(consultant)
        request = dict(request)
        if not (request.get("tone") or "").strip():          # empty tone -> the saved voice
            request.pop("tone", None)
            if self.voice_description(consultant):
                request["tone"] = self.voice_description(consultant)
        brand_voice = self._brand_voice(consultant)
        if not brand_voice.strip():                      # never write a generic post
            raise ValueError(f"No readable profile for {consultant}. Save the profile again.")
        query = self._search_query(request["topic"], provider)
        context, sources, strong = self._context(query)
        if not sources:
            raise ValueError(NO_MATCH.format(topic=request["topic"], query=query))
        anchors = self._anchors(consultant, brand_voice, query, provider)
        name = f"{request['platform']}_{consultant}_{datetime.now():%Y%m%d-%H%M}"
        return {"name": name, "consultant": consultant, "request": request,
                "provider": provider, "search_query": query, "anchors": anchors,
                "brand_voice": brand_voice, "context": context, "sources": sources,
                "strong_sources": strong, "versions": []}

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
            feedback=feedback, anchors=session.get("anchors"))
        provider = session.get("provider") or self.provider    # per session: safe for many users
        result = generate_content(user, system=system, provider=provider)
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
        result = generate_content(prompt, provider=session.get("provider") or self.provider)
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