/**
 * LegalConnector Dashboard - JavaScript
 */

// API Helper
const api = {
    async get(endpoint) {
        const response = await fetch(endpoint);
        if (!response.ok) throw new Error(`API error: ${response.status}`);
        return response.json();
    },

    async post(endpoint, data) {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!response.ok) throw new Error(`API error: ${response.status}`);
        return response.json();
    }
};

// Notification helper
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;

    // Style inline per semplicita'
    Object.assign(notification.style, {
        position: 'fixed',
        top: '1rem',
        right: '1rem',
        padding: '1rem 1.5rem',
        borderRadius: '8px',
        background: type === 'error' ? '#fee2e2' : type === 'success' ? '#dcfce7' : '#e0f2fe',
        color: type === 'error' ? '#991b1b' : type === 'success' ? '#166534' : '#075985',
        boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
        zIndex: '1000',
        animation: 'slideIn 0.3s ease'
    });

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// Format numbers
function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toLocaleString();
}

// Format date
function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('it-IT', {
        day: '2-digit',
        month: 'short',
        year: 'numeric'
    });
}

// Polling for sync status
async function pollSyncStatus(connectorName, interval = 2000) {
    const poll = async () => {
        try {
            const status = await api.get(`/api/connectors/${connectorName}/status`);

            if (status.state === 'running') {
                updateProgressBar(connectorName, status.progress);
                setTimeout(poll, interval);
            } else if (status.state === 'completed') {
                showNotification(`Sync completato: ${status.processed} documenti`, 'success');
                updateProgressBar(connectorName, 100);
            } else if (status.state === 'error') {
                showNotification(`Errore sync: ${status.error}`, 'error');
            }
        } catch (e) {
            console.error('Polling error:', e);
        }
    };

    poll();
}

// Progress bar update
function updateProgressBar(connectorName, progress) {
    const progressBar = document.querySelector(`[data-connector="${connectorName}"] .progress-bar`);
    if (progressBar) {
        progressBar.style.width = `${progress}%`;
    }
}

// Copy to clipboard
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showNotification('Copiato negli appunti!', 'success');
    } catch (e) {
        showNotification('Impossibile copiare', 'error');
    }
}

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

console.log('LegalConnector Dashboard initialized');
