from django.urls import path

from . import views


urlpatterns = [
    path('definitions/', views.DefinitionList.as_view(), name='definition-list'),
    path('definitions/<int:definition_id>/', views.DefinitionDetail.as_view(),
         name='definition-detail'),
]
