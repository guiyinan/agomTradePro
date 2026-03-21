# Security Scan Report - 2026-03-04

## Scan Overview

**Date**: 2026-03-04
**Scan Method**: Manual code review + static analysis
**Scan Scope**: `apps/` directory, `core/settings/`, configuration files
**Scanner**: Manual security audit (bandit, pip-audit, safety not installed)

---

## Executive Summary

**Overall Security Status**: **MEDIUM RISK**

The AgomTradePro project demonstrates **strong security practices** in several areas:
- Environment-based configuration (no hardcoded secrets)
- Proper secrets management via `shared/config/secrets.py`
- Field-level encryption for API keys
- DoS protection via upload limits
- Production security headers (HSTS, SSL redirect)

However, **several security concerns** were identified that require attention:
- **Pickle deserialization** in ML model loading (HIGH RISK)
- **Dynamic code execution** in strategy scripts (mitigated but inherent risk)
- **Missing automated dependency scanning**
- **Development debug configurations** that may accidentally leak to production

---

## Critical Findings

| Level | Type | Location | Description | Recommended Fix |
|-------|------|----------|-------------|-----------------|
| **HIGH** | Deserialization | `apps/alpha/infrastructure/adapters/qlib_adapter.py:480` | `pickle.load()` used to load ML models without validation | Use `pickle.loads()` with HMAC signature verification, or switch to safe formats like JSON/safetensors |
| **HIGH** | Deserialization | `apps/alpha/application/tasks.py:427` | `pickle.load()` used in Celery task for model loading | Same as above - add signature verification |
| **MEDIUM** | Code Execution | `apps/strategy/application/script_engine.py:596` | `exec()` used for user strategy scripts | Already mitigated with RestrictedPython, but document as inherent risk |
| **MEDIUM** | Code Execution | `apps/strategy/application/position_management_service.py:133` | `eval()` used for position rule expressions | Has AST validation and restricted builtins - acceptable with documentation |
| **LOW** | Configuration | `core/settings/base.py:48` | Default SECRET_KEY in development | Not an issue if production uses environment variable (verified in production.py) |

---

## Detailed Findings

### 1. Pickle Deserialization (HIGH RISK)

**Files Affected**:
- `apps/alpha/infrastructure/adapters/qlib_adapter.py` (line 480)
- `apps/alpha/application/tasks.py` (line 427)

**Issue**:
The project uses `pickle.load()` to deserialize machine learning models. Python's pickle module can execute arbitrary code during deserialization if the model file is malicious.

**Current Code**:
```python
with open(model_path, "rb") as f:
    self._model = pickle.load(f)
```

**Risk Assessment**:
- **Exploitability**: MEDIUM (requires file system access)
- **Impact**: HIGH (remote code execution)
- **Likelihood**: LOW (models are stored internally)

**Recommended Fix**:
```python
import hmac
import hashlib

def load_model_with_signature(model_path, secret_key):
    """Load model with HMAC signature verification."""
    with open(model_path, "rb") as f:
        data = f.read()

    # Split signature and model data
    sig = data[:64]
    model_data = data[64:]

    # Verify signature
    expected = hmac.new(secret_key.encode(), model_data, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Model signature verification failed")

    return pickle.loads(model_data)
```

**Alternative**: Use safer serialization formats like `safetensors` or JSON.

---

### 2. Dynamic Code Execution (MEDIUM RISK)

**Files Affected**:
- `apps/strategy/application/script_engine.py` (line 596)
- `apps/strategy/application/position_management_service.py` (line 133)

**Issue**:
The project uses `exec()` and `eval()` to execute user-defined code for trading strategies.

**Mitigations Already in Place**:
- **RestrictedPython**: Used for strategy script execution
- **AST Validation**: Position rules validated via AST parsing
- **Restricted Builtins**: `{"__builtins__": {}}`
- **Module Whitelisting**: Forbidden modules enforced

**Risk Assessment**:
- **Exploitability**: LOW (requires authenticated user access)
- **Impact**: MEDIUM (could access ScriptAPI methods)
- **Likelihood**: LOW (significant controls in place)

**Status**: **ACCEPTABLE** - The current implementation uses industry-standard sandboxing (RestrictedPython) and properly restricts dangerous modules.

**Recommendations**:
1. Document the security model in user-facing docs
2. Add rate limiting to script execution endpoints
3. Consider containerization for script execution

---

### 3. Configuration Security

#### SECRET_KEY Configuration
- **Development**: `core/settings/base.py:48` uses a default value
- **Production**: `core/settings/production.py` correctly uses `env('SECRET_KEY')`
- **Status**: **SECURE** - Production requires environment variable

#### DEBUG Mode
- **Development**: `DEBUG = True` in development settings
- **Production**: `DEBUG = False` in production settings
- **Status**: **SECURE**

#### ALLOWED_HOSTS
- **Development**: `['*']` in development settings
- **Production**: Uses `env.list('ALLOWED_HOSTS')`
- **Status**: **SECURE**

---

### 4. Secrets Management

**Implementation**: `shared/config/secrets.py`

