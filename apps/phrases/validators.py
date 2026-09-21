from django.core.exceptions import ValidationError

MAX_WORDS = 30
MAX_TEXT_LENGTH = 100
BREAKDOWN_KEYS = {'order', 'original_word', 'sound_hint'}


def build_word_breakdown(words, hints):
    """Form satırlarından sıralı word_breakdown listesi üretir.

    Sıra numarası istemciden alınmaz; satırların geliş sırasına göre 1'den başlayarak
    burada verilir (kelime sırası kuralı). Sondaki tamamen boş satırlar atılır, aradaki
    boş satırlar doğrulamada hata verir ki satır numaraları formdakilerle eşleşsin.
    """
    if len(words) != len(hints):
        raise ValidationError('Kelime ve ses karşılığı satırları eşleşmiyor.')

    rows = [(word.strip(), hint.strip()) for word, hint in zip(words, hints)]
    while rows and not rows[-1][0] and not rows[-1][1]:
        rows.pop()

    return [
        {'order': index, 'original_word': word, 'sound_hint': hint}
        for index, (word, hint) in enumerate(rows, start=1)
    ]


def validate_word_breakdown(value):
    """word_breakdown'un sıralı ve eksiksiz olduğunu doğrular (form, model ve AI çıktısı için)."""
    if not isinstance(value, list) or not value:
        raise ValidationError('En az bir kelime ve ses karşılığı girmelisin.')
    if len(value) > MAX_WORDS:
        raise ValidationError(f'En fazla {MAX_WORDS} kelime girebilirsin.')

    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict) or set(item) != BREAKDOWN_KEYS:
            raise ValidationError(f'{index}. satırın biçimi geçersiz.')
        if item['order'] != index:
            raise ValidationError('Kelime sırası bozuk: sıra numaraları 1, 2, 3… şeklinde ardışık olmalı.')
        for key, label in (('original_word', 'kelime'), ('sound_hint', 'ses karşılığı')):
            text = item[key]
            if not isinstance(text, str) or not text.strip():
                raise ValidationError(f'{index}. satırda {label} boş olamaz.')
            if len(text) > MAX_TEXT_LENGTH:
                raise ValidationError(f'{index}. satırda {label} en fazla {MAX_TEXT_LENGTH} karakter olabilir.')
