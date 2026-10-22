"""
main.py
AI Content Creator - Entry point

Run:  python src/main.py            (provider from .env, default openai)
      python src/main.py mock       (free test run, no API key needed)
"""
import sys

from content_pipeline import ContentPipeline
from prompt_templates import PLATFORM_RULES, FORMAT_RULES


def choose(label, options, default=None):
    """Show a numbered list and return the chosen option."""
    print(f"\n{label}")
    for i, option in enumerate(options, 1):
        marker = " (default)" if option == default else ""
        print(f"  {i}. {option}{marker}")
    while True:
        answer = input("> ").strip()
        if not answer and default:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        print("  Please type a number from the list.")


def ask(label, default):
    answer = input(f"{label} [{default}]: ").strip()
    return answer or default


def show(version):
    print("\n" + "=" * 60)
    if version["status"] == "failed":
        print(f"❌ Generation failed: {version['error']}")
    else:
        print(f"📝 Version {version['version']}  ({version['model']}, "
              f"{version['input_tokens']}+{version['output_tokens']} tokens, "
              f"{version['latency_s']}s)")
        print("=" * 60 + "\n" + version["text"])
    print("=" * 60)


def main():
    provider = sys.argv[1] if len(sys.argv) > 1 else None
    pipeline = ContentPipeline(provider=provider)

    # 1. Document
    print("📚 Loading knowledge base...")
    stats = pipeline.prepare_knowledge_base()
    print(f"   {stats['pieces']} pieces, {stats['rag_chunks']} RAG chunks, "
          f"retrieval: {'RAG index' if stats['rag'] else 'keyword search (temporary)'}")
    if not stats["consultants"]:
        sys.exit("No consultant profiles found in knowledge_base/primary/.")

    # 2. Collect the request (Monitor suggestions included)
    consultant = choose("Which consultant?", stats["consultants"])
    ideas = pipeline.suggest_topics()
    if ideas:
        print("\n💡 Topic ideas from the research documents:")
        for idea in ideas:
            print(f"   - {idea}")
    topic = ""
    while not topic:
        topic = input("\nTopic: ").strip()

    request = {
        "topic": topic,
        "platform": choose("Platform?", list(PLATFORM_RULES), "linkedin"),
        "format": choose("Format?", list(FORMAT_RULES), "professional_insight"),
        "audience": ask("Audience", "Business leaders"),
        "objective": ask("Objective", "Educate"),
        "additional_instructions": input("Extra instructions (optional): ").strip(),
    }

    # 3. Brief + 4. Publish
    session = pipeline.start_session(consultant, request)
    print("\n🔎 Sources used:")
    for source in session["brief"]["sources"] or ["(none found)"]:
        print(f"   {source}")
    show(pipeline.run(session))

    # 5. Iterate until approved or quit
    while True:
        action = input("\n[a]pprove  [r]evise  [b]aseline (generic)  [q]uit > ").strip().lower()
        if action == "a":
            try:
                pipeline.approve(session)
                print(f"✅ Approved. Saved in {session['folder']}")
                break
            except ValueError as error:
                print(f"⚠️  {error}")
        elif action == "r":
            feedback = input("Your feedback: ").strip()
            if feedback:
                show(pipeline.run(session, feedback=feedback))
        elif action == "b":
            result = pipeline.generate_baseline(session)
            print("\n--- Generic baseline (no brand voice, no RAG) ---")
            print(result["text"] if result["status"] == "success" else result["error"])
        elif action == "q":
            print(f"💾 Drafts saved in {session['folder']}")
            break


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")