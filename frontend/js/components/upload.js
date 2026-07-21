/**
 * Upload component — drag-drop + file picker with progress.
 * Uploads run through a bounded queue (MAX_CONCURRENT at a time).
 * Network/server failures auto-retry with backoff; final failures keep
 * their File handle so they can be retried per-item or all at once.
 */
const Upload = {
    MAX_CONCURRENT: 3,
    MAX_ATTEMPTS: 3,

    init() {
        this.dropZone = document.getElementById('drop-zone');
        this.fileInput = document.getElementById('file-input');
        this.queue = document.getElementById('upload-queue');

        this.pending = [];
        this.active = 0;
        this.failed = new Set();
        this.summaryEl = null;

        // Click to open file picker
        this.dropZone.addEventListener('click', (e) => {
            if (e.target === this.fileInput) return;
            this.fileInput.click();
        });

        this.fileInput.addEventListener('change', () => {
            if (this.fileInput.files.length) {
                this.handleFiles(Array.from(this.fileInput.files));
                this.fileInput.value = '';
            }
        });

        // "Browse Files" path: no accept filter, so Android opens the real
        // file manager (originals with GPS) instead of the photo picker
        this.browseInput = document.getElementById('file-input-browse');
        document.getElementById('browse-files-btn').addEventListener('click', () => {
            this.browseInput.click();
        });
        this.browseInput.addEventListener('change', () => {
            if (this.browseInput.files.length) {
                this.handleFiles(Array.from(this.browseInput.files));
                this.browseInput.value = '';
            }
        });

        // Caption style chips — remembered across sessions
        this.style = localStorage.getItem('skylight_style') || 'pill';
        const chips = document.getElementById('style-chips');
        chips.querySelectorAll('.style-chip').forEach((chip) => {
            if (chip.dataset.style === this.style) {
                chips.querySelectorAll('.style-chip').forEach((c) => c.classList.remove('active'));
                chip.classList.add('active');
            }
            chip.addEventListener('click', () => {
                chips.querySelectorAll('.style-chip').forEach((c) => c.classList.remove('active'));
                chip.classList.add('active');
                this.style = chip.dataset.style;
                localStorage.setItem('skylight_style', this.style);
            });
        });

        // Drag and drop
        this.dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            this.dropZone.classList.add('dragover');
        });

        this.dropZone.addEventListener('dragleave', () => {
            this.dropZone.classList.remove('dragover');
        });

        this.dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            this.dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                this.handleFiles(Array.from(e.dataTransfer.files));
            }
        });
    },

    handleFiles(files) {
        for (const file of files) {
            if (!Config.ALLOWED_TYPES.includes(file.type)) {
                Toast.error(`Unsupported: ${file.name}`);
                continue;
            }
            if (file.size > Config.MAX_FILE_SIZE) {
                Toast.error(`Too large: ${file.name} (max 500MB)`);
                continue;
            }
            // Snapshot the batch location when the files are picked, so
            // editing the box later doesn't change files already queued
            const location = document.getElementById('batch-location').value.trim();
            const job = { file, location, style: this.style,
                          item: this.createQueueItem(file), attempts: 0 };
            this.queue.prepend(job.item.el);
            job.item.status.textContent = 'Queued';
            this.pending.push(job);
        }
        this.pump();
    },

    pump() {
        while (this.active < this.MAX_CONCURRENT && this.pending.length) {
            const job = this.pending.shift();
            this.active++;
            this.run(job).finally(() => {
                this.active--;
                this.pump();
            });
        }
    },

    async run(job) {
        const { file, item } = job;
        job.attempts++;
        item.progress.classList.remove('error');
        item.progress.style.width = '0%';
        item.status.textContent = 'Uploading...';

        try {
            await API.uploadFile(file, (pct) => {
                item.progress.style.width = pct + '%';
                item.status.textContent = pct + '%';
            }, job.location, job.style);
            this.markDone(job, 'Done');
            Toast.success(`Uploaded ${file.name}`);

            // Refresh gallery if visible
            if (document.getElementById('tab-gallery').classList.contains('active')) {
                Gallery.load();
            }
        } catch (err) {
            if (err.status === 409) {
                // Server already has these exact bytes — treat as success
                this.markDone(job, 'Already uploaded');
                return;
            }

            if (err.message === 'Invalid PIN') {
                item.progress.classList.add('error');
                item.status.textContent = err.message;
                App.logout();
                return;
            }

            // Retry network drops and server errors; 4xx rejections are permanent
            const retriable = err.status === undefined || err.status >= 500;
            if (retriable && job.attempts < this.MAX_ATTEMPTS) {
                item.status.textContent =
                    `Retrying (${job.attempts}/${this.MAX_ATTEMPTS - 1})...`;
                await new Promise((r) => setTimeout(r, 1500 * job.attempts));
                this.pending.push(job);
                return;
            }

            this.markFailed(job, err.message);
        }
    },

    markDone(job, label) {
        const { item } = job;
        item.progress.style.width = '100%';
        item.progress.classList.add('done');
        item.status.textContent = label;
        this.failed.delete(job);
        this.updateSummary();
    },

    markFailed(job, message) {
        const { item } = job;
        item.progress.classList.add('error');
        item.status.textContent = '';

        const label = document.createElement('span');
        label.textContent = message + ' ';

        const retryBtn = document.createElement('button');
        retryBtn.className = 'upload-retry-btn';
        retryBtn.textContent = 'Retry';
        retryBtn.addEventListener('click', () => this.retryJob(job));

        item.status.appendChild(label);
        item.status.appendChild(retryBtn);

        this.failed.add(job);
        this.updateSummary();
        Toast.error(`Failed: ${job.file.name}`);
    },

    retryJob(job) {
        this.failed.delete(job);
        job.attempts = 0;
        job.item.status.textContent = 'Queued';
        job.item.progress.classList.remove('error');
        job.item.progress.style.width = '0%';
        this.pending.push(job);
        this.updateSummary();
        this.pump();
    },

    retryAllFailed() {
        for (const job of Array.from(this.failed)) {
            this.retryJob(job);
        }
    },

    updateSummary() {
        if (this.failed.size === 0) {
            if (this.summaryEl) {
                this.summaryEl.remove();
                this.summaryEl = null;
            }
            return;
        }

        if (!this.summaryEl) {
            this.summaryEl = document.createElement('div');
            this.summaryEl.className = 'upload-summary';

            const text = document.createElement('span');
            text.className = 'upload-summary-text';

            const btn = document.createElement('button');
            btn.className = 'btn btn-small';
            btn.textContent = 'Retry all';
            btn.addEventListener('click', () => this.retryAllFailed());

            this.summaryEl.appendChild(text);
            this.summaryEl.appendChild(btn);
        }

        this.summaryEl.querySelector('.upload-summary-text').textContent =
            `${this.failed.size} upload${this.failed.size === 1 ? '' : 's'} failed`;
        this.queue.prepend(this.summaryEl);
    },

    createQueueItem(file) {
        const el = document.createElement('div');
        el.className = 'upload-item';

        const thumb = document.createElement('div');
        thumb.className = 'upload-item-thumb';
        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.className = 'upload-item-thumb';
            img.src = URL.createObjectURL(file);
            img.onload = () => URL.revokeObjectURL(img.src);
            el.appendChild(img);
        } else {
            thumb.textContent = '🎬';
            thumb.style.display = 'flex';
            thumb.style.alignItems = 'center';
            thumb.style.justifyContent = 'center';
            thumb.style.fontSize = '24px';
            el.appendChild(thumb);
        }

        const info = document.createElement('div');
        info.className = 'upload-item-info';

        const name = document.createElement('div');
        name.className = 'upload-item-name';
        name.textContent = file.name;

        const status = document.createElement('div');
        status.className = 'upload-item-status';
        status.textContent = 'Uploading...';

        const progressWrap = document.createElement('div');
        progressWrap.className = 'upload-item-progress';
        const progressBar = document.createElement('div');
        progressBar.className = 'upload-item-progress-bar';
        progressWrap.appendChild(progressBar);

        info.appendChild(name);
        info.appendChild(status);
        info.appendChild(progressWrap);
        el.appendChild(info);

        return { el, progress: progressBar, status };
    },
};
