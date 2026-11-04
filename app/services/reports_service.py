from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Payment, Service, User


async def collect_order_report(
    session: AsyncSession, *, start_utc: datetime, end_utc: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = (await session.execute(
        select(Order, User, Service)
        .join(User, User.id == Order.user_id)
        .join(Service, Service.id == Order.service_id)
        .where(Order.created_at >= start_utc, Order.created_at < end_utc)
        .order_by(Order.created_at.desc())
    )).all()
    records: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    order_totals: dict[str, int] = {}
    for order, user, service in rows:
        status_counts[order.status] = status_counts.get(order.status, 0) + 1
        order_totals[order.currency] = order_totals.get(order.currency, 0) + int(order.total_minor)
        records.append({
            "order_number": order.order_number,
            "created_at": order.created_at.isoformat(),
            "user_telegram_id": user.telegram_id,
            "username": user.username or "",
            "service": service.name,
            "quantity": order.quantity,
            "total_minor": order.total_minor,
            "currency": order.currency,
            "status": order.status,
            "payment_method": order.payment_method,
            "completed_at": order.completed_at.isoformat() if order.completed_at else "",
        })
    paid_payments = (await session.execute(
        select(Payment.currency, Payment.amount_minor)
        .where(Payment.status == "paid", Payment.created_at >= start_utc, Payment.created_at < end_utc)
    )).all()
    paid_totals: dict[str, int] = {}
    for currency, amount in paid_payments:
        paid_totals[currency] = paid_totals.get(currency, 0) + int(amount)
    summary = {
        "orders": len(records),
        "status_counts": status_counts,
        "order_totals": order_totals,
        "paid_totals": paid_totals,
    }
    return records, summary


def csv_bytes(records: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    fields = [
        "order_number", "created_at", "user_telegram_id", "username", "service",
        "quantity", "total_minor", "currency", "status", "payment_method", "completed_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in records:
        safe = dict(row)
        # Prevent spreadsheet formula injection when a CSV is opened in Excel.
        for key, value in safe.items():
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                safe[key] = "'" + value
        writer.writerow(safe)
    return output.getvalue().encode("utf-8-sig")


def xlsx_bytes(records: list[dict[str, Any]], summary: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Buyurtmalar"
    fields = [
        "order_number", "created_at", "user_telegram_id", "username", "service",
        "quantity", "total_minor", "currency", "status", "payment_method", "completed_at",
    ]
    sheet.append(fields)
    for row in records:
        sheet.append([row.get(field, "") for field in fields])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="20314F")
        cell.alignment = Alignment(horizontal="center")
    widths = [18, 25, 19, 20, 28, 10, 17, 12, 18, 18, 25]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    summary_sheet = workbook.create_sheet("Xulosa")
    summary_sheet.append(["Ko‘rsatkich", "Qiymat"])
    summary_sheet.append(["Buyurtmalar soni", summary["orders"]])
    summary_sheet.append(["Holatlar", str(summary["status_counts"])])
    summary_sheet.append(["Buyurtma summalari (valyuta bo‘yicha minor units)", str(summary["order_totals"])])
    summary_sheet.append(["Tasdiqlangan to‘lovlar (valyuta bo‘yicha minor units)", str(summary["paid_totals"])])
    for cell in summary_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="20314F")
    summary_sheet.column_dimensions["A"].width = 54
    summary_sheet.column_dimensions["B"].width = 72
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def pdf_bytes(records: list[dict[str, Any]], summary: dict[str, Any], title: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    out = io.BytesIO()
    document = SimpleDocTemplate(out, pagesize=landscape(A4), rightMargin=10*mm, leftMargin=10*mm, topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(title.replace("&", "&amp;"), styles["Title"]), Spacer(1, 5*mm)]
    story.append(Paragraph(f"Buyurtmalar: {summary['orders']} | Holatlar: {str(summary['status_counts'])}", styles["Normal"]))
    story.append(Paragraph(f"Tasdiqlangan to‘lovlar (minor units): {str(summary['paid_totals'])}", styles["Normal"]))
    story.append(Spacer(1, 5*mm))
    table_data = [["Buyurtma", "Sana", "Telegram ID", "Xizmat", "Miqdor", "Summa", "Holat", "To‘lov"]]
    for row in records[:500]:
        table_data.append([
            str(row["order_number"]), str(row["created_at"])[:16].replace("T", " "),
            str(row["user_telegram_id"]), str(row["service"])[:24], str(row["quantity"]),
            f"{row['total_minor']} {row['currency']}", str(row["status"]), str(row["payment_method"]),
        ])
    table = Table(table_data, repeatRows=1, colWidths=[28*mm, 30*mm, 24*mm, 42*mm, 14*mm, 28*mm, 28*mm, 24*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#20314F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FA")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    document.build(story)
    return out.getvalue()
