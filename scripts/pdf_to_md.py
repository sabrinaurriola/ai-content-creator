"""One-off: turn the useful syllabus pages into knowledge_base/secondary/program.md"""
import re
from pypdf import PdfReader

reader = PdfReader("Syllabus_AC_EN_2026.pdf")
KEEP_PAGES = range(7, 17)                     # pages 7–16 (1-based)

def fix_spaced_letters(line):
    """'L e a r n i n g' -> 'Learning' (only lines made of single letters)."""
    if re.fullmatch(r"(\S )+\S", line.strip()):
        return line.replace(" ", "")
    return line

parts = ["# Ironhack AI Consulting Bootcamp – Program (Syllabus 2026)\n"]
for n in KEEP_PAGES:
    text = reader.pages[n - 1].extract_text() or ""
    lines = [fix_spaced_letters(l) for l in text.splitlines() if l.strip()]
    title = lines[0] if lines else f"Page {n}"
    parts.append(f"\n## {title} (syllabus p.{n})\n" + "\n".join(lines[1:]))

with open("knowledge_base/secondary/program.md", "w", encoding="utf-8") as f:
    f.write("\n".join(parts))
print("✅ program.md written")