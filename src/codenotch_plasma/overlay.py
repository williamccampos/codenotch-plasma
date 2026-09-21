"""Edge-welded Codenotch overlay for KDE Plasma (X11/Wayland)."""

import math
from datetime import datetime
from webbrowser import open as open_url

from PyQt5.QtCore import (
    QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtProperty,
)
from PyQt5.QtGui import (
    QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QRegion,
)
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QWidget

from .copytext import count_text, elapsed_text, percent_text, reset_text
from .glyphs import draw_glyph
from .layout import (
    Appearance, L, Palette, band, band_color, body_depth,
    is_dark_notch, ring_center, shape_length,
)
from .theme import normalize_mode, toggle_fixed_mode
from .theme_icons import draw_theme_icon
from .shape import card_path, edge_notch_path, lerp
from .store import dual_ring_windows, glyph_dimmed, headline_of, headline_text


MOTION_UNFOLD = 420
MOTION_FOLD = 300
MOTION_READING_MS = 900
LEAVE_GRACE_MS = 250
SWEEP_LERP = 1 - math.exp(-16 / MOTION_READING_MS)


def _qcolor(hex_color, alpha=1.0):
    c = QColor(hex_color)
    c.setAlphaF(Appearance["opacity"] * alpha if hex_color == Appearance["color"] else alpha)
    return c


