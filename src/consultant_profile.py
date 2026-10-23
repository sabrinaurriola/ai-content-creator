"""Save a consultant's own inputs into knowledge_base/primary/<consultant>/.

    profile.pdf      LinkedIn "Save to PDF" export (required for a new consultant)
    past_posts.pdf   some past posts, so the writer can match their voice (optional)
    voice.md         short description of their tone, e.g. "serious, a bit funny" (optional)
    services.md      their services or offer, typed in the app (optional)
    services.pdf     the same as a PDF, e.g. a service sheet (optional)
    github.md        public GitHub portfolio, made by github_import.py (optional)
"""
import re
import secrets
import shutil
from pathlib import Path

from document_processor import KB_DIR
from github_import import github_markdown

PRIMARY_DIR = KB_DIR / "primary"
PROFILE_FILE = "profile.pdf"
POSTS_FILE = "past_posts.pdf"
VOICE_FILE = "voice.md"
SERVICES_FILE = "services.md"
SERVICES_PDF = "services.pdf"
GITHUB_FILE = "github.md"
PRIVATE_FOLDER = re.compile(r".+_[0-9a-f]{16}$")   # e.g. jane_doe_3f9a1c0b7d2e4f61


def consultant_slug(name):
    """'Jane Doe' -> 'jane_doe', the consultant's folder name."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    if not slug:
        raise ValueError("Enter the consultant's name.")
    return slug


def private_folder_name(name):
    """Unguessable folder name for one user's session on a shared server."""
    return f"{consultant_slug(name)}_{secrets.token_hex(8)}"


def delete_consultant(folder_name, primary_dir=PRIMARY_DIR):
    """Remove a consultant's folder and everything in it."""
    folder = Path(primary_dir) / folder_name
    if folder_name and folder.is_dir():
        shutil.rmtree(folder)


def remove_private_folders(primary_dir=PRIMARY_DIR):
    """Delete leftover session folders (shared mode start-up); named folders are kept."""
    for folder in Path(primary_dir).glob("*"):
        if folder.is_dir() and PRIVATE_FOLDER.match(folder.name):
            shutil.rmtree(folder)


def _check_pdf(path, label):
    if path and Path(path).suffix.lower() != ".pdf":
        raise ValueError(f"The {label} must be a PDF file.")


def _replace_pdf(folder, uploaded, file_name):
    """Copy an uploaded PDF in; older files of the same kind (e.g. profile1.pdf) are removed."""
    for old in folder.glob(f"{Path(file_name).stem}*.pdf"):
        old.unlink()
    shutil.copy(uploaded, folder / file_name)


def save_consultant(name, profile_pdf=None, posts_pdf=None, voice=None, github_link=None,
                    services_text=None, services_pdf=None,
                    primary_dir=PRIMARY_DIR, folder_name=None):
    """Save whatever was given; empty fields keep what is already saved.
    folder_name overrides the folder (shared mode: private_folder_name()).
    Returns (consultant folder name, list of what was saved)."""
    consultant = folder_name or consultant_slug(name)
    folder = Path(primary_dir) / consultant
    _check_pdf(profile_pdf, "LinkedIn profile")
    _check_pdf(posts_pdf, "past posts file")
    _check_pdf(services_pdf, "services file")
    if not profile_pdf and not list(folder.glob("profile*.pdf")):
        raise ValueError("A LinkedIn profile PDF is required for a new consultant.")

    # Fetch GitHub first, so a bad link does not leave a half-saved folder
    github = github_markdown(github_link) if github_link and github_link.strip() else None

    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    if profile_pdf:
        _replace_pdf(folder, profile_pdf, PROFILE_FILE)
        saved.append("LinkedIn profile")
    if posts_pdf:
        _replace_pdf(folder, posts_pdf, POSTS_FILE)
        saved.append("past posts")
    if voice and voice.strip():
        (folder / VOICE_FILE).write_text(f"# Voice – {consultant}\n\n## Voice\n{voice.strip()}\n",
                                         encoding="utf-8")
        saved.append("voice description")
    if services_text and services_text.strip():
        (folder / SERVICES_FILE).write_text(
            f"# Services – {consultant}\n\n## Services and offer\n{services_text.strip()}\n",
            encoding="utf-8")
        saved.append("services")
    if services_pdf:
        _replace_pdf(folder, services_pdf, SERVICES_PDF)
        saved.append("services PDF")
    if github:
        markdown, projects = github
        (folder / GITHUB_FILE).write_text(markdown, encoding="utf-8")
        saved.append(f"GitHub portfolio ({projects} projects)")
    return consultant, saved


# ---------- Self-check: python src/consultant_profile.py   (temp folder, no API calls) ----------
if __name__ == "__main__":
    import tempfile
    from pypdf import PdfWriter

    assert consultant_slug("  Jane Doe ") == "jane_doe"
    assert consultant_slug("Dr. Elif Yurdakul") == "dr_elif_yurdakul"
    with tempfile.TemporaryDirectory() as tmp:
        try:
            save_consultant("Jane Doe", voice="Serious", primary_dir=tmp)
            raise SystemExit("❌ a new consultant without a profile should be refused")
        except ValueError as error:
            print(f"✅ refused: {error}")

        pdf = Path(tmp) / "upload.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(pdf)
        consultant, saved = save_consultant("Jane Doe", profile_pdf=pdf, posts_pdf=pdf,
                                            voice="Serious, short sentences", primary_dir=tmp)
        files = sorted(p.name for p in (Path(tmp) / consultant).iterdir())
        print(f"✅ {consultant}: {saved} → {files}")
        assert files == [POSTS_FILE, PROFILE_FILE, VOICE_FILE]

        consultant, saved = save_consultant("jane doe", voice="Playful", primary_dir=tmp)
        print(f"✅ update without a new PDF: {saved}")

        consultant, saved = save_consultant("Jane Doe", services_text="AI readiness workshops",
                                            services_pdf=pdf, primary_dir=tmp)
        files = sorted(p.name for p in (Path(tmp) / consultant).iterdir())
        print(f"✅ services: {saved} → {files}")
        assert SERVICES_FILE in files and SERVICES_PDF in files

        private = private_folder_name("Jane Doe")
        save_consultant("Jane Doe", profile_pdf=pdf, primary_dir=tmp, folder_name=private)
        remove_private_folders(tmp)
        left = sorted(p.name for p in Path(tmp).iterdir() if p.is_dir())
        print(f"✅ private folder {private} removed at start-up, kept: {left}")
        assert left == ["jane_doe"]
        delete_consultant("jane_doe", tmp)
        assert not (Path(tmp) / "jane_doe").exists()
        print("✅ delete_consultant")
