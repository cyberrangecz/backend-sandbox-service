# Content

1. [Sandbox Service](#sandbox-service)
    1. [Authors](#authors)
    2. [Installation](#installation)
    3. [Project Modules](#project-modules)
    3. [Wiki](#wiki)

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

## Wiki
The wiki with documentation to this project: [Sandbox Service wiki](https://github.com/cyberrangecz/backend-sandbox-service/wiki)

## Deployment
When a change to develop branch occurs, the repository is built into an image with the name *develop* that is then uploaded to the artifact repository. If a new tag is made from master, the image with the name of the tag is built and uploaded. The service comes with an admin account that can be used to access the admin panel. The default credentials are admin - PmOn78IbUv12. This can be changed for every build by setting DJNG_ADMIN_USER and DJNG_ADMIN_PASSWORD gitlab variables before building the image.
