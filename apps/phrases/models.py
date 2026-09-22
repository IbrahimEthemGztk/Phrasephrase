from django.conf import settings
from django.db import models

from . import languages
from .validators import validate_word_breakdown


class Phrase(models.Model):
    class Source(models.TextChoices):
        MANUAL = 'manual', 'Manuel'
        AI_GENERATED = 'ai_generated', 'AI ile üretildi'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='phrases')
    # Sesteş/hikaye dili her zaman Türkçe; bu, öğrenilen hedef dildir (bkz. languages.py).
    target_language = models.CharField(
        'hedef dil', max_length=8, choices=languages.choices(), default=languages.DEFAULT_LANGUAGE_CODE,
    )
    original_phrase = models.CharField('orijinal cümle', max_length=300)
    translation = models.CharField('çeviri', max_length=300)
    # İfadenin gerçek bir cümle içinde kullanıldığı örnek; boş olabilir (eski kayıtlar, bkz. migration 0006).
    example_sentence = models.CharField('örnek cümle', max_length=300, blank=True, default='')
    example_sentence_translation = models.CharField('örnek cümlenin çevirisi', max_length=300, blank=True, default='')
    # Sıralı liste: [{"order": 1, "original_word": "...", "sound_hint": "..."}, ...]
    word_breakdown = models.JSONField('kelime kelime ses karşılığı', default=list, validators=[validate_word_breakdown])
    association_story = models.TextField('çağrışım hikayesi')
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.original_phrase

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Her phrase, sahibi için bir ilerleme kaydıyla başlar (Faz 3 swipe mantığı bunu kullanır).
        PhraseProgress.objects.get_or_create(user=self.user, phrase=self)


class PhraseProgress(models.Model):
    class Status(models.TextChoices):
        LEARNING = 'learning', 'Öğreniliyor'
        REVIEWING = 'reviewing', 'Tekrarda'
        LEARNED = 'learned', 'Öğrenildi'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='phrase_progress')
    phrase = models.ForeignKey(Phrase, on_delete=models.CASCADE, related_name='progress')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.LEARNING)
    swipe_left_count = models.PositiveIntegerField(default=0)
    swipe_right_count = models.PositiveIntegerField(default=0)
    # Aralıklı tekrar: üst üste kaç kez "ezberledim" denildi (0-3). 3'e ulaşınca kart kalıcı `learned` olur.
    review_streak = models.PositiveSmallIntegerField(default=0)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    # Yalnızca `reviewing` durumunda dolu: kartın Kartlar ekranına yeniden gireceği an.
    next_review_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'phrase'], name='unique_progress_per_user_phrase'),
        ]

    def __str__(self):
        return f'{self.user} · {self.phrase} · {self.status}'


class AIGeneration(models.Model):
    """Başarılı her AI üretiminin kaydı: günlük limit ve kullanım (token) takibi için."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_generations')
    prompt_text = models.CharField(max_length=300)
    model_name = models.CharField(max_length=100)
    target_language = models.CharField(
        'hedef dil', max_length=8, choices=languages.choices(), default=languages.DEFAULT_LANGUAGE_CODE,
    )
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    thought_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} · {self.prompt_text}'
