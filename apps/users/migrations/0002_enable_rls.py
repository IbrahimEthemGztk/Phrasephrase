from django.db import migrations

from config.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        enable_rls('users_user', 'users_user_groups', 'users_user_user_permissions'),
    ]
