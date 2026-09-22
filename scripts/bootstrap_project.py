#!/usr/bin/env python3
"""Install this repository's engineering-collaboration setup into one project."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


AGENTS_BEGIN = "<!-- ai-engineering-collaboration:begin -->"
AGENTS_END = "<!-- ai-engineering-collaboration:end -->"
COMPATIBILITY_LINK_TARGET = "../../.agents/skills"
COMPATIBILITY_SKILL_DIRS = (
    ("Gemini", ".gemini"),
    ("Claude Code", ".claude"),
    ("ZCode", ".zcode"),
)
MANAGED_AGENTS_SECTION = f"""{AGENTS_BEGIN}
# AI Engineering Collaboration

- Read and follow applicable `AGENTS.md`, `AGENTS.override.md`, and `CLAUDE.md`; closer project rules take precedence.
- Check only material assumptions and gaps; distinguish verified facts from inferences and unknowns. Source-check time-sensitive or high-stakes claims, and explain disagreements that would change the outcome.
- Inspect relevant implementation, constraints, and existing edits before changing code; make the smallest root-cause fix and preserve unrelated work. Validate changed behavior in proportion to risk, reuse fresh evidence, and state what remains unverified.
- For every project-code editing task, use `aitasks-maintenance` to create or reuse one todo and close it with the actual result. Record a lesson immediately when the user explicitly asks, or after an issue's second substantive occurrence; check cleanup thresholds after allowed writes. Read-only tasks do not write records.
- Only with a usable `.codegraph/` index, prefer CodeGraph MCP then CLI for unknown code structure or impact; check `codegraph status` when the CLI is available. Use direct search for known paths or simple text, fall back when graph results are insufficient, verify important conclusions against code/tests, and never run `codegraph init` automatically.
- Use `ai-engineering-collaboration` only when the task needs coordination across multiple specialist stages or the user explicitly requests it; handle a single clear workflow directly or with its matching specialist skill.
{AGENTS_END}
"""

CUSTOM_INSTRUCTIONS = """# Engineering defaults

- 使用中文回复；代码、命令、文件名、错误日志和 API 名称保持原文。
- 修改前读取并遵守适用的 `AGENTS.md`、`AGENTS.override.md`、`CLAUDE.md`；更具体路径规则优先。
- 只核对会改变结论或交付的关键前提与信息缺口；保持独立判断，区分已验证事实、推断和未验证项。时效性或高风险结论优先查证；实质分歧说明依据和风险。
- 先调查相关实现、约束及工作区已有改动；Bug 确定根因后做当前任务所需的最小修复，保留无关修改。
- 修改后按风险执行最小必要验证；可复用输入未变的近期结果，不为纯文档变更运行无关测试。未经验证不得宣称通过，无法验证时说明边界。
- 单一明确工程任务直接处理或使用对应专项 Skill；确需跨多个专项阶段统筹或用户明确指定时，使用 `ai-engineering-collaboration`。
- 编辑项目代码时，不论是否使用入口 Skill，都用 `aitasks-maintenance` 为本任务创建或复用一条 todo，完成后写入实际结果并更新状态；仅修改 `.aitasks` 不递归创建 todo。
- 用户明确要求记录经验时立即记录；否则同一问题第二次实质出现时自动沉淀。先检索并更新已有同类经验；未证实的原因标注未确认。
- 每次允许写入 todo 或经验后按 `aitasks-maintenance` 阈值检查并自动归档清理：先归档再移出活动文件，不自动删除归档。只读或不修改文件时，不写记录、计数、忽略规则或归档。
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
    manifest: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise BootstrapError(f"Symlinked skill content is unsupported: {path}")
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest[str(path.relative_to(directory))] = digest
    return manifest


def read_regular_file(path: Path) -> str:
    if not path.exists():
        return ""
    if path.is_symlink() or not path.is_file():
        raise BootstrapError(f"Expected a regular file or no path at: {path}")
    return path.read_text(encoding="utf-8")


