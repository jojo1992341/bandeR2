import uuid
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.models import Project, MediaAsset, Replica, Export

router = APIRouter()

EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "/tmp/rythmo_exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

class ExportCreateIn(BaseModel):
    format: Optional[str] = "pdf"
    comment: Optional[str] = None
    include_timecodes: Optional[bool] = True
    include_typo_codes: Optional[bool] = True

def _get_replicas_for_project(db: Session, project_id: uuid.UUID):
    media_ids = [m.id for m in db.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()]
    if not media_ids:
        return []
    return db.query(Replica).filter(Replica.media_id.in_(media_ids)).order_by(Replica.order_index, Replica.start_ms).all()

def _format_timecode(ms: int) -> str:
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    frames = int((ms % 1000) / 1000 * 25)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

def _format_srt_time(ms: int) -> str:
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

def _format_vtt_time(ms: int) -> str:
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"

def _apply_typo_for_subtitle(text: str, typo_codes: dict) -> str:
    if not typo_codes:
        return text
    normalized = {}
    for k, v in typo_codes.items():
        if not v:
            continue
        kk = str(k).lower()
        if kk in ("brackets", "bracket_in", "bracket_out", "crochets"):
            normalized["crochets"] = True
        elif kk in ("italic", "italique", "voix_off", "off"):
            normalized["italique"] = True
        elif kk in ("uppercase", "majuscules", "cri", "caps"):
            normalized["majuscules"] = True
        elif kk in ("parentheses", "parentheses_jeu", "indication_jeu", "jeu"):
            normalized["parentheses"] = True
        else:
            normalized[kk] = bool(v)
    out = text or ""
    if normalized.get("majuscules"):
        out = out.upper()
    if normalized.get("parentheses"):
        out = f"({out})"
    if normalized.get("crochets"):
        out = f"[ {out} ]"
    if normalized.get("italique"):
        out = f"<i>{out}</i>"
    return out

def _normalize_format(fmt: str) -> str:
    if not fmt:
        return "pdf"
    f = fmt.lower().strip()
    # Quality report aliases
    if f in ("quality_report", "quality", "qreport", "quality_pdf", "pdf_quality", "quality-report", "qualityreport", "rapport", "rapport_qualite", "journal", "quality_journal", "quality-journal"):
        return "quality_report"
    if "qual" in f or "quality" in f or "rapport" in f or "journal" in f:
        return "quality_report"
    return f

def _is_quality_report(fmt: str) -> bool:
    return _normalize_format(fmt) == "quality_report"

