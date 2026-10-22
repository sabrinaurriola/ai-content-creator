# agents.md — AI Content Creator

## Purpose
We generate LinkedIn posts (plus blog, newsletter and Instagram drafts) in a specific
AI consultant's own voice. A post combines that consultant's LinkedIn profile (primary
knowledge base) with the Ironhack AI Consulting syllabus and industry research (secondary
knowledge base), retrieved with RAG. Every draft is reviewed and approved by a human.
Scope: see our Musts → [Musts list](LINK-TO-MUSTS)

## Stack & run
- Python 3.12 · `pip install -r requirements.txt`
- Run: `python src/main.py "topic" linkedin jane_doe` · free test run: add `--mock` · options: `--help`
- Web UI (Gradio): `python src/app.py` → http://127.0.0.1:7860 · tick "Free test run" for mock
- Env (`.env`, never committed, loaded by `main.py`): `OPENAI_API_KEY`, `LLM_MODEL`. Template: `.env.example`

## Repo map
```
knowledge_base/primary/     consultant LinkedIn profiles (.md / .pdf)
knowledge_base/secondary/   syllabus + industry research (.md)
src/document_processor.py   read, split, label, chunk documents
src/knowledge_base.py       build/load RAG index, search, filter by consultant
src/prompt_templates.py     all prompt wording: system + user prompt, revisions, baseline
src/llm_integration.py      the only file that talks to the OpenAI API
src/content_pipeline.py     runs the steps in order, saves drafts and the approved post
src/main.py                 command-line entry point, loads .env, human review
src/app.py                  Gradio web UI: same pipeline, review with buttons (UI only, no logic)
outputs/<platform>_<consultant>_<time>.md    approved post, ready to publish
outputs/drafts/             every draft + feedback (.json), generic baseline (--baseline)
```

## Conventions
- One job per file (see repo map). Prompt text only in `prompt_templates.py`; API code only in `llm_integration.py`.
- Chunks are dicts: `{"source", "file", "heading", "text"}`; `source` is `"primary"` or `"secondary"`.
- New modules go in `src/`, new documents in the matching `knowledge_base/` folder.
- `snake_case` names, small functions, short docstrings, an `if __name__ == "__main__":` self-check per module.
- Settings (models, prices, chunk sizes, paths) are constants at the top of a file or in `.env`.

## Definition of Done (same as our Trello DoD)
- Self-check of every touched file runs: `python src/<file>.py` (add `--mock` for `llm_integration.py`)
- Full flow works: `python src/main.py "topic" linkedin <consultant> --mock` → draft, feedback rewrite, Enter approves
- `outputs/<platform>_<consultant>_<time>.md` exists, drafts are in `outputs/drafts/`
- Needs a working `knowledge_base.py` (`build_index`, `search`); the pipeline stops with a clear message until then
- Card's Must ID is met; no secrets or personal data in the commit

## Never do
- Commit `.env`, API keys, `knowledge_base/primary/` or `outputs/`
- Invent experiences, clients, numbers or credentials for a consultant, or weaken the anti-fabrication rules in the prompt
- Mix consultants: primary retrieval is always filtered by the selected consultant
- Auto-publish anything; approval stays a human step
- Make real API calls in loops or tests without asking (use `mock`)
- Build anything on the Won't list, or decide our open questions (syllabus as content? RAG vs. context injection?) without the team

## How we use agents
- One Trello card at a time; every prompt names the card and its Must ID.
- The agent says which files it will touch before editing, and stops to ask if the card needs more.