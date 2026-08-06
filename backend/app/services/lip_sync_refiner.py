from typing import Dict, Any, List

def refine_timing_with_lipsync(
    replicas: List[Dict],
    lip_curve: List[float],
    sample_rate: int = 30
) -> List[Dict]:
    """
    G-3.2 — Refine bracket timing using lip opening correlation.
    Improves synchronization on close-up shots.
    """
    refined = []
    
    for rep in replicas:
        start_frame = int(rep["start_ms"] / 1000 * sample_rate)
        end_frame = int(rep["end_ms"] / 1000 * sample_rate)
        
        if start_frame < len(lip_curve) and end_frame < len(lip_curve):
            # Find peak mouth opening in segment
            segment = lip_curve[start_frame:end_frame]
            if segment:
                peak_idx = segment.index(max(segment))
                new_start = (start_frame + peak_idx) * (1000 / sample_rate)
                rep = rep.copy()
                rep["start_ms"] = int(max(rep["start_ms"], new_start - 80))
        
        refined.append(rep)
    
    return refined
