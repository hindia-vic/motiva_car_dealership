from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    """Extra per-user settings (e.g. forced password change)"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    must_change_password = models.BooleanField(
        default=True,
        help_text="Ask the user to set a new password after their next login",
    )
    email_verified = models.BooleanField(
        default=False,
        help_text="The user has clicked the verification link sent at registration",
    )

    def __str__(self):
        return f"Profile for {self.user.username}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Ensure every user has a profile; only staff accounts start with
    must_change_password=True (set explicitly by the creation view)."""
    if created:
        Profile.objects.create(user=instance, must_change_password=False)


class Favorite(models.Model):
    """A car saved/favorited by a registered user"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favorites',
    )
    car = models.ForeignKey(
        'cars.Car',
        on_delete=models.CASCADE,
        related_name='favorited_by',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'car'], name='unique_user_car_favorite'),
        ]

    def __str__(self):
        return f"{self.user} favorited {self.car}"
