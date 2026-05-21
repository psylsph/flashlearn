// ── State ────────────────────────────────────────────────────
let currentDeckId = null;
let studyCards = [];
let studyIndex = 0;
let studyCorrect = 0;
let selectedFile = null;
let currentCard = null;
let studyStartTime = 0;
let currentView = 'home';

// ── API Helpers ──────────────────────────────────────────────
async function api(url, opts = {}) {
    const res = await fetch(url, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ error: 'Request failed' }));
        throw new Error(err.error || `HTTP ${res.status}`);
    }
    return res.json();
}

// ── View Management ──────────────────────────────────────────
function showView(name) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const el = document.getElementById(`view-${name}`);
    if (el) el.classList.add('active');
    currentView = name;
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navMap = { home: 'nav-home', upload: 'nav-upload', achievements: 'nav-achievements' };
    const navEl = document.getElementById(navMap[name]);
    if (navEl) navEl.classList.add('active');
    if (name === 'home') loadHome();
    if (name === 'achievements') loadAchievements();
    if (name === 'settings') loadSettings();
    if (name === 'upload') resetUpload();
}

// ── Toast ────────────────────────────────────────────────────
function showToast(msg, type = 'success', duration = 2500) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = `toast toast-${type} show`;
    setTimeout(() => t.classList.remove('show'), duration);
}

// ── Loading ──────────────────────────────────────────────────
function showLoading(text, sub) {
    document.getElementById('loading-text').textContent = text || 'Loading...';
    document.getElementById('loading-sub').textContent = sub || '';
    document.getElementById('loading-overlay').style.display = 'flex';
}
function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
}

// ── Home ─────────────────────────────────────────────────────
async function loadHome() {
    try {
        const [progress, decks] = await Promise.all([
            api('/api/progress'),
            api('/api/decks'),
        ]);
        const level = progress.level;
        const xpInLevel = progress.total_xp - progress.xp_current_level;
        const xpNeeded = progress.xp_next_level - progress.xp_current_level;
        const pct = xpNeeded > 0 ? Math.min(100, (xpInLevel / xpNeeded) * 100) : 100;

        document.getElementById('stat-level').textContent = level;
        document.getElementById('stat-streak').textContent = progress.current_streak;
        document.getElementById('stat-reviewed').textContent = progress.total_cards_reviewed;
        document.getElementById('stat-xp').textContent = progress.total_xp;
        document.getElementById('xp-bar').style.width = pct + '%';

        const list = document.getElementById('deck-list');
        if (decks.decks.length === 0) {
            list.innerHTML = `<div class="empty-state"><div class="icon">📸</div><div class="text">No decks yet!<br>Tap the camera button to snap your notes and create your first deck.</div></div>`;
            return;
        }
        list.innerHTML = decks.decks.map(d => `
            <div class="deck-card" onclick="openDeck(${d.id})">
                <div class="deck-name">${esc(d.name)}</div>
                ${d.subject ? `<div class="deck-subject">${esc(d.subject)}</div>` : ''}
                <div class="deck-meta">
                    <span>🃏 ${d.card_count} cards</span>
                    ${d.due_count > 0 ? `<span class="badge badge-due">${d.due_count} due</span>` : ''}
                    ${d.mastered_count > 0 ? `<span class="badge badge-mastered">${d.mastered_count} mastered</span>` : ''}
                </div>
            </div>`).join('');
    } catch (e) { console.error(e); }
}

// ── Upload ───────────────────────────────────────────────────
function resetUpload() {
    selectedFile = null;
    document.getElementById('file-input').value = '';
    document.getElementById('deck-name-input').value = '';
    document.getElementById('upload-btn').disabled = true;
    const zone = document.getElementById('upload-zone');
    zone.classList.remove('has-image');
    zone.innerHTML = `<div class="icon">📷</div><div class="text">Tap to take a photo or upload an image of your notes</div>`;
}

