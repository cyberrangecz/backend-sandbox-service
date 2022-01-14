"""Sandbox Ansible App urls."""

from django.urls import path

from kypo.sandbox_ansible_app import views

urlpatterns = [
    path('allocation-requests/<int:request_id>/stages/networking-ansible',
         views.NetworkingAnsibleAllocationStageDetailView.as_view(),
         name='networking-ansible-allocation-stage'),
    path('allocation-requests/<int:request_id>/stages/user-ansible',
         views.UserAnsibleAllocationStageDetailView.as_view(),
         name='user-ansible-allocation-stage'),

    path('cleanup-requests/<int:request_id>/stages/networking-ansible',
         views.NetworkingAnsibleCleanupStageDetailView.as_view(),
         name='networking-ansible-cleanup-stage'),
    path('cleanup-requests/<int:request_id>/stages/user-ansible',
         views.UserAnsibleCleanupStageDetailView.as_view(),
         name='user-ansible-cleanup-stage'),

    path('allocation-requests/<int:request_id>/stages/networking-ansible/outputs',
         views.NetworkingAnsibleOutputListView.as_view(),
         name='networking-ansible-output'),
    path('allocation-requests/<int:request_id>/stages/user-ansible/outputs',
         views.UserAnsibleOutputListView.as_view(),
         name='user-ansible-output'),
]
