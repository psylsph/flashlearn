// ── State ────────────────────────────────────────────────────
let currentDeckId = null;
let currentFolderId = null;
let currentFolderName = '';
let studyCards = [];
let studyIndex = 0;
let studyCorrect = 0;
let selectedFiles = [];
let currentCard = null;
let studySessionId = null;
let studyStartTime = 0;
let currentView = 'home';
let deckCameFromFolder = false;
let thumbnailUrls = [];
let reviewInFlight = false;
let finishInFlight = false;

const FOLDER_ICONS = [
    '📁', '📚', '🧪', '🔬', '🧬', '📐', '🧮', '🌍',
    '🏛️', '⚔️', '🎨', '🎵', '💻', '🚀', '🧠', '📝',
    '🌿', '⚡', '🔥', '💎', '🎯', '🏆', '🌟', '❤️',
];

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
    if (name === 'home') { loadHome(); currentFolderId = null; }
    if (name === 'achievements') loadAchievements();
    if (name === 'settings') loadSettings();
    if (name === 'upload') resetUpload();
    if (name === 'create-folder') initFolderCreator();
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
    // Remove any old progress line
    const old = document.getElementById('loading-progress');
    if (old) old.remove();
    document.getElementById('loading-overlay').style.display = 'flex';
}

function hideLoading() {
    document.getElementById('loading-overlay').style.display = 'none';
}

// ── Home ─────────────────────────────────────────────────────
async function loadHome() {
    try {
        const [progress, folders, unassigned] = await Promise.all([
            api('/api/progress'),
            api('/api/folders'),
            api('/api/decks/unassigned'),
        ]);

        // Stats
        const level = progress.level;
        const xpInLevel = progress.total_xp - progress.xp_current_level;
        const xpNeeded = progress.xp_next_level - progress.xp_current_level;
        const pct = xpNeeded > 0 ? Math.min(100, (xpInLevel / xpNeeded) * 100) : 100;
        document.getElementById('stat-level').textContent = level;
        document.getElementById('stat-streak').textContent = progress.current_streak;
        document.getElementById('stat-reviewed').textContent = progress.total_cards_reviewed;
        document.getElementById('stat-xp').textContent = progress.total_xp;
        document.getElementById('xp-bar').style.width = pct + '%';

        const content = document.getElementById('home-content');
        let html = '';

        // Folders section
        if (folders.folders.length > 0) {
            html += `<div class="section-title">Subjects</div>`;
            html += `<div class="folder-grid">`;
            for (const f of folders.folders) {
                html += `
                    <div class="folder-card" style="--fc:${safeColor(f.color)}" onclick="openFolder(${f.id})">
                        <button class="btn-icon btn-sm-icon edit-btn" onclick="event.stopPropagation(); editFolderIcon(${f.id})" title="Change icon" aria-label="Change icon for ${escAttr(f.name)}">✏️</button>
                        <div class="folder-icon">${esc(f.icon)}</div>
                        <div class="folder-name">${esc(f.name)}</div>
                        <div class="folder-meta">${f.deck_count} decks · ${f.card_count} cards</div>
                    </div>`;
            }
            html += `
                <div class="add-folder-card" onclick="showView('create-folder')">
                    <div class="icon">➕</div>
                    <div class="text">New Folder</div>
                </div>`;
            html += `</div>`;
        } else {
            html += `
                <div class="folder-grid">
                    <div class="add-folder-card" onclick="showView('create-folder')">
                        <div class="icon">➕</div>
                        <div class="text">New Subject Folder</div>
                    </div>
                </div>`;
        }

        // Unassigned decks
        if (unassigned.decks.length > 0) {
            html += `<div class="section-title">Uncategorized Decks</div>`;
            html += `<div class="deck-list">`;
            for (const d of unassigned.decks) {
                html += renderDeckCard(d);
            }
            html += `</div>`;
        }

        content.innerHTML = html;
    } catch (e) { console.error(e); }
}

