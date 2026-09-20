"""The same per-frame recognizer for live operation and local rehearsal."""
from copy import deepcopy
from contextlib import nullcontext
import cv2

from ddrcv.apps.tournament_session import TournamentSession
from ddrcv.score.score_extractor import ScoreExtractor
from ddrcv.state.world_states import StateRotation
from ddrcv.ingest.file_source import normalize_frame
from ddrcv.state.region_monitor import collect_regions


class RecognitionEngine:
    def __init__(self, config=None, matcher=None, extractor=None):
        # Small, fixed ROI operations don't benefit from a machine-wide OpenCV pool.
        cv2.setNumThreads(1)
        self.config = deepcopy(config or {})
        self.config['debounce'] = {**dict(confirm_seconds=.2, min_frames=3, unknown_seconds=1.0, max_frame_gap=.5, min_fraction=.75), **self.config.get('debounce', {})}
        self.config['score_filter'] = {**dict(game_fps=60, max_per_frame=12), **self.config.get('score_filter', {})}
        self._owns_matcher = matcher is None
        self.matcher = matcher
        self.extractor = extractor or ScoreExtractor(self.config.get('score_extractor', {}).get('glyph_dir'))
        self.reset()

    def reset(self):
        if self._owns_matcher:
            self.matcher = StateRotation(**self.config.get('state', {}))
        self.session = TournamentSession(self.config.get('debounce'), self.config.get('score_filter'))
        self.extractor.set_presence(True, True)
        return deepcopy(self.session.info)

    def process(self, frame, timestamp, frame_index=None, diagnostics=False, stateless=False):
        frame = normalize_frame(frame)
        # Consumers only read small crops and support strided input. Reorder the
        # channels as a view instead of allocating/converting the entire frame.
        rgb = frame[..., ::-1]
        with collect_regions() if diagnostics else nullcontext([]) as regions:
            raw_state, data = self.matcher.match(rgb)
        if not stateless:
            self.session.observe(raw_state, data, timestamp)
        info = self.session.info
        players = (True, True) if stateless else info['players']
        self.extractor.set_presence(*players)
        raw = {'data': None}
        if diagnostics or (not stateless and self.session.needs_scores):
            raw = self.extractor.extract(rgb, debug=diagnostics)
        if not stateless and self.session.needs_scores:
            self.session.record_scores(raw['data'], timestamp)
        reasons = {}
        for key, tracker, present in zip(('p1_score', 'p2_score'), self.session.trackers, players):
            reasons[key] = ('diagnostic_only' if stateless else 'not_gameplay' if not self.session.needs_scores
                            else 'absent' if not present else tracker.last_reason)
            if diagnostics and present:
                top, left, height, width = ScoreExtractor.p1_roi if key == 'p1_score' else ScoreExtractor.p2_roi
                regions.append(dict(kind='score', player=key[:2], roi=[left, top, width, height],
                                    use='production' if not stateless and self.session.needs_scores else 'diagnostic',
                                    decision=reasons[key]))
        return dict(frame_index=frame_index, timestamp=timestamp, raw_state=raw_state,
                    confirmed_state=info['state'], warming_up=not stateless and raw_state != info['state'],
                    stateless=stateless, raw_scores=raw['data'], glyphs=raw.get('debug', {}),
                    decisions=reasons, monitored_regions=regions, published=deepcopy(info))
