/**
 * API client for Skylight Photos
 */
const API = {
    getPin() {
        return localStorage.getItem(Config.PIN_KEY) || '';
    },

    setPin(pin) {
        localStorage.setItem(Config.PIN_KEY, pin);
    },

    clearPin() {
        localStorage.removeItem(Config.PIN_KEY);
    },

    async verifyPin(pin) {
        const resp = await fetch(`${Config.API_BASE}/verify-pin`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin }),
        });
        const data = await resp.json();
        return data.valid === true;
    },

    async uploadFile(file, onProgress, location) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `${Config.API_BASE}/upload`);
            xhr.setRequestHeader('X-Upload-PIN', this.getPin());

            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable && onProgress) {
                    onProgress(Math.round((e.loaded / e.total) * 100));
                }
            });

            xhr.addEventListener('load', () => {
                if (xhr.status === 200) {
                    resolve(JSON.parse(xhr.responseText));
                    return;
                }
                let error;
                if (xhr.status === 403) {
                    this.clearPin();
                    error = new Error('Invalid PIN');
                } else {
                    try {
                        const body = JSON.parse(xhr.responseText);
                        error = new Error(body.detail || 'Upload failed');
                    } catch {
                        error = new Error(`Upload failed (${xhr.status})`);
                    }
                }
                error.status = xhr.status;
                reject(error);
            });

            xhr.addEventListener('error', () => reject(new Error('Network error')));

            const formData = new FormData();
            formData.append('file', file);
            if (location) formData.append('location', location);
            xhr.send(formData);
        });
    },

    async listMedia() {
        const resp = await fetch(`${Config.API_BASE}/media`);
        if (!resp.ok) throw new Error('Failed to load media');
        return resp.json();
    },

    async deleteMedia(id) {
        const resp = await fetch(`${Config.API_BASE}/media/${id}`, {
            method: 'DELETE',
            headers: { 'X-Upload-PIN': this.getPin() },
        });
        if (resp.status === 403) {
            this.clearPin();
            throw new Error('Invalid PIN');
        }
        if (!resp.ok) throw new Error('Delete failed');
        return resp.json();
    },

    mediaFileUrl(id) {
        return `${Config.API_BASE}/media/${id}/file`;
    },

    async googleStatus() {
        const resp = await fetch(`${Config.API_BASE}/google/status`);
        if (!resp.ok) throw new Error('Status fetch failed');
        return resp.json();
    },

    googleOAuthStartUrl() {
        return `${Config.API_BASE}/google/oauth/start`;
    },

    async googleCreatePickerSession() {
        const resp = await fetch(`${Config.API_BASE}/google/picker/session`, {
            method: 'POST',
            headers: { 'X-Upload-PIN': this.getPin() },
        });
        if (resp.status === 401) throw new Error('Google account not connected');
        if (resp.status === 403) { this.clearPin(); throw new Error('Invalid PIN'); }
        if (!resp.ok) throw new Error('Could not create picker session');
        return resp.json();
    },

    async googlePollPickerSession(sessionId) {
        const resp = await fetch(`${Config.API_BASE}/google/picker/session/${sessionId}`, {
            headers: { 'X-Upload-PIN': this.getPin() },
        });
        if (!resp.ok) throw new Error('Poll failed');
        return resp.json();
    },

    async googleImportPickerSession(sessionId) {
        const resp = await fetch(`${Config.API_BASE}/google/picker/session/${sessionId}/import`, {
            method: 'POST',
            headers: { 'X-Upload-PIN': this.getPin() },
        });
        if (!resp.ok) throw new Error('Import failed');
        return resp.json();
    },
};