function renderDeckCard(d) {
    return `
        <div class="deck-card" onclick="openDeck(${d.id})">
            <div class="deck-card-top">
                <div class="deck-name">${esc(d.name)}</div>
                <button class="btn-icon btn-sm-icon" onclick="event.stopPropagation(); showMovePicker(${d.id})" title="Move to folder">📁</button>
            </div>
            ${d.subject ? `<div class="deck-subject">${esc(d.subject)}</div>` : ''}
            <div class="deck-meta">
                <span>🃏 ${d.card_count} cards</span>
                ${d.due_count > 0 ? `<span class="badge badge-due">${d.due_count} due</span>` : ''}
                ${d.mastered_count > 0 ? `<span class="badge badge-mastered">${d.mastered_count} mastered</span>` : ''}
            </div>
        </div>`;
}

// ── Folders ──────────────────────────────────────────────────
async function openFolder(folderId) {
    currentFolderId = folderId;
    deckCameFromFolder = true;
    showView('folder');

    try {
        const [folder, decks] = await Promise.all([
            api('/api/folders'),  // get all, pick ours
            api(`/api/decks?folder_id=${folderId}`),
        ]);

        const f = folder.folders.find(x => x.id === folderId);
        if (!f) { showView('home'); return; }

        currentFolderName = f.name;
        document.getElementById('folder-title').textContent = `${f.icon || '📁'} ${f.name}`;

        const list = document.getElementById('folder-deck-list');
        if (decks.decks.length === 0) {
            list.innerHTML = `<div class="empty-state">
                <div class="icon">📸</div>
                <div class="text">No decks in this folder yet.<br>Tap the camera button to add one.</div>
            </div>`;
            return;
        }

        list.innerHTML = decks.decks.map(d => renderDeckCard(d)).join('');
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function confirmDeleteFolder() {
    if (confirm(`Delete "${currentFolderName}" folder? Decks inside will be moved to uncategorized.`)) {
        deleteFolder();
    }
}

async function deleteFolder() {
    try {
        await api(`/api/folders/${currentFolderId}`, { method: 'DELETE' });
        showToast('Folder deleted', 'success');
        showView('home');
    } catch (e) { showToast(e.message, 'error'); }
}

function initFolderCreator() {
    document.getElementById('folder-name-input').value = '';
    const grid = document.getElementById('icon-grid');
    grid.innerHTML = FOLDER_ICONS.map((icon, i) =>
        `<div class="icon-option ${i === 0 ? 'selected' : ''}" onclick="selectIcon(this)" data-icon="${escAttr(icon)}">${esc(icon)}</div>`
    ).join('');
}

function selectIcon(el) {
    document.querySelectorAll('.icon-option').forEach(o => o.classList.remove('selected'));
    el.classList.add('selected');
}

async function createFolder() {
    const name = document.getElementById('folder-name-input').value.trim();
    if (!name) { showToast('Please enter a folder name', 'error'); return; }

    const selected = document.querySelector('.icon-option.selected');
    const icon = selected ? selected.dataset.icon : '📁';

    try {
        await api('/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `name=${encodeURIComponent(name)}&icon=${encodeURIComponent(icon)}`,
        });
        showToast(`Created "${name}" folder`, 'success');
        showView('home');
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Edit Folder Icon ─────────────────────────────────────────
async function editFolderIcon(folderId) {
    try {
        const { folders } = await api('/api/folders');
        const folder = folders.find(f => f.id === folderId);
        if (!folder) { showToast('Folder not found', 'error'); return; }

        closeFolderIconPicker();
        const overlay = document.createElement('div');
        overlay.id = 'icon-picker-overlay';
        overlay.className = 'move-picker-overlay';
        overlay.innerHTML = `
            <div class="move-picker">
                <div class="move-picker-title">Change icon · ${esc(folder.name)}</div>
                <div class="icon-grid" style="margin:4px 16px 12px;">
                    ${FOLDER_ICONS.map(icon =>
                        `<div class="icon-option ${esc(icon) === esc(folder.icon) ? 'selected' : ''}"
                              data-icon="${escAttr(icon)}" role="button" aria-label="Pick icon ${escAttr(icon)}">${esc(icon)}</div>`
                    ).join('')}
                </div>
                <div class="move-picker-option move-picker-cancel" onclick="closeFolderIconPicker()">Cancel</div>
            </div>`;

        // Click outside the sheet, or on an icon, or Cancel
        overlay.addEventListener('click', (e) => {
            const option = e.target.closest('.icon-option');
            if (option) {
                option.parentElement.querySelector('.selected')?.classList.remove('selected');
                option.classList.add('selected');
                saveFolderIcon(folder.id, option.dataset.icon);
                return;
            }
            if (e.target === overlay) closeFolderIconPicker();
        });
        document.body.appendChild(overlay);
    } catch (e) { showToast(e.message, 'error'); }
}

function closeFolderIconPicker() {
    document.getElementById('icon-picker-overlay')?.remove();
}

async function saveFolderIcon(folderId, icon) {
    try {
        await api(`/api/folders/${folderId}?icon=${encodeURIComponent(icon)}`, { method: 'PUT' });
        closeFolderIconPicker();
        showToast('Icon updated', 'success');
        if (currentView === 'folder' && currentFolderId) openFolder(currentFolderId);
        else if (currentView === 'home') loadHome();
    } catch (e) { showToast(e.message, 'error'); }
}

// ── Move Deck to Folder ──────────────────────────────────────
async function showMovePicker(deckId) {
    try {
        const data = await api('/api/folders');
        const folders = data.folders;
        if (folders.length === 0) {
            showToast('Create a folder first', 'error');
            return;
        }

        // Build a simple picker overlay
        let existing = document.getElementById('move-picker-overlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'move-picker-overlay';
        overlay.className = 'move-picker-overlay';
        overlay.innerHTML = `
            <div class="move-picker">
                <div class="move-picker-title">Move to folder</div>
                <div class="move-picker-option" onclick="moveDeck(${deckId}, null)">
                    <span>📂</span> <span>No folder</span>
                </div>
                ${folders.map(f => `
                    <div class="move-picker-option" onclick="moveDeck(${deckId}, ${f.id})">
                        <span>${esc(f.icon)}</span> <span>${esc(f.name)}</span>
                    </div>`).join('')}
                <div class="move-picker-option move-picker-cancel" onclick="closeMovePicker()">Cancel</div>
            </div>`;
        document.body.appendChild(overlay);
    } catch (e) { showToast(e.message, 'error'); }
}

async function moveDeck(deckId, folderId) {
    closeMovePicker();
    try {
        const params = folderId !== null ? `?folder_id=${folderId}` : '';
        await api(`/api/decks/${deckId}/move${params}`, { method: 'PUT' });
        showToast('Deck moved!', 'success');
        // Refresh whatever view we're on
        if (currentView === 'home') loadHome();
        else if (currentView === 'folder' && currentFolderId) openFolder(currentFolderId);
    } catch (e) { showToast(e.message, 'error'); }
}

function closeMovePicker() {
    const el = document.getElementById('move-picker-overlay');
    if (el) el.remove();
}

// ── Upload ───────────────────────────────────────────────────
function resetUpload() {
    revokeThumbnailUrls();
    selectedFiles = [];
    document.getElementById('file-input').value = '';
    document.getElementById('deck-name-input').value = '';
    document.getElementById('upload-btn').disabled = true;
    document.getElementById('thumb-strip').innerHTML = '';
    const zone = document.getElementById('upload-zone');
    zone.classList.remove('has-image');
    zone.innerHTML = `
        <div class="icon">📷</div>
        <div class="text">Click to select photos or PDFs of your notes</div>
        <div class="text text-sm" style="margin-top:4px;">Images and PDF files supported</div>`;
    loadFolderSelect();
}

async function loadFolderSelect() {
    try {
        const folders = await api('/api/folders');
        const select = document.getElementById('folder-select');
        select.innerHTML = '<option value="">No folder (uncategorized)</option>';
        for (const f of folders.folders) {
            const sel = (currentFolderId && f.id === currentFolderId) ? ' selected' : '';
            select.innerHTML += `<option value="${f.id}"${sel}>${esc(f.icon)} ${esc(f.name)}</option>`;
        }
    } catch (e) { console.error(e); }
}

function handleFileSelect(e) {
    const files = Array.from(e.target.files);
    if (!files.length) return;

    for (const file of files) {
        // Avoid duplicates
        if (!selectedFiles.find(f => f.name === file.name && f.size === file.size)) {
            selectedFiles.push(file);
        }
    }

    renderThumbnails();
    document.getElementById('upload-btn').disabled = selectedFiles.length === 0;
}

function renderThumbnails() {
    revokeThumbnailUrls();
    const strip = document.getElementById('thumb-strip');
    strip.innerHTML = selectedFiles.map((file, i) => {
        const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
        const url = isPdf ? '' : URL.createObjectURL(file);
        if (url) thumbnailUrls.push(url);
        const preview = isPdf
            ? `<div class="thumb-pdf"><span>📄</span><small>${esc(file.name)}</small></div>`
            : `<img src="${url}" alt="Preview">`;
        return `
            <div class="thumb-item" id="thumb-${i}">
                ${preview}
                <button class="thumb-remove" onclick="removeThumb(${i})">✕</button>
            </div>`;
    }).join('');

    // Update upload zone
    const zone = document.getElementById('upload-zone');
    if (selectedFiles.length > 0) {
        zone.innerHTML = `
            <div class="icon">📷</div>
            <div class="text">${selectedFiles.length} file${selectedFiles.length > 1 ? 's' : ''} selected — click to add more</div>`;
    }
}

function removeThumb(index) {
    selectedFiles.splice(index, 1);
    renderThumbnails();
    document.getElementById('upload-btn').disabled = selectedFiles.length === 0;
    if (selectedFiles.length === 0) {
        const zone = document.getElementById('upload-zone');
        zone.innerHTML = `
            <div class="icon">📷</div>
            <div class="text">Click to select photos or PDFs of your notes</div>
            <div class="text text-sm" style="margin-top:4px;">Images and PDF files supported</div>`;
    }
}

async function uploadImages() {
    if (!selectedFiles.length) return;

    const total = selectedFiles.length;
    const folderId = document.getElementById('folder-select').value;

    if (total === 1) {
        // Single image - use original simple flow
        showLoading('Processing image...', 'AI is reading your notes and creating flashcards');
    } else {
        showLoading(`Processing ${total} images...`, 'AI is reading your notes and creating flashcards');
    }

    const formData = new FormData();
    for (const file of selectedFiles) {
        formData.append('photos', file);
    }
    formData.append('deck_name', document.getElementById('deck-name-input').value.trim());
    if (folderId) formData.append('folder_id', folderId);

    try {
        const result = await api('/api/upload', { method: 'POST', body: formData });
        hideLoading();
        currentDeckId = result.deck.id;
        deckCameFromFolder = !!folderId;
        currentFolderId = folderId ? parseInt(folderId) : null;

        let msg = `Created "${result.deck.name}" with ${result.cards.length} cards!`;
        if (result.images_processed > 1) {
            msg = `Processed ${result.images_processed} images — ${result.cards.length} cards created!`;
        }
        showToast(msg, 'success');

        if (result.errors && result.errors.length > 0) {
            setTimeout(() => showToast(`${result.errors.length} image(s) had issues`, 'error', 4000), 2600);
        }

        openDeck(result.deck.id);
    } catch (e) {
        hideLoading();
        showToast(e.message, 'error', 4000);
    }
}

// ── Camera (webcam capture for desktop) ──────────────────────
let cameraStream = null;

async function openCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showToast('Camera not supported in this browser', 'error', 4000);
        return;
    }
    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } }
        });
        const video = document.getElementById('camera-video');
        video.srcObject = cameraStream;
        document.getElementById('camera-overlay').style.display = 'flex';
    } catch (e) {
        let msg = 'Could not access camera';
        if (e.name === 'NotAllowedError') msg = 'Camera permission denied. Allow camera access in your browser settings.';
        else if (e.name === 'NotFoundError') msg = 'No camera found on this device';
        showToast(msg, 'error', 4000);
    }
}

