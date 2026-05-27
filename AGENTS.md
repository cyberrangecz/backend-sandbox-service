# AGENTS.md

This document defines how automated agents (CI systems, bots, or AI coding assistants)
should interact with this repository.

## Project Overview

For a high-level description, usage examples, and API overview, see the main project documentation:

[README.md](https://github.com/cyberrangecz/backend-sandbox-service/blob/master/README.md)

**Repository:** `backend-sandbox-service`

This repository hosts a Django REST Framework service that simplifies manipulation of the
OpenStack cloud platform for the CyberRangeCZ Platform. It manages sandbox definitions,
pools of sandboxes, sandbox instances, and Ansible playbook execution on sandbox machines.
The REST API is documented via OpenAPI (drf-spectacular).

Core tooling:

* **Package Manager:** `uv`
* **Project configuration:** `pyproject.toml`
* **Task orchestration:** `tox`
* **Code quality:** `pre-commit`, `ruff`, `mypy`, `pylint`
* **Security:** `bandit`, dependency `audit`
* **Testing:** `pytest` (with Django test settings)

---

## Branching Model

* `master` is the protected, stable branch
* All changes must be made via **feature branches**
* Feature branches are merged into `master` only after all checks pass

Agents **must not** push directly to `master`.

---

## Project Structure — Key Directories

```
/
├── .github/                          # CI workflows & automated checks
│   └── workflows/
├── bin/                              # Service startup scripts
├── crczp/
│   ├── sandbox_common_lib/           # Shared utilities: config, exceptions, permissions
│   ├── sandbox_uag/                  # User & group auth: OIDC/JWT, permissions
│   ├── sandbox_ansible_app/          # Django app: Ansible playbook execution on sandboxes
│   │   ├── lib/                      # Core logic
│   │   ├── migrations/               # Django DB migrations
│   │   └── tests/                    # App-level tests
│   ├── sandbox_cloud_app/            # Django app: cloud provider abstraction
│   │   ├── lib/                      # Core logic
│   │   └── migrations/               # Django DB migrations
│   ├── sandbox_definition_app/       # Django app: sandbox definition management
│   │   ├── lib/                      # Core logic
│   │   ├── migrations/               # Django DB migrations
│   │   └── tests/                    # App-level tests
│   ├── sandbox_instance_app/         # Django app: sandbox instance & pool management
│   │   ├── lib/                      # Core logic
│   │   ├── management/               # Django management commands
│   │   ├── migrations/               # Django DB migrations
│   │   └── tests/                    # App-level tests
│   └── sandbox_service_project/      # Django project: settings, root URLs, WSGI
│       └── tests/                    # Test-specific settings
├── tofu/                             # OpenTofu/Terraform infrastructure definitions
├── docs/                             # Project documentation
├── AGENTS.md                         # This file
├── config.yml-template               # Service runtime configuration template
├── Dockerfile
├── manage.py                         # Django management entrypoint
├── pyproject.toml                    # Python project config
├── tox.ini                           # Test & quality orchestrator
└── uv.lock                           # Locked dependency versions
```

* **`crczp/sandbox_common_lib`** contains shared utilities used across all apps
* **`crczp/sandbox_service_project`** contains Django project settings
* **`.github/workflows/`** defines CI behaviour

Agents must respect this structure and must not introduce alternative layouts without
explicit approval.

---

## Environment Setup

Agents must use **`uv`** for dependency management.

```bash
uv sync
```

Development dependencies are defined in the `dev` dependency group (type stubs for mypy).
Install them with:

```bash
uv sync --group dev
```

Python version must match the version specified in `pyproject.toml`.

---

## Virtual Environments and Isolation

Agents must not run tools using arbitrary or external virtual environments.

- All tooling must be executed via `tox` or `uv run`
- Agents must not invoke tools using:
  - system Python
  - manually created virtual environments
  - virtual environments not managed by `uv` or `tox`

Agents should rely on `uv` and `tox` for environment isolation and must not
invoke tools using globally installed Python packages.

---

## How Agents Must Run Code Quality Checks

Code quality checks must be executed in a reproducible, CI-equivalent environment.

### Authoritative Method

The **only authoritative way** to run the full quality suite is:

```bash
tox
```

This runs all tox environments: `pre-commit`, `pylint`, `bandit`, `audit`, `pytest`.

---

## Code Quality Requirements

All changes **must pass the full quality suite** before merging.

### Pre-commit

Run all hooks locally:

```bash
pre-commit run --all-files
```

Configured hooks include:

* `ruff` (linting)
* `ruff format` (formatting)
* `mypy` (static type checking)

Agents must ensure all hooks pass.

---

## Linting and Static Analysis

### Ruff

* Ruff is the authoritative linter and formatter
* Rules are defined in `pyproject.toml`
* Manual formatting outside Ruff is not allowed

### MyPy

* All new and modified code must be fully type-annotated
* Avoid `Any` unless absolutely necessary

### Pylint

* Code must satisfy configured Pylint rules (minimum score: `9.5`)
* Warnings should not be disabled without justification
* Pylint runs against both `crczp` and `tests` directories

---

## Security Checks

### Bandit

Bandit is used to detect common security issues. Configuration is in `pyproject.toml`.

Agents must not introduce:

* Unsafe `eval` or `exec` usage
* Hard-coded secrets
* Insecure cryptographic patterns

### Dependency Audit

Agents must not introduce dependencies with known vulnerabilities.

---

## Testing

### Pytest

All changes must include appropriate test coverage.

```bash
tox -e pytest
```

Guidelines:

* New features require new tests
* Bug fixes must include regression tests
* Tests must be deterministic and isolated
* Integration tests must be marked with `@pytest.mark.integration`; they are excluded from
  the default `tox` run (`-m "not integration"`)
* Django settings for tests: `crczp.sandbox_service_project.tests.settings`
* The tox `pytest` environment also runs `python manage.py check` after the test suite

Test paths:

* `crczp/sandbox_ansible_app/tests`
* `crczp/sandbox_common_lib/tests`
* `crczp/sandbox_definition_app/tests`
* `crczp/sandbox_instance_app/tests`
* `crczp/sandbox_service_project/tests`

---

## Tox

`tox` is the authoritative CI entry point.

Agents should prefer:

```bash
tox
```

All tox environments must pass before merging.

---

## Coding Standards

* Follow PEP 8 and project conventions
* Prefer clarity over cleverness
* Keep functions small and focused
* Document public APIs with docstrings
* Avoid breaking changes unless explicitly requested

---

## What Agents Must Not Do

* Do not commit directly to `master`
* Do not bypass or disable quality checks
* Do not introduce new dependencies without justification
* Do not modify tooling configuration unless requested
* Do not commit generated or compiled artifacts

---

## Recommended Agent Workflow

1. Create a feature branch
2. Make minimal, focused changes
3. Run:

   ```bash
   tox
   ```

   This runs the full suite, including:

   * `pre-commit` (ruff lint, ruff format, mypy)
   * `pylint`
   * `bandit`
   * dependency audit
   * `pytest` + `manage.py check`

4. Ensure all checks pass

---

## Handling Uncertainty

If requirements are unclear:

* Prefer conservative changes
* Ask for clarification
* Do not assume undocumented behaviour

---

This repository prioritises **quality, security, and maintainability**.
Agents are expected to follow these rules strictly.
