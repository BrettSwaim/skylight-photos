/**
 * Skylight Photos — client configuration
 */
const Config = {
    API_BASE: '/api',
    PIN_KEY: 'skylight_pin',
    MAX_FILE_SIZE: 500 * 1024 * 1024, // 500MB
    ALLOWED_IMAGE_TYPES: ['image/jpeg', 'image/png', 'image/webp'],
    ALLOWED_VIDEO_TYPES: ['video/mp4', 'video/quicktime', 'video/webm', 'video/x-matroska'],
};

Config.ALLOWED_TYPES = [...Config.ALLOWED_IMAGE_TYPES, ...Config.ALLOWED_VIDEO_TYPES];
