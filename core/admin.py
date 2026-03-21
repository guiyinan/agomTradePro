"""
Custom Admin Configuration for AgomTradePro
Apply custom branding to the default admin site
"""
from django.contrib import admin

# Update default admin site branding
admin.site.site_title = 'AgomTradePro 管理后台'
admin.site.site_header = 'AgomTradePro'
admin.site.index_title = '欢迎使用 AgomTradePro 管理后台'

# Disable the "View on site" links for models that don't have absolute URLs
admin.site.site_url = None


