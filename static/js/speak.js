// Sesli okuma: tarayıcının konuşma sentezi (Web Speech API) ile İngilizce cümleyi okur.
// Tarayıcı desteklemiyorsa okuma düğmeleri gizli kalır. Ses üretimi cihazda yapılır, sunucuya istek gitmez.
(function () {
    if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') return;

    const buttons = document.querySelectorAll('[data-speak]');
    if (!buttons.length) return;

    const synth = window.speechSynthesis;
    let voice = null;

    // Sesler bazı tarayıcılarda geç yüklenir; İngilizce (tercihen ABD) bir ses seçilir.
    function pickVoice() {
        const voices = synth.getVoices();
        voice = voices.find((item) => item.lang === 'en-US') || voices.find((item) => item.lang.startsWith('en')) || null;
    }
    pickVoice();
    if (synth.addEventListener) synth.addEventListener('voiceschanged', pickVoice);

    function speak(text, button) {
        synth.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'en-US';
        utterance.rate = 0.9;
        if (voice) utterance.voice = voice;
        utterance.onstart = () => button.classList.add('is-speaking');
        utterance.onend = utterance.onerror = () => button.classList.remove('is-speaking');
        synth.speak(utterance);
    }

    buttons.forEach((button) => { button.hidden = false; });

    document.addEventListener('click', (event) => {
        const button = event.target.closest('[data-speak]');
        if (button) speak(button.dataset.speak, button);
    });

    // Sayfadan ayrılırken ya da kart kaydırılırken okuma sürmesin.
    window.addEventListener('pagehide', () => synth.cancel());
    document.addEventListener('deck:card-moved', () => synth.cancel());
})();
