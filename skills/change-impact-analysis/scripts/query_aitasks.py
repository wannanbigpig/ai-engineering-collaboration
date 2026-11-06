#!/usr/bin/env python3
"""Read bounded .aitasks records without loading maintenance or writing files.

This is the authoritative record parser and read-only query implementation.
Consumer Skill copies are generated from this file; edit this source only.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ALIASES = (
    ("timeout", "超时"),
    ("retry", "retries", "重试"),
    ("timezone", "时区"),
    ("idempotency", "幂等"),
    ("refund", "退款"),
)


MARKER_PATTERN = re.compile(
    r"^ {0,3}<!--[ \t]*aitasks:(?P<kind>lesson|todo)[ \t]+(?P<fields>[^\r\n]*?)[ \t]*-->[ \t]*(?=\r?$)",
    re.MULTILINE,
)


FIELD_PATTERN = re.compile(r"(?P<key>[a-z_]+)=(?P<value>[^\s]+)")


HEADING_PATTERN = re.compile(r"^#{1,6}[ \t]+(?P<title>[^\r\n]+?)[ \t]*(?=\r?$)", re.MULTILINE)


FENCE_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass
class Record:
    kind: str
    raw: str
    fields: dict[str, str]
    start: int
    end: int

    @property
    def title(self) -> str:
        match = HEADING_PATTERN.search(self.raw)
        return match.group("title") if match else "<untitled>"

    @property
    def stable_id(self) -> str:
        """Stable content-derived id; honours an explicit id= field if present."""
        existing = self.fields.get("id")
        if existing:
            return existing
        return record_id(self.kind, self.title, self.fields.get("created_at", ""))

    def render(self) -> str:
        marker = MARKER_PATTERN.match(self.raw)
        original = parse_fields(marker.group("fields"))
        if original == self.fields:
            return self.raw
        fields = FIELD_PATTERN.sub(
            lambda match: f"{match.group('key')}={self.fields[match.group('key')]}",
            marker.group("fields"),
        )
        fields += "".join(f" {key}={value}" for key, value in self.fields.items() if key not in original)
        return self.raw[:marker.start("fields")] + fields + self.raw[marker.end("fields"):]

    def with_archive_id(self) -> Record:
        """Copy whose marker carries an explicit stable id= field."""
        fields = dict(self.fields)
        fields["id"] = self.stable_id
        return Record(
            kind=self.kind, raw=self.raw, fields=fields, start=self.start, end=self.end
        )


def record_id(kind: str, title: str, created_at: str) -> str:
    """Deterministic id for a record: sha1(kind|title|created_at), 12 hex chars."""
    digest = hashlib.sha1(
        f"{kind}|{title}|{created_at}".encode("utf-8")
    ).hexdigest()
    return digest[:12]


@dataclass(frozen=True)
class RecordFile:
    path: Path
    text: str
    records: list[Record]


def parse_fields(value: str) -> dict[str, str]:
    return {
        match.group("key"): match.group("value")
        for match in FIELD_PATTERN.finditer(value)
    }


def unfenced_matches(text: str, pattern: re.Pattern[str]) -> list[re.Match[str]]:
    """Match line-start syntax outside Markdown code fences."""
    matches: list[re.Match[str]] = []
    fence = ""
    offset = 0
    for line in text.splitlines(keepends=True):
        fence_match = FENCE_PATTERN.match(line)
        if fence_match:
            delimiter = fence_match.group(1)
            if not fence:
                fence = delimiter
            elif (
                delimiter[0] == fence[0]
                and len(delimiter) >= len(fence)
                and not line[fence_match.end() :].strip()
            ):
                fence = ""
        elif not fence:
            match = pattern.match(text, offset)
            if match:
                matches.append(match)
        offset += len(line)
    return matches


def record_markers(text: str, kind: str | None = None) -> list[re.Match[str]]:
    """Metadata must directly precede its heading, not appear in an example."""
    headings = unfenced_matches(text, HEADING_PATTERN)
    positions = [heading.start() for heading in headings]
    markers: list[re.Match[str]] = []
    for marker in unfenced_matches(text, MARKER_PATTERN):
        if kind is not None and marker.group("kind") != kind:
            continue
        index = bisect.bisect_left(positions, marker.end())
        if index < len(headings) and not text[marker.end() : headings[index].start()].strip():
            markers.append(marker)
    return markers


def read_markdown(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def load_record_file(path: Path, kind: str, text: str | None = None) -> RecordFile:
    if text is None and not path.exists():
        return RecordFile(path=path, text="", records=[])

    if text is None:
        text = read_markdown(path)
    markers = record_markers(text, kind)
    headings = unfenced_matches(text, HEADING_PATTERN)
    heading_positions = [heading.start() for heading in headings]
    if not markers:
        return RecordFile(path=path, text=text, records=[])

    records: list[Record] = []
    for index, marker in enumerate(markers):
        next_marker_start = (
            markers[index + 1].start() if index + 1 < len(markers) else len(text)
        )
        end = next_marker_start
        heading_index = bisect.bisect_left(heading_positions, marker.end())
        if heading_index < len(headings) and headings[heading_index].start() < next_marker_start:
            heading = headings[heading_index]
            heading_level = len(heading.group(0)) - len(heading.group(0).lstrip("#"))
            next_heading_index = bisect.bisect_left(
                heading_positions, next_marker_start, heading_index + 1
            )
            for candidate in headings[heading_index + 1 : next_heading_index]:
                candidate_level = len(candidate.group(0)) - len(
                    candidate.group(0).lstrip("#")
                )
                if candidate_level <= heading_level:
                    end = candidate.start()
                    break
        records.append(
            Record(
                kind=kind,
                raw=text[marker.start() : end],
                fields=parse_fields(marker.group("fields")),
                start=marker.start(),
                end=end,
            )
        )
    return RecordFile(path=path, text=text, records=records)


def project_files(project_root: Path) -> tuple[Path, Path, Path, Path]:
    root = project_root.expanduser().resolve()
    aitasks = root / ".aitasks"
    return (
        aitasks / "lessons.md",
        aitasks / "todo.md",
        aitasks / ".maintenance.json",
        aitasks / "archive",
    )


def lesson_json(record_file: RecordFile, record: Record) -> dict:
    """Return one record with its own metadata and original source coordinates."""
    raw_count = record.fields.get("use_count")
    use_count = None
    count_status = "missing"
    if raw_count is not None:
        try:
            use_count = int(raw_count)
            if use_count < 0:
                raise ValueError("negative use_count")
            count_status = "recorded"
        except ValueError:
            use_count = None
            count_status = "invalid"
    text = record_file.text
    heading = HEADING_PATTERN.search(text, record.start, record.end)
    content = record.raw
    marker = MARKER_PATTERN.match(content)
    if marker:
        content = content[marker.end():].lstrip("\r\n")
    content_end = record.start + len(text[record.start:record.end].rstrip())
    return {
        "title": record.title,
        "content": content.rstrip(),
        "metadata": dict(record.fields) if record.fields else None,
        "use_count": use_count,
        "use_count_status": count_status,
        "source": {
            "path": str(record_file.path.resolve()),
            "start_line": text.count("\n", 0, record.start) + 1,
            "end_line": text.count("\n", 0, content_end) + 1,
            "title_line": text.count("\n", 0, heading.start()) + 1 if heading else None,
        },
    }


def searchable_lesson_records(record_file: RecordFile) -> list[Record]:
    """Include headed legacy sections for search only, never for maintenance.

    Metadata records keep their existing boundaries and output. Uncovered
    sections become read-only records with empty fields; nested headings stay
    in their parent section so one lesson cannot appear multiple times.
    """
    text = record_file.text
    headings: list[tuple[int, int]] = []
    for heading in unfenced_matches(text, HEADING_PATTERN):
        headings.append((heading.start(), len(heading.group(0)) - len(heading.group(0).lstrip("#"))))

    # A sole leading H1 with child headings is the document title.
    if (
        len(headings) > 1
        and headings[0][1] == 1
        and sum(level == 1 for _, level in headings) == 1
    ):
        headings = headings[1:]

    records = list(record_file.records)
    cursor = 0
    gaps: list[tuple[int, int]] = []
    for record in record_file.records:
        gaps.append((cursor, record.start))
        cursor = record.end
    gaps.append((cursor, len(text)))

    for start, end in gaps:
        section_start: int | None = None
        section_level = 0
        for heading_start, level in headings:
            if not start <= heading_start < end:
                continue
            if section_start is not None and level > section_level:
                continue
            if section_start is not None:
                records.append(
                    Record(
                        "lesson",
                        text[section_start:heading_start],
                        {},
                        section_start,
                        heading_start,
                    )
                )
            section_start, section_level = heading_start, level
        if section_start is not None:
            records.append(
                Record(
                    "lesson", text[section_start:end],
                    {}, section_start, end,
                )
            )
    return sorted(records, key=lambda record: record.start)


def record_content(record: Record) -> str:
    marker = MARKER_PATTERN.match(record.raw)
    return (record.raw[marker.end():] if marker else record.raw).strip()


def record_summary(record: Record) -> dict:
    body = record_content(record)
    scope = re.search(r"^- 适用范围：[ \t]*(.+)$", body, re.MULTILINE)
    preview = " ".join(line.strip() for line in body.splitlines() if not line.startswith("#"))
    return {"id": record.stable_id, "title": record.title[:80],
            "scope": scope.group(1).strip()[:100] if scope else "",
            "preview": preview[:120]}


def lesson_status(record: Record) -> str:
    return record.fields.get("status", "active")


def query_concepts(project_root: Path, terms: list[str]) -> list[tuple[str, ...]]:
    """Expand curated aliases locally; overlapping groups form one search concept."""
    groups: list[set[str]] = []
    local = Path(__file__).resolve().parent.parent / "assets/search-aliases.json"
    project = project_files(project_root)[0].parent / "search-aliases.json"
    sources = [(local, None)] if local.exists() else [("built-in aliases", DEFAULT_ALIASES)]
    if project.exists():
        sources.append((project, None))
    for path, data in sources:
        if data is None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as error:
                raise SystemExit(f"invalid aliases at {path}: {error}") from error
        else:
            data = [list(group) for group in data]
        if not isinstance(data, list) or any(not isinstance(group, list) or len(group) < 2
                or any(not isinstance(term, str) or not term.strip() for term in group) for group in data):
            raise SystemExit(f"aliases at {path} must be a JSON list of groups of at least two nonempty strings")
        for group in data:
            merged = {term.strip().casefold() for term in group}
            others = []
            for existing in groups:
                if existing & merged:
                    merged.update(existing)
                else:
                    others.append(existing)
            groups = others + [merged]
    concepts = []
    for term in terms:
        concept = tuple(sorted(next((group for group in groups if term in group), {term})))
        if concept not in concepts:
            concepts.append(concept)
    return concepts


def ranked_records(record_file: RecordFile, concepts: list[tuple[str, ...]], kind: str) -> list[tuple]:
    records = searchable_lesson_records(record_file) if kind == "lesson" else record_file.records
    found = []
    for record in records:
        if kind == "lesson" and lesson_status(record) != "active":
            continue
        title, content = record.title.casefold(), record_content(record).casefold()
        hits = sum(any(term in content for term in concept) for concept in concepts)
        title_hits = sum(any(term in title for term in concept) for concept in concepts)
        if hits or not concepts:
            score = (-hits, -title_hits, record.fields.get("pinned", "false").lower() != "true")
            found.append((score, record_file, record))
    return sorted(found, key=lambda item: item[0])


def bounded_json(payload: dict, max_chars: int) -> str:
    """Bound the serialized response, not the local scan or only the number of rows."""
    if max_chars < 512:
        raise SystemExit("--max-chars must be at least 512")
    max_chars -= 1  # print() adds one trailing newline to the tool response.
    encode = lambda: json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    text = encode()
    while len(text) > max_chars:
        collections = [payload[key] for key in ("lessons", "todos", "observations") if payload.get(key)]
        if not collections:
            break
        max(collections, key=lambda rows: len(json.dumps(rows[-1], ensure_ascii=False))).pop()
        payload["truncated"] = True
        text = encode()
    if len(text) > max_chars and "content" in payload:
        content = payload["content"]
        payload["truncated"] = True
        low, high = 0, len(content)
        while low < high:
            middle = (low + high + 1) // 2
            payload["content"] = content[:middle]
            if len(encode()) <= max_chars:
                low = middle
            else:
                high = middle - 1
        payload["content"] = content[:low]
        text = encode()
    if len(text) > max_chars:
        raise SystemExit("--max-chars is too small for this record's identity; increase the budget")
    return text


def command_context(args: argparse.Namespace) -> int:
    terms = args.query.casefold().split()
    if not terms or min(args.lesson_limit, args.todo_limit) < 1:
        raise SystemExit("context requires nonempty keywords and positive limits")
    concepts = query_concepts(args.project_root, terms)
    lesson_path, todo_path, _, archive_dir = project_files(args.project_root)
    lesson_file, todo_file = load_record_file(lesson_path, "lesson"), load_record_file(todo_path, "todo")
    sources = [lesson_file, todo_file]
    lessons = ranked_records(lesson_file, concepts, "lesson")
    searched_archive = not lessons or -lessons[0][0][0] < len(concepts) or lessons[0][0][1] == 0
    if searched_archive:
        for path in sorted(archive_dir.glob("lessons-*.md")):
            source = load_record_file(path, "lesson")
            sources.append(source)
            lessons.extend(ranked_records(source, concepts, "lesson"))
        lessons.sort(key=lambda item: item[0])
    todos = [item for item in ranked_records(todo_file, concepts, "todo")
             if item[2].fields.get("status") == "active"]
    stamp_input = json.dumps([args.query, concepts, args.lesson_limit, args.todo_limit, args.max_chars,
                             [(str(source.path), source.text) for source in sources]], ensure_ascii=False)
    stamp = hashlib.sha256(stamp_input.encode()).hexdigest()[:24]
    if args.since == stamp:
        print(bounded_json({"stamp": stamp, "unchanged": True}, args.max_chars))
        return 0
    payload = {"stamp": stamp, "unchanged": False,
               "lessons": [{**record_summary(record), "archived": source.path != lesson_path}
                           for _, source, record in lessons[:args.lesson_limit]],
               "todos": [record_summary(record) for _, _, record in todos[:args.todo_limit]],
               "total_lessons": len(lessons), "total_todos": len(todos),
               "searched_archive": searched_archive,
               "truncated": len(lessons) > args.lesson_limit or len(todos) > args.todo_limit}
    print(bounded_json(payload, args.max_chars))
    return 0


def command_get_record(args: argparse.Namespace) -> int:
    lesson_path, todo_path, _, archive_dir = project_files(args.project_root)
    primary = load_record_file(lesson_path if args.kind == "lesson" else todo_path, args.kind)
    records = searchable_lesson_records(primary) if args.kind == "lesson" else primary.records
    matches = [(primary, r) for r in records if r.stable_id == args.id]
    if not matches and args.kind == "lesson":
        for path in sorted(archive_dir.glob("lessons-*.md")):
            source = load_record_file(path, "lesson")
            matches.extend((source, r) for r in searchable_lesson_records(source) if r.stable_id == args.id)
    if len(matches) != 1:
        raise SystemExit("record ID must match exactly one record; query context again")
    source, record = matches[0]
    detail = lesson_json(source, record)
    payload = {"id": record.stable_id, "kind": args.kind, "title": record.title,
               "content": detail["content"], "source": detail["source"], "truncated": False}
    if args.kind == "lesson":
        payload.update(status=lesson_status(record), superseded_by=record.fields.get("superseded_by", "-") or "-")
        if payload["superseded_by"] == "-":
            payload["superseded_by"] = None
    print(bounded_json(payload, args.max_chars))
    return 0


def command_list_todos(args: argparse.Namespace) -> int:
    todo_file = load_record_file(project_files(args.project_root)[1], "todo")
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    terms = args.query.casefold().split() if args.query else []
    records = [record for _, _, record in ranked_records(todo_file, [(term,) for term in terms], "todo")
               if args.status == "all" or record.fields.get("status") == args.status]
    payload = {"todos": [{"id": r.stable_id, "title": r.title[:80], "status": r.fields.get("status"),
                          **({"content": r.raw} if args.include_content else {})} for r in records[:args.limit]],
               "total_matches": len(records), "truncated": len(records) > args.limit}
    if args.include_content:
        # Bound each explicit body before bounding the collection envelope.
        for row in payload["todos"]:
            if len(row["content"]) > args.max_chars // args.limit:
                row["content"] = row["content"][:args.max_chars // args.limit]
                payload["truncated"] = True
    serialized = bounded_json(payload, args.max_chars)
    if args.json_output:
        print(serialized)
    elif payload["todos"]:
        text = "\n".join(row["content"].rstrip() if args.include_content else
                         f"- {row['id']}: {row['title']} ({row['status']})" for row in payload["todos"])
        if payload["truncated"]:
            text += f"\nShowing {len(payload['todos'])} of {len(records)} todos; output may be truncated."
        print(text[:args.max_chars - 1])
    else:
        print("No todos matched.")
    return 0


def add_query_commands(commands) -> None:
    list_todos = commands.add_parser("list-todos", help="List active todos without writing.")
    list_todos.add_argument("--status", choices=("active", "completed", "cancelled", "all"), default="active")
    list_todos.add_argument("--json", dest="json_output", action="store_true")
    list_todos.add_argument("--include-content", action="store_true")
    list_todos.add_argument("--query")
    list_todos.add_argument("--limit", type=int, default=3)
    list_todos.add_argument("--max-chars", type=int, default=2000)
    list_todos.set_defaults(handler=command_list_todos)

    context_parser = commands.add_parser("context", help="Read bounded relevant lesson/todo summaries; no writes.")
    context_parser.add_argument("--query", required=True, help="Space-separated module, symbol or error keywords.")
    context_parser.add_argument("--lesson-limit", type=int, default=3)
    context_parser.add_argument("--todo-limit", type=int, default=3)
    context_parser.add_argument("--max-chars", type=int, default=2000)
    context_parser.add_argument("--since", help="Stamp already read in this conversation; never persist as a skip flag.")
    context_parser.set_defaults(handler=command_context)

    get_record = commands.add_parser("get-record", help="Read exactly one record by ID with a serialized output budget.")
    get_record.add_argument("--kind", choices=("lesson", "todo"), required=True)
    get_record.add_argument("--id", required=True)
    get_record.add_argument("--max-chars", type=int, default=2400)
    get_record.set_defaults(handler=command_get_record)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    add_query_commands(commands)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f"query failed without writing: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
