"""App config that points Django's default admin site at our superuser-only
site. This module is imported early (from INSTALLED_APPS) so it must not pull
in models; it only imports the admin app config.
"""
from django.contrib.admin.apps import AdminConfig


class SuperuserAdminConfig(AdminConfig):
    default_site = "config.admin.SuperuserAdminSite"
