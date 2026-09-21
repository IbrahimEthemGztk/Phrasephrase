"""Çalışma (kart yığını) mantığı: kuyruk kurma ve swipe kayıtları."""

from django.db import transaction
from django.db.models import Case, F, IntegerField, Value, When
from django.utils import timezone

from .models import PhraseProgress

RIGHT = 'right'
LEFT = 'left'
DIRECTIONS = (RIGHT, LEFT)

STUDY_QUEUE_LIMIT = 50


def get_study_queue(user, limit=STUDY_QUEUE_LIMIT):
    """Kullanıcının çalışma kuyruğunu döndürür (PhraseProgress listesi).

    Yalnızca `learning` durumundaki kartlar girer. Sıra: önce daha önce görülüp
    öğrenilememiş kartlar (en eski gözden geçirilen önce), sonra hiç görülmemişler
    (eklenme sırasıyla). "Hiç görülmemiş" = iki swipe sayacı da sıfır.
    """
    unseen = Case(
        When(swipe_left_count=0, swipe_right_count=0, then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )
    queryset = (
        PhraseProgress.objects
        .filter(user=user, status=PhraseProgress.Status.LEARNING)
        .select_related('phrase')
        .annotate(unseen=unseen)
        .order_by('unseen', F('last_reviewed_at').asc(nulls_last=True), 'phrase__created_at', 'phrase_id')
    )
    return list(queryset[:limit])


def record_swipe(user, phrase_id, direction):
    """Swipe'ı kaydeder. Güncel PhraseProgress'i döndürür, kayıt yoksa None.

    Sağ: öğrenildi. Sol: öğreniliyor kalır. Sayaçlar F() ile artırılır.
    """
    if direction == RIGHT:
        changes = {'status': PhraseProgress.Status.LEARNED, 'swipe_right_count': F('swipe_right_count') + 1}
    elif direction == LEFT:
        changes = {'status': PhraseProgress.Status.LEARNING, 'swipe_left_count': F('swipe_left_count') + 1}
    else:
        raise ValueError(f'Geçersiz yön: {direction!r}')

    own = PhraseProgress.objects.filter(user=user, phrase_id=phrase_id)
    if not own.update(last_reviewed_at=timezone.now(), **changes):
        return None
    return own.get()


def restudy(user, phrase_id):
    """Öğrenilmiş bir phrase'i tekrar çalışma kuyruğuna alır (durumu `learning` yapar).

    Swipe sayaçları ve geçmiş korunur; phrase zaten `learning` ise bir şey değişmez.
    Kullanıcının böyle bir phrase'i yoksa False döndürür.
    """
    own = PhraseProgress.objects.filter(user=user, phrase_id=phrase_id)
    return bool(own.update(status=PhraseProgress.Status.LEARNING))


@transaction.atomic
def undo_swipe(user, phrase_id, direction):
    """Son swipe'ı geri alır. Geri alınacak bir şey yoksa None döndürür.

    `direction` geri alınan swipe'ın yönüdür. Sayaçlar hiçbir zaman sıfırın altına inmez.
    Kart hiç görülmemiş haline dönerse (iki sayaç da sıfır) `last_reviewed_at` de temizlenir.
    """
    own = PhraseProgress.objects.filter(user=user, phrase_id=phrase_id)
    if direction == RIGHT:
        updated = own.filter(
            status=PhraseProgress.Status.LEARNED, swipe_right_count__gt=0,
        ).update(status=PhraseProgress.Status.LEARNING, swipe_right_count=F('swipe_right_count') - 1)
    elif direction == LEFT:
        updated = own.filter(
            status=PhraseProgress.Status.LEARNING, swipe_left_count__gt=0,
        ).update(swipe_left_count=F('swipe_left_count') - 1)
    else:
        raise ValueError(f'Geçersiz yön: {direction!r}')

    if not updated:
        return None
    own.filter(swipe_left_count=0, swipe_right_count=0).update(last_reviewed_at=None)
    return own.get()
