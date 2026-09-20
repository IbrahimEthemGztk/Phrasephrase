// Parola alanlarında "Göster / Gizle" düğmesi
document.querySelectorAll('[data-toggle-password]').forEach((button) => {
    const input = document.getElementById(button.dataset.togglePassword);
    if (!input) return;
    button.addEventListener('click', () => {
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        button.textContent = show ? 'Gizle' : 'Göster';
        button.setAttribute('aria-label', show ? 'Parolayı gizle' : 'Parolayı göster');
    });
});
