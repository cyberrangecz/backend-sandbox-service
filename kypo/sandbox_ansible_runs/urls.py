from django.urls import path

from . import views


urlpatterns = [
    path('stages/allocation/<int:stage_id>/ansible/',
         views.AnsibleAllocationStageDetail.as_view(), name='ansible-allocation-stage'),
    path('stages/allocation/<int:stage_id>/ansible/outputs/',
         views.AnsibleStageOutputList.as_view(), name='ansible-stage-output'),

    path('stages/cleanup/<int:stage_id>/ansible/',
         views.AnsibleCleanupStageDetail.as_view(), name='ansible-cleanup-stage'),
]
