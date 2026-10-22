"""
app.py
AI Content Creator - Gradio web interface (optional UI, same pipeline as main.py)

Run:  python src/app.py      then open http://127.0.0.1:7860

This file only collects input, shows drafts and handles the review buttons.
All real work happens in content_pipeline.py.
"""
import gradio as gr
from dotenv import load_dotenv

from content_pipeline import ContentPipeline
from prompt_templates import PLATFORM_RULES, FORMAT_RULES, DEFAULT_FORMAT, DEFAULT_PLATFORM


# --------------------------------------------------
# 1. START: load the knowledge base once
# --------------------------------------------------

load_dotenv()
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

def _use_mock(mock):
    """Switch between the real API and the free mock for this click."""
    pipeline.provider = "mock" if mock else "openai"


def _show(session):
    """Return (draft text, status line) for the latest version."""
    v = session["versions"][-1]
    if v["status"] == "failed":
        good = pipeline.last_good_draft(session)       # keep showing the last good draft
        hint = " Click Rewrite to try again." if good else " Click Generate draft to try again."
        return (good["text"] if good else ""), f"❌ **Generation failed:** {v['error']}{hint}"
    status = (f"📝 **Draft {v['version']}** · {v['model']} · "
              f"{v['input_tokens']}+{v['output_tokens']} tokens · {v['latency_s']}s")
    return v["text"], status


def _sources(session):
    lines = session["sources"] or ["(no research found for this topic)"]
    return "**Sources used:**\n\n" + "\n".join(f"- {s}" for s in lines)


def _buttons(session):
    """Rewrite needs any good draft; Approve only when the LATEST draft is good."""
    can_rewrite = pipeline.last_good_draft(session) is not None
    can_approve = session["versions"][-1]["status"] == "draft"
    return (ENABLED if can_rewrite else DISABLED), (ENABLED if can_approve else DISABLED)


# --------------------------------------------------
# 3. BUTTON ACTIONS
# --------------------------------------------------

def generate(topic, platform, consultant, content_format, audience, objective, extra, mock):
    """Build the prompt (files 1-3) and get the first draft (file 4)."""
    if STARTUP_ERROR:
        return None, "", f"❌ {STARTUP_ERROR}", "", DISABLED, DISABLED, ""
    if not topic.strip() or not consultant:
        return None, "", "⚠️ Enter a topic and choose a consultant.", "", DISABLED, DISABLED, ""
    _use_mock(mock)
    request = {"topic": topic, "platform": platform, "format": content_format,
               "audience": audience, "objective": objective,
               "additional_instructions": extra}
    try:
        session = pipeline.start_session(consultant, request)
    except ValueError as error:
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
    _use_mock(mock)
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
    message = f"✅ **Approved and saved:** `{path}`"
    if baseline:
        _use_mock(mock)
        try:
            message += f"\n\n📄 Generic baseline saved: `{pipeline.generate_baseline(session)}`"
        except RuntimeError as error:
            message += f"\n\n⚠️ Baseline failed: {error}"
    return session, message, DISABLED, DISABLED


# --------------------------------------------------
# 4. LAYOUT
# --------------------------------------------------

with gr.Blocks(title="AI Content Creator") as demo:
    gr.Markdown("# AI Content Creator\nPosts in a consultant's own voice, "
                "based on their profile and the research documents. Every post needs your approval.")
    if STARTUP_ERROR:
        gr.Markdown(f"❌ **Cannot start the pipeline:** {STARTUP_ERROR}")

    session_state = gr.State(None)

    with gr.Row():
        # Left: the request
        with gr.Column(scale=1):
            topic = gr.Textbox(label="Topic", placeholder="When should companies use RAG?")
            platform = gr.Dropdown(list(PLATFORM_RULES), value=DEFAULT_PLATFORM, label="Platform")
            consultant = gr.Dropdown(STATS["consultants"], label="Consultant",
                                     value=STATS["consultants"][0] if STATS["consultants"] else None)
            with gr.Accordion("More options", open=False):
                content_format = gr.Dropdown(list(FORMAT_RULES), value=DEFAULT_FORMAT, label="Format")
                audience = gr.Textbox(value="Business leaders", label="Audience")
                objective = gr.Textbox(value="Educate", label="Objective")
                extra = gr.Textbox(label="Extra instructions", lines=2)
            mock = gr.Checkbox(label="Free test run (mock, no API call)", value=False)
            baseline = gr.Checkbox(label="On approval, also save a generic baseline post", value=False)
            generate_btn = gr.Button("Generate draft", variant="primary")
            sources = gr.Markdown()

        # Right: the draft and the human review
        with gr.Column(scale=2):
            status = gr.Markdown("Fill in a topic and click **Generate draft**.")
            draft = gr.Textbox(label="Draft", lines=16, interactive=False, buttons=["copy"])
            feedback = gr.Textbox(label="Feedback", lines=2,
                                  placeholder="e.g. Make it shorter and end with a question")
            with gr.Row():
                rewrite_btn = gr.Button("Rewrite with feedback", interactive=False)
                approve_btn = gr.Button("Approve and save", variant="primary", interactive=False)

    # --------------------------------------------------
    # 5. WIRING: which button calls which function
    # --------------------------------------------------

    generate_btn.click(
        generate,
        inputs=[topic, platform, consultant, content_format, audience, objective, extra, mock],
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
    demo.launch()