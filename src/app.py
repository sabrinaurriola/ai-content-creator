"""
app.py
AI Content Creator - Gradio web interface (optional UI, same pipeline as main.py)

Run:  python src/app.py      then open http://127.0.0.1:7860

Brand: VoicePrint - AI content that sounds like you, not like everyone else.

Shared mode (on by default on Render, or SHARED_MODE=1): many people use one server,
so each browser session only sees the consultant it created. That consultant's files
live in a random folder that is deleted when the tab closes or the session expires.
Locally (shared mode off) every folder in knowledge_base/primary/ is listed.

Password: set APP_PASSWORD (and optionally APP_USERNAME) to ask for a login.
Always set it on Render: every real draft is paid with the project's OpenAI key.

This file only collects input, shows drafts and handles the review buttons.
All real work happens in content_pipeline.py (posts) and consultant_profile.py
(saving the consultant's profile PDF, past posts, voice and GitHub link).
"""
import base64
import os
import secrets
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from consultant_profile import (delete_consultant, private_folder_name, remove_private_folders,
                                save_consultant)
from content_pipeline import ContentPipeline
from prompt_templates import (PLATFORM_RULES, FORMAT_RULES, DEFAULT_FORMAT, DEFAULT_PLATFORM,
                              DEFAULT_TONE)


# --------------------------------------------------
# 1. START: brand settings, then load the knowledge base once
# --------------------------------------------------

BRAND_NAME = "VoicePrint"
BRAND_TAGLINE = "AI content that sounds like you, not like everyone else."
LOGO_FILE = Path(__file__).resolve().parent.parent / "assets" / "ironhack_logo.png"
# Day/night: Gradio styles the page dark when <body> has the class "dark"
TOGGLE_THEME_JS = "() => { document.body.classList.toggle('dark'); }"
SHARED_MODE = os.getenv("SHARED_MODE", "1" if os.getenv("RENDER") else "0") == "1"
SESSION_TTL_S = 4 * 60 * 60          # shared mode: a profile is deleted 4 h after its last change
NO_RESEARCH_WARNING = ("⚠️ **{found} found for this topic.** The draft relies mostly on your "
                       "profile, so check every fact before approving. Check the spelling of "
                       "the topic, or pick a topic the Ironhack documents cover.")
APP_USERNAME = os.getenv("APP_USERNAME", "voiceprint")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")


def check_login(username, password):
    """Gradio login check (constant-time compare, so the password cannot be guessed by timing)."""
    return (secrets.compare_digest(username, APP_USERNAME)
            and secrets.compare_digest(password, APP_PASSWORD))


def _logo_html():
    """Ironhack logo for the top right, embedded so no file serving is needed."""
    if not LOGO_FILE.exists():
        return ""
    data = base64.b64encode(LOGO_FILE.read_bytes()).decode()
    return (f'<div style="text-align:right"><img src="data:image/png;base64,{data}" '
            f'alt="Ironhack" style="height:44px;display:inline-block;border-radius:6px"></div>')


load_dotenv()
if SHARED_MODE:
    remove_private_folders()          # sessions from before a restart are gone
pipeline = ContentPipeline()
try:
    STATS = pipeline.prepare_knowledge_base()
    STARTUP_ERROR = None
except (RuntimeError, FileNotFoundError) as error:
    STATS = {"pieces": 0, "consultants": []}
    STARTUP_ERROR = str(error)

ENABLED, DISABLED = gr.update(interactive=True), gr.update(interactive=False)


# --------------------------------------------------
# 2. HELPERS
# --------------------------------------------------

def _use_mock(session, mock):
    """Real API or free mock for this session only (other users are not affected)."""
    session["provider"] = "mock" if mock else "openai"


def _choices(owned):
    """Consultants this browser may use: shared mode only its own, locally all folders."""
    if SHARED_MODE:
        return [(owned["name"], owned["folder"])] if owned else []
    return pipeline.list_consultants()


def _allowed(consultant, owned):
    """Server-side check, so nobody can pick another user's folder through the API."""
    return not SHARED_MODE or bool(owned and consultant == owned["folder"])


