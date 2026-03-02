
from .base import *
import os
DEBUG = True
# Development only: relax host checks for local debugging/tools.
ALLOWED_HOSTS = ['*']
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'db.sqlite3'),
    }
}
CORS_ALLOW_ALL_ORIGINS = True
