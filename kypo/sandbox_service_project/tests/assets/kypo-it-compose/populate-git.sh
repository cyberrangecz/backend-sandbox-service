#!/usr/bin/env sh

# ---
echo "Create Temporary Directory"
TEMP=$(mktemp -d)
cd "${TEMP}" || exit

# ---
echo "Create Dirs in '/repos' volume"
docker exec kypo-it-git-ssh sh -c 'mkdir -p /repos/backend-python/ansible-networking-stage'
docker exec kypo-it-git-ssh sh -c 'mkdir -p /repos/prototypes-and-examples/sandbox-definitions'
docker exec kypo-it-git-ssh sh -c 'mkdir -p /repos/useful-ansible-roles'

# ---
echo "Clone and Copy Sandbox Definitions"
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/prototypes-and-examples/sandbox-definitions/small-sandbox.git
docker cp small-sandbox.git kypo-it-git-ssh:/repos/prototypes-and-examples/sandbox-definitions

# ---
echo "Clone and Copy Ansible Stage One"
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-ansible-stage-one.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-user-access.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-interface.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-common.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/useful-ansible-roles/kypo-disable-qxl.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/useful-ansible-roles/kypo-sandbox-logging-forward.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-man-logging-forward.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/useful-ansible-roles/kypo-sandbox-logging-bash.git

docker cp kypo-ansible-stage-one.git       kypo-it-git-ssh:/repos/backend-python/ansible-networking-stage
docker cp kypo-user-access.git             kypo-it-git-ssh:/repos/backend-python/ansible-networking-stage
docker cp kypo-interface.git               kypo-it-git-ssh:/repos/backend-python/ansible-networking-stage
docker cp kypo-common.git                  kypo-it-git-ssh:/repos/backend-python/ansible-networking-stage
docker cp kypo-disable-qxl.git             kypo-it-git-ssh:/repos/useful-ansible-roles/
docker cp kypo-sandbox-logging-forward.git kypo-it-git-ssh:/repos/useful-ansible-roles/
docker cp kypo-man-logging-forward.git     kypo-it-git-ssh:/repos/backend-python/ansible-networking-stage/
docker cp kypo-sandbox-logging-bash.git    kypo-it-git-ssh:/repos/useful-ansible-roles/

# ---
echo "Cleanup..."
rm -rf "${TEMP}"

# ---
echo "Done."
