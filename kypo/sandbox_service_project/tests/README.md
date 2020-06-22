# Integration tests

Set `os_*` credentials in `kypo/sandbox_service_project/tests/config.yml`
Optionally, you can also set the `PUBLIC_NETWORK` environment variable to choose
the public network used. Otherwise, the default will be used.

From the cloned repository, run the following:

```bash
cd kypo/sandbox_service_project/tests/assets/kypo-it-compose/
./build-images.sh
chmod 0600 git-keys/git-ssh-key
docker-compose up -d
./populate-git.sh
```

Run the tests (in the project root):

```bash
pipenv sync --dev
tox -- -m integration
```