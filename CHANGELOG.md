# Changelog

All notable changes to AgomSAAF will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- (TBD)

### Changed
- (TBD)

### Deprecated
- (TBD)

### Removed
- (TBD)

### Fixed
- (TBD)

### Security
- (TBD)

---

## [3.5.0] - 2026-03-04

### Added
- **API Route Migration**: Unified API route format `/api/{module}/{resource}/`
- **Migration Documentation**: Complete route migration guide and quick reference
- **Deprecation Headers**: Old routes now return deprecation warning headers
- **Migration Guide**: See [docs/migration/route-migration-guide.md](docs/migration/route-migration-guide.md)

### Changed
- **API Routes**: All API endpoints now use unified routing format
  - Old: `/{module}/api/{resource}/` or `/api/{module}/api/{resource}/`
  - New: `/api/{module}/{resource}/`
- **SDK Compatibility**: SDK v1.2.0+ automatically uses new routes

### Deprecated
- **Legacy API Routes**: Old route patterns deprecated, will be removed 2026-06-01
  - `/{module}/api/{resource}/` format
  - `/api/{module}/api/{resource}/` format

### Migration Timeline
- **2026-03-04**: New routes released, old routes marked deprecated
- **2026-04-01**: Old routes enter read-only mode (GET only)
- **2026-06-01**: Old routes will be completely removed

---

## [3.4.2] - 2026-03-02

### Added
- **Valuation & Pricing Engine**: Complete valuation snapshot and investment recommendation system
- **Execution Approval Workflow**: Pre-approval process for investment decisions
- **Decision Workflow Module**: Precheck, beta gate, quota, and cooldown checks
- **Database Migration**: 0003 migration for new valuation and approval models
- **API Endpoints**: 7 new endpoints for valuation and approval operations

### Changed
- **Decision Rhythm Module**: Extended with execute_request and cancel_request operations
- **SDK**: Added `DecisionWorkflowModule` with precheck and gate check methods

### Fixed
- Valuation calculation edge cases for price-sensitive assets
- Approval state machine race conditions

---

## [3.4.1] - 2026-03-01

### Added
- **Decision Workflow Integration**: Main workflow with precheck and gate validation
- **Policy + RSS + Hotspot Workbench**: Unified macro environment entry system
- **Dual Gate Mechanism**: Policy Gate (P0-P3) + Heat/Sentiment Gate (L0-L3)
- **API Endpoints**: 9 workbench endpoints, 4 scheduled tasks

### Changed
- **Navigation**: Unified top navigation structure
- **Dashboard**: Investment account entrance renamed to "我的投资账户"

### Fixed
- 6 acceptance issues (P0-1 ~ P2-1)
- Data migration with historical backfill

---

## [3.4.0] - 2026-02-26

### Added
- **Module**: `task_monitor` - Scheduled task monitoring
- **Testing**: Full regression test suite with CI gates
- **Documentation**: Complete module documentation structure

### Changed
- **Architecture**: Removed `apps/shared/`, moved to `shared/infrastructure/htmx/`
- **Dependencies**: Fixed 4违规 dependencies from `shared/` to `apps/`
- **Exceptions**: Unified exception handling via `core/exceptions.py`

### Fixed
- Sentiment module route configuration
- AI provider application layer
- 31 new unit tests added

---

## [3.3.0] - 2026-02-20

### Added
- **Routing Convention**: Unified API route naming standard
- **Health Checks**: Liveness and readiness endpoints
- **Deprecation Middleware**: Automatic deprecation headers for old routes

### Changed
- **Dashboard**: Consolidated legacy routes, removed technical identifiers from user-facing URLs

### Fixed
- 22 API route naming compliance issues
- Dashboard route conflicts

---

## [3.2.0] - 2026-02-18

### Added
- **Factor Module**: Factor calculation, IC/ICIR evaluation
- **Rotation Module**: Sector rotation based on Regime
- **Hedge Module**: Futures hedge calculation and management

### Changed
- **Alpha Module**: Deep integration with Qlib (Phase 1-5 complete)

---

## [3.1.0] - 2026-02-01

### Added
- **Audit Module**: Post-trade audit with Brinson attribution
- **Dashboard**: Streamlit integration for visualization

### Changed
- **Performance**: Optimized database queries for large datasets

---

## [3.0.0] - 2026-01-15

### Added
- **Beta Gate Module**: Market condition filtering
- **Decision Rhythm**: Decision frequency constraints
- **Alpha Trigger**: Discrete alpha signal triggering

### Changed
- **Architecture**: Complete four-layer architecture enforcement
- **Breaking**: Module imports restructured

---

## [2.0.0] - 2025-12-01

### Added
- **Qlib Integration**: AI-based stock selection
- **Alpha Module**: Abstract layer for multiple alpha sources
- **Cache Provider**: Performance optimization for alpha queries

### Changed
- **Breaking**: Alpha API completely redesigned

---

## [1.0.0] - 2025-10-01

### Added
- Initial release with core modules:
  - Macro (data collection)
  - Regime (determination engine)
  - Policy (event management)
  - Signal (investment signals)
  - Filter (HP/Kalman filtering)
  - Account (portfolio management)
  - Backtest (backtesting engine)
  - Simulated Trading (automated trading)
  - Realtime (price monitoring)
  - Strategy (strategy system)

---

## Version History Summary

| Version | Date | Key Changes |
|---------|------|-------------|
| 3.5.0 | 2026-03-04 | API route migration, unified `/api/{module}/` format |
| 3.4.2 | 2026-03-02 | Valuation & Pricing Engine, Execution Approval |
| 3.4.1 | 2026-03-01 | Decision Workflow, Policy Workbench |
| 3.4.0 | 2026-02-26 | Task Monitor, architecture fixes |
| 3.3.0 | 2026-02-20 | Routing convention, health checks |
| 3.2.0 | 2026-02-18 | Factor, Rotation, Hedge modules |
| 3.1.0 | 2026-02-01 | Audit module, Streamlit dashboard |
| 3.0.0 | 2026-01-15 | Beta Gate, Decision Rhythm, Alpha Trigger |
| 2.0.0 | 2025-12-01 | Qlib integration, Alpha module |
| 1.0.0 | 2025-10-01 | Initial release |

---

**Maintained by**: AgomSAAF Team
**Last Updated**: 2026-03-04
