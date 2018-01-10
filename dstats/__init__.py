import sys
import json
import logging
import asyncio
import aiodocker
from aiohttp import web, WSMsgType
from aiohttp.http import WSCloseCode


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
        self._web_socket_timeout = 0.1
        self._web_sockets = set()
        self._web_sockets_lock = asyncio.Lock()

        self.loop = asyncio.get_event_loop()

        self.docker = aiodocker.Docker()

        self.app = web.Application(loop=self.loop)
        self.app.router.add_get('/', self.index_handler)

        self.app.router.add_get('/containers/{container_id}',
                                self.container_handler)
        self.app.router.add_get('/containers/{container_id}/ws',
                                self.container_ws_handler)

        self.app.router.add_get('/docker-stats/ws', self.ws_handler)
        self.app.router.add_static('/static/', path='static/')

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

        log.info('Start collecting stats for container \
                 "{container_id}".'.format(
                     container_id=container._id
                 ))

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

    async def collect(self, container_id=None, ws=None):

        while True:

            try:

                if container_id:
                    containers = [await
                                  self.docker.containers.get(container_id)]
                else:
                    containers = await self.docker.containers.list()

                if not containers:
                    await asyncio.sleep(self._sleep_delay)
                    continue

                tasks = [self._get_stats(c) for c in containers]

                done, not_done = await asyncio.wait(tasks)

                tasks = []
                for t in done:

                    stats = t.result()

                    if ws:
                        log.info('Send to single web socket...')
                        tasks.append(self._send_stats(stats, ws))
                    else:
                        log.info('Send to multiple web sockets...')
                        with await self._web_sockets_lock:
                            log.info('Lock for sending multiple web sockets \
                                     aquired.')
                            print(self._web_sockets)
                            for ws in self._web_sockets:
                                tasks.append(self._send_stats(stats, ws))

                if not tasks:
                    await asyncio.sleep(self._sleep_delay)
                    continue

                done, not_done = await asyncio.wait(tasks)
                log.info('Stats are sended.')
                await asyncio.sleep(self._sleep_delay)

            except asyncio.CancelledError as e:
                log.error(e)
                break

    async def start_background_tasks(self, app):
        self.collect_task = asyncio.ensure_future(self.collect())

    async def cleanup_background_tasks(self, app):

        self.collect_task.cancel()
        await self.collect_task

        log.info('cleanup background tasks...')
        tasks = [task for task in asyncio.Task.all_tasks() if task is not
                 asyncio.tasks.Task.current_task()]
        list(map(lambda task: task.cancel(), tasks))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        log.info('finished awaiting cancelled tasks, results: {0}'.format(
            results
        ))

    async def on_shutdown(self, app):

        with await self._web_sockets_lock:

            tasks = [ws.close(code=WSCloseCode.GOING_AWAY, message='Server \
                              shutdown') for ws in self._web_sockets]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            log.info('finished awaiting close of web sockets, \
                     results: {0}'.format(results))

    async def ws_handler(self, request):

        log.info('WebSocket is ready.')
        ws = web.WebSocketResponse(timeout=self._web_socket_timeout)
        await ws.prepare(request)
        log.info('WebSocket is connected')
        log.info('WebSocket is added to web sockets.')
        await self._add_web_socket(ws)

        while True:

            log.info('Waiting...')
            msg = await ws.receive()
            log.info(msg.type)
            if msg.type == WSMsgType.CLOSING or \
                    msg.type == WSMsgType.CLOSED or \
                    msg.tp == WSMsgType.ERROR:
                break

        await self._discard_web_socket(ws)
        log.info('WebSocket is closed.')

        return ws

    async def index_handler(self, request):

        return web.FileResponse('templates/index.html')

    async def container_ws_handler(self, request):

        container_id = request.match_info['container_id']

        log.info('WebSocket is ready.')
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        log.info('WebSocket is connected')
        await self._add_web_socket(ws)

        asyncio.ensure_future(self.collect(
                container_id=container_id,
                ws=ws
        ))

        while True:

            log.info('Waiting...')
            msg = await ws.receive()
            log.info(msg.type)
            if msg.type == WSMsgType.CLOSING or \
                    msg.type == WSMsgType.CLOSED or \
                    msg.tp == WSMsgType.ERROR:
                break

        await self._discard_web_socket(ws)
        log.info('WebSocket is closed.')

        return ws

    async def container_handler(self, request):

        container_id = request.match_info['container_id']
        log.info('container_handler "{container_id}".'.format(
            container_id=container_id
        ))

        return web.FileResponse('templates/container.html')
