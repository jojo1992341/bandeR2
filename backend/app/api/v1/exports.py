import uuid
import os
import struct
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.rbac import get_optional_user_payload, is_risky_role
from app.core.rate_limit import export_rate_limit_dep
from app.core.audit import record_audit_log, check_download_anomalies
from app.models import Project, MediaAsset, Replica, Export, Studio

router = APIRouter()

EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "/tmp/rythmo_exports"))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


class ExportCreateIn(BaseModel):
    format: Optional[str] = "pdf"
    comment: Optional[str] = None
    include_timecodes: Optional[bool] = True
    include_typo_codes: Optional[bool] = True


def _get_replicas_for_project(db: Session, project_id: uuid.UUID):
    media_ids = [
        m.id
        for m in db.query(MediaAsset)
        .filter(MediaAsset.project_id == project_id)
        .all()
    ]
    if not media_ids:
        return []
    return (
        db.query(Replica)
        .filter(Replica.media_id.in_(media_ids))
        .order_by(Replica.order_index, Replica.start_ms)
        .all()
    )


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
        elif kk in (
            "parentheses",
            "parentheses_jeu",
            "indication_jeu",
            "jeu",
        ):
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
    if f in (
        "quality_report",
        "quality",
        "qreport",
        "quality_pdf",
        "pdf_quality",
        "quality-report",
        "qualityreport",
        "rapport",
        "rapport_qualite",
        "journal",
        "quality_journal",
        "quality-journal",
    ):
        return "quality_report"
    if "qual" in f or "quality" in f or "rapport" in f or "journal" in f:
        return "quality_report"
    # EBU-STL aliases (Annexe A.2)
    low = f.lower().strip().lstrip(".")
    if low in ("stl", "ebu-stl", "ebu_stl", "ebu-stl-etendu", "ebu_stl_etendu", "ebu-stlextended", "stl_extended", "ebu", "ebu-stl_extended", "stl-etendu"):
        return "stl"
    if "ebu" in low and "stl" in low:
        return "stl"
    if low == "stl":
        return "stl"
    # Cavena aliases
    if low in ("cavena", "cav", "cavena/lrd", "cavena_lrd", "cavena-rythmo"):
        return "cavena"
    if low == "cavena":
        return "cavena"
    # .rythmo aliases (proprietary reconstituted)
    if low in ("rythmo", ".rythmo", "lrd", "rythmoai", "rythmo_ai", "cavena/.rythmo", "cavena_rythmo"):
        return "rythmo"
    if low.startswith(".rythmo") or low == "rythmo":
        return "rythmo"
    if low.endswith(".rythmo"):
        return "rythmo"
    # Handles with dot or slash
    if low.replace("-", "_").replace(".", "_").replace("/", "_") in ("ebu_stl", "ebu_stl_etendu", "stl_etendu"):
        return "stl"
    if low.replace("-", "_").replace(".", "_") in ("cavena", "cav"):
        return "cavena"
    if low.replace("-", "_").replace(".", "_") in ("rythmo", "rythmo_ai"):
        return "rythmo"
    return f


def _is_quality_report(fmt: str) -> bool:
    return _normalize_format(fmt) == "quality_report"


def _get_watermark_text(
    created_by: str, creator_role: str, created_at: datetime = None
) -> str:
    dt = created_at or datetime.now(timezone.utc)
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M:%S")
    return f"WATERMARK — RythmoAI — {created_by} ({creator_role}) — {date_str} {time_str}"


