from django.urls import path

from . import views


urlpatterns = [
    path('pools/', views.PoolList.as_view(), name='pool-list'),
    path('pools/<int:pool_id>/', views.PoolDetail.as_view(), name='pool-detail'),

    path('pools/<int:pool_id>/sandbox-allocation-units/',
         views.SandboxAllocationUnitList.as_view(), name='sandbox-allocation-unit-list'),
    path('pools/<int:pool_id>/sandbox-allocation-units/<int:unit_id>/',
         views.SandboxAllocationUnitDetail.as_view(), name='sandbox-allocation-unit-detail'),

    path('pools/<int:pool_id>/allocation-requests/<int:request_id>/',
         views.SandboxAllocationRequestDetail.as_view(), name='allocation-request-detail'),

    path('pools/<int:pool_id>/allocation-requests/<int:request_id>/stages/',
         views.SandboxCreateRequestStageList.as_view(), name='allocation-request-stage-list'),

    # # Stages
    # path('stages/<int:stage_id>/openstack/',
    #      views.OpenstackStageDetail.as_view(), name='openstack-stage'),
    # path('stages/<int:stage_id>/openstack/events/', views.OpenstackStageEventList.as_view(),
    #      name='sandbox-events'),
    # path('stages/<int:stage_id>/openstack/resources/', views.OpenstackStageResourceList.as_view(),
    #      name='sandbox-resources'),
    #
    # path('stages/<int:stage_id>/bootstrap/',
    #      views.BootstrapStageDetail.as_view(), name='boostrap-stage'),
    #
    # path('stages/<int:stage_id>/ansible/',
    #      views.AnsibleStageDetail.as_view(), name='ansible-stage'),
    # path('stages/<int:stage_id>/ansible/outputs/',
    #      views.AnsibleStageOutputList.as_view(), name='ansible-stage-output'),
    #
    # # FIXME: mocked
    # # path('pools/<int:pool_id>/sandboxes/', views.PoolSandboxList.as_view(), name='sandbox-list'),
    #
    # # Snapshots in OpenStack driver do not work
    # # path('pools/<int:pool_id>/sandboxes/snapshots/', views.PoolSandboxSnapshot.as_view()),
    #
    # path('pools/<int:pool_id>/key-pairs/management/', views.PoolKeypairManagement.as_view(),
    #      name='pool-mng-key-pair'),
    #
    # path('sandboxes/<int:sandbox_id>/delete-requests/', views.SandboxDeleteRequestList.as_view(),
    #      name='sandbox-delete-request'),
    #
    # # FIXME: mocked
    # # path('sandboxes/<int:sandbox_id>/', cache_page(5)(views.SandboxDetail.as_view()), name='sandbox-detail'),
    # path('sandboxes/<int:sandbox_id>/lock/', views.SandboxLock.as_view(), name='sandbox-lock'),
    # path('sandboxes/<int:sandbox_id>/topology/', cache_page(None)(views.SandboxTopology.as_view()),
    #      name='sandbox-topology'),
    #
    # path('sandboxes/<int:sandbox_id>/key-pairs/user/', views.SandboxKeypairUser.as_view(),
    #      name='sandbox-user-key-pair'),
    #
    # path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>/', views.SandboxVMDetail.as_view(),
    #      name='sandbox-vm-detail'),
    # path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>/console/', views.SandboxVMConsole.as_view(),
    #      name='sandbox-vm-console'),
    #
    # # Snapshots in OpenStack driver do not work
    # # path('sandboxes/<int:sandbox_id>/snapshots/', views.SandboxSnapshotList.as_view()),
    # # path('sandboxes/<int:sandbox_id>/snapshots/<str:snapshot_id>/', views.SandboxSnapshotDetail.as_view()),
    # # path('sandboxes/<int:sandbox_id>/snapshots/<str:snapshot_id>/restore/', views.SandboxSnapshotRestore.as_view()),
    #
    # path('sandboxes/<int:sandbox_id>/user-ssh-config/',
    #      cache_page(1)(views.SandboxUserSSHConfig.as_view()), name='sandbox-user-ssh-config'),
    # path('sandboxes/<int:sandbox_id>/management-ssh-config/',
    #      cache_page(1)(views.SandboxManagementSSHConfig.as_view()),
    #      name='sandbox-management-ssh-config'),
    #
    # path('pools/<int:pool_id>/sandboxes/', cache_page(5)(views.PoolSandboxInfoList.as_view()),
    #      name='sandbox-info-list'),
    # path('sandboxes/<int:sandbox_id>/', cache_page(5)(views.SandboxInfoDetail.as_view()),
    #      name='sandbox-info-detail'),
]