class NotchOverlay(QWidget):
    def __init__(self, store, config, parent=None, on_theme_change=None, open_menu=None):
        super().__init__(parent)
        self._store = store
        self._config = config
        self._on_theme_change = on_theme_change
        self._open_menu = open_menu
        self._theme_mode = normalize_mode(config.get("themeMode", "auto"))
        self._edge = config.get("edge", "right")
        self._position = max(0.0, min(1.0, float(config.get("position", 0.5))))
        self._always_open = bool(config.get("alwaysOpen", False))
        self._hide_fullscreen = bool(config.get("hideInFullscreen", True))
        self._hot_zone = max(1, int(config.get("hotZone", 4)))
        self._open_delay = max(0, int(config.get("openDelay", 150)))
        self._progress = 1.0 if self._always_open else 0.0
        self._expanded = self._always_open
        self._hover_index = -1
        self._card_shown = False
        self._activity_phase = 0.0
        self._sweeps = {p.id: 0.0 for p in store.providers}
        self._inner_sweeps = {p.id: 0.0 for p in store.providers}
        self._open_timer = QTimer(self)
        self._open_timer.setSingleShot(True)
        self._open_timer.timeout.connect(self._expand)
        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.timeout.connect(self._maybe_fold)
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_progress)
        self._activity_timer = QTimer(self)
        self._activity_timer.timeout.connect(self._tick_activity)
        self._activity_timer.start(16)
        self._card_timer = QTimer(self)
        self._card_timer.timeout.connect(self.update)
        self._card_timer.start(30_000)
        self._fullscreen_timer = QTimer(self)
        self._fullscreen_timer.timeout.connect(self._sync_fullscreen_visibility)
        self._fullscreen_timer.start(500)
        self._screen_relayout_timer = QTimer(self)
        self._screen_relayout_timer.setSingleShot(True)
        self._screen_relayout_timer.setInterval(150)
        self._screen_relayout_timer.timeout.connect(self._apply_screen_change)

        self.setWindowTitle("Codenotch")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_X11NetWmWindowTypeDock, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        store.changed.connect(lambda _id: self.update())
        self._install_screen_watchers()
        self._relayout()
        self._update_mask()

    def set_theme_mode(self, mode):
        self._theme_mode = normalize_mode(mode)

    def reload_providers(self):
        self._sweeps = {p.id: self._sweeps.get(p.id, 0.0) for p in self._store.providers}
        self._inner_sweeps = {p.id: self._inner_sweeps.get(p.id, 0.0) for p in self._store.providers}
        self._hover_index = -1
        self._relayout()
        self._update_mask()
        self.update()

    def get_progress(self):
        return self._progress

    def set_progress(self, value):
        self._progress = float(value)
        self._relayout()
        self._update_mask()
        self.update()

    progress = pyqtProperty(float, get_progress, set_progress)

    def _cell_count(self):
        return len(self._store.providers) + 1

    def _vertical(self):
        return self._edge in ("left", "right")

    def _full_depth(self):
        return body_depth(self._vertical())

    def _full_length(self):
        return shape_length(self._cell_count(), self._vertical())

    def _current_depth(self):
        rest = 0 if False else L["pillWidth"]
        return lerp(rest, self._full_depth(), max(0.0, min(1.0, self._progress)))

    def _current_length(self):
        return lerp(L["pillHeight"], self._full_length(), max(0.0, min(1.0, self._progress)))

    def _envelope_size(self):
        depth = self._full_depth()
        length = self._full_length()
        card_w = L["cardWidth"] + L["tailLength"] + L["tailGap"]
        if self._vertical():
            w = int(math.ceil(depth + card_w + L["envelopeMargin"] + L["envelopeSlack"]))
            h = int(math.ceil(max(length, 280) + 2 * L["envelopeMargin"] + L["envelopeSlack"]))
        else:
            w = int(math.ceil(max(length, card_w) + 2 * L["envelopeMargin"] + L["envelopeSlack"]))
            h = int(math.ceil(depth + L["cardWidth"] + L["tailLength"] + L["envelopeMargin"]))
        return max(w, 80), max(h, 80)

    def _primary_screen(self):
        return QApplication.primaryScreen()

    def _screen_geo(self):
        screen = self._primary_screen()
        if screen:
            return screen.availableGeometry()
        return QApplication.desktop().availableGeometry()

    def _install_screen_watchers(self):
        app = QApplication.instance()
        if app is None:
            return
        app.primaryScreenChanged.connect(self._schedule_screen_relayout)
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(self._schedule_screen_relayout)
        for screen in app.screens():
            self._watch_screen(screen)

    def _watch_screen(self, screen):
        if screen is None:
            return
        screen.geometryChanged.connect(self._schedule_screen_relayout)
        screen.availableGeometryChanged.connect(self._schedule_screen_relayout)

    def _on_screen_added(self, screen):
        self._watch_screen(screen)
        self._schedule_screen_relayout()

    def _schedule_screen_relayout(self, *_args):
        self._screen_relayout_timer.start()

    def _apply_screen_change(self):
        self._relayout()
        self._update_mask()
        self._sync_fullscreen_visibility()
        self.update()

    def _relayout(self):
        w, h = self._envelope_size()
        geo = self._screen_geo()
        if self._edge == "right":
            x = geo.x() + geo.width() - w
            y = geo.y() + int((geo.height() - h) * self._position)
        elif self._edge == "left":
            x = geo.x()
            y = geo.y() + int((geo.height() - h) * self._position)
        elif self._edge == "top":
            x = geo.x() + int((geo.width() - w) * self._position)
            y = geo.y()
        else:
            x = geo.x() + int((geo.width() - w) * self._position)
            y = geo.y() + geo.height() - h
        self.setGeometry(x, y, w, h)

    def _update_mask(self):
        region = QRegion(self._notch_path().toFillPolygon().toPolygon())
        if self._progress < 0.2:
            geo = self.rect()
            if self._edge == "right":
                strip = QRectF(
                    geo.width() - self._hot_zone, (geo.height() - L["pillHeight"]) / 2,
                    self._hot_zone, L["pillHeight"],
                ).toRect()
                region = region.united(QRegion(strip))
            elif self._edge == "left":
                strip = QRectF(
                    0, (geo.height() - L["pillHeight"]) / 2,
                    self._hot_zone, L["pillHeight"],
                ).toRect()
                region = region.united(QRegion(strip))
            elif self._edge == "top":
                strip = QRectF(
                    (geo.width() - L["pillHeight"]) / 2, 0,
                    L["pillHeight"], self._hot_zone,
                ).toRect()
                region = region.united(QRegion(strip))
            elif self._edge == "bottom":
                strip = QRectF(
                    (geo.width() - L["pillHeight"]) / 2, geo.height() - self._hot_zone,
                    L["pillHeight"], self._hot_zone,
                ).toRect()
                region = region.united(QRegion(strip))
        if self._hover_index >= 0 and self._progress > 0.7:
            rect, side, tip, *_rest = self._card_metrics(self._hover_index)
            if not rect.isNull():
                path = card_path(
                    rect.x(), rect.y(), rect.width(), rect.height(),
                    L["cardCorner"], side, L["tailLength"], L["tailHeight"], tip,
                )
                region = region.united(QRegion(path.toFillPolygon().toPolygon()))
        self.setMask(region)

    def _notch_path(self):
        return edge_notch_path(
            self._edge, self.width(), self.height(),
            self._current_depth(), self._current_length(), L["curlRadius"],
        )

    def _ring_center(self, index):
        w, h = self.width(), self.height()
        length = self._current_length()
        depth = self._current_depth()
        vertical = self._vertical()
        along = ring_center(index, vertical) * (length / max(1e-6, self._full_length()))
        if self._edge == "right":
            cx = w - depth + L["ringMargin"] + L["ringDiameter"] / 2
            cy = (h - length) / 2 + along
        elif self._edge == "left":
            cx = depth - L["ringMargin"] - L["ringDiameter"] / 2
            cy = (h - length) / 2 + along
        elif self._edge == "top":
            cx = (w - length) / 2 + along
            cy = depth - L["ringMargin"] - L["ringDiameter"] / 2
        else:
            cx = (w - length) / 2 + along
            cy = h - depth + L["ringMargin"] + L["ringDiameter"] / 2
        return cx, cy

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        body = QColor(Appearance["color"])
        body.setAlphaF(Appearance["opacity"])
        painter.setBrush(body)
        painter.drawPath(self._notch_path())

        t = max(0.0, min(1.0, self._progress))
        if t < 0.08:
            return

        for i, provider in enumerate(self._store.providers):
            cx, cy = self._ring_center(i)
            state = self._store.state_of(provider.id)
            activity = self._store.activity(provider.id)
            snapshot = (state or {}).get("snapshot")
            dual = dual_ring_windows(snapshot)
            headline = headline_of(snapshot)
            fraction = headline.get("usedFraction") if headline else None
            dim = 1.0 if (state or {}).get("status") == "ok" else 0.45
            painter.setOpacity(t * dim)
            badge = getattr(provider, "badge", None)
            if dual:
                outer_frac, inner_frac = dual["outer"], dual["inner"]
                outer_target = max(0.0, min(1.0, outer_frac))
                inner_target = max(0.0, min(1.0, inner_frac))
                outer_cur = self._sweeps.get(provider.id, 0)
                inner_cur = self._inner_sweeps.get(provider.id, 0)
                self._sweeps[provider.id] = outer_cur + (outer_target - outer_cur) * SWEEP_LERP
                self._inner_sweeps[provider.id] = inner_cur + (inner_target - inner_cur) * SWEEP_LERP
                self._paint_dual_ring(
                    painter, cx, cy,
                    self._sweeps[provider.id], self._inner_sweeps[provider.id],
                    outer_frac, inner_frac, provider.glyph, badge,
                )
            else:
                target = 0 if fraction is None else max(0.0, min(1.0, fraction))
                current = self._sweeps.get(provider.id, 0)
                self._sweeps[provider.id] = current + (target - current) * SWEEP_LERP
                self._paint_ring(
                    painter, cx, cy, self._sweeps[provider.id], fraction,
                    provider.glyph, badge,
                )
            self._paint_activity(painter, cx, cy, activity)
            if L["showLabels"]:
                painter.setOpacity(t)
                label = headline_text(snapshot) if snapshot else "—"
                self._paint_label(painter, cx, cy, label)
            painter.setOpacity(1)

        if self._hover_index >= 0 and t > 0.7:
            self._paint_card(painter, self._hover_index)
        if t > 0.35:
            self._paint_theme_toggle(painter, t)
            self._paint_menu_button_footer(painter, t)

    def _theme_toggle_index(self):
        return len(self._store.providers)

    def _theme_toggle_center(self):
        return self._ring_center(self._theme_toggle_index())

    def _theme_toggle_scale(self):
        return L["themeToggleScale"]

    def _theme_ring_radius(self):
        diameter = L["ringDiameter"] * self._theme_toggle_scale()
        return diameter / 2 - L["trackStroke"] * self._theme_toggle_scale() / 2

    def _paint_theme_divider(self, painter, t):
        providers = self._store.providers
        if not providers:
            return
        cx1, cy1 = self._ring_center(len(providers) - 1)
        cx2, cy2 = self._theme_toggle_center()
        mx, my = (cx1 + cx2) / 2, (cy1 + cy2) / 2
        span = L["ringDiameter"] * 0.52
        pen = QPen(QColor(Palette["ringTrack"]))
        pen.setWidthF(max(1.0, L["hairline"]))
        painter.setPen(pen)
        painter.setOpacity(t)
        if self._vertical():
            painter.drawLine(QPointF(mx - span / 2, my), QPointF(mx + span / 2, my))
        else:
            painter.drawLine(QPointF(mx, my - span / 2), QPointF(mx, my + span / 2))
        painter.setOpacity(1.0)

    def _paint_theme_toggle(self, painter, t):
        cx, cy = self._theme_toggle_center()
        painter.save()
        painter.setOpacity(t)
        self._paint_theme_divider(painter, t)
        radius = self._theme_ring_radius()
        track = QPen(QColor(Palette["ringTrack"]))
        track.setWidthF(L["trackStroke"] * self._theme_toggle_scale())
        track.setCapStyle(Qt.FlatCap)
        painter.setPen(track)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        icon_size = L["glyphSize"] * self._theme_toggle_scale() * 1.08
        kind = "sun" if is_dark_notch() else "moon"
        draw_theme_icon(painter, kind, cx, cy, icon_size, Palette["textPrimary"])
        painter.restore()

    def _hit_theme_toggle(self, pos):
        if self._progress < 0.4:
            return False
        cx, cy = self._theme_toggle_center()
        hit_radius = L["ringDiameter"] * self._theme_toggle_scale() / 2
        return math.hypot(pos.x() - cx, pos.y() - cy) <= hit_radius

    def _toggle_theme(self):
        new_mode = toggle_fixed_mode(is_dark_notch())
        self._theme_mode = new_mode
        self._config["themeMode"] = new_mode
        if self._on_theme_change:
            self._on_theme_change(new_mode)
        self.update()

    def _menu_button_center(self):
        w, h = self.width(), self.height()
        length = self._current_length()
        depth = self._current_depth()
        size = L["glyphSize"] * L["themeButtonScale"]
        if self._edge == "right":
            return w - depth / 2, (h + length) / 2 - L["padBottom"] * 0.42, size
        if self._edge == "left":
            return depth / 2, (h + length) / 2 - L["padBottom"] * 0.42, size
        if self._edge == "top":
            return (w + length) / 2 - L["padBottom"] * 0.42, depth / 2, size
        return (w + length) / 2 - L["padBottom"] * 0.42, h - depth / 2, size

    def _hit_menu_button(self, pos):
        if self._progress < 0.35:
            return False
        cx, cy, size = self._menu_button_center()
        return math.hypot(pos.x() - cx, pos.y() - cy) <= size * 0.62

    def _paint_menu_button_footer(self, painter, progress):
        cx, cy, size = self._menu_button_center()
        self._paint_menu_button(painter, progress, cx, cy, size)

    def _paint_menu_button(self, painter, progress, cx, cy, size):
        painter.save()
        painter.setOpacity(progress)
        icon = QColor(Palette["textPrimary"])
        dot = max(2.0, size * 0.07)
        gap = dot * 2.2
        painter.setPen(Qt.NoPen)
        painter.setBrush(icon)
        for offset in (-gap, 0, gap):
            painter.drawEllipse(QPointF(cx + offset, cy), dot, dot)
        painter.restore()

    def _paint_arc_ring(self, painter, cx, cy, radius, sweep, fraction, track_stroke, progress_stroke):
        track = QPen(QColor(Palette["ringTrack"]))
        track.setWidthF(track_stroke)
        track.setCapStyle(Qt.FlatCap)
        painter.setPen(track)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        if fraction is not None and sweep > 0:
            color = band_color(band(fraction))
            progress = QPen(QColor(color))
            progress.setWidthF(progress_stroke)
            progress.setCapStyle(Qt.RoundCap)
            painter.setPen(progress)
            span = -360 * sweep
            painter.drawArc(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                90 * 16,
                int(span * 16),
            )

    def _paint_ring(self, painter, cx, cy, sweep, fraction, glyph, badge=None):
        radius = L["ringDiameter"] / 2 - L["trackStroke"] / 2
        self._paint_arc_ring(
            painter, cx, cy, radius, sweep, fraction,
            L["trackStroke"], L["progressStroke"],
        )
        painter.setPen(Qt.NoPen)
        glyph_alpha = 0.35 if glyph_dimmed(fraction) else 1.0
        draw_glyph(painter, glyph, cx, cy, L["glyphSize"], glyph_alpha, badge=badge)

    def _paint_dual_ring(self, painter, cx, cy, outer_sweep, inner_sweep, outer_frac, inner_frac, glyph, badge=None):
        outer_radius = L["ringDiameter"] / 2 - L["trackStroke"] / 2
        inner_radius = (
            outer_radius - L["innerRingGap"]
            - (L["trackStroke"] + L["innerTrackStroke"]) / 2
        )
        self._paint_arc_ring(
            painter, cx, cy, outer_radius, outer_sweep, outer_frac,
            L["trackStroke"], L["progressStroke"],
        )
        self._paint_arc_ring(
            painter, cx, cy, inner_radius, inner_sweep, inner_frac,
            L["innerTrackStroke"], L["innerProgressStroke"],
        )
        painter.setPen(Qt.NoPen)
        glyph_alpha = 0.35 if glyph_dimmed(inner_frac) else 1.0
        draw_glyph(painter, glyph, cx, cy, L["glyphSize"], glyph_alpha, badge=badge)

    def _paint_activity(self, painter, cx, cy, activity):
        state = None if not activity or activity.get("state") == "idle" else activity.get("state")
        if not state:
            return
        radius = L["activityDiameter"] / 2
        pen = QPen()
        pen.setWidthF(L["activityStroke"])
        pen.setCapStyle(Qt.RoundCap)
        painter.setBrush(Qt.NoBrush)
        if state == "working":
            pen.setColor(QColor(Palette["textPrimary"]))
            painter.setPen(pen)
            start = -90 + self._activity_phase * 360
            painter.drawArc(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                int(start * 16),
                90 * 16,
            )
        else:
            color = QColor(Palette["watch"])
            color.setAlphaF(1 - 0.7 * abs(math.sin(self._activity_phase * math.pi)))
            pen.setColor(color)
            painter.setPen(pen)
            painter.drawEllipse(QPointF(cx, cy), radius, radius)

    def _paint_label(self, painter, cx, cy, text):
        font = QFont("Noto Sans")
        if font.family() != "Noto Sans":
            font = QFont()
        font.setPixelSize(max(9, int(round(L["percentFont"]))))
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(Palette["textPrimary"]))
        rect = QRectF(
            cx - L["bodyDepth"] / 2,
            cy + L["ringDiameter"] / 2 + L["ringLabelGap"] - 2,
            L["bodyDepth"],
            L["percentLineHeight"] + 4,
        )
        painter.drawText(rect, Qt.AlignHCenter | Qt.AlignTop, text)

    def _card_metrics(self, index):
        provider = self._store.providers[index]
        state = self._store.state_of(provider.id) or {}
        snapshot = state.get("snapshot")
        windows = (snapshot or {}).get("windows") or []
        extra = 1 if (snapshot or {}).get("note") else 0
        extra += 1 if state.get("error") and snapshot else 0
        activity = self._store.activity(provider.id)
        sess = min(L["sessionCap"], len((activity or {}).get("sessions") or []))
        block = L["headerToBlock"] + L["labelToBar"] + L["barHeight"] + L["barToUsed"] + L["bodyFont"] * 1.4 + L["blockSpacing"]
        height = (
            L["cardPadding"] * 2
            + L["glyphSize"]
            + extra * (L["bodyFont"] * 1.4 + L["headerToBlock"])
            + max(1, len(windows)) * block
            + sess * (L["bodyFont"] * 2.8 + L["blockSpacing"])
        )
        height = max(height, 120)
        cx, cy = self._ring_center(index)
        w = L["cardWidth"]
        tail = L["tailLength"]
        gap = L["tailGap"]
        depth = self._current_depth()
        if self._edge == "right":
            tip_x = self.width() - depth - gap
            x = tip_x - tail - w
            y = cy - height / 2
            y = max(L["envelopeMargin"], min(self.height() - height - L["envelopeMargin"], y))
            return QRectF(x, y, w, height), "right", cy - y, provider, state, activity
        if self._edge == "left":
            tip_x = depth + gap
            x = tip_x + tail
            y = cy - height / 2
            y = max(L["envelopeMargin"], min(self.height() - height - L["envelopeMargin"], y))
            return QRectF(x, y, w, height), "left", cy - y, provider, state, activity
        if self._edge == "top":
            tip_y = depth + gap
            y = tip_y + tail
            x = cx - w / 2
            x = max(L["envelopeMargin"], min(self.width() - w - L["envelopeMargin"], x))
            return QRectF(x, y, w, height), "top", cx - x, provider, state, activity
        tip_y = self.height() - depth - gap
        y = tip_y - tail - height
        x = cx - w / 2
        x = max(L["envelopeMargin"], min(self.width() - w - L["envelopeMargin"], x))
        return QRectF(x, y, w, height), "bottom", cx - x, provider, state, activity

    def _paint_card(self, painter, index):
        rect, side, tip, provider, state, activity = self._card_metrics(index)
        if rect.isNull():
            return
        path = card_path(
            rect.x(), rect.y(), rect.width(), rect.height(),
            L["cardCorner"], side, L["tailLength"], L["tailHeight"], tip,
        )
        body = QColor(Appearance["color"])
        body.setAlphaF(Appearance["opacity"])
        painter.setPen(Qt.NoPen)
        painter.setBrush(body)
        painter.drawPath(path)

        x = rect.x() + L["cardPadding"]
        y = rect.y() + L["cardPadding"]
        draw_glyph(
            painter, provider.glyph, x + L["glyphSize"] / 2, y + L["glyphSize"] / 2,
            L["glyphSize"], badge=getattr(provider, "badge", None),
        )
        self._text(
            painter, f"{provider.display_name} Usage",
            x + L["glyphSize"] + L["headerGap"], y + 4,
            L["titleFont"], Palette["textPrimary"], bold=True,
        )
        y += L["glyphSize"] + L["headerToBlock"]
        snapshot = state.get("snapshot")
        now = datetime.now().astimezone()
        if not snapshot:
            if state.get("fetching"):
                msg = "Reading usage…"
            else:
                err = state.get("error")
                msg = str(err) if err else "No usage data yet"
            self._text(painter, msg, x, y, L["bodyFont"], Palette["textSecondary"])
            return
        if snapshot.get("note"):
            self._text(painter, snapshot["note"], x, y, L["bodyFont"], Palette["textSecondary"])
            y += L["bodyFont"] * 1.5 + L["blockSpacing"]
        for window in snapshot.get("windows") or []:
            resets_at = window.get("resetsAt")
            reset = reset_text(resets_at, now) if resets_at else ""
            self._text(painter, window.get("label") or "", x, y, L["bodyFont"], Palette["textPrimary"])
            if reset:
                self._text(
                    painter, reset, x, y, L["bodyFont"], Palette["textSecondary"],
                    width=L["cardTextWidth"], align=Qt.AlignRight,
                )
            y += L["bodyFont"] + L["labelToBar"]
            frac = window.get("usedFraction")
            if isinstance(frac, (int, float)):
                self._usage_bar(painter, x, y, L["cardTextWidth"], frac)
                y += L["barHeight"] + L["barToUsed"]
                self._text(painter, f"{percent_text(frac)} Used", x, y, L["bodyFont"], Palette["textPrimary"])
                y += L["bodyFont"] + L["blockSpacing"]
            else:
                self._text(
                    painter,
                    count_text(window.get("used") or 0, snapshot.get("fidelity") == "derived"),
                    x, y, L["bodyFont"], Palette["textPrimary"],
                )
                y += L["bodyFont"] + L["blockSpacing"]
        if state.get("error") and snapshot.get("fetchedAt"):
            err = state["error"]
            kind = getattr(err, "kind", "")
            lead = "Waiting for the API" if kind == "rateLimited" else "Couldn't refresh"
            fetched = datetime.fromtimestamp(snapshot["fetchedAt"] / 1000)
            self._text(
                painter,
                f"{lead} · last read {elapsed_text(fetched, now)} ago",
                x, y, L["bodyFont"], Palette["textSecondary"],
            )
            y += L["bodyFont"] + L["blockSpacing"]
        y = self._paint_sessions(painter, x, y, activity, now)

    def _paint_sessions(self, painter, x, y, activity, now):
        sessions = (activity or {}).get("sessions") or []
        if not sessions:
            return y
        rank = {"waiting": 0, "working": 1, "busy": 1, "idle": 2}
        ordered = sorted(
            sessions,
            key=lambda s: (rank.get(s.get("state"), 2), -(s.get("since") or 0)),
        )
        shown = ordered[:L["sessionCap"]]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Palette["ringTrack"]))
        painter.drawRect(QRectF(x, y, L["cardTextWidth"], L["hairline"]))
        y += L["hairline"] + L["blockSpacing"]
        for session in shown:
            state = session.get("state") or "idle"
            color = (
                Palette["ample"] if state in ("busy", "working")
                else Palette["watch"] if state == "waiting"
                else Palette["textSecondary"]
            )
            word = "working" if state in ("busy", "working") else state
            self._status_dot(painter, x, y + L["bodyFont"] * 0.35, color)
            self._text(
                painter, session.get("name") or "Session",
                x + L["statusDot"] + L["statusDotGap"], y,
                L["bodyFont"], Palette["textPrimary"],
            )
            self._text(
                painter, word, x, y, L["bodyFont"], color,
                width=L["cardTextWidth"], align=Qt.AlignRight,
            )
            y += L["bodyFont"] + L["sessionRowGap"]
            detail = session.get("waitingFor") if state == "waiting" else session.get("detail")
            if detail:
                self._text(painter, detail, x, y, L["bodyFont"], Palette["textSecondary"])
                since = session.get("since")
                if since:
                    when = datetime.fromtimestamp(since / 1000 if since > 1e12 else since)
                    self._text(
                        painter, elapsed_text(when, now), x, y, L["bodyFont"],
                        Palette["textSecondary"], width=L["cardTextWidth"], align=Qt.AlignRight,
                    )
                y += L["bodyFont"] + L["blockSpacing"]
        if len(ordered) > len(shown):
            self._text(
                painter, f"and {len(ordered) - len(shown)} more",
                x, y, L["bodyFont"], Palette["textSecondary"],
            )
            y += L["bodyFont"] + L["blockSpacing"]
        return y

    def _status_dot(self, painter, x, y, color):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        r = L["statusDot"] / 2
        painter.drawEllipse(QPointF(x + r, y), r, r)

    def _usage_bar(self, painter, x, y, width, fraction):
        h = L["barHeight"]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Palette["barTrack"]))
        painter.drawRoundedRect(QRectF(x, y, width, h), h / 2, h / 2)
        fill = max(h, width * max(0.0, min(1.0, fraction)))
        painter.setBrush(QColor(band_color(band(fraction))))
        painter.drawRoundedRect(QRectF(x, y, fill, h), h / 2, h / 2)

    def _text(self, painter, text, x, y, size, color, bold=False, width=None, align=Qt.AlignLeft):
        font = QFont("Noto Sans")
        font.setPixelSize(max(9, int(round(size))))
        font.setWeight(QFont.DemiBold if bold else QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(color))
        w = width or L["cardTextWidth"]
        painter.drawText(QRectF(x, y, w, size * 1.4), align | Qt.AlignVCenter, text)

    def _tick_activity(self):
        self._activity_phase = (self._activity_phase + 0.016 / 1.1) % 1.0
        if any((self._store.activity(p.id) or {}).get("state") in ("working", "waiting") for p in self._store.providers):
            self.update()
        elif self._progress not in (0.0, 1.0):
            self.update()

    def _on_progress(self, value):
        self.set_progress(value)

    def _expand(self):
        self._expanded = True
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(MOTION_UNFOLD)
        self._anim.setEasingCurve(QEasingCurve.OutBack)
        self._anim.start()

    def _fold(self):
        if self._always_open:
            return
        self._expanded = False
        self._hover_index = -1
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(0.0)
        self._anim.setDuration(MOTION_FOLD)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.start()

    def _maybe_fold(self):
        if self._pointer_inside():
            return
        self._fold()

    def _pointer_inside(self):
        pos = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(pos):
            return False
        if self._notch_path().contains(pos):
            return True
        if self._hover_index >= 0 and self._progress > 0.7:
            rect, side, tip, *_ = self._card_metrics(self._hover_index)
            path = card_path(rect.x(), rect.y(), rect.width(), rect.height(),
                             L["cardCorner"], side, L["tailLength"], L["tailHeight"], tip)
            if path.contains(pos):
                return True
        if self._progress < 0.2:
            mid_w, mid_h = self.width() / 2, self.height() / 2
            half = L["pillHeight"] / 2 + L["curlRadius"]
            if self._edge == "right" and pos.x() >= self.width() - self._hot_zone:
                return abs(pos.y() - mid_h) <= half
            if self._edge == "left" and pos.x() <= self._hot_zone:
                return abs(pos.y() - mid_h) <= half
            if self._edge == "top" and pos.y() <= self._hot_zone:
                return abs(pos.x() - mid_w) <= half
            if self._edge == "bottom" and pos.y() >= self.height() - self._hot_zone:
                return abs(pos.x() - mid_w) <= half
        return False

    def _hit_cell(self, pos):
        if self._progress < 0.4:
            return -1
        best = -1
        best_d = 1e9
        for i, _p in enumerate(self._store.providers):
            cx, cy = self._ring_center(i)
            d = math.hypot(pos.x() - cx, pos.y() - cy)
            if d < L["ringDiameter"] and d < best_d:
                best, best_d = i, d
        return best

    @staticmethod
    def _screen_has_panel(screen):
        return screen.geometry() != screen.availableGeometry()

    def _sync_fullscreen_visibility(self):
        if not self._hide_fullscreen:
            if not self.isVisible():
                self.show()
            return
        screen = self._primary_screen()
        if not screen:
            return
        if not self._screen_has_panel(screen):
            if not self.isVisible():
                self.show()
            return
        panels_hidden = screen.geometry() == screen.availableGeometry()
        if panels_hidden and self.isVisible():
            self.hide()
        elif not panels_hidden and not self.isVisible():
            self.show()

    def enterEvent(self, _event):
        self._leave_timer.stop()
        if not self._expanded:
            self._open_timer.start(self._open_delay)

    def leaveEvent(self, _event):
        self._open_timer.stop()
        self._leave_timer.start(LEAVE_GRACE_MS)

    def mouseMoveEvent(self, event):
        if self._progress > 0.5:
            self._hover_index = self._hit_cell(event.pos())
            self._update_mask()
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._show_app_menu(event.globalPos())
            return
        if event.button() == Qt.LeftButton:
            if self._hit_theme_toggle(event.pos()):
                self._toggle_theme()
                return
            if self._hit_menu_button(event.pos()):
                self._show_app_menu(event.globalPos())
                return
            idx = self._hit_cell(event.pos())
            if idx >= 0:
                provider = self._store.providers[idx]
                open_url(provider.manage_url)
                self._store.refresh(provider.id)
                if provider.id == "cursor-corp":
                    QTimer.singleShot(5000, lambda: self._store.refresh(provider.id))

    def _show_app_menu(self, global_pos):
        if self._open_menu:
            self._open_menu(global_pos)
            return
        menu = QMenu(self)
        always = QAction("Sempre aberto", menu)
        always.setCheckable(True)
        always.setChecked(self._always_open)
        always.toggled.connect(self._set_always_open)
        menu.addAction(always)
        quit_act = QAction("Sair do Codenotch", menu)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_act)
        menu.exec_(global_pos)

    def _set_always_open(self, checked):
        self._always_open = checked
        self._config["alwaysOpen"] = checked
        if checked:
            self._expand()
        else:
            self._fold()
