# Content

1. [KYPO Sandbox Service](#kypo-sandbox-service)
    1. [Authors](#authors)
    2. [Installation](#installation)
    3. [Project Modules](#project-modules)
    3. [Wiki](#wiki)
    
# KYPO Sandbox Service

This project simplifies manipulation of OpenStack cloud platform for KYPO purposes.

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

## Installation
The requirements and installation process is described in detail in Installation
Documentation found in this
[wiki](https://gitlab.ics.muni.cz/kypo-crp/backend-python/kypo-sandbox-service/-/wikis/Installation-Documentation).


## Wiki
The wiki with documentation to this project: [KYPO Sandbox Service wiki](https://gitlab.ics.muni.cz/kypo-crp/backend-python/kypo-sandbox-service/-/wikis/home)

## Deployment
When a change to develop branch occurs, the repository is built into an image with the name *develop* that is then uploaded to the artifact repository. If a new tag is made from master, the image with the name of the tag is built and uploaded. The service comes with an admin account that can be used to access the admin panel. The default credentials are admin - PmOn78IbUv12. This can be changed for every build by setting DJNG_ADMIN_USER and DJNG_ADMIN_PASSWORD gitlab variables before building the image.
