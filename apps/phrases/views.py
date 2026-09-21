from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import PhraseForm
from .models import Phrase


def _get_own_phrase(request, pk):
    return get_object_or_404(Phrase, pk=pk, user=request.user)


@login_required
def home(request):
    return render(request, 'home.html', {'phrases': request.user.phrases.all()})


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
        return redirect('home')
    return render(request, 'phrases/confirm_delete.html', {'phrase': phrase})
