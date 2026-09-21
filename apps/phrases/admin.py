from django.contrib import admin

from .models import AIGeneration, Phrase, PhraseProgress


@admin.register(Phrase)
class PhraseAdmin(admin.ModelAdmin):
    list_display = ('original_phrase', 'translation', 'user', 'source', 'created_at')
    list_filter = ('source',)
    search_fields = ('original_phrase', 'translation', 'user__email')


@admin.register(PhraseProgress)
class PhraseProgressAdmin(admin.ModelAdmin):
    list_display = ('phrase', 'user', 'status', 'swipe_left_count', 'swipe_right_count', 'last_reviewed_at')
    list_filter = ('status',)


@admin.register(AIGeneration)
class AIGenerationAdmin(admin.ModelAdmin):
    list_display = ('prompt_text', 'user', 'model_name', 'input_tokens', 'output_tokens', 'thought_tokens', 'created_at')
    search_fields = ('prompt_text', 'user__email')
    date_hierarchy = 'created_at'
