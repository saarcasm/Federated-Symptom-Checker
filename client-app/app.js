document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initSymptomChecker();
    initSkinAnalysis();
    initRespiratoryAnalysis();
    initPrivacyDashboard();
    initResultsPanel();
});

// --- Tab Navigation Logic ---
function initTabs() {
    const tabs = document.querySelectorAll('.tab-btn');
    const indicator = document.getElementById('tabIndicator');
    const panes = document.querySelectorAll('.tab-pane');

    function updateIndicator(btn) {
        if (!indicator || window.innerWidth <= 768) return;
        indicator.style.width = `${btn.offsetWidth}px`;
        indicator.style.transform = `translateX(${btn.offsetLeft}px)`;
    }

    function switchTab(targetId) {
        // Update URL hash without scroll
        history.replaceState(null, null, `#${targetId}`);

        tabs.forEach(t => {
            t.classList.remove('active');
            if (t.dataset.target === targetId) {
                t.classList.add('active');
                updateIndicator(t);
            }
        });

        panes.forEach(p => {
            if (p.id === targetId) {
                p.classList.remove('hidden');
                // Trigger reflow for animation
                void p.offsetWidth;
                p.classList.add('fade-in');
            } else {
                p.classList.add('hidden');
                p.classList.remove('fade-in');
            }
        });
        
        hideResults();
    }

    tabs.forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.target));
    });

    // Handle initial route
    const hash = window.location.hash.substring(1);
    const validTabs = ['symptoms', 'skin', 'respiratory'];
    if (validTabs.includes(hash)) {
        switchTab(hash);
    } else {
        // Init indicator for default tab
        const activeTab = document.querySelector('.tab-btn.active');
        if (activeTab) setTimeout(() => updateIndicator(activeTab), 100);
    }

    window.addEventListener('resize', () => {
        const activeTab = document.querySelector('.tab-btn.active');
        if (activeTab) updateIndicator(activeTab);
    });
}

// --- Symptom Checker Logic ---
async function initSymptomChecker() {
    let symptomsList = [];

    const formatName = (str) => str.trim().replace(/\.\d+$/, '').replace(/\s+/g, '_')
        .split('_').filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

    const container = document.getElementById('symptomList');
    const searchInput = document.getElementById('symptomSearch');
    const tagsContainer = document.getElementById('selectedSymptoms');
    const analyzeBtn = document.getElementById('analyzeSymptomsBtn');

    let selectedSymptoms = new Set();

    try {
        const vocab = await window.api.getSymptomVocabulary();
        symptomsList = vocab.symptoms || [];
        if (!vocab.trained || symptomsList.length === 0) {
            container.innerHTML = '<p class="upload-hint">Symptom model is not trained on the server yet. Run benchmarks/train_and_export_checkpoint.py, then reload.</p>';
            analyzeBtn.disabled = true;
            return;
        }
    } catch (error) {
        container.innerHTML = '<p class="upload-hint">Could not reach the API server. Is it running on http://localhost:8000?</p>';
        analyzeBtn.disabled = true;
        return;
    }

    // Render list
    function renderList(filter = '') {
        container.innerHTML = '';
        const filtered = symptomsList.filter(s => formatName(s).toLowerCase().includes(filter.toLowerCase()));
        
        filtered.forEach(sym => {
            const label = document.createElement('label');
            label.className = 'symptom-item';
            const isChecked = selectedSymptoms.has(sym);
            label.innerHTML = `
                <input type="checkbox" value="${sym}" ${isChecked ? 'checked' : ''}>
                <span>${formatName(sym)}</span>
            `;
            
            label.querySelector('input').addEventListener('change', (e) => {
                if(e.target.checked) selectedSymptoms.add(sym);
                else selectedSymptoms.delete(sym);
                renderTags();
                updateBtnState();
            });
            container.appendChild(label);
        });
    }

    function renderTags() {
        tagsContainer.innerHTML = '';
        selectedSymptoms.forEach(sym => {
            const tag = document.createElement('div');
            tag.className = 'tag';
            tag.innerHTML = `
                ${formatName(sym)}
                <span class="tag-remove" data-val="${sym}">×</span>
            `;
            tag.querySelector('.tag-remove').addEventListener('click', () => {
                selectedSymptoms.delete(sym);
                renderTags();
                renderList(searchInput.value);
                updateBtnState();
            });
            tagsContainer.appendChild(tag);
        });
    }

    function updateBtnState() {
        analyzeBtn.disabled = selectedSymptoms.size === 0;
    }

    searchInput.addEventListener('input', (e) => renderList(e.target.value));

    analyzeBtn.addEventListener('click', async () => {
        setLoading(analyzeBtn, true);
        try {
            const results = await window.api.predictSymptoms(Array.from(selectedSymptoms));
            displayResults(results.disease, results.confidence, results.top_predictions, results);
        } catch (error) {
            alert('Analysis failed: ' + error.message);
        } finally {
            setLoading(analyzeBtn, false);
        }
    });

    renderList();
    updateBtnState();
}

