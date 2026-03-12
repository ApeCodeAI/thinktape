// braindump — minimal client-side JS

async function deleteNote(id) {
    if (!confirm('Move this note to trash?')) return;
    const resp = await fetch(`/api/notes/${id}`, { method: 'DELETE' });
    if (resp.ok) {
        window.location.reload();
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
