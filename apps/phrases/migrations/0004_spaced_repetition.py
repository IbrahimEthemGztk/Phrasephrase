from django.db import migrations, models

REVIEW_TARGET = 3


def mark_learned_as_complete(apps, schema_editor):
    """Bu özellikten önce öğrenilmiş kartlar kalıcı kalır: 3 başarıyı tamamlamış sayılır."""
    PhraseProgress = apps.get_model('phrases', 'PhraseProgress')
    PhraseProgress.objects.filter(status='learned').update(review_streak=REVIEW_TARGET)


class Migration(migrations.Migration):

    dependencies = [
        ('phrases', '0003_aigeneration'),
    ]

    operations = [
        migrations.AddField(
            model_name='phraseprogress',
            name='review_streak',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='phraseprogress',
            name='status',
            field=models.CharField(
                choices=[('learning', 'Öğreniliyor'), ('reviewing', 'Tekrarda'), ('learned', 'Öğrenildi')],
                default='learning', max_length=10,
            ),
        ),
        migrations.RunPython(mark_learned_as_complete, migrations.RunPython.noop),
    ]
