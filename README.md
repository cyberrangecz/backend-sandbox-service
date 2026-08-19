# Content

- [Content](#content)
- [Sandbox Service](#sandbox-service)
  - [Project Modules](#project-modules)
  - [Tests](#tests)
  - [Wiki](#wiki)
  - [Deployment](#deployment)

# Sandbox Service

This project simplifies manipulation of cloud platforms (OpenStack and AWS) for CyberRangeCZ Platform purposes. It is a Django REST Framework service whose API is documented via OpenAPI (drf-spectacular).

It provides REST calls for manipulation with:

* Sandbox definitions
* Pools of sandboxes
* Sandboxes themselves
* Applying Ansible playbooks on sandbox machines
* OpenStack project quota, image, and limit information

Provisioning is backed by Terraform (`crczp-terraform-client`), with a client selected per deployment via `crczp-openstack-lib` or `crczp-aws-lib` depending on which cloud is configured.

## Project Modules
This Django project is organized as one project-wide settings module, four self-contained apps, and two shared libraries.
- __Sandbox Common Lib__ with shared configuration, exceptions, permissions, and cloud/utility helpers (including OpenStack/AWS client selection)
- __Sandbox UAG__ handling OIDC/JWT authentication and role-based permissions
- __Sandbox Definition App__ which handles the sandbox definitions (including Git-based definition providers)
- __Sandbox Ansible App__ which runs Ansible on the sandbox
- __Sandbox Instance App__ which manages the sandboxes, pools, and their lifecycle requests
- __Sandbox Cloud App__ which exposes OpenStack project quota/image/limit information
- __Sandbox Service Project__ with the Django project settings, root URL configuration, and WSGI entrypoint

## Tests

| File | Type | Covers |
|------|------|--------|
| `sandbox_common_lib/tests/test_utils.py` | Unit | Utility functions |
| `sandbox_common_lib/tests/test_crczp_config.py` | Unit | CRCZP configuration parsing |
| `sandbox_common_lib/tests/test_crczp_config_validation.py` | Unit | Configuration attribute validation |
| `sandbox_common_lib/tests/test_netbird_client.py` | Unit | NetBird management API client |
| `sandbox_definition_app/tests/test_definitions.py` | Unit | Create/load/get definitions, topology validation |
| `sandbox_definition_app/tests/test_definition_providers.py` | Unit | GitLab/GitHub provider URL parsing, ref fetching |
| `sandbox_definition_app/tests/test_definition_providers.py` (`TestGitIntegration`) | **Integration** | Live Git operations |
| `sandbox_instance_app/tests/test_topology.py` | Unit | Topology serialization, Docker container handling |
| `sandbox_instance_app/tests/test_nodes.py` | Unit | Node actions, node retrieval |
| `sandbox_instance_app/tests/test_projects.py` | Unit | Project management |
| `sandbox_instance_app/tests/test_pools.py` | Unit | Sandbox pool operations |
| `sandbox_instance_app/tests/test_sandboxes.py` | Unit | Sandbox lifecycle |
| `sandbox_instance_app/tests/test_requests.py` | Unit | Request handling |
| `sandbox_instance_app/tests/test_request_handlers.py` | Unit | Request handler logic |
| `sandbox_instance_app/tests/test_request_handlers.py` (`TestAllocationRequestHandler`, `TestCleanupRequestHandler`) | **Integration** | Allocation/cleanup request handling |
| `sandbox_instance_app/tests/test_stage_handlers.py` | Unit | Stage handler logic |
| `sandbox_instance_app/tests/test_sshconfig.py` | Unit | SSH config generation |
| `sandbox_instance_app/tests/test_flavor_mapping.py` | Unit | Flavor mapping |
| `sandbox_instance_app/tests/test_netbird.py` | Unit | NetBird provisioning, teardown, sandbox VPN API view |
| `sandbox_ansible_app/tests/test_ansible.py` | Unit | Ansible execution |
| `sandbox_ansible_app/tests/test_inventory.py` | Unit | Ansible inventory building |
| `sandbox_ansible_app/tests/test_stages.py` | Unit | Ansible stage handling |
| `sandbox_service_project/tests/test_integration.py` | **Integration** | Full service integration |

 Integration tests are marked with `@pytest.mark.integration` and are included in the default `tox` run.
 To run only the integration tests explicitly, use `pytest -m integration`.
 
## Wiki
The wiki with documentation to this project: [Sandbox Service wiki](https://github.com/cyberrangecz/backend-sandbox-service/wiki)

## Deployment
CI/CD runs via GitHub Actions (`.github/workflows/github-actions.yml`):

* Every push to a non-`master` branch and every pull request against `master` runs the full quality suite through `tox` (pre-commit, pylint, bandit, dependency audit, pytest).
* Pushes also build a Docker image and publish it to the GitHub Container Registry as `ghcr.io/cyberrangecz/backend-sandbox-service/sandbox-service:<version>-dev`.
* Manually dispatching the workflow on `master` (with tag creation confirmed) builds and publishes the release image tagged with the version from `pyproject.toml`, generates the OpenAPI schema (drf-spectacular) to GitHub Pages, and pushes the corresponding git tag.

At container startup (`bin/run-sandbox-service.sh`), the service applies database migrations, creates the cache table, creates/refreshes a Django admin account from the `DJANGO_ADMIN_USER`, `DJANGO_ADMIN_EMAIL`, and `DJANGO_ADMIN_PASSWORD` environment variables, registers roles, and starts `gunicorn`.
