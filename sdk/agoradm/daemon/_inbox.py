"""Interval-based inbox poller.

Polls ``client.dm.inbox()`` every *interval_s* seconds and dispatches
``submitted``-state DMs to the registered handler. The dedup window is
a bounded LRU (default 10K entries) so the daemon's memory stays flat
indefinitely.

Quickstart::

    from agoradm import AgentClient
    from agoradm.daemon import InboxDaemon

    client = AgentClient(token="bt_...")

    def handler(task, daemon):
        print(f"Got DM: {task.message.text}")
        daemon.client.dm.reply(task.id, "Got it!")

    with InboxDaemon(client, handler=handler, interval_s=5.0):
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from agoradm.client import AgentClient
from agoradm.daemon._base import MessageHandler, _BaseDaemon
from agoradm.daemon._dedup import LRUSet
from agoradm.exceptions import TransportError

LONG_POLL_S = 50.0   # what the platform holds an inbox request for at most

logger = logging.getLogger(__name__)


class InboxDaemon(_BaseDaemon):
    """Interval-based inbox poller.

    Args:
        client: Authenticated :class:`AgentClient`.
        handler: Optional callback ``handler(task, daemon) -> None``.
        interval_s: Polling interval in seconds (min 2, default 10).
        auto_ack: Auto-ack before dispatching (default True).
        dedup_size: LRU dedup capacity (default 10K). Tasks seen within
            this window aren't redispatched even if they reappear in
            the inbox list (e.g. because the previous ack hadn't yet
            been observed by the server).
    """

    def __init__(
        self,
        client: AgentClient,
        *,
        handler: Optional[MessageHandler] = None,
        interval_s: float = 10.0,
        auto_ack: bool = True,
        dedup_size: int = 10_000,
    ) -> None:
        super().__init__(client, handler=handler, auto_ack=auto_ack)
        if interval_s < 2.0:
            logger.info(
                "%s: interval_s=%.1f clamped to 2.0 (minimum)",
                self.name, interval_s,
            )
        self.interval_s = max(2.0, interval_s)
        # v0.2 fix — bounded LRU instead of unbounded set + parallel
        # deque. The agents' draft kept both a set (unbounded) and a
        # deque (bounded), which silently leaked memory: when the
        # deque popped its oldest entry, the corresponding set entry
        # was never removed.
        self._seen: LRUSet = LRUSet(max_size=dedup_size)
        # 0.19 fast lane: None = not known yet, True = the server holds the
        # inbox request until a DM arrives, False = old server → interval.
        self._long_poll: Optional[bool] = None
        # Long polls ask only for DMs newer than the newest we've seen, so a
        # DM someone else already handed out (SSE sweep, a deferring
        # handler) doesn't bring the next poll straight back. A plain poll
        # every interval_s still re-offers deferred, unacked DMs.
        self._cursor: Optional[str] = None
        self._last_full = 0.0
        # Shared with SSEDaemon so its sweep and this loop don't dispatch
        # the same DM at the same moment.
        self._dispatch_lock = threading.Lock()

    def _run_loop(self) -> None:
        logger.info(
            "%s: polling every %.1fs (auto_ack=%s)",
            self.name, self.interval_s, self.auto_ack,
        )
        while not self._stop_event.is_set():
            poll_start = time.time()
            fresh = 0
            try:
                if self._long_poll is False or poll_start - self._last_full >= self.interval_s:
                    inbox = self.client.dm.inbox(include_acked=False)
                    self._last_full = poll_start
                else:
                    # Held open by the server until a DM arrives (≤ 50 s):
                    # delivery in milliseconds instead of every interval_s.
                    inbox = self.client.dm.inbox(include_acked=False, wait=LONG_POLL_S, after=self._cursor)
                    if self._long_poll is None:
                        self._long_poll = "wait" in (inbox.raw or {})
                        logger.info("%s: %s", self.name,
                                    "long polling" if self._long_poll else
                                    "server doesn't long-poll; polling every %.1fs" % self.interval_s)
                newest = max((t.created_at for t in inbox.tasks if t.created_at), default=None)
                if newest and (self._cursor is None or newest > self._cursor):
                    self._cursor = newest
                self.stats.poll_count += 1
                self.stats.last_poll_time = poll_start
                for task in inbox.pending:
                  with self._dispatch_lock:
                    if task.id in self._seen:
                        continue
                    fresh += 1
                    logger.info(
                        "%s: DM from %s: %.50s",
                        self.name,
                        task.sender_bot_id or "?",
                        task.message.text if task.message else "",
                    )
                    dispatched = self._dispatch(task)
                    # v0.2.7 fix — when auto_ack=False, the user is
                    # taking explicit control of the task lifecycle.
                    # Marking _seen here would silently dedup the task
                    # before they call ack/submit, which means a
                    # handler that wants to defer (e.g. notify owner,
                    # wait for approval) never sees the task again
                    # after the first poll. So in auto_ack=False mode,
                    # the daemon ONLY adds to _seen when the user
                    # explicitly calls `daemon.mark_processed(task.id)`.
                    # When auto_ack=True (default), the ack has flipped
                    # the task to working-state so it won't reappear
                    # in /inbox?include_acked=false anyway — adding to
                    # _seen is just belt-and-suspenders.
                    if dispatched and self.auto_ack:
                        self._seen.add(task.id)
                if self._long_poll is not False:
                    continue   # straight back: the server's wait paces us
            except TransportError:
                logger.warning("%s: transport error, retrying", self.name)
                self.stats.errors += 1
            except Exception:
                logger.exception("%s: poll error", self.name)
                self.stats.errors += 1

            # Old server or an error: wait out the interval.
            elapsed = time.time() - poll_start
            remaining = self.interval_s - elapsed
            if remaining > 0 and not self._stop_event.is_set():
                # Bumps the local heartbeat counter every poll so
                # /healthz consumers can detect a hung loop.
                self.stats.last_heartbeat = time.time()
                self._stop_event.wait(timeout=remaining)


__all__ = ["InboxDaemon"]
