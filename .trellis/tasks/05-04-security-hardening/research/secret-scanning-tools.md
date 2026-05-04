# Research: Pre-Commit Secret Scanning Tools

- **Query**: Compare gitleaks, detect-secrets, git-secrets for Python + Vue.js project
- **Scope**: Mixed (internal project state + external tool evaluation)
- **Date**: 2026-05-04

## Findings

### Project Current State

| Item | Status |
|------|--------|
| `pre-commit` command | NOT installed on system |
| `.pre-commit-config.yaml` | Does NOT exist |
| `backend/requirements.txt` | Does NOT list `pre-commit` or any scanning tool |
| Any scanning tool (gitleaks/detect-secrets/git-secrets) | None installed |

### Sensitive Files in Repo

| File Path | Risk Level | Notes |
|---|---|---|
| `backend/.env` | **CRITICAL but SAFE** | Contains real DB credential, but NOT tracked by git (confirmed via `git ls-files`). `.env` is in `.gitignore`. |
| `.env.example` | Low | Template only, uses placeholder values |
| `backend/config.py` | Low | Reads from env vars, no hardcoded secrets |

### Tool Comparison

#### 1. gitleaks

| Criterion | Assessment |
|---|---|
| **Installation complexity** | Low. Downloads a single pre-built Go binary; no Go runtime needed. Also available via `brew`, `docker`, or as a pre-commit hook (downloads binary automatically). |
| **Pre-commit framework compatibility** | Excellent. Official hook at `gitleaks/gitleaks`. Works by adding to `.pre-commit-config.yaml` with `repo: https://github.com/gitleaks/gitleaks`. |
| **False positive handling** | Good. Supports inline `gitleaks:allow` comments and a `.gitleaksignore` file to suppress specific findings by fingerprint. Also supports allowlist via config. |
| **Custom regex rules** | Excellent. Supports custom rules via `.gitleaks.toml` with `[[rules]]` entries. Can define custom regex, entropy thresholds, and allowlists per rule. Easy to add `postgresql://` pattern. |
| **Language agnostic** | Yes. Scans all text files by default. Works on `.py`, `.js`, `.vue`, `.env.example`, `.md`, `.jsonl`. |
| **Maintenance status** | Very active. Latest release v8.30.1 (2026-03-21). 26,554 GitHub stars. Regular commits through 2026. |

**Pre-commit hook config example:**
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - id: gitleaks
```

**Custom rule for PostgreSQL connection strings:**
```toml
[[rules]]
id = "postgresql-connection-string"
description = "PostgreSQL connection string with credentials"
regex = '''postgresql(?:\+[a-z]+)?://[^\s]+:[^\s]+@[^\s]+'''
tags = ["database", "credential"]
```

#### 2. detect-secrets (Yelp)

| Criterion | Assessment |
|---|---|
| **Installation complexity** | Low. Pure Python package. `pip install detect-secrets`. No extra runtime. However, requires a Python environment to run. |
| **Pre-commit framework compatibility** | Good. Official hook at `Yelp/detect-secrets`. Works via `.pre-commit-config.yaml`. |
| **False positive handling** | Excellent. Has a baseline file mechanism (`detect-secrets scan > .secrets.baseline`) that records known secrets and allows auditing. This is its strongest feature -- you can audit each finding as "ok" or "secret". |
| **Custom regex rules** | Limited. Supports custom plugins but the mechanism is more complex than gitleaks. Requires writing a Python class inheriting from `detect_secrets.plugins.base.Plugin`. |
| **Language agnostic** | Yes. Scans all text files. Works on `.py`, `.js`, `.vue`, `.env.example`, `.md`, `.jsonl`. |
| **Maintenance status** | Moderate. Latest release v1.5.0 (2024-05-06, ~2 years old). 4,497 stars. Last substantive commit was 2025-01-06 (Python 3.13 support). Active but slower cadence than gitleaks. |

**Pre-commit hook config example:**
```yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

**Custom plugin for PostgreSQL:**
Requires writing a full Python plugin class -- significantly more effort than gitleaks' TOML config.

#### 3. git-secrets (AWS)