// --- Skin Analysis Logic ---
function initSkinAnalysis() {
    const dropZone = document.getElementById('skinDropZone');
    const fileInput = document.getElementById('skinFileInput');
    const uploadContent = document.getElementById('skinUploadContent');
    const previewContainer = document.getElementById('skinPreviewContainer');
    const previewImg = document.getElementById('skinPreview');
    const removeBtn = document.getElementById('removeSkinFile');
    const analyzeBtn = document.getElementById('analyzeSkinBtn');
    
    let currentFile = null;

    dropZone.addEventListener('click', (e) => {
        if (e.target.closest('#removeSkinFile')) return;
        fileInput.click();
    });
    
    // Drag & Drop
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if(e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    
    fileInput.addEventListener('change', (e) => {
        if(e.target.files.length) handleFile(e.target.files[0]);
    });

    removeBtn.addEventListener('click', (e) => {
        e.stopPropagation(); // Prevent opening file dialog
        resetSkinUpload();
    });

    function handleFile(file) {
        if (!file.type.startsWith('image/')) return alert('Please upload an image file.');
        currentFile = file;
        const reader = new FileReader();
        reader.onload = (e) => {
            previewImg.src = e.target.result;
            uploadContent.classList.add('hidden');
            previewContainer.classList.remove('hidden');
            analyzeBtn.disabled = false;
        };
        reader.readAsDataURL(file);
    }

    function resetSkinUpload() {
        currentFile = null;
        fileInput.value = '';
        previewImg.src = '';
        previewContainer.classList.add('hidden');
        uploadContent.classList.remove('hidden');
        analyzeBtn.disabled = true;
    }

    analyzeBtn.addEventListener('click', async () => {
        if(!currentFile) return;
        setLoading(analyzeBtn, true);
        try {
            const results = await window.api.predictSkin(currentFile);
            displayResults(results.lesion_type || results.condition, results.confidence, results.top_predictions, results);
        } catch (error) {
            alert('Analysis failed: ' + error.message);
        } finally {
            setLoading(analyzeBtn, false);
        }
    });
}

// --- Respiratory Analysis Logic ---
function initRespiratoryAnalysis() {
    const recordBtn = document.getElementById('recordBtn');
    const timerDisplay = document.getElementById('recordingTimer');
    const statusText = document.getElementById('recordingStatus');
    const waveform = document.getElementById('waveform');
    const dropZone = document.getElementById('audioDropZone');
    const fileInput = document.getElementById('audioFileInput');
    const playerContainer = document.getElementById('audioPlayerContainer');
    const audioPlayback = document.getElementById('audioPlayback');
    const removeBtn = document.getElementById('removeAudioFile');
    const analyzeBtn = document.getElementById('analyzeAudioBtn');

    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;
    let timerInterval = null;
    let startTime = null;
    let currentAudioFile = null;

    // Recording logic
    recordBtn.addEventListener('click', async () => {
        if (isRecording) {
            stopRecording();
        } else {
            startRecording();
        }
    });

    async function startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunks.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                // The browser records webm/opus (or similar) regardless of what we
                // ask for; relabeling those bytes as audio/wav without transcoding
                // produces a file the server's WAV decoder can't read. Decode the
                // real recording via the Web Audio API and re-encode a genuine WAV.
                const rawBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
                try {
                    const wavBlob = await encodeBlobAsWav(rawBlob);
                    currentAudioFile = new File([wavBlob], "recording.wav", { type: 'audio/wav' });
                    setupAudioPlayback(wavBlob);
                } catch (err) {
                    console.error('Failed to encode recording as WAV:', err);
                    alert('Could not process the recording in this browser. Please try uploading an audio file instead.');
                }
            };

            mediaRecorder.start();
            isRecording = true;
            recordBtn.classList.add('recording');
            waveform.classList.add('active');
            statusText.textContent = "Recording... Click to stop";
            
            startTime = Date.now();
            timerInterval = setInterval(updateTimer, 1000);
            updateTimer();
        } catch (err) {
            alert("Microphone access denied or not available.");
        }
    }

    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
            mediaRecorder.stream.getTracks().forEach(track => track.stop());
        }
        isRecording = false;
        recordBtn.classList.remove('recording');
        waveform.classList.remove('active');
        clearInterval(timerInterval);
        statusText.textContent = "Recording complete";
    }

    function updateTimer() {
        const diff = Math.floor((Date.now() - startTime) / 1000);
        const mins = String(Math.floor(diff / 60)).padStart(2, '0');
        const secs = String(diff % 60).padStart(2, '0');
        timerDisplay.textContent = `${mins}:${secs}`;
    }

    // File Upload logic
    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
        if(e.target.files.length) {
            const file = e.target.files[0];
            if(!file.type.startsWith('audio/')) return alert('Please upload an audio file.');
            currentAudioFile = file;
            setupAudioPlayback(file);
        }
    });

    function setupAudioPlayback(blobOrFile) {
        const url = URL.createObjectURL(blobOrFile);
        audioPlayback.src = url;
        playerContainer.classList.remove('hidden');
        analyzeBtn.disabled = false;
    }

    removeBtn.addEventListener('click', () => {
        audioPlayback.src = '';
        currentAudioFile = null;
        fileInput.value = '';
        playerContainer.classList.add('hidden');
        analyzeBtn.disabled = true;
        timerDisplay.textContent = "00:00";
        statusText.textContent = "Click to start recording";
    });

    analyzeBtn.addEventListener('click', async () => {
        if(!currentAudioFile) return;
        setLoading(analyzeBtn, true);
        try {
            const results = await window.api.predictRespiratory(currentAudioFile);
            displayResults(results.condition, results.confidence, results.top_predictions, results);
        } catch (error) {
            alert('Analysis failed: ' + error.message);
        } finally {
            setLoading(analyzeBtn, false);
        }
    });
}

