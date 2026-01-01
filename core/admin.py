"""
Custom Admin Configuration for AgomSAAF
Apply custom branding to the default admin site
"""
from django.contrib import admin

# Update default admin site branding
admin.site.site_title = 'AgomSAAF 管理后台'
admin.site.site_header = 'AgomSAAF'
admin.site.index_title = '欢迎使用 AgomSAAF 管理后台'

# Disable the "View on site" links for models that don't have absolute URLs
admin.site.site_url = None


