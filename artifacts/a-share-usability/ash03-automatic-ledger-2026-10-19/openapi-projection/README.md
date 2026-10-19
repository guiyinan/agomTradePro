# Bounded OpenAPI projection

This private candidate carries only `/api/simulated-trading/auto-trading/run/` and its seven generated schemas from the supplied `full_generated` artifacts onto the supplied BASE artifacts (`0e54384678e6b0bbddc72e4fb1088455d1c34b52`). It preserves the BASE text outside those mapping entries, including unrelated paths, components, and top-level properties.

The selected schemas are `AutoTradingAccountOutcomeResponse`, `AutoTradingIssueResponse`, `AutoTradingRunRequestRequest`, `AutoTradingRunResponse`, `AutoTradingRunSummary`, `KindEnum`, and `Outcome537Enum`. The Python helper uses only the standard library and PyYAML to splice original source blocks, parse the three formats, and assert the requested boundaries. It confirmed that the three BASE files and three full-generated files are semantically consistent, the candidate formats are semantically identical, the selected endpoint and schemas equal full generation, all other BASE paths/components/top-level values remain equal to BASE, every reachable internal reference resolves, and no other BASE path/component references the selected schemas.

The three full-generator outputs had preexisting schema drift. This candidate deliberately retains that drift outside the selected endpoint closure and does not claim full OpenAPI synchronization. It does not modify shared files.

The bounded projection script ran against the captured inputs and its static assertions passed. No project imports, tests, QA, ORM/database, network, Git, or shared-source writes were used.