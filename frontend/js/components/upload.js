/**
 * Upload component — drag-drop + file picker with progress
 */
const Upload = {
    init() {
        this.dropZone = document.getElementById('drop-zone');
        this.fileInput = document.getElementById('file-input');
        this.queue = document.getElementById('upload-queue');

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
            this.uploadOne(file);
        }
    },

    async uploadOne(file) {
        const item = this.createQueueItem(file);
        this.queue.prepend(item.el);

        try {
            await API.uploadFile(file, (pct) => {
                item.progress.style.width = pct + '%';
                item.status.textContent = pct + '%';
            });
            item.progress.style.width = '100%';
            item.progress.classList.add('done');
            item.status.textContent = 'Done';
            Toast.success(`Uploaded ${file.name}`);

            // Refresh gallery if visible
            if (document.getElementById('tab-gallery').classList.contains('active')) {
                Gallery.load();
            }
        } catch (err) {
            item.progress.classList.add('error');
            item.status.textContent = err.message;
            Toast.error(err.message);

            if (err.message === 'Invalid PIN') {
                App.logout();
            }
        }
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