function handleFileSelect(e) {
    const file = e.target.files[0];
    if (!file) return;
    selectedFile = file;
    const zone = document.getElementById('upload-zone');
    zone.classList.add('has-image');
    const reader = new FileReader();
    reader.onload = (ev) => { zone.innerHTML = `<img src="${ev.target.result}" alt="Preview">`; };
    reader.readAsDataURL(file);
    document.getElementById('upload-btn').disabled = false;
}

async function uploadImage() {
    if (!selectedFile) return;
    showLoading('Processing image...', 'AI is reading your notes and creating flashcards');
    const formData = new FormData();
    formData.append('photo', selectedFile);
    formData.append('deck_name', document.getElementById('deck-name-input').value.trim());
    try {
        const result = await api('/api/upload', { method: 'POST', body: formData });
        hideLoading();
        currentDeckId = result.deck.id;
        showToast(`Created "${result.deck.name}" with ${result.cards.length} cards!`, 'success');
        openDeck(result.deck.id);
    } catch (e) {
        hideLoading();
        showToast(e.message, 'error', 4000);
    }
}

// ── Deck View ────────────────────────────────────────────────
async function openDeck(deckId) {
    currentDeckId = deckId;
    showView('deck');
    try {
        const data = await api(`/api/decks/${deckId}`);
        const deck = data.deck;
        document.getElementById('deck-title').textContent = deck.name;
        const dueCount = deck.due_count || 0;
        const masteredCount = deck.mastered_count || 0;
        document.getElementById('deck-info-card').innerHTML = `
            ${deck.subject ? `<div class="deck-subject" style="margin-bottom:4px;">${esc(deck.subject)}</div>` : ''}
            ${deck.description ? `<div class="text-sm text-muted" style="margin-bottom:8px;">${esc(deck.description)}</div>` : ''}
            <div class="deck-meta">
                <span>🃏 ${deck.card_count} cards</span>
                ${dueCount > 0 ? `<span class="badge badge-due">${dueCount} due</span>` : ''}
                ${masteredCount > 0 ? `<span class="badge badge-mastered">${masteredCount} mastered</span>` : ''}
            </div>`;
        const list = document.getElementById('card-list');
        if (data.cards.length === 0) {
            list.innerHTML = '<div class="empty-state"><div class="text">No cards yet</div></div>';
            return;
        }
        list.innerHTML = data.cards.map(c => `
            <div class="card-item">
                <div class="q">${esc(c.question)}</div>
                <span class="type-badge">${c.card_type.replace('_', ' ')}</span>
                <button class="delete-btn" onclick="deleteCard(${c.id}, event)">🗑️</button>
            </div>`).join('');
        document.getElementById('study-btn').textContent = dueCount > 0 ? `📖 Study ${dueCount} due cards` : '📖 Practice all cards';
    } catch (e) { showToast(e.message, 'error'); }
}

async function deleteCard(cardId, e) {
    e.stopPropagation();
    if (!confirm('Delete this card?')) return;
    try {
        await api(`/api/cards/${cardId}`, { method: 'DELETE' });
        openDeck(currentDeckId);
    } catch (e) { showToast(e.message, 'error'); }
}

function confirmDeleteDeck() {
    if (confirm('Delete this entire deck and all its cards?')) deleteCurrentDeck();
}

