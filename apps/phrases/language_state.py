"""Kullanıcının o an çalıştığı hedef dili oturumda tutar (Kartlar/Phrase'lerim/İstatistik bunu kullanır).

Diller birbirine çevrilmez: her phrase tek bir hedef dile aittir, bu modül yalnızca hangi dilin
gösterileceğini seçer/hatırlar.
"""

from . import languages
from .models import Phrase

SESSION_KEY = 'study_language'


def get_active_language(request):
    """Oturumdaki geçerli bir dili döndürür. Yoksa kullanıcının en son eklediği phrase'in dilini,
    o da yoksa varsayılan dili kullanır (oturuma yazmaz; bir sonraki istekte aynı mantık tekrar çalışır)."""
    code = request.session.get(SESSION_KEY)
    if code in languages.TARGET_LANGUAGES:
        return code
    latest = Phrase.objects.filter(user=request.user).values_list('target_language', flat=True).first()
    return latest if latest in languages.TARGET_LANGUAGES else languages.DEFAULT_LANGUAGE_CODE


def set_active_language(request, code):
    """Oturumdaki aktif dili değiştirir. Bilinmeyen bir kod verilirse ValueError fırlatır."""
    if code not in languages.TARGET_LANGUAGES:
        raise ValueError(f'Bilinmeyen dil: {code!r}')
    request.session[SESSION_KEY] = code
