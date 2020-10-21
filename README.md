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

