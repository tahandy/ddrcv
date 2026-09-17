"""Durable outbox. Only this worker makes network requests; no capture locks."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import logging
import math
from pathlib import Path
from queue import Queue, Empty, Full
import re
import shutil
import threading
import time
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit, unquote, parse_qs

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


def screenshot_filename(record):
    """Readable UTC timestamp, optional confirmed names, and stable collision-free ID."""
    stamp = datetime.fromtimestamp(record['created_at'], timezone.utc).strftime('%Y-%m-%d_%H-%M-%S_%f_UTC')
    parts = [stamp]
    if record.get('include_player_names', True) and record.get('parse_names', True):
        for index, player in enumerate(record['players'], 1):
            if not player['present'] or not player['name']:
                continue
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', player['name'])
            name = ''.join(c for c in name if c.isprintable())
            name = re.sub(r'\s+', '_', name).strip(' ._')[:32].rstrip(' ._')
            if name:
                parts.append(f'P{index}-{name}')
    parts.append(record['event_id'])
    return '_'.join(parts) + '.png'


def format_payload(record):
    label = 'EX' if record['score_mode'] == 'ex' else 'Money'
    lines = []
    for i, p in enumerate(record['players']):
        if not p['present']:
            lines.append(f'P{i+1}: absent')
            continue
        name = escaped(p['name']) if p['name'] else (f'P{i+1}' if not record.get('parse_names', True)
                                                    else f'P{i+1} (name unread)')
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
    for attachment in body.get('attachments') or []:
        if isinstance(attachment, dict) and attachment.get('filename') == 'results.png' and attachment.get('url'):
            receipt['image_url'] = attachment['url']
    embedded = False
    for embed in (body.get('embeds') or []):
        image = embed.get('image', {}) if isinstance(embed, dict) else {}
        if not isinstance(image, dict):
            continue
        for key in ('url', 'proxy_url'):
            try:
                url = urlsplit(image.get(key, ''))
                parts = unquote(url.path).strip('/').split('/')
                matched = (url.scheme == 'https' and url.hostname in ('cdn.discordapp.com', 'media.discordapp.net')
                             and len(parts) == 4 and parts[:2] == ['attachments', str(body['channel_id'])]
                             and parts[2].isdigit() and parts[3] == 'results.png')
                embedded |= matched
                if matched:
                    receipt['image_url'] = image[key]
            except (ValueError, TypeError, AttributeError):
                pass
    if not attached and not embedded:
        raise DeliveryError('Discord created the message but did not confirm its screenshot; inspect before retrying',
                            receipt=receipt)
    return receipt


def webhook_identity(webhook):
    # Bind edits to the original destination/token without persisting another secret.
    return hashlib.sha256((webhook or '').encode()).hexdigest()


def response_body(response):
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
        return response.json()
    except ValueError:
        raise DeliveryError('Discord returned an unreadable acknowledgement', retryable=True) from None


def edit_record(webhook, record):
    delivery = record['delivery']
    if delivery.get('webhook_identity') != webhook_identity(webhook):
        raise DeliveryError('Name update requires the original Discord webhook')
    message_id = str(delivery.get('message_id', ''))
    if not message_id.isdigit():
        raise DeliveryError('No confirmed Discord message to update')
    url = urlsplit(webhook)
    endpoint = urlunsplit((url.scheme, url.netloc, url.path.rstrip('/') + '/messages/' + message_id, '', ''))
    params = {k: v[-1] for k, v in parse_qs(url.query).items() if k == 'thread_id'}
    payload = format_payload(record)
    # Omit files/attachments entirely: edit only the embed and keep the existing image.
    image_url = delivery.get('image_url') or 'attachment://results.png'
    image = urlsplit(image_url)
    if image.hostname in ('cdn.discordapp.com', 'media.discordapp.net'):
        # Discord refreshes its CDN signature; a persisted signature may have expired.
        image_url = urlunsplit((image.scheme, image.netloc, image.path, '', ''))
    payload['embeds'][0]['image']['url'] = image_url
    try:
        with requests.patch(endpoint, params=params, json=payload, timeout=(3, 10)) as response:
            receipt = message_receipt(response_body(response))
            if str(receipt['message_id']) != message_id:
                raise DeliveryError('Discord acknowledged a different message')
            return receipt
    except requests.RequestException as error:
        raise DeliveryError(redact_error(error, webhook), retryable=True) from None


def send_record(webhook, record, image_path):
    try:
        with open(image_path, 'rb') as stream:
            response = requests.post(webhook, params={'wait': 'true'},
                data={'payload_json': json.dumps(format_payload(record))},
                files={'files[0]': ('results.png', stream, 'image/png')}, timeout=(3, 10))
    except requests.RequestException as error:
        raise DeliveryError(redact_error(error, webhook), retryable=True) from None
    with response:
        body = response_body(response)
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
    def __init__(self, directory, webhook=None, enabled=False, sender=send_record, notify=None, editor=edit_record):
        self.directory = Path(directory).resolve()
        self.webhook, self.enabled, self.sender, self.notify = webhook, enabled, sender, notify
        self.editor = editor
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
                    self._defaults(record)
                    if record['name_update']['state'] == 'sending':
                        record['name_update'].update(state='retrying', next_attempt=0)
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
        record = deepcopy(record)
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
            self._defaults(record)
            self._merge_interval(record)
            self._write(record)
            with self.lock:
                self._merge_interval(record)
                self.records[record['event_id']] = deepcopy(record)
                self.observe_interval(record['event_id'], record['source_id'], record['score_mode'], *record['interval'])
        self._announce()
        self.wake.set()
        # The readable export is optional; the durable outbox already owns delivery.
        export = {}
        try:
            if record.get('output_directory'):
                output = Path(record['output_directory']).expanduser().resolve()
                output.mkdir(parents=True, exist_ok=True)
                target = output / screenshot_filename(record)
                temporary_export = output / f'.{uuid4().hex}.tmp'
                try:
                    shutil.copyfile(record['screenshot_path'], temporary_export)
                    temporary_export.replace(target)
                finally:
                    temporary_export.unlink(missing_ok=True)
                export['screenshot_export_path'] = str(target)
        except OSError as exc:
            export['export_error'] = redact_error(exc, self.webhook)
        if export:
            try:
                self._metadata(record['event_id'], export)
            except OSError as exc:
                self.error = 'Screenshot export metadata: ' + redact_error(exc, self.webhook)
        LOG.info('Results %s: %s', record['event_id'], record['delivery']['state'])
        self._announce()
        self.wake.set()

    def snapshot(self):
        with self.lock:
            records = sorted(self.records.values(), key=lambda r: r.get('created_at', 0))
            failed = lambda r: r['delivery']['state'] == 'failed' or r['name_update']['state'] == 'failed'
            recent = {r['event_id'] for r in records[-20:]}
            return dict(error=self.error, available=self.available and not self.stopped.is_set(),
                        needs_attention=sum(failed(r) for r in records),
                        last_sent_at=max((r['delivery'].get('sent_at', 0) for r in records), default=0) or None,
                        records=deepcopy([r for r in records if r['event_id'] in recent or failed(r)]))

    @staticmethod
    def _defaults(record):
        record.setdefault('revision', 1)
        record['delivery'].setdefault('delivered_revision', record['revision'] if record['delivery']['state'] == 'sent' else 0)
        record.setdefault('name_update', dict(state='idle', attempts=0, error=None, next_attempt=0))
        record.setdefault('alternatives', [])

    def _metadata(self, event_id, fields):
        with self.write_lock:
            with self.lock:
                record = deepcopy(self.records[event_id])
            record.update(fields)
            self._replace(record, metadata=True)

    def save_alternatives(self, event_id, samples):
        import cv2
        alternatives = []
        try:
            for index, sample in enumerate(samples[:2], 1):
                name = f'alternative-{index}.png'
                path = self.directory / event_id / name
                if not cv2.imwrite(str(path), sample.frame):
                    raise OSError('Could not save alternative screenshot')
                alternatives.append(dict(id=f'alternative-{index}', timestamp=sample.timestamp,
                                         frame_index=sample.index))
            if alternatives:
                self._metadata(event_id, dict(alternatives=alternatives))
        except OSError as exc:
            self.error = 'Alternative screenshots: ' + redact_error(exc, self.webhook)

    def enrich_names(self, event_id, names):
        with self.write_lock:
            with self.lock:
                record = deepcopy(self.records[event_id])
            changed = False
            for player, name in zip(record['players'], names):
                if player['present'] and player['name'] is None and name is not None:
                    player['name'] = name
                    changed = True
            if not changed:
                return
            record['revision'] += 1
            record['partial'] = any(p['present'] and (p['name'] is None or p['score'] is None) for p in record['players'])
            record['name_update'] = dict(state='queued', attempts=0, error=None, next_attempt=0)
            self._replace(record)
        self.wake.set()

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
            if action == 'retry_names' and (state != 'sent' or self.records[event_id]['name_update']['state'] != 'failed'):
                raise ValueError('Only failed name updates can be retried')
            if action in ('retry', 'republish', 'retry_names') and (not self.webhook or not self.enabled):
                raise ValueError('Enable Discord and configure its webhook first')
        try:
            self.commands.put_nowait((action, event_id, args))
        except Full:
            raise ValueError('Results command queue is full; try again shortly') from None
        self.wake.set()

    def _replace(self, record, metadata=False):
        with self.write_lock:
            with self.lock:
                current = self.records.get(record['event_id'])
                if current:
                    if current.get('revision', 1) > record.get('revision', 1):
                        for key in ('players', 'partial', 'revision'):
                            record[key] = deepcopy(current[key])
                    for key in ('alternatives', 'export_error', 'screenshot_export_path'):
                        if key in current and not metadata:
                            record[key] = deepcopy(current[key])
            if record['delivery']['state'] == 'sent':
                update = record['name_update']
                if record['delivery']['delivered_revision'] >= record['revision']:
                    update.update(state='idle', error=None, next_attempt=0)
                elif update['state'] == 'idle':
                    update.update(state='queued', attempts=0, next_attempt=0)
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
                if action == 'republish':
                    record['delivery'].update(message_id=None, message_url=None, delivered_revision=0)
            elif action == 'retry_names':
                record['name_update'].update(state='queued', attempts=0, next_attempt=0, error=None)
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
            self._edit_next()
            return
        delivery = record['delivery']
        if delivery['attempts'] >= 5:
            delivery.update(state='failed', error='Retry budget exhausted; manual retry available')
            self._replace(record)
            return
        delivery.update(state='sending', attempts=delivery['attempts'] + 1, webhook_identity=webhook_identity(webhook))
        self._replace(record)  # persist intent before the request
        revision = record['revision']
        try:
            result = self.sender(webhook, record, record['screenshot_path'])
            delivery.update(result, state='sent', error=None, next_attempt=0, delivered_revision=revision, sent_at=time.time())
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

    def _edit_next(self):
        with self.lock:
            if not self.enabled or not self.webhook:
                return
            webhook = self.webhook
            record = next((deepcopy(r) for r in self.records.values()
                           if r['delivery']['state'] == 'sent'
                           and r['name_update']['state'] in ('queued', 'retrying')
                           and r['name_update']['next_attempt'] <= time.time()), None)
        if record is None:
            return
        update = record['name_update']
        if update['attempts'] >= 5:
            update.update(state='failed', error='Name update retry budget exhausted')
            self._replace(record)
            return
        update.update(state='sending', attempts=update['attempts'] + 1)
        self._replace(record)
        revision = record['revision']
        try:
            if record['delivery'].get('webhook_identity') != webhook_identity(webhook):
                raise DeliveryError('Name update requires the original Discord webhook')
            self.editor(webhook, record)
            record['delivery']['delivered_revision'] = revision
            update.update(state='idle', error=None, next_attempt=0)
        except DeliveryError as exc:
            retry = exc.retryable and update['attempts'] < 5
            delay = exc.retry_after if exc.retry_after is not None else min(60, 2 ** (update['attempts'] - 1))
            update.update(state='retrying' if retry else 'failed', error=redact_error(exc, webhook),
                          next_attempt=time.time() + delay if retry else 0)
        except Exception as exc:
            update.update(state='failed', error=redact_error(exc, webhook))
        try:
            self._replace(record)
        except OSError:
            with self.lock:
                self.records[record['event_id']] = deepcopy(record)
            self._dirty = deepcopy(record)
            raise

    def close(self, timeout=2):
        self.stopped.set()
        self.wake.set()
        self.worker.join(timeout)
