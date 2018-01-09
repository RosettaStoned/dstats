#!/usr/bin/env python3

import os
import sys
from dstats import StatsCollector

HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 9090))


def main():

    if not os.geteuid() == 0:
        sys.exit("Only root can run the server script")

    stats_collector = StatsCollector(host=HOST, port=PORT)
    stats_collector.start()


if __name__ == '__main__':
    main()
