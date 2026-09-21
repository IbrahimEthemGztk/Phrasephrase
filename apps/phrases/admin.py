from django.contrib import admin

from .models import Phrase, PhraseProgress


@admin.register(Phrase)
class PhraseAdmin(admin.ModelAdmin):
    list_display = ('original_phrase', 'translation', 'user', 'source', 'created_at')
    list_filter = ('source',)
    search_fields = ('original_phrase', 'translation', 'user__email')


@admin.register(PhraseProgress)
class PhraseProgressAdmin(admin.ModelAdmin):
    list_display = ('phrase', 'user', 'status', 'swipe_left_count', 'swipe_right_count', 'last_reviewed_at')
    list_filter = ('status',)
