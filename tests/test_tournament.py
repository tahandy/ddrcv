import asyncio
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ddrcv.apps.tournament_session import TournamentSession
from ddrcv.score.temporal import ScoreTracker
from ddrcv.state.temporal import StateDebouncer
from apps.obs.scene_policy import ScenePolicy
from apps.obs.state_stream import consume_states


def observe_for(session, state, start, duration=0.4, data=None):
    for i in range(round(duration / 0.02) + 1):
        session.observe(state, data, start + i * 0.02)
    return start + duration


class StateTests(unittest.TestCase):
    def test_requires_time_and_multiple_frames(self):
        state = StateDebouncer()
        for t in (0, .01, .02):
            self.assertEqual(state.update('song_playing', now=t)[0], 'unknown')
        for i in range(3, 15):
            state.update('song_playing', now=i * .02)
        self.assertEqual(state.state, 'song_playing')

    def test_twenty_percent_wrong_frames_still_converge(self):
        state = StateDebouncer()
        for i in range(61):
            raw = 'song_result' if i % 5 == 0 else 'song_playing'
            state.update(raw, now=i / 60)
        self.assertEqual(state.state, 'song_playing')

    def test_single_wrong_screen_and_brief_unknown_hold_state(self):
        session = TournamentSession()
        observe_for(session, 'song_playing', 0)
        session.observe('song_select', None, .42)
        for t in (.44, .46, .48):
            session.observe('unknown', None, t)
        self.assertEqual(session.info['state'], 'song_playing')
        self.assertFalse(session.needs_scores)

    def test_prolonged_unknown_expires_but_can_recover(self):
        session = TournamentSession()
        observe_for(session, 'song_playing', 0)
        observe_for(session, 'unknown', .42, 1.2)
        self.assertEqual(session.info['state'], 'unknown')
        observe_for(session, 'song_result', 1.64)
        self.assertEqual(session.info['state'], 'song_result')

    def test_capture_gap_does_not_confirm_a_single_frame(self):
        state = StateDebouncer()
        state.update('song_playing', now=0)
        state.update('song_playing', now=.01)
        self.assertEqual(state.update('song_playing', now=10)[0], 'unknown')

    def test_alternating_ambiguous_screens_do_not_switch(self):
        state = StateDebouncer()
        for i in range(60):
            state.update('song_playing' if i % 2 else 'song_select', now=i / 60)
        self.assertEqual(state.state, 'unknown')


class ScoreTests(unittest.TestCase):
    def test_none_limit_accepts_money_score_jumps_but_preserves_other_checks(self):
        tracker = ScoreTracker(max_per_frame=None)
        self.assertEqual(tracker.update(0, 0), 0)
        self.assertEqual(tracker.update(123456, .01), 123456)
        self.assertEqual(tracker.update(987654, .02), 987654)
        self.assertEqual(tracker.update(123, .03), 987654)
        self.assertEqual(tracker.update(-1, .04), 987654)
        self.assertIsNone(tracker.update(None, .05))

    def test_nonpositive_limits_remain_invalid(self):
        for limit in (0, -12):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                ScoreTracker(max_per_frame=limit)

    def test_missed_frames_allow_more_than_twelve(self):
        tracker = ScoreTracker()
        self.assertEqual(tracker.update(100, 0), 100)
        self.assertEqual(tracker.update(160, .1), 160)

    def test_rejected_value_does_not_permanently_lock_tracking(self):
        tracker = ScoreTracker()
        tracker.update(100, 0)
        self.assertEqual(tracker.update(160, .01), 100)
        self.assertEqual(tracker.update(160, .1), 160)

    def test_bad_read_and_decrease_preserve_score(self):
        tracker = ScoreTracker()
        tracker.update(100, 0)
        self.assertEqual(tracker.update(99999, .02), 100)
        self.assertEqual(tracker.update(10, .03), 100)
        self.assertEqual(tracker.update(-1, .04), 100)
        self.assertEqual(tracker.update(112, .05), 112)

    def test_no_valid_initial_read_and_absent_player(self):
        tracker = ScoreTracker()
        self.assertEqual(tracker.update(-1, 0), -1)
        self.assertIsNone(tracker.update(None, .1))
        self.assertEqual(tracker.update(1234, .2), 1234)

    def test_reset_accepts_next_song_start(self):
        tracker = ScoreTracker()
        tracker.update(3000, 0)
        tracker.reset()
        self.assertEqual(tracker.update(0, 1), 0)


