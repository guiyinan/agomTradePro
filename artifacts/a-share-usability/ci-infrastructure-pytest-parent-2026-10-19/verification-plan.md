# Pytest temp parent candidate verification

The candidate adds one setup command to each independent GitHub Actions checkout in scope: nightly, critical-postgres, and the RC journey job. Each command creates only .tmp; pytest continues to create and own .tmp/pytest, preserving pytest.ini and the existing baseline.

Static checks completed against private candidate copies:

- PyYAML parsed both candidate workflow files.
- A standard-library text check confirmed each setup step precedes the first pytest or pytest-runner step.
- The candidate patch passed git apply --check.
- The candidate only adds the three mkdir -p .tmp steps.

When the candidate is applied for integration, run actionlint on .github/workflows/nightly-tests.yml and .github/workflows/rc-gate.yml. Then validate in fresh CI checkouts that the parent-creation step runs before pytest in all three jobs. Re-run the PostgreSQL critical reliability step and confirm both affected tmp_path cases execute. The RC journey should be verified when its dependency installation succeeds.

This private diagnostic did not run pytest, import project modules, access a database, alter the index, or modify tracked source.