"""Giriş yapmış kullanıcı için aktif hedef dili ve dil listesini tüm şablonlara ekler (dil anahtarı, formlar)."""

from . import languages
from .language_state import get_active_language


def study_language(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    code = get_active_language(request)
    return {
        'active_language': code,
        'active_language_name': languages.TARGET_LANGUAGES[code].name,
        'target_languages': languages.TARGET_LANGUAGES,
    }