def _generate_pdf(
    project: Project,
    replicas: list,
    output_path: Path,
    watermark_text: Optional[str] = None,
):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        from reportlab.lib import colors
    except ImportError:
        with open(output_path, "wb") as f:
            wm = (
                f" BT /F1 10 Tf 50 710 Td ({watermark_text}) Tj ET"
                if watermark_text
                else ""
            )
            f.write(
                (
                    f"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>endobj\n4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 50 750 Td (Rythmo Band PDF) Tj ET{wm}\nendstream endobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\n0000000230 00000 n\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n380\n%%EOF"
                ).encode("utf-8")
            )
        return

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Bande Rythmo - {project.title}",
        author="RythmoAI",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontSize=16,
        textColor=HexColor("#1a1c2e"),
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    heading_style = ParagraphStyle(
        "HeadingCustom",
        parent=styles["Heading2"],
        fontSize=10,
        textColor=HexColor("#3f3f46"),
        alignment=TA_LEFT,
        spaceAfter=8,
    )
    normal_style = ParagraphStyle(
        "NormalCustom",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
        textColor=HexColor("#1a1c2e"),
    )
    timecode_style = ParagraphStyle(
        "Timecode",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
        textColor=HexColor("#6b7280"),
        alignment=TA_CENTER,
    )
    replica_style = ParagraphStyle(
        "Replica",
        parent=styles["Normal"],
        fontSize=10,
        leading=13,
        textColor=HexColor("#0b0c15"),
        borderPadding=(4, 6, 4),
        spaceAfter=4,
    )
    italic_style = ParagraphStyle(
        "Italic", parent=replica_style, fontName="Helvetica-Oblique"
    )

    story = []
    if watermark_text:
        wm_banner_style = ParagraphStyle(
            "WatermarkBanner",
            parent=styles["Normal"],
            fontSize=10,
            textColor=HexColor("#dc2626"),
            alignment=TA_CENTER,
            spaceAfter=10,
        )
        story.append(
            Paragraph(
                f"<b>[FILIGRANE CONFIDENTIEL : {watermark_text}]</b>",
                wm_banner_style,
            )
        )

    story.append(Paragraph(f"Bande Rythmo &mdash; {project.title}", title_style))
    story.append(
        Paragraph(
            f"Projet : {project.title} &nbsp;|&nbsp; Studio : {project.studio_id} &nbsp;|&nbsp; Généré par RythmoAI",
            heading_style,
        )
    )
    story.append(
        Paragraph(
            f"Annexe A.2 — PDF calligraphié &mdash; mise en page de la bande avec codes typographiques et timecodes de référence",
            normal_style,
        )
    )
    story.append(Spacer(1, 8))

    legend_data = [
        [
            Paragraph("<b>Code</b>", normal_style),
            Paragraph("<b>Signification</b>", normal_style),
            Paragraph("<b>Rendu PDF</b>", normal_style),
        ],
        [
            Paragraph("Crochets [ ]", normal_style),
            Paragraph("Entrée / sortie", normal_style),
            Paragraph("[ texte ]", normal_style),
        ],
        [
            Paragraph("<i>Italique</i>", normal_style),
            Paragraph("Voix off / téléphone", normal_style),
            Paragraph("<i>texte en italique</i>", italic_style),
        ],
        [
            Paragraph("MAJUSCULES", normal_style),
            Paragraph("Cris", normal_style),
            Paragraph("TEXTE EN MAJUSCULES", normal_style),
        ],
        [
            Paragraph("(parenthèses)", normal_style),
            Paragraph("Indications de jeu", normal_style),
            Paragraph("(indication)", normal_style),
        ],
    ]
    legend_table = Table(legend_data, colWidths=[35 * mm, 45 * mm, 45 * mm])
    legend_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e11d48")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d4d4d8")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, HexColor("#f4f4f5")],
                ),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
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
                elif kk in (
                    "parentheses",
                    "parentheses_jeu",
                    "indication_jeu",
                    "jeu",
                ):
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

            data.append(
                [
                    Paragraph(str(idx), timecode_style),
                    Paragraph(tc_in, timecode_style),
                    Paragraph(tc_out, timecode_style),
                    Paragraph(text_escaped, p_style),
                    Paragraph(speaker, timecode_style),
                ]
            )

        col_widths = [12 * mm, 22 * mm, 22 * mm, 95 * mm, 18 * mm]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#1a1c2e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d4d4d8")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, HexColor("#f9fafb")],
                    ),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(table)

    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            f"Généré le {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')} — RythmoAI &middot; {len(replicas)} répliques &middot; Timecodes SMPTE 25fps",
            normal_style,
        )
    )

    if watermark_text:

        def draw_wm(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 20)
            canvas.setFillColorRGB(0.85, 0.2, 0.2, alpha=0.3)
            canvas.translate(250, 420)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, watermark_text)
            canvas.restoreState()

        doc.build(story, onFirstPage=draw_wm, onLaterPages=draw_wm)
    else:
        doc.build(story)


