// Phrase formu: dinamik kelime / ses karşılığı satırları.
// Sıra numarası burada yalnızca görsel amaçlıdır; kayıtta sıra sunucuda satır sırasından üretilir.
(function () {
    const form = document.querySelector('[data-phrase-form]');
    if (!form) return;

    const MAX_ROWS = 30;
    const rowsBox = form.querySelector('[data-rows]');
    const template = form.querySelector('[data-row-template]');
    const addButton = form.querySelector('[data-add-row]');
    const splitButton = form.querySelector('[data-split]');
    const phraseInput = form.querySelector('[name="original_phrase"]');

    const getRows = () => Array.from(rowsBox.querySelectorAll('[data-row]'));

    function refresh() {
        const rows = getRows();
        rows.forEach((row, index) => {
            row.querySelector('[data-number]').textContent = index + 1;
            row.querySelector('[data-remove]').disabled = rows.length === 1;
        });
        addButton.disabled = rows.length >= MAX_ROWS;
    }

    function addRow(word = '', hint = '') {
        const row = template.content.firstElementChild.cloneNode(true);
        row.querySelector('[name="original_word"]').value = word;
        row.querySelector('[name="sound_hint"]').value = hint;
        rowsBox.appendChild(row);
        refresh();
        return row;
    }

    addButton.addEventListener('click', () => {
        addRow().querySelector('[name="original_word"]').focus();
    });

    rowsBox.addEventListener('click', (event) => {
        const removeButton = event.target.closest('[data-remove]');
        if (!removeButton || getRows().length === 1) return;
        removeButton.closest('[data-row]').remove();
        refresh();
    });

    // Orijinal cümleyi boşluklardan bölüp kelime kutularını doldurur.
    // Aynı sıradaki mevcut ses karşılıkları korunur.
    splitButton.addEventListener('click', () => {
        const words = phraseInput.value.trim().split(/\s+/).filter(Boolean).slice(0, MAX_ROWS);
        if (!words.length) {
            phraseInput.focus();
            return;
        }
        const hints = getRows().map((row) => row.querySelector('[name="sound_hint"]').value);
        rowsBox.replaceChildren();
        words.forEach((word, index) => addRow(word, hints[index] || ''));
        rowsBox.querySelector('[name="sound_hint"]').focus();
    });

    refresh();
})();