def _forget_owned(owned):
    """Called by Gradio when a session ends: delete that user's files."""
    if owned:
        delete_consultant(owned["folder"])
        pipeline.forget_consultant(owned["folder"])


def _show(session):
    """Return (draft text, status line) for the latest version."""
    v = session["versions"][-1]
    if v["status"] == "failed":
        good = pipeline.last_good_draft(session)       # keep showing the last good draft
        hint = " Click Rewrite to try again." if good else " Click Generate draft to try again."
        return (good["text"] if good else ""), f"❌ **Generation failed:** {v['error']}{hint}"
    status = (f"📝 **Draft {v['version']}** · {v['model']} · "
              f"{v['input_tokens']}+{v['output_tokens']} tokens · {v['latency_s']}s")
    if not session["strong_sources"]:                  # no sources at all never gets here
        status += "\n\n" + NO_RESEARCH_WARNING.format(found="Only loosely related research")
    return v["text"], status


def _sources(session):
    searched = f"🔎 Searched for: *{session['search_query']}*\n\n"
    anchors = "".join(f"- “{a}”\n" for a in session["anchors"]) or "- (none found)\n"
    return (searched + "**Your material used:**\n\n" + anchors + "\n**Sources used:**\n\n"
            + "\n".join(f"- {s}" for s in session["sources"]))


def _buttons(session):
    """Rewrite needs any good draft; Approve only when the LATEST draft is good."""
    can_rewrite = pipeline.last_good_draft(session) is not None
    can_approve = session["versions"][-1]["status"] == "draft"
    return (ENABLED if can_rewrite else DISABLED), (ENABLED if can_approve else DISABLED)


# --------------------------------------------------
# 3. BUTTON ACTIONS
# --------------------------------------------------

def save_profile(name, profile_pdf, posts_pdf, voice, github_link, services_text, services_pdf,
                 owned):
    """Save the consultant's inputs, reload the documents, select that consultant."""
    if STARTUP_ERROR:
        return f"❌ {STARTUP_ERROR}", gr.update(), gr.update(), owned
    try:
        folder = None
        if SHARED_MODE:                                  # one private folder per session
            folder = owned["folder"] if owned else private_folder_name(name)
        consultant, saved = save_consultant(name, profile_pdf, posts_pdf, voice, github_link,
                                            services_text, services_pdf, folder_name=folder)
        pipeline.prepare_knowledge_base()               # research index is cached: no API call
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        return f"❌ {error}", gr.update(), gr.update(), owned
    if consultant not in pipeline.list_consultants():  # e.g. a scanned PDF: no text inside
        return ("❌ No text could be read from your files. Use LinkedIn's \"Save to PDF\" "
                "export (not a scan or screenshot), or add a voice description."), \
            gr.update(), gr.update(), owned
    if SHARED_MODE:
        owned = {"folder": consultant, "name": name.strip()}
    shown = owned["name"] if SHARED_MODE else consultant
    message = (f"✅ Saved for **{shown}**: {', '.join(saved) or 'nothing new'}. "
               "Now open **2. Write a post**.")
    if SHARED_MODE:
        message += ("\n\n🔒 Only you can see this profile. It is deleted when you close "
                    "or refresh this tab.")
    return (message, gr.update(choices=_choices(owned), value=consultant),
            pipeline.voice_description(consultant) or DEFAULT_TONE, owned)


def saved_tone(consultant, owned=None):
    """Prefill the Tone box with the consultant's saved voice description."""
    if not consultant or not _allowed(consultant, owned):
        return DEFAULT_TONE
    return pipeline.voice_description(consultant) or DEFAULT_TONE


