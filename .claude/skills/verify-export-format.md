# verify-export-format

**Objectif** : Valide un fichier exporté (SRT, VTT, PDF, EBU-STL) contre son format.

## Étapes
1. Génère l'export via l'API
2. Parse le fichier avec un validateur de référence
3. Vérifie les timecodes à la milliseconde
4. Vérifie les codes typographiques