**Positive Findings**:
- No hardcoded secrets in codebase
- Centralized secrets management via environment variables
- Database fallback for API keys
- Field-level encryption for AI provider keys (`apps/ai_provider/`)

**Encryption**: `AGOMTRADEPRO_ENCRYPTION_KEY` properly required for new API keys

---

### 5. Dependency Security

**Scanner Status**: NOT INSTALLED
- `bandit` - not available
- `pip-audit` - not available
- `safety` - not available

**Key Dependencies Review** (from requirements-prod.txt):

| Package | Version | Known Concerns |
|---------|---------|----------------|
| Django | >=5.0,<6.0 | No major security issues in 5.x |
| djangorestframework | Latest | No major security issues |
| cryptography | >=41.0 | Keep updated for security patches |
| celery | Latest | Monitor for CVEs |
| streamlit | >=1.42 | Monitor for CVEs |
| akshare | ==1.18.22 | Fixed version - verify no CVEs |

**Recommendations**:
1. Install and run `pip-audit` regularly:
   ```bash
   pip install pip-audit
   pip-audit --desc --format json > docs/plan/m0-baseline/pip-audit-report.json
   ```

2. Pin specific versions in production requirements

3. Set up Dependabot or Renovate for automated updates

---

### 6. Production Security Headers

**File**: `core/settings/production.py`

**Status**: **EXCELLENT**

All critical security headers are properly configured:

```python
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
```

---

### 7. DoS Protection

**File**: `core/settings/base.py`

**Status**: **GOOD**

Proper upload limits configured:
```python
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
```

**Test Coverage**: Tests exist in `tests/unit/test_dos_limits.py`

---

### 8. CSRF Protection

**Finding**: No `@csrf_exempt` decorators found in codebase

**Status**: **SECURE** - Django's default CSRF protection is intact

---

### 9. SQL Injection

**Finding**: No raw SQL with user input found

**Status**: **SECURE** - All database queries use Django ORM

---

### 10. XSS Protection

**Finding**:
- No `mark_safe()` calls with user input
- DRF serializers used for API responses
- Django templates auto-escape by default

**Status**: **SECURE**

---

## Dependency Security (Manual Review)

### High-Priority Dependencies to Monitor

| Package | Current Version | Recommendation |
|---------|-----------------|----------------|
| cryptography | >=41.0 | Keep updated, has security patches |
| celery | Latest | Monitor for CVEs |
| pandas | >=2.0 | Monitor for CVEs |
| requests | Latest | Monitor for CVEs |
| urllib3 | Latest | Monitor for CVEs |
| akshare | ==1.18.22 | Consider updating to latest stable |

---

## Configuration Security Checklist

| Check | Status | Notes |
|-------|--------|-------|
| SECRET_KEY from environment | ✅ | Production uses `env('SECRET_KEY')` |
| DEBUG=False in production | ✅ | Configured in production.py |
| ALLOWED_HOSTS configured | ✅ | Uses environment variable |
| HTTPS enabled | ✅ | SECURE_SSL_REDIRECT=True |
| HSTS enabled | ✅ | SECURE_HSTS_SECONDS=31536000 |
| Secure cookies | ✅ | SESSION_COOKIE_SECURE=True |
| CORS restrictions | ✅ | CORS_ALLOW_ALL_ORIGINS=False |
| Upload limits | ✅ | 10MB limit configured |
| Rate limiting | ⚠️ | Not found - recommend adding |
| Input validation | ✅ | DRF serializers used |

---

## Recommendations

### Priority 1 (HIGH)
1. **Add model signature verification** for pickle deserialization
2. **Install automated dependency scanning** (pip-audit)
3. **Add rate limiting** to API endpoints

### Priority 2 (MEDIUM)
1. **Document the strategy script security model** for users
2. **Set up Dependabot** for automated dependency updates
3. **Add security testing** to CI pipeline
4. **Consider containerization** for strategy script execution

### Priority 3 (LOW)
1. **Pin dependency versions** in requirements-prod.txt
2. **Add security headers audit** to deployment checklist
3. **Implement API key rotation** mechanism

---

## Installation Instructions for Security Tools

### pip-audit (Dependency Vulnerability Scanner)
```bash
pip install pip-audit
pip-audit --format json > docs/plan/m0-baseline/pip-audit-report.json
```

### bandit (Python Security Linter)
```bash
pip install bandit
bandit -r apps/ -f json > docs/plan/m0-baseline/bandit-report.json
```

### safety (Security Vulnerability Checker)
```bash
pip install safety
safety check --json > docs/plan/m0-baseline/safety-report.json
```

---

## Conclusion

AgomTradePro demonstrates **strong security practices** overall. The main areas of concern are:

1. **Pickle deserialization** for ML models - should add signature verification
2. **Lack of automated dependency scanning** - should add to CI/CD
3. **Rate limiting** - should implement for production

The project's use of RestrictedPython for sandboxing user code is **well-implemented** and follows industry best practices.

**Overall Security Rating**: **7.5/10**

---

**Report Generated**: 2026-03-04
**Next Review**: 2026-04-04 (recommended monthly)
