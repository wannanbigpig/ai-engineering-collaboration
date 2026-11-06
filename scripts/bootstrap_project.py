#!/usr/bin/env python3
"""Install this repository's engineering-collaboration setup into one project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


AGENTS_BEGIN = "<!-- ai-engineering-collaboration:begin -->"
AGENTS_END = "<!-- ai-engineering-collaboration:end -->"
COMPATIBILITY_SKILL_DIRS = (
    ("Gemini", ".gemini"),
    ("Claude Code", ".claude"),
    ("ZCode", ".zcode"),
)
DISTRIBUTION_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
MANAGED_AGENTS_SECTION = f"""{AGENTS_BEGIN}
# AI Engineering Collaboration

- Read and follow applicable `AGENTS.md`, `AGENTS.override.md`, and `CLAUDE.md`; closer project rules take precedence.
- At task start, scope changes, or confirmation of a new root cause, use the installed maintenance tool's `context` with module/symbol/error keywords when supported. Read bounded summaries first, then one relevant record by ID; never load whole lesson/todo files. Reuse unchanged context only within this conversation; use bounded targeted search if the tool is unavailable.
- Check only material assumptions and gaps; distinguish verified facts from inferences and unknowns. Source-check time-sensitive or high-stakes claims, and explain disagreements that would change the outcome.
- Inspect relevant implementation, constraints, and existing edits before changing code; make the smallest root-cause fix and preserve unrelated work. Validate changed behavior in proportion to risk, reuse fresh evidence, and state what remains unverified.
- Add validation, fallbacks, or compatibility branches only for contracts, reachable failures, or concrete risks. Reuse validated data within the same trust boundary; preserve necessary authorization, transaction, and concurrency safeguards.
- Follow existing repository tools and workflows. Extract helpers for real reuse, a clear concept, or a meaningful reduction in complexity, keeping the main flow readable. Change generated files through their source and regenerate them.
- Consider the experience of users, developers, and AI Agents on every change: improve relevant aspects within scope without degrading the others or expanding the task just to improve all three. Preserve existing functionality and contracts except for explicitly requested behavior changes, and validate affected paths in proportion to risk.
- For UI and other user-facing information, remove slogans, repeated explanations, and decorative labels that do not help understanding, decisions, or actions. Keep necessary names, domain explanations, status, guidance, and accessibility information. If extensive explanation is still needed, inspect hierarchy, grouping, naming, and action paths; adjust confirmed layout problems within scope.
- Use `aitasks-maintenance` for one todo per code-editing task and actual results. Record explicit requests immediately; otherwise observe verified reusable causes across independent task IDs and record only a confirmed repeat. Reuse lesson IDs; count a useful application once per task, never a lookup. Read-only tasks write no records, observations, counts, ignore rules, or archives; already-maintained commands need no separate status call.
- Only with a usable `.codegraph/` index, prefer CodeGraph MCP then CLI for unknown code structure or impact; check `codegraph status` when the CLI is available. Use direct search for known paths or simple text, fall back when graph results are insufficient, verify important conclusions against code/tests, and never run `codegraph init` automatically.
- Use `ai-engineering-collaboration` only when the task needs coordination across multiple specialist stages or the user explicitly requests it; handle a single clear workflow directly or with its matching specialist skill.
{AGENTS_END}
"""

CUSTOM_INSTRUCTIONS = """# Engineering defaults

