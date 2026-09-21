from itertools import zip_longest

from django import forms
from django.core.exceptions import ValidationError

from .ai import CATEGORY_CHOICES
from .models import Phrase
from .validators import MAX_TEXT_LENGTH, MAX_WORDS, build_word_breakdown, validate_word_breakdown


class PhraseForm(forms.ModelForm):
    """Phrase formu. Kelime/ses karşılığı satırları `original_word` ve `sound_hint` alanlarının
    tekrarlanan girdileri olarak gelir ve sıra numarası sunucuda üretilir."""

    class Meta:
        model = Phrase
        fields = ('original_phrase', 'translation', 'association_story')
        labels = {
            'original_phrase': 'İngilizce cümle / deyim',
            'translation': 'Türkçe anlamı',
            'association_story': 'Çağrışım hikayesi',
        }
        widgets = {
            'original_phrase': forms.TextInput(attrs={'placeholder': 'Break a leg', 'autofocus': True}),
            'translation': forms.TextInput(attrs={'placeholder': 'Bol şans'}),
            'association_story': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': 'Ses karşılıklarını birbirine bağlayan kısa, akılda kalıcı bir hikaye yaz…',
            }),
        }

    def __init__(self, *args, initial_breakdown=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            rows = zip_longest(self.data.getlist('original_word'), self.data.getlist('sound_hint'), fillvalue='')
            self.rows = [{'original_word': word, 'sound_hint': hint} for word, hint in rows]
        elif self.instance.pk:
            self.rows = [
                {'original_word': item['original_word'], 'sound_hint': item['sound_hint']}
                for item in self.instance.word_breakdown
            ]
        elif initial_breakdown:
            # AI önizlemesi: henüz kaydedilmemiş, önceden doldurulmuş kelime satırları
            self.rows = [
                {'original_word': item['original_word'], 'sound_hint': item['sound_hint']}
                for item in initial_breakdown
            ]
        else:
            self.rows = []
        if not self.rows:
            self.rows = [{'original_word': '', 'sound_hint': ''}]
        self.max_text_length = MAX_TEXT_LENGTH

    def clean(self):
        cleaned_data = super().clean()
        try:
            breakdown = build_word_breakdown(
                self.data.getlist('original_word'), self.data.getlist('sound_hint'),
            )
            validate_word_breakdown(breakdown)
        except ValidationError as error:
            self.add_error(None, error)
        else:
            self.instance.word_breakdown = breakdown
        return cleaned_data


class AIPhraseInputForm(forms.Form):
    """AI ile üretim için tek alanlı giriş: yalnızca İngilizce ifade."""

    original_phrase = forms.CharField(
        label='İngilizce cümle / deyim',
        max_length=Phrase._meta.get_field('original_phrase').max_length,
        widget=forms.TextInput(attrs={'placeholder': 'Break a leg', 'autofocus': True, 'autocomplete': 'off'}),
    )

    def clean_original_phrase(self):
        value = ' '.join(self.cleaned_data['original_phrase'].split())
        if len(value.split()) > MAX_WORDS:
            raise forms.ValidationError(f'En fazla {MAX_WORDS} kelime girebilirsin.')
        return value


class AIAutoForm(forms.Form):
    """Tamamen AI ile üretim: yalnızca istenen ifade türü seçilir, ifadeyi AI seçer."""

    category = forms.ChoiceField(
        label='Ne tür bir ifade?',
        choices=CATEGORY_CHOICES,
        initial='random',
    )
