# RAG Decision – AI Content Creator

## 1. The question
The app has two kinds of knowledge:

| | Consultant info (primary) | Ironhack docs (secondary) |
|---|---|---|
| What | LinkedIn profile PDF, past posts, services | Program/syllabus, weekly curriculum |
| Size | Small (a few pages) | Larger, and will grow |
| Changes | Different for every user | Same for all users, changes rarely |
| Needed per request | All of it (voice, USP, experience) | Only the part that fits the topic |

Do we need RAG for both? **No. We use a hybrid approach.**

## 2. Decision
- **Consultant info → inject directly into the prompt (no RAG).**
  It is small, every part is relevant (voice comes from past posts, facts from the profile), and searching it could drop exactly the detail that makes the content unique.
- **Ironhack docs → RAG (retrieve only the relevant chunks).**
  Each post is about one topic (e.g. EU AI Act, RAG, agents). Sending the whole syllabus every time adds cost and noise and makes the model more likely to use the wrong facts.

We would switch the profile to RAG only if users upload many long documents (e.g. full publication lists) that no longer fit comfortably in the prompt.

## 3. How the RAG part works
| Step | Choice | Why |
|---|---|---|
| Loading | `document_processor.py`: markdown split at `##`, LinkedIn PDF split at its section names | Every piece keeps `source`, `file`, `heading` labels for citing |
| Chunking | `RecursiveCharacterTextSplitter`, 800 chars, 100 overlap, sentence-first separators, `keep_separator="end"` | Chunks end at sentence boundaries; overlap keeps context between chunks |
| Heading in the chunk | Each chunk is embedded as `heading + text` | A chunk "knows" its topic even if the topic word is not in its text |
| Embeddings | OpenAI `text-embedding-3-small` (1536 numbers per chunk) | Cheap, good quality, enough for a small knowledge base |
| Storage | JSON cache (`data/kb_embeddings.json`) + NumPy | 22 chunks do not need a vector database; the cache means we pay for embeddings only once |
| Search | Cosine similarity, `top_k=3`, `min_score=0.3` | Simple, transparent, easy to test |

Rule: after changing any knowledge base file, rebuild the index with `build_index(force=True)`.

## 4. Evidence (measured, not guessed)
Test run of `python src/knowledge_base.py` (22 chunks):

| Question | Top result | Score | Verdict |
|---|---|---|---|
| What will students learn about the EU AI Act? | curriculum.md – Week 7 – EU AI Act, GDPR, ethics… | 0.62 | Correct |
| Does the bootcamp cover RAG and AI agents? | curriculum.md – Week 3 – API integration patterns, RAG and Kanban | 0.49 | Correct (RAG part) |
| Best pizza in Berlin (off-topic test) | none | below 0.3 | Correctly rejected |

## 5. What we learned
1. **Headings matter.** The PDF conversion produced cut-off headings ("What you will", "bootcamp"). After fixing them by hand, retrieval changed.
2. **A higher score is not a better answer.** Before the fix, a chunk titled "bootcamp" scored 0.62 for the RAG question just because the word *bootcamp* was in both. After the fix the score dropped to 0.49, but the right chunk (Week 3 – RAG) came first. Similarity ≠ relevance.
3. **Mixed questions dilute the scores.** "RAG *and* agents" gave three results tied at 0.49, and the agents week (Week 4) did not make the top 3. For content generation we will use `top_k=4–5` so requests covering several topics get enough context.

## 6. Limitations and next steps
- The threshold 0.3 was checked on one off-topic question only; more negative tests are needed.
- Week 6 of the curriculum is still missing from the knowledge base.
- No re-ranking yet; if wrong chunks appear in the generated content, add a re-ranking step or keyword boost.
- The generator must cite the `file` and `heading` of every Ironhack fact it uses, so a reviewer can check it (grounding check).