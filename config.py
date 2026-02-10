import os

# Skylight frame email address
FRAME_EMAIL = os.getenv("FRAME_EMAIL", "killerkastle@ourskylight.com")

# SMTP settings (Mailcow)
SMTP_HOST = os.getenv("SMTP_HOST", "192.168.1.139")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "skylight@2azone.com")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "skylight@2azone.com")
SMTP_TLS = os.getenv("SMTP_TLS", "true").lower() == "true"

# Upload settings
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(25 * 1024 * 1024)))  # 25MB
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp"}

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8007"))
