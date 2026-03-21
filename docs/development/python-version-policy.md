# Python Version Policy

> **Last Updated**: 2026-03-04
> **Status**: Active
> **Owner**: Technical Team

## Overview

AgomTradePro supports a dual-version Python strategy to ensure compatibility while maintaining forward-looking support.

## Supported Versions

| Version | Status | CI Testing | Runtime | EOL Date |
|---------|--------|------------|---------|----------|
| 3.11    | Primary | Yes | **Yes** | 2027-10-24 |
| 3.13    | Secondary | Yes | No | 2029-10-15 |

## Policy Details

### CI Testing Strategy

All CI workflows test against both Python 3.11 and 3.13 using a matrix strategy:

```yaml
strategy:
  matrix:
    python-version: ['3.11', '3.13']
  fail-fast: false
```

This ensures:
- Code is compatible with both versions
- Deprecation warnings are caught early
- Smooth migration path when 3.11 reaches EOL

### Runtime Deployment Version

**Production and development environments use Python 3.11.**

Rationale:
- Stable and mature release
- Long-term support until 2027
- All dependencies verified compatible
- Primary target for our deployment tooling

### Docker Images

All Dockerfiles use `python:3.11-slim` as the base image:

```dockerfile
FROM python:3.11-slim
```

### Development Tools

The following tools are configured for Python 3.11:

- **black**: `target-version = ['py311']`
- **ruff**: `target-version = "py311"`
- **mypy**: `python_version = "3.11"`

## Dependency Constraints

### Minimum Version

`pyproject.toml` specifies:

```toml
requires-python = ">=3.11"
```

This ensures:
- Python 3.11+ is required for installation
- Python 3.13 is explicitly supported
- Future Python 3.14+ will be accepted when available

### Upper Bound

No explicit upper bound is set. Instead:
- CI testing validates compatibility
- Version bumps are controlled through release process

## Version Upgrade Process

When upgrading the primary Python version (e.g., 3.11 -> 3.13):

1. **Announcement** (3 months before)
   - Notify all developers
   - Document breaking changes
   - Plan migration timeline

2. **Preparation** (1-2 months)
   - Update CI to include new version
   - Fix any compatibility issues
   - Update dependencies if needed

3. **Testing** (1 month)
   - Extended testing period on new version
   - Performance benchmarks
   - Security audit

4. **Migration** (scheduled)
   - Update runtime version in Dockerfiles
   - Update development tools config
   - Deploy to staging first

5. **Verification** (1 week)
   - Monitor production metrics
   - Rollback plan ready

6. **Documentation** (within 1 week)
   - Update this policy
   - Update CLAUDE.md
   - Update README

## Consistency Checking

Run the version consistency check script:

```bash
python scripts/check_python_version_consistency.py
```

This validates:
- `pyproject.toml` version constraints
- CI workflow Python versions
- Dockerfile Python versions
- `.python-version` file (if present)

Add this check to CI to prevent drift:

```yaml
- name: Check Python version consistency
  run: python scripts/check_python_version_consistency.py
```

## Troubleshooting

### Import Errors on Python 3.13

If you encounter import errors only on Python 3.13:

1. Check if the package supports 3.13
2. Look for type annotation issues (removed in 3.13)
3. Check for removed stdlib modules

### Type Checking Failures

If `mypy` fails on Python 3.13:

1. Ensure you're using mypy 1.8+
2. Check for removed typing aliases
3. Update stub packages

## References

- [Python 3.11 Release Notes](https://docs.python.org/3.11/whatsnew/3.11.html)
- [Python 3.13 Release Notes](https://docs.python.org/3.13/whatsnew/3.13.html)
- [PEP 604 - Allow writing union types as X | Y](https://peps.python.org/pep-0604/)
- [Python Developer's Guide](https://devguide.python.org/versions/)
