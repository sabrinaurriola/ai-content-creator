# VoicePrint

**AI content that sounds like you, not like everyone else.**

VoicePrint writes LinkedIn posts, blog articles, newsletters and Instagram captions in an AI
consultant's own voice. It combines the consultant's own material (LinkedIn profile, past posts,
services, GitHub) with the Ironhack AI Consulting program documents, and every draft needs a
human's approval before it is saved.

Ironhack AI Consulting bootcamp · Project 2 (AI Content Creator) · Sabrina Urriola, Elif Yurdakul, Pieter Albrecht

Live app: https://ai-content-creator-t62h.onrender.com (password protected)

---

## What it does

1. **Your profile:** upload your LinkedIn PDF, and optionally past posts (PDF), a short
   description of your voice, your services (text or PDF) and your GitHub profile link.
2. **Write a post:** choose a topic, platform (LinkedIn, blog, newsletter, Instagram) and format
   (educational, storytelling, opinion, how-to, professional insight). The tone comes from your
   saved voice and can be changed per post.
3. **Review:** give feedback to get a rewrite, as often as you like.
4. **Approve:** only then is the post saved. Nothing is published automatically.

## How it works

```
your files ──► document_processor ──► whole profile ─────────────────┐
                                                                      ├─► prompt ─► gpt-4o-mini ─► draft ─► feedback / approve
topic ──► spelling clean-up ──► search Ironhack docs (top 5 chunks) ──┤
                               ──► 2–3 quotes from your own files ────┘
                                   (checked against the files)
```

**Hybrid context (see [rag_decision.md](rag_decision.md)):**
- **The consultant's files go into the prompt whole.** They are small, and every detail is what
  makes the post personal.
- **The Ironhack documents are searched (RAG).** Embeddings with `text-embedding-3-small`, cosine
  similarity, top 5 chunks. A score of 0.30 or more counts as relevant, 0.20–0.30 is sent as
  "loosely related", and anything lower is never sent. Embeddings are cached in
  `data/kb_embeddings.json` and rebuilt only when a document changes.

**Safeguards against generic or invented content:**
- The topic is cleaned up before searching (typos, abbreviations).
- **If no research matches the topic, no post is written**; the app asks you to rephrase.
- 2–3 quotes are picked from the consultant's own files. The code checks that each one really
  appears in the files, and the post must build on at least one of them. They are shown in the
  app as "Your material used".
- The prompt rules forbid invented experiences, clients, numbers and credentials, merged facts,
  and stories presented as real. GitHub projects are never described as client work.
- A human approves every post.

## Quick start (local)

Requires Python 3.11 or newer.

```bash
git clone https://github.com/sabrinaurriola/ai-content-creator.git
cd ai-content-creator
pip install -r requirements.txt
cp .env.example .env          # then add your OPENAI_API_KEY
python src/app.py             # open http://127.0.0.1:7860
```

In the app, add yourself in **1. Your profile**, then write in **2. Write a post**.
Tick **Free test run** to try the whole flow without any OpenAI cost.

### Command line

The same pipeline without the web UI, for a consultant folder that already exists:

```bash
python src/main.py "When should companies use RAG?" linkedin jane_doe
python src/main.py "When should companies use RAG?" linkedin jane_doe --mock   # free test run
python src/main.py --help                                                      # all options
```

Type feedback to get a rewrite, press Enter to approve, or `q` to quit.

## Configuration (`.env`)

| Variable | Needed | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | OpenAI key for drafts and embeddings |
| `LLM_MODEL` | no | Model for drafts, default `gpt-4o-mini` |
| `APP_PASSWORD` | on Render | Turns on the login page |
| `APP_USERNAME` | no | Login name, default `voiceprint` |
| `SHARED_MODE` | no | `1` = each browser only sees its own profile (on automatically on Render) |
| `GITHUB_TOKEN` | no | Higher GitHub API limit for the portfolio import |

`.env` is in `.gitignore`. Never commit it; [.env.example](.env.example) is the template.

## Deploy on Render

1. New **Web Service** → connect this repository, branch `main`.
2. Build command: `pip install -r requirements.txt`
3. Start command: `python src/app.py`
4. Environment: `OPENAI_API_KEY`, `LLM_MODEL`, `APP_PASSWORD`, and `PYTHON_VERSION=3.11.9`.

The app listens on Render's `$PORT` and switches to **shared mode** automatically: each browser
session sees only the profile it created. That profile is stored in a randomly named folder and
deleted when the tab is closed or refreshed, or 4 hours after it was last saved. On the free plan
the service sleeps after about 15 minutes without visitors, so open it a minute before a demo.

## Project structure

```
knowledge_base/primary/<consultant>/  one folder per consultant (profile, past posts, voice,
                                      services, github.md). Not in git: personal data.
knowledge_base/secondary/             Ironhack program.md (syllabus) and curriculum.md
src/document_processor.py             read, split, label and chunk documents
src/knowledge_base.py                 embeddings index (cached) and search
src/consultant_profile.py             save a consultant's uploads to their folder
src/github_import.py                  public GitHub profile + top projects -> github.md
src/prompt_templates.py               all prompt wording
src/llm_integration.py                the only file that calls the OpenAI API (plus a free mock)
src/content_pipeline.py               runs the steps in order, saves drafts and approved posts
src/main.py                           command-line entry point
src/app.py                            Gradio web UI
scripts/pdf_to_md.py                  one-off: syllabus PDF -> program.md
outputs/                              approved posts; outputs/drafts/ every draft + feedback (not in git)
```

Each file in `src/` runs a self-check: `python src/<file>.py` (add `--mock` for
`llm_integration.py`).

## Cost

A draft uses about 5,200 input + 320 output tokens on `gpt-4o-mini`, roughly **$0.001 per draft**
at list price, plus about $0.0007 for the topic clean-up and quote picking. Building the
embeddings index costs well under one cent and happens once per document change. Every call is
logged in `outputs/usage_log.jsonl`.

## Privacy

- Consultant files, drafts, `.env` and the embeddings cache are in `.gitignore`.
- Users upload their own LinkedIn export; nothing is scraped.
- On Render, profiles are private per browser session and deleted afterwards, and the app sits
  behind a password.

## Limitations

- Scanned PDFs (images) contain no text to read; use LinkedIn's "Save to PDF" export.
- On Render, users re-upload their profile on each visit (there are no accounts or database).
- Topics far outside the Ironhack documents are refused rather than written generically.
- Posts are never published automatically.

## Project documents

- [project_structure.md](project_structure.md): goals, stakeholders, Musts M1–M8, WBS, risks
- [rag_decision.md](rag_decision.md): why hybrid, with measured retrieval results
- [agents.md](agents.md): rules for the AI coding agents working on this repo
