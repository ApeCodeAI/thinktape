// braindump — client-side JS

// ─── Delete / Restore ───
async function deleteNote(id) {
    if (!confirm('Move this note to trash?')) return;
    const resp = await fetch(`/api/notes/${id}`, { method: 'DELETE' });
    if (resp.ok) {
        window.location.href = '/';
    } else {
        alert('Failed to delete note');
    }
}

async function restoreNote(id) {
    const resp = await fetch(`/api/notes/${id}/restore`, { method: 'POST' });
    if (resp.ok) {
        window.location.reload();
    } else {
        alert('Failed to restore note');
    }
}

// ─── Image Lightbox ───
function openLightbox(src) {
    const overlay = document.createElement('div');
    overlay.className = 'lightbox-overlay';
    overlay.innerHTML = `<img src="${src}" alt="">`;
    overlay.addEventListener('click', function () {
        overlay.classList.remove('active');
        setTimeout(function () { overlay.remove(); }, 300);
    });
    document.body.appendChild(overlay);
    // Trigger transition
    requestAnimationFrame(function () { overlay.classList.add('active'); });
}

// ─── Markdown Rendering ───
document.addEventListener('DOMContentLoaded', function () {
    if (typeof marked === 'undefined') return;

    // Configure marked
    marked.setOptions({
        breaks: true,
        gfm: true,
    });

    // Render all markdown content blocks on detail pages
    document.querySelectorAll('.note-detail-content.markdown-body[data-markdown]').forEach(function (el) {
        var raw = el.getAttribute('data-markdown');
        // Decode HTML entities
        var textarea = document.createElement('textarea');
        textarea.innerHTML = raw;
        var decoded = textarea.value;
        el.innerHTML = marked.parse(decoded);
    });

    // Stop click propagation on videos/audios inside card links
    document.querySelectorAll('.note-card-link video, .note-card-link audio').forEach(function (el) {
        el.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); });
    });
});
