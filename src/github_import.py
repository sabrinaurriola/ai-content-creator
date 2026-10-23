"""Turn a public GitHub profile into a short markdown portfolio (github.md).

Uses the free GitHub REST API (no login needed, 60 requests/hour).
Set GITHUB_TOKEN in .env for a higher limit. About 9 requests per import.
"""
import json
import os
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API = "https://api.github.com"
MAX_REPOS = 6                 # top projects kept (by stars, then most recently updated)
README_CHARS = 600            # summary length per project README
PROFILE_README_CHARS = 1000   # the user's profile README (repo named after the user)
TIMEOUT_S = 15


# ---------- 1. Read the link ----------
def parse_username(link):
    """'https://github.com/janedoe', 'github.com/janedoe/' or 'janedoe' -> 'janedoe'."""
    link = link.strip()
    match = re.search(r"github\.com/([A-Za-z0-9-]+)", link) or re.fullmatch(r"@?([A-Za-z0-9-]+)", link)
    if not match:
        raise ValueError(f"Not a GitHub profile link: {link}")
    return match.group(1)


# ---------- 2. Call the API ----------
def _get(path, raw=False):
    """GET one API path; JSON by default, plain text for README files."""
    headers = {"User-Agent": "ai-content-creator",
               "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json"}
    if os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.getenv('GITHUB_TOKEN')}"
    try:
        with urlopen(Request(API + path, headers=headers), timeout=TIMEOUT_S) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        if error.code == 404:
            return None
        if error.code in (403, 429):
            raise ValueError("GitHub rate limit reached. Try again in an hour "
                             "or add GITHUB_TOKEN to .env.") from error
        raise ValueError(f"GitHub error {error.code} for {path}") from error
    except URLError as error:
        raise ValueError(f"Could not reach GitHub: {error.reason}") from error
    return body if raw else json.loads(body)


# ---------- 3. Clean README text ----------
def clean_readme(text, limit):
    """Drop images, badges, HTML, code blocks and heading marks; cut at a word boundary."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)            # code blocks
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)             # images and badges
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)          # links -> their text
    text = re.sub(r"<[^>]+>", " ", text)                          # HTML tags
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)             # '## Title' -> 'Title'
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


# ---------- 4. Build the portfolio ----------
def _top_repos(repos, username):
    """Own, non-empty projects; most stars first, then most recently updated."""
    own = [r for r in repos if not r["fork"] and r["name"].lower() != username.lower()
           and r.get("size", 0) > 0]
    own.sort(key=lambda r: (r["stargazers_count"], r["pushed_at"] or ""), reverse=True)
    return own[:MAX_REPOS]


def github_markdown(link):
    """Return (markdown, number of projects) for a GitHub profile link."""
    username = parse_username(link)
    user = _get(f"/users/{username}")
    if user is None:
        raise ValueError(f"GitHub user not found: {username}")

    lines = [f"# GitHub portfolio – {user['login']}", "", "## GitHub profile"]
    for label, key in [("Name", "name"), ("Bio", "bio"), ("Company", "company"),
                       ("Location", "location"), ("Website", "blog")]:
        if user.get(key):
            lines.append(f"{label}: {user[key]}")
    lines.append(f"Profile: {user['html_url']} · {user['public_repos']} public repositories")
    profile_readme = _get(f"/repos/{username}/{username}/readme", raw=True)
    if profile_readme:
        lines.append(f"Profile README: {clean_readme(profile_readme, PROFILE_README_CHARS)}")

    repos = _top_repos(_get(f"/users/{username}/repos?per_page=100&sort=updated") or [], username)
    for repo in repos:
        lines += ["", f"## Project: {repo['name']}"]
        if repo.get("description"):
            lines.append(f"Description: {repo['description']}")
        updated = datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00")).date()
        facts = [f"Language: {repo['language'] or 'n/a'}",
                 f"Stars: {repo['stargazers_count']}", f"Last updated: {updated}"]
        if repo.get("topics"):
            facts.insert(1, f"Topics: {', '.join(repo['topics'])}")
        lines += [" · ".join(facts), f"URL: {repo['html_url']}"]
        readme = _get(f"/repos/{username}/{repo['name']}/readme", raw=True)
        if readme:
            lines.append(f"README summary: {clean_readme(readme, README_CHARS)}")
    return "\n".join(lines) + "\n", len(repos)


# ---------- Self-check: python src/github_import.py [link]   (GitHub API, free) ----------
if __name__ == "__main__":
    import sys
    assert parse_username("https://github.com/janedoe/") == "janedoe"
    assert parse_username("github.com/jane-doe?tab=repositories") == "jane-doe"
    assert parse_username("@janedoe") == "janedoe"
    assert clean_readme("# Title\n![badge](x.svg) See [docs](http://d).", 100) == "Title See docs."
    print("✅ link parsing and README cleaning")

    markdown, count = github_markdown(sys.argv[1] if len(sys.argv) > 1 else "octocat")
    print(f"✅ {count} projects, {len(markdown)} chars\n")
    print(markdown[:800])
