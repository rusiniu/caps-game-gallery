// js/common.js — общие функции для галереи Caps Game

const STORAGE_BASE = "https://firebasestorage.googleapis.com/v0/b/capsgame-prod.appspot.com/o/";

// ---------- типы коллекций ----------
const COLLECTION_TYPES = {
    common:    { label: 'Common',    emoji: '📀', color: '#94a3b8', bg: '#e2e8f0' },
    special:   { label: 'Special',   emoji: '✨', color: '#16a34a', bg: '#dcfce7' },
    event:     { label: 'Event',     emoji: '🎉', color: '#2563eb', bg: '#dbeafe' },
    community: { label: 'Community', emoji: '👥', color: '#9333ea', bg: '#f3e5f5' },
    premium:   { label: 'Premium',   emoji: '💎', color: '#b45309', bg: '#fef3c7' }
};

function getCollectionTypeInfo(type) {
    return COLLECTION_TYPES[type] || { label: type || 'Other', emoji: '🎴', color: '#64748b', bg: '#e2e8f0' };
}

// ---------- утилиты ----------
function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>]/g, m => (
        m === '&' ? '&amp;' : m === '<' ? '&lt;' : '&gt;'
    ));
}

function formatNumber(num) {
    if (num === null || num === undefined) return '—';
    return Number(num).toLocaleString('ru-RU');
}

function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
}

// ---------- URL картинок ----------
function buildCollectionLogoUrl(collectionId) {
    const path = `collections/${collectionId}/logo.png`;
    return `${STORAGE_BASE}${encodeURIComponent(path)}?alt=media`;
}

function buildCollectionChipUrl(collectionId, number) {
    const path = `collections/${collectionId}/${number}.png`;
    return `${STORAGE_BASE}${encodeURIComponent(path)}?alt=media`;
}

// ---------- данные ----------
// Снапшот приходит из data/collections.js: window.CAPS_DATA = { generatedAt, count, collections: [...] }
// Подключается в index.html ДО этого файла.
function fetchCollectionsList() {
    const data = window.CAPS_DATA;
    if (!data || !Array.isArray(data.collections)) {
        console.error('CAPS_DATA не загружен. Проверь <script src="data/collections.js">');
        return [];
    }
    // сортировка по collection_id (как договорились)
    return data.collections.slice().sort((a, b) =>
        a.id.localeCompare(b.id, 'en', { sensitivity: 'base' })
    );
}

function getSnapshotMeta() {
    const data = window.CAPS_DATA;
    if (!data) return { generatedAt: null, count: 0 };
    return { generatedAt: data.generatedAt || null, count: data.count || 0 };
}

// ---------- экспорт (не обязателен, но удобно для консоли) ----------
window.CapsTools = {
    STORAGE_BASE,
    COLLECTION_TYPES,
    getCollectionTypeInfo,
    escapeHtml,
    formatNumber,
    formatDate,
    buildCollectionLogoUrl,
    buildCollectionChipUrl,
    fetchCollectionsList,
    getSnapshotMeta,
};