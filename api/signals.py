from django.db.models.signals import post_save
from django.contrib.auth.models import User
from django.dispatch import receiver
from .models import Profile

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    print("Signal triggered for User:", instance.username)
    if created:
        # Create a profile only if it doesn't already exist
        Profile.objects.get_or_create(user=instance)
    else:
        # Save the profile only if it exists
        if hasattr(instance, 'profile'):
            instance.profile.save()