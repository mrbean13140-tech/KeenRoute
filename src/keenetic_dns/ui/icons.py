"""Единый набор линейных иконок, нарисованных кодом (не зависят от шрифтов и эмодзи, перекрашиваются под тему)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import C as COL


def _draw(name: str, p: QPainter, s: float):
    """Рисует иконку в квадрате 0..s (s = 24 условных единицы)."""
    k = s / 24.0

    def P(x, y):
        return QPointF(x * k, y * k)

    def line(*pts):
        path = QPainterPath(P(*pts[0]))
        for pt in pts[1:]:
            path.lineTo(P(*pt))
        p.drawPath(path)

    def rect(x, y, w, h, r=2):
        p.drawRoundedRect(QRectF(x * k, y * k, w * k, h * k), r * k, r * k)

    def circle(x, y, r):
        p.drawEllipse(P(x, y), r * k, r * k)

    def arc(x, y, r, start, span):
        p.drawArc(QRectF((x - r) * k, (y - r) * k, 2 * r * k, 2 * r * k), int(start * 16), int(span * 16))

    if name == "catalog":       # книжка
        rect(4, 3, 14, 18, 2); line((8, 3), (8, 21)); line((11, 8), (15, 8)); line((11, 12), (15, 12))
    elif name == "import":      # стрелка вниз в лоток
        line((12, 3), (12, 14)); line((7.5, 9.5), (12, 14), (16.5, 9.5)); line((4, 15), (4, 20), (20, 20), (20, 15))
    elif name == "export":      # стрелка вверх из лотка
        line((12, 14), (12, 3)); line((7.5, 7.5), (12, 3), (16.5, 7.5)); line((4, 15), (4, 20), (20, 20), (20, 15))
    elif name == "save":        # дискета
        rect(4, 4, 16, 16, 2); line((8, 4), (8, 9), (15, 9), (15, 4)); rect(8, 13, 8, 7, 1)
    elif name == "restore":     # стрелка против часовой
        arc(12, 12, 7.5, 200, -290); line((4.2, 6.5), (4.6, 10.6), (8.6, 10.0))
    elif name == "refresh":
        arc(12, 12, 7.5, 60, 290); line((19.6, 5.5), (19.4, 9.7), (15.3, 9.3))
    elif name == "plus":
        line((12, 5), (12, 19)); line((5, 12), (19, 12))
    elif name == "search":
        circle(10.5, 10.5, 6); line((15, 15), (20, 20))
    elif name == "compass":     # куда пойдёт домен
        circle(12, 12, 8.5); line((15.5, 8.5), (13.5, 13.5), (8.5, 15.5), (10.5, 10.5), (15.5, 8.5))
    elif name == "route":       # маршрутизация: развилка
        circle(5, 12, 2); circle(19, 6, 2); circle(19, 18, 2)
        line((7, 12), (11, 12)); line((11, 12), (13.5, 7), (17, 6)); line((11, 12), (13.5, 17), (17, 18))
    elif name == "lock":
        rect(5, 10.5, 14, 10, 2); arc(12, 10.5, 4.5, 0, 180); line((7.5, 10.5), (7.5, 9)); line((16.5, 10.5), (16.5, 9))
        line((12, 14.5), (12, 17))
    elif name == "monitor":     # ярлык на рабочий стол
        rect(3, 4, 18, 12, 2); line((9, 20), (15, 20)); line((12, 16), (12, 20))
    elif name == "theme":       # полукруг
        circle(12, 12, 8)
        path = QPainterPath(P(12, 4))
        path.arcTo(QRectF(4 * k, 4 * k, 16 * k, 16 * k), 90, 180)
        path.closeSubpath()
        p.save(); p.setBrush(p.pen().color()); p.drawPath(path); p.restore()
    elif name == "update":      # стрелка вверх в круге
        circle(12, 12, 8.5); line((12, 16.5), (12, 7.5)); line((8.5, 11), (12, 7.5), (15.5, 11))
    elif name == "trash":
        line((4, 7), (20, 7)); line((9, 7), (9, 4.5), (15, 4.5), (15, 7)); line((6, 7), (7, 20), (17, 20), (18, 7))
        line((10, 10.5), (10, 16.5)); line((14, 10.5), (14, 16.5))
    elif name == "swap":        # сменить роутер
        line((5, 8), (19, 8)); line((15.5, 4.5), (19, 8), (15.5, 11.5))
        line((19, 16), (5, 16)); line((8.5, 12.5), (5, 16), (8.5, 19.5))
    elif name == "split":       # разбить
        line((4, 12), (10, 12)); line((10, 12), (14, 6), (20, 6)); line((10, 12), (14, 18), (20, 18))
    elif name == "router":
        rect(3, 12, 18, 7, 2); line((8, 12), (8, 6)); line((16, 12), (16, 6)); circle(7.5, 15.5, 0.6)
        circle(11, 15.5, 0.6)
    elif name == "pause":
        line((9, 6), (9, 18)); line((15, 6), (15, 18))
    elif name == "play":
        line((8, 5.5), (18.5, 12), (8, 18.5), (8, 5.5))
    elif name == "check":
        line((5, 12.5), (10, 17), (19, 7))


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    col = QColor(color or COL["text"])
    ic = QIcon()
    for scale in (1, 2):
        px = QPixmap(size * scale, size * scale)
        px.setDevicePixelRatio(scale)
        px.fill(Qt.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(col, 1.7 * size / 20)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        _draw(name, p, size)
        p.end()
        ic.addPixmap(px)
    return ic


def _color_for(kind: str | None) -> str:
    return {"primary": "#ffffff", "danger": COL["bad"], "muted": COL["muted"]}.get(kind or "", COL["text"])


def set_icon(btn, name: str, kind: str | None = None) -> None:
    """Иконка на кнопке; запоминается, чтобы перекрасить при смене темы."""
    btn.setProperty("ic", name)
    btn.setProperty("ick", kind or "")
    btn.setIcon(icon(name, _color_for(kind)))


def refresh_icons(root) -> None:
    from PySide6.QtWidgets import QPushButton
    for b in root.findChildren(QPushButton):
        name = b.property("ic")
        if name:
            b.setIcon(icon(name, _color_for(b.property("ick"))))


def lead_icon(edit, name: str) -> None:
    """Иконка слева внутри поля ввода."""
    from PySide6.QtWidgets import QLineEdit
    edit.addAction(icon(name, "#8b92a1", 18), QLineEdit.LeadingPosition)
