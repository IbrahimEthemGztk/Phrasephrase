// Kart yığını: sürükleyerek / düğmeyle / klavyeyle swipe, dokunarak aşamalı gösterim, geri al.
// Kartlar sunucuda render edilir; deck'in çocuk sırası kuyruk sırasıdır (ilk çocuk = üstteki kart).
(function () {
    const root = document.querySelector('[data-deck-root]');
    if (!root) return;

    const deck = root.querySelector('[data-deck]');
    const actions = root.querySelector('[data-actions]');
    const hint = root.querySelector('[data-hint]');
    const doneBox = root.querySelector('[data-done]');
    const remainingEl = root.querySelector('[data-remaining]');
    const learnedEl = root.querySelector('[data-learned-count]');
    const errorBox = root.querySelector('[data-error]');
    const liveRegion = root.querySelector('[data-live]');
    const leftButton = root.querySelector('[data-action="left"]');
    const rightButton = root.querySelector('[data-action="right"]');
    const undoButton = root.querySelector('[data-action="undo"]');

    const csrfToken = root.dataset.csrf;
    const loginUrl = root.dataset.loginUrl;

    const VISIBLE_CARDS = 3;     // yığında görünen kart sayısı
    const COMMIT_RATIO = 0.3;    // kart genişliğinin bu oranından fazla sürüklenirse karar verilir
    const FLING_SPEED = 0.8;     // px/ms: bu hızın üstündeki fırlatma da karar sayılır
    const FLING_MIN_DISTANCE = 60;
    const VELOCITY_WINDOW = 100; // ms: hız, bırakma anından geriye doğru bu pencerede ölçülür
    const VELOCITY_MIN_SPAN = 16; // ms: bundan kısa aralıkta hız güvenilir değildir
    const TAP_MOVE = 8;          // px: bunun altındaki hareket dokunma sayılır
    const TAP_TIME = 400;        // ms
    const REINSERT_MIN = 3;      // sola kaydırılan kart 3-5 kart sonrasına eklenir
    const REINSERT_MAX = 5;
    // Aşamalar: 1 = cümle, 2 = + sesli parçalama, 3 = + hikaye, 4 = + anlam.
    // Amaç hikayeyi değil cümlenin anlamını ezberlemek olduğu için anlam en sona kalır.
    const LAST_STAGE = 4;
    const REVEAL_LABELS = { 1: 'Sesli parçalamayı göster', 2: 'Hikayeyi göster', 3: 'Anlamı göster' };
    const STAGE_ANNOUNCEMENTS = { 2: 'Sesli parçalama gösterildi.', 3: 'Çağrışım hikayesi gösterildi.', 4: 'Anlam gösterildi.' };
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    let learned = Number(root.dataset.learned) || 0;
    let busy = false;        // animasyon veya sunucu isteği sürerken yeni işlem alınmaz
    let lastSwipe = null;    // { card } - yalnızca en son "ezberledim" geri alınabilir; "henüz değil" geri alınamaz
    let drag = null;

    const getCards = () => Array.from(deck.children);
    const randomInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;

    // ---- Görünüm ----

    function setStage(card, stage) {
        card.dataset.stage = stage;
        const button = card.querySelector('[data-reveal]');
        button.hidden = stage >= LAST_STAGE;
        if (stage < LAST_STAGE) button.textContent = REVEAL_LABELS[stage];
    }

    function announce(text) {
        liveRegion.textContent = text;
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
    }

    function clearError() {
        errorBox.hidden = true;
    }

    function layout() {
        const cards = getCards();
        cards.forEach((card, index) => {
            card.dataset.pos = index < VISIBLE_CARDS ? String(index) : 'hidden';
            card.toggleAttribute('inert', index !== 0);
            card.setAttribute('aria-hidden', index === 0 ? 'false' : 'true');
        });

        const empty = cards.length === 0;
        remainingEl.textContent = cards.length;
        learnedEl.textContent = learned;
        deck.hidden = empty;
        hint.hidden = empty;
        doneBox.hidden = !empty;
        // Kart kalmadığında yalnızca "Geri al" görünür kalır (son kart yanlışlıkla kaydırılmış olabilir).
        leftButton.hidden = empty;
        rightButton.hidden = empty;
        actions.classList.toggle('is-finished', empty);
        actions.hidden = empty && !lastSwipe;

        leftButton.disabled = busy || empty;
        rightButton.disabled = busy || empty;
        undoButton.disabled = busy || !lastSwipe;
    }

    function resetCard(card) {
        // Geçişi kapatıp stili sıfırla; yoksa kart ekran dışından geri kayar.
        card.style.transition = 'none';
        card.classList.remove('is-dragging');
        card.style.transform = '';
        card.style.removeProperty('--stamp-right');
        card.style.removeProperty('--stamp-left');
        void card.offsetWidth;
        card.style.transition = '';
    }

    function moveCard(card, dx, width) {
        const strength = Math.min(Math.abs(dx) / (width * COMMIT_RATIO), 1);
        card.style.transform = `translateX(${dx}px) rotate(${(dx / width) * 15}deg)`;
        card.style.setProperty('--stamp-right', dx > 0 ? strength : 0);
        card.style.setProperty('--stamp-left', dx < 0 ? strength : 0);
    }

    function animateTo(card, transform) {
        card.classList.remove('is-dragging');
        card.style.transform = transform;
        if (reduceMotion.matches) return Promise.resolve();
        return new Promise((resolve) => {
            let finished = false;
            const finish = () => {
                if (finished) return;
                finished = true;
                card.removeEventListener('transitionend', onEnd);
                resolve();
            };
            const onEnd = (event) => {
                if (event.target === card && event.propertyName === 'transform') finish();
            };
            card.addEventListener('transitionend', onEnd);
            setTimeout(finish, 400);
        });
    }

    function flyOut(card, direction) {
        const sign = direction === 'right' ? 1 : -1;
        card.style.setProperty('--stamp-right', sign > 0 ? 1 : 0);
        card.style.setProperty('--stamp-left', sign < 0 ? 1 : 0);
        return animateTo(card, `translateX(${sign * window.innerWidth * 1.2}px) rotate(${sign * 20}deg)`);
    }

    async function snapBack(card) {
        card.style.setProperty('--stamp-right', 0);
        card.style.setProperty('--stamp-left', 0);
        await animateTo(card, '');
        card.style.removeProperty('--stamp-right');
        card.style.removeProperty('--stamp-left');
    }

    // ---- Sunucu ----

    let sessionExpired = false;

    async function post(url, direction) {
        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'X-CSRFToken': csrfToken,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
            },
            body: new URLSearchParams({ direction }),
        });
        if (response.status === 401) {
            sessionExpired = true;
            window.location.href = loginUrl;
            throw new Error('Oturum süresi doldu.');
        }
        if (!response.ok) throw new Error(`İstek başarısız (${response.status}).`);
        return response.json();
    }

    function handleFailure() {
        if (sessionExpired) return;
        showError('Kaydedilemedi. Bağlantını kontrol edip tekrar dene.');
    }

    // ---- Swipe ve geri alma ----

    // Kartı kuyruktan çıkarır (sağ) ya da 3-5 kart sonrasına taşır (sol).
    function moveOut(card, direction) {
        const record = { card, direction, stage: Number(card.dataset.stage) };
        deck.removeChild(card);
        if (direction === 'right') {
            learned += 1;
        } else {
            const others = getCards();
            const index = Math.min(randomInt(REINSERT_MIN, REINSERT_MAX), others.length);
            deck.insertBefore(card, others[index] || null);
        }
        setStage(card, 1);
        return record;
    }

    function revertMoveOut(record) {
        if (record.direction === 'right') learned -= 1;
        deck.insertBefore(record.card, deck.firstElementChild);
        setStage(record.card, record.stage);
    }

    async function commit(direction) {
        if (busy) return;
        const card = getCards()[0];
        if (!card) return;

        busy = true;
        clearError();
        layout();

        await flyOut(card, direction);
        const record = moveOut(card, direction);
        resetCard(card);
        layout();

        try {
            await post(card.dataset.swipeUrl, direction);
            // "Henüz değil" geri alınabilir bir işlem sayılmaz; öncekini de geçersiz kılar (yalnızca en son swipe geri alınır).
            lastSwipe = direction === 'right' ? { card } : null;
            const next = getCards()[0];
            announce(
                (direction === 'right' ? 'Ezberledim olarak işaretlendi. ' : 'Henüz değil olarak işaretlendi. ') +
                (next ? `Sıradaki kart: ${next.dataset.title}` : 'Tüm kartlar tamamlandı.')
            );
        } catch (error) {
            revertMoveOut(record);
            handleFailure();
        } finally {
            busy = false;
            layout();
        }
    }

    // "Ezberledim"i geri alır: kart kuyruğun başına döner, öğrenildi işareti kalkar.
    async function undo() {
        if (busy || !lastSwipe) return;
        const { card } = lastSwipe;

        busy = true;
        clearError();

        learned -= 1;
        deck.insertBefore(card, deck.firstElementChild);
        setStage(card, 1);
        layout();

        try {
            await post(card.dataset.undoUrl, 'right');
            lastSwipe = null;
            announce(`Geri alındı. Kart: ${card.dataset.title}`);
        } catch (error) {
            learned += 1;
            deck.removeChild(card);
            handleFailure();
        } finally {
            busy = false;
            layout();
        }
    }

    function reveal() {
        const card = getCards()[0];
        if (!card) return;
        const stage = Number(card.dataset.stage);
        if (stage >= LAST_STAGE) return;
        setStage(card, stage + 1);
        announce(STAGE_ANNOUNCEMENTS[stage + 1]);
    }

    // ---- Sürükleme (fare + dokunma) ----

    deck.addEventListener('pointerdown', (event) => {
        if (busy || (event.pointerType === 'mouse' && event.button !== 0)) return;
        const card = event.target.closest('.study-card');
        if (!card || card !== getCards()[0] || event.target.closest('button, a')) return;

        drag = {
            card,
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            startTime: performance.now(),
            samples: [],
            dx: 0,
            width: card.offsetWidth,
            active: false,
        };
    });

    // Bırakma anındaki yatay hız (px/ms): yalnızca son VELOCITY_WINDOW ms'deki örnekler sayılır.
    // Parmağı durdurup bırakmak ya da tek bir anlık örnek fırlatma sayılmaz.
    function releaseVelocity(samples) {
        const now = performance.now();
        const recent = samples.filter((sample) => now - sample.time <= VELOCITY_WINDOW);
        if (recent.length < 2) return 0;
        const first = recent[0];
        const last = recent[recent.length - 1];
        const span = last.time - first.time;
        return span >= VELOCITY_MIN_SPAN ? (last.x - first.x) / span : 0;
    }

    deck.addEventListener('pointermove', (event) => {
        if (!drag || event.pointerId !== drag.pointerId) return;

        const dx = event.clientX - drag.startX;
        const dy = event.clientY - drag.startY;

        if (!drag.active) {
            // Dikey hareket sayfanın kaydırmasına bırakılır; yalnızca yatay niyette sürüklemeye başlanır.
            if (Math.abs(dx) < TAP_MOVE || Math.abs(dx) < Math.abs(dy)) return;
            drag.active = true;
            drag.card.classList.add('is-dragging');
            try {
                drag.card.setPointerCapture(event.pointerId);
            } catch (error) { /* yakalama desteklenmiyorsa sürükleme yine çalışır */ }
        }

        drag.samples.push({ x: event.clientX, time: performance.now() });
        if (drag.samples.length > 20) drag.samples.shift();
        drag.dx = dx;
        moveCard(drag.card, dx, drag.width);
    });

    function endDrag(event) {
        if (!drag || event.pointerId !== drag.pointerId) return;
        const current = drag;
        drag = null;
        const released = event.type === 'pointerup';

        if (!current.active) {
            const moved = Math.hypot(event.clientX - current.startX, event.clientY - current.startY);
            if (released && moved < TAP_MOVE && performance.now() - current.startTime < TAP_TIME) reveal();
            return;
        }

        const velocity = releaseVelocity(current.samples);
        const farEnough = Math.abs(current.dx) > current.width * COMMIT_RATIO;
        const flung = Math.abs(velocity) > FLING_SPEED && Math.abs(current.dx) > FLING_MIN_DISTANCE;
        if (released && (farEnough || flung)) {
            const sign = farEnough ? Math.sign(current.dx) : Math.sign(velocity);
            commit(sign > 0 ? 'right' : 'left');
        } else {
            snapBack(current.card);
        }
    }

    deck.addEventListener('pointerup', endDrag);
    deck.addEventListener('pointercancel', endDrag);
    deck.addEventListener('dragstart', (event) => event.preventDefault());

    // ---- Düğmeler ve klavye ----

    root.addEventListener('click', (event) => {
        if (event.target.closest('[data-reveal]')) {
            reveal();
            return;
        }
        const button = event.target.closest('[data-action]');
        if (!button) return;
        if (button.dataset.action === 'undo') undo();
        else commit(button.dataset.action);
    });

    document.addEventListener('keydown', (event) => {
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        const target = event.target instanceof Element ? event.target : document.body;
        if (target.closest('input, textarea, select, [contenteditable]')) return;

        if (event.key === 'ArrowRight') {
            event.preventDefault();
            commit('right');
        } else if (event.key === 'ArrowLeft') {
            event.preventDefault();
            commit('left');
        } else if (event.key === 'ArrowDown' || ((event.key === ' ' || event.key === 'Enter') && !target.closest('button, a'))) {
            event.preventDefault();
            reveal();
        }
    });

    // ---- Başlangıç ----

    getCards().forEach((card) => setStage(card, 1));
    layout();
})();
