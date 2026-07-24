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

  Core tooling: `uv` (packages), `pyproject.toml` (config), `tox` (task orchestration),
  `pre-commit` / `ruff` / `mypy` / `pylint` (quality), `bandit` + dependency audit (security),
  `pytest` with Django test settings (testing).

---

## Branching Model

* `master` is the protected, stable branch
* All changes must be made via **feature branches**
* Feature branches are merged into `master` only after all checks pass

Agents **must not** push directly to `master`.

---

## Project Structure

Shared code lives in `crczp/sandbox_common_lib` (config, exceptions, permissions) and
`crczp/sandbox_uag` (auth: OIDC/JWT, permissions).

Each of `sandbox_ansible_app`, `sandbox_cloud_app`, `sandbox_definition_app`, and
`sandbox_instance_app` is a self-contained Django app with its own `lib/`, `migrations/`,
and `tests/`. `sandbox_service_project` holds project-wide settings, root URLs, and WSGI.

`tofu/` contains OpenTofu/Terraform infrastructure definitions; these are not part of the
Django app and are not covered by `tox`/`pytest`.

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

## Running Checks

Two different bars apply, and agents should not conflate them:

* **While iterating on a change:** run the specific checks relevant to what you touched —
  e.g. `ruff check`, `ruff format`, `mypy`, and the specific test file(s) for the code you
  changed (`tox -e pytest -- path/to/test_file.py` or `pytest` directly inside `uv run`).
* **Before considering a change complete / ready to merge:** run the full suite via `tox`,
  which runs `pre-commit` (ruff lint, ruff format, mypy), `pylint`, `bandit`, dependency
  audit, `pytest`, and `python manage.py check`.

```bash
tox
```

This is the single authoritative, CI-equivalent way to validate a change before merge.
All tox environments must pass.

Notes:

* Ruff is the authoritative linter/formatter — rules are in `pyproject.toml`; no manual
  formatting outside Ruff.
* New/modified code must be type-annotated (`mypy`); avoid `Any` unless necessary.
* Minimum Pylint score: `9.5`, run against both `crczp` and `tests`. Don't disable
  warnings without justification.
* Bandit: no `eval`/`exec` on untrusted input, no hard-coded secrets, no insecure crypto
  patterns. No new dependencies with known vulnerabilities.

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
3. Run the relevant fast checks while iterating (see "Running Checks")
4. Before finishing, run `tox` and ensure all environments pass

---

## Handling Uncertainty

If requirements are unclear:

* Prefer conservative changes
* Ask for clarification
* Do not assume undocumented behaviour

---

This repository prioritises **quality, security, and maintainability**.
Agents are expected to follow these rules strictly.
