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
function initSymptomChecker() {
    const symptomsList = [
        "itching", "skin_rash", "nodal_skin_eruptions", "continuous_sneezing", "shivering", "chills", "joint_pain", "stomach_pain", "acidity", "ulcers_on_tongue", "muscle_wasting", "vomiting", "burning_micturition", "fatigue", "weight_gain", "anxiety", "cold_hands_and_feets", "mood_swings", "weight_loss", "restlessness", "lethargy", "patches_in_throat", "irregular_sugar_level", "cough", "high_fever", "sunken_eyes", "breathlessness", "sweating", "dehydration", "indigestion", "headache", "yellowish_skin", "dark_urine", "nausea", "loss_of_appetite", "pain_behind_the_eyes", "back_pain", "constipation", "abdominal_pain", "diarrhoea", "mild_fever", "yellow_urine", "yellowing_of_eyes", "acute_liver_failure", "fluid_overload", "swelling_of_stomach", "swelled_lymph_nodes", "malaise", "blurred_and_distorted_vision", "phlegm", "throat_irritation", "redness_of_eyes", "sinus_pressure", "runny_nose", "congestion", "chest_pain", "weakness_in_limbs", "fast_heart_rate", "pain_during_bowel_movements", "pain_in_anal_region", "bloody_stool", "irritation_in_anus", "neck_pain", "dizziness", "cramps", "bruising", "obesity", "swollen_legs", "swollen_blood_vessels", "puffy_face_and_eyes", "enlarged_thyroid", "brittle_nails", "swollen_extremeties", "excessive_hunger", "extra_marital_contacts", "drying_and_tingling_lips", "slurred_speech", "knee_pain", "hip_joint_pain", "muscle_weakness", "stiff_neck", "swelling_joints", "movement_stiffness", "spinning_movements", "loss_of_balance", "unsteadiness", "weakness_of_one_body_side", "loss_of_smell", "bladder_discomfort", "foul_smell_of_urine", "continuous_feel_of_urine", "passage_of_gases", "internal_itching", "toxic_look_typhos", "depression", "irritability", "muscle_pain", "altered_sensorium", "red_spots_over_body", "belly_pain", "abnormal_menstruation", "dischromic_patches", "watering_from_eyes", "increased_appetite", "polyuria", "family_history", "mucoid_sputum", "rusty_sputum", "lack_of_concentration", "visual_disturbances", "receiving_blood_transfusion", "receiving_unsterile_injections", "coma", "stomach_bleeding", "distention_of_abdomen", "history_of_alcohol_consumption", "blood_in_sputum", "prominent_veins_on_calf", "palpitations", "painful_walking", "pus_filled_pimples", "blackheads", "scurring", "skin_peeling", "silver_like_dusting", "small_dents_in_nails", "inflammatory_nails", "blister", "red_sore_around_nose", "yellow_crust_ooze"
    ];

    const formatName = (str) => str.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

    const container = document.getElementById('symptomList');
    const searchInput = document.getElementById('symptomSearch');
    const tagsContainer = document.getElementById('selectedSymptoms');
    const analyzeBtn = document.getElementById('analyzeSymptomsBtn');
    
    let selectedSymptoms = new Set();

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
            displayResults(results.disease, results.confidence, results.top_predictions);
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
            displayResults(results.lesion_type || results.condition, results.confidence, results.top_predictions);
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

            mediaRecorder.onstop = () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                currentAudioFile = new File([audioBlob], "recording.wav", { type: 'audio/wav' });
                setupAudioPlayback(audioBlob);
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
            displayResults(results.condition, results.confidence, results.top_predictions);
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
        const [status, privacy] = await Promise.all([
            window.api.getModelStatus(),
            window.api.getPrivacyBudget()
        ]);

        document.getElementById('currentRound').textContent = status.current_round;
        document.getElementById('totalRounds').textContent = status.total_rounds;
        document.getElementById('globalAccuracy').textContent = status.global_accuracy;
        
        document.getElementById('epsilonValue').textContent = privacy.epsilon;
        
        // Assume budget goes up to 10 for progress bar
        const epsVal = Math.min((parseFloat(privacy.epsilon) / 10) * 100, 100);
        document.getElementById('epsilonFill').style.width = `${epsVal}%`;
    }

    await updateData();
    // Update every 30 seconds
    setInterval(updateData, 30000);
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

function displayResults(primaryName, primaryConf, topPredictions) {
    const panel = document.getElementById('resultsPanel');
    
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
