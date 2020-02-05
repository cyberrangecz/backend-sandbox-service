# Content

1. [KYPO Django OpenStack](#kypo-django-openstack)
    1. [Authors](#authors)
    2. [Installation](#installation)
    3. [Project Modules](#project-modules)

# KYPO Django OpenStack

This project simplifies manipulation of OpenStack cloud platform for KYPO purposes.

It provides REST calls for manipulation with:

* Sandbox definitions
* Pools of sandboxes
* Sandboxes themselves
* Applying Ansible playbooks on sandbox machines

## Authors

Name          | Email
------------- | ------------
Daniel Tovarňák | tovarnak@ics.muni.cz
Kamil Andoniadis | andoniadis@ics.muni.cz
Miloslav Staněk | milosst@mail.muni.cz
Tatiana Zbončáková | 445312@mail.muni.cz

## Installation

The requirements and installation process is described in detail in Installation
Documentation found in this
[wiki](https://gitlab.ics.muni.cz/kypo-crp/backend-python/kypo-django-openstack/wikis/home).

## Project Modules
This project consists of two main parts.

### kypo2_django_openstack_project
Django project for `kypo2_django_openstack` as Django application.
It also contains project settings.
 
### kypo2_django_openstack
Django application. It contains several modules.
- `REST API` layer
- Services taking care of business logic
    - `Definition service` for management of Sandbox defintions
    - `Pool service` for organization of sandboxes into logical groups called Pools 
    - `Sandbox service` for management of Sandbox instances
    - `Node service` for management of nodes in sandbox
    - `Ansible service` for management of Ansible
    - `Sandbox Creator` for asynchronous sandbox creation
    - `Sandbox Destructor` for asynchronous sandbox cleanup

## Run tests
- ### Unit
```bash
pipevn run tox
```
- ### Integration
You need to have OpenStack credentials in you environment variables:
```bash
OS_AUTH_URL
OS_APPLICATION_CREDENTIAL_ID
OS_APPLICATION_CREDENTIAL_SECRET
```
Then run the following command.
```bash
pipevn run tox -- -m integration
```
__NOTE__: Kill all running workers before running integration tests.
