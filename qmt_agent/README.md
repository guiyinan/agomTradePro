# Agom QMT Agent Windows package

This directory contains the standalone Windows execution Agent and its repeatable package build scripts.

- Build the ZIP from the repository with `powershell -File scripts/build_qmt_agent_package.ps1`.
- Install from the ZIP with `Install.ps1`.
- Store the VPS Agent token with `Set-AgentToken.ps1`; it is encrypted with Windows DPAPI.
- Run installation checks with `Test-Connection.ps1`; add `-ReadProbe` for the no-order/no-cancel QMT probe.
- Keep `dry_run` enabled until the broker permission and simulation acceptance gates pass.

The package does not contain QMT, a broker password, an Agent token, or an XtQuant wheel. The installer downloads the recorded official wheel and verifies its SHA-256, or accepts a broker-provided wheel together with an explicit SHA-256.

Chinese installation documentation: `docs/operations/qmt-agent-local-install-package.md`.
