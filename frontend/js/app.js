/**
 * Skylight Photos — main app controller
 */
const App = {
    init() {
        Upload.init();
        Gallery.init();
        this.bindEvents();

        // Auto-login if PIN is saved
        const savedPin = API.getPin();
        if (savedPin) {
            this.enterApp();
        }
    },

    bindEvents() {
        // PIN submit
        document.getElementById('pin-submit').addEventListener('click', () => this.submitPin());
        document.getElementById('pin-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.submitPin();
        });

        // Logout
        document.getElementById('logout-btn').addEventListener('click', () => this.logout());

        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
        });
    },

    async submitPin() {
        const input = document.getElementById('pin-input');
        const error = document.getElementById('pin-error');
        const pin = input.value.trim();

        if (!pin) {
            error.textContent = 'Please enter a PIN';
            error.classList.remove('hidden');
            return;
        }

        try {
            const valid = await API.verifyPin(pin);
            if (valid) {
                API.setPin(pin);
                error.classList.add('hidden');
                this.enterApp();
            } else {
                error.textContent = 'Incorrect PIN';
                error.classList.remove('hidden');
                input.value = '';
                input.focus();
            }
        } catch {
            error.textContent = 'Connection error';
            error.classList.remove('hidden');
        }
    },

    enterApp() {
        document.getElementById('pin-screen').classList.remove('active');
        document.getElementById('app-screen').classList.add('active');
        Gallery.load();
    },

    logout() {
        API.clearPin();
        document.getElementById('app-screen').classList.remove('active');
        document.getElementById('pin-screen').classList.add('active');
        document.getElementById('pin-input').value = '';
        document.getElementById('pin-error').classList.add('hidden');
    },

    switchTab(name) {
        document.querySelectorAll('.tab').forEach(t =>
            t.classList.toggle('active', t.dataset.tab === name)
        );
        document.querySelectorAll('.tab-content').forEach(c =>
            c.classList.toggle('active', c.id === `tab-${name}`)
        );
        if (name === 'gallery') Gallery.load();
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
