from django.urls import re_path

from . import consumers

#websocket_urlpatterns = [
   # path("ws/chatroom/<chatroom_name>", ChatroomConsumer.as_asgi()),
#]

#websocket_urlpatterns = [
#    re_path(
#        r"ws/bar/(?P<room_name>\w+)/(?P<temperature>\w+)/$",
#        consumers.ChatroomConsumer.as_asgi(),
#    ),
#]

websocket_urlpatterns = [
    re_path(
        r"ws/socket-server/(?P<user_name>\w+)",
        consumers.ChatroomConsumer.as_asgi(),
    ),
]