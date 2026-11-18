from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


def avatar_upload_to(instance, filename):
    """Store each user's avatar under media/avatars/user_<id>/"""
    return f"avatars/user_{instance.user_id}/{filename}"


class Profile(models.Model):
    """Extra per-user settings (e.g. forced password change)"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    avatar = models.ImageField(
        upload_to=avatar_upload_to,
        blank=True,
        help_text="The user's profile picture",
    )
    must_change_password = models.BooleanField(
        default=True,
        help_text="Ask the user to set a new password after their next login",
    )
    email_verified = models.BooleanField(
        default=False,
        help_text="The user has clicked the verification link sent at registration",
    )
    notify_price_drops = models.BooleanField(
        default=True,
        help_text="Email me when a car I favorited drops in price",
    )
    notify_back_in_stock = models.BooleanField(
        default=True,
        help_text="Email me when a car I favorited is available again",
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
    price_at_save = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Asking price when the car was favorited, used for price-drop alerts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'car'], name='unique_user_car_favorite'),
        ]

    def __str__(self):
        return f"{self.user} favorited {self.car}"


def customer_document_upload_to(instance, filename):
    return f"customer_documents/user_{instance.user_id}/{filename}"


class CustomerDocument(models.Model):
    """Customer document vault - secure uploads for ID copies, logbooks, etc."""
    DOCUMENT_TYPES = [
        ('id_copy', 'ID/Passport Copy'),
        ('driving_license', 'Driving License'),
        ('logbook', 'Logbook'),
        ('proof_of_address', 'Proof of Address'),
        ('insurance', 'Insurance'),
        ('other', 'Other'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='customer_documents',
    )
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    title = models.CharField(max_length=200)
    document = models.FileField(upload_to=customer_document_upload_to)
    notes = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_customer_documents',
    )
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_customer_documents',
    )

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.user.username} - {self.title} ({self.get_document_type_display()})"