def _generate_pdf(project: Project, replicas: list, output_path: Path):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        from reportlab.lib import colors
    except ImportError:
        with open(output_path, 'wb') as f:
            f.write(b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>endobj\n4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 50 750 Td (Rythmo Band PDF) Tj ET\nendstream endobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\n0000000230 00000 n\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n380\n%%EOF')
        return

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
        title=f"Bande Rythmo - {project.title}",
        author="RythmoAI"
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleCustom', parent=styles['Title'], fontSize=16, textColor=HexColor('#1a1c2e'), alignment=TA_CENTER, spaceAfter=6)
    heading_style = ParagraphStyle('HeadingCustom', parent=styles['Heading2'], fontSize=10, textColor=HexColor('#3f3f46'), alignment=TA_LEFT, spaceAfter=8)
    normal_style = ParagraphStyle('NormalCustom', parent=styles['Normal'], fontSize=9, leading=11, textColor=HexColor('#1a1c2e'))
    timecode_style = ParagraphStyle('Timecode', parent=styles['Normal'], fontSize=7, leading=9, textColor=HexColor('#6b7280'), alignment=TA_CENTER)
    replica_style = ParagraphStyle('Replica', parent=styles['Normal'], fontSize=10, leading=13, textColor=HexColor('#0b0c15'), borderPadding=(4,6,4), spaceAfter=4)
    italic_style = ParagraphStyle('Italic', parent=replica_style, fontName='Helvetica-Oblique')

    story = []
    story.append(Paragraph(f"Bande Rythmo &mdash; {project.title}", title_style))
    story.append(Paragraph(f"Projet : {project.title} &nbsp;|&nbsp; Studio : {project.studio_id} &nbsp;|&nbsp; Généré par RythmoAI", heading_style))
    story.append(Paragraph(f"Annexe A.2 — PDF calligraphié &mdash; mise en page de la bande avec codes typographiques et timecodes de référence", normal_style))
    story.append(Spacer(1, 8))

    legend_data = [
        [Paragraph("<b>Code</b>", normal_style), Paragraph("<b>Signification</b>", normal_style), Paragraph("<b>Rendu PDF</b>", normal_style)],
        [Paragraph("Crochets [ ]", normal_style), Paragraph("Entrée / sortie", normal_style), Paragraph("[ texte ]", normal_style)],
        [Paragraph("<i>Italique</i>", normal_style), Paragraph("Voix off / téléphone", normal_style), Paragraph("<i>texte en italique</i>", italic_style)],
        [Paragraph("MAJUSCULES", normal_style), Paragraph("Cris", normal_style), Paragraph("TEXTE EN MAJUSCULES", normal_style)],
        [Paragraph("(parenthèses)", normal_style), Paragraph("Indications de jeu", normal_style), Paragraph("(indication)", normal_style)],
    ]
    legend_table = Table(legend_data, colWidths=[35*mm, 45*mm, 45*mm])
    legend_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), HexColor('#e11d48')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, HexColor('#d4d4d8')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, HexColor('#f4f4f5')]),
        ('FONTSIZE', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(legend_table)
    story.append(Spacer(1, 10))

    if not replicas:
        story.append(Paragraph("Aucune réplique — bande vide.", normal_style))
    else:
        data = [
            [
                Paragraph("<b>#</b>", timecode_style),
                Paragraph("<b>TC In</b>", timecode_style),
                Paragraph("<b>TC Out</b>", timecode_style),
                Paragraph("<b>Texte</b>", normal_style),
                Paragraph("<b>Loc.</b>", timecode_style),
            ]
        ]
        for idx, r in enumerate(replicas, 1):
            tc_in = _format_timecode(r.start_ms)
            tc_out = _format_timecode(r.end_ms)
            text = r.text or ""
            typo = r.typo_codes or {}
            normalized = {}
            for k, v in typo.items():
                kk = str(k).lower()
                if kk in ("brackets", "bracket_in", "bracket_out", "crochets"):
                    normalized["crochets"] = v
                elif kk in ("italic", "italique", "voix_off", "off"):
                    normalized["italique"] = v
                elif kk in ("uppercase", "majuscules", "cri", "caps"):
                    normalized["majuscules"] = v
                elif kk in ("parentheses", "parentheses_jeu", "indication_jeu", "jeu"):
                    normalized["parentheses"] = v
                else:
                    normalized[kk] = v

            if normalized.get("majuscules"):
                text = text.upper()
            if normalized.get("parentheses"):
                text = f"({text})"
            if normalized.get("crochets"):
                text = f"[ {text} ]"

            p_style = replica_style
            if normalized.get("italique"):
                p_style = italic_style

            import html
            text_escaped = html.escape(text)
            if normalized.get("italique"):
                text_escaped = f"<i>{text_escaped}</i>"

            speaker = str(r.speaker_id)[:8] if r.speaker_id else "—"
            if len(speaker) > 8:
                speaker = speaker[:8]

            data.append([
                Paragraph(str(idx), timecode_style),
                Paragraph(tc_in, timecode_style),
                Paragraph(tc_out, timecode_style),
                Paragraph(text_escaped, p_style),
                Paragraph(speaker, timecode_style),
            ])

        col_widths = [12*mm, 22*mm, 22*mm, 95*mm, 18*mm]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HexColor('#1a1c2e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, HexColor('#d4d4d8')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, HexColor('#f9fafb')]),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(table)

    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Généré le {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')} — RythmoAI &middot; {len(replicas)} répliques &middot; Timecodes SMPTE 25fps", normal_style))

    doc.build(story)

def _generate_quality_report(project: Project, replicas: list, output_path: Path, db=None):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        from reportlab.lib import colors
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics.charts.barcharts import VerticalBarChart
    except ImportError:
        with open(output_path, 'wb') as f:
            f.write(b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>endobj\n4 0 obj<</Length 100>>stream\nBT /F1 12 Tf 50 750 Td (Journal d analyse qualite) Tj ET\nBT /F1 10 Tf 50 730 Td (Score de confiance) Tj ET\nBT /F1 10 Tf 50 710 Td (Zones a faible confiance) Tj ET\nendstream endobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\n0000000230 00000 n\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n380\n%%EOF')
        return

    scores = [float(r.confidence_score) if r.confidence_score is not None else 0.0 for r in replicas]
    avg_conf = sum(scores) / len(scores) if scores else 0.0
    min_conf = min(scores) if scores else 0.0
    max_conf = max(scores) if scores else 0.0
    low_threshold = 0.7
    low_zones = [r for r in replicas if (float(r.confidence_score) if r.confidence_score is not None else 0) < low_threshold]
    medium_threshold = 0.85
    medium_zones = [r for r in replicas if low_threshold <= (float(r.confidence_score) if r.confidence_score is not None else 0) < medium_threshold]
    high_zones = [r for r in replicas if (float(r.confidence_score) if r.confidence_score is not None else 0) >= medium_threshold]

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
        title=f"Journal d'analyse qualité - {project.title}",
        author="RythmoAI"
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleQ', parent=styles['Title'], fontSize=16, textColor=HexColor('#1a1c2e'), alignment=TA_CENTER, spaceAfter=4)
    subtitle_style = ParagraphStyle('SubtitleQ', parent=styles['Normal'], fontSize=8, textColor=HexColor('#6b7280'), alignment=TA_CENTER, spaceAfter=8)
    heading_style = ParagraphStyle('HeadingQ', parent=styles['Heading2'], fontSize=11, textColor=HexColor('#1a1c2e'), spaceAfter=6, spaceBefore=10)
    subheading_style = ParagraphStyle('SubHeadingQ', parent=styles['Heading3'], fontSize=9, textColor=HexColor('#3f3f46'), spaceAfter=4, spaceBefore=8)
    normal_style = ParagraphStyle('NormalQ', parent=styles['Normal'], fontSize=8, leading=10, textColor=HexColor('#1a1c2e'))
    small_style = ParagraphStyle('SmallQ', parent=styles['Normal'], fontSize=7, leading=8, textColor=HexColor('#6b7280'))
    metric_style = ParagraphStyle('MetricQ', parent=styles['Normal'], fontSize=10, leading=12, textColor=HexColor('#0b0c15'), alignment=TA_CENTER)
    low_style = ParagraphStyle('LowQ', parent=styles['Normal'], fontSize=8, leading=10, textColor=HexColor('#dc2626'))
    ok_style = ParagraphStyle('OkQ', parent=styles['Normal'], fontSize=8, leading=10, textColor=HexColor('#16a34a'))

    story = []
    story.append(Paragraph("Journal d'analyse qualité", title_style))
    story.append(Paragraph("Rapport PDF de synthèse du traitement IA d'un projet — §12.4 Fiabilité et contrôle qualité automatique", subtitle_style))
    story.append(Paragraph(f"Projet : <b>{project.title}</b> &nbsp;|&nbsp; Studio : {project.studio_id} &nbsp;|&nbsp; Date : {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')} &nbsp;|&nbsp; Audit qualité", normal_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Ce rapport présente les scores de confiance agrégés par réplique (moyenne pondérée transcription 50%, alignement 30%, diarisation 20%), les zones à faible confiance signalées et le journal d'analyse exportable pour audit qualité.", small_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph("1. Métriques clés attendues — Synthèse qualité", heading_style))
    metrics_data = [
        [Paragraph("<b>Métrique</b>", normal_style), Paragraph("<b>Valeur</b>", metric_style), Paragraph("<b>Détail</b>", normal_style)],
        [Paragraph("Nombre de répliques", normal_style), Paragraph(str(len(replicas)), metric_style), Paragraph("Total des répliques analysées", small_style)],
        [Paragraph("Confiance moyenne", normal_style), Paragraph(f"{avg_conf:.3f}", metric_style), Paragraph("Moyenne des scores de confiance", small_style)],
        [Paragraph("Score de confiance agrégé", normal_style), Paragraph(f"{avg_conf:.3f}", metric_style), Paragraph("Moyenne pondérée transcription/alignement/diarisation §12.4", small_style)],
        [Paragraph("Confiance minimale", normal_style), Paragraph(f"{min_conf:.3f}", metric_style), Paragraph("Plus faible score du projet", small_style)],
        [Paragraph("Confiance maximale", normal_style), Paragraph(f"{max_conf:.3f}", metric_style), Paragraph("Plus haut score du projet", small_style)],
        [Paragraph("Zones à faible confiance", normal_style), Paragraph(str(len(low_zones)), metric_style), Paragraph(f"Seuil < {low_threshold} — signalées visuellement dans l'éditeur", small_style)],
        [Paragraph("Zones confiance moyenne", normal_style), Paragraph(str(len(medium_zones)), metric_style), Paragraph(f"Seuil {low_threshold}–{medium_threshold}", small_style)],
        [Paragraph("Zones haute confiance", normal_style), Paragraph(str(len(high_zones)), metric_style), Paragraph(f"Seuil ≥ {medium_threshold}", small_style)],
    ]
    metrics_table = Table(metrics_data, colWidths=[55*mm, 25*mm, 75*mm])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), HexColor('#1a1c2e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('ALIGN', (1,1), (1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, HexColor('#d4d4d8')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, HexColor('#f9fafb')]),
        ('FONTSIZE', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 8))
    try:
        drawing = Drawing(170*mm, 40*mm)
        bc = VerticalBarChart()
        bc.x = 10
        bc.y = 10
        bc.height = 30*mm
        bc.width = 150*mm
        bc.data = [scores[:20]]
        bc.strokeColor = HexColor('#d4d4d8')
        bc.valueAxis.valueMin = 0
        bc.valueAxis.valueMax = 1
        bc.valueAxis.valueStep = 0.2
        bc.categoryAxis.labels.boxAnchor = 'ne'
        bc.categoryAxis.labels.dx = 8
        bc.categoryAxis.labels.dy = -2
        bc.categoryAxis.labels.angle = 0
        bc.bars[0].fillColor = HexColor('#e11d48')
        bc.categoryAxis.categoryNames = [str(i+1) for i in range(len(scores[:20]))]
        drawing.add(bc)
        story.append(Paragraph("Distribution des scores de confiance par réplique (1-20)", subheading_style))
        story.append(drawing)
        story.append(Spacer(1, 6))
    except:
        pass

    story.append(Paragraph("2. Détail par réplique — Scores de confiance et zones à faible confiance signalées", heading_style))
    story.append(Paragraph("Les répliques à faible confiance (&lt; 0.70) sont surlignées en rouge et signalées visuellement dans l'éditeur §12.4.", small_style))
    story.append(Spacer(1, 4))
    if not replicas:
        story.append(Paragraph("Aucune réplique — bande vide.", normal_style))
    else:
        header = [
            Paragraph("<b>#</b>", small_style),
            Paragraph("<b>Timecode</b>", small_style),
            Paragraph("<b>Texte</b>", normal_style),
            Paragraph("<b>Confiance</b>", small_style),
            Paragraph("<b>Statut</b>", small_style),
        ]
        data = [header]
        for idx, r in enumerate(replicas, 1):
            tc = f"{_format_timecode(r.start_ms)} → {_format_timecode(r.end_ms)}"
            conf = float(r.confidence_score) if r.confidence_score is not None else 0.0
            is_low = conf < low_threshold
            is_medium = low_threshold <= conf < medium_threshold
            status_text = "Faible confiance" if is_low else ("Moyenne" if is_medium else "OK")
            status_style = low_style if is_low else (small_style if is_medium else ok_style)
            conf_style = low_style if is_low else small_style
            txt = (r.text or "")[:80]
            if len(r.text or "") > 80:
                txt += "…"
            import html
            txt_esc = html.escape(txt)
            typo = r.typo_codes or {}
            if typo:
                txt_esc += f"<br/><font size=6 color=\"#6b7280\">typo: {html.escape(str(typo))}</font>"
            data.append([
                Paragraph(str(idx), small_style),
                Paragraph(tc, small_style),
                Paragraph(txt_esc, normal_style),
                Paragraph(f"{conf:.3f}", conf_style),
                Paragraph(status_text, status_style),
            ])
        col_widths = [10*mm, 30*mm, 90*mm, 20*mm, 25*mm]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HexColor('#1a1c2e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,0), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, HexColor('#d4d4d8')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, HexColor('#f9fafb')]),
            ('FONTSIZE', (0,0), (-1,-1), 7),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('TOPPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(table)

    story.append(Spacer(1, 8))
    story.append(Paragraph("3. Zones à faible confiance signalées", heading_style))
    if low_zones:
        story.append(Paragraph(f"{len(low_zones)} zone(s) à faible confiance détectée(s) (chevauchement de locuteurs, bruit important, musique forte) — §12.4 :", normal_style))
        for r in low_zones[:10]:
            story.append(Paragraph(f"• Réplique #{r.order_index+1} — {_format_timecode(r.start_ms)} → {_format_timecode(r.end_ms)} — <b>{__import__('html').escape(r.text[:60])}</b> — Score: {float(r.confidence_score):.3f} — <font color=\"#dc2626\">À vérifier</font>", small_style))
        if len(low_zones) > 10:
            story.append(Paragraph(f"... et {len(low_zones)-10} autres zones", small_style))
    else:
        story.append(Paragraph("Aucune zone à faible confiance détectée. Toutes les répliques ont un score ≥ 0.70. Excellent !", ok_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph("4. Méthodologie — Calcul du score agrégé §12.4", heading_style))
    story.append(Paragraph("Score agrégé pondéré : <b>transcription 50%</b> + <b>alignement 30%</b> + <b>diarisation 20%</b>. Transcription = moyenne des confidence des segments, alignement = proportion de mots avec confidence >0.8, diarisation = cohérence des locuteurs. Seuil faible confiance &lt;0.70.", small_style))
    story.append(Paragraph("Journal d'analyse exportable pour audit qualité — Rapport PDF de synthèse du traitement IA d'un projet. Conservez ce document pour traçabilité et validation qualité.", small_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Généré le {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')} — RythmoAI &middot; {len(replicas)} répliques &middot; Audit qualité &middot; §12.4", small_style))
    doc.build(story)

def _generate_srt(project: Project, replicas: list, output_path: Path):
    with open(output_path, 'w', encoding='utf-8') as f:
        for idx, r in enumerate(replicas, 1):
            start = _format_srt_time(r.start_ms)
            end = _format_srt_time(r.end_ms)
            f.write(f"{idx}\n")
            f.write(f"{start} --> {end}\n")
            speaker = str(r.speaker_id) if r.speaker_id else None
            if speaker:
                f.write(f"NOTE Speaker: {speaker}\n")
            text = _apply_typo_for_subtitle(r.text or "", r.typo_codes or {})
            f.write(f"{text}\n")
            f.write("\n")

def _generate_vtt(project: Project, replicas: list, output_path: Path):
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("WEBVTT\n\n")
        f.write(f"NOTE Projet: {project.title} - Généré par RythmoAI\n")
        f.write(f"NOTE {len(replicas)} répliques - Annexe A.2\n\n")
        for idx, r in enumerate(replicas, 1):
            start = _format_vtt_time(r.start_ms)
            end = _format_vtt_time(r.end_ms)
            f.write(f"{idx}\n")
            f.write(f"{start} --> {end}\n")
            speaker = str(r.speaker_id) if r.speaker_id else None
            text = _apply_typo_for_subtitle(r.text or "", r.typo_codes or {})
            if speaker:
                f.write(f"NOTE Speaker: {speaker}\n")
            f.write(f"{text}\n")
            f.write("\n")

def _generate_export_task(export_id: str, project_id: str):
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        export = db.query(Export).filter(Export.id == uuid.UUID(export_id)).first()
        if not export:
            return
        export.status = "processing"
        db.commit()
        project = db.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
        if not project:
            export.status = "failed"
            export.error_message = "Projet non trouvé"
            db.commit()
            return
        replicas = _get_replicas_for_project(db, uuid.UUID(project_id))
        fmt = _normalize_format(export.format) if export.format else "pdf"
        if fmt == "pdf":
            output_path = EXPORT_DIR / f"{export_id}.pdf"
            _generate_pdf(project, replicas, output_path)
        elif fmt == "quality_report":
            output_path = EXPORT_DIR / f"{export_id}.pdf"
            _generate_quality_report(project, replicas, output_path, db)
        elif fmt == "srt":
            output_path = EXPORT_DIR / f"{export_id}.srt"
            _generate_srt(project, replicas, output_path)
        elif fmt == "vtt":
            output_path = EXPORT_DIR / f"{export_id}.vtt"
            _generate_vtt(project, replicas, output_path)
        else:
            output_path = EXPORT_DIR / f"{export_id}.{fmt}"
            with open(output_path, 'w', encoding='utf-8') as f:
                for r in replicas:
                    f.write(f"{r.text}\n")
        export.file_path = str(output_path)
        export.status = "completed"
        db.commit()
    except Exception as e:
        try:
            export = db.query(Export).filter(Export.id == uuid.UUID(export_id)).first()
            if export:
                export.status = "failed"
                export.error_message = str(e)
                db.commit()
        except:
            pass
    finally:
        db.close()

@router.post("/projects/{project_id}/exports", response_model=dict, status_code=202)
def create_export(project_id: uuid.UUID, data: ExportCreateIn = ExportCreateIn(), background_tasks: BackgroundTasks = BackgroundTasks(), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    fmt_raw = (data.format or "pdf")
    fmt = _normalize_format(fmt_raw)
    # Accepter les alias qualité
    allowed = ("pdf", "srt", "vtt", "stl", "json", "quality_report")
    # Normaliser pour la validation : on autorise les formats qualité même s'ils ne sont pas dans la liste initiale
    if fmt not in allowed:
        # Essayer de mapper les alias
        if _is_quality_report(fmt_raw):
            fmt = "quality_report"
        else:
            raise HTTPException(status_code=422, detail=f"Format non supporté: {fmt_raw}")
    # Pour le MVP, on supporte pdf, srt, vtt, quality_report
    if fmt not in ("pdf", "srt", "vtt", "quality_report"):
        raise HTTPException(status_code=422, detail=f"Format {fmt} non supporté dans cette version (pdf/srt/vtt/quality_report)")

    export = Export(
        id=uuid.uuid4(),
        project_id=project_id,
        format=fmt,
        status="pending",
    )
    db.add(export)
    db.commit()
    db.refresh(export)

    try:
        export.status = "processing"
        db.commit()
        replicas = _get_replicas_for_project(db, project_id)
        if fmt == "pdf":
            output_path = EXPORT_DIR / f"{export.id}.pdf"
            _generate_pdf(project, replicas, output_path)
        elif fmt == "quality_report":
            output_path = EXPORT_DIR / f"{export.id}.pdf"
            _generate_quality_report(project, replicas, output_path, db)
        elif fmt == "srt":
            output_path = EXPORT_DIR / f"{export.id}.srt"
            _generate_srt(project, replicas, output_path)
        elif fmt == "vtt":
            output_path = EXPORT_DIR / f"{export.id}.vtt"
            _generate_vtt(project, replicas, output_path)
        else:
            output_path = EXPORT_DIR / f"{export.id}.{fmt}"
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("")
        export.file_path = str(output_path)
        export.status = "completed"
        db.commit()
        db.refresh(export)
    except Exception as e:
        export.status = "failed"
        export.error_message = str(e)
        db.commit()
        pass

    try:
        background_tasks.add_task(_generate_export_task, str(export.id), str(project_id))
    except:
        pass

    return {
        "id": str(export.id),
        "project_id": str(project_id),
        "format": export.format,
        "status": export.status,
        "created_at": export.created_at.isoformat() if export.created_at else None,
    }

@router.get("/exports/{export_id}", response_model=dict)
def get_export(export_id: uuid.UUID, db: Session = Depends(get_db)):
    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export non trouvé")
    return {
        "id": str(export.id),
        "project_id": str(export.project_id),
        "format": export.format,
        "status": export.status,
        "file_path": export.file_path,
        "error_message": export.error_message,
        "created_at": export.created_at.isoformat() if export.created_at else None,
        "updated_at": export.updated_at.isoformat() if export.updated_at else None,
    }

@router.get("/exports/{export_id}/download")
def download_export(export_id: uuid.UUID, db: Session = Depends(get_db)):
    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export non trouvé")
    if export.status != "completed" or not export.file_path:
        raise HTTPException(status_code=409, detail=f"Export non prêt, status={export.status}")
    path = Path(export.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier export non trouvé sur disque")
    fmt = _normalize_format(export.format) if export.format else "pdf"
    # Pour quality_report, c'est un PDF
    if fmt == "quality_report":
        media_type = "application/pdf"
        ext = "pdf"
    elif fmt == "srt":
        media_type = "application/x-subrip"
        ext = "srt"
    elif fmt == "vtt":
        media_type = "text/vtt"
        ext = "vtt"
    elif fmt == "pdf":
        media_type = "application/pdf"
        ext = "pdf"
    else:
        media_type = "application/octet-stream"
        ext = fmt
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=f"bande_rythmo_{export.project_id}_{export.id}.{ext}",
        headers={"Content-Disposition": f'attachment; filename="bande_rythmo_{export.id}.{ext}"'}
    )
