from rest_framework_simplejwt.authentication import JWTAuthentication
from django.conf import settings

class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        # Look for the 'access_token' cookie
        raw_token = request.COOKIES.get(settings.SIMPLE_JWT['AUTH_COOKIE']) or None
        
        if raw_token is None:
            return None

        # Standard SimpleJWT validation
        validated_token = self.get_validated_token(raw_token)
        
        # Returns (user, token)
        return self.get_user(validated_token), validated_token