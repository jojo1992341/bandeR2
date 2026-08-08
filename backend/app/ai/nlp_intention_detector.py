import re
from typing import Dict, Any


class NLPIntentionDetector:
    """
    Analyse textuelle NLP FR §8.2.5 (b)
    Détecte l'intention de la réplique à partir du texte transcrit.
    Labels : affirmation, question, ordre, hesitation, exclamation
    Source : texte
    Aucun appel externe requis en V1 — heuristiques FR déterministes,
    substituables par un modèle CamemBERT fine-tuné en V2.
    """

    INTENTIONS = ["affirmation", "question", "ordre", "hesitation", "exclamation"]

    # Mots-clés impératifs / ordre en FR (racines fréquentes doublage)
    ORDER_PATTERNS = [
        r"^(écoute|ecoute|regarde|viens|arrête|arrete|stop|tais-toi|taisez|donne|prends|vas-y|viens|pars|file|sors|rentre|reviens|attends|bouge|dégage|degage)",
        r"\b(écoute-moi|regarde-moi|viens ici|arrête ça|ne bouge pas|tais-toi)\b",
    ]

    HESITATION_PATTERNS = [
        r"\b(euh|heu|ben|bah|hmm|hum|eh ben|enfin)\b",
        r"\.\.\.",
        r"—\s*$",  # tiret en fin = suspension
        r"\b(je ne sais pas|peut-être|peut être|j'hésite)\b",
    ]

    def detect(self, text: str) -> Dict[str, Any]:
        if not text or not text.strip():
            return {
                "label": "affirmation",
                "score": 0.5,
                "source": "texte",
                "details": {"reason": "empty"},
            }

        t = text.strip()
        low = t.lower()

        # 1. Question : point d'interrogation ou tournure interrogative FR
        if t.endswith("?") or "?" in t:
            return {
                "label": "question",
                "score": 0.95 if t.endswith("?") else 0.80,
                "source": "texte",
                "details": {"cue": "?", "text": t},
            }

        # Interrogative lexicale sans "?"
        if re.search(r"\b(est-ce que|qu'est-ce que|qui|que|quoi|où|quand|comment|pourquoi|combien)\b.*\?$", low):
            return {"label": "question", "score": 0.85, "source": "texte", "details": {"cue": "interrogatif"}}

        # 2. Exclamation : "!" final ou emphase forte
        if t.endswith("!") or t.endswith("!!") or "!" in t:
            # distinguer ordre vs exclamation : ordre contient impératif + "!"
            for pat in self.ORDER_PATTERNS:
                if re.search(pat, low, re.IGNORECASE):
                    return {"label": "ordre", "score": 0.90, "source": "texte", "details": {"cue": "ordre+!"}}
            return {"label": "exclamation", "score": 0.92, "source": "texte", "details": {"cue": "!"}}
        
        # 3. Hésitation : euh/ben/... / suspension
        for pat in self.HESITATION_PATTERNS:
            if re.search(pat, low, re.IGNORECASE):
                return {"label": "hesitation", "score": 0.88, "source": "texte", "details": {"cue": pat}}

        # 4. Ordre sans "!" : impératif détecté
        for pat in self.ORDER_PATTERNS:
            if re.search(pat, low, re.IGNORECASE):
                return {"label": "ordre", "score": 0.82, "source": "texte", "details": {"cue": "imperatif"}}

        # 5. Téléphone / voix off cue -> reste affirmation mais annoté dans details pour typo suggestion
        if re.search(r"\b(off|téléphone|telephone|voix off|allo|allô)\b", low):
            return {"label": "affirmation", "score": 0.75, "source": "texte", "details": {"cue": "off/telephone"}}

        # Défaut : affirmation
        return {"label": "affirmation", "score": 0.70, "source": "texte", "details": {"cue": "default"}}

    def batch_detect(self, texts: list) -> list:
        return [self.detect(t) for t in texts]
