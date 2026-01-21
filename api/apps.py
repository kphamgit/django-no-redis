from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'
 
    def ready(self):
        # Import signals to connect them when the app is ready
        print("ApiConfig is ready, importing signals...")
        import api.signals
