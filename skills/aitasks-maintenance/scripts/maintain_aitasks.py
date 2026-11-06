#!/usr/bin/env python3
"""Track lesson reuse and archive stale .aitasks records safely."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator
from uuid import uuid4

from query_aitasks import (
    FIELD_PATTERN, FENCE_PATTERN, HEADING_PATTERN, MARKER_PATTERN,
    Record, RecordFile, add_query_commands, bounded_json, lesson_json, lesson_status,
    load_record_file, parse_fields, project_files, query_concepts, read_markdown,
    record_markers, searchable_lesson_records, unfenced_matches,
)


ARCHIVE_HEADER_PATTERN = re.compile(
    r"^<!-- archived_at=\d{4}-\d{2}-\d{2} source=[^\r\n>]* -->(?=\r?$)", re.MULTILINE
)
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


class ArchiveConflictError(ValueError):
    """An archive ID cannot safely identify one unchanged record."""


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


def collect_archive_records(archive_dir: Path, prefix: str,
                            overrides: dict[Path, str] | None = None) -> dict[str, str]:
    """Read all existing archive records; fail closed on conflicts or read errors."""
    contents: dict[str, str] = {}
    if not archive_dir.is_dir():
        return contents
    for path in sorted(archive_dir.glob(f"{prefix}-*.md")):
        for record_id_value, content in archive_record_contents(
            overrides[path] if overrides and path in overrides else read_markdown(path)
        ).items():
            previous = contents.setdefault(record_id_value, content)
            if previous != content:
                raise ArchiveConflictError(f"archive ID collision: {record_id_value}")
    return contents


def atomic_write(
    path: Path, content: str, *, preserve_newlines: bool = True, preserve_mode: bool = True
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if preserve_mode and path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="" if preserve_newlines else None) as handle:
            if existing_mode is not None:
                os.chmod(temporary_name, existing_mode)
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
        + "".join(record.render() for record in to_append).lstrip("\r\n")
    )
    if not addition.endswith("\n"):
        addition += "\n"
    return existing_text.rstrip("\r\n") + "\n\n" + addition


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
        read_markdown(path)
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
    archive_overrides: dict[Path, str] | None = None,
) -> list[tuple[Path, str]]:
    """Build every file --apply would write, in commit order.

    Archive files come first (deduplicated against every existing archive),
    then the trimmed active files, then the state file last. Nothing is
    written here; callers commit the returned list with commit_writes().
    """
    # Validate the entire active file, not just the subset selected by policy.
    # Otherwise a duplicate can be split across active and archive files.
    for record_file in (lesson_file, todo_file):
        seen_ids: set[str] = set()
        for record in record_file.records:
            if record.stable_id in seen_ids:
                raise ArchiveConflictError(f"active ID collision: {record.stable_id}")
            seen_ids.add(record.stable_id)

    # All archive contents are prepared first, then the trimmed active
    # files, then the state file last: commit order is
    # [archive lessons, archive todos, active lessons, active todos, state].
    archive_writes: list[tuple[Path, str]] = []
    if plan.lessons:
        archive_path = archive_dir / f"lessons-{today.isoformat()}.md"
        existing = (
            read_markdown(archive_path)
            if archive_path.exists()
            else f"# Archived lessons records\n\n"
        )
        if archive_overrides and archive_path in archive_overrides:
            existing = archive_overrides[archive_path]
        content = prepare_archive_content(
            existing,
            "lessons",
            lesson_path,
            plan.lessons,
            today,
            collect_archive_records(archive_dir, "lessons", archive_overrides),
        )
        if content is not None:
            archive_writes.append((archive_path, content))
    if plan.todos:
        archive_path = archive_dir / f"todo-{today.isoformat()}.md"
        existing = (
            read_markdown(archive_path)
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
        self._contents: bytes | None = None

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
        contents = f"{os.getpid()}\n{secrets.token_hex(16)}\n".encode("ascii")
        with self.path.open("xb") as handle:
            handle.write(contents)
            stat_result = os.fstat(handle.fileno())
            self._identity = (stat_result.st_dev, stat_result.st_ino)
            self._contents = contents

    def _read_pid(self) -> int | None:
        try:
            text = self.path.read_text(encoding="utf-8").partition("\n")[0].strip()
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
                    try:
                        contents = self.path.read_bytes()
                    except OSError:
                        contents = None
                    if contents == self._contents:
                        self.path.unlink()
            self._acquired = False
            self._identity = None
            self._contents = None
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


def write_record_change(args: argparse.Namespace, path: Path, content: str,
                        extra_writes: list[tuple[Path, str]] | None = None) -> bool:
    """Called under the maintenance lock; preflight records and archives before writing."""
    if not getattr(args, "maintain", False):
        changed = not path.exists() or read_markdown(path) != content
        if changed:
            atomic_write(path, content)
        remaining = [(target, body) for target, body in (extra_writes or [])
                     if not target.exists() or read_markdown(target) != body]
        if remaining:
            commit_writes(remaining)
        return changed or bool(remaining)
    lesson_path, todo_path, state_path, archive_dir = project_files(args.project_root)
    lesson_file = load_record_file(lesson_path, "lesson", content if path == lesson_path else None)
    todo_file = load_record_file(todo_path, "todo", content if path == todo_path else None)
    today = resolve_today(args.today)
    plan = build_cleanup_plan(today, policy_from_args(args), load_state(state_path),
                              lesson_file, todo_file, args.force)
    try:
        writes = prepare_cleanup_writes(today, archive_dir, lesson_path, todo_path, state_path,
                                        lesson_file, todo_file, plan,
                                        {path: content} if path.parent == archive_dir else None) if plan.due_reasons else []
    except (ArchiveConflictError, OSError, UnicodeError) as error:
        raise SystemExit(f"record update aborted before writing: {error}") from error
    if not any(target == path for target, _ in writes):
        writes.insert(max(0, len(writes) - 1), (path, content))
    if extra_writes:
        position = len(writes) - 1 if plan.due_reasons else len(writes)
        writes[position:position] = extra_writes
    writes = [(target, body) for target, body in writes
              if not target.exists() or read_markdown(target) != body]
    try:
        commit_writes(writes)
    except CommitError as error:
        raise SystemExit(report_commit_error(error)) from error
    if not getattr(args, "quiet", False) and not getattr(args, "json_output", False):
        print_plan(plan, lesson_file, todo_file)
        if plan.due_reasons:
            print("Maintenance checked and applied; no separate status call is needed.")
    return bool(writes)


def print_record_result(args: argparse.Namespace, identity: str, kind: str, status: str,
                        action: str, changed: bool, message: str, *,
                        maintenance_checked: bool | None = None, **details) -> None:
    if getattr(args, "json_output", False):
        print(json.dumps({"id": identity, "kind": kind, "action": action,
                          "status": status, "changed": changed,
                          "maintenance_checked": bool(args.maintain) if maintenance_checked is None else maintenance_checked,
                          **details}, ensure_ascii=False))
    else:
        print(message)


def command_mark_used(args: argparse.Namespace) -> int:
    lesson_path, _, _, archive_dir = project_files(args.project_root)
    with create_lock(args.project_root):
        lesson_file = load_record_file(lesson_path, "lesson")
        matches = [
            record for record in lesson_file.records
            if (record.stable_id == args.id if args.id else record.title == args.lesson)
        ]
        if not matches and args.id:
            archived_matches = []
            for path in sorted(archive_dir.glob("lessons-*.md")):
                archived = load_record_file(path, "lesson")
                archived_matches.extend((archived, record) for record in archived.records if record.stable_id == args.id)
            if len(archived_matches) == 1:
                lesson_file, record = archived_matches[0]
                matches = [record]
            elif archived_matches:
                raise SystemExit("lesson ID is ambiguous across archives")
        if not matches:
            raise SystemExit(f"lesson not found or missing metadata: {args.lesson}")
        if len(matches) > 1:
            raise SystemExit(f"lesson title is not unique: {args.lesson}")

        record = matches[0]
        if lesson_status(record) != "active":
            raise SystemExit("inactive lesson cannot count as a useful application; read its replacement")
        try:
            use_count = int(record.fields.get("use_count", ""))
        except ValueError as error:
            raise SystemExit(f"lesson has invalid use_count: {args.lesson}") from error
        if use_count < 0:
            raise SystemExit(f"lesson has invalid use_count: {args.lesson}")
        if args.task_id:
            task = short_field(args.task_id, "task-id", 128)
            task_key = hashlib.sha256(task.encode()).hexdigest()[:32]
            used = record.fields.get("used_tasks", "").split(",")
            if task_key in used:
                print_record_result(args, record.stable_id, "lesson", "active", "unchanged", False,
                    f"Usage already counted for task {task}; no write needed.",
                    maintenance_checked=False, use_count=use_count)
                return 0
            record.fields["used_tasks"] = ",".join([key for key in used if key] + [task_key])
        record.fields["use_count"] = str(use_count + 1)
        record.fields["last_used_at"] = resolve_today(args.today).isoformat()
        changed = write_record_change(args, lesson_file.path, render_record_file(lesson_file))
    print_record_result(args, record.stable_id, "lesson", "active", "updated", changed,
        f"Marked lesson used: {record.title} "
        f"(use_count={record.fields['use_count']}, "
        f"last_used_at={record.fields['last_used_at']})",
        use_count=use_count + 1, last_used_at=record.fields["last_used_at"])
    return 0


def command_find_lessons(args: argparse.Namespace) -> int:
    """Print matching lesson records without modifying project files."""
    if args.limit < 1:
        raise SystemExit("--limit must be a positive integer")
    lesson_path, _, _, archive_dir = project_files(args.project_root)
    lesson_file = load_record_file(lesson_path, "lesson")
    query = args.query.casefold()
    matches = [
        (lesson_file, record)
        for record in searchable_lesson_records(lesson_file)
        if (args.include_inactive or lesson_status(record) == "active")
        and (query in record.title.casefold() or query in record.raw.casefold())
    ]
    searched_archive = not matches or args.include_archive
    if searched_archive:
        for path in sorted(archive_dir.glob("lessons-*.md")):
            archived = load_record_file(path, "lesson")
            matches.extend((archived, record) for record in searchable_lesson_records(archived)
                           if (args.include_inactive or lesson_status(record) == "active")
                           and (query in record.title.casefold() or query in record.raw.casefold()))
    matches.sort(key=lambda item: (
        0 if item[1].title.casefold() == query else 1 if query in item[1].title.casefold() else 2,
        item[1].fields.get("pinned", "false").lower() != "true",
    ))
    total = len(matches)
    matches = matches[:args.limit]
    if args.json_output:
        print(json.dumps({"matches": [lesson_json(source, record) for source, record in matches],
                          "total_matches": total, "truncated": total > len(matches),
                          "searched_archive": searched_archive},
                         ensure_ascii=False, indent=2))
        return 0
    if not matches:
        print("No lessons matched.")
        return 0
    for source, record in matches:
        if source.path != lesson_path:
            print(f"[archive: {source.path.name}]")
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
    if total > len(matches):
        print(f"Showing {len(matches)} of {total} matches; increase --limit to read more.")
    return 0


def validate_new_record_field(value: str, name: str, *, title: bool = False) -> str:
    """Reject input that would change Markdown record boundaries."""
    value = value.strip()
    if not value:
        raise SystemExit(f"{name} must not be empty")
    if title:
        if "\n" in value or "\r" in value:
            raise SystemExit("title must be a single line")
        return value

    fence = ""
    for line in value.splitlines():
        match = FENCE_PATTERN.match(line)
        if match:
            delimiter = match.group(1)
            if not fence:
                fence = delimiter
            elif (delimiter[0] == fence[0] and len(delimiter) >= len(fence)
                  and not line[match.end():].strip()):
                fence = ""
            continue
        if not fence:
            heading = HEADING_PATTERN.match(line)
            if heading and len(heading.group(0)) - len(heading.group(0).lstrip("#")) <= 2:
                raise SystemExit(f"{name} cannot contain a top-level record heading")
            if MARKER_PATTERN.match(line):
                raise SystemExit(f"{name} cannot contain an unfenced record marker")
    if fence:
        raise SystemExit(f"{name} contains an unclosed Markdown fence")
    return value


def load_record_template(kind: str) -> str:
    """Load the sole distributed template and reject incomplete scaffolds."""
    path = Path(__file__).resolve().parent.parent / "assets" / f"{'todo' if kind == 'todo' else 'lessons'}.md"
    try:
        template = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SystemExit(f"cannot read {kind} template {path}: {error}") from error

    # The template's first comment is an instruction to its reader, not a record.
    first, separator, rest = template.partition("\n")
    if first.strip().startswith("<!--") and "aitasks:" not in first:
        if not separator or not first.strip().endswith("-->"):
            raise SystemExit(f"invalid {kind} template instruction comment")
        template = rest
    template = template.lstrip("\r\n")

    expected_placeholders = {
        "{{UUID4_HEX}}", "{{YYYY-MM-DD}}",
        *({"{{任务标题}}", "{{要达成的结果及受影响范围。}}", "{{计划的必要验证；完成后写入实际结果。}}"}
          if kind == "todo" else
          {"{{经验标题}}", "{{经验出现的上下文。}}", "{{需要避免或解决的问题。}}",
           "{{经证实的原因；尚未确认则写“未确认”，不要猜测。}}", "{{可直接执行的处理方法。}}", "{{适用的项目、模块或条件。}}"}),
    }
    placeholder_pattern = re.compile(r"\{\{[^{}\r\n]+\}\}")
    placeholders = placeholder_pattern.findall(template)
    leftover = placeholder_pattern.sub("", template)
    if (set(placeholders) != expected_placeholders or len(placeholders) != len(expected_placeholders)
            or "{{" in leftover or "}}" in leftover):
        raise SystemExit(f"invalid {kind} template placeholders in {path}")
    markers = record_markers(template)
    if len(markers) != 1 or markers[0].start() != 0 or markers[0].group("kind") != kind:
        raise SystemExit(f"invalid {kind} template record marker in {path}")
    probe = "\n\n<!-- aitasks:todo id=template-end-probe -->\n## Template end probe\n"
    if len(record_markers(template + probe)) != 2:
        raise SystemExit(f"invalid {kind} template Markdown fence in {path}")
    fields = list(FIELD_PATTERN.finditer(markers[0].group("fields")))
    names = [field.group("key") for field in fields]
    values = {field.group("key"): field.group("value") for field in fields}
    required = {"id": "{{UUID4_HEX}}", "created_at": "{{YYYY-MM-DD}}"}
    required.update({"status": "active", "completed_at": "-"} if kind == "todo" else
                    {"last_used_at": "-", "use_count": "0", "pinned": "false"})
    headings = [heading for heading in unfenced_matches(template, HEADING_PATTERN)
                if heading.start() > markers[0].end()]
    title_placeholder = "{{任务标题}}" if kind == "todo" else "{{经验标题}}"
    if (FIELD_PATTERN.sub("", markers[0].group("fields")).strip()
            or len(names) != len(set(names)) or any(values.get(key) != value for key, value in required.items())
            or not headings or headings[0].group("title") != title_placeholder):
        raise SystemExit(f"invalid {kind} template metadata or title in {path}")
    return template


def render_record_template(template: str, kind: str, replacements: dict[str, str], pinned: bool) -> str:
    """Replace template tokens once; never interpret tokens in user input."""
    marker = record_markers(template, kind)[0]
    if kind == "lesson" and pinned:
        field = next(field for field in FIELD_PATTERN.finditer(marker.group("fields"))
                     if field.group("key") == "pinned")
        start = marker.start("fields") + field.start()
        end = marker.start("fields") + field.end()
        template = template[:start] + "pinned=true" + template[end:]

    def replace(match: re.Match[str]) -> str:
        value = replacements[match.group(0)]
        # Fences in multiline lesson values must start on their own line.
        prefix = template[template.rfind("\n", 0, match.start()) + 1:match.start()]
        return "\n\n" + value if kind == "lesson" and "\n" in value and prefix.strip() else value

    rendered = re.sub(r"\{\{[^{}\r\n]+\}\}", replace, template)
    return rendered if rendered.endswith("\n") else rendered + "\n"


def command_add_record(args: argparse.Namespace) -> int:
    """Append one structured record while holding the same lock as maintenance."""
    kind = args.kind
    title = validate_new_record_field(args.title, "title", title=True)
    if kind == "todo":
        goal = validate_new_record_field(args.goal, "goal")
        verify = validate_new_record_field(args.verify, "verify")
    else:
        context = validate_new_record_field(args.context, "context")
        problem = validate_new_record_field(args.problem, "problem")
        cause = validate_new_record_field(args.cause, "cause")
        resolution = validate_new_record_field(args.resolution, "resolution")
        scope = validate_new_record_field(args.scope, "scope")

    template = load_record_template(kind)
    today = resolve_today(args.today).isoformat()
    lesson_path, todo_path, _, _ = project_files(args.project_root)
    path = todo_path if kind == "todo" else lesson_path
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise SystemExit(".aitasks must already be a non-symlink directory; check project ignore rules before creating it")
    with create_lock(args.project_root):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise SystemExit(f"expected a regular file or no path at: {path}")
        existing_file = load_record_file(path, kind)
        extra_writes = []
        if getattr(args, "upsert", False):
            key = short_field(args.key, "key", 200).casefold() if args.key else None
            observation_path, observations = (load_observations(args.project_root) if key else
                                               (None, {"observations": {}}))
            signature = hashlib.sha256(key.encode()).hexdigest()[:32] if key else None
            observation = observations["observations"].get(signature) if signature else None
            linked_id = (observation or {}).get("lesson_id")
            if args.id and linked_id and args.id != linked_id:
                raise SystemExit("observation key is already linked to a different lesson ID")
            selected_id = args.id or linked_id
            # An ID or the creation signature identifies a record; a shared title does not.
            # Search archives too, including when an interrupted link write is retried.
            archive_dir = project_files(args.project_root)[3]
            files = [existing_file] + [load_record_file(p, "lesson")
                                       for p in sorted(archive_dir.glob("lessons-*.md"))]
            matches = [(source, r) for source in files for r in source.records
                       if (r.stable_id == selected_id if selected_id else
                           bool(signature) and r.fields.get("observation_sig") == signature)]
            if len(matches) > 1 or (selected_id and not matches):
                raise SystemExit("lesson ID or observation signature is ambiguous or missing; read it before revising")
            selected_file, selected = matches[0] if matches else (None, None)
            if selected_file is not None and (selected_file.path.is_symlink() or selected_file.path.parent.is_symlink()):
                raise SystemExit("refusing to update a symlinked lesson file or archive directory")
            if selected is not None and lesson_status(selected) != "active":
                raise SystemExit("lesson is inactive; read its replacement or explicitly reactivate before updating")
            if not args.explicit:
                if cause.casefold() in {"未确认", "unknown", "unconfirmed"}:
                    raise SystemExit("automatic recording requires a confirmed cause")
                if not key or (selected is None and len((observation or {}).get("tasks", [])) < 2):
                    raise SystemExit("automatic recording requires two independent verified tasks")
            if key:
                row = observation or {"key": key, "tasks": [], "evidence": "", "lesson_id": None}
                observations["observations"][signature] = row
            if selected is not None:
                for label, value in (("场景", context), ("问题", problem), ("原因", cause),
                                     ("正确做法", resolution), ("适用范围", scope)):
                    update_lesson_field(selected, label, value)
                if key and row["evidence"]:
                    update_lesson_field(selected, "依据", row["evidence"])
                if key:
                    row["lesson_id"] = selected.stable_id
                    extra_writes.append((observation_path, json.dumps(observations, ensure_ascii=False)))
                changed = write_record_change(args, selected_file.path, render_record_file(selected_file), extra_writes)
                print_record_result(args, selected.stable_id, "lesson", lesson_status(selected),
                                    "updated", changed, "")
                return 0
        if any(record.title == title for record in searchable_lesson_records(existing_file)):
            raise SystemExit(f"{kind} title already exists: {title}")
        # UUID4 is unpredictable; checking active IDs also handles accidental collisions.
        existing_ids = {record.stable_id for record in existing_file.records}
        record_id_value = uuid4().hex
        while record_id_value in existing_ids:
            record_id_value = uuid4().hex
        replacements = {"{{UUID4_HEX}}": record_id_value, "{{YYYY-MM-DD}}": today}
        if kind == "todo":
            replacements.update({"{{任务标题}}": title, "{{要达成的结果及受影响范围。}}": goal,
                                 "{{计划的必要验证；完成后写入实际结果。}}": verify})
        else:
            replacements.update({"{{经验标题}}": title, "{{经验出现的上下文。}}": context,
                                 "{{需要避免或解决的问题。}}": problem,
                                 "{{经证实的原因；尚未确认则写“未确认”，不要猜测。}}": cause,
                                 "{{可直接执行的处理方法。}}": resolution, "{{适用的项目、模块或条件。}}": scope})
        record = render_record_template(template, kind, replacements, getattr(args, "pinned", False))
        if getattr(args, "upsert", False) and key:
            # Persist identity with the lesson before linking the observation. This
            # allows a retry after a partial write without guessing from the title.
            marker = record_markers(record, kind)[0]
            record = record[:marker.end("fields")] + f" observation_sig={signature}" + record[marker.end("fields"):]
        if getattr(args, "upsert", False) and key and row["evidence"]:
            record += "\n- 依据：" + row["evidence"] + "\n"
        if len(record_markers(record, kind)) != 1:
            raise SystemExit("record content would create additional metadata records")
        # Read without universal-newline conversion; preserve every existing byte.
        if path.exists():
            with path.open(encoding="utf-8", newline="") as handle:
                original = handle.read()
        else:
            original = ""
        separator = "" if not original or original.endswith("\n\n") else (
            "\n" if original.endswith("\n") else "\n\n"
        )
        combined = original + separator + record
        record_start = len(original) + len(separator)
        if not any(marker.start() == record_start for marker in record_markers(combined, kind)):
            raise SystemExit("existing Markdown would hide the new record; inspect its unclosed code fences")
        if getattr(args, "upsert", False) and key:
            row["lesson_id"] = record_id_value
            extra_writes.append((observation_path, json.dumps(observations, ensure_ascii=False)))
        changed = write_record_change(args, path, combined, extra_writes)
    print_record_result(args, record_id_value, kind, "active", "created", changed,
                        f"Added {kind}: {title} (id={record_id_value})"
                        + ("" if args.maintain else "; check maintenance thresholds with status"))
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
        changed = write_record_change(args, todo_path, render_record_file(todo_file))
    print_record_result(args, record.stable_id, "todo", args.status, "updated" if changed else "unchanged", changed,
        f"Updated todo: {record.title} "
        f"(status={record.fields['status']}, "
        f"completed_at={record.fields['completed_at']})")
    return 0


def short_field(value: str, name: str, limit: int) -> str:
    value = validate_new_record_field(value, name, title=True)
    if len(value) > limit:
        raise SystemExit(f"{name} must be at most {limit} characters; use an evidence reference, not raw logs")
    return value


def load_observations(project_root: Path) -> tuple[Path, dict]:
    path = project_files(project_root)[0].parent / ".observations.json"
    if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
        raise SystemExit("observations require an existing non-symlink .aitasks directory and regular state file")
    if not path.exists():
        return path, {"version": 1, "observations": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("observations"), dict):
            raise ValueError("unsupported schema")
        for signature, row in data["observations"].items():
            if (not isinstance(row, dict) or not isinstance(row.get("key"), str)
                    or not isinstance(row.get("tasks"), list) or len(row["tasks"]) > 2
                    or not all(isinstance(task, str) and task for task in row["tasks"])
                    or len(set(row["tasks"])) != len(row["tasks"])
                    or not isinstance(row.get("evidence"), str)
                    or not (row.get("lesson_id") is None or isinstance(row["lesson_id"], str))):
                raise ValueError("invalid observation")
            if signature != hashlib.sha256(row["key"].encode()).hexdigest()[:32]:
                raise ValueError("observation signature does not match its key")
        return path, data
    except (OSError, ValueError) as error:
        raise SystemExit(f"invalid observation state; preserved without overwriting: {error}") from error


def command_observe(args: argparse.Namespace) -> int:
    if not args.verified:
        print(json.dumps({"decision": "skip", "reason": "unverified"}))
        return 0
    key = short_field(args.key, "key", 200).casefold()
    task = short_field(args.task_id, "task-id", 128)
    evidence = short_field(args.evidence, "evidence", 300)
    directory = project_files(args.project_root)[0].parent
    if not directory.is_dir() or directory.is_symlink():
        raise SystemExit("create .aitasks under the project ignore rules before recording observations")
    with create_lock(args.project_root):
        path, state = load_observations(args.project_root)
        signature = hashlib.sha256(key.encode()).hexdigest()[:32]
        row = state["observations"].get(signature)
        if row is None:
            row = {"key": key, "tasks": [], "evidence": evidence, "lesson_id": None}
            state["observations"][signature] = row
        if task not in row["tasks"] and len(row["tasks"]) < 2:
            row["tasks"].append(task)
            row["evidence"] = evidence
            atomic_write(path, json.dumps(state, ensure_ascii=False))
        count = len(row["tasks"])
        decision = "recorded" if row["lesson_id"] else "ready" if count >= 2 else "candidate"
    print(json.dumps({"decision": decision, "count": count, "lesson_id": row["lesson_id"]}, ensure_ascii=False))
    return 0


def command_find_observations(args: argparse.Namespace) -> int:
    terms = args.query.casefold().split()
    if not terms or args.limit < 1:
        raise SystemExit("find-observations requires nonempty keywords and a positive limit")
    concepts = query_concepts(args.project_root, terms)
    directory = project_files(args.project_root)[0].parent
    state = load_observations(args.project_root)[1] if directory.exists() else {"observations": {}}
    matches = []
    for row in state["observations"].values():
        key = row["key"].casefold()
        content = key + " " + row["evidence"].casefold()
        hits = sum(any(term in content for term in concept) for concept in concepts)
        if not hits:
            continue
        key_hits = sum(any(term in key for term in concept) for concept in concepts)
        count = len(row["tasks"])
        summary = {"key": row["key"], "count": count, "evidence": row["evidence"],
                   "lesson_id": row["lesson_id"],
                   "decision": "recorded" if row["lesson_id"] else "ready" if count >= 2 else "candidate"}
        matches.append(((-hits, -key_hits), summary))
    matches.sort(key=lambda item: item[0])
    payload = {"observations": [row for _, row in matches[:args.limit]],
               "total_matches": len(matches), "truncated": len(matches) > args.limit}
    print(bounded_json(payload, args.max_chars))
    return 0


def update_lesson_field(record: Record, label: str, value: str) -> None:
    newline = "\r\n" if "\r\n" in record.raw else "\n"
    value = value.replace("\r\n", "\n").replace("\n", newline)
    rendered = newline * 2 + value if newline in value else value
    fields = unfenced_matches(record.raw, re.compile(r"^- (?P<label>[^：:\r\n]+)[：:][^\r\n]*(?=\r?$)", re.MULTILINE))
    headings = unfenced_matches(record.raw, HEADING_PATTERN)
    for field in fields:
        if field.group("label") == label:
            end = min([other.start() for other in fields + headings if other.start() > field.start()] + [len(record.raw)])
            old_line = record.raw[field.start():field.end()]
            old_value = re.split(r"[：:]", old_line, maxsplit=1)[1].strip()
            tail = record.raw[field.end():end]
            first_content_line = next((line for line in tail.splitlines() if line.strip()), "")
            if (not old_value and tail.strip()) or re.match(r"^[ \t]+\S", first_content_line):
                raise SystemExit(f"multiline {label} has ambiguous boundaries; review and update manually")
            record.raw = record.raw[:field.start()] + f"- {label}：{rendered}" + record.raw[field.end():]
            return
    record.raw = record.raw.rstrip("\r\n") + newline + f"- {label}：{rendered}" + newline


def command_set_lesson_status(args: argparse.Namespace) -> int:
    reason = validate_new_record_field(args.reason, "reason")
    lesson_path, _, _, archive_dir = project_files(args.project_root)
    with create_lock(args.project_root):
        files = [load_record_file(path, "lesson") for path in
                 [lesson_path, *sorted(archive_dir.glob("lessons-*.md"))]]
        matches = [(source, record) for source in files for record in source.records if record.stable_id == args.id]
        if len(matches) != 1:
            raise SystemExit("lesson ID must match exactly one metadata record")
        source, record = matches[0]
        if args.status == "superseded":
            targets = [r for f in files for r in f.records if r.stable_id == args.superseded_by]
            if len(targets) != 1 or targets[0].stable_id == record.stable_id or lesson_status(targets[0]) != "active":
                raise SystemExit("superseded requires one distinct existing active replacement ID")
        elif args.superseded_by:
            raise SystemExit("--superseded-by is only valid for superseded lessons")
        record.fields.update(status=args.status, superseded_by=args.superseded_by or "-",
                             status_changed_at=resolve_today(args.today).isoformat())
        update_lesson_field(record, "状态依据", reason)
        write_record_change(args, source.path, render_record_file(source))
    print(json.dumps({"id": record.stable_id, "status": args.status, "superseded_by": args.superseded_by,
                      "maintenance_checked": True}, ensure_ascii=False))
    return 0


def update_todo_section(record: Record, title: str, value: str) -> None:
    newline = "\r\n" if "\r\n" in record.raw else "\n"
    value = value.replace("\r\n", "\n").replace("\n", newline)
    headings = unfenced_matches(record.raw, HEADING_PATTERN)
    for index, heading in enumerate(headings):
        if heading.group(0).startswith("### ") and heading.group("title") == title:
            end = next((other.start() for other in headings[index + 1:]
                        if len(other.group(0)) - len(other.group(0).lstrip("#")) <= 3), len(record.raw))
            if record.raw[heading.end():end].strip("\r\n") == value:
                return
            record.raw = (record.raw[:heading.end()] + newline * 2 + value + newline * 2
                          + record.raw[end:])
            return
    record.raw = record.raw.rstrip("\r\n") + newline * 2 + f"### {title}" + newline * 2 + value + newline


def command_finish_todo(args: argparse.Namespace) -> int:
    result = validate_new_record_field(args.result, "result")
    verify = validate_new_record_field(args.verify, "verify") if args.verify is not None else None
    todo_path = project_files(args.project_root)[1]
    with create_lock(args.project_root):
        todo_file = load_record_file(todo_path, "todo")
        matches = [r for r in todo_file.records
                   if (r.stable_id == args.id if args.id else r.title == args.todo)]
        if len(matches) != 1:
            raise SystemExit("todo selector must match exactly one metadata record")
        record = matches[0]
        record.fields.update(status=args.status, completed_at=resolve_today(args.today).isoformat())
        update_todo_section(record, "结果", result)
        if verify is not None:
            update_todo_section(record, "验证", verify)
        changed = write_record_change(args, todo_path, render_record_file(todo_file))
    print_record_result(args, record.stable_id, "todo", args.status, "updated" if changed else "unchanged", changed,
                        f"Finished todo: {record.title} (id={record.stable_id}, status={args.status})")
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
    mark_selector = mark_parser.add_mutually_exclusive_group(required=True)
    mark_selector.add_argument("--lesson", help="Exact lesson heading text.")
    mark_selector.add_argument("--id")
    mark_parser.add_argument("--task-id", help="Count this task only once; lookup alone is not a use.")
    add_policy_arguments(mark_parser)
    mark_parser.add_argument("--maintain", action="store_true", help="Check and apply due maintenance in this write.")
    mark_parser.add_argument("--json", dest="json_output", action="store_true")
    mark_parser.set_defaults(handler=command_mark_used)

    find_parser = commands.add_parser(
        "find-lessons", help="Find lessons by title or body text without editing."
    )
    find_parser.add_argument("--query", required=True, help="One case-insensitive literal substring, not a regex or keyword list.")
    find_parser.add_argument("--limit", type=int, default=10)
    find_parser.add_argument("--include-inactive", action="store_true", help="Explicitly audit retired and superseded lessons too.")
    find_parser.add_argument("--include-archive", action="store_true",
                             help="Search archives alongside active lessons; otherwise use archives only on a miss.")
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
    add_policy_arguments(todo_parser)
    todo_parser.add_argument("--maintain", action="store_true")
    todo_parser.add_argument("--json", dest="json_output", action="store_true")

    add_query_commands(commands)

    lesson_status_parser = commands.add_parser("set-lesson-status", help="Retire, supersede or reactivate one lesson with evidence.")
    lesson_status_parser.add_argument("--id", required=True)
    lesson_status_parser.add_argument("--status", required=True, choices=("active", "retired", "superseded"))
    lesson_status_parser.add_argument("--superseded-by", help="Existing active replacement ID, required for superseded.")
    lesson_status_parser.add_argument("--reason", required=True, help="Verified contract or evidence for this lifecycle change.")
    add_policy_arguments(lesson_status_parser)
    lesson_status_parser.set_defaults(handler=command_set_lesson_status, maintain=True, quiet=True)

    finish = commands.add_parser("finish-todo", help="Write result, verification, status and due maintenance together.")
    selector = finish.add_mutually_exclusive_group(required=True)
    selector.add_argument("--id")
    selector.add_argument("--todo", help="Exact unique title for legacy callers.")
    finish.add_argument("--result", required=True)
    finish.add_argument("--verify")
    finish.add_argument("--status", choices=("completed", "cancelled"), default="completed")
    finish.add_argument("--json", dest="json_output", action="store_true")
    add_policy_arguments(finish)
    finish.set_defaults(handler=command_finish_todo, maintain=True)

    add_todo = commands.add_parser("add-todo", help="Add a new active todo under the maintenance lock.")
    add_todo.add_argument("--title", required=True)
    add_todo.add_argument("--goal", required=True, help="Goal and affected scope.")
    add_todo.add_argument("--verify", required=True, help="Necessary verification plan.")
    add_todo.set_defaults(handler=command_add_record, kind="todo")
    add_policy_arguments(add_todo)
    add_todo.add_argument("--maintain", action="store_true")
    add_todo.add_argument("--json", dest="json_output", action="store_true")

    add_lesson = commands.add_parser("add-lesson", help="Add a new lesson under the maintenance lock.")
    add_lesson.add_argument("--title", required=True)
    add_lesson.add_argument("--context", required=True)
    add_lesson.add_argument("--problem", required=True)
    add_lesson.add_argument("--cause", required=True, help="Use 未确认 if the cause is unproven.")
    add_lesson.add_argument("--resolution", required=True)
    add_lesson.add_argument("--scope", required=True)
    add_lesson.add_argument("--pinned", action="store_true")
    add_lesson.set_defaults(handler=command_add_record, kind="lesson")
    add_policy_arguments(add_lesson)
    add_lesson.add_argument("--maintain", action="store_true")
    add_lesson.add_argument("--json", dest="json_output", action="store_true")

    observe = commands.add_parser("observe", help="Count independent verified tasks; never creates a formal lesson.")
    observe.add_argument("--key", required=True, help="Stable module/symptom/cause signature, not a task description.")
    observe.add_argument("--task-id", required=True)
    observe.add_argument("--evidence", required=True, help="Short source or log reference, at most 300 characters.")
    observe.add_argument("--verified", action="store_true", help="Agent has confirmed this non-expected failure's cause.")
    observe.set_defaults(handler=command_observe)

    observation_query = commands.add_parser("find-observations", help="Read bounded candidate keys and evidence; never increments counts or merges causes.")
    observation_query.add_argument("--query", required=True, help="Space-separated module, symptom or cause keywords.")
    observation_query.add_argument("--limit", type=int, default=3)
    observation_query.add_argument("--max-chars", type=int, default=2000)
    observation_query.set_defaults(handler=command_find_observations)

    upsert = commands.add_parser("upsert-lesson", help="Record explicit instructions or a verified repeat; update a uniquely identified lesson.")
    upsert.add_argument("--title", required=True)
    upsert.add_argument("--context", required=True)
    upsert.add_argument("--problem", required=True)
    upsert.add_argument("--cause", required=True)
    upsert.add_argument("--resolution", required=True)
    upsert.add_argument("--scope", required=True)
    upsert.add_argument("--id", help="Update this active or archived lesson without replacing its identity or extra notes.")
    upsert.add_argument("--key", help="Link the observation signature; automatic creation requires two tasks.")
    upsert.add_argument("--explicit", action="store_true", help="The user explicitly requested recording; bypass recurrence count.")
    add_policy_arguments(upsert)
    upsert.set_defaults(handler=command_add_record, kind="lesson", upsert=True, maintain=True, quiet=True, json_output=True)

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
