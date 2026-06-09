# Content

- [Content](#content)
- [Sandbox Service](#sandbox-service)
  - [Project Modules](#project-modules)
  - [Tests](#tests)
  - [Wiki](#wiki)
  - [Deployment](#deployment)

# Sandbox Service

This project simplifies manipulation of OpenStack cloud platform for CyberRangeCZ Platform purposes.

It provides REST calls for manipulation with:

* Sandbox definitions
* Pools of sandboxes
* Sandboxes themselves
* Applying Ansible playbooks on sandbox machines

## Project Modules
This Django project contains three apps and one common library.
- __Sandbox Common Lib__ with common functionality
- __Sandbox Defintion App__ which handles the sandbox defintions
- __Sandbox Ansible App__ which runs Asible on the sandbox
- __Sandbox Instance App__ which manges the sanfboxes

## Tests

| File | Type | Covers |
|------|------|--------|
| `sandbox_common_lib/tests/test_utils.py` | Unit | Utility functions |
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
| `sandbox_instance_app/tests/test_stage_handlers.py` | Unit | Stage handler logic |
| `sandbox_instance_app/tests/test_sshconfig.py` | Unit | SSH config generation |
| `sandbox_instance_app/tests/test_flavor_mapping.py` | Unit | Flavor mapping |
| `sandbox_ansible_app/tests/test_ansible.py` | Unit | Ansible execution |
| `sandbox_ansible_app/tests/test_inventory.py` | Unit | Ansible inventory building |
| `sandbox_ansible_app/tests/test_stages.py` | Unit | Ansible stage handling |
| `sandbox_service_project/tests/test_integration.py` | **Integration** | Full service integration |

 Integration tests are marked with `@pytest.mark.integration` and are included in the default `tox` run.
 To run only the integration tests explicitly, use `pytest -m integration`.
 
## Wiki
The wiki with documentation to this project: [Sandbox Service wiki](https://github.com/cyberrangecz/backend-sandbox-service/wiki)

## Deployment
When a change to develop branch occurs, the repository is built into an image with the name *develop* that is then uploaded to the artifact repository. If a new tag is made from master, the image with the name of the tag is built and uploaded. The service comes with an admin account that can be used to access the admin panel. The default credentials are admin - PmOn78IbUv12. This can be changed for every build by setting DJNG_ADMIN_USER and DJNG_ADMIN_PASSWORD gitlab variables before building the image.
