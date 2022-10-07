import abc

import docker
import structlog
from django.conf import settings
from docker.models.containers import Container
from kubernetes import client, config, watch
from kubernetes.client import V1PersistentVolumeClaimVolumeSource
from kypo.cloud_commons import KypoException

from kypo.sandbox_ansible_app.models import AllocationAnsibleOutput, CleanupAnsibleOutput
from kypo.sandbox_common_lib import exceptions

LOG = structlog.get_logger()
ANSIBLE_FILE_VOLUME_NAME = "ansible-files-path"


class ContainerVolume:
    def __init__(self, name: str, bind: str, mode: str):
        self.name = name
        self.bind = bind
        self.mode = mode


class BaseContainer(abc.ABC):
    """Base class for all containers."""

    ANSIBLE_SSH_DIR = ContainerVolume(
        name='ansible-ssh-dir',
        bind='/root/.ssh',
        mode='rw'
    )
    ANSIBLE_INVENTORY_PATH = ContainerVolume(
        name='ansible-inventory-path',
        bind='/app/inventory.yml',
        mode='ro'
    )
    ANSIBLE_DOCKER_CONTAINER_PATH = ContainerVolume(
        name='docker-containers-path',
        bind='/root/containers',
        mode='rw'
    )

    @abc.abstractmethod
    def __init__(self, url, rev, stage, ssh_directory, inventory_path, containers_path, cleanup=False):
        """Initialize the container."""
        self.url = url
        self.rev = rev
        self.stage = stage
        self.cleanup = cleanup
        self.ssh_directory = ssh_directory
        self.inventory_path = inventory_path
        self.containers_path = containers_path
        self.output_class = CleanupAnsibleOutput if self.cleanup else AllocationAnsibleOutput
        self.stage_info = {'cleanup_stage': self.stage} if self.cleanup\
            else {'allocation_stage': self.stage}

    @abc.abstractmethod
    def _run_container(self):
        """Run the container."""
        pass

    @abc.abstractmethod
    def get_container_name(self):
        """Get the container ID."""
        pass

    @abc.abstractmethod
    def get_container_outputs(self):
        """Get the container outputs."""
        pass

    @abc.abstractmethod
    def check_container_status(self):
        """Check the container status."""
        pass

    @abc.abstractmethod
    def delete(self):
        """Delete the container."""
        pass

    @classmethod
    @abc.abstractmethod
    def delete_container(cls, container_name):
        """Delete the container. Used when cancelling a stage."""
        pass


class DockerContainer(BaseContainer):
    """Docker container."""

    DOCKER_NETWORK = settings.KYPO_CONFIG.ansible_docker_network
    CLIENT = docker.from_env

    def __init__(self, url, rev, stage, ssh_directory, inventory_path, containers_path, cleanup=False):
        """Initialize the container."""
        super().__init__(url, rev, stage, ssh_directory, inventory_path, containers_path, cleanup)
        self.container = self._run_container()

    def _run_container(self):
        """
        Run Ansible in Docker container.
        """
        volumes = {
            self.ssh_directory: self.ANSIBLE_SSH_DIR.__dict__,
            self.inventory_path: self.ANSIBLE_INVENTORY_PATH.__dict__,
            self.containers_path: self.ANSIBLE_DOCKER_CONTAINER_PATH.__dict__
        }
        command = ['-u', self.url, '-r', self.rev, '-i', self.ANSIBLE_INVENTORY_PATH.bind,
                   '-a', settings.KYPO_CONFIG.answers_storage_api]
        command += ['-c'] if self.cleanup else []
        LOG.debug("Ansible container options", command=command)
        return self.CLIENT().containers.run(settings.KYPO_CONFIG.ansible_docker_image, detach=True,
                                            command=command, volumes=volumes,
                                            network=self.DOCKER_NETWORK)

    def get_container_name(self):
        """Get the container ID."""
        return self.container.id

    def get_container_outputs(self):
        """Get the container outputs."""
        for output in self.container.logs(stream=True):
            output = output.decode('utf-8')
            output = output[:-1] if output[-1] == '\n' else output
            self.output_class.objects.create(**self.stage_info, content=output)

    def check_container_status(self):
        """Check the container status."""
        status = self.container.wait(timeout=settings.KYPO_CONFIG.sandbox_ansible_timeout)
        status_code = status['StatusCode']
        if status_code != 0:
            raise exceptions.AnsibleError(f'Ansible stage {self.stage.id} failed.'
                                          f' See Ansible outputs for details.')

    @classmethod
    def _get_container(cls, container_id: str) -> Container:
        """
        Return Docker container with given container ID.
        """
        return cls.CLIENT().containers.get(container_id)

    @classmethod
    def delete_container(cls, container_name):
        """Delete the container. Used when cancelling a stage."""
        cls._get_container(container_name).remove(force=True)

    def delete(self):
        """Delete the container."""
        self.delete_container(self.get_container_name())


