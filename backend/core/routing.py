from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/hal/(?P<client_id>[\w-]+)/$', consumers.HalConsumer.as_asgi()),
]
