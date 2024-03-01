from crczp.sandbox_common_lib.exceptions import ValidationError
from crczp.sandbox_common_lib.crczp_config import CrczpConfiguration
from crczp.terraform_driver import CrczpTerraformClient, AvailableCloudLibraries, \
    CrczpTerraformBackendType


def get_database_settings(crczp_config: CrczpConfiguration) -> dict:
    db_settings = crczp_config.database
    return {
        'user': db_settings.user,
        'password': db_settings.password,
        'host': db_settings.host,
        'name': db_settings.name,
    }


def get_ostack_client(crczp_config: CrczpConfiguration) -> CrczpTerraformClient:
    """Abstracts creation and authentication to CRCZP lib client."""
    if None in [
        crczp_config.os_auth_url,
        crczp_config.os_application_credential_id,
        crczp_config.os_application_credential_secret,
    ]:
        raise ValidationError(
            "Missing OpenStack configuration options. "
            "Either AWS or OpenStack configuration must be set."
        )

    return CrczpTerraformClient(
        auth_url=crczp_config.os_auth_url,
        application_credential_id=crczp_config.os_application_credential_id,
        application_credential_secret=crczp_config.os_application_credential_secret,
        trc=crczp_config.trc, cloud_client=AvailableCloudLibraries.OPENSTACK,
        backend_type=CrczpTerraformBackendType(
            crczp_config.terraform_configuration.backend_type
        ),
        db_configuration=get_database_settings(crczp_config),
        kube_namespace=crczp_config.ansible_runner_settings.namespace,
    )


def get_aws_client(crczp_config: CrczpConfiguration) -> CrczpTerraformClient:
    """
    Get AWS terraform client
    """
    return CrczpTerraformClient(
        aws_access_key=crczp_config.aws.access_key_id,
        aws_secret_key=crczp_config.aws.secret_access_key,
        region=crczp_config.aws.region,
        availability_zone=crczp_config.aws.availability_zone,
        base_vpc_name=crczp_config.aws.base_vpc,
        base_subnet_name=crczp_config.aws.base_subnet,
        trc=crczp_config.trc, cloud_client=AvailableCloudLibraries.AWS,
        backend_type=CrczpTerraformBackendType(
            crczp_config.terraform_configuration.backend_type
        ),
        db_configuration=get_database_settings(crczp_config),
        kube_namespace=crczp_config.ansible_runner_settings.namespace,
    )
