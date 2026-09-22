from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import ai
from .forms import AIAutoForm, AIPhraseInputForm, PhraseForm
from .language_state import get_active_language, set_active_language
from .models import Phrase, PhraseProgress
from .services import (
    DIRECTIONS, LEFT, REVIEW_TARGET, RIGHT, get_progress_summary, get_source_counts, get_study_queue, record_swipe,
    restudy, review_interval_label, undo_swipe,
)


def _phrase_limit_error(user):
    """Kullanıcı phrase üst sınırına ulaştıysa mesaj, yoksa None (kontrol ve ekleme arasındaki küçük yarış kabul edilir)."""
    if user.phrases.count() >= settings.MAX_PHRASES_PER_USER:
        return f'En fazla {settings.MAX_PHRASES_PER_USER} phrase ekleyebilirsin. Yenisini eklemek için birini silmelisin.'
    return None


def _get_own_phrase(request, pk):
    return get_object_or_404(Phrase, pk=pk, user=request.user)


@login_required
@require_POST
def set_language(request, code):
    """Kartlar/Phrase'lerim/İstatistik'te gösterilen aktif hedef dili değiştirir (oturumda tutulur)."""
    try:
        set_active_language(request, code)
    except ValueError:
        raise Http404
    next_url = request.POST.get('next')
    # `next` bir gizli form alanı olarak biz gönderiyoruz ama yine de dışarıdan gelen bir yönlendirme gibi doğrulanır.
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('home')


