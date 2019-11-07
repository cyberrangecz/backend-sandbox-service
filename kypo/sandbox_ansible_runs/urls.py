from django.urls import path

from . import views


urlpatterns = [
    path('stages/<int:stage_id>/ansible/',
         views.AnsibleStageDetail.as_view(), name='ansible-stage'),
    path('stages/<int:stage_id>/ansible/outputs/',
         views.AnsibleStageOutputList.as_view(), name='ansible-stage-output'),
]
