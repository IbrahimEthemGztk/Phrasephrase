from django.db import migrations

from config.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ('phrases', '0001_initial'),
    ]

    operations = [
        enable_rls('phrases_phrase', 'phrases_phraseprogress'),
    ]
