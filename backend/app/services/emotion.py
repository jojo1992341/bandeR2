from typing import Dict, Any, List
import re

EMOTION_KEYWORDS = {
    "colère": ["colère", "furieux", "énervé", "rage", "putain", "merde"],
    "joie": ["super", "génial", "magnifique", "heureux", "fantastique"],
    "tristesse": ["triste", "malheureux", "désolé", "peine", "pleurer"],
    "surprise": ["quoi", "ah", "oh", "incroyable", "sérieux"],
    "peur": ["peur", "effrayé", "terreur", "panique"],
    "dégoût": ["dégoûtant", "horrible", "beurk"]
}

INTENTION_KEYWORDS = {
    "question": ["?", "comment", "pourquoi", "quand", "où", "qui"],
    "ordre": ["!", "fais", "va", "viens", "arrête", "donne"],
    "suggestion": ["peut-être", "si", "pourquoi pas", "on pourrait"],
    "plainte": ["je n'aime pas", "c'est nul", "horrible"]
}

def detect_emotion_and_intention(replica: Dict[str, Any]) -> Dict[str, Any]:
    """
    G-2.3 — Emotion + Intention detection (acoustic + textual).
    Returns suggestions only (never auto-applies).
    """
    text = replica.get("text", "").lower()
    
    detected_emotions = []
    for emotion, keywords in EMOTION_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            detected_emotions.append(emotion)
    
    detected_intentions = []
    for intention, keywords in INTENTION_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            detected_intentions.append(intention)
    
    # Default values
    emotion = detected_emotions[0] if detected_emotions else "neutre"
    intention = detected_intentions[0] if detected_intentions else "affirmation"
    
    return {
        "emotion": emotion,
        "intention": intention,
        "suggestion": f"Code typographique suggéré : {emotion.upper()} + {intention}",
        "apply_automatically": False,  # Never auto-apply
        "confidence": 0.75
    }
