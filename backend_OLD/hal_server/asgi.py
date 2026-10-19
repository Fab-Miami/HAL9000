import os
import django
from django.core.asgi import get_asgi_application

# 1. Set the environment variable FIRST
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hal_server.settings')

# 2. Call django.setup() or get_asgi_application() to initialize settings
django_asgi_app = get_asgi_application()

# 3. NOW import your application-specific code (models, consumers, routing)
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import core.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            core.routing.websocket_urlpatterns
        )
    ),
})
