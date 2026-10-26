from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError


class Command(BaseCommand):
    help = "Used to create a default superuser from ADMIN_EMAIL / ADMIN_PASSWORD."
    requires_migrations_checks = True

    def handle(self, *args, **options):
        if not settings.EMAIL or not settings.PASSWORD:
            msg = "ADMIN_EMAIL and ADMIN_PASSWORD must be set."
            raise CommandError(msg)
        user, _created = get_user_model().objects.update_or_create(
            email=settings.EMAIL,
            defaults={"is_staff": True, "is_superuser": True, "is_active": True},
        )
        user.set_password(settings.PASSWORD)
        user.save()
