import json
import time

from asgiref.sync import async_to_sync
from channels.generic.websocket import WebsocketConsumer
from django.core.exceptions import ValidationError


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
        
        self.room_group_name = "students_room"     # only one group
        print("Room Group Name:", self.room_group_name)
        self.accept()

        # Join room group
        async_to_sync(self.channel_layer.group_add)(
            self.room_group_name, 
            self.channel_name    # channel_name is automatically generated and is unique for each connection
        )

        self.send(text_data=json.dumps({
            "type": "connection_established",
            "message": "WebSocket connection established."
        }))

    def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json.get("message", "")
        print("Received message:", message)
        
        """
        self.send(text_data=json.dumps({
            "type": "chat",
            "message": message,
        }))
        """
        # Send message to room group
        async_to_sync(self.channel_layer.group_send)(
            self.room_group_name,
            {
                "type": "chat_messsage",
                "message": message,
            },
        ) 
        
    def chat_messsage(self, event):
        message = event["message"]
        self.send(text_data=json.dumps({
            "type": "chat",
            "message": message,
            "user_name": self.user_name,
        }))
        
    def disconnect(self, close_code):
        # Leave room group
        async_to_sync(self.channel_layer.group_discard)(
            self.room_group_name, self.channel_name
        )

    def make_cake(self, event):
        message = event["message"]
        self.send_progress_msg("Gathering Ingredients", 1)
        self.gather_ingredients()
        self.send_progress_msg("Preparing the Batter", 2)
        self.prepare_the_batter()
        self.send_progress_msg("Preparing Cake Pans", 3)
        self.prepare_cake_pans()
        self.send_progress_msg("Baking", 4)
        try:
            self.bake()
        except ValidationError as e:
            self.send_error_msg(e)
            return None
        self.send_progress_msg("Cooling And Frosting", 5)
        self.cool_and_frost()
        self.send_completed_msg(message.get("message"), message.get("progress"))
        self.disconnect(1000)
 
 
    def gather_ingredients(self):
        time.sleep(1)

    def prepare_the_batter(self):
        time.sleep(1)

    def prepare_cake_pans(self):
        time.sleep(1)

    def bake(self):
        time.sleep(2)
        if self.temperature == "high":
            raise ValidationError("Temperature was too high, the cake burned")

    def cool_and_frost(self):
        time.sleep(1)
        
    def send_progress_msg(self, msg, progress):
        self.send(
            text_data=json.dumps(
                {
                    "type": "progress",
                    "message": msg,
                    "progress": progress,
                }
            )
        )

    def send_completed_msg(self, msg, progress):
        self.send(
            text_data=json.dumps(
                {
                    "type": "completed",
                    "message": msg,
                    "progress": progress,
                }
            )
        )

    def send_error_msg(self, msg):
        if not isinstance(msg, str):
            msg = (
                msg.args[0] if hasattr(msg, "args") and len(msg.args) > 0 else str(msg)
            )
        self.send(text_data=json.dumps({"type": "error", "message": msg}))