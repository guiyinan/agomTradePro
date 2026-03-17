from django.urls import path

from apps.agent_runtime.interface.page_views import (
    operator_proposal_detail_view,
    operator_proposal_list_view,
    operator_task_detail_view,
    operator_task_list_view,
)

app_name = "agent_runtime_pages"

urlpatterns = [
    path("", operator_task_list_view, name="task_list"),
    path("tasks/<int:task_id>/", operator_task_detail_view, name="task_detail"),
    path("proposals/", operator_proposal_list_view, name="proposal_list"),
    path("proposals/<int:proposal_id>/", operator_proposal_detail_view, name="proposal_detail"),
]