// --- Privacy Dashboard ---
async function initPrivacyDashboard() {
    async function updateData() {
        try {
            const [status, privacy] = await Promise.all([
                window.api.getModelStatus(),
                window.api.getPrivacyBudget()
            ]);

            document.getElementById('currentRound').textContent = status.current_round;
            document.getElementById('totalRounds').textContent = status.total_rounds;
            document.getElementById('globalAccuracy').textContent = status.global_accuracy != null
                ? Math.round(status.global_accuracy * 100)
                : '--';

            document.getElementById('epsilonValue').textContent = privacy.epsilon;

            // Assume budget goes up to 10 for progress bar
            const epsVal = Math.min((parseFloat(privacy.epsilon) / 10) * 100, 100);
            document.getElementById('epsilonFill').style.width = `${epsVal}%`;

            const epsilonNote = document.getElementById('epsilonNote');
            epsilonNote.textContent = privacy.dp_applied_to_deployed_model === false
                ? 'Reference benchmark only -- not applied to this deployed model'
                : '';
        } catch (error) {
            console.warn('Privacy dashboard update failed (is the API server running?):', error);
            document.getElementById('currentRound').textContent = '--';
            document.getElementById('totalRounds').textContent = '--';
            document.getElementById('globalAccuracy').textContent = '--';
            document.getElementById('epsilonValue').textContent = '--';
            document.getElementById('epsilonNote').textContent = 'API server unreachable';
        }
    }

    await updateData();
    // Update every 30 seconds
    setInterval(updateData, 30000);
}