| Criterion | Assessment |
|---|---|
| **Installation complexity** | Moderate. Shell script. Requires `git-secrets` binary on PATH. No package manager distribution (manual install from source). |
| **Pre-commit framework compatibility** | Poor. Does NOT have a native pre-commit hook. Works via `git secrets --install` which creates git hooks directly. Would need a `local` hook wrapper in `.pre-commit-config.yaml`. |
| **False positive handling** | Minimal. Only supports allowlist patterns via `--add-patterns` and allowed strings via `--add-allowed`. No baseline file mechanism. |
| **Custom regex rules** | Moderate. Supports custom patterns via `git secrets --add-pattern`. Can add `postgresql://` pattern. But pattern syntax is basic (grep-style). |
| **Language agnostic** | Yes. Scans all file content via grep-style matching. Works on any text file. |
| **Maintenance status** | Stale. Latest tag 1.3.0 (last release long ago). 13,291 stars but code is largely unmaintained. Last real code commit was 2025-09-17 (Amazon Bedrock patterns by external contributor). Core repo has had no meaningful updates since 2023. AWS focus means patterns are AWS-specific (access keys, secret keys). |

**No standard pre-commit hook exists. Workaround:**
```yaml
repos:
  - repo: local
    hooks:
      - id: git-secrets
        name: git-secrets
        entry: git-secrets --commit_msg_hook
        language: system
        stages: [commit-msg]
```

### Summary Comparison Matrix

| Criterion | gitleaks | detect-secrets | git-secrets |
|---|---|---|---|
| Installation | Binary (no runtime) | pip (Python needed) | Shell (manual) |
| Pre-commit compat | Native hook | Native hook | No (local workaround) |
| False positive handling | `.gitleaksignore` + allow | **Baseline file (best)** | Minimal allowlist |
| Custom regex | TOML rules (easy) | Python plugin (hard) | grep patterns (okay) |
| Language agnostic | Yes | Yes | Yes |
| Latest release | v8.30.1 (2026-03) | v1.5.0 (2024-05) | v1.3.0 (stale) |
| Stars | 26,554 | 4,497 | 13,291 |
| Activity | Very active | Moderate | Stale |
| PostgreSQL regex | Easy TOML rule | Hard (Python plugin) | Possible (grep) |

### Critical Finding: backend/.env Status

The file `backend/.env` contains real credentials:
- PostgreSQL connection string with password: `postgresql+psycopg://quiz:TKy6ynBYD2FJDXxC@localhost:5433/quiz`
- Weak JWT and Flask secret keys

However, this file is **NOT tracked by git** (confirmed via `git ls-files`). The `.gitignore` file includes `.env` at the root level, which covers `backend/.env`. Secret scanning will not flag this file unless it gets accidentally staged.

## Recommendation

**gitleaks** is the best choice for this project. Reasons:

1. **No runtime dependency** -- downloads a pre-built binary via pre-commit, does not require Go or Python to be available. The project has no `pre-commit` framework yet, so a zero-runtime-dependency tool simplifies the initial setup.

2. **Most active maintenance** -- v8.30.1 released 2026-03-21, regular updates, 26K+ stars. detect-secrets is 2 years behind on releases; git-secrets is effectively unmaintained.

3. **Easy custom rules** -- Adding a PostgreSQL connection string rule is a 6-line TOML snippet, vs. writing a full Python class for detect-secrets. This project uses `postgresql://` connection strings which are not caught by default rules.

4. **Native pre-commit hook** -- Works directly with `.pre-commit-config.yaml`. git-secrets requires a `local` workaround.

5. **Balanced false positive handling** -- `.gitleaksignore` and inline `gitleaks:allow` comments are sufficient. detect-secrets' baseline file is superior for large existing repos, but for this small project the simpler approach is adequate.

**If baseline/audit workflow is highly valued**, a secondary option is `detect-secrets` as a CI scan (not pre-commit), since its baseline mechanism is genuinely better for managing false positives at scale. But for pre-commit integration, gitleaks wins.

**git-secrets should be excluded** -- stale maintenance, no native pre-commit support, and AWS-focused patterns that do not match this project's needs.

## Caveats / Not Found

- git-secrets latest release date could not be fetched from GitHub Releases API (it uses tags only), but the tag v1.3.0 appears to be very old based on commit history.
- detect-secrets PyPI latest is 1.5.0, matching GitHub -- confirms the 2024-05 release is current.
- The `.gitignore` contains `.env` at root which covers `backend/.env` -- confirmed via `git ls-files` that the file is not tracked. However, the real credential in that file exists on disk and should be rotated if the repo is ever shared or the file is accidentally committed.