def generate(topic, platform, consultant, tone, content_format, audience, objective, extra, mock,
             owned):
    """Build the prompt (files 1-3) and get the first draft (file 4)."""
    if STARTUP_ERROR:
        return None, "", f"❌ {STARTUP_ERROR}", "", DISABLED, DISABLED, ""
    if not topic.strip() or not consultant:
        return None, "", ("⚠️ Enter a topic and choose a consultant "
                          "(add one in **1. Your profile**)."), "", DISABLED, DISABLED, ""
    if not _allowed(consultant, owned):
        return None, "", "⚠️ Save your profile in **1. Your profile** first.", "", DISABLED, DISABLED, ""
    request = {"topic": topic, "platform": platform, "format": content_format,
               "audience": audience, "objective": objective, "tone": tone,
               "additional_instructions": extra}
    try:
        session = pipeline.start_session(consultant, request, provider="mock" if mock else "openai")
    except (ValueError, RuntimeError) as error:       # no matching research or search failed
        return None, "", f"❌ {error}", "", DISABLED, DISABLED, ""
    pipeline.run(session)
    draft, status = _show(session)
    return (session, draft, status, _sources(session), *_buttons(session), "")


def rewrite(session, feedback, mock):
    """Human feedback -> rewrite."""
    if session is None:
        return session, "", "⚠️ Generate a draft first.", DISABLED, DISABLED, feedback
    if not feedback.strip():
        draft, _ = _show(session)
        return (session, draft, "⚠️ Type your feedback first, then click Rewrite.",
                *_buttons(session), feedback)
    _use_mock(session, mock)
    version = pipeline.run(session, feedback=feedback.strip())
    draft, status = _show(session)
    keep = feedback if version["status"] == "failed" else ""    # keep feedback for a retry
    return (session, draft, status, *_buttons(session), keep)


def approve(session, baseline, mock):
    """Human approval -> save in outputs/ (and the generic baseline if asked)."""
    if session is None:
        return session, "⚠️ Generate a draft first.", DISABLED, DISABLED
    try:
        path = pipeline.approve(session)
    except ValueError as error:
        return session, f"⚠️ {error}", *_buttons(session)
    message = ("✅ **Approved.** Copy it with the copy button on the draft." if SHARED_MODE
               else f"✅ **Approved and saved:** `{path}`")
    if baseline:
        _use_mock(session, mock)
        try:
            message += f"\n\n📄 Generic baseline saved: `{pipeline.generate_baseline(session)}`"
        except RuntimeError as error:
            message += f"\n\n⚠️ Baseline failed: {error}"
    return session, message, DISABLED, DISABLED


# --------------------------------------------------
# 4. LAYOUT
# --------------------------------------------------

