# Project Structure – VoicePrint (AI Content Creator)

## 1. Project identity
- **Project name:** VoicePrint (AI Content Creator)
- **Primary project type:** R&D (new prototype; the method is not proven yet)
- **Defined goal (1 sentence):** Turn an AI consultant's LinkedIn profile, past posts and services, plus Ironhack program facts, into LinkedIn, Instagram and newsletter content that sounds like that consultant and is clearly different from generic ChatGPT output.
- **Start / end:** Day 1 morning (W3D4) → Day 2 presentation (W3D5)
- **Why this is a project:** ☑ defined goal ☑ limited resources ☑ interdisciplinary ☑ responsibility for results ☑ complex ☑ novel ☑ defined start/end

## 2. Objectives (Quality / Time / Cost)
| Constraint | Our objective |
|---|---|
| **Quality** | Every generated piece uses the consultant's own voice and experience, and contains only facts that exist in the knowledge base. A reader should be able to tell it apart from a generic AI post. |
| **Time** | Hard deadline: Day 2 presentation. Internal milestone: end of Day 1 – knowledge base loads and the LLM responds with KB context. |
| **Cost** | Embeddings are built once and cached; test with a small, cheap model and few calls; API keys stay in `.env` only. Budget: [team to confirm, e.g. under $5 for the sprint]. |

## 3. Stakeholder analysis
| Role | Interest | Influence | Quadrant | Engagement in this project |
|---|---|---|---|---|
| AI consultant (end user, e.g. Ironhack graduate) | H | H | II – manage closely | Their profile/posts are the input; we test with a real profile and check "does this sound like me?" |
| Ironhack (KB owner, brand) | H | M | II – manage closely | Program facts only from official docs; Ironhack is a credential in the post, not the hero |
| Instructors / evaluators | M | H | IV – keep satisfied | Deliverables match the rubric; demo + uniqueness proof on Day 2 |
| Consultant's audience (followers, potential clients) – non-builder | H | L | I – keep informed | Content must be useful and credible to them; no invented facts |
| Project team (3 builders) | H | H | II – manage closely | Kanban, WIP 2, one card per person, shared `agents.md` |
| People whose data is in profiles (GDPR) – non-builder | M | L | I – keep informed | No scraping, user uploads own PDF, no other people's real profiles in the public repo |

## 4. Requirements → implementation
**Use case (1 sentence):** An AI consultant uploads their LinkedIn PDF and past posts and gets a ready-to-edit LinkedIn post, Instagram caption or newsletter section that promotes their skills and USP.

**Must have:**
| ID | Must requirement | Maps to (file / module) | How we verify |
|---|---|---|---|
| M1 | Ingest primary KB (profile PDF, past posts, services) | `src/document_processor.py` (`load_user_profile`) + `knowledge_base/primary/` | Run file: profile → 8 labelled pieces; posts and services split at `##` |
| M2 | Ingest secondary KB (Ironhack program + curriculum) | `src/document_processor.py` + `src/knowledge_base.py` + `knowledge_base/secondary/` | 22 chunks indexed; test questions return the right week (EU AI Act → Week 7) |
| M3 | Call LLM with KB context | `src/llm_client.py` [name to confirm] | Output mentions real profile facts and retrieved Ironhack facts |
| M4 | Reusable prompt templates (≥2) | `src/prompts.py` [name to confirm] – LinkedIn, Instagram, newsletter | Same topic → three different formats, same voice |
| M5 | End-to-end pipeline command | `src/main.py` [name to confirm] | One command produces content from PDF + topic |
| M6 | Uniqueness evidence vs ChatGPT | `docs/uniqueness.md` | Same request in ChatGPT vs our app, side by side, differences listed |
| M7 | RAG decision documented | `rag_decision.md` | Choice + ≥3 criteria + measured retrieval results |
| M8 | Project structured + agents guided | `project_structure.md`, `agents.md` | Sections complete; agents.md referenced in agent prompts |

**Won't have this sprint:**
| Won't | Why deferred |
|---|---|
| LinkedIn link input / LinkedIn API / scraping | Login wall, terms of service and GDPR; PDF export works |
| Auto-publishing to LinkedIn/Instagram | Needs platform APIs and approval; human review comes first |
| Image or video generation for Instagram | Text quality and uniqueness are the priority |
| Vector database, user accounts | 22 chunks fit in a JSON cache; one user at a time is enough for the MVP |

## 5. WBS (2 levels) → Trello cards
```
1. Structure & board
   1.1 Write project_structure.md
   1.2 Create Trello lists + WIP 2 + DoD
   1.3 Write agents.md
   1.4 Create cards from this WBS
2. Knowledge bases
   2.1 Primary set: profile PDF, past_posts.md, services.md
   2.2 Secondary set: program.md (syllabus), curriculum.md
3. Ingest & context
   3.1 Document processor (markdown + LinkedIn PDF + user upload)
   3.2 Knowledge base: embeddings, cached index, cosine search; profile injected
4. Generate & differentiate
   4.1 LLM client + .env (+ .env.example)
   4.2 Prompt templates: LinkedIn, Instagram, newsletter
   4.3 End-to-end pipeline command
   4.4 Uniqueness comparison vs ChatGPT
5. Close
   5.1 Finalize rag_decision.md (+ §7)
   5.2 README + demo prep
   5.3 Day 1 / Day 2 board screenshots
```

## 6. Risks
| Risk | P | I | Strategy | Concrete action |
|---|---|---|---|---|
| Generic "AI slop" that sounds like any ChatGPT post | H | H | Reduction | Inject the consultant's past posts as voice examples; uniqueness test by Day 2 noon; refine prompts from the comparison |
| Invented facts about the consultant or Ironhack | M | H | Reduction | Prompts allow only facts from the KB; cite file + heading of every Ironhack fact; human review before posting |
| API key leaked in the public repo (happened once on Day 1) | M | H | Mitigation | `.env` in `.gitignore`, `.env.example` committed instead, `git status` before every commit, exposed key rotated immediately |

## 7. Bridge to `rag_decision.md`
The consultant needs content that sounds like them and contains only true facts, so the Quality objective drives our context strategy. M1 and M6 need the whole consultant profile and past posts in every prompt, so we inject them in full: retrieval could drop the very details that make the content unique. M2 and M3 need only the Ironhack facts that fit the chosen topic, and the syllabus is too large and noisy to send every time, so we retrieve those chunks. **Decision:** hybrid – inject the profile, retrieve Ironhack facts (cosine search, top-k, threshold 0.3). Revisit when users upload many or long documents, or when the Ironhack corpus grows beyond what a JSON cache handles well.