// --- Audio helpers ---
async function encodeBlobAsWav(blob) {
    const arrayBuffer = await blob.arrayBuffer();
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const audioCtx = new AudioCtx();
    const decoded = await audioCtx.decodeAudioData(arrayBuffer);
    audioCtx.close();

    const numChannels = decoded.numberOfChannels;
    const sampleRate = decoded.sampleRate;
    const numFrames = decoded.length;

    // Interleave channels
    const interleaved = new Float32Array(numFrames * numChannels);
    for (let ch = 0; ch < numChannels; ch++) {
        const channelData = decoded.getChannelData(ch);
        for (let i = 0; i < numFrames; i++) {
            interleaved[i * numChannels + ch] = channelData[i];
        }
    }

    const bytesPerSample = 2; // 16-bit PCM
    const blockAlign = numChannels * bytesPerSample;
    const dataSize = interleaved.length * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    const writeString = (offset, str) => {
        for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);       // PCM chunk size
    view.setUint16(20, 1, true);        // audio format = PCM
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bytesPerSample * 8, true);
    writeString(36, 'data');
    view.setUint32(40, dataSize, true);

    let offset = 44;
    for (let i = 0; i < interleaved.length; i++, offset += 2) {
        const s = Math.max(-1, Math.min(1, interleaved[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

// --- Common UI Utils ---
function setLoading(btn, isLoading) {
    const text = btn.querySelector('.btn-text');
    const loader = btn.querySelector('.loader');
    if (isLoading) {
        btn.disabled = true;
        text.classList.add('hidden');
        loader.classList.remove('hidden');
    } else {
        btn.disabled = false;
        text.classList.remove('hidden');
        loader.classList.add('hidden');
    }
}

function initResultsPanel() {
    document.getElementById('closeResults').addEventListener('click', hideResults);
}

function hideResults() {
    const panel = document.getElementById('resultsPanel');
    panel.classList.add('hidden');
    panel.classList.remove('slide-up');
}

function displayResults(primaryName, primaryConf, topPredictions, fullResult) {
    const panel = document.getElementById('resultsPanel');

    // Demo-mode notice (shown when the backend flags this prediction as untrained)
    const demoNotice = document.getElementById('demoNotice');
    const demoNoticeText = document.getElementById('demoNoticeText');
    if (fullResult && fullResult.trained === false) {
        demoNoticeText.textContent = fullResult.notice || 'This model has not been trained on real data yet -- result is illustrative only.';
        demoNotice.classList.remove('hidden');
    } else {
        demoNotice.classList.add('hidden');
    }

    // Set primary
    document.getElementById('primaryDiagnosis').textContent = primaryName || 'Unknown';
    const confPercent = Math.round(primaryConf * 100);
    
    // Animate percentage text
    animateValue('primaryConfidence', 0, confPercent, 1000);
    
    // Color code confidence circle
    const arc = document.getElementById('primaryConfidenceArc');
    let color = '#ef4444'; // red
    if (confPercent >= 80) color = '#10b981'; // green
    else if (confPercent >= 50) color = '#f59e0b'; // yellow
    
    arc.style.stroke = color;
    
    // Animate dasharray: length is 100
    // Dasharray format: "filled, empty"
    setTimeout(() => {
        arc.style.strokeDasharray = `${confPercent}, 100`;
    }, 100); // slight delay to trigger css transition

    // Set secondary predictions
    const list = document.getElementById('predictionsList');
    list.innerHTML = '';
    
    (topPredictions || []).forEach((pred, index) => {
        const name = pred.disease || pred.condition || 'Unknown';
        const conf = Math.round(pred.confidence * 100);
        
        let barColor = 'var(--accent-primary)';
        if(conf < 50) barColor = 'var(--danger)';
        else if(conf < 80) barColor = 'var(--warning)';

        const item = document.createElement('div');
        item.className = 'prediction-item';
        item.innerHTML = `
            <div class="pred-name" title="${name}">${name}</div>
            <div class="pred-bar-container">
                <div class="pred-bar" style="background: ${barColor};" data-width="${conf}%"></div>
            </div>
            <div class="pred-val">${conf}%</div>
        `;
        list.appendChild(item);
        
        // Trigger animation
        setTimeout(() => {
            const bar = item.querySelector('.pred-bar');
            bar.style.width = bar.dataset.width;
        }, 100 + (index * 100));
    });

    // Show panel
    panel.classList.remove('hidden');
    // Trigger reflow
    void panel.offsetWidth;
    panel.classList.add('slide-up');
    
    // Scroll to results
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function animateValue(id, start, end, duration) {
    const obj = document.getElementById(id);
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        obj.innerHTML = Math.floor(progress * (end - start) + start);
        if (progress < 1) {
            window.requestAnimationFrame(step);
        }
    };
    window.requestAnimationFrame(step);
}
