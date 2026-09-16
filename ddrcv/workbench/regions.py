"""Render recognition evidence on a copy of the frame; never on the OBS feed."""
from collections import OrderedDict

import cv2

STATE_NAMES = dict(unknown='Unknown', login='Login', song_select='Song select',
                   song_splash='Song splash', song_playing='Gameplay',
                   song_result='Song results', total_result='Total results')
# BGR: blue for matches/production reads, gray for misses, amber for diagnostics.
ACTIVE = (250, 190, 115)
MISSED = (185, 185, 185)
DIAGNOSTIC = (110, 195, 245)


def draw_monitored_regions(frame, regions):
    height, width = frame.shape[:2]
    grouped = OrderedDict()
    for region in regions:
        key = (region['kind'], region.get('state'), tuple(region['roi']))
        grouped.setdefault(key, []).append(region)
    labels = []
    for (kind, state, roi), checks in grouped.items():
        x, y, w, h = roi
        left, top = max(0, x), max(0, y)
        right, bottom = min(width - 1, x + w - 1), min(height - 1, y + h - 1)
        if left > right or top > bottom:
            continue
        if kind == 'state':
            matched = sum(check['matched'] for check in checks)
            color = ACTIVE if matched else MISSED
            label = f"{STATE_NAMES.get(state, state or 'State')}: {'match' if matched else 'no match'}"
            if len(checks) > 1:
                label += f' ({matched}/{len(checks)})'
            dashed = not matched
        else:
            diagnostic = checks[0]['use'] == 'diagnostic'
            color, dashed = (DIAGNOSTIC, True) if diagnostic else (ACTIVE, False)
            decision = checks[0]['decision']
            reason = dict(accepted='accepted', jump_limit='increase rejected', decrease='decrease rejected',
                          no_digits='no digits', no_read='unread').get(decision, 'read')
            label = f"{checks[0]['player'].upper()} score: {'diagnostic only' if diagnostic else reason}"
        if dashed:
            for start in range(left, right, 12):
                cv2.line(frame, (start, top), (min(start + 6, right), top), color, 1)
                cv2.line(frame, (start, bottom), (min(start + 6, right), bottom), color, 1)
            for start in range(top, bottom, 12):
                cv2.line(frame, (left, start), (left, min(start + 6, bottom)), color, 1)
                cv2.line(frame, (right, start), (right, min(start + 6, bottom)), color, 1)
        else:
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        text_width, text_height = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .55, 1)[0]
        label_width, label_height = text_width + 10, text_height + 10
        lx = min(left, max(0, width - label_width))
        ly = top - label_height if top >= label_height else min(bottom + 1, height - label_height)
        # Alternate templates can overlap. Move their labels, keeping a leader
        # line back to the exact ROI instead of concealing one another.
        for _ in range(len(labels) + 1):
            overlap = any(lx < px + pw and lx + label_width > px and ly < py + ph and ly + label_height > py
                          for px, py, pw, ph in labels)
            if not overlap:
                break
            ly = ly - label_height - 2 if ly >= label_height + 2 else min(height - label_height, bottom + 4 + len(labels) * (label_height + 2))
        labels.append((lx, ly, label_width, label_height))
        cv2.line(frame, (left, top), (lx, ly + label_height), color, 1)
        cv2.rectangle(frame, (lx, ly), (lx + label_width, ly + label_height), (25, 26, 29), -1)
        cv2.putText(frame, label, (lx + 5, ly + text_height + 3), cv2.FONT_HERSHEY_SIMPLEX, .55, color, 1, cv2.LINE_AA)
    return frame
