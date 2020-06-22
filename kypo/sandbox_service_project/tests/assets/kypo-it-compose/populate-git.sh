#!/usr/bin/env sh

# ---
echo "Create Temporary Directory"
TEMP=$(mktemp -d)
cd "${TEMP}" || exit

# ---
echo "Create Dirs in '/repos' volume"
docker exec kypo-it-git-ssh sh -c 'mkdir /repos/ansible-roles'
#docker exec kypo-it-git-ssh sh -c 'mkdir /repos/sandbox-definitions'

# ---
echo "Clone and Copy Sandbox Definitions"
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/prototypes-and-examples/sandbox-definitions/small-sandbox.git
docker cp small-sandbox.git kypo-it-git-ssh:/repos/

# ---
echo "Clone and Copy Ansible Stage One"
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-ansible-stage-one.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-user-access.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-interface.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/backend-python/ansible-networking-stage/kypo-common.git
git clone -q --bare git@gitlab.ics.muni.cz:kypo-crp/useful-ansible-roles/kypo-disable-qxl.git

docker cp kypo-ansible-stage-one.git kypo-it-git-ssh:/repos/ansible-roles/
docker cp kypo-user-access.git kypo-it-git-ssh:/repos/ansible-roles/
docker cp kypo-interface.git kypo-it-git-ssh:/repos/ansible-roles/
docker cp kypo-common.git kypo-it-git-ssh:/repos/ansible-roles/
docker cp kypo-disable-qxl.git kypo-it-git-ssh:/repos/ansible-roles/

# ---
echo "Cleanup..."
rm -rf "${TEMP}"

# ---
echo "Done."