def render_agents(existing: str) -> str:
    begin_count = existing.count(AGENTS_BEGIN)
    end_count = existing.count(AGENTS_END)
    if begin_count != end_count or begin_count > 1:
        raise BootstrapError("AGENTS.md has incomplete or duplicate managed markers.")
    if begin_count == 1:
        start = existing.index(AGENTS_BEGIN)
        end = existing.index(AGENTS_END, start) + len(AGENTS_END)
        return existing[:start] + MANAGED_AGENTS_SECTION.rstrip() + existing[end:]
    if not existing:
        return MANAGED_AGENTS_SECTION
    return existing.rstrip() + "\n\n" + MANAGED_AGENTS_SECTION


def has_aitasks_rule(content: str) -> bool:
    normalized = {line.strip() for line in content.splitlines()}
    return bool({".aitasks", ".aitasks/", "/.aitasks", "/.aitasks/"} & normalized)


def run_git(target: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(target), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def git_allows_ignore_update(target: Path) -> tuple[bool, str | None]:
    repository = run_git(target, "rev-parse", "--is-inside-work-tree")
    if repository.returncode != 0 or repository.stdout.strip() != "true":
        return True, None

    tracked = run_git(target, "ls-files", "--", ".aitasks")
    if tracked.stdout.strip():
        return False, ".aitasks is already tracked by Git"

    history = run_git(target, "log", "-p", "--", ".gitignore")
    if ".aitasks" in history.stdout:
        return False, ".gitignore history contains a removed .aitasks rule"
    return True, None


def render_gitignore(target: Path, track_aitasks: bool) -> tuple[Path, str | None, str | None]:
    path = target / ".gitignore"
    existing = read_regular_file(path)
    if track_aitasks or has_aitasks_rule(existing):
        return path, None, None

    allowed, reason = git_allows_ignore_update(target)
    if not allowed:
        return path, None, reason

    section = "# Keep temporary collaboration records out of version control.\n.aitasks/\n"
    return path, (existing.rstrip() + "\n\n" if existing else "") + section, None


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def skill_install_plan(
    sources: list[Path], destination_root: Path
) -> tuple[list[Path], list[Path], list[str]]:
    if destination_root.is_symlink() and not destination_root.exists():
        raise BootstrapError(f"Expected a directory or no path at: {destination_root}")
    if destination_root.exists() and not destination_root.is_dir():
        raise BootstrapError(f"Expected a directory or no path at: {destination_root}")

    install_sources: list[Path] = []
    current_sources: list[Path] = []
    conflicts: list[str] = []
    for source in sources:
        destination = destination_root / source.name
        if destination.is_symlink() and not destination.exists():
            conflicts.append(f"{destination} exists but is not a directory")
        elif not destination.exists():
            install_sources.append(source)
        elif not destination.is_dir():
            conflicts.append(f"{destination} exists but is not a directory")
        elif file_manifest(source) == file_manifest(destination):
            current_sources.append(source)
        else:
            conflicts.append(f"{destination} differs from the source Skill")
    return install_sources, current_sources, conflicts


def report_skill_conflicts(conflicts: list[str]) -> int:
    print("Conflicts detected; no files were changed:", file=sys.stderr)
    for conflict in conflicts:
        print(f"- {conflict}", file=sys.stderr)
    print("Resolve the conflict manually instead of overwriting existing Skills.", file=sys.stderr)
    return 2


def copy_skills(install_sources: list[Path], destination_root: Path) -> None:
    for source in install_sources:
        shutil.copytree(source, destination_root / source.name)


def compatibility_link_plan(
    sources: list[Path], destination_root: Path, harness: str
) -> tuple[list[Path], list[Path], list[str]]:
    """Plan links from a harness-specific discovery directory to .agents/skills."""
    if destination_root.is_symlink() and not destination_root.exists():
        raise BootstrapError(f"Expected a directory or no path at: {destination_root}")
    if destination_root.exists() and not destination_root.is_dir():
        raise BootstrapError(f"Expected a directory or no path at: {destination_root}")

    link_sources: list[Path] = []
    current_links: list[Path] = []
    conflicts: list[str] = []
    for source in sources:
        link = destination_root / source.name
        expected = destination_root / COMPATIBILITY_LINK_TARGET / source.name
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
            else:
                conflicts.append(
                    f"{link} exists but is not a managed {harness} link or an identical Skill copy"
                )
        else:
            link_sources.append(link)
    return link_sources, current_links, conflicts


def create_compatibility_links(links: list[Path], harness: str) -> None:
    for link in links:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(
                f"{COMPATIBILITY_LINK_TARGET}/{link.name}", target_is_directory=True
            )
        except OSError as error:
            raise BootstrapError(
                f"Failed to create {harness} link {link}: {error}. "
                "The .agents/skills copies are intact; create this link manually "
                "or rerun on a filesystem that supports symbolic links."
            ) from error


def install_project(target: Path, dry_run: bool, track_aitasks: bool) -> int:
    root = repository_root()
    target = target.expanduser().resolve()
    if not target.is_dir():
        raise BootstrapError(f"Target directory does not exist: {target}")
    if target == root:
        raise BootstrapError("Target must be a project that is separate from this Skill source.")

    sources = skill_directories(root)
    destination_root = target / ".agents" / "skills"
    install_sources, current_sources, conflicts = skill_install_plan(
        sources, destination_root
    )

    compatibility_plans = []
    for harness, directory in COMPATIBILITY_SKILL_DIRS:
        link_root = target / directory / "skills"
        links, current, link_conflicts = compatibility_link_plan(
            sources, link_root, harness
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
    planned.extend(f"install {source.name}" for source in install_sources)
    for _, _, links, _ in compatibility_plans:
        planned.extend(
            f"link {link.relative_to(target)} -> {COMPATIBILITY_LINK_TARGET}/{link.name}"
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

    copy_skills(install_sources, destination_root)
    for harness, _, links, _ in compatibility_plans:
        create_compatibility_links(links, harness)
    if rendered_agents != existing_agents:
        atomic_write(agents_path, rendered_agents)
    if rendered_gitignore is not None:
        atomic_write(gitignore_path, rendered_gitignore)

    print(
        f"Skills: {len(install_sources)} installed, {len(current_sources)} already current."
    )
    for harness, link_root, links, current in compatibility_plans:
        print(
            f"{harness}: {len(links)} linked, {len(current)} already current "
            f"in {link_root.relative_to(target)}."
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


def install_user(dry_run: bool) -> int:
    root = repository_root()
    sources = skill_directories(root)
    destination_root = Path.home() / ".agents" / "skills"
    install_sources, current_sources, conflicts = skill_install_plan(
        sources, destination_root
    )

    compatibility_plans = []
    for harness, directory in COMPATIBILITY_SKILL_DIRS:
        link_root = Path.home() / directory / "skills"
        links, current, link_conflicts = compatibility_link_plan(
            sources, link_root, harness
        )
        compatibility_plans.append((harness, link_root, links, current))
        conflicts.extend(link_conflicts)
    if conflicts:
        return report_skill_conflicts(conflicts)

    if dry_run:
        print("Dry run:")
        for source in install_sources:
            print(f"- install {source.name}")
        for _, _, links, _ in compatibility_plans:
            for link in links:
                print(f"- link {link} -> {COMPATIBILITY_LINK_TARGET}/{link.name}")
        if not install_sources and not any(plan[2] for plan in compatibility_plans):
            print("- no changes required")
        print(f"- user Skill directory: {destination_root}")
        for harness, link_root, _, _ in compatibility_plans:
            print(f"- {harness} link directory: {link_root}")
        return 0

    copy_skills(install_sources, destination_root)
    for harness, _, links, _ in compatibility_plans:
        create_compatibility_links(links, harness)
    print(
        f"User Skills: {len(install_sources)} installed, "
        f"{len(current_sources)} already current."
    )
    for harness, _, links, current in compatibility_plans:
        print(
            f"{harness} Skills: {len(links)} linked, "
            f"{len(current)} already current."
        )
    link_roots = ", ".join(str(plan[1]) for plan in compatibility_plans)
    print(f"Installed only in: {destination_root}; compatibility links in: {link_roots}")
    print("No AGENTS.md, .gitignore, or project files were changed.")
    print("Paste global Custom Instructions manually with --print-custom-instructions.")
    return 0


def main() -> int:
    arguments = parser().parse_args()
    if arguments.print_custom_instructions:
        print(CUSTOM_INSTRUCTIONS.rstrip())
        if arguments.target is None:
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
        if arguments.scope == "user":
            return install_user(arguments.dry_run)
        return install_project(arguments.target, arguments.dry_run, arguments.track_aitasks)
    except BootstrapError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
