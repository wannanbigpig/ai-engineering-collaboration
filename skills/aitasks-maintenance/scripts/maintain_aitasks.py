#!/usr/bin/env python3
"""Track lesson reuse and archive stale .aitasks records safely."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator


MARKER_PATTERN = re.compile(
    r"^ {0,3}<!--[ \t]*aitasks:(?P<kind>lesson|todo)[ \t]+(?P<fields>[^\r\n]*?)[ \t]*-->[ \t]*$",
    re.MULTILINE,
)
ARCHIVE_HEADER_PATTERN = re.compile(
    r"^<!-- archived_at=\d{4}-\d{2}-\d{2} source=[^\r\n>]* -->$", re.MULTILINE
)
FIELD_PATTERN = re.compile(r"(?P<key>[a-z_]+)=(?P<value>[^\s]+)")
HEADING_PATTERN = re.compile(r"^#{1,6}[ \t]+(?P<title>.+?)[ \t]*$", re.MULTILINE)
FENCE_PATTERN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
COMPLETED_TODO_STATUSES = {"completed", "cancelled"}

LOCK_FILE_NAME = ".maintenance.lock"
DEFAULT_LOCK_TIMEOUT = 5.0
DEFAULT_LOCK_STALE_SECONDS = 300.0


@dataclass(frozen=True)
class Policy:
    check_interval_days: int
    lesson_count_trigger: int
    todo_count_trigger: int
    lesson_unused_days: int
    lesson_once_used_days: int
    lesson_reused_days: int
    todo_completed_days: int


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
        field_text = " ".join(f"{key}={value}" for key, value in self.fields.items())
        marker = f"<!-- aitasks:{self.kind} {field_text} -->"
        return MARKER_PATTERN.sub(marker, self.raw, count=1)

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


@dataclass(frozen=True)
class CleanupPlan:
    due_reasons: list[str]
    lessons: list[Record]
    todos: list[Record]


def parse_date(value: str | None) -> date | None:
    if not value or value == "-":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_fields(value: str) -> dict[str, str]:
    return {
        match.group("key"): match.group("value")
        for match in FIELD_PATTERN.finditer(value)
    }


class ArchiveConflictError(ValueError):
    """An archive ID cannot safely identify one unchanged record."""


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


def archive_record_contents(text: str) -> dict[str, str]:
    """Index archived records by ID and their exact rendered content."""
    markers = record_markers(text)
    header_positions = [match.start() for match in unfenced_matches(text, ARCHIVE_HEADER_PATTERN)]
    contents: dict[str, str] = {}
    for index, marker in enumerate(markers):
        record_id_value = parse_fields(marker.group("fields")).get("id")
        if not record_id_value:
            continue
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        next_header = bisect.bisect_left(header_positions, marker.end())
        if next_header < len(header_positions) and header_positions[next_header] < end:
            end = header_positions[next_header]
        content = text[marker.start():end].strip("\r\n")
        previous = contents.setdefault(record_id_value, content)
        if previous != content:
            raise ArchiveConflictError(f"archive ID collision: {record_id_value}")
    return contents


def collect_archive_records(archive_dir: Path, prefix: str) -> dict[str, str]:
    """Read all existing archive records; fail closed on conflicts or read errors."""
    contents: dict[str, str] = {}
    if not archive_dir.is_dir():
        return contents
    for path in sorted(archive_dir.glob(f"{prefix}-*.md")):
        for record_id_value, content in archive_record_contents(
            path.read_text(encoding="utf-8")
        ).items():
            previous = contents.setdefault(record_id_value, content)
            if previous != content:
                raise ArchiveConflictError(f"archive ID collision: {record_id_value}")
    return contents


def load_record_file(path: Path, kind: str) -> RecordFile:
    if not path.exists():
        return RecordFile(path=path, text="", records=[])

    text = path.read_text(encoding="utf-8")
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


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def render_record_file(record_file: RecordFile, excluded: Iterable[Record] = ()) -> str:
    excluded_ids = {id(record) for record in excluded}
    parts: list[str] = []
    cursor = 0
    for record in record_file.records:
        parts.append(record_file.text[cursor : record.start])
        if id(record) not in excluded_ids:
            parts.append(record.render())
        cursor = record.end
    parts.append(record_file.text[cursor:])
    return "".join(parts)


def load_state(state_path: Path) -> dict[str, str]:
    if not state_path.exists():
        return {}
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def due_reasons(
    today: date,
    policy: Policy,
    state: dict[str, str],
    lessons: list[Record],
    todos: list[Record],
    force: bool,
) -> list[str]:
    reasons: list[str] = []
    if force:
        reasons.append("forced")

    last_cleanup = parse_date(state.get("last_cleanup_at"))
    if last_cleanup is None:
        reasons.append("no previous cleanup")
    elif (today - last_cleanup).days >= policy.check_interval_days:
        reasons.append(f"last cleanup was {(today - last_cleanup).days} days ago")

    if len(lessons) >= policy.lesson_count_trigger:
        reasons.append(
            f"lesson count {len(lessons)} reached {policy.lesson_count_trigger}"
        )

    completed_count = sum(
        record.fields.get("status") in COMPLETED_TODO_STATUSES for record in todos
    )
    if completed_count >= policy.todo_count_trigger:
        reasons.append(
            f"completed todo count {completed_count} reached {policy.todo_count_trigger}"
        )
    return list(dict.fromkeys(reasons))


def lesson_is_stale(record: Record, today: date, policy: Policy) -> bool:
    if record.fields.get("pinned", "false").lower() == "true":
        return False

    try:
        use_count = int(record.fields.get("use_count", ""))
    except ValueError:
        return False
    if use_count < 0:
        return False

    created_at = parse_date(record.fields.get("created_at"))
    last_used_at = parse_date(record.fields.get("last_used_at"))
    if created_at is None:
        return False

    if use_count == 0:
        anchor = created_at
        threshold = policy.lesson_unused_days
    elif use_count == 1:
        anchor = last_used_at or created_at
        threshold = policy.lesson_once_used_days
    else:
        anchor = last_used_at or created_at
        threshold = policy.lesson_reused_days
    return (today - anchor).days >= threshold


def todo_is_stale(record: Record, today: date, policy: Policy) -> bool:
    if record.fields.get("status") not in COMPLETED_TODO_STATUSES:
        return False
    completed_at = parse_date(record.fields.get("completed_at"))
    return (
        completed_at is not None
        and (today - completed_at).days >= policy.todo_completed_days
    )


def build_cleanup_plan(
    today: date,
    policy: Policy,
    state: dict[str, str],
    lesson_file: RecordFile,
    todo_file: RecordFile,
    force: bool,
) -> CleanupPlan:
    reasons = due_reasons(
        today,
        policy,
        state,
        lesson_file.records,
        todo_file.records,
        force,
    )
    if not reasons:
        return CleanupPlan(due_reasons=[], lessons=[], todos=[])
    stale_lessons = [
        record for record in lesson_file.records if lesson_is_stale(record, today, policy)
    ]
    stale_todos = [
        record for record in todo_file.records if todo_is_stale(record, today, policy)
    ]
    stale_lesson_ids = {id(record) for record in stale_lessons}
    stale_todo_ids = {id(record) for record in stale_todos}

    # A count trigger must reduce the active file even when records are recent.
    # Archive the oldest eligible overflow, then preserve source order for writes.
    lesson_overflow = max(
        0, len(lesson_file.records) - len(stale_lessons) - policy.lesson_count_trigger + 1
    )
    if lesson_overflow:
        candidates = []
        for record in lesson_file.records:
            if (
                id(record) in stale_lesson_ids
                or record.fields.get("pinned", "false").lower() == "true"
            ):
                continue
            created_at = parse_date(record.fields.get("created_at"))
            try:
                use_count = int(record.fields.get("use_count", ""))
            except ValueError:
                continue
            if created_at is not None and use_count >= 0:
                candidates.append((use_count, created_at, record.start, record))
        stale_lessons.extend(
            item[3]
            for item in sorted(candidates, key=lambda item: item[:3])[:lesson_overflow]
        )
        stale_lesson_ids.update(id(record) for record in stale_lessons)

    completed_count = sum(
        record.fields.get("status") in COMPLETED_TODO_STATUSES
        for record in todo_file.records
    )
    todo_overflow = max(
        0, completed_count - len(stale_todos) - policy.todo_count_trigger + 1
    )
    if todo_overflow:
        candidates = []
        for record in todo_file.records:
            if (
                id(record) in stale_todo_ids
                or record.fields.get("status") not in COMPLETED_TODO_STATUSES
            ):
                continue
            completed_at = parse_date(record.fields.get("completed_at"))
            if completed_at is not None:
                candidates.append((completed_at, record.start, record))
        stale_todos.extend(
            item[2]
            for item in sorted(candidates, key=lambda item: item[:2])[:todo_overflow]
        )
        stale_todo_ids.update(id(record) for record in stale_todos)

    return CleanupPlan(
        due_reasons=reasons,
        lessons=[
            record for record in lesson_file.records if id(record) in stale_lesson_ids
        ],
        todos=[record for record in todo_file.records if id(record) in stale_todo_ids],
    )


def prepare_archive_content(
    existing_text: str,
    kind: str,
    source_path: Path,
    records: list[Record],
    today: date,
    existing_records: dict[str, str] | None = None,
) -> str | None:
    """Build archive content, rejecting ambiguous IDs before any file is removed."""
    seen = (
        dict(existing_records)
        if existing_records is not None
        else archive_record_contents(existing_text)
    )
    batch_ids: set[str] = set()
    to_append: list[Record] = []
    for record in records:
        archived = record.with_archive_id()
        record_id_value = archived.fields["id"]
        content = archived.render().strip("\r\n")
        if record_id_value in batch_ids:
            raise ArchiveConflictError(f"archive ID collision: {record_id_value}")
        batch_ids.add(record_id_value)
        if record_id_value in seen:
            if seen[record_id_value] != content:
                raise ArchiveConflictError(f"archive ID collision: {record_id_value}")
            continue
        seen[record_id_value] = content
        to_append.append(archived)
    if not to_append:
        return None
    source = source_path.name
    addition = (
        f"<!-- archived_at={today.isoformat()} source={source} -->\n\n"
        + "".join(record.render() for record in to_append).lstrip()
    )
    if not addition.endswith("\n"):
        addition += "\n"
    return existing_text.rstrip() + "\n\n" + addition


def append_archive(
    path: Path,
    kind: str,
    source_path: Path,
    records: list[Record],
    today: date,
) -> bool:
    """Append records to an archive file, skipping identical records already there.

    Returns True when the file was written, False when nothing was appended.
    """
    if not records:
        return False
    existing = (
        path.read_text(encoding="utf-8")
        if path.exists()
        else f"# Archived {kind} records\n\n"
    )
    content = prepare_archive_content(existing, kind, source_path, records, today)
    if content is None:
        return False
    atomic_write(path, content)
    return True


def prepare_cleanup_writes(
    today: date,
    archive_dir: Path,
    lesson_path: Path,
    todo_path: Path,
    state_path: Path,
    lesson_file: RecordFile,
    todo_file: RecordFile,
    plan: CleanupPlan,
) -> list[tuple[Path, str]]:
    """Build every file --apply would write, in commit order.

    Archive files come first (deduplicated against every existing archive),
    then the trimmed active files, then the state file last. Nothing is
    written here; callers commit the returned list with commit_writes().
    """
    # All archive contents are prepared first, then the trimmed active
    # files, then the state file last: commit order is
    # [archive lessons, archive todos, active lessons, active todos, state].
    archive_writes: list[tuple[Path, str]] = []
    if plan.lessons:
        archive_path = archive_dir / f"lessons-{today.isoformat()}.md"
        existing = (
            archive_path.read_text(encoding="utf-8")
            if archive_path.exists()
            else f"# Archived lessons records\n\n"
        )
        content = prepare_archive_content(
            existing,
            "lessons",
            lesson_path,
            plan.lessons,
            today,
            collect_archive_records(archive_dir, "lessons"),
        )
        if content is not None:
            archive_writes.append((archive_path, content))
    if plan.todos:
        archive_path = archive_dir / f"todo-{today.isoformat()}.md"
        existing = (
            archive_path.read_text(encoding="utf-8")
            if archive_path.exists()
            else f"# Archived todo records\n\n"
        )
        content = prepare_archive_content(
            existing,
            "todo",
            todo_path,
            plan.todos,
            today,
            collect_archive_records(archive_dir, "todo"),
        )
        if content is not None:
            archive_writes.append((archive_path, content))
    writes = list(archive_writes)
    if plan.lessons:
        writes.append((lesson_path, render_record_file(lesson_file, plan.lessons)))
    if plan.todos:
        writes.append((todo_path, render_record_file(todo_file, plan.todos)))
    writes.append(
        (
            state_path,
            json.dumps(
                {"last_cleanup_at": today.isoformat()}, ensure_ascii=False, indent=2
            )
            + "\n",
        )
    )
    return writes


class CommitError(Exception):
    """Raised when a transactional commit fails partway through."""

    def __init__(
        self,
        completed: list[Path],
        remaining: list[tuple[Path, str]],
        error: BaseException,
    ) -> None:
        super().__init__(str(error))
        self.completed = completed
        self.remaining = remaining
        self.error = error


def commit_writes(writes: list[tuple[Path, str]]) -> None:
    """Write (path, content) pairs in order; raise CommitError on failure."""
    completed: list[Path] = []
    try:
        for path, content in writes:
            atomic_write(path, content)
            completed.append(path)
    except BaseException as error:
        raise CommitError(
            completed=completed, remaining=writes[len(completed):], error=error
        ) from error


def report_commit_error(error: CommitError) -> int:
    print(
        "ERROR: cleanup failed partway through; the .maintenance.json state "
        "file was NOT updated.",
        file=sys.stderr,
    )
    if error.completed:
        print(
            f"  Writes completed ({len(error.completed)}): "
            + ", ".join(str(path) for path in error.completed),
            file=sys.stderr,
        )
    else:
        print("  No writes completed.", file=sys.stderr)
    if error.remaining:
        print(
            f"  Writes not completed ({len(error.remaining)}): "
            + ", ".join(str(path) for path, _ in error.remaining),
            file=sys.stderr,
        )
    print(f"  Cause: {error.error}", file=sys.stderr)
    print(
        "  Recovery: rerun `cleanup --apply`; records already archived are "
        "skipped only when their ID and content still match.",
        file=sys.stderr,
    )
    return 1


def pid_alive(pid: int) -> bool:
    """Return whether a process id is currently alive (platform-aware)."""
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_alive_windows(pid: int) -> bool:
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


@contextmanager
def lock_transition_guard(
    path: Path, timeout: float, sleep_interval: float
) -> Iterator[None]:
    """Serialize changes to the PID lock through a persistent OS-locked file."""
    guard_path = path.with_name(path.name + ".guard")
    with guard_path.open("a+b") as guard:
        if os.name == "nt":
            import msvcrt

            if guard.seek(0, os.SEEK_END) == 0:
                guard.write(b"\0")
                guard.flush()
            guard.seek(0)
        else:
            import fcntl

        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SystemExit(f"another maintenance process is changing {path}")
                time.sleep(sleep_interval)
        try:
            yield
        finally:
            if os.name == "nt":
                guard.seek(0)
                msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(guard.fileno(), fcntl.LOCK_UN)


class MaintenanceLock:
    """Cross-platform advisory lock via an O_CREAT|O_EXCL lock file.

    The lock file records the holder's pid. A dead holder is reclaimable;
    age is a fallback only when no valid pid has been written.
    Contention is retried until ``timeout`` seconds, then SystemExit is
    raised. Set ``enabled=False`` (or AITASKS_DISABLE_LOCK=1) to skip locking.
    """

    def __init__(
        self,
        path: Path,
        *,
        timeout: float = DEFAULT_LOCK_TIMEOUT,
        stale_seconds: float = DEFAULT_LOCK_STALE_SECONDS,
        enabled: bool = True,
        sleep_interval: float = 0.05,
    ) -> None:
        self.path = path
        self.timeout = timeout
        self.stale_seconds = stale_seconds
        self.enabled = enabled
        self.sleep_interval = sleep_interval
        self._acquired = False
        self._identity: tuple[int, int] | None = None

    def __enter__(self) -> MaintenanceLock:
        if not self.enabled:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            with lock_transition_guard(self.path, self.timeout, self.sleep_interval):
                try:
                    self._create()
                except FileExistsError:
                    if self._reclaim_stale():
                        self._create()
                if self._identity is not None:
                    self._acquired = True
                    return self
                holder = self._read_pid()
            if time.monotonic() >= deadline:
                detail = f" (pid {holder})" if holder is not None else ""
                raise SystemExit(
                    f"another maintenance process holds {self.path}{detail}; "
                    "retry when it finishes (or remove the lock file if stale)"
                )
            time.sleep(self.sleep_interval)

    def _create(self) -> None:
        with self.path.open("x", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
            stat_result = os.fstat(handle.fileno())
            self._identity = (stat_result.st_dev, stat_result.st_ino)

    def _read_pid(self) -> int | None:
        try:
            text = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        try:
            pid = int(text)
            return pid if pid > 0 else None
        except ValueError:
            return None

    def _reclaim_stale(self) -> bool:
        try:
            before = self.path.lstat()
        except FileNotFoundError:
            return False
        if not self.is_stale():
            return False
        try:
            after = self.path.lstat()
        except FileNotFoundError:
            return False
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            return False
        self.path.unlink()
        return True

    def is_stale(self) -> bool:
        try:
            stat_result = self.path.stat()
        except FileNotFoundError:
            return False
        pid = self._read_pid()
        if pid is not None:
            return not pid_alive(pid)
        return time.time() - stat_result.st_mtime > self.stale_seconds

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._acquired:
            with lock_transition_guard(self.path, self.timeout, self.sleep_interval):
                try:
                    current = self.path.lstat()
                except FileNotFoundError:
                    current = None
                if current and self._identity == (current.st_dev, current.st_ino):
                    self.path.unlink()
            self._acquired = False
            self._identity = None
        return False


def create_lock(project_root: Path) -> MaintenanceLock:
    """Build the lock for write commands, honouring test/operator env knobs."""
    env_timeout = os.environ.get("AITASKS_LOCK_TIMEOUT")
    try:
        timeout = float(env_timeout) if env_timeout else DEFAULT_LOCK_TIMEOUT
    except ValueError:
        timeout = DEFAULT_LOCK_TIMEOUT
    enabled = os.environ.get("AITASKS_DISABLE_LOCK") != "1"
    lock_path = project_root.expanduser().resolve() / ".aitasks" / LOCK_FILE_NAME
    return MaintenanceLock(lock_path, timeout=timeout, enabled=enabled)


def policy_from_args(args: argparse.Namespace) -> Policy:
    values = [
        args.check_interval_days,
        args.lesson_count_trigger,
        args.todo_count_trigger,
        args.lesson_unused_days,
        args.lesson_once_used_days,
        args.lesson_reused_days,
        args.todo_completed_days,
    ]
    if any(value <= 0 for value in values):
        raise SystemExit("all maintenance thresholds must be positive integers")
    return Policy(*values)


def resolve_today(value: str | None) -> date:
    if value is None:
        return date.today()
    parsed = parse_date(value)
    if parsed is None:
        raise SystemExit("--today must use YYYY-MM-DD")
    return parsed


def project_files(project_root: Path) -> tuple[Path, Path, Path, Path]:
    root = project_root.expanduser().resolve()
    aitasks = root / ".aitasks"
    return (
        aitasks / "lessons.md",
        aitasks / "todo.md",
        aitasks / ".maintenance.json",
        aitasks / "archive",
    )


def print_plan(plan: CleanupPlan, lesson_file: RecordFile, todo_file: RecordFile) -> None:
    if plan.due_reasons:
        print(f"Maintenance due: {';'.join(plan.due_reasons)}")
    else:
        print("Maintenance not due.")
    print(
        f"Tracked records: {len(lesson_file.records)} lessons, "
        f"{len(todo_file.records)} todos"
    )
    print(
        f"Eligible for archive: {len(plan.lessons)} lessons, {len(plan.todos)} todos"
    )
    for record in plan.lessons:
        print(f"- lesson: {record.title}")
    for record in plan.todos:
        print(f"- todo: {record.title}")


def command_status(args: argparse.Namespace) -> int:
    lesson_path, todo_path, state_path, _ = project_files(args.project_root)
    lesson_file = load_record_file(lesson_path, "lesson")
    todo_file = load_record_file(todo_path, "todo")
    plan = build_cleanup_plan(
        resolve_today(args.today),
        policy_from_args(args),
        load_state(state_path),
        lesson_file,
        todo_file,
        args.force,
    )
    print_plan(plan, lesson_file, todo_file)
    return 0


def command_mark_used(args: argparse.Namespace) -> int:
    lesson_path, _, _, _ = project_files(args.project_root)
    with create_lock(args.project_root):
        lesson_file = load_record_file(lesson_path, "lesson")
        matches = [
            record for record in lesson_file.records if record.title == args.lesson
        ]
        if not matches:
            raise SystemExit(f"lesson not found or missing metadata: {args.lesson}")
        if len(matches) > 1:
            raise SystemExit(f"lesson title is not unique: {args.lesson}")

        record = matches[0]
        try:
            use_count = int(record.fields.get("use_count", ""))
        except ValueError as error:
            raise SystemExit(f"lesson has invalid use_count: {args.lesson}") from error
        if use_count < 0:
            raise SystemExit(f"lesson has invalid use_count: {args.lesson}")

        record.fields["use_count"] = str(use_count + 1)
        record.fields["last_used_at"] = resolve_today(args.today).isoformat()
        atomic_write(lesson_path, render_record_file(lesson_file))
    print(
        f"Marked lesson used: {record.title} "
        f"(use_count={record.fields['use_count']}, "
        f"last_used_at={record.fields['last_used_at']})"
    )
    return 0


def command_find_lessons(args: argparse.Namespace) -> int:
    """Print matching lesson records without modifying project files."""
    lesson_path, _, _, _ = project_files(args.project_root)
    lesson_file = load_record_file(lesson_path, "lesson")
    query = args.query.casefold()
    matches = [
        record
        for record in searchable_lesson_records(lesson_file)
        if query in record.title.casefold() or query in record.raw.casefold()
    ][: args.limit]
    if args.json_output:
        print(json.dumps({"matches": [lesson_json(lesson_file, record) for record in matches]},
                         ensure_ascii=False, indent=2))
        return 0
    if not matches:
        print("No lessons matched.")
        return 0
    for record in matches:
        if args.include_content:
            print(record.raw.rstrip())
        else:
            print(
                "- {title} (created_at={created_at}, last_used_at={last_used_at}, "
                "use_count={use_count}, pinned={pinned})".format(
                    title=record.title,
                    created_at=record.fields.get("created_at", "-"),
                    last_used_at=record.fields.get("last_used_at", "-"),
                    use_count=record.fields.get("use_count", "-"),
                    pinned=record.fields.get("pinned", "-"),
                )
            )
    return 0


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


def command_set_todo_status(args: argparse.Namespace) -> int:
    """Set one uniquely titled todo record's lifecycle metadata."""
    todo_path = project_files(args.project_root)[1]
    with create_lock(args.project_root):
        todo_file = load_record_file(todo_path, "todo")
        matches = [record for record in todo_file.records if record.title == args.todo]
        if not matches:
            raise SystemExit(f"todo not found or missing metadata: {args.todo}")
        if len(matches) > 1:
            raise SystemExit(f"todo title is not unique: {args.todo}")
        record = matches[0]
        record.fields["status"] = args.status
        record.fields["completed_at"] = (
            resolve_today(args.today).isoformat()
            if args.status in COMPLETED_TODO_STATUSES
            else "-"
        )
        atomic_write(todo_path, render_record_file(todo_file))
    print(
        f"Updated todo: {record.title} "
        f"(status={record.fields['status']}, "
        f"completed_at={record.fields['completed_at']})"
    )
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    lesson_path, todo_path, state_path, archive_dir = project_files(args.project_root)
    today = resolve_today(args.today)
    policy = policy_from_args(args)

    if not args.apply:
        lesson_file = load_record_file(lesson_path, "lesson")
        todo_file = load_record_file(todo_path, "todo")
        plan = build_cleanup_plan(
            today, policy, load_state(state_path), lesson_file, todo_file, args.force
        )
        print_plan(plan, lesson_file, todo_file)
        print("Dry run only; rerun with --apply to archive eligible records.")
        return 0

    with create_lock(args.project_root):
        lesson_file = load_record_file(lesson_path, "lesson")
        todo_file = load_record_file(todo_path, "todo")
        state = load_state(state_path)
        plan = build_cleanup_plan(
            today, policy, state, lesson_file, todo_file, args.force
        )
        print_plan(plan, lesson_file, todo_file)
        if not plan.due_reasons:
            print("No changes applied because maintenance is not due.")
            return 0

        try:
            writes = prepare_cleanup_writes(
                today,
                archive_dir,
                lesson_path,
                todo_path,
                state_path,
                lesson_file,
                todo_file,
                plan,
            )
        except (ArchiveConflictError, OSError, UnicodeError) as error:
            print(f"ERROR: cleanup aborted before writing: {error}", file=sys.stderr)
            return 1
        if not writes:
            print(
                "No changes applied because every eligible record is already archived."
            )
            return 0
        try:
            commit_writes(writes)
        except CommitError as error:
            return report_commit_error(error)

    print("Maintenance state updated; eligible records were archived before removal.")
    return 0