def _generate_quality_report(
    project: Project,
    replicas: list,
    output_path: Path,
    db=None,
    watermark_text: Optional[str] = None,
):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        from reportlab.lib import colors
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics.charts.barcharts import VerticalBarChart
    except ImportError:
        with open(output_path, "wb") as f:
            wm = (
                f" BT /F1 10 Tf 50 710 Td ({watermark_text}) Tj ET"
                if watermark_text
                else ""
            )
            f.write(
                (
                    f"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>endobj\n4 0 obj<</Length 100>>stream\nBT /F1 12 Tf 50 750 Td (Journal d analyse qualite) Tj ET\nBT /F1 10 Tf 50 730 Td (Score de confiance) Tj ET\nBT /F1 10 Tf 50 710 Td (Zones a faible confiance) Tj ET{wm}\nendstream endobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\n0000000230 00000 n\ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n380\n%%EOF"
                ).encode("utf-8")
            )
        return

    scores = [
        float(r.confidence_score) if r.confidence_score is not None else 0.0
        for r in replicas
    ]
    avg_conf = sum(scores) / len(scores) if scores else 0.0
    min_conf = min(scores) if scores else 0.0
    max_conf = max(scores) if scores else 0.0
    low_threshold = 0.7
    low_zones = [
        r
        for r in replicas
        if (
            float(r.confidence_score)
            if r.confidence_score is not None
            else 0
        )
        < low_threshold
    ]
    medium_threshold = 0.85
    medium_zones = [
        r
        for r in replicas
        if low_threshold
        <= (
            float(r.confidence_score)
            if r.confidence_score is not None
            else 0
        )
        < medium_threshold
    ]
    high_zones = [
        r
        for r in replicas
        if (
            float(r.confidence_score)
            if r.confidence_score is not None
            else 0
        )
        >= medium_threshold
    ]

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Journal d'analyse qualité - {project.title}",
        author="RythmoAI",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleQ",
        parent=styles["Title"],
        fontSize=16,
        textColor=HexColor("#1a1c2e"),
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleQ",
        parent=styles["Normal"],
        fontSize=8,
        textColor=HexColor("#6b7280"),
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    heading_style = ParagraphStyle(
        "HeadingQ",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=HexColor("#1a1c2e"),
        spaceAfter=6,
        spaceBefore=10,
    )
    subheading_style = ParagraphStyle(
        "SubHeadingQ",
        parent=styles["Heading3"],
        fontSize=9,
        textColor=HexColor("#3f3f46"),
        spaceAfter=4,
        spaceBefore=8,
    )
    normal_style = ParagraphStyle(
        "NormalQ",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=HexColor("#1a1c2e"),
    )
    small_style = ParagraphStyle(
        "SmallQ",
        parent=styles["Normal"],
        fontSize=7,
        leading=8,
        textColor=HexColor("#6b7280"),
    )
    metric_style = ParagraphStyle(
        "MetricQ",
        parent=styles["Normal"],
        fontSize=10,
        leading=12,
        textColor=HexColor("#0b0c15"),
        alignment=TA_CENTER,
    )
    low_style = ParagraphStyle(
        "LowQ",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=HexColor("#dc2626"),
    )
    ok_style = ParagraphStyle(
        "OkQ",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=HexColor("#16a34a"),
    )

    story = []
    if watermark_text:
        wm_style = ParagraphStyle(
            "WatermarkBanner",
            parent=styles["Normal"],
            fontSize=10,
            textColor=HexColor("#dc2626"),
            alignment=TA_CENTER,
            spaceAfter=10,
        )
        story.append(
            Paragraph(
                f"<b>[FILIGRANE CONFIDENTIEL : {watermark_text}]</b>", wm_style
            )
        )

    story.append(Paragraph("Journal d'analyse qualité", title_style))
    story.append(
        Paragraph(
            "Rapport PDF de synthèse du traitement IA d'un projet — §12.4 Fiabilité et contrôle qualité automatique",
            subtitle_style,
        )
    )
    story.append(
        Paragraph(
            f"Projet : <b>{project.title}</b> &nbsp;|&nbsp; Studio : {project.studio_id} &nbsp;|&nbsp; Date : {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')} &nbsp;|&nbsp; Audit qualité",
            normal_style,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "Ce rapport présente les scores de confiance agrégés par réplique (moyenne pondérée transcription 50%, alignement 30%, diarisation 20%), les zones à faible confiance signalées et le journal d'analyse exportable pour audit qualité.",
            small_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "1. Métriques clés attendues — Synthèse qualité", heading_style
        )
    )
    metrics_data = [
        [
            Paragraph("<b>Métrique</b>", normal_style),
            Paragraph("<b>Valeur</b>", metric_style),
            Paragraph("<b>Détail</b>", normal_style),
        ],
        [
            Paragraph("Nombre de répliques", normal_style),
            Paragraph(str(len(replicas)), metric_style),
            Paragraph("Total des répliques analysées", small_style),
        ],
        [
            Paragraph("Confiance moyenne", normal_style),
            Paragraph(f"{avg_conf:.3f}", metric_style),
            Paragraph("Moyenne des scores de confiance", small_style),
        ],
        [
            Paragraph("Score de confiance agrégé", normal_style),
            Paragraph(f"{avg_conf:.3f}", metric_style),
            Paragraph(
                "Moyenne pondérée transcription/alignement/diarisation §12.4",
                small_style,
            ),
        ],
        [
            Paragraph("Confiance minimale", normal_style),
            Paragraph(f"{min_conf:.3f}", metric_style),
            Paragraph("Plus faible score du projet", small_style),
        ],
        [
            Paragraph("Confiance maximale", normal_style),
            Paragraph(f"{max_conf:.3f}", metric_style),
            Paragraph("Plus haut score du projet", small_style),
        ],
        [
            Paragraph("Zones à faible confiance", normal_style),
            Paragraph(str(len(low_zones)), metric_style),
            Paragraph(
                f"Seuil < {low_threshold} — signalées visuellement dans l'éditeur",
                small_style,
            ),
        ],
        [
            Paragraph("Zones confiance moyenne", normal_style),
            Paragraph(str(len(medium_zones)), metric_style),
            Paragraph(f"Seuil {low_threshold}–{medium_threshold}", small_style),
        ],
        [
            Paragraph("Zones haute confiance", normal_style),
            Paragraph(str(len(high_zones)), metric_style),
            Paragraph(f"Seuil ≥ {medium_threshold}", small_style),
        ],
    ]
    metrics_table = Table(metrics_data, colWidths=[55 * mm, 25 * mm, 75 * mm])
    metrics_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#1a1c2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (1, 1), (1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d4d4d8")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, HexColor("#f9fafb")],
                ),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(metrics_table)
    story.append(Spacer(1, 8))
    try:
        drawing = Drawing(170 * mm, 40 * mm)
        bc = VerticalBarChart()
        bc.x = 10
        bc.y = 10
        bc.height = 30 * mm
        bc.width = 150 * mm
        bc.data = [scores[:20]]
        bc.strokeColor = HexColor("#d4d4d8")
        bc.valueAxis.valueMin = 0
        bc.valueAxis.valueMax = 1
        bc.valueAxis.valueStep = 0.2
        bc.categoryAxis.labels.boxAnchor = "ne"
        bc.categoryAxis.labels.dx = 8
        bc.categoryAxis.labels.dy = -2
        bc.categoryAxis.labels.angle = 0
        bc.bars[0].fillColor = HexColor("#e11d48")
        bc.categoryAxis.categoryNames = [
            str(i + 1) for i in range(len(scores[:20]))
        ]
        drawing.add(bc)
        story.append(
            Paragraph(
                "Distribution des scores de confiance par réplique (1-20)",
                subheading_style,
            )
        )
        story.append(drawing)
        story.append(Spacer(1, 6))
    except:
        pass

    story.append(
        Paragraph(
            "2. Détail par réplique — Scores de confiance et zones à faible confiance signalées",
            heading_style,
        )
    )
    story.append(
        Paragraph(
            "Les répliques à faible confiance (&lt; 0.70) sont surlignées en rouge et signalées visuellement dans l'éditeur §12.4.",
            small_style,
        )
    )
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
            tc = (
                f"{_format_timecode(r.start_ms)} → {_format_timecode(r.end_ms)}"
            )
            conf = (
                float(r.confidence_score)
                if r.confidence_score is not None
                else 0.0
            )
            is_low = conf < low_threshold
            is_medium = low_threshold <= conf < medium_threshold
            status_text = (
                "Faible confiance"
                if is_low
                else ("Moyenne" if is_medium else "OK")
            )
            status_style = (
                low_style
                if is_low
                else (small_style if is_medium else ok_style)
            )
            conf_style = low_style if is_low else small_style
            txt = (r.text or "")[:80]
            if len(r.text or "") > 80:
                txt += "…"
            import html

            txt_esc = html.escape(txt)
            typo = r.typo_codes or {}
            if typo:
                txt_esc += f'<br/><font size=6 color="#6b7280">typo: {html.escape(str(typo))}</font>'
            data.append(
                [
                    Paragraph(str(idx), small_style),
                    Paragraph(tc, small_style),
                    Paragraph(txt_esc, normal_style),
                    Paragraph(f"{conf:.3f}", conf_style),
                    Paragraph(status_text, status_style),
                ]
            )
        col_widths = [10 * mm, 30 * mm, 90 * mm, 20 * mm, 25 * mm]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#1a1c2e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d4d4d8")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, HexColor("#f9fafb")],
                    ),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)

    story.append(Spacer(1, 8))
    story.append(
        Paragraph("3. Zones à faible confiance signalées", heading_style)
    )
    if low_zones:
        story.append(
            Paragraph(
                f"{len(low_zones)} zone(s) à faible confiance détectée(s) (chevauchement de locuteurs, bruit important, musique forte) — §12.4 :",
                normal_style,
            )
        )
        for r in low_zones[:10]:
            story.append(
                Paragraph(
                    f'• Réplique #{r.order_index+1} — {_format_timecode(r.start_ms)} → {_format_timecode(r.end_ms)} — <b>{__import__("html").escape(r.text[:60])}</b> — Score: {float(r.confidence_score):.3f} — <font color="#dc2626">À vérifier</font>',
                    small_style,
                )
            )
        if len(low_zones) > 10:
            story.append(
                Paragraph(
                    f"... et {len(low_zones)-10} autres zones", small_style
                )
            )
    else:
        story.append(
            Paragraph(
                "Aucune zone à faible confiance détectée. Toutes les répliques ont un score ≥ 0.70. Excellent !",
                ok_style,
            )
        )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "4. Méthodologie — Calcul du score agrégé §12.4", heading_style
        )
    )
    story.append(
        Paragraph(
            "Score agrégé pondéré : <b>transcription 50%</b> + <b>alignement 30%</b> + <b>diarisation 20%</b>. Transcription = moyenne des confidence des segments, alignement = proportion de mots avec confidence >0.8, diarisation = cohérence des locuteurs. Seuil faible confiance &lt;0.70.",
            small_style,
        )
    )
    story.append(
        Paragraph(
            "Journal d'analyse exportable pour audit qualité — Rapport PDF de synthèse du traitement IA d'un projet. Conservez ce document pour traçabilité et validation qualité.",
            small_style,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"Généré le {__import__('datetime').datetime.now().strftime('%d/%m/%Y %H:%M')} — RythmoAI &middot; {len(replicas)} répliques &middot; Audit qualité &middot; §12.4",
            small_style,
        )
    )

    if watermark_text:

        def draw_wm(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 20)
            canvas.setFillColorRGB(0.85, 0.2, 0.2, alpha=0.3)
            canvas.translate(250, 420)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, watermark_text)
            canvas.restoreState()

        doc.build(story, onFirstPage=draw_wm, onLaterPages=draw_wm)
    else:
        doc.build(story)


