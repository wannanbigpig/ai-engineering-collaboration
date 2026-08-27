#!/usr/bin/env python3
"""Track lesson reuse and archive stale .aitasks records safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


MARKER_PATTERN = re.compile(
    r"<!--\s*aitasks:(?P<kind>lesson|todo)\s+(?P<fields>.*?)\s*-->",
    re.DOTALL,
)
FIELD_PATTERN = re.compile(r"(?P<key>[a-z_]+)=(?P<value>[^\s]+)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$", re.MULTILINE)
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


def marker_ids(text: str) -> set[str]:
    """Every explicit id= value found inside aitasks markers in ``text``."""
    ids: set[str] = set()
    for match in MARKER_PATTERN.finditer(text):
        for field in FIELD_PATTERN.finditer(match.group("fields")):
            if field.group("key") == "id":
                ids.add(field.group("value"))
    return ids


def collect_archive_ids(archive_dir: Path, prefix: str) -> set[str]:
    """Record ids already stored in any archive file named '<prefix>-*.md'."""
    ids: set[str] = set()
    if not archive_dir.is_dir():
        return ids
    for path in sorted(archive_dir.glob(f"{prefix}-*.md")):
        try:
            ids.update(marker_ids(path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return ids


def load_record_file(path: Path, kind: str) -> RecordFile:
    if not path.exists():
        return RecordFile(path=path, text="", records=[])

    text = path.read_text(encoding="utf-8")
    markers = [
        match for match in MARKER_PATTERN.finditer(text) if match.group("kind") == kind
    ]
    if not markers:
        return RecordFile(path=path, text=text, records=[])

    records: list[Record] = []
    for index, marker in enumerate(markers):
        next_marker_start = (
            markers[index + 1].start() if index + 1 < len(markers) else len(text)
        )
        end = next_marker_start
        heading = HEADING_PATTERN.search(text, marker.end(), next_marker_start)
        if heading:
            heading_level = len(heading.group(0)) - len(heading.group(0).lstrip("#"))
            for candidate in HEADING_PATTERN.finditer(
                text, heading.end(), next_marker_start
            ):
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
    return CleanupPlan(
        due_reasons=reasons,
        lessons=[
            record
            for record in lesson_file.records
            if lesson_is_stale(record, today, policy)
        ],
        todos=[
            record
            for record in todo_file.records
            if todo_is_stale(record, today, policy)
        ],
    )


def prepare_archive_content(
    existing_text: str,
    kind: str,
    source_path: Path,
    records: list[Record],
    today: date,
    existing_ids: set[str] | None = None,
) -> str | None:
    """Build the full archive file content, skipping already-archived records.

    A record is skipped when its stable id already appears in ``existing_ids``
    (or, by default, in ``existing_text`` itself) or was appended earlier in
    this same batch. Returns None when there is nothing new to append.
    """
    seen = (
        set(existing_ids) if existing_ids is not None else marker_ids(existing_text)
    )
    to_append: list[Record] = []
    for record in records:
        archived = record.with_archive_id()
        if archived.fields["id"] in seen:
            continue
        seen.add(archived.fields["id"])
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
    """Append records to an archive file, skipping ids already present there.

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
            collect_archive_ids(archive_dir, "lessons"),
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
            collect_archive_ids(archive_dir, "todo"),
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
        "deduplicated by stable id, so nothing will be appended twice.",
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


class MaintenanceLock:
    """Cross-platform advisory lock via an O_CREAT|O_EXCL lock file.

    The lock file records the holder's pid. A lock is stale (and reclaimable)
    when its pid is gone or when the file is older than ``stale_seconds``.
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

    def __enter__(self) -> MaintenanceLock:
        if not self.enabled:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._create()
                self._acquired = True
                return self
            except FileExistsError:
                if self._reclaim_stale():
                    continue
                if time.monotonic() >= deadline:
                    holder = self._read_pid()
                    detail = f" (pid {holder})" if holder is not None else ""
                    raise SystemExit(
                        f"another maintenance process holds {self.path}{detail}; "
                        "retry when it finishes (or remove the lock file if stale)"
                    )
                time.sleep(self.sleep_interval)

    def _create(self) -> None:
        with self.path.open("x", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")

    def _read_pid(self) -> int | None:
        try:
            text = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        try:
            return int(text)
        except ValueError:
            return None

    def _reclaim_stale(self) -> bool:
        if not self.is_stale():
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return True

    def is_stale(self) -> bool:
        try:
            stat_result = self.path.stat()
        except FileNotFoundError:
            return False
        if time.time() - stat_result.st_mtime > self.stale_seconds:
            return True
        pid = self._read_pid()
        if pid is None:
            return True
        return not pid_alive(pid)

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._acquired = False
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
    query = args.query.casefold()
    matches = [
        record
        for record in load_record_file(lesson_path, "lesson").records
        if query in record.title.casefold() or query in record.raw.casefold()
    ][: args.limit]
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
    find_parser.add_argument("--query", required=True, help="Case-insensitive text.")
    find_parser.add_argument("--limit", type=int, default=10)
    find_parser.add_argument(
        "--include-content", action="store_true", help="Print matching record bodies."
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
