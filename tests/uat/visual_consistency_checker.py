"""
Visual Consistency Checker for UAT
Automated checks for visual design tokens and component consistency.
"""
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StyleIssue:
    """Represents a style consistency issue."""
    file_path: str
    line_number: int
    issue_type: str  # 'inline_style', 'hardcoded_color', 'custom_component'
    description: str
    severity: str  # 'P0', 'P1', 'P2'
    snippet: str


class VisualConsistencyChecker:
    """Check visual consistency across templates."""

    def __init__(self, base_dir: Path):
        """Initialize checker.

        Args:
            base_dir: Project base directory
        """
        self.base_dir = base_dir
        self.template_dir = base_dir / "apps"
        self.issues: list[StyleIssue] = []

        # Design tokens that should be used
        self.design_tokens = {
            'colors': [
                'var(--bs-primary)',
                'var(--bs-secondary)',
                'var(--bs-success)',
                'var(--bs-danger)',
                'var(--bs-warning)',
                'var(--bs-info)',
                'var(--bs-light)',
                'var(--bs-dark)',
            ],
            'spacings': [
                'var(--bs-spacer)',
            ],
            'fonts': [
                'var(--bs-body-font-family)',
                'var(--bs-font-sans-serif)',
            ],
        }

        # Hardcoded colors that should use tokens
        self.hardcoded_color_pattern = re.compile(
            r'(color|background|border):\s*(#[0-9a-fA-F]{3,6}|rgb|hsl)\('
        )

    def scan_templates(self) -> None:
        """Scan all template files for style issues."""
        template_files = self._find_template_files()

        for template_file in template_files:
            self._check_file(template_file)

    def _find_template_files(self) -> list[Path]:
        """Find all HTML template files."""
        templates = []
        for pattern in ['**/*.html', '**/*.htm']:
            templates.extend(self.template_dir.rglob(pattern))
        return templates

    def _check_file(self, file_path: Path) -> None:
        """Check a single file for style issues."""
        try:
            content = file_path.read_text(encoding='utf-8')
            lines = content.split('\n')

            for line_num, line in enumerate(lines, 1):
                # Check for inline styles
                self._check_inline_styles(file_path, line_num, line)

                # Check for hardcoded colors
                self._check_hardcoded_colors(file_path, line_num, line)

                # Check for style tags
                self._check_style_tags(file_path, line_num, line)

        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}")

    def _check_inline_styles(self, file_path: Path, line_num: int, line: str) -> None:
        """Check for inline style attributes."""
        if ' style=' in line:
            # Check if style uses design tokens
            if not any(token in line for token in self.design_tokens['colors']):
                self.issues.append(StyleIssue(
                    file_path=str(file_path.relative_to(self.base_dir)),
                    line_number=line_num,
                    issue_type='inline_style',
                    description='Inline style found without design tokens',
                    severity='P1',
                    snippet=line.strip()
                ))

    def _check_hardcoded_colors(self, file_path: Path, line_num: int, line: str) -> None:
        """Check for hardcoded color values."""
        matches = self.hardcoded_color_pattern.findall(line)
        if matches:
            self.issues.append(StyleIssue(
                file_path=str(file_path.relative_to(self.base_dir)),
                line_number=line_num,
                issue_type='hardcoded_color',
                description=f'Hardcoded color found: {matches[0]}',
                severity='P2',
                snippet=line.strip()
            ))

    def _check_style_tags(self, file_path: Path, line_num: int, line: str) -> None:
        """Check for style tags (should be minimal)."""
        if '<style' in line and not line.strip().startswith('{#'):
            self.issues.append(StyleIssue(
                file_path=str(file_path.relative_to(self.base_dir)),
                line_number=line_num,
                issue_type='style_tag',
                description='Style tag found (consider external CSS)',
                severity='P2',
                snippet=line.strip()
            ))

    def get_issues_by_severity(self, severity: str) -> list[StyleIssue]:
        """Get issues filtered by severity."""
        return [i for i in self.issues if i.severity == severity]

    def get_issues_by_type(self, issue_type: str) -> list[StyleIssue]:
        """Get issues filtered by type."""
        return [i for i in self.issues if i.issue_type == issue_type]

    def generate_report(self) -> dict:
        """Generate a summary report."""
        total = len(self.issues)
        by_severity = {
            'P0': len([i for i in self.issues if i.severity == 'P0']),
            'P1': len([i for i in self.issues if i.severity == 'P1']),
            'P2': len([i for i in self.issues if i.severity == 'P2']),
        }
        by_type = Counter([i.issue_type for i in self.issues])

        return {
            'total_issues': total,
            'by_severity': dict(by_severity),
            'by_type': dict(by_type),
            'files_checked': len(self._find_template_files()),
        }


def check_visual_consistency(base_dir: Path) -> VisualConsistencyChecker:
    """Run visual consistency checks.

    Args:
        base_dir: Project base directory

    Returns:
        VisualConsistencyChecker with results
    """
    checker = VisualConsistencyChecker(base_dir)
    checker.scan_templates()
    return checker


if __name__ == '__main__':
    import sys

    # Run from project root or provided path
    if len(sys.argv) > 1:
        base_dir = Path(sys.argv[1])
    else:
        base_dir = Path(__file__).parent.parent.parent

    print(f"Scanning templates in: {base_dir}")
    print()

    checker = check_visual_consistency(base_dir)
    report = checker.generate_report()

    print("=== Visual Consistency Report ===")
    print(f"Files checked: {report['files_checked']}")
    print(f"Total issues: {report['total_issues']}")
    print()

    print("By Severity:")
    for severity, count in report['by_severity'].items():
        print(f"  {severity}: {count}")
    print()

    print("By Type:")
    for issue_type, count in report['by_type'].items():
        print(f"  {issue_type}: {count}")
    print()

    if report['total_issues'] > 0:
        print("\n=== Top 10 Issues ===")
        for issue in checker.issues[:10]:
            print(f"\n{issue.severity} - {issue.file_path}:{issue.line_number}")
            print(f"  {issue.description}")
            print(f"  {issue.snippet[:80]}...")