def add_policy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--check-interval-days", type=int, default=30)
    parser.add_argument("--lesson-count-trigger", type=int, default=100)
    parser.add_argument("--todo-count-trigger", type=int, default=20)
    parser.add_argument("--lesson-unused-days", type=int, default=90)
    parser.add_argument("--lesson-once-used-days", type=int, default=180)
    parser.add_argument("--lesson-reused-days", type=int, default=365)
    parser.add_argument("--todo-completed-days", type=int, default=30)
    parser.add_argument(
        "--force", action="store_true", help="Check thresholds even when not scheduled."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track lesson reuse and archive stale .aitasks records."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--today", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    status_parser = commands.add_parser("status", help="Show whether maintenance is due.")
    add_policy_arguments(status_parser)
    status_parser.set_defaults(handler=command_status)

    mark_parser = commands.add_parser(
        "mark-used", help="Increment one lesson's use_count and last_used_at."
    )
    mark_parser.add_argument("--lesson", required=True, help="Exact lesson heading text.")
    mark_parser.set_defaults(handler=command_mark_used)

    find_parser = commands.add_parser(
        "find-lessons", help="Find lessons by title or body text without editing."
    )
    find_parser.add_argument("--query", required=True, help="One case-insensitive literal substring, not a regex or keyword list.")
    find_parser.add_argument("--limit", type=int, default=10)
    find_output = find_parser.add_mutually_exclusive_group()
    find_output.add_argument(
        "--include-content", action="store_true", help="Print matching record bodies."
    )
    find_output.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Return complete records with owned metadata, nullable use_count and source line numbers."
    )
    find_parser.set_defaults(handler=command_find_lessons)

    todo_parser = commands.add_parser(
        "set-todo-status", help="Update one todo record's lifecycle metadata."
    )
    todo_parser.add_argument("--todo", required=True, help="Exact todo heading text.")
    todo_parser.add_argument(
        "--status", required=True, choices=("active", "completed", "cancelled")
    )
    todo_parser.set_defaults(handler=command_set_todo_status)

    cleanup_parser = commands.add_parser(
        "cleanup", help="Preview or apply archive-based cleanup."
    )
    add_policy_arguments(cleanup_parser)
    cleanup_parser.add_argument(
        "--apply", action="store_true", help="Archive and remove eligible records."
    )
    cleanup_parser.set_defaults(handler=command_cleanup)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
