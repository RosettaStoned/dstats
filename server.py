#!/usr/bin/env python3

import os
from dstats import StatsCollector

HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 9090))


def main():
    stats_collector = StatsCollector(host=HOST, port=PORT)
    stats_collector.start()


if __name__ == '__main__':
    main()
