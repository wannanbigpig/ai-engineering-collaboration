#!/usr/bin/env python3
"""Check distributable Skill resources and propagate every required check's failure."""
from __future__ import annotations

import argparse
from html import unescape
import os
from pathlib import Path
import re
import subprocess
import string
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
LINK_LABEL = r"(?<!\\)\[((?:\\.|[^\]\\\n])*)\]"
LINK_TITLE = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^)\\])*\))'''


def link_destination(text: str, start: int = 0) -> tuple[str, int] | None:
    """Read an angle-delimited or balanced bare destination, leaving its title."""
    while start < len(text) and text[start].isspace():
        start += 1
    if start < len(text) and text[start] == "<":
        match = re.match(r"<((?:\\.|[^<>\\\n])*)>", text[start:])
        return (match.group(1), start + match.end()) if match else None
    end, depth = start, 0
    while end < len(text):
        char = text[end]
        if char == "\\" and end + 1 < len(text):
            end += 2
            continue
        if char.isspace() or (char == ")" and depth == 0):
            break
        if char in "<>":
            return None
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        end += 1
    return (text[start:end], end) if depth == 0 else None


def markdown_link_targets(text: str) -> list[str]:
    """Read common inline/image/reference links, excluding fenced and inline code.

    This is a bounded resource check, not a CommonMark renderer: HTML links,
    nested containers/labels and multiline reference definitions are not parsed.
    """
    visible, fence = [], ""
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = ""
            visible.append("\n")
        elif marker:
            fence = marker[1]
            visible.append("\n")
        else:
            visible.append(line)
    text = re.sub(r"(?<![\\`])(`+)(?!`)(.*?)(?<!`)\1(?!`)",
                  lambda match: re.sub(r"[^\n]", " ", match[0]), "".join(visible), flags=re.DOTALL)
    definitions = {}
    normalize = lambda label: " ".join(label.split()).casefold()

    def read_definition(match: re.Match) -> str:
        destination = link_destination(match[2])
        if destination and re.fullmatch(rf"[ \t]*(?:{LINK_TITLE})?[ \t]*", match[2][destination[1]:]):
            definitions.setdefault(normalize(match[1]), destination[0])
            return ""
        return match[0]

    text = re.sub(rf"(?m)^ {{0,3}}{LINK_LABEL}:[ \t]*(.*)$", read_definition, text)
    targets = []
    for label in re.finditer(LINK_LABEL, text):
        end = label.end()
        if text[end:end + 1] == "(":
            destination = link_destination(text, end + 1)
            if destination and re.match(rf"\s*(?:{LINK_TITLE})?\s*\)", text[destination[1]:]):
                targets.append(destination[0])
        else:
            reference = re.match(LINK_LABEL, text[end:])
            key = normalize((reference[1] or label[1]) if reference else label[1])
            if key in definitions:
                targets.append(definitions[key])
    return list(dict.fromkeys(unescape(re.sub(r"\\([" + re.escape(string.punctuation) + r"])", r"\1", target))
                              for target in targets))


def check_packages(root: Path) -> list[str]:
    errors = []
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as error:
        version = ""
        errors.append(f"Cannot read VERSION: {error}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.append("VERSION must contain a release version such as 1.7.12")
    skills = sorted(path for path in (root / "skills").glob("*") if path.is_dir())
    if not skills:
        errors.append("No Skill packages found")
    for skill in skills:
        entry = skill / "SKILL.md"
        if not entry.is_file():
            errors.append(f"{entry}: missing SKILL.md")
            continue
        body = entry.read_text(encoding="utf-8")
        match = re.search(r"^  version: (.+)$", body, re.MULTILINE)
        if not match or match.group(1) != version:
            errors.append(f"{entry}: metadata.version differs from VERSION ({version})")
        # Validate each package in isolation: a resource in a sibling Skill is
        # unavailable to users who install this Skill alone.
        for document in sorted(skill.rglob("*.md")):
            for target in markdown_link_targets(document.read_text(encoding="utf-8")):
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                resource = (document.parent / unquote(parsed.path)).resolve()
                if not resource.is_relative_to(skill.resolve()):
                    errors.append(f"{document}: resource outside standalone package: {target}")
                elif not resource.exists():
                    errors.append(f"{document}: missing resource: {target}")
    return errors


def run_check(command: list[str], root: Path) -> int:
    print("Checking: " + " ".join(command), flush=True)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_OPTIONAL_LOCKS="0")
    try:
        return subprocess.run(command, cwd=root, env=environment, check=False).returncode
    except OSError as error:
        print(f"Cannot run check: {error}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--offline", action="store_true", help="Skip the external Agent Skills validator; report this gap explicitly.")
    parser.add_argument("--tests", action="store_true", help="Also run the repository's full unit tests.")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        errors = check_packages(root)
    except (OSError, UnicodeError, ValueError) as error:
        errors = [f"Cannot validate package content: {error}"]
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Release versions and standalone package resources: passed", flush=True)
    commands = []
    if args.offline:
        print("Agent Skills schema validation: NOT RUN (--offline)", flush=True)
    else:
        commands.extend(["uvx", "--from", "skills-ref==0.1.1", "agentskills", "validate", str(skill)]
                        for skill in sorted((root / "skills").iterdir()) if skill.is_dir())
    commands.append(["git", "diff", "--check"])
    commands.append(["git", "diff", "--cached", "--check"])
    if args.tests:
        commands.append([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"])
    for command in commands:
        status = run_check(command, root)
        if status:
            return status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
