/**
 * Google Photos import component — Upload-tab button, picker window, polling, ingest.
 */
const GoogleImport = {
    POLL_INTERVAL_MS: 3000,
    POLL_TIMEOUT_MS: 5 * 60 * 1000,

    async init() {
        this.btn = document.getElementById('google-import-btn');
        this.btnLabel = document.getElementById('google-import-btn-label');
        this.statusEl = document.getElementById('google-import-status');
        this.btn.addEventListener('click', () => this.onClick());

        // Listen for the OAuth callback page posting back via window.opener
        window.addEventListener('message', (e) => {
            if (e.data && e.data.type === 'google-oauth') {
                this.refreshState();
            }
        });

        await this.refreshState();
    },

    async refreshState() {
        try {
            const status = await API.googleStatus();
            this.btn.hidden = false;
            if (!status.authorized) {
                this.btnLabel.textContent = 'Connect Google Photos';
                this.mode = 'connect';
            } else if (status.expired) {
                this.btnLabel.textContent = 'Reconnect Google Photos';
                this.mode = 'reconnect';
            } else {
                this.btnLabel.textContent = '📷 Import from Google Photos';
                this.mode = 'import';
            }
        } catch (err) {
            console.error('Google status fetch failed:', err);
            this.btn.hidden = true;
        }
    },

    async onClick() {
        if (this.mode === 'connect' || this.mode === 'reconnect') {
            this.openOAuth();
        } else if (this.mode === 'import') {
            await this.startImport();
        }
    },

    openOAuth() {
        // window.open() cannot set custom headers, so we pass the PIN as a query param.
        // The backend's /oauth/start accepts ?pin= as an alternative to X-Upload-PIN (see Step 5).
        // The popup lands on Google's consent screen, then on our /oauth/callback page,
        // which closes itself and posts a message back to refresh button state.
        const url = `${API.googleOAuthStartUrl()}?pin=${encodeURIComponent(API.getPin())}`;
        window.open(url, 'gp_oauth', 'width=520,height=640');
    },

    async startImport() {
        this.statusEl.classList.remove('hidden');
        this.statusEl.textContent = 'Creating picker session...';
        let session;
        try {
            session = await API.googleCreatePickerSession();
        } catch (err) {
            this.statusEl.textContent = '';
            this.statusEl.classList.add('hidden');
            Toast.error(err.message);
            if (err.message.includes('not connected') || err.message.includes('expired')) {
                await this.refreshState();
            }
            return;
        }

        const popup = window.open(session.picker_uri, 'gp_picker', 'width=900,height=700');
        if (!popup) {
            Toast.error('Popup blocked — allow popups for this site and try again');
            this.statusEl.classList.add('hidden');
            return;
        }
        this.statusEl.textContent = 'Waiting for selection in Google Photos...';

        const ready = await this.pollUntilReady(session.session_id);
        if (!ready) {
            this.statusEl.textContent = '';
            this.statusEl.classList.add('hidden');
            Toast.error('Picker session expired or timed out');
            return;
        }

        this.statusEl.textContent = 'Importing... this may take a moment';
        try {
            const result = await API.googleImportPickerSession(session.session_id);
            this.statusEl.classList.add('hidden');
            const s = result.summary;
            const parts = [];
            if (s.imported) parts.push(`${s.imported} imported`);
            if (s.duplicates) parts.push(`${s.duplicates} duplicate${s.duplicates === 1 ? '' : 's'} skipped`);
            if (s.failed) parts.push(`${s.failed} failed`);
            Toast.success(parts.join(', ') || 'Nothing to import');

            // Refresh gallery if visible
            if (document.getElementById('tab-gallery').classList.contains('active')) {
                Gallery.load();
            }
        } catch (err) {
            this.statusEl.classList.add('hidden');
            Toast.error(err.message);
        }
    },

    async pollUntilReady(sessionId) {
        const start = Date.now();
        while (Date.now() - start < this.POLL_TIMEOUT_MS) {
            try {
                const result = await API.googlePollPickerSession(sessionId);
                if (result.status === 'ready') return true;
                if (result.status === 'expired') return false;
            } catch (err) {
                console.warn('poll error', err);
            }
            await new Promise(r => setTimeout(r, this.POLL_INTERVAL_MS));
        }
        return false;
    },
};
