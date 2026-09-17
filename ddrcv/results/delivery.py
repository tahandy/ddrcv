"""Durable outbox. Only this worker makes network requests; no capture locks."""
from copy import deepcopy
import json
import logging
import math
from pathlib import Path
from queue import Queue, Empty, Full
import re
import threading
import time
from uuid import uuid4
from urllib.parse import urlsplit, unquote

import requests

LOG = logging.getLogger('ddrcv.results')
SECRET_URL = re.compile(r'https?://(?:[\w-]+\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/[^\s\"\'<>]+')


def redact_error(error, webhook=None):
    text = str(error)
    if webhook:
        text = text.replace(webhook, '[redacted webhook]')
        token = webhook.rstrip('/').split('/')[-1]
        if token:
            text = text.replace(token, '[redacted]')
    return SECRET_URL.sub('[redacted webhook]', text)[:500]


def escaped(text):
    return re.sub(r'([\\`*_~|<>@])', r'\\\1', str(text))


def format_payload(record):
    label = 'EX' if record['score_mode'] == 'ex' else 'Money'
    lines = []
    for i, p in enumerate(record['players']):
        if not p['present']:
            lines.append(f'P{i+1}: absent')
            continue
        name = escaped(p['name']) if p['name'] else f'P{i+1} (name unread)'
        score = f"{p['score']:,}" if p['score'] is not None else 'unconfirmed'
        lines.append(f'**{name}** — {label}: **{score}**')
    result = record['outcome']
    if result['kind'] == 'tie':
        lines.append('**TIE**')
    elif result['kind'] == 'winner':
        i = result['winner']
        name = escaped(record['players'][i]['name'] or f'P{i+1}')
        lines.append(f"**Winner: {name} (+{result['margin']:,} EX)**")
    elif sum(p['present'] for p in record['players']) == 1:
        lines.append('Single-player result')
    else:
        lines.append('Winner unavailable — both EX scores must be confirmed.')
    if record['partial']:
        lines.append('Partial result: missing fields are unconfirmed.')
    if not record['screenshot_confirmed']:
        lines.append('Screenshot stability unconfirmed.')
    title = 'Rehearsal — DDR results' if record.get('rehearsal') else 'DDR results'
    return dict(allowed_mentions={'parse': []}, embeds=[dict(title=title, description='\n'.join(lines),
        image={'url': 'attachment://results.png'}, footer={'text': f"Event {record['event_id']}"})])


class DeliveryError(Exception):
    def __init__(self, message, retryable=False, retry_after=None, receipt=None):
        super().__init__(message)
        self.retryable, self.retry_after = retryable, retry_after
        self.receipt = receipt or {}


def message_receipt(body):
    """Discord omits attachments referenced by embeds from message.attachments.

    https://docs.discord.com/developers/resources/message#message-object
    Retain a known message identity even when its image confirmation is invalid.
    """
    if not isinstance(body, dict) or not all(str(body.get(key, '')).isdigit() for key in ('id', 'channel_id')):
        raise DeliveryError('Discord response did not confirm message identity', retryable=True)
    receipt = dict(message_id=body['id'], channel_id=body['channel_id'], message_url=None)
    attached = any(isinstance(a, dict) and a.get('filename') == 'results.png'
                   for a in (body.get('attachments') or []))
    embedded = False
    for embed in (body.get('embeds') or []):
        image = embed.get('image', {}) if isinstance(embed, dict) else {}
        if not isinstance(image, dict):
            continue
        for key in ('url', 'proxy_url'):
            try:
                url = urlsplit(image.get(key, ''))
                parts = unquote(url.path).strip('/').split('/')
                embedded |= (url.scheme == 'https' and url.hostname in ('cdn.discordapp.com', 'media.discordapp.net')
                             and len(parts) == 4 and parts[:2] == ['attachments', str(body['channel_id'])]
                             and parts[2].isdigit() and parts[3] == 'results.png')
            except (ValueError, TypeError, AttributeError):
                pass
    if not attached and not embedded:
        raise DeliveryError('Discord created the message but did not confirm its screenshot; inspect before retrying',
                            receipt=receipt)
    return receipt


