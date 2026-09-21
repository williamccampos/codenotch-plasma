"""Geometry and palette measured from Codenotch's design frame (layout.js)."""

FRAME_SCALE = 44 / 117
CAP_RATIO = 0.714

L = {}
Appearance = {"color": "#000000", "opacity": 1.0}


def set_appearance(color="#000000", opacity=1.0):
    Appearance["color"] = color or "#000000"
    Appearance["opacity"] = max(0.1, min(1.0, float(opacity)))


def configure_layout(scale=1.0, show_labels=True, text_scale=1.0):
    def px(p):
        return p * FRAME_SCALE * scale

    def font_size(cap):
        return px(cap) / CAP_RATIO * text_scale

    L.update({
        "bodyDepth": px(186),
        "curlRadius": px(103),
        "cornerRadius": px(78.8),
        "padTop": px(69.5),
        "padBottom": px(50.1),
        "cellSpacing": px(83.5),
        "pillWidth": px(26),
        "pillHeight": px(210),
        "pillHotZone": px(90),
        "ringDiameter": px(117),
        "trackStroke": px(15.5),
        "progressStroke": px(8),
        "innerRingGap": px(11),
        "innerTrackStroke": px(9),
        "innerProgressStroke": px(4.5),
        "glyphSize": px(46),
        "ringLabelGap": px(26.9) if show_labels else 0,
        "percentFont": font_size(27),
        "activityDiameter": px(72),
        "activityStroke": px(5.5),
        "cardWidth": px(600) * text_scale,
        "cardCorner": px(49.5),
        "cardPadding": px(32),
        "tailLength": px(75),
        "tailHeight": px(87),
        "tailGap": px(28),
        "barHeight": px(10.5),
        "headerGap": px(17),
        "headerToBlock": px(21),
        "labelToBar": px(16.8),
        "barToUsed": px(17.8),
        "blockSpacing": px(20),
        "sessionRowGap": px(10),
        "statusDot": px(17),
        "statusDotStroke": px(3.4),
        "statusDotGap": px(11),
        "hairline": 1,
        "titleFont": font_size(26),
        "bodyFont": font_size(18),
        "envelopeMargin": 16 * scale,
        "envelopeSlack": 48 * scale,
        "sessionCap": 4,
        "showLabels": show_labels,
    })
    L["percentLineHeight"] = int(L["percentFont"] * 1.25) if show_labels else 0
    L["ringMargin"] = (L["bodyDepth"] - L["ringDiameter"]) / 2
    L["cellExtent"] = L["ringDiameter"] + L["ringLabelGap"] + L["percentLineHeight"]
    L["bodyDepthH"] = 2 * L["ringMargin"] + L["cellExtent"]
    L["cardTextWidth"] = L["cardWidth"] - 2 * L["cardPadding"]


configure_layout()

Palette = {
    "ringTrack": "#303030",
    "barTrack": "#2D2D2D",
    "ample": "#00FF88",
    "watch": "#F2FF00",
    "critical": "#FF3F00",
    "textPrimary": "#FFFFFF",
    "textSecondary": "#808080",
}


def cell_along(vertical):
    return L["cellExtent"] if vertical else L["ringDiameter"]


def cell_pitch(vertical):
    return cell_along(vertical) + L["cellSpacing"]


def _pad_start(vertical):
    return L["padTop"] if vertical else (L["padTop"] + L["padBottom"]) / 2


def _pad_end(vertical):
    return L["padBottom"] if vertical else (L["padTop"] + L["padBottom"]) / 2


def body_depth(vertical):
    return L["bodyDepth"] if vertical else L["bodyDepthH"]


def body_length(cell_count, vertical):
    if cell_count <= 0:
        return _pad_start(vertical) + _pad_end(vertical)
    return (
        _pad_start(vertical)
        + cell_count * cell_along(vertical)
        + (cell_count - 1) * L["cellSpacing"]
        + _pad_end(vertical)
    )


def shape_length(cell_count, vertical):
    return body_length(cell_count, vertical) + 2 * L["curlRadius"]


def ring_center(index, vertical):
    return (
        L["curlRadius"]
        + _pad_start(vertical)
        + L["ringDiameter"] / 2
        + index * cell_pitch(vertical)
    )


def band(fraction):
    if fraction is None:
        return None
    if fraction >= 1:
        return "exhausted"
    if fraction >= 0.7:
        return "critical"
    if fraction >= 0.5:
        return "watch"
    return "ample"


def band_color(b):
    if b == "ample":
        return Palette["ample"]
    if b == "watch":
        return Palette["watch"]
    return Palette["critical"]