async function deleteCurrentDeck() {
    try {
        await api(`/api/decks/${currentDeckId}`, { method: 'DELETE' });
        showToast('Deck deleted', 'success');
        showView('home');
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Study Mode ───────────────────────────────────────────────
async function startStudy() {
    showView('study');
    studyIndex = 0;
    studyCorrect = 0;
    studyStartTime = Date.now();
    try {
        const data = await api(`/api/decks/${currentDeckId}/study`);
        studyCards = data.cards;
        if (studyCards.length === 0) {
            showToast('No cards to study!', 'error');
            showView('deck');
            return;
        }
        renderStudyCard();
    } catch (e) {
        showToast(e.message, 'error');
        showView('deck');
    }
}

function renderStudyCard() {
    if (studyIndex >= studyCards.length) { finishStudy(); return; }
    currentCard = studyCards[studyIndex];
    const pct = (studyIndex / studyCards.length) * 100;
    document.getElementById('study-progress-fill').style.width = pct + '%';
    document.getElementById('study-count').textContent = `${studyIndex + 1}/${studyCards.length}`;
    const area = document.getElementById('study-card-area');
    if (currentCard.card_type === 'multiple_choice') renderMultipleChoice(area);
    else if (currentCard.card_type === 'fill_blank') renderFillBlank(area);
    else renderFlashcard(area);
}

function renderFlashcard(area) {
    area.innerHTML = `
        <div class="flashcard" onclick="this.querySelector('.flashcard-inner').classList.toggle('flipped')">
            <div class="flashcard-inner">
                <div class="flashcard-front"><div class="question">${esc(currentCard.question)}</div><div class="hint">Tap to flip</div></div>
                <div class="flashcard-back"><div class="card-type-label">Answer</div><div class="answer">${esc(currentCard.answer)}</div></div>
            </div>
        </div>`;
    document.getElementById('study-actions').innerHTML = `
        <button class="btn btn-danger" onclick="markCard(false)">❌ Didn't Know</button>
        <button class="btn btn-success" onclick="markCard(true)">✅ Got It!</button>`;
    document.getElementById('study-actions').style.display = 'flex';
}

function renderMultipleChoice(area) {
    const options = [...(currentCard.options || [])];
    if (!options.includes(currentCard.answer)) options.push(currentCard.answer);
    for (let i = options.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [options[i], options[j]] = [options[j], options[i]];
    }
    area.innerHTML = `
        <div class="flashcard" style="cursor:default"><div class="flashcard-inner" style="transform:none">
            <div class="flashcard-front" style="position:relative;min-height:120px;"><div class="question">${esc(currentCard.question)}</div></div>
        </div></div>
        <div class="mc-options">${options.map(o => `
            <div class="mc-option" onclick="selectMcOption(this, '${escAttr(o)}')">${esc(o)}</div>`).join('')}
        </div>`;
    document.getElementById('study-actions').style.display = 'none';
}

function selectMcOption(el, selected) {
    const options = document.querySelectorAll('.mc-option');
    if (el.classList.contains('correct') || el.classList.contains('wrong')) return;
    options.forEach(o => {
        o.style.pointerEvents = 'none';
        if (o.textContent === currentCard.answer) o.classList.add('correct');
    });
    if (selected === currentCard.answer) {
        el.classList.add('correct');
        setTimeout(() => markCard(true), 800);
    } else {
        el.classList.add('wrong');
        setTimeout(() => markCard(false), 1200);
    }
}

function renderFillBlank(area) {
    area.innerHTML = `
        <div class="flashcard" style="cursor:default"><div class="flashcard-inner" style="transform:none">
            <div class="flashcard-front" style="position:relative;min-height:120px;"><div class="question">${esc(currentCard.question)}</div></div>
        </div></div>
        <input type="text" class="type-answer-input" id="type-answer" placeholder="Type your answer..." onkeydown="if(event.key==='Enter')checkTypedAnswer()">
        <div id="type-answer-feedback"></div>`;
    document.getElementById('study-actions').innerHTML = `<button class="btn btn-primary" onclick="checkTypedAnswer()">Submit</button>`;
    document.getElementById('study-actions').style.display = 'flex';
    setTimeout(() => document.getElementById('type-answer')?.focus(), 100);
}

function checkTypedAnswer() {
    const input = document.getElementById('type-answer');
    if (!input) return;
    const typed = input.value.trim().toLowerCase();
    const correct = currentCard.answer.trim().toLowerCase();
    const feedback = document.getElementById('type-answer-feedback');
    const isCorrect = typed === correct || correct.includes(typed) || typed.includes(correct);
    if (isCorrect) {
        feedback.className = 'type-answer-feedback correct';
        feedback.textContent = `✅ Correct! "${currentCard.answer}"`;
        input.disabled = true;
        setTimeout(() => markCard(true), 1000);
    } else {
        feedback.className = 'type-answer-feedback wrong';
        feedback.textContent = `❌ The answer was: ${currentCard.answer}`;
        input.disabled = true;
        setTimeout(() => markCard(false), 1500);
    }
}

async function markCard(correct) {
    const timeMs = Date.now() - studyStartTime;
    studyStartTime = Date.now();
    if (correct) studyCorrect++;
    try {
        const result = await api(`/api/cards/${currentCard.id}/review?correct=${correct}&time_ms=${timeMs}`, { method: 'POST' });
        if (result.xp_earned) showToast(`+${result.xp_earned} XP`, 'xp', 1500);
    } catch (e) { console.error(e); }
    studyIndex++;
    renderStudyCard();
}

async function finishStudy() {
    try {
        const result = await api(`/api/session/complete?deck_id=${currentDeckId}&correct_count=${studyCorrect}&total_count=${studyCards.length}`, { method: 'POST' });
        const pct = studyCards.length > 0 ? Math.round((studyCorrect / studyCards.length) * 100) : 0;
        let emoji = '🎉';
        if (pct === 100) emoji = '🏆';
        else if (pct >= 80) emoji = '🌟';
        else if (pct >= 60) emoji = '👍';
        else emoji = '💪';
        document.getElementById('results-emoji').textContent = emoji;
        document.getElementById('results-score').textContent = `${studyCorrect}/${studyCards.length}`;
        document.getElementById('results-label').textContent = `${pct}% Correct`;
        document.getElementById('results-xp').textContent = `+${result.bonus_xp} XP`;
        document.getElementById('results-streak').textContent = result.streak > 0 ? `${result.streak} day streak 🔥` : '';
        showView('results');
    } catch (e) { showToast(e.message, 'error'); }
}

function confirmQuitStudy() {
    if (studyIndex > 0 && studyIndex < studyCards.length) {
        if (!confirm('Quit study session? Progress will be saved.')) return;
    }
    if (currentDeckId) openDeck(currentDeckId);
    else showView('home');
}

// ── Achievements ─────────────────────────────────────────────
async function loadAchievements() {
    try {
        const data = await api('/api/achievements');
        const list = document.getElementById('achievement-list');
        const unlocked = data.achievements.filter(a => a.unlocked_at).length;
        list.innerHTML = `<div class="text-center text-muted text-sm mb-16">${unlocked}/${data.achievements.length} unlocked</div>` +
            data.achievements.map(a => `
            <div class="achievement ${a.unlocked_at ? '' : 'locked'}">
                <div class="ach-icon">${a.icon}</div>
                <div class="info">
                    <div class="ach-name">${esc(a.name)}</div>
                    <div class="ach-desc">${esc(a.description)}</div>
                    ${a.unlocked_at ? '<div class="ach-date">Unlocked!</div>' : ''}
                </div>
            </div>`).join('');
    } catch (e) { console.error(e); }
}

// ── Settings ─────────────────────────────────────────────────
async function loadSettings() {
    try {
        const [settings, status] = await Promise.all([api('/api/settings'), api('/api/status')]);
        const select = document.getElementById('model-select');
        if (status.models && status.models.length > 0) {
            select.innerHTML = status.models.map(m =>
                `<option value="${m}" ${m === settings.model ? 'selected' : ''}>${m}</option>`).join('');
        }
        const statusEl = document.getElementById('ollama-status');
        if (status.running) {
            statusEl.innerHTML = `<span style="color:var(--success);">● Connected</span> — ${status.models.length} models available`;
        } else {
            statusEl.innerHTML = '<span style="color:var(--error);">● Not connected</span> — Is Ollama running?';
        }
    } catch (e) { console.error(e); }
}

async function saveModel() {
    const model = document.getElementById('model-select').value;
    try {
        await api(`/api/settings?model=${encodeURIComponent(model)}`, { method: 'PUT' });
        showToast(`Model set to ${model}`, 'success');
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Utilities ────────────────────────────────────────────────
function esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
}
function escAttr(str) { return (str || '').replace(/'/g, "\\'").replace(/"/g, '&quot;'); }

// ── Init ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => { loadHome(); });