def send_record(webhook, record, image_path):
    try:
        with open(image_path, 'rb') as stream:
            response = requests.post(webhook, params={'wait': 'true'},
                data={'payload_json': json.dumps(format_payload(record))},
                files={'files[0]': ('results.png', stream, 'image/png')}, timeout=(3, 10))
    except requests.RequestException as error:
        raise DeliveryError(redact_error(error, webhook), retryable=True) from None
    with response:
        if response.status_code == 429:
            try:
                seconds = float(response.json().get('retry_after', response.headers.get('Retry-After', 1)))
                if not math.isfinite(seconds) or seconds < 0:
                    seconds = 1
            except (ValueError, TypeError, AttributeError):
                seconds = 1
            raise DeliveryError('Discord rate limit', retryable=True, retry_after=seconds)
        if response.status_code >= 500:
            raise DeliveryError(f'Discord HTTP {response.status_code}', retryable=True)
        if response.status_code != 200:
            raise DeliveryError(f'Discord HTTP {response.status_code}')
        try:
            body = response.json()
        except ValueError:
            raise DeliveryError('Discord returned an unreadable acknowledgement', retryable=True) from None
        receipt = message_receipt(body)
        guild_id = body.get('guild_id')
        if not guild_id:
            # This GET cannot turn an acknowledged send into a retry.
            try:
                with requests.get(webhook, timeout=(3, 10)) as metadata:
                    if metadata.status_code == 200:
                        guild_id = metadata.json().get('guild_id')
            except (requests.RequestException, ValueError, AttributeError):
                pass
        if guild_id and str(guild_id).isdigit():
            receipt['message_url'] = f"https://discord.com/channels/{guild_id}/{body['channel_id']}/{body['id']}"
        return receipt



