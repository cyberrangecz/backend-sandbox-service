#!/usr/bin/env bash

# Ansible Runner Image for Docker
docker build \
  -t kypo-crp/docker-ansible-runner \
  git@gitlab.ics.muni.cz:kypo-crp/backend-python/kypo-ansible-runner.git#master

# Git REST Proxy
docker build \
  -t kypo-crp/restfulgit \
  git@gitlab.ics.muni.cz:kypo-crp/dependency-forks/csirtmu-docker-restfulgit.git#master

# SSH Git Repository Support
docker build \
  -t kypo-crp/ssh-git \
  git@gitlab.ics.muni.cz:kypo-crp/dependency-forks/csirtmu-docker-ssh-git.git#master