class KubernetesContainer(BaseContainer):
    """Kubernetes container."""

    ALLOCATION_JOB_NAME = 'ansible-allocation-{}'
    CLEANUP_JOB_NAME = 'ansible-cleanup-{}'
    KUBERNETES_NAMESPACE = settings.KYPO_CONFIG.ansible_runner_settings.namespace
    CORE_API = client.CoreV1Api()
    BATCH_API = client.BatchV1Api()

    def __init__(self, url, rev, stage, ssh_directory, inventory_path, containers_path, cleanup=False):
        """Initialize the container."""
        super().__init__(url, rev, stage, ssh_directory, inventory_path, containers_path, cleanup)
        self.job_name = self.ALLOCATION_JOB_NAME.format(self.stage.id) if not self.cleanup\
            else self.CLEANUP_JOB_NAME.format(self.stage.id)
        self._initialize_kube_config()
        self.container = self._run_container()

    @classmethod
    def _initialize_kube_config(cls):
        """Initialize the kubernetes config."""
        try:
            config.load_incluster_config()
        except config.ConfigException as exc:
            raise KypoException(exc)

        cls.CORE_API = client.CoreV1Api()
        cls.BATCH_API = client.BatchV1Api()

    def _create_container(self):
        """Create the container."""
        kuber_container = client.V1Container(
            name=self.job_name,
            image=settings.KYPO_CONFIG.ansible_docker_image,
            args=['-u', self.url, '-r', self.rev, '-i', self.ANSIBLE_INVENTORY_PATH.bind,
                  '-a', settings.KYPO_CONFIG.answers_storage_api]
        )
        kuber_container.args += ['-c'] if self.cleanup else []
        kuber_container.volume_mounts = [
            client.V1VolumeMount(
                name=ANSIBLE_FILE_VOLUME_NAME,
                mount_path=self.ANSIBLE_SSH_DIR.bind,
                sub_path=self.ssh_directory[
                         len(settings.KYPO_CONFIG.ansible_runner_settings.volumes_path)+1:]
            ),
            client.V1VolumeMount(
                name=ANSIBLE_FILE_VOLUME_NAME,
                mount_path=self.ANSIBLE_INVENTORY_PATH.bind,
                sub_path=self.inventory_path[
                         len(settings.KYPO_CONFIG.ansible_runner_settings.volumes_path)+1:]
            ),
            client.V1VolumeMount(
                name=ANSIBLE_FILE_VOLUME_NAME,
                mount_path=self.ANSIBLE_DOCKER_CONTAINER_PATH.bind,
                sub_path=self.inventory_path[
                         len(settings.KYPO_CONFIG.ansible_runner_settings.volumes_path) + 1:]
            )
        ]

        return kuber_container

    def _create_kube_job(self):
        """
        Run Ansible in Kubernetes job.
        """
        kuber_container = self._create_container()

        job = client.V1Job(
            metadata=client.V1ObjectMeta(
                name=self.job_name,
                namespace=self.KUBERNETES_NAMESPACE
            ),
            spec=client.V1JobSpec(
                backoff_limit=0,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        name=self.job_name,
                        namespace=self.KUBERNETES_NAMESPACE
                    ),
                    spec=client.V1PodSpec(
                        restart_policy='Never',
                        containers=[kuber_container],
                        volumes=[
                            client.V1Volume(
                                name=ANSIBLE_FILE_VOLUME_NAME,
                                persistent_volume_claim=V1PersistentVolumeClaimVolumeSource(
                                    claim_name=settings.KYPO_CONFIG.ansible_runner_settings.persistent_volume_claim_name
                                )
                            )
                        ]
                    )
                )
            )
        )
        self.BATCH_API.create_namespaced_job(namespace=self.KUBERNETES_NAMESPACE, body=job)

        return job

    def _run_container(self):
        """Run the container."""
        return self._create_kube_job()

    def get_container_name(self):
        """Return the container name."""
        return self.job_name

    def _wait_for_pod_start(self):
        """
        Wait for pod to start.
        """
        w = watch.Watch()
        for event in w.stream(self.CORE_API.list_namespaced_pod, namespace=self.KUBERNETES_NAMESPACE,
                              label_selector='job-name={}'.format(self.job_name)):
            pod_phase = event['object'].status.phase
            if pod_phase == 'Running' or pod_phase == 'Failed':
                w.stop()
                return event['object'].metadata.name
            if event['type'] == 'DELETED':
                w.stop()
                raise KypoException('Pod was deleted before it was ready.')

    def _wait_for_job_finish(self):
        """
        Wait for job to finish.
        """
        w = watch.Watch()
        for event in w.stream(self.BATCH_API.list_namespaced_job, namespace=self.KUBERNETES_NAMESPACE,
                              label_selector='job-name={}'.format(self.job_name)):
            job_status = event['object'].status
            if job_status.failed or job_status.succeeded:
                w.stop()
                return job_status

    def _save_pod_outputs(self, pod_name: str):
        """
        Replace live outputs of the pod with the ones from the storage.
        """
        temporary_outputs = self.output_class.objects.filter(**self.stage_info)
        temporary_outputs.delete()
        pod_outputs = self.CORE_API.read_namespaced_pod_log(name=pod_name,
                                                            namespace=self.KUBERNETES_NAMESPACE)
        for output in pod_outputs.split('\n'):
            self.output_class.objects.create(**self.stage_info, content=output)

    def get_container_outputs(self):
        """
        Return the container outputs.
        """
        w = watch.Watch()

        pod_name = self._wait_for_pod_start()
        job_done = False
        while not job_done:
            for log in w.stream(self.CORE_API.read_namespaced_pod_log, name=pod_name,
                                namespace=self.KUBERNETES_NAMESPACE, _preload_content=False):
                self.output_class.objects.create(**self.stage_info, content=log)
                job = self.BATCH_API.read_namespaced_job_status(name=self.job_name,
                                                                namespace=self.KUBERNETES_NAMESPACE)
                if job.status.succeeded or job.status.failed:
                    job_done = True
                    w.stop()
                    break
        self._save_pod_outputs(pod_name)

    def check_container_status(self):
        """Check the container status."""
        status = self._wait_for_job_finish()
        if status.failed or (status.conditions and status.conditions[0].type == 'Failed'):
            raise exceptions.AnsibleError(f'Ansible stage {self.stage.id} failed.'
                                          f' See Ansible outputs for details.')

    @classmethod
    def delete_container(cls, container_name):
        """Delete the container."""
        cls._initialize_kube_config()
        try:
            cls.BATCH_API.delete_namespaced_job(name=container_name,
                                                namespace=cls.KUBERNETES_NAMESPACE,
                                                body=client.V1DeleteOptions(
                                                    propagation_policy='Background'
                                                ))
        except client.ApiException as exc:
            raise KypoException('Failed to delete job: {}'.format(exc))

    def delete(self):
        """Delete the container."""
        self.delete_container(self.get_container_name())
