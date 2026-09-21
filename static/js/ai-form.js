// AI üretim formları: gönderim sırasında "hazırlıyor" durumunu gösterir ve çift tıklamayı engeller.
(function () {
    const status = document.querySelector('[data-ai-status]');

    function reset() {
        if (status) status.hidden = true;
        document.querySelectorAll('[data-ai-generate] button[type="submit"], [data-ai-regenerate]').forEach((button) => {
            button.disabled = false;
            if (button.dataset.label) button.textContent = button.dataset.label;
        });
    }

    document.querySelectorAll('form').forEach((form) => {
        form.addEventListener('submit', (event) => {
            const submitter = event.submitter;
            const generating = form.hasAttribute('data-ai-generate')
                || (submitter && submitter.hasAttribute('data-ai-regenerate'));
            if (!generating) return;

            if (status) status.hidden = false;
            if (submitter) {
                submitter.dataset.label = submitter.textContent;
                submitter.textContent = 'AI hazırlıyor…';
            }
            // Gönderim başladıktan sonra kilitle (disabled düğme değeri gönderilmediği için erteliyoruz).
            setTimeout(() => {
                form.querySelectorAll('button[type="submit"]').forEach((button) => { button.disabled = true; });
            }, 0);
        });
    });

    // Geri tuşuyla dönüldüğünde sayfa kilitli kalmasın.
    window.addEventListener('pageshow', (event) => {
        if (event.persisted) reset();
    });
})();
