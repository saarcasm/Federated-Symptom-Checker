import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os
from typing import List, Dict, Any
import torch
import torch.nn.functional as F
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import get_model

app = FastAPI(title="Privacy-Preserving Federated Symptom Checker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants (131 symptoms matching SymptomMLP input vocabulary)
SYMPTOM_LIST = [
    "itching", "skin_rash", "nodal_skin_eruptions", "continuous_sneezing", "shivering",
    "chills", "joint_pain", "stomach_pain", "acidity", "ulcers_on_tongue", "muscle_wasting",
    "vomiting", "burning_micturition", "spotting_urination", "fatigue", "weight_gain",
    "anxiety", "cold_hands_and_feets", "mood_swings", "weight_loss", "restlessness",
    "lethargy", "patches_in_throat", "irregular_sugar_level", "cough", "high_fever",
    "sunken_eyes", "breathlessness", "sweating", "dehydration", "indigestion", "headache",
    "yellowish_skin", "dark_urine", "nausea", "loss_of_appetite", "pain_behind_the_eyes",
    "back_pain", "constipation", "abdominal_pain", "diarrhoea", "mild_fever", "yellow_urine",
    "yellowing_of_eyes", "acute_liver_failure", "fluid_overload", "swelling_of_stomach",
    "swelled_lymph_nodes", "malaise", "blurred_and_distorted_vision", "phlegm",
    "throat_irritation", "redness_of_eyes", "sinus_pressure", "runny_nose", "congestion",
    "chest_pain", "weakness_in_limbs", "fast_heart_rate", "pain_during_bowel_movements",
    "pain_in_anal_region", "bloody_stool", "irritation_in_anus", "neck_pain", "dizziness",
    "cramps", "bruising", "obesity", "swollen_legs", "swollen_blood_vessels",
    "puffy_face_and_eyes", "enlarged_thyroid", "brittle_nails", "swollen_extremeties",
    "excessive_hunger", "extra_marital_contacts", "drying_and_tingling_lips",
    "slurred_speech", "knee_pain", "hip_joint_pain", "muscle_weakness", "stiff_neck",
    "swelling_joints", "movement_stiffness", "spinning_movements", "loss_of_balance",
    "unsteadiness", "weakness_of_one_body_side", "loss_of_smell", "bladder_discomfort",
    "foul_smell_of_urine", "continuous_feel_of_urine", "passage_of_gases", "internal_itching",
    "toxic_look_typhos", "depression", "irritability", "muscle_pain", "altered_sensorium",
    "red_spots_over_body", "belly_pain", "abnormal_menstruation", "dischromic_patches",
    "watering_from_eyes", "increased_appetite", "polyuria", "family_history", "mucoid_sputum",
    "rusty_sputum", "lack_of_concentration", "visual_disturbances", "receiving_blood_transfusion",
    "receiving_unsterile_injections", "coma", "stomach_bleeding", "distention_of_abdomen",
    "history_of_alcohol_consumption", "blood_in_sputum", "prominent_veins_on_calf",
    "palpitations", "painful_walking", "pus_filled_pimples", "blackheads", "scurring",
    "skin_peeling", "silver_like_dusting", "small_dents_in_nails", "inflammatory_nails",
    "blister", "red_sore_around_nose", "yellow_crust_ooze"
]

DISEASE_LIST = [
    "Fungal infection", "Allergy", "GERD", "Chronic cholestasis", "Drug Reaction",
    "Peptic ulcer diseae", "AIDS", "Diabetes", "Gastroenteritis", "Bronchial Asthma",
    "Hypertension", "Migraine", "Cervical spondylosis", "Paralysis (brain hemorrhage)",
    "Jaundice", "Malaria", "Chicken pox", "Dengue", "Typhoid", "hepatitis A",
    "Hepatitis B", "Hepatitis C", "Hepatitis D", "Hepatitis E", "Alcoholic hepatitis",
    "Tuberculosis", "Common Cold", "Pneumonia", "Dimorphic hemmorhoids(piles)",
    "Heart attack", "Varicose veins", "Hypothyroidism", "Hyperthyroidism", "Hypoglycemia",
    "Osteoarthristis", "Arthritis", "(vertigo) Paroymsal  Positional Vertigo", "Acne",
    "Urinary tract infection", "Psoriasis", "Impetigo"
]

SKIN_LESION_LIST = ["Actinic keratoses (akiec)", "Basal cell carcinoma (bcc)", "Benign keratosis (bkl)", "Dermatofibroma (df)", "Melanoma (mel)", "Melanocytic nevi (nv)", "Vascular lesions (vasc)"]
RESPIRATORY_COND_LIST = ["Normal", "Crackle detected", "Wheeze detected", "Both Crackle & Wheeze"]

# Global model state
models = {}
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def load_latest_checkpoint(model_name: str, checkpoint_dir: str = "results/checkpoints") -> torch.nn.Module:
    model = get_model(model_name).to(device)
    ckpt_path = Path(checkpoint_dir) / "global_model_latest.npy"
    if ckpt_path.exists():
        params = np.load(ckpt_path, allow_pickle=True)
        # Check if length matches
        model_state = model.state_dict()
        if len(params) == len(model_state):
            state_dict = {}
            for k, p in zip(model_state.keys(), params):
                state_dict[k] = torch.tensor(p)
            model.load_state_dict(state_dict)
    model.eval()
    return model

@app.on_event("startup")
async def startup_event():
    print("Starting API Server and loading models...")
    models['symptom_mlp'] = load_latest_checkpoint('symptom_mlp')
    models['skin_cnn'] = load_latest_checkpoint('skin_cnn')
    models['respiratory_cnn'] = load_latest_checkpoint('respiratory_cnn')

class SymptomRequest(BaseModel):
    symptoms: List[str]

@app.post("/predict/symptoms")
async def predict_symptoms(request: SymptomRequest) -> Dict[str, Any]:
    if not request.symptoms:
        raise HTTPException(status_code=400, detail="Symptoms list cannot be empty")
        
    # Feature vector creation
    features = torch.zeros((1, len(SYMPTOM_LIST)), device=device)
    for sym in request.symptoms:
        if sym in SYMPTOM_LIST:
            idx = SYMPTOM_LIST.index(sym)
            features[0, idx] = 1.0
            
    model = models.get('symptom_mlp')
    if not model:
        raise HTTPException(status_code=500, detail="Model not loaded")
        
    with torch.no_grad():
        output = model(features)
        probs = F.softmax(output, dim=1)[0].cpu().numpy()
        
    top_pred_idx = np.argmax(probs)
    
    top_predictions = [
        {"disease": DISEASE_LIST[i], "probability": float(probs[i])}
        for i in range(len(probs))
    ]
    top_predictions.sort(key=lambda x: x["probability"], reverse=True)
    
    return {
        "disease": DISEASE_LIST[top_pred_idx],
        "confidence": float(probs[top_pred_idx]),
        "top_predictions": top_predictions
    }

@app.post("/predict/skin")
async def predict_skin(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an image.")
        
    # Dummy processing for example
    content = await file.read()
    # In reality: image = Image.open(io.BytesIO(content)); transform(image)
    
    # Dummy input
    dummy_input = torch.randn(1, 3, 224, 224, device=device)
    
    model = models.get('skin_cnn')
    with torch.no_grad():
        output = model(dummy_input)
        probs = F.softmax(output, dim=1)[0].cpu().numpy()
        
    top_pred_idx = np.argmax(probs)
    
    top_predictions = [
        {"disease": SKIN_LESION_LIST[i], "probability": float(probs[i])}
        for i in range(len(probs))
    ]
    top_predictions.sort(key=lambda x: x["probability"], reverse=True)
    
    return {
        "lesion_type": SKIN_LESION_LIST[top_pred_idx],
        "confidence": float(probs[top_pred_idx]),
        "top_predictions": top_predictions
    }

@app.post("/predict/respiratory")
async def predict_respiratory(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.content_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload audio.")
        
    content = await file.read()
    # Dummy processing
    dummy_input = torch.randn(1, 1, 128, 128, device=device)
    
    model = models.get('respiratory_cnn')
    with torch.no_grad():
        output = model(dummy_input)
        probs = F.softmax(output, dim=1)[0].cpu().numpy()
        
    top_pred_idx = np.argmax(probs)
    
    top_predictions = [
        {"condition": RESPIRATORY_COND_LIST[i], "probability": float(probs[i])}
        for i in range(len(probs))
    ]
    top_predictions.sort(key=lambda x: x["probability"], reverse=True)
    
    return {
        "condition": RESPIRATORY_COND_LIST[top_pred_idx],
        "confidence": float(probs[top_pred_idx]),
        "top_predictions": top_predictions
    }

@app.get("/model/status")
async def get_model_status() -> Dict[str, Any]:
    return {
        "current_round": 20, # Simulated
        "total_rounds": 20,
        "global_accuracy": 0.85,
        "num_clients": 10
    }

@app.get("/privacy/budget")
async def get_privacy_budget() -> Dict[str, Any]:
    return {
        "epsilon": 2.0,
        "delta": 1e-5,
        "noise_multiplier": 1.5,
        "max_grad_norm": 1.0
    }

@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.api_server:app", host="0.0.0.0", port=8000, reload=True)
