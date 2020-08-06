# Integration tests

## Prepare

1. Set `os_*` credentials in [kypo/sandbox_service_project/tests/config.yml](kypo/sandbox_service_project/tests/config.yml)

2. Prepare necessary Docker images and local Git repository.
From the cloned repository, run the following:

    ```bash
    cd kypo/sandbox_service_project/tests/assets/kypo-it-compose/
    ./build-images.sh
    chmod 0600 git-keys/git-ssh-key
    docker-compose up -d
    ./populate-git.sh
    ```

3. Prepare virtual environment.

    ```bash
    pipenv sync --dev
    ```

4. **Optionally**, you can also set the `PUBLIC_NETWORK` environment variable
to choose the external public network that will allow the integration tests
to allocate Floating IP address from the public IP address range.
Otherwise, the default will be used. You can find default in
[kypo/sandbox_service_project/tests/test_integration.py](kypo/sandbox_service_project/tests/test_integration.py).

    ```bash
    export PUBLIC_NETWORK=<external-public-network-name>
    ```

## Run

1. Run the tests (in the project root):

    ```bash
    pipenv run tox -- -m integration
    ```

**NOTE**: There may be errors in the output,
but the important thing is that the last 2 lines look like the following.

```
py36: commands succeeded
congratulations :)
```

**NOTE**: The integration tests will automatically set variable
`proxy_jump_to_man.HOST` and `proxy_jump_to_man.IdentityFile`, but the variable
`proxy_jump_to_man.USER` must correspond with the default user of the image
specified in variable `sandbox_configuration.extra_node_image`.