from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('email',)
        widgets = {
            'email': forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs['autocomplete'] = 'new-password'
        self.fields['password2'].widget.attrs['autocomplete'] = 'new-password'

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Bu e-posta ile kayıtlı bir hesap zaten var.')
        return email


class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'E-posta veya parola hatalı.',
    }

    username = forms.EmailField(
        label='E-posta',
        widget=forms.EmailInput(attrs={'autocomplete': 'email', 'autofocus': True}),
    )

    def clean_username(self):
        return self.cleaned_data['username'].lower()
