import json
import asyncio
import aiodocker
import aiofiles
from aiohttp import web


class StatsCollector():

    def __init__(self, host, port):

        self._host = host
        self._port = port
        self._sleep_delay = 5
        self._web_sockets = set()

        self.loop = asyncio.get_event_loop()

        self.docker = aiodocker.Docker()

        self.app = web.Application(loop=self.loop)
        self.app.router.add_get('/', self.index_handler)
        self.app.router.add_get('/docker-stats', self.websocket_handler)
        self.app.on_startup.append(self.start_background_tasks)
        self.app.on_cleanup.append(self.cleanup_background_tasks)
        self.app.on_shutdown.append(self.on_shutdown)

    def start(self):
        web.run_app(self.app, host=self._host, port=self._port)

    def _calculate_cpu_percent(self, stats):
        cpu1 = stats['precpu_stats']['cpu_usage']['total_usage']
        system1 = stats['precpu_stats']['system_cpu_usage']
        cpu2 = stats['cpu_stats']['cpu_usage']['total_usage']
        system2 = stats['cpu_stats']['system_cpu_usage']
        # Calculate deltas
        cpu_delta = float(cpu2 - cpu1)
        system_delta = float(system2 - system1)
        # Calculate percent
        if (system_delta > 0.0 and cpu_delta > 0.0):
            cpu_percent = (cpu_delta / system_delta) * \
                len(stats['cpu_stats']['cpu_usage']['percpu_usage']) * 100.0
        else:
            cpu_percent = 0.0

        return cpu_percent

    def _calculate_memory_percent(self, stats):
        memory_percent = (float(stats['memory_stats']['usage']) /
                          float(stats['memory_stats']['limit'])) * 100
        return memory_percent, stats['memory_stats']['usage']

    async def _get_stats(self, container):

        print('start')

        stats = await container.stats(stream=False)

        cpu_usage_perc = self._calculate_cpu_percent(stats)
        memory_percent, memory_usage = self._calculate_memory_percent(stats)

        stats['cpu_stats']['cpu_usage_perc'] = cpu_usage_perc
        stats['memory_stats']['perc'] = memory_percent

        print('end')

        return stats

    async def _send_stats(self, stats, ws):

        stats_json = json.dumps(stats)

        return await ws.send_str(stats_json)

    async def collect(self):

        while True:

            try:
                containers = await self.docker.containers.list()
                if not containers:
                    await asyncio.sleep(self._sleep_delay)
                    continue

                tasks = [self._get_stats(c) for c in containers]

                done, not_done = await asyncio.wait(tasks)

                tasks = []
                for t in done:

                    stats = t.result()

                    for ws in self._web_sockets:
                        tasks.append(self._send_stats(stats, ws))

                if not tasks:
                    await asyncio.sleep(self._sleep_delay)
                    continue

                done, not_done = await asyncio.wait(tasks)
                await asyncio.sleep(self._sleep_delay)

            except asyncio.CancelledError:
                pass

    async def start_background_tasks(self, app):
        self.collect_task = asyncio.ensure_future(self.collect())

    async def cleanup_background_tasks(self, app):
        print('cleanup background tasks...')
        self.collect_task.cancel()
        await self.collect_task

    async def on_shutdown(self, app):
        for ws in self._web_sockets:
            await ws.close(code=999, message='Server shutdown')

    async def websocket_handler(self, request):

        print('WebSocket is ready.')
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        print('WebSocket is connected')
        self._web_sockets.add(ws)

        while True:

            msg = await ws.receive()
            if msg.tp == web.MsgType.text:
                print("Got message %s" % msg.data)
                ws.send_str("Pressed key code: {}".format(msg.data))
            elif msg.tp == web.MsgType.close or \
                    msg.tp == web.MsgType.error:
                break

        self._web_sockets.discard(ws)
        print('WebSocket is closed.')

        return ws

    async def index_handler(self, request):

        resp = web.StreamResponse(status=200,
                                  reason='OK',
                                  headers={'Content-Type': 'text/html'})

        await resp.prepare(request)

        async with aiofiles.open('templates/index.html', mode='r') as f:
            async for line in f:
                resp.write(line.encode())
                await resp.drain()

        return resp
