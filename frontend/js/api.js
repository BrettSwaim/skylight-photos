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

    async uploadFile(file, onProgress) {
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
                } else if (xhr.status === 403) {
                    this.clearPin();
                    reject(new Error('Invalid PIN'));
                } else {
                    try {
                        const err = JSON.parse(xhr.responseText);
                        reject(new Error(err.detail || 'Upload failed'));
                    } catch {
                        reject(new Error(`Upload failed (${xhr.status})`));
                    }
                }
            });

            xhr.addEventListener('error', () => reject(new Error('Network error')));

            const formData = new FormData();
            formData.append('file', file);
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
};
