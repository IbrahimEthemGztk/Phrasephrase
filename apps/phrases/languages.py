"""Uygulamanın öğretebileceği hedef diller: tek kayıt defteri (registry).

Sesteş/hikaye dili her zaman Türkçe kalır; burada değişen yalnızca "hangi dili öğreniyorsun" (hedef dil).
Yeni bir dil eklemek için (en fazla birkaç dil beklenir; bu yüzden veritabanı değil düz bir sözlük):

1. Aşağıya bir `TargetLanguage` girdisi ekle: kod, Türkçe görünen ad, sesli okuma için BCP-47 kodu.
2. En az 1 (tercihen 2) `Example` yaz: gerçek bir ifade + her kelimesi için gerçek bir Türkçe sesteş + kısa hikaye.
   Bu örnekler AI'ya biçim ve üslubu öğreten few-shot örnekleridir; kalitesi üretim kalitesini doğrudan etkiler.
3. İstersen `function_word_hints` ile kısa işlev kelimeleri (the, de, la gibi) için sesteş önerileri ekle.

Başka hiçbir yeri değiştirmeye gerek yok: ekleme formları, dil anahtarı, AI istemleri ve sesli okuma
buradan besleniyor. `apps/phrases/test_languages.py` her girdinin eksiksiz olduğunu denetler.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExampleWord:
    word: str
    hint: str


@dataclass(frozen=True)
class Example:
    """AI istemindeki bir few-shot örneği: gerçek bir ifade, sesteşleri ve bağlayan hikaye."""

    phrase: str
    translation: str
    words: tuple[ExampleWord, ...]
    story: str


@dataclass(frozen=True)
class TargetLanguage:
    code: str
    name: str                                    # Türkçe görünen ad: "İngilizce"
    speech_locale: str                           # Web Speech API için BCP-47 kodu: "en-US"
    examples: tuple[Example, ...]
    function_word_hints: tuple[ExampleWord, ...] = ()

    @property
    def example_phrases(self):
        """Few-shot örneklerindeki ifadeler: tamamen AI modunda tekrar seçilmesinler diye dışlanır."""
        return tuple(example.phrase for example in self.examples)


def _w(word, hint):
    return ExampleWord(word, hint)


TARGET_LANGUAGES = {
    'en': TargetLanguage(
        code='en', name='İngilizce', speech_locale='en-US',
        function_word_hints=(
            _w('a', 'Ey'), _w('the', 'De'), _w('of', 'Of'), _w('in', 'İn'),
            _w('on', 'On'), _w('at', 'At'), _w('is', 'İz'), _w('I', 'Ay'),
        ),
        examples=(
            Example(
                phrase='Break a leg', translation='Bol şans',
                words=(_w('Break', 'Bırak'), _w('a', 'Ey'), _w('leg', 'Lig')),
                story=(
                    'Antrenör sahaya çıkacak oyuncuya döndü: "Korkuyu bırak! Ey genç, Süper Lig seni '
                    'bekliyor. Bol şans!"'
                ),
            ),
            Example(
                phrase='Piece of cake', translation='Çocuk oyuncağı (çok kolay)',
                words=(_w('Piece', 'Pis'), _w('of', 'Of'), _w('cake', 'Kek')),
                story=(
                    'Pis elli bir çocuk yere düşen kekine baktı, "Of" diye içini çekti ve yine de yedi. '
                    'Çünkü kek yemek onun için çocuk oyuncağıydı: çok kolay!'
                ),
            ),
        ),
    ),
    'es': TargetLanguage(
        code='es', name='İspanyolca', speech_locale='es-ES',
        function_word_hints=(
            _w('de', 'De'), _w('la', 'La'), _w('el', 'El'), _w('en', 'En'),
            _w('un', 'Un'), _w('no', 'Nota'), _w('que', 'Kek'),
        ),
        examples=(
            Example(
                phrase='Dar en el clavo', translation='Tam on ikiden vurmak',
                words=(_w('Dar', 'Dar'), _w('en', 'En'), _w('el', 'El'), _w('clavo', 'Klavye')),
                story=(
                    'Dar bir ofiste çalışan yazılımcı, ekranın enini ölçtükten sonra elini uzattı ve '
                    'klavyede tam doğru tuşa bastı: sorunu tam on ikiden çözmüştü!'
                ),
            ),
            Example(
                phrase='Tirar la toalla', translation='Pes etmek',
                words=(_w('Tirar', 'Tiran'), _w('la', 'La'), _w('toalla', 'Tavla')),
                story=(
                    'Zalim bir tiran, sarayında "la" notasını bir türlü tutturamayan şarkıcıyı dinleyince '
                    'öfkeyle masadaki tavlayı fırlatıp pes etti.'
                ),
            ),
        ),
    ),
}

DEFAULT_LANGUAGE_CODE = 'en'


def choices():
    """Form/model `choices` için: [(kod, ad), ...]."""
    return [(code, language.name) for code, language in TARGET_LANGUAGES.items()]


def get(code, default=None):
    return TARGET_LANGUAGES.get(code, default)
