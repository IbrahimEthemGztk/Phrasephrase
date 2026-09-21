from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import ai
from .forms import AIAutoForm, AIPhraseInputForm, PhraseForm
from .models import Phrase, PhraseProgress
from .services import DIRECTIONS, get_study_queue, record_swipe, restudy, undo_swipe


def _get_own_phrase(request, pk):
    return get_object_or_404(Phrase, pk=pk, user=request.user)


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
    counts = request.user.phrase_progress.aggregate(
        total=Count('id'),
        learned=Count('id', filter=Q(status=PhraseProgress.Status.LEARNED)),
    )
    return render(request, 'home.html', {
        'queue': get_study_queue(request.user),
        'total_count': counts['total'],
        'learned_count': counts['learned'],
    })


@login_required
def phrase_list(request):
    items = request.user.phrase_progress.select_related('phrase').order_by('-phrase__created_at', '-phrase_id')
    return render(request, 'phrases/list.html', {'items': items})


@login_required
def phrase_create(request):
    """Ekleme yöntemi seçimi: manuel ya da AI ile üretim."""
    return render(request, 'phrases/create_choice.html', {'ai_enabled': ai.is_configured()})


@login_required
def phrase_create_manual(request):
    form = PhraseForm(request.POST) if request.method == 'POST' else PhraseForm()
    if request.method == 'POST' and form.is_valid():
        phrase = form.save(commit=False)
        phrase.user = request.user
        phrase.save()
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


def _preview_form(result):
    return PhraseForm(
        initial={
            'original_phrase': result.phrase,
            'translation': result.translation,
            'association_story': result.association_story,
        },
        initial_breakdown=result.word_breakdown,
    )


def _known_phrases(user, current=''):
    """Kullanıcının zaten bildiği ifadeler (AI bunlardan farklı seçer). `current`: önizlemede gösterilen ifade."""
    known = list(user.phrases.values_list('original_phrase', flat=True)[:200])
    current = ' '.join(current.split())
    return [current, *known] if current else known


@login_required
def phrase_create_ai(request):
    """İngilizce ifadeyi alır, AI ile üretir ve düzenlenebilir bir önizleme gösterir."""
    form = AIPhraseInputForm(request.POST) if request.method == 'POST' else AIPhraseInputForm()

    if request.method == 'POST' and form.is_valid():
        if not ai.is_configured():
            form.add_error(None, ai.AINotConfigured().user_message)
        elif ai.remaining_generations(request.user) <= 0:
            form.add_error(None, 'Bugünlük AI üretim hakkın doldu. Yarın tekrar deneyebilir ya da manuel ekleyebilirsin.')
        else:
            try:
                result = ai.generate_phrase(form.cleaned_data['original_phrase'])
            except ai.AIError as error:
                form.add_error(None, error.user_message)
            else:
                ai.record_generation(request.user, result)
                return _ai_preview(request, _preview_form(result))

    return render(request, 'phrases/ai_input.html', {
        'form': form,
        'ai_enabled': ai.is_configured(),
        'remaining': ai.remaining_generations(request.user),
        'daily_limit': settings.AI_DAILY_LIMIT,
    })


@login_required
def phrase_create_ai_auto(request):
    """Tamamen AI: ifadeyi de AI seçer (kullanıcının zaten bildikleri hariç) ve düzenlenebilir önizleme gösterir."""
    form = AIAutoForm(request.POST) if request.method == 'POST' else AIAutoForm()

    if request.method == 'POST' and form.is_valid():
        category = form.cleaned_data['category']
        if not ai.is_configured():
            form.add_error(None, ai.AINotConfigured().user_message)
        elif ai.remaining_generations(request.user) <= 0:
            form.add_error(None, 'Bugünlük AI üretim hakkın doldu. Yarın tekrar deneyebilir ya da manuel ekleyebilirsin.')
        else:
            # Önizlemeden "başka bir phrase üret" denirse gösterilen ifade de (henüz kaydedilmediği için) hariç tutulur.
            avoid = _known_phrases(request.user, request.POST.get('original_phrase', ''))
            try:
                result = ai.generate_auto_phrase(category, avoid)
            except ai.AIError as error:
                form.add_error(None, error.user_message)
            else:
                ai.record_generation(request.user, result)
                return _ai_preview(request, _preview_form(result), category=category)

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
    if form.is_valid():
        phrase = form.save(commit=False)
        phrase.user = request.user
        phrase.source = Phrase.Source.AI_GENERATED
        phrase.save()
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
    if direction not in DIRECTIONS:
        return JsonResponse({'error': 'Geçersiz yön.'}, status=400)
    progress = undo_swipe(request.user, pk, direction)
    if progress is None:
        exists = PhraseProgress.objects.filter(user=request.user, phrase_id=pk).exists()
        if not exists:
            return JsonResponse({'error': 'Phrase bulunamadı.'}, status=404)
        return JsonResponse({'error': 'Geri alınacak bir işlem yok.'}, status=409)
    return _progress_json(progress)