def _generate_srt(project: Project, replicas: list, output_path: Path):
    with open(output_path, "w", encoding="utf-8") as f:
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
    with open(output_path, "w", encoding="utf-8") as f:
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



# ──────────────────────────────────────────────────────────────────────────────
# EBU-STL étendu — ETSI EN 300 706 / EBU Tech 3264
# Rétro-ingénierie documentée : docs/retro_engineering_cavena_ebu.md
# GSI 1024 bytes + N * TTI 128 bytes (binary, Latin-1, 25fps)
# ──────────────────────────────────────────────────────────────────────────────

def _ms_to_stl_timecode(ms: int, fps: int = 25) -> bytes:
    """Convertit ms en 4 bytes H:M:S:F pour STL (EBU)."""
    if ms < 0:
        ms = 0
    total_seconds = ms // 1000
    hours = (total_seconds // 3600) % 100
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    frames = int((ms % 1000) * fps / 1000)
    if frames >= fps:
        frames = fps - 1
    return bytes([hours & 0xFF, minutes & 0xFF, seconds & 0xFF, frames & 0xFF])

def _stl_timecode_to_ms(tc: bytes, fps: int = 25) -> int:
    if len(tc) < 4:
        return 0
    h, m, s, f = tc[0], tc[1], tc[2], tc[3]
    return ((h * 3600 + m * 60 + s) * 1000) + int(f * 1000 / fps)

def _stl_encode_text(text: str, typo_codes: dict, max_len: int = 112) -> bytes:
    """Encode le texte en 112 bytes Latin-1 avec contrôles EBU-STL étendu."""
    if not text:
        text = ""
    typo = typo_codes or {}
    norm = {}
    for k, v in typo.items():
        if not v:
            continue
        kk = str(k).lower()
        if kk in ("brackets", "bracket_in", "bracket_out", "crochets"):
            norm["crochets"] = True
        elif kk in ("italic", "italique", "voix_off", "off"):
            norm["italique"] = True
        elif kk in ("uppercase", "majuscules", "cri", "caps"):
            norm["majuscules"] = True
        elif kk in ("parentheses", "parentheses_jeu", "indication_jeu", "jeu"):
            norm["parentheses"] = True
    out = text
    if norm.get("majuscules"):
        out = out.upper()
    if norm.get("parentheses"):
        out = f"({out})"
    if norm.get("crochets"):
        out = f"[ {out} ]"
    prefix = b""
    suffix = b""
    if norm.get("italique"):
        prefix = bytes([0x80, 0x04])
        suffix = bytes([0x80, 0x05])
    try:
        raw = out.encode("latin-1", errors="replace")
    except:
        raw = out.encode("utf-8", errors="replace")[:max_len]
    max_text_len = max_len - len(prefix) - len(suffix)
    if len(raw) > max_text_len:
        raw = raw[:max_text_len]
    tf = prefix + raw + suffix
    if len(tf) < max_len:
        tf = tf + bytes([0x8F] * (max_len - len(tf)))
    else:
        tf = tf[:max_len]
    return tf

def _stl_decode_text(tf_bytes: bytes) -> str:
    """Décode le champ TF 112 bytes (validation)."""
    cleaned = bytearray()
    i = 0
    while i < len(tf_bytes):
        b = tf_bytes[i]
        if b == 0x8F or b == 0x00:
            i += 1
            continue
        if b == 0x80 and i + 1 < len(tf_bytes):
            i += 2
            continue
        if b == 0x8A:
            cleaned.append(ord("\n"))
            i += 1
            continue
        cleaned.append(b)
        i += 1
    try:
        return cleaned.decode("latin-1", errors="ignore").strip()
    except:
        return cleaned.decode("utf-8", errors="ignore").strip()

def _generate_stl(project: Project, replicas: list, output_path: Path, fps: int = 25):
    """Génère un fichier EBU-STL binaire conforme (GSI 1024 + TTI 128*N)."""
    gsi = bytearray(1024)
    for i in range(1024):
        gsi[i] = 0x20
    gsi[0:3] = b"850"
    dfc = f"STL{fps:02d}.01".encode("ascii")
    gsi[3:3+len(dfc)] = dfc
    gsi[11] = ord("1")
    gsi[12:14] = b"00"
    gsi[14:16] = b"0F"
    opt = (project.title or "RythmoAI")[:32].encode("latin-1", errors="replace")
    gsi[16:16+len(opt)] = opt
    oet = (project.title[:32] if project.title else "Rythmo Band")[:32].encode("latin-1", errors="replace")
    gsi[48:48+len(oet)] = oet
    gsi[80:80+len(opt)] = opt
    gsi[112:112+len(oet)] = oet
    tn = b"RythmoAI"
    gsi[144:144+len(tn)] = tn
    tcd = b"RythmoAI Studio"
    gsi[176:176+len(tcd)] = tcd
    slr = str(project.id)[:16].encode("ascii", errors="replace")
    gsi[208:208+len(slr)] = slr
    cd = datetime.now(timezone.utc).strftime("%y%m%d").encode("ascii")
    gsi[224:230] = cd
    gsi[230:236] = cd
    gsi[236:238] = b"01"
    tnb_str = f"{len(replicas):05d}".encode("ascii")
    gsi[238:243] = tnb_str
    gsi[243:248] = tnb_str
    gsi[248:251] = b"001"
    gsi[251:253] = b"32"
    gsi[253:255] = b"01"
    gsi[255] = ord("0")
    gsi[256:264] = b"00000000"
    if replicas:
        tcf_str = _format_timecode(replicas[0].start_ms).replace(":", "")[:8].encode("ascii")
        tcf_str = (tcf_str + b"        ")[:8]
        gsi[264:272] = tcf_str
    else:
        gsi[264:272] = b"00000000"
    gsi[272] = ord("1")
    gsi[273] = ord("1")
    gsi[274:277] = b"FRA"
    pub = b"RythmoAI EBU-STL Extended"
    gsi[277:277+len(pub)] = pub
    gsi[309:309+len(tn)] = tn
    gsi[341:341+len(tcd)] = tcd
    uda = f"RythmoAI Extended EBU-STL | Project:{project.title} | Replicas:{len(replicas)} | Generated:{datetime.now(timezone.utc).isoformat()} | FPS:{fps}".encode("latin-1", errors="replace")[:576]
    gsi[448:448+len(uda)] = uda
    with open(output_path, "wb") as f:
        f.write(gsi)
        for idx, r in enumerate(replicas, 1):
            tti = bytearray(128)
            tti[0] = 0
            tti[1] = idx & 0xFF
            tti[2] = (idx >> 8) & 0xFF
            tti[3] = 0xFF
            tti[4] = 0xFF
            tci = _ms_to_stl_timecode(r.start_ms, fps)
            tti[5:9] = tci
            tco = _ms_to_stl_timecode(r.end_ms, fps)
            tti[9:13] = tco
            tti[13] = 0x16
            tti[14] = 2
            tti[15] = 0
            tf_bytes = _stl_encode_text(r.text or "", r.typo_codes or {}, max_len=112)
            tti[16:128] = tf_bytes
            f.write(tti)

def _typo_flags_bitmask(typo_codes: dict) -> int:
    if not typo_codes:
        return 0
    mask = 0
    for k, v in typo_codes.items():
        if not v:
            continue
        kk = str(k).lower()
        if kk in ("brackets", "bracket_in", "bracket_out", "crochets"):
            mask |= 1
        elif kk in ("italic", "italique", "voix_off", "off"):
            mask |= 2
        elif kk in ("uppercase", "majuscules", "cri", "caps"):
            mask |= 4
        elif kk in ("parentheses", "parentheses_jeu", "indication_jeu", "jeu"):
            mask |= 8
    return mask

def _typo_flags_to_dict(mask: int) -> dict:
    d = {}
    if mask & 1:
        d["crochets"] = True
    if mask & 2:
        d["italique"] = True
    if mask & 4:
        d["majuscules"] = True
    if mask & 8:
        d["parentheses"] = True
    return d

def _generate_cavena(project: Project, replicas: list, output_path: Path, variant: str = "cavena"):
    is_rythmo = variant.lower() == "rythmo"
    magic = b"RYTHMO\n" if is_rythmo else b"CAVENA\x00"
    if len(magic) < 7:
        magic = magic.ljust(7, b"\x00")
    elif len(magic) > 7:
        magic = magic[:7]
    with open(output_path, "wb") as f:
        f.write(magic)
        f.write(struct.pack("B", 1))
        f.write(struct.pack("B", 0))
        f.write(struct.pack("<I", len(replicas)))
        title_bytes = (project.title or "RythmoAI Project").encode("utf-8")
        f.write(struct.pack("<H", len(title_bytes)))
        f.write(title_bytes)
        try:
            studio_bytes = project.studio_id.bytes
        except:
            studio_bytes = uuid.UUID(str(project.studio_id)).bytes if project.studio_id else b"\x00"*16
        f.write(studio_bytes)
        f.write(struct.pack("B", 25))
        f.write(struct.pack("<Q", int(datetime.now(timezone.utc).timestamp() * 1000)))
        f.write(b"\x00" * 32)
        for r in replicas:
            start_ms = int(r.start_ms or 0)
            end_ms = int(r.end_ms or 0)
            if end_ms <= start_ms:
                end_ms = start_ms + 1000
            f.write(struct.pack("<I", start_ms))
            f.write(struct.pack("<I", end_ms))
            f.write(struct.pack("<H", int(r.order_index or 0)))
            mask = _typo_flags_bitmask(r.typo_codes or {})
            f.write(struct.pack("B", mask))
            conf = float(r.confidence_score) if r.confidence_score is not None else 0.85
            f.write(struct.pack("<f", conf))
            speaker_str = str(r.speaker_id) if r.speaker_id else ""
            spk_bytes = speaker_str.encode("utf-8")[:255]
            f.write(struct.pack("B", len(spk_bytes)))
            f.write(spk_bytes)
            text_str = r.text or ""
            text_bytes = text_str.encode("utf-8")
            if len(text_bytes) > 65535:
                text_bytes = text_bytes[:65535]
            f.write(struct.pack("<H", len(text_bytes)))
            f.write(text_bytes)
            f.write(struct.pack("B", 1 if r.breath_marker else 0))
            f.write(struct.pack("B", 0))
        f.write(b"\xFF\xFE" if is_rythmo else b"\xFE\xFF")

def _generate_rythmo(project: Project, replicas: list, output_path: Path):
    return _generate_cavena(project, replicas, output_path, variant="rythmo")

def _generate_json(project: Project, replicas: list, output_path: Path):
    data = {
        "project": {
            "id": str(project.id),
            "title": project.title,
            "studio_id": str(project.studio_id),
            "source_lang": project.source_lang,
            "target_lang": project.target_lang,
        },
        "export": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "replica_count": len(replicas),
            "format": "json",
            "version": "1.0",
        },
        "replicas": [
            {
                "id": str(r.id),
                "media_id": str(r.media_id),
                "speaker_id": str(r.speaker_id) if r.speaker_id else None,
                "text": r.text,
                "start_ms": r.start_ms,
                "end_ms": r.end_ms,
                "order_index": r.order_index,
                "typo_codes": r.typo_codes or {},
                "confidence_score": float(r.confidence_score) if r.confidence_score is not None else None,
                "is_manually_edited": r.is_manually_edited,
                "breath_marker": r.breath_marker,
            }
            for r in replicas
        ],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _generate_export_task(export_id: str, project_id: str):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        export = (
            db.query(Export).filter(Export.id == uuid.UUID(export_id)).first()
        )
        if not export:
            return
        export.status = "processing"
        db.commit()
        project = (
            db.query(Project)
            .filter(Project.id == uuid.UUID(project_id))
            .first()
        )
        if not project:
            export.status = "failed"
            export.error_message = "Projet non trouvé"
            db.commit()
            return
        replicas = _get_replicas_for_project(db, uuid.UUID(project_id))
        fmt = _normalize_format(export.format) if export.format else "pdf"

        watermark_text = (
            _get_watermark_text(
                export.created_by or "system",
                export.creator_role or "invité",
                export.created_at,
            )
            if export.is_watermarked
            else None
        )

        if fmt == "pdf":
            output_path = EXPORT_DIR / f"{export_id}.pdf"
            _generate_pdf(
                project, replicas, output_path, watermark_text=watermark_text
            )
        elif fmt == "quality_report":
            output_path = EXPORT_DIR / f"{export_id}.pdf"
            _generate_quality_report(
                project,
                replicas,
                output_path,
                db,
                watermark_text=watermark_text,
            )
        elif fmt == "srt":
            output_path = EXPORT_DIR / f"{export_id}.srt"
            _generate_srt(project, replicas, output_path)
        elif fmt == "vtt":
            output_path = EXPORT_DIR / f"{export_id}.vtt"
            _generate_vtt(project, replicas, output_path)
        elif fmt == "stl":
            output_path = EXPORT_DIR / f"{export_id}.stl"
            _generate_stl(project, replicas, output_path)
        elif fmt == "cavena":
            output_path = EXPORT_DIR / f"{export_id}.cav"
            _generate_cavena(project, replicas, output_path, variant="cavena")
        elif fmt == "rythmo":
            output_path = EXPORT_DIR / f"{export_id}.rythmo"
            _generate_rythmo(project, replicas, output_path)
        elif fmt == "json":
            output_path = EXPORT_DIR / f"{export_id}.json"
            _generate_json(project, replicas, output_path)
        else:
            output_path = EXPORT_DIR / f"{export_id}.{fmt}"
            with open(output_path, "w", encoding="utf-8") as f:
                for r in replicas:
                    f.write(f"{r.text}\n")
        export.file_path = str(output_path)
        export.status = "completed"
        db.commit()
    except Exception as e:
        try:
            export = (
                db.query(Export)
                .filter(Export.id == uuid.UUID(export_id))
                .first()
            )
            if export:
                export.status = "failed"
                export.error_message = str(e)
                db.commit()
        except:
            pass
    finally:
        db.close()


@router.post(
    "/projects/{project_id}/exports", response_model=dict, status_code=202
)
def create_export(
    project_id: uuid.UUID,
    data: ExportCreateIn = ExportCreateIn(),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
    _rl=Depends(export_rate_limit_dep),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")

    if payload and payload.get("sub"):
        try:
            from app.models import StudioMembership

            uid = uuid.UUID(payload.get("sub"))
            membership = (
                db.query(StudioMembership)
                .filter(
                    StudioMembership.studio_id == project.studio_id,
                    StudioMembership.user_id == uid,
                )
                .first()
            )
            any_membership = (
                db.query(StudioMembership)
                .filter(StudioMembership.user_id == uid)
                .first()
            )
            if any_membership and not membership:
                raise HTTPException(
                    status_code=404,
                    detail="Projet non trouvé (§15.7 IDOR protection)",
                )
        except HTTPException:
            raise
        except Exception:
            pass
    fmt_raw = data.format or "pdf"
    fmt = _normalize_format(fmt_raw)
    allowed = ("pdf", "srt", "vtt", "stl", "cavena", "rythmo", "json", "quality_report")
    if fmt not in allowed:
        if _is_quality_report(fmt_raw):
            fmt = "quality_report"
        else:
            raise HTTPException(
                status_code=422, detail=f"Format non supporté: {fmt_raw}"
            )
    # Tous les formats de l'allowed sont maintenant supportés : pdf/srt/vtt/stl/cavena/rythmo/json/quality_report
    # Plus de restriction secondaire

    created_by = payload.get("email", "system") if payload else "system"
    creator_role = (
        payload.get("role", "adaptateur") if payload else "adaptateur"
    )

    studio = db.query(Studio).filter(Studio.id == project.studio_id).first()
    studio_settings = (
        getattr(studio, "security_settings", None)
        if studio
        else {
            "watermark_enabled": True,
            "auto_purge_enabled": True,
            "retention_days": 30,
        }
    ) or {}
    watermark_enabled = studio_settings.get("watermark_enabled", True)
    auto_purge_enabled = studio_settings.get("auto_purge_enabled", True)
    retention_days = int(studio_settings.get("retention_days", 30))

    is_watermarked = bool(watermark_enabled and is_risky_role(creator_role))
    watermark_text = (
        _get_watermark_text(created_by, creator_role)
        if is_watermarked
        else None
    )
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=retention_days)
        if auto_purge_enabled
        else None
    )

    export = Export(
        id=uuid.uuid4(),
        project_id=project_id,
        format=fmt,
        status="pending",
        created_by=created_by,
        creator_role=creator_role,
        is_watermarked=is_watermarked,
        is_archived=False,
        expires_at=expires_at,
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
            _generate_pdf(
                project, replicas, output_path, watermark_text=watermark_text
            )
        elif fmt == "quality_report":
            output_path = EXPORT_DIR / f"{export.id}.pdf"
            _generate_quality_report(
                project,
                replicas,
                output_path,
                db,
                watermark_text=watermark_text,
            )
        elif fmt == "srt":
            output_path = EXPORT_DIR / f"{export.id}.srt"
            _generate_srt(project, replicas, output_path)
        elif fmt == "vtt":
            output_path = EXPORT_DIR / f"{export.id}.vtt"
            _generate_vtt(project, replicas, output_path)
        elif fmt == "stl":
            output_path = EXPORT_DIR / f"{export.id}.stl"
            _generate_stl(project, replicas, output_path)
        elif fmt == "cavena":
            output_path = EXPORT_DIR / f"{export.id}.cav"
            _generate_cavena(project, replicas, output_path, variant="cavena")
        elif fmt == "rythmo":
            output_path = EXPORT_DIR / f"{export.id}.rythmo"
            _generate_rythmo(project, replicas, output_path)
        elif fmt == "json":
            output_path = EXPORT_DIR / f"{export.id}.json"
            _generate_json(project, replicas, output_path)
        else:
            output_path = EXPORT_DIR / f"{export.id}.{fmt}"
            with open(output_path, "w", encoding="utf-8") as f:
                for r in replicas:
                    f.write(f"{r.text}\n")
        export.file_path = str(output_path)
        export.status = "completed"
        db.commit()
        db.refresh(export)
        try:
            record_audit_log(
                db,
                "export_create",
                user_email=created_by,
                studio_id=project.studio_id,
                details={
                    "project_id": str(project_id),
                    "format": fmt,
                    "export_id": str(export.id),
                },
            )
        except Exception:
            pass
    except Exception as e:
        export.status = "failed"
        export.error_message = str(e)
        db.commit()
        pass

    try:
        background_tasks.add_task(
            _generate_export_task, str(export.id), str(project_id)
        )
    except:
        pass

    return {
        "id": str(export.id),
        "project_id": str(project_id),
        "format": export.format,
        "status": export.status,
        "is_watermarked": export.is_watermarked,
        "is_archived": export.is_archived,
        "created_by": export.created_by,
        "creator_role": export.creator_role,
        "expires_at": (
            export.expires_at.isoformat() if export.expires_at else None
        ),
        "created_at": (
            export.created_at.isoformat() if export.created_at else None
        ),
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
        "is_watermarked": export.is_watermarked,
        "is_archived": export.is_archived,
        "created_by": export.created_by,
        "creator_role": export.creator_role,
        "expires_at": (
            export.expires_at.isoformat() if export.expires_at else None
        ),
        "file_path": export.file_path,
        "error_message": export.error_message,
        "created_at": (
            export.created_at.isoformat() if export.created_at else None
        ),
        "updated_at": (
            export.updated_at.isoformat() if export.updated_at else None
        ),
    }


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export non trouvé")
    if export.status != "completed" or not export.file_path:
        raise HTTPException(
            status_code=409, detail=f"Export non prêt, status={export.status}"
        )
    path = Path(export.file_path)
    if not path.exists():
        raise HTTPException(
            status_code=404, detail="Fichier export non trouvé sur disque"
        )
    fmt = _normalize_format(export.format) if export.format else "pdf"
    if fmt == "quality_report":
        media_type = "application/pdf"
        ext = "pdf"
    elif fmt == "srt":
        media_type = "application/x-subrip"
        ext = "srt"
    elif fmt == "vtt":
        media_type = "text/vtt"
        ext = "vtt"
    elif fmt == "stl":
        media_type = "application/x-stl"
        ext = "stl"
    elif fmt == "cavena":
        media_type = "application/x-cavena"
        ext = "cav"
    elif fmt == "rythmo":
        media_type = "application/x-rythmo"
        ext = "rythmo"
    elif fmt == "json":
        media_type = "application/json"
        ext = "json"
    elif fmt == "pdf":
        media_type = "application/pdf"
        ext = "pdf"
    else:
        media_type = "application/octet-stream"
        ext = fmt
    user_id_val = uuid.UUID(payload["sub"]) if payload else None
    user_email_val = payload.get("email", "unknown") if payload else "unknown"
    try:
        record_audit_log(
            db,
            "export_download",
            user_id=user_id_val,
            user_email=user_email_val,
            studio_id=export.project_id,
            details={
                "export_id": str(export_id),
                "project_id": str(export.project_id),
                "format": export.format,
            },
        )
        check_download_anomalies(
            db,
            user_id=user_id_val,
            user_email=user_email_val,
            studio_id=export.project_id,
        )
    except Exception:
        pass
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=f"bande_rythmo_{export.project_id}_{export.id}.{ext}",
        headers={
            "Content-Disposition": f'attachment; filename="bande_rythmo_{export.id}.{ext}"'
        },
    )


@router.post("/exports/purge-expired")
@router.post("/api/v1/exports/purge-expired")
def purge_expired_exports_endpoint(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    expired = (
        db.query(Export)
        .filter(Export.is_archived == False)
        .filter(Export.expires_at <= now)
        .all()
    )
    purged_count = 0
    for exp in expired:
        if exp.file_path and os.path.exists(exp.file_path):
            try:
                os.remove(exp.file_path)
            except Exception:
                pass
        db.delete(exp)
        purged_count += 1
    db.commit()
    return {
        "status": "success",
        "purged_count": purged_count,
        "message": f"{purged_count} expired exports purged successfully",
    }


@router.post("/exports/{export_id}/archive")
@router.post("/api/v1/exports/{export_id}/archive")
def archive_export(
    export_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export non trouvé")
    export.is_archived = True
    db.commit()
    db.refresh(export)
    return {
        "id": str(export.id),
        "is_archived": True,
        "status": "archived",
        "message": "Export archived explicitly — protected from auto-purge",
    }
