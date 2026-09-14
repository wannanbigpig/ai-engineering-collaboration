from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


class SkillQualityContractTest(unittest.TestCase):
    def test_main_entry_requires_scoped_structural_review(self) -> None:
        content = read_text("skills/ai-engineering-collaboration/SKILL.md")

        self.assertIn("结构质量", content)
        self.assertIn("本次变更范围", content)

    def test_impact_analysis_checks_reuse_before_adding_code(self) -> None:
        content = read_text("skills/change-impact-analysis/SKILL.md")

        self.assertIn("复用检查", content)
        self.assertIn("有意保持重复", content)

    def test_project_conventions_are_discovered_and_preserved(self) -> None:
        entry = read_text("skills/ai-engineering-collaboration/SKILL.md")
        impact = read_text("skills/change-impact-analysis/SKILL.md")
        execution = read_text("skills/plan-execution/SKILL.md")
        review = read_text("skills/code-review/SKILL.md")
        verification = read_text("skills/verification-gate/SKILL.md")

        self.assertIn("风格基线", entry)
        self.assertIn("同类实现", entry)
        self.assertIn("后端", impact)
        self.assertIn("前端", impact)
        self.assertIn("显式要求", execution)
        self.assertIn("第二套", execution)
        self.assertIn("项目一致性", review)
        self.assertIn("设计令牌", review)
        self.assertIn("视觉", verification)
        self.assertIn("编译", verification)

    def test_execution_has_a_post_change_structure_pass(self) -> None:
        content = read_text("skills/plan-execution/SKILL.md")

        self.assertIn("结构复核", content)
        self.assertIn("无关重构", content)

    def test_structure_rules_reject_length_driven_function_splitting(self) -> None:
        execution = read_text("skills/plan-execution/SKILL.md")
        verification = read_text("skills/verification-gate/SKILL.md")
        review = read_text("skills/code-review/SKILL.md")

        self.assertIn("内聚", execution)
        self.assertIn("调用跳转", execution)
        self.assertIn("过度拆分", verification)
        self.assertIn("调用层级", verification)
        self.assertIn("单次使用", verification)
        self.assertIn("导航成本", review)
        self.assertIn("函数长度", review)

    def test_test_strategy_covers_failure_paths(self) -> None:
        content = read_text("skills/test-driven-change/SKILL.md")

        self.assertIn("失败路径", content)
        self.assertIn("错误语义", content)

    def test_verification_requires_tool_backed_metrics(self) -> None:
        content = read_text("skills/verification-gate/SKILL.md")

        self.assertIn("结构质量", content)
        self.assertIn("量化结论", content)
        self.assertIn("工具、版本、范围和输出", content)

    def test_review_distinguishes_expected_and_unexpected_errors(self) -> None:
        content = read_text("skills/code-review/SKILL.md")

        self.assertIn("预期错误", content)
        self.assertIn("非预期异常", content)
        self.assertIn("脱敏", content)

    def test_behavior_evaluation_covers_all_maintainability_scenarios(self) -> None:
        content = read_text("evals/maintainability-scenarios.md")

        for scenario in (
            "复用已有实现",
            "影响分析优先",
            "错误处理语义",
            "量化指标证据",
            "避免过度拆分",
            "沿用后端主流风格",
            "无设计稿时沿用现有 UI",
            "保护无关修改",
        ):
            with self.subTest(scenario=scenario):
                self.assertIn(f"## {scenario}", content)
        self.assertIn("不得判定通过", content)
        self.assertIn("Harness", content)


if __name__ == "__main__":
    unittest.main()