class SessionTests(unittest.TestCase):
    def test_json_null_disables_jump_limit_for_both_players(self):
        config = json.loads('{"score_filter": {"max_per_frame": null}}')
        session = TournamentSession(**config)
        observe_for(session, 'song_playing', 0)
        session.record_scores({'p1_score': 0, 'p2_score': 0}, .4)
        session.record_scores({'p1_score': 123456, 'p2_score': 234567}, .41)
        self.assertEqual(session.info['score'], {'p1_score': 123456, 'p2_score': 234567})

    def test_unknown_does_not_reset_current_scores(self):
        session = TournamentSession()
        observe_for(session, 'song_playing', 0)
        session.record_scores({'p1_score': 100, 'p2_score': 120}, .4)
        observe_for(session, 'unknown', .42, 1.2)
        observe_for(session, 'song_playing', 1.64)
        session.record_scores({'p1_score': 90, 'p2_score': 110}, 2.04)
        self.assertEqual(session.info['score'], {'p1_score': 100, 'p2_score': 120})

    def test_next_song_resets_even_when_select_and_splash_were_missed(self):
        session = TournamentSession()
        observe_for(session, 'song_playing', 0)
        session.record_scores({'p1_score': 1000, 'p2_score': 1200}, .4)
        observe_for(session, 'song_result', .42)
        observe_for(session, 'song_playing', .84)
        session.record_scores({'p1_score': 3, 'p2_score': 6}, 1.24)
        self.assertEqual(session.info['score'], {'p1_score': 3, 'p2_score': 6})

    def test_single_player_then_duo_presence_resets(self):
        session = TournamentSession()
        observe_for(session, 'song_splash', 0, data={'p1_present': True, 'p2_present': False})
        observe_for(session, 'song_playing', .42)
        session.record_scores({'p1_score': 100, 'p2_score': None}, .82)
        self.assertEqual(session.info['score'], {'p1_score': 100, 'p2_score': None})
        observe_for(session, 'song_select', .84)
        self.assertEqual(session.info['players'], (True, True))
        self.assertIsNone(session.info['score'])

    def test_held_gameplay_does_not_extract_on_results_frames(self):
        session = TournamentSession()
        observe_for(session, 'song_playing', 0)
        session.observe('song_result', None, .42)
        self.assertEqual(session.info['state'], 'song_playing')
        self.assertFalse(session.needs_scores)
        session.record_scores({'p1_score': 99999, 'p2_score': 99999}, .42)
        self.assertIsNone(session.info['score'])

    def test_results_gap_does_not_duplicate_screenshot(self):
        session = TournamentSession()
        observe_for(session, 'song_result', 0, 1)
        self.assertTrue(session.screenshot_due(1, .5))
        session.results_saved = True
        observe_for(session, 'unknown', 1.02, 1.2)
        observe_for(session, 'song_result', 2.24, 1)
        self.assertFalse(session.screenshot_due(3.24, .5))
        observe_for(session, 'song_select', 3.26)
        self.assertFalse(session.results_saved)

    def test_screenshot_wait_does_not_block_new_state(self):
        session = TournamentSession()
        observe_for(session, 'song_result', 0)
        self.assertFalse(session.screenshot_due(.4, 5))
        observe_for(session, 'song_select', .42)
        self.assertEqual(session.info['state'], 'song_select')
        self.assertFalse(session.screenshot_due(10, 5))


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.policy = ScenePolicy(clock=lambda: self.now)
        self.client = Mock()
        self.client.get_current_program_scene.return_value = SimpleNamespace(current_program_scene_name='Commentator')

    def send(self, state, override=False):
        self.policy({'state': state}, {'state': state}, self.client, override=override)

    def test_startup_mid_song_and_missed_transition_reconcile(self):
        self.send('song_playing')
        self.client.set_current_program_scene.assert_called_once_with('Gameplay')

    def test_already_correct_scene_does_not_repeat_switch(self):
        self.client.get_current_program_scene.return_value.current_program_scene_name = 'Gameplay'
        for i in range(10):
            self.now = i * .1
            self.send('song_playing')
        self.client.set_current_program_scene.assert_not_called()

    def test_failed_switch_retries_without_new_state(self):
        self.client.set_current_program_scene.side_effect = [RuntimeError('temporary'), None]
        with self.assertLogs('apps.obs.scene_policy', level='ERROR'):
            self.send('song_playing')
        self.now = .1
        self.send('song_playing')
        self.assertEqual(self.client.set_current_program_scene.call_count, 1)
        self.now = .5
        self.send('song_playing')
        self.assertEqual(self.client.set_current_program_scene.call_count, 2)

    def test_override_holds_and_resume_reconciles(self):
        self.send('song_playing', override=True)
        self.client.get_current_program_scene.assert_not_called()
        self.send('song_playing', override=False)
        self.client.set_current_program_scene.assert_called_once_with('Gameplay')

    def test_unknown_holds_scene(self):
        self.send('unknown')
        self.client.get_current_program_scene.assert_not_called()

    def test_configurable_mapping_and_null_hold(self):
        self.policy = ScenePolicy({'song_result': 'Results', 'song_select': None}, clock=lambda: self.now)
        self.send('song_select')
        self.client.get_current_program_scene.assert_not_called()
        self.send('song_result')
        self.client.set_current_program_scene.assert_called_once_with('Results')


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_retry_invalid_messages_and_stop(self):
        stop = threading.Event()
        received, statuses = [], []
        attempts = []

        class Socket:
            def __init__(self):
                self.messages = iter(['not json', '[]', '{}', json.dumps({'state': 'song_playing'})])
            async def recv(self):
                return next(self.messages)

        class Connection:
            async def __aenter__(self):
                if len(attempts) == 1:
                    raise OSError('driver restarting')
                return Socket()
            async def __aexit__(self, *args):
                return False

        def connect(*args, **kwargs):
            attempts.append(1)
            return Connection()

        def receive(message):
            received.append(message)
            stop.set()

        with self.assertLogs('apps.obs.state_stream', level='WARNING'):
            await asyncio.wait_for(consume_states(connect, 'ws://test', stop, receive, statuses.append,
                                                   reconnect_delay=0), 2)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(received, [{'state': 'song_playing'}])
        self.assertEqual(statuses, [False, True, False])

    async def test_stop_interrupts_idle_receive(self):
        stop = threading.Event()
        class Connection:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def recv(self):
                stop.set()
                await asyncio.Future()
        await asyncio.wait_for(consume_states(lambda *a, **k: Connection(), 'ws://test', stop,
                                               lambda message: None, lambda status: None), 1)


if __name__ == '__main__':
    unittest.main()
