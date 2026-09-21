"""Notch and card paths, ported from shape.js onto QPainterPath."""

import math

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QPainterPath, QTransform

from .layout import L


def _cairo_arc(path, cx, cy, r, a0, a1, negative=False):
    two_pi = 2 * math.pi
    if not negative:
        while a1 < a0:
            a1 += two_pi
    else:
        while a1 > a0:
            a1 -= two_pi
    sweep = a1 - a0
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    path.arcTo(rect, -math.degrees(a0), -math.degrees(sweep))


def notch_path(x, y, depth, length, flare=None, corner_radius=None):
    if flare is None:
        flare = L["curlRadius"]
    if corner_radius is None:
        corner_radius = L["cornerRadius"]
    wanted = max(0.0, min(corner_radius, depth / 2))
    curl = max(0.0, min(flare, length / 2, depth - wanted))
    corner = max(0.0, min(wanted, (length - 2 * curl) / 2))
    right = x + depth
    bottom = y + length

    path = QPainterPath()
    path.moveTo(right, y)
    if curl > 0:
        _cairo_arc(path, right - curl, y, curl, 0, math.pi / 2)
    path.lineTo(x + corner, y + curl)
    _cairo_arc(path, x + corner, y + curl + corner, corner, -math.pi / 2, math.pi, True)
    path.lineTo(x, bottom - curl - corner)
    _cairo_arc(path, x + corner, bottom - curl - corner, corner, math.pi, math.pi / 2, True)
    path.lineTo(right - curl, bottom - curl)
    if curl > 0:
        _cairo_arc(path, right - curl, bottom, curl, -math.pi / 2, 0)
    path.closeSubpath()
    return path


def edge_notch_path(edge, w, h, depth, length, flare=None):
    if flare is None:
        flare = L["curlRadius"]
    if edge == "right":
        return notch_path(w - depth, (h - length) / 2, depth, length, flare)
    if edge == "left":
        t = QTransform()
        t.translate(depth, 0)
        t.scale(-1, 1)
        return t.map(notch_path(0, (h - length) / 2, depth, length, flare))
    if edge == "top":
        t = QTransform()
        t.translate(0, depth)
        t.rotate(-90)
        return t.map(notch_path(0, (w - length) / 2, depth, length, flare))
    t = QTransform()
    t.translate(0, h - depth)
    t.scale(-1, 1)
    t.rotate(90)
    return t.map(notch_path(0, (w - length) / 2, depth, length, flare))


def card_path(x, y, w, h, corner, side, tail_length, tail_height, tip):
    r = min(corner, w / 2, h / 2)
    half = tail_height / 2

    def base(along):
        lo = r + half
        hi = along - r - half
        if lo <= hi:
            return max(lo, min(hi, tip))
        return along / 2

    path = QPainterPath()
    path.moveTo(x + r, y)
    if side == "top":
        b = base(w)
        path.lineTo(x + b - half, y)
        path.lineTo(x + b, y - tail_length)
        path.lineTo(x + b + half, y)
    path.lineTo(x + w - r, y)
    path.arcTo(QRectF(x + w - 2 * r, y, 2 * r, 2 * r), 90, -90)
    if side == "right":
        b = base(h)
        path.lineTo(x + w, y + b - half)
        path.lineTo(x + w + tail_length, y + b)
        path.lineTo(x + w, y + b + half)
    path.lineTo(x + w, y + h - r)
    path.arcTo(QRectF(x + w - 2 * r, y + h - 2 * r, 2 * r, 2 * r), 0, -90)
    if side == "bottom":
        b = base(w)
        path.lineTo(x + b + half, y + h)
        path.lineTo(x + b, y + h + tail_length)
        path.lineTo(x + b - half, y + h)
    path.lineTo(x + r, y + h)
    path.arcTo(QRectF(x, y + h - 2 * r, 2 * r, 2 * r), 270, -90)
    if side == "left":
        b = base(h)
        path.lineTo(x, y + b + half)
        path.lineTo(x - tail_length, y + b)
        path.lineTo(x, y + b - half)
    path.lineTo(x, y + r)
    path.arcTo(QRectF(x, y, 2 * r, 2 * r), 180, -90)
    path.closeSubpath()
    return path


def lerp(a, b, t):
    return a + (b - a) * t
