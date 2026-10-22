"""
main.py
AI Content Creator - Entry point

Run:
    python src/main.py "When should companies use RAG?" linkedin jane_doe
    python src/main.py "When should companies use RAG?" linkedin jane_doe --mock   (free test)
    python src/main.py --help                                                      (all options)
"""
import argparse
import sys

from dotenv import load_dotenv

from content_pipeline import ContentPipeline
from prompt_templates import PLATFORM_RULES, FORMAT_RULES, DEFAULT_FORMAT

REVIEW_QUESTION = "\nFeedback to rewrite, Enter to approve, q to quit: "


# --------------------------------------------------
# 1. COMMAND-LINE INPUT
# --------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Write a post in a consultant's own voice.")
    parser.add_argument("topic", help='What the post is about, e.g. "When should companies use RAG?"')
    parser.add_argument("platform", choices=list(PLATFORM_RULES), type=str.lower)
    parser.add_argument("consultant", help="Profile file name without extension, e.g. jane_doe")
    parser.add_argument("--format", default=DEFAULT_FORMAT, choices=list(FORMAT_RULES))
    parser.add_argument("--audience", default="Business leaders")
    parser.add_argument("--objective", default="Educate")
    parser.add_argument("--extra", default="", help="Extra instructions for the writer")
    parser.add_argument("--mock", action="store_true", help="Free test run, no API call")
    parser.add_argument("--baseline", action="store_true",
                        help="Also save a generic post (no brand voice, no RAG) for comparison")
    return parser.parse_args()


# --------------------------------------------------
# 2. DISPLAY
# --------------------------------------------------

def show(version):
    print("\n" + "=" * 60)
    if version["status"] == "failed":
        print(f"❌ Generation failed: {version['error']}")
        print("   Press Enter to try again, or q to quit.")
    else:
        print(f"📝 Draft {version['version']}  ({version['model']}, "
              f"{version['input_tokens']}+{version['output_tokens']} tokens, "
              f"{version['latency_s']}s)")
        print("=" * 60 + "\n" + version["text"])
    print("=" * 60)


# --------------------------------------------------
# 3. RUN: build prompt -> draft -> human review -> save
# --------------------------------------------------

def main():
    load_dotenv()
    args = parse_args()
    pipeline = ContentPipeline(mock=args.mock)

    try:
        stats = pipeline.prepare_knowledge_base()
        request = {"topic": args.topic, "platform": args.platform, "format": args.format,
                   "audience": args.audience, "objective": args.objective,
                   "additional_instructions": args.extra}
        session = pipeline.start_session(args.consultant, request)
    except (RuntimeError, ValueError, FileNotFoundError) as error:
        sys.exit(f"❌ {error}")

    print(f"📚 {stats['pieces']} pieces loaded · consultant: {session['consultant']}")
    print("🔎 Sources used:")
    for source in session["sources"] or ["(none found)"]:
        print(f"   {source}")
    show(pipeline.run(session))

    # Human review: feedback -> rewrite, Enter -> approve, q -> quit
    while True:
        answer = input(REVIEW_QUESTION).strip()
        latest = session["versions"][-1]

        if answer.lower() == "q":
            print("Stopped without approving. Drafts are in outputs/drafts/.")
            return
        if not answer and latest["status"] == "failed":
            show(pipeline.run(session, feedback=latest["feedback"]))   # retry same request
        elif not answer:
            path = pipeline.approve(session)
            print(f"✅ Approved and saved: {path}")
            break
        else:
            show(pipeline.run(session, feedback=answer))      # rewrite

    if args.baseline:
        try:
            print(f"📄 Generic baseline saved: {pipeline.generate_baseline(session)}")
        except RuntimeError as error:
            print(f"⚠️  Baseline failed: {error}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped without approving.")