# -*- coding:utf-8 -*-

"""
Server heartbeat.

Author: HuangTao
Date:   2018/04/26
Email:  huangtao@ifclover.com
"""

import asyncio

from aioquant.utils import tools
from aioquant.utils import logger
from aioquant.configure import config

__all__ = ("heartbeat", )


class HeartBeat(object):
    """Server heartbeat.
    """

    def __init__(self):
        self._count = 0  # Heartbeat count.
        self._interval = 1  # Heartbeat interval(second).
        self._print_interval = config.heartbeat.get("interval", 0)  # Printf heartbeat information interval(second).
        self._broadcast_interval = config.heartbeat.get("broadcast", 0) # 心跳广播间隔(秒)，0为不广播
        self._tasks = {}  # Loop run tasks with heartbeat service. `{task_id: {...}}`

    @property
    def count(self):
        return self._count

    def ticker(self):
        """Loop run ticker per self._interval.
        """
        self._count += 1

        if self._print_interval > 0:
            if self._count % self._print_interval == 0:
                logger.info("do server heartbeat, count:", self._count, caller=self)

        # Later call next ticker.
        asyncio.get_event_loop().call_later(self._interval, self.ticker)

        # Exec tasks.
        for task_id, task in self._tasks.items():
            interval = task["interval"]
            if self._count % interval != 0:
                continue
            func = task["func"]
            args = task["args"]
            kwargs = task["kwargs"]
            kwargs["task_id"] = task_id
            kwargs["heart_beat_count"] = self._count
            asyncio.get_event_loop().create_task(func(*args, **kwargs))
        # 广播服务进程心跳
        if self._broadcast_interval > 0:
            if self._count % self._broadcast_interval == 0:
                self.alive()

    def register(self, func, interval=1, *args, **kwargs):
        """Register an asynchronous callback function.

        Args:
            func: Asynchronous callback function.
            interval: Loop callback interval(second), default is `1s`.

        Returns:
            task_id: Task id.
        """
        t = {
            "func": func,
            "interval": interval,
            "args": args,
            "kwargs": kwargs
        }
        task_id = tools.get_uuid1()
        self._tasks[task_id] = t
        return task_id

    def unregister(self, task_id):
        """Unregister a task.

        Args:
            task_id: Task id.
        """
        if task_id in self._tasks:
            self._tasks.pop(task_id)

    def alive(self):
        """ 服务进程广播心跳
        """
        from aioquant.event import EventHeartbeat
        EventHeartbeat(config.server_id, self.count).publish()

heartbeat = HeartBeat()
