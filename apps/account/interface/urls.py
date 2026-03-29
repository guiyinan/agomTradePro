"""Account URL Configuration."""

from django.urls import path
from django.views.generic import RedirectView

from apps.account.interface import views

app_name = 'account'

urlpatterns = [
    path("", RedirectView.as_view(url="/account/login/", permanent=False), name="home"),
    # 页面视图
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('settings/', views.settings_view, name='settings'),
    path('settings/tokens/create/', views.create_self_token_view, name='create_self_token'),
    path('settings/tokens/<int:token_id>/revoke/', views.revoke_self_token_view, name='revoke_self_token'),
    path('capital-flow/', views.capital_flow_view, name='capital_flow'),
    path('backtest/<int:backtest_id>/apply/', views.apply_backtest_results_view, name='apply_backtest'),

    # 账户协作视图
    path('collaboration/', views.collaboration_view, name='collaboration'),
    path('observer/', views.observer_portal_view, name='observer_portal'),

    # ⭐ 创建投资组合功能已移至 simulated_trading 模块
    # 访问路径：/simulated-trading/my-accounts/

    # 管理员视图（用户管理）
    path('admin/users/', views.user_management_view, name='user_management'),
    path('admin/tokens/', views.token_management_view, name='token_management'),
    path('admin/tokens/<int:user_id>/rotate/', views.rotate_user_token_view, name='rotate_user_token'),
    path('admin/tokens/<int:user_id>/revoke/', views.revoke_user_token_view, name='revoke_user_token'),
    path('admin/access-tokens/<int:token_id>/revoke/', views.revoke_access_token_view, name='revoke_access_token'),
    path('admin/tokens/<int:user_id>/mcp-toggle/', views.toggle_user_mcp_view, name='toggle_user_mcp'),
    path('admin/users/<int:user_id>/approve/', views.approve_user_view, name='approve_user'),
    path('admin/users/<int:user_id>/reject/', views.reject_user_view, name='reject_user'),
    path('admin/users/<int:user_id>/role/', views.set_user_role_view, name='set_user_role'),
    path('admin/users/<int:user_id>/reset/', views.reset_user_status_view, name='reset_user_status'),
    path('admin/settings/', views.system_settings_view, name='system_settings'),
]
