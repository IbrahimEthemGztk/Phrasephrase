// Sesli okuma: tarayıcının konuşma sentezi (Web Speech API) ile hedef dildeki cümleyi okur.
// Her düğme kendi dilini `data-speak-lang` ile taşır (bkz. includes/speak_button.html), böylece aynı
// sayfada farklı dillerdeki kartlar doğru sesle okunur. Tarayıcı desteklemiyorsa düğmeler gizli kalır.
// Ses üretimi cihazda yapılır, sunucuya istek gitmez.
(function () {
    if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') return;

    const buttons = document.querySelectorAll('[data-speak]');
    if (!buttons.length) return;

    const synth = window.speechSynthesis;

    // Sesler bazı tarayıcılarda geç yüklenir; verilen dile (tercihen tam bölge eşleşmesiyle) bir ses seçilir.
    function pickVoice(locale) {
        const voices = synth.getVoices();
        const base = locale.split('-')[0];
        return voices.find((item) => item.lang === locale) || voices.find((item) => item.lang.startsWith(base)) || null;
    }

    function speak(text, locale, button) {
        synth.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = locale;
        utterance.rate = 0.9;
        const voice = pickVoice(locale);
        if (voice) utterance.voice = voice;
        utterance.onstart = () => button.classList.add('is-speaking');
        utterance.onend = utterance.onerror = () => button.classList.remove('is-speaking');
        synth.speak(utterance);
    }

    buttons.forEach((button) => { button.hidden = false; });

    document.addEventListener('click', (event) => {
        const button = event.target.closest('[data-speak]');
        if (button) speak(button.dataset.speak, button.dataset.speakLang || 'en-US', button);
    });

    // Sayfadan ayrılırken ya da kart kaydırılırken okuma sürmesin.
    window.addEventListener('pagehide', () => synth.cancel());
    document.addEventListener('deck:card-moved', () => synth.cancel());
})();
