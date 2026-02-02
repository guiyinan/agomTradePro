
from .base import *
import os
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'db.sqlite3'),
    }
}
CORS_ALLOW_ALL_ORIGINS = True
