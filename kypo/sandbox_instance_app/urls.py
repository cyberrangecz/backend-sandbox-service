"""Sandbox Instance App urls."""

from django.urls import path

from kypo.sandbox_instance_app import views

urlpatterns = [
    path('pools', views.PoolListCreateView.as_view(), name='pool-list'),
    path('pools/<int:pool_id>', views.PoolDetailDeleteView.as_view(), name='pool-detail'),
    path('pools/<int:pool_id>/definition', views.PoolDefinitionView.as_view(), name='pool-definition'),
    path('pools/<int:pool_id>/locks', views.PoolLockListCreateView.as_view(), name='pool-lock-list'),
    path('pools/<int:pool_id>/locks/<int:lock_id>', views.PoolLockDetailDeleteView.as_view(),
         name='pool-lock-detail'),
    path('pools/<int:pool_id>/allocation-requests', views.PoolAllocationRequestListView.as_view(),
         name='pool-allocation-request-list'),
    path('pools/<int:pool_id>/cleanup-requests', views.PoolCleanupRequestsListCreateView.as_view(),
         name='pool-cleanup-request-list'),
    path('pools/<int:pool_id>/variables',
         views.PoolVariablesView.as_view(), name='pool-variables'),

    path('pools/<int:pool_id>/sandbox-allocation-units',
         views.SandboxAllocationUnitListCreateView.as_view(), name='sandbox-allocation-unit-list'),

    # Sandbox allocation units
    path('sandbox-allocation-units/<int:unit_id>',
         views.SandboxAllocationUnitDetailView.as_view(), name='sandbox-allocation-unit-detail'),
    path('sandbox-allocation-units/<int:unit_id>/allocation-request',
         views.SandboxAllocationRequestView.as_view(), name='sandbox-allocation-request'),
    path('sandbox-allocation-units/<int:unit_id>/cleanup-request',
         views.SandboxCleanupRequestView.as_view(), name='sandbox-cleanup-request'),
    path('sandbox-allocation-units/<int:unit_id>/allocation-stages/restart',
         views.SandboxAllocationStagesRestartView.as_view(), name='allocation-stages-restart'),

    # Allocation request
    path('allocation-requests/<request_id>',
         views.AllocationRequestDetailView.as_view(), name='sandbox-allocation-request-detail'),
    path('allocation-requests/<int:request_id>/cancel',
         views.AllocationRequestCancelView.as_view(), name='sandbox-allocation-request-cancel'),

    # Cleanup request
    path('cleanup-requests/<int:request_id>',
         views.CleanupRequestDetailView.as_view(), name='sandbox-cleanup-request-detail'),
    path('cleanup-requests/<int:request_id>/cancel',
         views.CleanupRequestCancelView.as_view(), name='sandbox-cleanup-request-cancel'),

    # Stages
    path('allocation-requests/<int:request_id>/stages/terraform',
         views.TerraformAllocationStageDetailView.as_view(),
         name='openstack-allocation-stage'),
    path('cleanup-requests/<int:request_id>/stages/terraform',
         views.TerraformCleanupStageDetailView.as_view(),
         name='terraform-cleanup-stage'),

    path('allocation-requests/<int:request_id>/stages/terraform/outputs',
         views.TerraformAllocationStageOutputListView.as_view(), name='terraform-outputs'),

    # Pool manipulation
    path('pools/<int:pool_id>/sandboxes', views.PoolSandboxListView.as_view(),
         name='pool-sandbox-list'),
    path('pools/<int:pool_id>/sandboxes/get-and-lock', views.SandboxGetAndLockView.as_view(),
         name='pool-sandbox-get-and-lock'),
    path('pools/<int:pool_id>/management-ssh-access',
         views.PoolManagementSSHAccessView.as_view(),
         name='pool-management-ssh-access'),

    # Sandboxes
    path('sandboxes/<int:sandbox_id>', views.SandboxDetailView.as_view(), name='sandbox-detail'),
    path('sandboxes/<int:sandbox_id>/locks', views.SandboxLockListCreateView.as_view(),
         name='sandbox-lock-list'),
    path('sandboxes/<int:sandbox_id>/locks/<int:lock_id>',
         views.SandboxLockDetailDestroyView.as_view(), name='sandbox-lock-detail'),
    path('sandboxes/<int:sandbox_id>/topology',
         views.SandboxTopologyView.as_view(), name='sandbox-topology'),

    path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>',
         views.SandboxVMDetailView.as_view(),  name='sandbox-vm-detail'),
    path('sandboxes/<int:sandbox_id>/vms/<str:vm_name>/console',
         views.SandboxVMConsoleView.as_view(), name='sandbox-vm-console'),

    path('sandboxes/<int:sandbox_id>/user-ssh-access',
         views.SandboxUserSSHAccessView.as_view(),
         name='sandbox-user-ssh-access'),

    path('sandboxes/<int:sandbox_id>/man-out-port-ip',
         views.SandboxManOutPortIPView.as_view(),
         name='man-out-port-ip'),

    path('sandboxes/<int:sandbox_id>/consoles',
         views.SandboxConsolesView.as_view(),
         name='consoles')
]
