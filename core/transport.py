"""Transport wrapper to centralize publishes and optional encryption.

Usage: instantiate with `Transport(parent)` where parent provides `client`,
`topic`, and `encrypt_message(message)` method. Plugins should call
`parent.transport.send_command(cmd_dict, encrypt=True)` instead of using
`parent.client.publish` directly.
"""
from typing import Dict
import ujson as json
import logging
import threading
import queue
import time

logger = logging.getLogger(__name__)


class Transport:
    """Transport that centralizes publishes and queues when disconnected.

    The transport relies on the `parent` exposing `client`, `topic`,
    `encrypt_message(payload)` and `is_connected` attributes.
    """

    def __init__(self, parent):
        self.parent = parent
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        # Start a background flusher thread to retry queued messages
        self._flusher = threading.Thread(target=self._flusher_loop, daemon=True)
        self._flusher.start()

    def _flusher_loop(self):
        while not self._stop_event.is_set():
            try:
                # Attempt to flush one queued item if connected
                if getattr(self.parent, 'is_connected', False):
                    try:
                        cmd = self._queue.get_nowait()
                    except queue.Empty:
                        time.sleep(0.2)
                        continue
                    try:
                        self._publish_raw(cmd)
                    except Exception as e:
                        logger.error(f"Transport flusher failed to publish queued command: {e}")
                        # put it back for later
                        self._queue.put(cmd)
                        time.sleep(1.0)
                else:
                    time.sleep(0.5)
            except Exception:
                time.sleep(0.5)

    def stop(self):
        self._stop_event.set()
        try:
            self._flusher.join(timeout=1.0)
        except Exception:
            pass

    def _publish_raw(self, command: Dict, qos: int = 1, retain: bool = False):
        payload = json.dumps(command)
        if hasattr(self.parent, 'encrypt_message'):
            payload = self.parent.encrypt_message(payload)
        client = getattr(self.parent, 'client', None)
        topic = getattr(self.parent, 'topic', None)
        if client is None or topic is None:
            raise RuntimeError('Transport: missing client or topic on parent')
        client.publish(topic, payload, qos=qos, retain=retain)

    def send_command(self, command: Dict, encrypt: bool = True, qos: int = 1, retain: bool = False):
        """Attempt to send a command now; if disconnected, queue for later.

        Return True if published or queued successfully, False otherwise.
        """
        try:
            if getattr(self.parent, 'is_connected', False):
                try:
                    self._publish_raw(command, qos=qos, retain=retain)
                    logger.debug(f"Transport published to {self.parent.topic}: {command}")
                    return True
                except Exception as e:
                    logger.error(f"Transport publish failed, enqueueing command: {e}")
                    try:
                        self._queue.put_nowait(command)
                        return True
                    except Exception as ex:
                        logger.error(f"Transport failed to enqueue command: {ex}")
                        return False
            else:
                # Not connected: queue the command for later
                try:
                    self._queue.put_nowait(command)
                    logger.debug(f"Transport queued command (disconnected): {command}")
                    return True
                except Exception as e:
                    logger.error(f"Transport failed to queue command: {e}")
                    return False
        except Exception as e:
            logger.error(f"Transport encountered error in send_command: {e}")
            return False

    def flush_queued(self):
        """Attempt to flush all queued messages immediately.

        This is useful to call after reconnecting.
        """
        if not getattr(self.parent, 'is_connected', False):
            return 0
        flushed = 0
        while True:
            try:
                cmd = self._queue.get_nowait()
                try:
                    self._publish_raw(cmd)
                    flushed += 1
                except Exception as e:
                    logger.error(f"Transport flush failed to publish cmd: {e}")
                    # put back and break
                    self._queue.put(cmd)
                    break
            except queue.Empty:
                break
        return flushed

