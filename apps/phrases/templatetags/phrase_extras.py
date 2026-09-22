from math import ceil

from django import template
from django.utils import timezone

from .. import languages

register = template.Library()


@register.filter
def speech_locale(language_code):
    """Bir hedef dil koduna karşılık gelen Web Speech API kodu: "en-US", "es-ES"."""
    language = languages.get(language_code) or languages.get(languages.DEFAULT_LANGUAGE_CODE)
    return language.speech_locale


@register.filter
def language_name(language_code):
    """Bir hedef dil kodunun Türkçe görünen adı: "İngilizce", "İspanyolca"."""
    language = languages.get(language_code)
    return language.name if language else language_code


@register.filter
def until_text(value):
    """Gelecekteki bir zamanı kısa Türkçe metne çevirir: "12 dk sonra", "5 sa sonra", "1 gün sonra"."""
    if not value:
        return ''
    minutes = ceil((value - timezone.now()).total_seconds() / 60)
    if minutes <= 0:
        return 'şimdi'
    if minutes < 60:
        return f'{minutes} dk sonra'
    hours = ceil(minutes / 60)
    if hours < 24:
        return f'{hours} sa sonra'
    return f'{ceil(hours / 24)} gün sonra'
