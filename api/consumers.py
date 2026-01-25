import json
import time

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer
from django.core.exceptions import ValidationError
from django.core.cache import cache


#class ChatroomConsumer(WebsocketConsumer):
#    def connect(self):
#        self.accept()
        
class ChatroomConsumer(WebsocketConsumer):
    def connect(self):
        """
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        print("Room Name:", self.room_name)
        self.temperature = self.scope["url_route"]["kwargs"]["temperature"]
        print("Temperature:", self.temperature)
        #self.room_group_name = f"chat_{self.room_name}"
        #print("Room Group Name:", self.room_group_name)
        
        """
        
        self.user_name = self.scope["url_route"]["kwargs"]["user_name"]
        
        #print("Connected User Name:", self.user_name)
        
        self.room_group_name = "students_room"     # only one group
        #print("Room Group Name:", self.room_group_name)
        self.accept()

      # Add the user to the cache
        #print(" new user connected")
        #print(" current users in cache before adding:", cache.get("students_room_users", set()))
        #print("Adding user to cache:", self.user_name)
        self.add_user_to_cache(self.user_name)

        # Join room group
        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name, 
            self.channel_name    # channel_name is automatically generated and is unique for each connection
        )

        connected_users = cache.get("students_room_users", set())   
        connected_users_list = list(connected_users)
        # send connection established message
        # send this message to everybody in the group including the newly connected user
        # print(' sending connection established message to group', connected_users_list)
        async_to_sync(self.channel_layer.group_send)(
            self.room_group_name,
            {
                "type": "send_connection_change_message_handler",   # name of event handler method
                "message_type": "connection_change",
                "message": "WebSocket connection established for user:" + self.user_name,
                "connected_users": connected_users_list,
            },
        )
        
        """
        self.send(text_data=json.dumps({
            "type": "connection_established",
            "message": "WebSocket connection established.",
            "connected_users": connected_users_list,
        }))
        """
    def send_connection_change_message_handler(self, event): # event handler method
        #print("Event received in send_connected_message_handler:", event)
        self.send(text_data=json.dumps({
            "message_type": event["message_type"],
            "message": event["message"],
            "connected_users": event["connected_users"],
        }))

    def add_user_to_cache(self, user_name):
        #print("Trying to add user to cache. User :", user_name)
        """
        Add a user to the cache for connected users.
        """
        connected_users = cache.get("students_room_users", set())
        #print("Current connected users from cache:", connected_users)
        if user_name in connected_users:
            print("User already in connected users:", user_name)
        else:
            #print("User not in connected users. Adding user:", user_name)
            connected_users.add(user_name) # add the new user if not already present
            # if present, python set will ignore duplicate
            print("Finish adding user. Now, connected_users:", connected_users)
            print(" Setting updated connected users in cache.")
            cache.set("students_room_users", connected_users, timeout=None)
        
         # get the updated list and print
            updated_users = cache.get("students_room_users", set())
            #print("Updated connected users in cache:", updated_users)
       
    def remove_user_from_cache(self, user_name):
        """
        Remove a user from the Redis cache for connected users.
        """
        connected_users = cache.get("students_room_users", set())
        if user_name in connected_users:
            connected_users.remove(user_name)
            print("Removed user from connected users:", user_name)
            cache.set("students_room_users", connected_users, timeout=None)
        
        # get the updated list and print
        updated_users = cache.get("students_room_users", set())
        #print("Updated connected users in cache after removal:", updated_users)

    def receive(self, text_data):
        text_data_json = json.loads(text_data)
        #print("Received data text_data_json:", text_data_json)
        message = text_data_json.get("message", "")
        source_user = text_data_json.get("user_name", "")
        message_type = text_data_json.get("message_type", "")
        #print("Received message:", message)
        
        """
        # 
        self.send(text_data=json.dumps({
            "type": "chat",
            "message": message,
        }))
        """
        # Relay message to room group
        # when the group_send is called, the chat_message event handler method is triggered
        # and message is sent to everyone in the group
        async_to_sync(self.channel_layer.group_send)(    # triggers an event handler method
            self.room_group_name,
            {
                "type": "send_message_handler",   # name of event handler method
                "message_type": message_type,
                "message": message,     # the 'message' key will be passed to the event handler method
                "user_name": source_user,
            },
        ) 
        
    def send_message_handler(self, event): # event handler method
        #print("Event received in send_message_handler:", event)
        #message = event["message"]   # get value of 'message' key from event dict
        source_user = event["user_name"]
        self.send(text_data=json.dumps({
            "message_type": event["message_type"],
            "message": event["message"],
            "user_name": source_user,
        }))
        
    def disconnect(self, close_code):
        # Remove the user from the cache
        self.remove_user_from_cache(self.user_name)
        # print out the updated list of connected users
        # print("User disconnected:", self.user_name)
        # print(" users after disconnect:", cache.get("students_room_users", set()))
        # Leave room group
        async_to_sync(self.channel_layer.group_discard)(
            self.room_group_name, self.channel_name
        )
        
        connected_users = cache.get("students_room_users", set())   
        connected_users_list = list(connected_users)
        # send connection established message
        # send this message to everybody in the group including the newly connected user
        # print(' sending connection established message to group', connected_users_list)
        async_to_sync(self.channel_layer.group_send)(
            self.room_group_name,
            {
                "type": "send_connection_change_message_handler",   # name of event handler method
                "message_type": "connection_change",
                "message": "WebSocket connection dropped for user:" + self.user_name,
                "connected_users": connected_users_list,
            },
        )

    def send_error_msg(self, msg):
        if not isinstance(msg, str):
            msg = (
                msg.args[0] if hasattr(msg, "args") and len(msg.args) > 0 else str(msg)
            )
        self.send(text_data=json.dumps({"type": "error", "message": msg}))