- 使用中文回复；代码、命令、文件名、错误日志和 API 名称保持原文。
- 修改前读取并遵守适用的 `AGENTS.md`、`AGENTS.override.md`、`CLAUDE.md`；更具体路径规则优先。
- 工程任务开始、范围变化或新根因确认时，先按任务关键词轻量检索相关经验与 todo。工具支持时用 `context` 取有界摘要，必要时按 ID 读一条；否则定向取少量命中段落，不整篇读取。不默认整篇加载或更新计数；同一会话复用未变结果，新会话重新取相关摘要。
- 只核对会改变结论或交付的关键前提与信息缺口；保持独立判断，区分已验证事实、推断和未验证项。时效性或高风险结论优先查证；实质分歧说明依据和风险。
- 先调查相关实现、约束及工作区已有改动；Bug 确定根因后做当前任务所需的最小修复，保留无关修改。
- 校验、兜底和兼容分支须有具体依据，同一信任边界内复用已验证数据，保留必要保障。沿用已有工具与流程，抽象须有实际收益；生成文件改源后生成。
- 在任务范围内兼顾用户、开发者和 AI Agent 的体验，保持既有功能与契约。面向用户的信息只保留理解、判断或操作所需内容；保留必要解释、状态、指引与无障碍信息，确认布局问题后局部调整。
- 修改后按风险执行最小必要验证；可复用输入未变的近期结果，不为纯文档变更运行无关测试。未经验证不得宣称通过，无法验证时说明边界。
- 单一明确工程任务直接处理或使用对应专项 Skill；确需跨多个专项阶段统筹或用户明确指定时，使用 `ai-engineering-collaboration`。
- 编辑项目代码时，不论是否使用入口 Skill，都用 `aitasks-maintenance` 维护一条 todo 和实际结果，按阈值先归档再移出，不删除归档；已自动检查维护的命令不再单独查状态。仅修改 `.aitasks` 不递归建 todo。
- 用户明确要求记录经验时立即记录；否则在已授权写入时观察已验证且可复用的问题，按独立任务计数，二次出现再沉淀并优先更新原 ID。未证实原因标“未确认”；只读不写观察、经验、todo、计数、忽略规则或归档，查询不算复用。
- 项目根目录有 `.codegraph/` 且索引可用时，理解未知代码结构、调用链或改动影响优先用 CodeGraph MCP；MCP 不可用且 CLI 可用时改用 CLI，首次使用先运行 `codegraph status`。已知路径或简单文本直接检索；图谱不可用或结果不足时回退常规工具，关键结论核对代码与测试，不自动执行 `codegraph init`。
"""


class BootstrapError(Exception):
    """A safe-to-report bootstrap failure."""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Install AI Engineering Collaboration Skills into a target project."
    )
    install_scope = result.add_mutually_exclusive_group()
    install_scope.add_argument(
        "--target",
        type=Path,
        help="Target project directory.",
    )
    install_scope.add_argument(
        "--scope",
        choices=("user",),
        help="Install all Skills into the current user's ~/.agents/skills directory.",
    )
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing files.",
    )
    result.add_argument(
        "--track-aitasks",
        action="store_true",
        help="Do not add .aitasks/ to the target .gitignore.",
    )
    result.add_argument(
        "--print-custom-instructions",
        action="store_true",
        help="Print the compact global Custom Instructions block for manual pasting.",
    )
    operation = result.add_mutually_exclusive_group()
    operation.add_argument("--check", action="store_true",
                           help="Report installed versions and differences without writing; exit 1 if not current.")
    operation.add_argument("--upgrade-from", type=Path, metavar="OLD_RELEASE",
                           help="Explicitly upgrade copies that still match OLD_RELEASE/skills exactly.")
    result.add_argument("--json", action="store_true",
                        help="With --check, emit one JSON report instead of text; never writes files.")
    return result


def repository_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if not (root / "skills").is_dir():
        raise BootstrapError("Cannot find the source skills directory next to this script.")
    return root


def skill_directories(root: Path) -> list[Path]:
    directories = sorted(path for path in (root / "skills").iterdir() if path.is_dir())
    if not directories or any(not (path / "SKILL.md").is_file() for path in directories):
        raise BootstrapError("Every source skill directory must contain SKILL.md.")
    return directories


def file_manifest(directory: Path) -> dict[str, str]:
    """Compare only distributed files; generated artifacts cannot create conflicts."""
    def inspection_failed(error: OSError) -> None:
        raise BootstrapError(f"Cannot inspect Skill content: {error}") from error

    manifest: dict[str, str] = {}
    for base, directories, files in os.walk(directory, followlinks=False, onerror=inspection_failed):
        ignored = DISTRIBUTION_IGNORE(base, directories + files)
        directories[:] = sorted(name for name in directories if name not in ignored)
        for name in sorted(set(directories + files) - ignored):
            path = Path(base) / name
            if path.is_symlink():
                raise BootstrapError(f"Symlinked skill content is unsupported: {path}")
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest[path.relative_to(directory).as_posix()] = f"{stat.S_IMODE(path.stat().st_mode):o}:{digest}"
    return dict(sorted(manifest.items()))


def read_regular_file(path: Path) -> str:
    if not path.exists() and not path.is_symlink():
        return ""
    if path.is_symlink() or not path.is_file():
        raise BootstrapError(f"Expected a regular file or no path at: {path}")
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def newline_for(content: str) -> str:
    return "\r\n" if "\r\n" in content else "\n"


def render_agents(existing: str) -> str:
    begin_count = existing.count(AGENTS_BEGIN)
    end_count = existing.count(AGENTS_END)
    if begin_count != end_count or begin_count > 1:
        raise BootstrapError("AGENTS.md has incomplete or duplicate managed markers.")
    newline = newline_for(existing)
    managed = MANAGED_AGENTS_SECTION.replace("\n", newline)
    if begin_count == 1:
        start = existing.index(AGENTS_BEGIN)
        end = existing.index(AGENTS_END, start) + len(AGENTS_END)
        return existing[:start] + managed.rstrip("\r\n") + existing[end:]
    if not existing:
        return managed
    return existing + ("" if existing.endswith("\n") else newline) + newline + managed


def has_aitasks_rule(content: str) -> bool:
    normalized = {line.strip() for line in content.splitlines()}
    return bool({".aitasks", ".aitasks/", "/.aitasks", "/.aitasks/"} & normalized)


def run_git(target: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(target), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    )


def git_allows_ignore_update(target: Path) -> tuple[bool, str | None]:
    try:
        repository = run_git(target, "rev-parse", "--is-inside-work-tree")
        if repository.returncode != 0:
            git_marker_exists = any(
                (parent / ".git").exists() or (parent / ".git").is_symlink()
                for parent in (target, *target.parents)
            )
            git_location_overridden = any(
                os.environ.get(name) for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
            )
            if (
                "not a git repository" in repository.stderr.lower()
                and not git_marker_exists
                and not git_location_overridden
            ):
                return True, None
            return False, "Git repository state could not be checked"
        if repository.stdout.strip() == "false":
            return True, None
        if repository.stdout.strip() != "true":
            return False, "Git repository state could not be checked"

        tracked = run_git(target, "ls-files", "--", ".aitasks")
        if tracked.returncode != 0:
            return False, "Git tracked paths could not be checked"
        if tracked.stdout.strip():
            return False, ".aitasks is already tracked by Git"

        history = run_git(target, "log", "--format=", "--unified=0", "-p", "--", ".gitignore")
        if history.returncode != 0:
            # A newly initialized repository has no HEAD and therefore no log.
            refs = run_git(target, "rev-list", "--all", "--max-count=1")
            if refs.returncode != 0 or refs.stdout.strip():
                return False, "Git ignore-rule history could not be checked"
        if any(
            line.startswith("-") and has_aitasks_rule(line[1:])
            for line in history.stdout.splitlines()
        ):
            return False, ".gitignore history contains a removed .aitasks rule"
        return True, None
    except OSError:
        return False, "Git is unavailable; tracked paths and ignore-rule history could not be checked"


def render_gitignore(target: Path, track_aitasks: bool) -> tuple[Path, str | None, str | None]:
    path = target / ".gitignore"
    if track_aitasks:
        return path, None, None
    existing = read_regular_file(path)
    if has_aitasks_rule(existing):
        return path, None, None

    allowed, reason = git_allows_ignore_update(target)
    if not allowed:
        return path, None, reason

    newline = newline_for(existing)
    section = f"# Keep temporary collaboration records out of version control.{newline}.aitasks/{newline}"
    prefix = existing + ("" if existing.endswith("\n") else newline) + newline if existing else ""
    return path, prefix + section, None


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    if existing_mode is not None:
        temporary_path.chmod(existing_mode)
    temporary_path.replace(path)


def skill_install_plan(
    sources: list[Path], destination_root: Path, baseline_skills: Path | None = None
) -> tuple[list[Path], list[Path], list[str]]:
    validate_directory_path(destination_root)

    install_sources: list[Path] = []
    current_sources: list[Path] = []
    conflicts: list[str] = []
    for source in sources:
        source_manifest = file_manifest(source)
        destination = destination_root / source.name
        if destination.is_symlink() and not destination.exists():
            conflicts.append(f"{destination} exists but is not a directory")
        elif not destination.exists():
            install_sources.append(source)
        elif not destination.is_dir():
            conflicts.append(f"{destination} exists but is not a directory")
        elif source_manifest == file_manifest(destination):
            current_sources.append(source)
        elif matches_upgrade_baseline(destination, source.name, baseline_skills):
            install_sources.append(source)
        else:
            conflicts.append(f"{destination} differs from the source Skill")
    return install_sources, current_sources, conflicts


def matches_upgrade_baseline(destination: Path, name: str, baseline_skills: Path | None) -> bool:
    return bool(baseline_skills is not None and not destination.is_symlink()
                and (baseline_skills / name).is_dir()
                and file_manifest(destination) == file_manifest(baseline_skills / name))


def describe_skill(path: Path, manifest: dict[str, str] | None) -> dict:
    skill_file = path / "SKILL.md"
    version = None
    diagnostics = []
    if skill_file.is_file():
        try:
            version = re.search(r"^  version: (.+)$", skill_file.read_text(encoding="utf-8"), re.MULTILINE)
        except UnicodeDecodeError as error:
            diagnostics.append({"code": "invalid_utf8", "path": str(skill_file),
                                "message": f"Cannot read SKILL.md as UTF-8: {error}"})
    return {
        "path": str(path),
        "resolved_path": str(path.resolve()) if path.exists() else None,
        "version": version.group(1) if version else None,
        "diagnostics": diagnostics,
        "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if manifest is not None else None,
    }


def check_installation(target: Path, user_scope: bool, json_output: bool = False) -> int:
    root = repository_root()
    sources = skill_directories(root)
    canonical = target / ".agents/skills"
    different = False
    skills = []
    for source in sources:
        installed = canonical / source.name
        source_manifest = file_manifest(source)
        installed_manifest = file_manifest(installed) if installed.is_dir() else None
        status = ("current" if installed_manifest == source_manifest
                  else "different" if installed.exists() or installed.is_symlink() else "missing")
        different |= status != "current"
        skill = {"name": source.name, "status": status,
                 "source": describe_skill(source, source_manifest),
                 "installed": describe_skill(installed, installed_manifest), "compatibility": []}
        different |= bool(skill["source"]["diagnostics"] or skill["installed"]["diagnostics"])
        for harness, directory in COMPATIBILITY_SKILL_DIRS:
            path = target / directory / "skills" / source.name
            current = ((path.is_symlink() and path.resolve() == installed.resolve() and installed.is_dir())
                       or (not path.is_symlink() and path.is_dir()
                           and file_manifest(path) == source_manifest))
            different |= not current
            skill["compatibility"].append({
                "harness": harness, "path": str(path),
                "resolved_path": str(path.resolve()) if path.exists() else None,
                "kind": "symlink" if path.is_symlink() else "copy" if path.is_dir() else "file" if path.exists() else "missing",
                "status": "current" if current else "different" if path.exists() or path.is_symlink() else "missing",
            })
        skills.append(skill)
    if json_output:
        print(json.dumps({"schema_version": 1, "scope": "user" if user_scope else "project",
                          "source_repository": str(root), "canonical_directory": str(canonical),
                          "current": not different, "skills": skills}, ensure_ascii=False))
    else:
        for skill in skills:
            print(f"{skill['name']}: {skill['status']} (installed={skill['installed']['version'] or '-'}, "
                  f"source={skill['source']['version'] or '-'})")
            for location in ("source", "installed"):
                for diagnostic in skill[location]["diagnostics"]:
                    print(f"  {location}: {diagnostic['message']} at {diagnostic['path']}")
            for link in skill["compatibility"]:
                if link["status"] != "current":
                    print(f"  {link['harness']}: missing or different at {link['path']}")
        print(f"Read-only {'user' if user_scope else 'project'} check: {canonical}")
    return int(different)


def report_skill_conflicts(conflicts: list[str]) -> int:
    print("Conflicts detected; no files were changed:", file=sys.stderr)
    for conflict in conflicts:
        print(f"- {conflict}", file=sys.stderr)
    print("Resolve the conflict manually instead of overwriting existing Skills.", file=sys.stderr)
    return 2


def copy_skills(install_sources: list[Path], destination_root: Path) -> None:
    for source in install_sources:
        destination = destination_root / source.name
        upgrading = destination.exists()
        destination_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{source.name}-install-", dir=destination_root))
        backup = staging / "previous"
        completed = False
        try:
            shutil.copytree(source, staging / "new", ignore=DISTRIBUTION_IGNORE)
            if upgrading:
                destination.replace(backup)
            (staging / "new").replace(destination)
            completed = True
        except OSError as error:
            if not upgrading:
                raise BootstrapError(f"Install failed; no Skill installed at {destination}: {error}") from error
            if backup.exists():
                try:
                    backup.replace(destination)
                except OSError as restore_error:
                    raise BootstrapError(f"Upgrade failed; previous copy retained at {backup}: {restore_error}") from error
            raise BootstrapError(f"Upgrade failed; previous copy restored at {destination}: {error}") from error
        finally:
            if completed or not backup.exists():
                shutil.rmtree(staging)


def validate_directory_path(destination_root: Path) -> None:
    """Check every existing ancestor before creating directories or copying files."""
    for path in (destination_root, *destination_root.parents):
        if (path.is_symlink() and not path.exists()) or (path.exists() and not path.is_dir()):
            raise BootstrapError(f"Expected a directory or no path at: {path}")


def compatibility_target(link: Path, canonical_skills: Path) -> str:
    try:
        return os.path.relpath((canonical_skills / link.name).resolve(), link.parent.resolve())
    except ValueError as error:
        raise BootstrapError(f"Cannot make a relative compatibility link for {link}: {error}") from error


def compatibility_link_plan(
    sources: list[Path], destination_root: Path, harness: str, canonical_skills: Path,
    baseline_skills: Path | None = None,
) -> tuple[list[Path], list[Path], list[str]]:
    """Plan links from a harness-specific discovery directory to .agents/skills."""
    validate_directory_path(destination_root)

    link_sources: list[Path] = []
    current_links: list[Path] = []
    conflicts: list[str] = []
    for source in sources:
        link = destination_root / source.name
        expected = canonical_skills / source.name
        compatibility_target(link, canonical_skills)  # Verify relative target before writes.
        if link.is_symlink():
            if link.resolve() == expected.resolve():
                current_links.append(link)
            else:
                conflicts.append(
                    f"{link} is not a managed {harness} link (points to {link.readlink()})"
                )
        elif link.exists():
            if link.is_dir() and file_manifest(source) == file_manifest(link):
                current_links.append(link)
            elif link.is_dir() and matches_upgrade_baseline(link, source.name, baseline_skills):
                link_sources.append(link)
            else:
                conflicts.append(
                    f"{link} exists but is not a managed {harness} link or an identical Skill copy"
                )
        else:
            link_sources.append(link)
    return link_sources, current_links, conflicts


def create_compatibility_links(links: list[Path], harness: str, canonical_skills: Path) -> None:
    for link in links:
        # Different Harness paths can resolve to one shared discovery directory.
        # A prior plan may therefore have created this exact managed link.
        if link.is_symlink() and link.resolve() == (canonical_skills / link.name).resolve():
            continue
        if link.is_dir() and not link.is_symlink():
            copy_skills([canonical_skills / link.name], link.parent)
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(
                compatibility_target(link, canonical_skills), target_is_directory=True
            )
        except OSError as error:
            raise BootstrapError(
                f"Failed to create {harness} link {link}: {error}. "
                "The .agents/skills copies are intact; create this link manually "
                "or rerun on a filesystem that supports symbolic links."
            ) from error


def install_project(target: Path, dry_run: bool, track_aitasks: bool, baseline_skills: Path | None = None) -> int:
    root = repository_root()
    target = target.expanduser().resolve()
    if not target.is_dir():
        raise BootstrapError(f"Target directory does not exist: {target}")
    if target == root:
        raise BootstrapError("Target must be a project that is separate from this Skill source.")

    sources = skill_directories(root)
    destination_root = target / ".agents" / "skills"
    install_sources, current_sources, conflicts = skill_install_plan(
        sources, destination_root, baseline_skills
    )

    compatibility_plans = []
    for harness, directory in COMPATIBILITY_SKILL_DIRS:
        link_root = target / directory / "skills"
        links, current, link_conflicts = compatibility_link_plan(
            sources, link_root, harness, destination_root, baseline_skills
        )
        compatibility_plans.append((harness, link_root, links, current))
        conflicts.extend(link_conflicts)

    agents_path = target / "AGENTS.md"
    existing_agents = read_regular_file(agents_path)
    rendered_agents = render_agents(existing_agents)
    gitignore_path, rendered_gitignore, ignore_skip_reason = render_gitignore(
        target, track_aitasks
    )
    if conflicts:
        return report_skill_conflicts(conflicts)

    planned: list[str] = []
    planned.extend(f"{'upgrade' if (destination_root / source.name).exists() else 'install'} {source.name}"
                   for source in install_sources)
    for _, _, links, _ in compatibility_plans:
        planned.extend(
            f"upgrade copy {link.relative_to(target)}" if link.is_dir() and not link.is_symlink() else
            f"link {link.relative_to(target)} -> {compatibility_target(link, destination_root)}"
            for link in links
        )
    if rendered_agents != existing_agents:
        planned.append(f"update {agents_path.relative_to(target)}")
    if rendered_gitignore is not None:
        planned.append(f"update {gitignore_path.relative_to(target)}")
    if ignore_skip_reason:
        planned.append(f"leave .gitignore unchanged ({ignore_skip_reason})")

    if dry_run:
        print("Dry run:")
        for item in planned or ["no changes required"]:
            print(f"- {item}")
        return 0

    upgrades = sum((destination_root / source.name).exists() for source in install_sources)
    copy_counts = {harness: sum(link.is_dir() and not link.is_symlink() for link in links)
                   for harness, _, links, _ in compatibility_plans}
    copy_skills(install_sources, destination_root)
    for harness, _, links, _ in compatibility_plans:
        create_compatibility_links(links, harness, destination_root)
    if rendered_agents != existing_agents:
        atomic_write(agents_path, rendered_agents)
    if rendered_gitignore is not None:
        atomic_write(gitignore_path, rendered_gitignore)

    print(
        f"Skills: {len(install_sources) - upgrades} installed, "
        + (f"{upgrades} upgraded, " if upgrades else "")
        + f"{len(current_sources)} already current."
    )
    for harness, link_root, links, current in compatibility_plans:
        print(
            f"{harness}: {len(links) - copy_counts[harness]} linked, "
            + (f"{copy_counts[harness]} copies updated, " if copy_counts[harness] else "")
            + f"{len(current)} already current in {link_root.relative_to(target)}."
        )
    if rendered_agents != existing_agents:
        print("AGENTS.md: managed collaboration section installed.")
    else:
        print("AGENTS.md: managed collaboration section already current.")
    if rendered_gitignore is not None:
        print(".gitignore: added .aitasks/ rule.")
    elif ignore_skip_reason:
        print(f".gitignore: unchanged ({ignore_skip_reason}).")
    else:
        print(".gitignore: no change required.")
    print("Paste global Custom Instructions manually with --print-custom-instructions.")
    return 0


def install_user(dry_run: bool, baseline_skills: Path | None = None) -> int:
    root = repository_root()
    sources = skill_directories(root)
    destination_root = Path.home() / ".agents" / "skills"
    install_sources, current_sources, conflicts = skill_install_plan(
        sources, destination_root, baseline_skills
    )

    compatibility_plans = []
    for harness, directory in COMPATIBILITY_SKILL_DIRS:
        link_root = Path.home() / directory / "skills"
        links, current, link_conflicts = compatibility_link_plan(
            sources, link_root, harness, destination_root, baseline_skills
        )
        compatibility_plans.append((harness, link_root, links, current))
        conflicts.extend(link_conflicts)
    if conflicts:
        return report_skill_conflicts(conflicts)

    if dry_run:
        print("Dry run:")
        for source in install_sources:
            print(f"- {'upgrade' if (destination_root / source.name).exists() else 'install'} {source.name}")
        for _, _, links, _ in compatibility_plans:
            for link in links:
                print(f"- upgrade copy {link}" if link.is_dir() and not link.is_symlink() else
                      f"- link {link} -> {compatibility_target(link, destination_root)}")
        if not install_sources and not any(plan[2] for plan in compatibility_plans):
            print("- no changes required")
        print(f"- user Skill directory: {destination_root}")
        for harness, link_root, _, _ in compatibility_plans:
            print(f"- {harness} link directory: {link_root}")
        return 0

    upgrades = sum((destination_root / source.name).exists() for source in install_sources)
    copy_counts = {harness: sum(link.is_dir() and not link.is_symlink() for link in links)
                   for harness, _, links, _ in compatibility_plans}
    copy_skills(install_sources, destination_root)
    for harness, _, links, _ in compatibility_plans:
        create_compatibility_links(links, harness, destination_root)
    print(
        f"User Skills: {len(install_sources) - upgrades} installed, "
        + (f"{upgrades} upgraded, " if upgrades else "")
        + f"{len(current_sources)} already current."
    )
    for harness, _, links, current in compatibility_plans:
        print(
            f"{harness} Skills: {len(links) - copy_counts[harness]} linked, "
            + (f"{copy_counts[harness]} copies updated, " if copy_counts[harness] else "")
            + f"{len(current)} already current."
        )
    link_roots = ", ".join(str(plan[1]) for plan in compatibility_plans)
    print(f"Installed only in: {destination_root}; compatibility links in: {link_roots}")
    print("No AGENTS.md, .gitignore, or project files were changed.")
    print("Paste global Custom Instructions manually with --print-custom-instructions.")
    return 0


def main() -> int:
    arguments = parser().parse_args()
    if arguments.json and (not arguments.check or arguments.print_custom_instructions):
        parser().error("--json requires --check and cannot be combined with --print-custom-instructions")
    if arguments.print_custom_instructions:
        print(CUSTOM_INSTRUCTIONS.rstrip())
        if arguments.target is None and arguments.scope is None:
            return 0
        print()
    if arguments.target is None and arguments.scope is None:
        parser().error(
            "--target or --scope user is required unless using "
            "--print-custom-instructions alone"
        )
    if arguments.scope == "user" and arguments.track_aitasks:
        parser().error("--track-aitasks is available only with --target")
    try:
        if arguments.check:
            target = Path.home() if arguments.scope == "user" else arguments.target.expanduser().resolve()
            return check_installation(target, arguments.scope == "user", arguments.json)
        baseline_skills = None
        if arguments.upgrade_from is not None:
            baseline_skills = arguments.upgrade_from.expanduser().resolve() / "skills"
            if not baseline_skills.is_dir():
                raise BootstrapError("--upgrade-from must contain the previous release's skills directory.")
        if arguments.scope == "user":
            return install_user(arguments.dry_run, baseline_skills)
        return install_project(arguments.target, arguments.dry_run, arguments.track_aitasks, baseline_skills)
    except BootstrapError as error:
        if arguments.json:
            print(json.dumps({"schema_version": 1, "current": False, "error": str(error)}, ensure_ascii=False))
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
