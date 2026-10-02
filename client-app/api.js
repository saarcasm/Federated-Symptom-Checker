const API_BASE = 'http://localhost:8000';

class ApiClient {
    static async fetchWithRetry(url, options = {}, retries = 2) {
        const timeout = 30000; // 30 seconds
        
        for (let i = 0; i <= retries; i++) {
            try {
                const controller = new AbortController();
                const id = setTimeout(() => controller.abort(), timeout);
                
                const response = await fetch(url, {
                    ...options,
                    signal: controller.signal
                });
                clearTimeout(id);

                if (!response.ok) {
                    let detail = `HTTP error! status: ${response.status}`;
                    try {
                        const body = await response.json();
                        if (body && body.detail) detail = body.detail;
                    } catch (_) { /* body wasn't JSON */ }
                    const httpError = new Error(detail);
                    httpError.status = response.status;
                    throw httpError;
                }
                return await response.json();
            } catch (err) {
                // Don't retry client errors (4xx) -- retrying won't fix a bad request or a 503 "not trained" state
                const isClientError = err.status >= 400 && err.status < 500;
                const isLastAttempt = i === retries || isClientError;
                if (isLastAttempt) {
                    console.error('API request failed:', err);
                    throw new Error(err.name === 'AbortError' ? 'Request timed out' : err.message || 'Network error');
                }
                // Wait before retrying (exponential backoff could be added here)
                await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)));
            }
        }
    }

    static async getSymptomVocabulary() {
        return await this.fetchWithRetry(`${API_BASE}/symptoms`);
    }

    static async predictSymptoms(symptomsList) {
        return await this.fetchWithRetry(`${API_BASE}/predict/symptoms`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symptoms: symptomsList })
        });
    }

    static async predictSkin(imageFile) {
        const formData = new FormData();
        formData.append('file', imageFile);
        return await this.fetchWithRetry(`${API_BASE}/predict/skin`, {
            method: 'POST',
            body: formData
        });
    }

    static async predictRespiratory(audioFile) {
        const formData = new FormData();
        formData.append('file', audioFile);
        return await this.fetchWithRetry(`${API_BASE}/predict/respiratory`, {
            method: 'POST',
            body: formData
        });
    }

    static async getModelStatus() {
        return await this.fetchWithRetry(`${API_BASE}/model/status`);
    }

    static async getPrivacyBudget() {
        return await this.fetchWithRetry(`${API_BASE}/privacy/budget`);
    }
}

window.api = ApiClient;
