from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import PhraseForm
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
    form = PhraseForm(request.POST) if request.method == 'POST' else PhraseForm()
    if request.method == 'POST' and form.is_valid():
        phrase = form.save(commit=False)
        phrase.user = request.user
        phrase.save()
        messages.success(request, 'Phrase eklendi.')
        return redirect('phrase_detail', pk=phrase.pk)
    return render(request, 'phrases/form.html', {'form': form, 'title': 'Yeni phrase'})


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