def json_login_required(view):
    """AJAX uç noktaları için: oturum yoksa giriş sayfasına yönlendirmek yerine 401 JSON döner."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Oturum süresi doldu.'}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


@login_required
def home(request):
    language = get_active_language(request)
    summary = get_progress_summary(request.user, language)
    return render(request, 'home.html', {
        'queue': get_study_queue(request.user, language),
        'total_count': summary['total'],
        'learned_count': summary['learned'],
        'reviewing_count': summary['reviewing'],
        'next_review_at': summary['next_review_at'],
        'review_target': REVIEW_TARGET,
        'review_interval': review_interval_label(),
    })


@login_required
def stats(request):
    language = get_active_language(request)
    return render(request, 'phrases/stats.html', {
        'summary': get_progress_summary(request.user, language),
        'sources': get_source_counts(request.user, language),
        'review_target': REVIEW_TARGET,
        'review_interval': review_interval_label(),
    })


@login_required
def phrase_list(request):
    language = get_active_language(request)
    items = (
        request.user.phrase_progress.filter(phrase__target_language=language)
        .select_related('phrase').order_by('-phrase__created_at', '-phrase_id')
    )
    return render(request, 'phrases/list.html', {'items': items, 'review_target': REVIEW_TARGET})


@login_required
def phrase_create(request):
    """Ekleme yöntemi seçimi: manuel ya da AI ile üretim."""
    return render(request, 'phrases/create_choice.html', {'ai_enabled': ai.is_configured()})


@login_required
def phrase_create_manual(request):
    initial = {'target_language': get_active_language(request)}
    form = PhraseForm(request.POST) if request.method == 'POST' else PhraseForm(initial=initial)
    if request.method == 'POST':
        limit_error = _phrase_limit_error(request.user)
        if limit_error:
            form.add_error(None, limit_error)
        elif form.is_valid():
            phrase = form.save(commit=False)
            phrase.user = request.user
            phrase.save()
            set_active_language(request, phrase.target_language)
            messages.success(request, 'Phrase eklendi.')
            return redirect('phrase_detail', pk=phrase.pk)
    return render(request, 'phrases/form.html', {'form': form, 'title': 'Yeni phrase'})


def _ai_preview(request, form, category=None):
    """AI önizlemesi. `category` doluysa tamamen AI modudur: "yeniden üret" yeni bir ifade seçer."""
    auto = category in ai.CATEGORIES
    return render(request, 'phrases/form.html', {
        'form': form,
        'title': 'AI önizleme',
        'ai_mode': True,
        'form_action': reverse('phrase_create_ai_save'),
        'remaining': ai.remaining_generations(request.user),
        'category': category if auto else None,
        'back_url': reverse('phrase_create_ai_auto' if auto else 'phrase_create_ai'),
        'regenerate_url': reverse('phrase_create_ai_auto' if auto else 'phrase_create_ai'),
        'regenerate_label': '↻ Başka bir phrase üret' if auto else '↻ Yeniden üret',
    })


def _preview_form(result, language_code):
    return PhraseForm(
        initial={
            'target_language': language_code,
            'original_phrase': result.phrase,
            'translation': result.translation,
            'association_story': result.association_story,
        },
        initial_breakdown=result.word_breakdown,
    )


def _known_phrases(user, language_code, current=''):
    """Kullanıcının aynı hedef dildeki bildiği ifadeler (AI bunlardan farklı seçer).

    `current`: önizlemede gösterilen ifade (henüz kaydedilmediği için ayrıca eklenir).
    """
    known = list(user.phrases.filter(target_language=language_code).values_list('original_phrase', flat=True)[:200])
    current = ' '.join(current.split())[:ai.MAX_PHRASE_LENGTH]   # istemci metni: AI istemine sınırsız girmesin
    return [current, *known] if current else known


@login_required
def phrase_create_ai(request):
    """Hedef dildeki ifadeyi alır, AI ile üretir ve düzenlenebilir bir önizleme gösterir.

    Hedef dil ayrıca sorulmaz: o an aktif olan dil (üstteki dil anahtarı) kullanılır, böylece yanlışlıkla
    başka bir dilin altına karışık dilde phrase eklenmez.
    """
    language_code = get_active_language(request)
    form = AIPhraseInputForm(request.POST) if request.method == 'POST' else AIPhraseInputForm()

    if request.method == 'POST' and form.is_valid():
        if not ai.is_configured():
            form.add_error(None, ai.AINotConfigured().user_message)
        elif quota_error := ai.quota_error(request.user):
            form.add_error(None, quota_error)
        elif limit_error := _phrase_limit_error(request.user):
            form.add_error(None, limit_error)
        else:
            try:
                result = ai.generate_phrase(form.cleaned_data['original_phrase'], language_code)
            except ai.AIError as error:
                form.add_error(None, error.user_message)
            else:
                ai.record_generation(request.user, result, language_code)
                return _ai_preview(request, _preview_form(result, language_code))

    return render(request, 'phrases/ai_input.html', {
        'form': form,
        'ai_enabled': ai.is_configured(),
        'remaining': ai.remaining_generations(request.user),
        'daily_limit': settings.AI_DAILY_LIMIT,
    })


@login_required
def phrase_create_ai_auto(request):
    """Tamamen AI: ifadeyi de AI seçer (kullanıcının aynı dildeki bildikleri hariç) ve önizleme gösterir.

    Hedef dil ayrıca sorulmaz: o an aktif olan dil (üstteki dil anahtarı) kullanılır.
    """
    language_code = get_active_language(request)
    form = AIAutoForm(request.POST) if request.method == 'POST' else AIAutoForm()

    if request.method == 'POST' and form.is_valid():
        category = form.cleaned_data['category']
        if not ai.is_configured():
            form.add_error(None, ai.AINotConfigured().user_message)
        elif quota_error := ai.quota_error(request.user):
            form.add_error(None, quota_error)
        elif limit_error := _phrase_limit_error(request.user):
            form.add_error(None, limit_error)
        else:
            # Önizlemeden "başka bir phrase üret" denirse gösterilen ifade de (henüz kaydedilmediği için) hariç tutulur.
            avoid = _known_phrases(request.user, language_code, request.POST.get('original_phrase', ''))
            try:
                result = ai.generate_auto_phrase(category, language_code, avoid)
            except ai.AIError as error:
                form.add_error(None, error.user_message)
            else:
                ai.record_generation(request.user, result, language_code)
                return _ai_preview(request, _preview_form(result, language_code), category=category)

    return render(request, 'phrases/ai_auto.html', {
        'form': form,
        'ai_enabled': ai.is_configured(),
        'remaining': ai.remaining_generations(request.user),
        'daily_limit': settings.AI_DAILY_LIMIT,
    })


@login_required
def phrase_create_ai_save(request):
    """AI önizlemesindeki (kullanıcının düzenlemiş olabileceği) içeriği kaydeder."""
    if request.method != 'POST':
        return redirect('phrase_create_ai')
    form = PhraseForm(request.POST)
    limit_error = _phrase_limit_error(request.user)
    if limit_error:
        form.add_error(None, limit_error)
    elif form.is_valid():
        phrase = form.save(commit=False)
        phrase.user = request.user
        phrase.source = Phrase.Source.AI_GENERATED
        phrase.save()
        set_active_language(request, phrase.target_language)
        messages.success(request, 'AI ile üretilen phrase eklendi.')
        return redirect('phrase_detail', pk=phrase.pk)
    # Hata varsa önizleme yeniden gösterilir; tamamen AI modundan geldiyse (gizli `category` alanı) o mod korunur.
    return _ai_preview(request, form, category=request.POST.get('category'))


@login_required
def phrase_detail(request, pk):
    phrase = _get_own_phrase(request, pk)
    return render(request, 'phrases/detail.html', {'phrase': phrase})


@login_required
def phrase_update(request, pk):
    phrase = _get_own_phrase(request, pk)
    form = PhraseForm(request.POST, instance=phrase) if request.method == 'POST' else PhraseForm(instance=phrase)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Phrase güncellendi.')
        return redirect('phrase_detail', pk=phrase.pk)
    return render(request, 'phrases/form.html', {'form': form, 'title': 'Phrase düzenle', 'phrase': phrase})


@login_required
def phrase_delete(request, pk):
    phrase = _get_own_phrase(request, pk)
    if request.method == 'POST':
        phrase.delete()
        messages.success(request, 'Phrase silindi.')
        return redirect('phrase_list')
    return render(request, 'phrases/confirm_delete.html', {'phrase': phrase})


@login_required
@require_POST
def phrase_relearn(request, pk):
    if not restudy(request.user, pk):
        raise Http404
    messages.success(request, 'Phrase tekrar çalışma kuyruğuna alındı.')
    return redirect('phrase_list')


def _progress_json(progress):
    return JsonResponse({
        'status': progress.status,
        'review_streak': progress.review_streak,
        'next_review_at': progress.next_review_at.isoformat() if progress.next_review_at else None,
        'swipe_left_count': progress.swipe_left_count,
        'swipe_right_count': progress.swipe_right_count,
    })


@json_login_required
@require_POST
def phrase_swipe(request, pk):
    direction = request.POST.get('direction')
    if direction not in DIRECTIONS:
        return JsonResponse({'error': 'Geçersiz yön.'}, status=400)
    progress = record_swipe(request.user, pk, direction)
    if progress is None:
        return JsonResponse({'error': 'Phrase bulunamadı.'}, status=404)
    return _progress_json(progress)


@json_login_required
@require_POST
def phrase_swipe_undo(request, pk):
    direction = request.POST.get('direction')
    if direction == LEFT:
        return JsonResponse({'error': 'Yalnızca "ezberledim" geri alınabilir.'}, status=400)
    if direction != RIGHT:
        return JsonResponse({'error': 'Geçersiz yön.'}, status=400)
    progress = undo_swipe(request.user, pk)
    if progress is None:
        exists = PhraseProgress.objects.filter(user=request.user, phrase_id=pk).exists()
        if not exists:
            return JsonResponse({'error': 'Phrase bulunamadı.'}, status=404)
        return JsonResponse({'error': 'Geri alınacak bir işlem yok.'}, status=409)
    return _progress_json(progress)