function capturePhoto() {
    const video = document.getElementById('camera-video');
    const canvas = document.getElementById('camera-canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0);
    canvas.toBlob(blob => {
        const file = new File([blob], `photo-${Date.now()}.jpg`, { type: 'image/jpeg' });
        selectedFiles.push(file);
        renderThumbnails();
        document.getElementById('upload-btn').disabled = selectedFiles.length === 0;
        closeCamera();
        showToast('Photo captured!', 'success');
    }, 'image/jpeg', 0.9);
}

function closeCamera() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(t => t.stop());
        cameraStream = null;
    }
    document.getElementById('camera-overlay').style.display = 'none';
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

        document.getElementById('study-btn').textContent =
            dueCount > 0 ? `📖 Study ${dueCount} due cards` : '📖 Practice all cards';

    } catch (e) { showToast(e.message, 'error'); }
}

function deckBack() {
    if (deckCameFromFolder && currentFolderId) {
        openFolder(currentFolderId);
    } else {
        showView('home');
    }
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
        if (deckCameFromFolder && currentFolderId) {
            openFolder(currentFolderId);
        } else {
            showView('home');
        }
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
        studySessionId = data.session_id;
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
    reviewInFlight = false;
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

function setStudyActionsDisabled(disabled) {
    document.querySelectorAll('#study-actions button, .mc-option, #type-answer').forEach(el => {
        if (el.tagName === 'BUTTON' || el.tagName === 'INPUT') el.disabled = disabled;
        else el.style.pointerEvents = disabled ? 'none' : '';
    });
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
            <div class="mc-option" data-answer="${escAttr(o)}" onclick="selectMcOption(this)">${esc(o)}</div>`).join('')}
        </div>`;
    document.getElementById('study-actions').style.display = 'none';
}

function selectMcOption(el) {
    if (reviewInFlight) return;
    const selected = el.dataset.answer || '';
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
    if (reviewInFlight) return;
    const input = document.getElementById('type-answer');
    if (!input) return;
    const typed = input.value.trim().toLowerCase();
    const correct = currentCard.answer.trim().toLowerCase();
    const feedback = document.getElementById('type-answer-feedback');
    const isCorrect = typed === correct || (
        typed.length >= 3 &&
        (correct.length >= 5 && typed.length >= Math.ceil(correct.length * 0.8) && correct.includes(typed)) ||
        (typed.length >= 5 && correct.length >= Math.ceil(typed.length * 0.8) && typed.includes(correct))
    );
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
    if (reviewInFlight || !currentCard) return;
    reviewInFlight = true;
    setStudyActionsDisabled(true);
    const timeMs = Date.now() - studyStartTime;
    try {
        const result = await api(`/api/cards/${currentCard.id}/review?correct=${correct}&time_ms=${timeMs}&session_id=${encodeURIComponent(studySessionId || '')}`, { method: 'POST' });
        if (correct) studyCorrect++;
        studyStartTime = Date.now();
        if (result.xp_earned) showToast(`+${result.xp_earned} XP`, 'xp', 1500);
        studyIndex++;
        renderStudyCard();
    } catch (e) {
        reviewInFlight = false;
        setStudyActionsDisabled(false);
        showToast(e.message, 'error', 4000);
    }
}

async function finishStudy() {
    if (finishInFlight) return;
    finishInFlight = true;
    const area = document.getElementById('study-card-area');
    area.innerHTML = `<div class="empty-state"><div class="text">Saving study session...</div></div>`;
    document.getElementById('study-actions').innerHTML = `
        <button class="btn btn-outline" onclick="deckBack()">Back to deck</button>`;
    document.getElementById('study-actions').style.display = 'flex';
    try {
        const result = await api(`/api/session/complete?deck_id=${currentDeckId}&session_id=${encodeURIComponent(studySessionId || '')}`, { method: 'POST' });
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
    } catch (e) {
        area.innerHTML = `<div class="empty-state"><div class="text">Could not save study session.</div></div>`;
        document.getElementById('study-actions').innerHTML = `
            <button class="btn btn-primary" onclick="finishStudy()">Retry save</button>
            <button class="btn btn-outline" onclick="deckBack()">Back to deck</button>`;
        showToast(e.message, 'error', 4000);
    } finally {
        finishInFlight = false;
    }
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
                <div class="ach-icon">${esc(a.icon)}</div>
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
                `<option value="${escAttr(m)}" ${m === settings.model ? 'selected' : ''}>${esc(m)}</option>`).join('');
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
function escAttr(str) {
    return esc(str).replace(/'/g, '&#39;').replace(/`/g, '&#96;');
}
function safeColor(color) {
    return /^#[0-9a-fA-F]{6}$/.test(color || '') ? color : 'var(--primary)';
}
function revokeThumbnailUrls() {
    thumbnailUrls.forEach(url => URL.revokeObjectURL(url));
    thumbnailUrls = [];
}

// ── Init ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => { loadHome(); });
