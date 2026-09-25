#!/usr/bin/env python3
"""Fail if a shipped Markdown doc links to a path the export does not ship.

A link that 404s on the repository's front page is worse than no link: it tells a
newcomer the project is broken before they have read a line of code.

This was audited by hand once, on 2026-08-17, and the manifest still records that
audit as the reason several files are excluded. By 2026-09-05 the published tree
had **ten** dangling links, including the "Deploying to Cloud Run" link in both
READMEs and both quickstarts. That is what an un-automated check does: it is
correct on the day it is run and decays silently afterwards.

Two ways to satisfy it, and the right one depends on the target:
  * the target belongs in the public repo  -> add it to export_manifest.txt
  * the target is internal (incident logs, audits, planning docs) -> remove or
    reword the link, and do NOT export the target to silence the check

Usage:
    python scripts/check-dangling-links.py <exported-tree>
    python scripts/check-dangling-links.py            # defaults to a fresh export
    python scripts/check-dangling-links.py <tree> --check-code-paths
        also report backticked `src/...` paths that no longer exist. Advisory,
        not gated — see the note in main() for why.

Exit codes: 0 clean, 1 dangling links found, 2 could not build a tree to check.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# [text](target) — ignoring pure-anchor links and any URL scheme.
LINK = re.compile(r"\[[^\]]*\]\((?!#)([^)\s]+?)(?:#[^)]*)?\)")

# `src/foo/bar.py` — a source path in backticks. Not a link, so LINK never sees
# it, and it rots exactly the same way: the dead-code round-3 merge would have
# left `src/identity/normalizer.py` cited in two architecture docs and a
# publicly-exported ADR, and one of those docs was *already* naming an
# identity_sync.py that had been deleted earlier. Only extensions that denote a
# file in this repository are checked; prose like `pyproject.toml` in a sentence
# about some other project is not this checker's business.
CODE_PATH = re.compile(r"`((?:src|tests|scripts|tools|deploy|config)/[A-Za-z0-9_./-]+\.(?:py|sh|sql|ts|tsx|yaml|yml))`")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:")
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".pytest_cache"}


# Documentation legitimately names paths that do not exist, and the code-path
# check cannot tell those from rot by inspection. Two carve-outs, both narrow:
#
#   * docs/playbooks/** is prescriptive — it tells you what to create in *your*
#     new repository, so `scripts/guard-destructive.sh` there is an instruction,
#     not a reference.
#   * a placeholder a reader is told to create themselves.
#
# Keep this list short. Every entry is a place the checker cannot help, so a
# long list means the check is not earning its keep.
CODE_PATH_SKIP_DIRS = ("docs/playbooks/",)
CODE_PATH_ALLOW = frozenset({
    "config/readers/my_broker.yaml",   # example filename in the add-a-reader guide
})


def _readable_markdown(tree: Path):
    """Yield (path, text) for every readable .md file.

    Skips what cannot be read rather than dying on it. The private repo carries
    broken symlinks under `.agent/skills/` left by skills deleted in July, and a
    scanner that crashes on one unreadable file reports nothing about the
    hundred it could have read.
    """
    for md in sorted(tree.rglob("*.md")):
        if SKIP_DIRS & set(md.parts):
            continue
        try:
            yield md, md.read_text(errors="ignore")
        except (OSError, ValueError):
            continue


def find_dangling_code_paths(tree: Path) -> list[tuple[str, str, int]]:
    """Backticked repo paths that no longer exist.

    Resolved from the tree root, not the document, because these are written as
    repository-absolute paths regardless of where the doc lives.
    """
    out: list[tuple[str, str, int]] = []
    for md, text in _readable_markdown(tree):
        for lineno, line in enumerate(text.splitlines(), 1):
            rel = md.relative_to(tree).as_posix()
            if rel.startswith(CODE_PATH_SKIP_DIRS):
                continue
            for m in CODE_PATH.finditer(line):
                target = m.group(1)
                if target in CODE_PATH_ALLOW:
                    continue
                if not (tree / target).exists():
                    out.append((str(md.relative_to(tree)), target, lineno))
    return out


def find_dangling(tree: Path) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    for md, text in _readable_markdown(tree):
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in LINK.finditer(line):
                target = m.group(1).strip()
                if target.startswith(SKIP_PREFIXES) or target.startswith("<"):
                    continue
                resolved = (md.parent / target).resolve()
                # Anything resolving outside the tree is dangling by definition:
                # the reader has only this tree.
                try:
                    resolved.relative_to(tree.resolve())
                except ValueError:
                    out.append((str(md.relative_to(tree)), target, lineno))
                    continue
                if not resolved.exists():
                    out.append((str(md.relative_to(tree)), target, lineno))
    return out


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        tree = Path(argv[1])
        if not tree.is_dir():
            print(f"not a directory: {tree}", file=sys.stderr)
            return 2
        cleanup = None
    else:
        tree = Path(tempfile.mkdtemp(prefix="huinsight-linkcheck."))
        script = ROOT / "tools" / "release" / "export_public.sh"
        if not script.is_file():
            print("export_public.sh not found; pass a tree explicitly", file=sys.stderr)
            return 2
        proc = subprocess.run(
            ["bash", str(script), str(tree)], capture_output=True, text=True
        )
        if proc.returncode != 0:
            print(proc.stdout[-2000:], file=sys.stderr)
            print(proc.stderr[-2000:], file=sys.stderr)
            return 2
        cleanup = tree

    # Markdown links are the CI gate: a broken one is unambiguously a defect.
    dangling = find_dangling(tree)

    # Backticked source paths are opt-in, and deliberately not gated. The same
    # rot happens there — the dead-code round-3 merge left `src/identity/
    # normalizer.py` cited in two architecture docs and a published ADR — but
    # the signal-to-noise is different in kind: documentation legitimately names
    # paths that do not exist. `docs/architecture/data-pipeline-v4.md` describes
    # a superseded architecture in which those modules really did exist, and
    # rewriting it would misrepresent what was true then. A sweep of docs/ found
    # 96 such references, most of them in that category. Gating on them would
    # force either mass edits to frozen documents or an allowlist long enough to
    # mean nothing, so this runs when asked for and reports, rather than blocks.
    if "--check-code-paths" in argv:
        dangling += find_dangling_code_paths(tree)
    count = sum(1 for _ in _readable_markdown(tree))
    print(f"dangling-link check: scanned {count} markdown file(s) in {tree}")

    if dangling:
        print(f"\nFAIL — {len(dangling)} dangling reference(s):\n")
        for src, target, lineno in dangling:
            print(f"  {src}:{lineno} -> {target}")
        print(
            "\nEither add the target to tools/release/export_manifest.txt (if it "
            "belongs in the public repo) or remove/reword the link (if it is "
            "internal). Do not export an internal document just to silence this."
        )
        return 1

    scope = "link and source-path reference" if "--check-code-paths" in argv else "link"
    print(f"PASS — every internal {scope} in the shipped docs resolves")
    if cleanup:
        subprocess.run(["rm", "-rf", str(cleanup)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
