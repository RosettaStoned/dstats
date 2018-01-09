import sys
import json
import logging
import asyncio
import aiodocker
import aiofiles
from aiohttp import web

logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s: %(message)s',
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


class StatsCollector():

    def __init__(self, host, port):

        self._host = host
        self._port = port
        self._sleep_delay = 5
        self._web_sockets = set()
        self._web_sockets_lock = asyncio.Lock()

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

    def _graceful_chain_get(self, d, *args, default=None):
        t = d
        for a in args:
            try:
                t = t[a]
            except (KeyError, ValueError, TypeError) as ex:
                return default
        return t

    def _calculate_cpu_percent(self, stats):
        cpu_count = len(stats["cpu_stats"]["cpu_usage"]["percpu_usage"])
        cpu_percent = 0.0
        cpu_delta = float(stats["cpu_stats"]["cpu_usage"]["total_usage"]) - \
            float(stats["precpu_stats"]["cpu_usage"]["total_usage"])
        system_delta = float(stats["cpu_stats"]["system_cpu_usage"]) - \
            float(stats["precpu_stats"]["system_cpu_usage"])
        if system_delta > 0.0:
            cpu_percent = cpu_delta / system_delta * 100.0 * cpu_count
        return cpu_percent

    def _calculate_memory_percent(self, stats):
        memory_percent = (float(stats['memory_stats']['usage']) /
                          float(stats['memory_stats']['limit'])) * 100
        return memory_percent, stats['memory_stats']['usage']

    def _calculate_blkio_bytes(self, stats):
        bytes_stats = self._graceful_chain_get(
            stats,
            "blkio_stats",
            "io_service_bytes_recursive"
        )
        if not bytes_stats:
            return 0, 0
        r = 0
        w = 0
        for s in bytes_stats:
            if s["op"] == "Read":
                r += s["value"]
            elif s["op"] == "Write":
                w += s["value"]
        return r, w

    def _calculate_network_bytes(self, stats):
        networks = self._graceful_chain_get(stats, "networks")
        if not networks:
            return 0, 0
        r = 0
        t = 0
        for if_name, data in networks.items():
            r += data["rx_bytes"]
            t += data["tx_bytes"]
        return r, t

    async def _get_stats(self, container):

        log.info('start')

        container_data = await container.show()
        stats = await container.stats(stream=False)

        cpu_usage_perc = self._calculate_cpu_percent(stats)
        memory_percent, memory_usage = self._calculate_memory_percent(stats)
        read_bytes, wrote_bytes = self._calculate_blkio_bytes(stats)
        received_bytes, transceived_bytes = \
            self._calculate_network_bytes(stats)

        stats['container'] = container_data
        stats['cpu_stats']['cpu_usage_perc'] = cpu_usage_perc
        stats['memory_stats']['perc'] = memory_percent
        stats['blkio_stats']['read_bytes'] = read_bytes
        stats['blkio_stats']['wrote_bytes'] = wrote_bytes
        stats['network_stats'] = {
            'received_bytes': received_bytes,
            'transceived_bytes': transceived_bytes
        }

        log.info('end')

        return stats

    async def _add_web_socket(self, ws):
        with await self._web_sockets_lock:
            self._web_sockets.add(ws)

    async def _discard_web_socket(self, ws):
        with await self._web_sockets_lock:
            self._web_sockets.discard(ws)

    async def _send_stats(self, stats, ws):
        log.info('Send stats...')

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
        log.info('cleanup background tasks...')
        self.collect_task.cancel()
        await self.collect_task

    async def on_shutdown(self, app):
        log.info('Shutdown...')
        with self._web_sockets_lock:
            for ws in self._web_sockets:
                await ws.close(code=999, message='Server shutdown')

    async def websocket_handler(self, request):

        log.info('WebSocket is ready.')
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        log.info('WebSocket is connected')
        await self._add_web_socket(ws)

        while True:

            msg = await ws.receive()
            if msg.tp == web.MsgType.text:
                log.info("Got message %s" % msg.data)
                ws.send_str("Pressed key code: {}".format(msg.data))
            elif msg.tp == web.MsgType.close or \
                    msg.tp == web.MsgType.error:
                break

        await self._discard_web_socket(ws)
        log.info('WebSocket is closed.')

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
