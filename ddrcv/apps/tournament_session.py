"""Tournament state and score lifetime, without camera or network side effects."""

from ddrcv.score.temporal import ScoreTracker
from ddrcv.state.temporal import StateDebouncer


class TournamentSession:
    def __init__(self, debounce=None, score_filter=None):
        self.debouncer = StateDebouncer(**(debounce or {}))
        self.trackers = [ScoreTracker(**(score_filter or {})) for _ in range(2)]
        self.info = {'state': 'unknown', 'players': (True, True), 'song': None, 'score': None}
        self.last_known_state = 'unknown'
        self.raw_state = 'unknown'
        self.results_saved = False
        self.results_since = None

    def observe(self, raw_state, data, now):
        self.raw_state = raw_state
        state, stable_data = self.debouncer.update(raw_state, data, now)
        self.info['state'] = state
        if state != 'unknown' and state != self.last_known_state:
            previous = self.last_known_state
            self.last_known_state = state
            if state in ('song_select', 'song_splash', 'login', 'total_result') or (
                    state == 'song_playing' and previous not in ('song_select', 'song_splash')):
                for tracker in self.trackers:
                    tracker.reset()
                self.info.update(players=(True, True), song=None, score=None)
            if state in ('song_select', 'song_splash', 'song_playing', 'login', 'total_result'):
                self.results_saved = False
                self.results_since = None
        # Never use held splash data to infer presence on a different raw screen.
        if state == raw_state == 'song_splash' and stable_data is not None:
            self.info['players'] = (stable_data['p1_present'], stable_data['p2_present'])
        # Unknown gaps must not re-arm a screenshot, but they do restart its
        # settling timer to avoid capturing a wipe immediately on recovery.
        if state == raw_state == 'song_result':
            if self.results_since is None:
                self.results_since = now
        else:
            self.results_since = None
        return self.info

    @property
    def needs_scores(self):
        return self.raw_state == self.info['state'] == 'song_playing'

    def record_scores(self, scores, now):
        if self.needs_scores:
            self.info['score'] = {
                key: tracker.update(scores[key], now) if present else None
                for key, tracker, present in zip(
                    ('p1_score', 'p2_score'), self.trackers, self.info['players'])
            }

    def screenshot_due(self, now, delay):
        return (not self.results_saved and self.results_since is not None
                and now - self.results_since >= delay)
