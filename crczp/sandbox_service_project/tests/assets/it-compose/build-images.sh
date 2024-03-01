#!/usr/bin/env bash

# Ansible Runner Image for Docker
docker build \
  -t crczp/docker-ansible-runner \
  git@github.com:cyberrangecz/backend-ansible-runner.git


