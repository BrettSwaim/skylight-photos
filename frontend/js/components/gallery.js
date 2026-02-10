/**
 * Gallery component — grid view with delete and lightbox
 */
const Gallery = {
    init() {
        this.grid = document.getElementById('gallery-grid');
        this.stats = document.getElementById('gallery-stats');
        this.empty = document.getElementById('gallery-empty');
        this.lightbox = document.getElementById('lightbox');
        this.lightboxContent = this.lightbox.querySelector('.lightbox-content');

        document.querySelector('.lightbox-close').addEventListener('click', () => {
            this.closeLightbox();
        });

        this.lightbox.addEventListener('click', (e) => {
            if (e.target === this.lightbox) this.closeLightbox();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.closeLightbox();
        });
    },

    async load() {
        try {
            const data = await API.listMedia();
            this.render(data.media);
        } catch (err) {
            Toast.error('Failed to load gallery');
        }
    },

    render(items) {
        // Clear grid safely
        while (this.grid.firstChild) this.grid.removeChild(this.grid.firstChild);

        if (!items.length) {
            this.stats.textContent = '';
            this.empty.classList.remove('hidden');
            return;
        }

        this.empty.classList.add('hidden');

        const images = items.filter(i => i.media_type === 'image').length;
        const videos = items.filter(i => i.media_type === 'video').length;
        const totalSize = items.reduce((s, i) => s + (i.size_bytes || 0), 0);
        const parts = [];
        if (images) parts.push(`${images} photo${images !== 1 ? 's' : ''}`);
        if (videos) parts.push(`${videos} video${videos !== 1 ? 's' : ''}`);
        parts.push(this.formatSize(totalSize));
        this.stats.textContent = parts.join(' \u00b7 ');

        // Newest first
        const sorted = [...items].sort((a, b) =>
            new Date(b.uploaded_at) - new Date(a.uploaded_at)
        );

        for (const item of sorted) {
            this.grid.appendChild(this.createItem(item));
        }
    },

    createItem(item) {
        const div = document.createElement('div');
        div.className = 'gallery-item';

        const url = API.mediaFileUrl(item.id);

        if (item.media_type === 'image') {
            const img = document.createElement('img');
            img.src = url;
            img.loading = 'lazy';
            img.alt = item.original_name;
            div.appendChild(img);
        } else {
            const video = document.createElement('video');
            video.src = url;
            video.preload = 'metadata';
            video.muted = true;
            div.appendChild(video);

            const badge = document.createElement('span');
            badge.className = 'gallery-item-badge';
            badge.textContent = 'VIDEO';
            div.appendChild(badge);
        }

        // Delete button
        const del = document.createElement('button');
        del.className = 'gallery-item-delete';
        del.textContent = '\u00d7';
        del.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!confirm(`Delete ${item.original_name}?`)) return;
            try {
                await API.deleteMedia(item.id);
                div.remove();
                Toast.success('Deleted');
                this.load(); // refresh stats
            } catch (err) {
                Toast.error(err.message);
                if (err.message === 'Invalid PIN') App.logout();
            }
        });
        div.appendChild(del);

        // Click to lightbox
        div.addEventListener('click', () => this.openLightbox(item));

        return div;
    },

    openLightbox(item) {
        const url = API.mediaFileUrl(item.id);
        while (this.lightboxContent.firstChild) {
            this.lightboxContent.removeChild(this.lightboxContent.firstChild);
        }

        if (item.media_type === 'image') {
            const img = document.createElement('img');
            img.src = url;
            this.lightboxContent.appendChild(img);
        } else {
            const video = document.createElement('video');
            video.src = url;
            video.controls = true;
            video.autoplay = true;
            this.lightboxContent.appendChild(video);
        }

        this.lightbox.classList.remove('hidden');
    },

    closeLightbox() {
        this.lightbox.classList.add('hidden');
        // Stop video playback
        const video = this.lightboxContent.querySelector('video');
        if (video) video.pause();
        while (this.lightboxContent.firstChild) {
            this.lightboxContent.removeChild(this.lightboxContent.firstChild);
        }
    },

    formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB';
    },
};
