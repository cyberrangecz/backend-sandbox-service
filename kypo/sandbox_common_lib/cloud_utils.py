from kypo.sandbox_common_lib.kypo_config import KypoConfiguration
from kypo.terraform_driver import KypoTerraformClient, AvailableCloudLibraries, \
    KypoTerraformBackendType


def get_database_settings(kypo_config: KypoConfiguration) -> dict:
    db_settings = kypo_config.database
    return {
        'user': db_settings.user,
        'password': db_settings.password,
        'host': db_settings.host,
        'name': db_settings.name,
    }


def get_ostack_client(kypo_config: KypoConfiguration) -> KypoTerraformClient:
    """Abstracts creation and authentication to KYPO lib client."""
    return KypoTerraformClient(
        auth_url=kypo_config.os_auth_url,
        application_credential_id=kypo_config.os_application_credential_id,
        application_credential_secret=kypo_config.os_application_credential_secret,
        trc=kypo_config.trc, cloud_client=AvailableCloudLibraries.OPENSTACK,
        backend_type=KypoTerraformBackendType(
            kypo_config.terraform_configuration.backend_type
        ),
        db_configuration=get_database_settings(kypo_config),
        kube_namespace=kypo_config.ansible_runner_settings.namespace,
    )


def get_aws_client(kypo_config: KypoConfiguration) -> KypoTerraformClient:
    """
    Get AWS terraform client
    """
    return KypoTerraformClient(
        aws_access_key=kypo_config.aws.access_key_id,
        aws_secret_key=kypo_config.aws.secret_access_key,
        region=kypo_config.aws.region,
        availability_zone=kypo_config.aws.availability_zone,
        base_vpc_name=kypo_config.aws.base_vpc,
        base_subnet_name=kypo_config.aws.base_subnet,
        trc=kypo_config.trc, cloud_client=AvailableCloudLibraries.AWS,
        backend_type=KypoTerraformBackendType(
            kypo_config.terraform_configuration.backend_type
        ),
        db_configuration=get_database_settings(kypo_config),
        kube_namespace=kypo_config.ansible_runner_settings.namespace,
    )
