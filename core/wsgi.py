"""
WSGI config for AgomTradePro project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')

application = get_wsgi_application()