with gr.Blocks(title=f"{BRAND_NAME} · {BRAND_TAGLINE}") as demo:
    with gr.Row(equal_height=True):
        with gr.Column(scale=4):
            gr.Markdown(f"# {BRAND_NAME}\n### {BRAND_TAGLINE}\n"
                        "Posts in your own voice, based on your profile, past posts, GitHub "
                        "and the Ironhack research documents. Every post needs your approval.")
        with gr.Column(scale=1, min_width=200):
            gr.HTML(_logo_html())
            theme_btn = gr.Button("🌓 Day / Night", size="sm")
    theme_btn.click(None, js=TOGGLE_THEME_JS)
    if STARTUP_ERROR:
        gr.Markdown(f"❌ **Cannot start the pipeline:** {STARTUP_ERROR}")

    session_state = gr.State(None)
    # Shared mode: {"folder", "name"} of this browser's own consultant; files deleted with it
    owned_state = gr.State(None, time_to_live=SESSION_TTL_S, delete_callback=_forget_owned)
    first = None if SHARED_MODE or not STATS["consultants"] else STATS["consultants"][0]

    with gr.Tabs():
        # Tab 1: who writes - saved in knowledge_base/primary/<name>/
        with gr.Tab("1. Your profile"):
            gr.Markdown("Your files stay private to this browser tab and are deleted when you "
                        "close it. Save again to update; empty fields keep what is saved."
                        if SHARED_MODE else
                        "Add a new consultant, or update one by typing the same name. "
                        "Empty fields keep what is already saved.")
            with gr.Row():
                with gr.Column():
                    profile_name = gr.Textbox(label="Your name", placeholder="Jane Doe")
                    profile_pdf = gr.File(label="LinkedIn profile (PDF) · required for a new consultant",
                                          file_types=[".pdf"], type="filepath")
                    posts_pdf = gr.File(label="Some past posts (PDF) · optional, to learn your voice",
                                        file_types=[".pdf"], type="filepath")
                with gr.Column():
                    voice = gr.Textbox(label="Your voice in a few words · optional", lines=3,
                                       placeholder="e.g. Serious and evidence-based, short sentences, "
                                                   "a bit of dry humour, no emojis")
                    github_link = gr.Textbox(label="GitHub profile link · optional",
                                             placeholder="https://github.com/janedoe")
                    services_text = gr.Textbox(
                        label="Your services or offer · optional", lines=4,
                        placeholder="e.g. AI readiness assessments for SMEs, AI literacy workshops "
                                    "for leadership teams, responsible AI in HR...")
                    services_pdf = gr.File(label="…or your services as a PDF · optional",
                                           file_types=[".pdf"], type="filepath")
                    save_btn = gr.Button("Save profile", variant="primary")
                    profile_status = gr.Markdown()

        # Tab 2: the request, the draft and the human review
        with gr.Tab("2. Write a post"):
            with gr.Row():
                with gr.Column(scale=1):
                    topic = gr.Textbox(label="Topic", placeholder="When should companies use RAG?")
                    platform = gr.Dropdown(list(PLATFORM_RULES), value=DEFAULT_PLATFORM, label="Platform")
                    consultant = gr.Dropdown(_choices(None), label="Consultant", value=first)
                    tone = gr.Textbox(label="Tone for this post (from your saved voice, edit freely)",
                                      value=saved_tone(first), lines=2)
                    with gr.Accordion("More options", open=False):
                        content_format = gr.Dropdown(list(FORMAT_RULES), value=DEFAULT_FORMAT,
                                                     label="Format")
                        audience = gr.Textbox(value="Business leaders", label="Audience")
                        objective = gr.Textbox(value="Educate", label="Objective")
                        extra = gr.Textbox(label="Extra instructions", lines=2)
                    mock = gr.Checkbox(label="Free test run (mock, no API call)", value=False)
                    baseline = gr.Checkbox(label="On approval, also save a generic baseline post",
                                           value=False)
                    generate_btn = gr.Button("Generate draft", variant="primary")
                    sources = gr.Markdown()

                with gr.Column(scale=2):
                    status = gr.Markdown("Fill in a topic and click **Generate draft**.")
                    draft = gr.Textbox(label="Draft", lines=16, interactive=False, buttons=["copy"])
                    feedback = gr.Textbox(label="Feedback", lines=2,
                                          placeholder="e.g. Make it shorter and end with a question")
                    with gr.Row():
                        rewrite_btn = gr.Button("Rewrite with feedback", interactive=False)
                        approve_btn = gr.Button("Approve and save", variant="primary",
                                                interactive=False)

    # --------------------------------------------------
    # 5. WIRING: which button calls which function
    # --------------------------------------------------

    save_btn.click(
        save_profile,
        inputs=[profile_name, profile_pdf, posts_pdf, voice, github_link, services_text,
                services_pdf, owned_state],
        outputs=[profile_status, consultant, tone, owned_state])
    consultant.change(saved_tone, inputs=[consultant, owned_state], outputs=[tone])
    generate_btn.click(
        generate,
        inputs=[topic, platform, consultant, tone, content_format, audience, objective, extra, mock,
                owned_state],
        outputs=[session_state, draft, status, sources, rewrite_btn, approve_btn, feedback])
    rewrite_btn.click(
        rewrite,
        inputs=[session_state, feedback, mock],
        outputs=[session_state, draft, status, rewrite_btn, approve_btn, feedback])
    approve_btn.click(
        approve,
        inputs=[session_state, baseline, mock],
        outputs=[session_state, status, rewrite_btn, approve_btn])


if __name__ == "__main__":
    login = {"auth": check_login, "auth_message": f"{BRAND_NAME}: please log in."} if APP_PASSWORD else {}
    if SHARED_MODE and not APP_PASSWORD:
        print("⚠️  Shared mode without APP_PASSWORD: anyone with the link can spend the OpenAI credits.")
    if os.getenv("PORT"):            # Render: listen on its port, on all network interfaces
        demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT")), **login)
    else:
        demo.launch(**login)