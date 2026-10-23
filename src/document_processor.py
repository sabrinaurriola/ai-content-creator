"""Read the knowledge bases (markdown + PDF) and cut them into labelled pieces."""
import re
from pathlib import Path
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter

KB_DIR = Path(__file__).resolve().parent.parent / "knowledge_base"

# Section titles that LinkedIn writes on their own line in "Save to PDF" exports
LINKEDIN_SECTIONS = {"Contact", "Top Skills", "Languages", "Certifications",
                     "Honors-Awards", "Publications", "Summary", "Experience", "Education"}


# ---------- 1. Read files ----------
def read_pdf(path):
    """Return all text of a PDF, without 'Page 1 of 3' footers."""
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    return re.sub(r"Page \d+ of \d+", "", text)


# ---------- 2. Split into labelled pieces ----------
def make_piece(source, file_name, heading, lines):
    return {"source": source, "file": file_name,
            "heading": heading, "text": "\n".join(lines).strip()}


def split_markdown(text, source, file_name):
    """Split a markdown file at every '## ' heading."""
    pieces, heading, lines = [], "Intro", []
    for line in text.splitlines():
        if line.startswith("# "):
            continue                      # document title, not content
        if line.startswith("## "):
            pieces.append(make_piece(source, file_name, heading, lines))
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    pieces.append(make_piece(source, file_name, heading, lines))
    return [p for p in pieces if p["text"]]          # drop empty pieces


def split_linkedin_profile(text, source, file_name):
    """Split a LinkedIn PDF export at its section titles (Summary, Experience, ...)."""
    pieces, heading, lines = [], "Header", []
    for line in text.splitlines():
        if line.strip() in LINKEDIN_SECTIONS:
            pieces.append(make_piece(source, file_name, heading, lines))
            heading, lines = line.strip(), []
        else:
            lines.append(line)
    pieces.append(make_piece(source, file_name, heading, lines))
    return [p for p in pieces if p["text"]]


# ---------- 3. Load everything ----------
def load_knowledge_base(kb_dir=KB_DIR):
    """Read every .md and .pdf file in primary/ and secondary/ and return all pieces.
    'file' is the path inside the source folder, e.g. 'elif_yurdakul/services.md'."""
    pieces = []
    for source in ["primary", "secondary"]:
        folder = Path(kb_dir) / source
        if source == "primary" and not folder.exists():
            continue                      # no consultants yet: add one in the app
        if not folder.exists():
            raise FileNotFoundError(f"[document_processor] Folder not found: {folder}")
        for path in sorted(folder.rglob("*")):
            file_name = path.relative_to(folder).as_posix()
            if path.suffix == ".md":
                pieces += split_markdown(path.read_text(encoding="utf-8"), source, file_name)
            elif path.suffix == ".pdf" and path.stem.startswith("profile"):
                pieces += split_linkedin_profile(read_pdf(path), source, file_name)
            elif path.suffix == ".pdf":                       # e.g. past_posts.pdf: one piece
                heading = path.stem.replace("_", " ").capitalize()
                pieces += [p for p in [make_piece(source, file_name, heading,
                                                  read_pdf(path).splitlines())] if p["text"]]
    return pieces


# ---------- 4. Chunks for RAG (Ironhack docs) ----------
def chunk_for_rag(pieces, chunk_size=800, chunk_overlap=100):
    """Cut pieces into smaller chunks; every chunk keeps its labels."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\n\n", ". ", "\n", " ", ""], keep_separator="end")
    chunks = []
    for piece in pieces:
        for i, text in enumerate(splitter.split_text(piece["text"])):
            chunks.append({**piece, "text": text, "chunk_id": i})
    return chunks


# ---------- Self-check: python src/document_processor.py ----------
if __name__ == "__main__":
    pieces = load_knowledge_base()
    files = sorted({p["file"] for p in pieces})
    print(f"✅ {len(files)} files → {len(pieces)} pieces")
    for p in pieces:
        print(f"  [{p['source']}] {p['file']} › {p['heading']} ({len(p['text'])} chars)")

    secondary = [p for p in pieces if p["source"] == "secondary"]
    chunks = chunk_for_rag(secondary)
    print(f"\n🔎 {len(secondary)} secondary pieces → {len(chunks)} RAG chunks")