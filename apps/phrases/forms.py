from itertools import zip_longest

from django import forms
from django.core.exceptions import ValidationError

from .ai import CATEGORY_CHOICES, MAX_STORY_LENGTH
from .models import Phrase
from .validators import MAX_TEXT_LENGTH, MAX_WORDS, build_word_breakdown, validate_word_breakdown


class PhraseForm(forms.ModelForm):
    """Phrase formu. Kelime/ses karşılığı satırları `original_word` ve `sound_hint` alanlarının
    tekrarlanan girdileri olarak gelir ve sıra numarası sunucuda üretilir."""

    # Modelde blank=True (eski kayıtlar boş kalabilsin diye); yeni eklenen her phrase için burada zorunlu kılınır.
    example_sentence = forms.CharField(
        label='Örnek cümle',
        max_length=Phrase._meta.get_field('example_sentence').max_length,
        widget=forms.TextInput(attrs={'placeholder': "Don't worry, it will be a piece of cake."}),
    )
    example_sentence_translation = forms.CharField(
        label='Örnek cümlenin Türkçe anlamı',
        max_length=Phrase._meta.get_field('example_sentence_translation').max_length,
        widget=forms.TextInput(attrs={'placeholder': 'Merak etme, çocuk oyuncağı olacak.'}),
    )
    # Modelde TextField olduğu için sınır yok; burada AI çıktısıyla aynı üst sınır uygulanır (veritabanını şişirmesin).
    association_story = forms.CharField(
        label='Çağrışım hikayesi',
        max_length=MAX_STORY_LENGTH,
        widget=forms.Textarea(attrs={
            'rows': 5,
            'placeholder': 'Ses karşılıklarını birbirine bağlayan kısa, akılda kalıcı bir hikaye yaz…',
        }),
    )

    class Meta:
        model = Phrase
        fields = (
            'target_language', 'original_phrase', 'translation', 'example_sentence',
            'example_sentence_translation', 'association_story',
        )
        labels = {
            'target_language': 'Hedef dil',
            'original_phrase': 'Cümle / deyim',
            'translation': 'Türkçe anlamı',
        }
        widgets = {
            'original_phrase': forms.TextInput(attrs={'placeholder': 'Break a leg', 'autofocus': True}),
            'translation': forms.TextInput(attrs={'placeholder': 'Bol şans'}),
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
    """AI ile üretim için giriş: o an aktif olan hedef dildeki ifade (dil ayrıca sorulmaz, aktif dil kullanılır)."""

    original_phrase = forms.CharField(
        label='Cümle / deyim',
        max_length=Phrase._meta.get_field('original_phrase').max_length,
        widget=forms.TextInput(attrs={'placeholder': 'Break a leg', 'autofocus': True, 'autocomplete': 'off'}),
    )

    def clean_original_phrase(self):
        value = ' '.join(self.cleaned_data['original_phrase'].split())
        if len(value.split()) > MAX_WORDS:
            raise forms.ValidationError(f'En fazla {MAX_WORDS} kelime girebilirsin.')
        return value


class AIAutoForm(forms.Form):
    """Tamamen AI ile üretim: istenen ifade türü seçilir (dil sorulmaz, aktif dil kullanılır), ifadeyi AI seçer."""

    category = forms.ChoiceField(
        label='Ne tür bir ifade?',
        choices=CATEGORY_CHOICES,
        initial='random',
    )