class Outbox:
    def __init__(self, directory, webhook=None, enabled=False, sender=send_record, notify=None):
        self.directory = Path(directory).resolve()
        self.webhook, self.enabled, self.sender, self.notify = webhook, enabled, sender, notify
        self.lock = threading.RLock()
        self.records = {}
        self.intervals = {}
        self.write_lock = threading.RLock()
        self._dirty = None
        self.error = None
        self.commands = Queue(maxsize=32)
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self._lease = None
        self.available = False
        # Initialization is before capture begins. Runtime disk writes run in workers.
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._acquire_lease()
            self.available = True
            for path in self.directory.glob('*/result.json'):
                try:
                    record = json.loads(path.read_text(encoding='utf-8'))
                    if record['event_id'] != path.parent.name:
                        raise ValueError('Outbox event ID mismatch')
                    if record['delivery']['state'] == 'sending':
                        record['delivery'].update(state='retrying', next_attempt=time.time())
                    self.records[record['event_id']] = record
                    self.observe_interval(record['event_id'], record['source_id'], record['score_mode'], *record['interval'])
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.error = f'Cannot recover outbox item {path.parent.name}: {type(exc).__name__}'
        except OSError as exc:
            self.error = redact_error(exc, webhook)
        self.worker = threading.Thread(target=self._run, name='results-discord', daemon=True)
        self.worker.start()

    def _acquire_lease(self):
        # The CLI and panel may point at one outbox. Only one process may send
        # or mutate it; OS locks release automatically after a crash.
        import os
        stream = (self.directory / '.lock').open('a+b')
        try:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise OSError('Results outbox is already in use; close the other driver or choose another outbox') from None
        self._lease = stream

    def configure(self, webhook=None, enabled=False):
        if enabled and not webhook:
            raise ValueError('Set results.webhook before enabling Discord')
        with self.lock:
            self.webhook, self.enabled = webhook, enabled
        self.wake.set()

    def _write(self, record):
        path = self.directory / record['event_id'] / 'result.json'
        temporary = path.with_suffix(f'.{uuid4().hex}.tmp')
        try:
            temporary.write_text(json.dumps(record, indent=2), encoding='utf-8')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _announce(self):
        if self.notify:
            try:
                self.notify()
            except Exception:
                LOG.error('Results status callback failed')

    def save(self, record, frame):
        """Called by the persistence worker. Publish only after image and metadata exist."""
        import cv2
        with self.write_lock:
            if not self.available or self.stopped.is_set():
                raise OSError(self.error or 'Results outbox is unavailable')
            folder = self.directory / record['event_id']
            folder.mkdir(parents=True, exist_ok=True)
            temporary = folder / 'screenshot.tmp.png'
            if not cv2.imwrite(str(temporary), frame):
                raise OSError('Could not encode results screenshot')
            temporary.replace(folder / 'screenshot.png')
            record['screenshot_path'] = str(folder / 'screenshot.png')
            record['delivery'] = dict(state='queued' if record.pop('auto_publish') else 'saved', attempts=0,
                                      error=None, next_attempt=0, message_id=None, message_url=None)
            self._merge_interval(record)
            self._write(record)
            with self.lock:
                self._merge_interval(record)
                self.records[record['event_id']] = deepcopy(record)
                self.observe_interval(record['event_id'], record['source_id'], record['score_mode'], *record['interval'])
        LOG.info('Results %s: %s', record['event_id'], record['delivery']['state'])
        self._announce()
        self.wake.set()

    def snapshot(self):
        with self.lock:
            return dict(error=self.error, available=self.available, records=deepcopy(list(self.records.values())[-20:]))

    def observe_interval(self, event_id, source_id, mode, start, end):
        """Memory only: capture/deduplication never wait for a network or disk operation."""
        with self.lock:
            previous = self.intervals.get(event_id)
            if previous:
                start, end = min(start, previous[2]), max(end, previous[3])
            self.intervals[event_id] = (source_id, mode, start, end)
            if event_id in self.records:
                self._merge_interval(self.records[event_id])

    def forget_interval(self, event_id):
        with self.lock:
            if event_id not in self.records:
                self.intervals.pop(event_id, None)

    def _merge_interval(self, record):
        with self.lock:
            interval = self.intervals.get(record['event_id'])
            if interval:
                record['interval'] = [min(record['interval'][0], interval[2]), max(record['interval'][1], interval[3])]

    def persist_interval(self, event_id):
        with self.write_lock:
            if not self.available or self.stopped.is_set():
                raise OSError('Results outbox is closed')
            with self.lock:
                record = deepcopy(self.records.get(event_id))
            if record is not None:
                self._write(record)

    def find(self, source_id, timestamp, mode):
        with self.lock:
            return next((event_id for event_id, (source, score_mode, start, end) in self.intervals.items()
                         if source == source_id and score_mode == mode
                         and start - .5 <= timestamp <= end + .5), None)

    def command(self, action, event_id, **args):
        if not self.available or self.stopped.is_set():
            raise ValueError(self.error or 'Results outbox is unavailable')
        with self.lock:
            if event_id not in self.records:
                raise ValueError('Unknown result event')
            state = self.records[event_id]['delivery']['state']
            if action == 'retry' and state not in ('failed', 'saved'):
                raise ValueError('Only failed or saved results can be retried; use republish for sent results')
            if action in ('retry', 'republish') and (not self.webhook or not self.enabled):
                raise ValueError('Enable Discord and configure its webhook first')
        try:
            self.commands.put_nowait((action, event_id, args))
        except Full:
            raise ValueError('Results command queue is full; try again shortly') from None
        self.wake.set()

    def _replace(self, record):
        with self.write_lock:
            self._merge_interval(record)
            self._write(record)
            with self.lock:
                self._merge_interval(record)
                self.records[record['event_id']] = deepcopy(record)
        self._announce()

    def _run(self):
        try:
            while not self.stopped.is_set():
                try:
                    if self.available:
                        self._tick()
                except Exception as exc:
                    with self.lock:
                        self.error = redact_error(exc, self.webhook)
                    LOG.error('Results outbox: %s', self.error)
                    self._announce()
                    self.stopped.wait(1)
                self.wake.wait(.1)
                self.wake.clear()
        finally:
            with self.write_lock:
                self.available = False
                if self._lease is not None:
                    self._lease.close()
                    self._lease = None

    def _tick(self):
        if self._dirty is not None:
            self._replace(self._dirty)
            self._dirty = None
            self.error = None
        try:
            action, event_id, args = self.commands.get_nowait()
        except Empty:
            pass
        else:
            with self.lock:
                record = deepcopy(self.records[event_id])
            if action == 'interval':
                record['interval'][1] = max(record['interval'][1], args['end'])
                self.observe_interval(event_id, record['source_id'], record['score_mode'], *record['interval'])
            elif action in ('retry', 'republish'):
                # Commands queued during an in-flight send must not overwrite its result.
                if action == 'retry' and record['delivery']['state'] not in ('failed', 'saved'):
                    return
                record['delivery'].update(state='queued', attempts=0, next_attempt=0, error=None)
            else:
                raise ValueError('Unknown outbox command')
            self._replace(record)
        with self.lock:
            if not self.enabled or not self.webhook:
                return
            webhook = self.webhook
            record = next((deepcopy(r) for r in self.records.values()
                           if r['delivery']['state'] in ('queued', 'retrying')
                           and r['delivery']['next_attempt'] <= time.time()), None)
        if record is None:
            return
        delivery = record['delivery']
        if delivery['attempts'] >= 5:
            delivery.update(state='failed', error='Retry budget exhausted; manual retry available')
            self._replace(record)
            return
        delivery.update(state='sending', attempts=delivery['attempts'] + 1)
        self._replace(record)  # persist intent before the request
        try:
            result = self.sender(webhook, record, record['screenshot_path'])
            delivery.update(result, state='sent', error=None, next_attempt=0)
        except DeliveryError as exc:
            delivery.update(exc.receipt)
            retry = exc.retryable and delivery['attempts'] < 5
            delay = exc.retry_after if exc.retry_after is not None else min(60, 2 ** (delivery['attempts'] - 1))
            delivery.update(state='retrying' if retry else 'failed', error=redact_error(exc, webhook),
                            next_attempt=time.time() + delay if retry else 0)
        except Exception as exc:
            delivery.update(state='failed', error=redact_error(exc, webhook))
        try:
            self._replace(record)
        except OSError:
            # Keep the acknowledged result in memory and retry its metadata write
            # before any further sends. Never resend merely because disk is full.
            with self.lock:
                self._merge_interval(record)
                self.records[record['event_id']] = deepcopy(record)
            self._dirty = deepcopy(record)
            raise
        LOG.info('Results %s: %s (attempt %s)%s', record['event_id'], delivery['state'], delivery['attempts'],
                 ': ' + delivery['error'] if delivery['error'] else '')

    def close(self, timeout=2):
        self.stopped.set()
        self.wake.set()
        self.worker.join(timeout)
