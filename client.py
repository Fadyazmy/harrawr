import argparse
import binascii
import json
import signal
import sys

import asyncio
try:
    import selectors
except ImportError:
    from asyncio import selectors

import aiohttp

ARGS = argparse.ArgumentParser(
    description="websocket console client for wssrv.py example.")
ARGS.add_argument(
    '--host', action="store", dest='host',
    default='127.0.0.1', help='Host name')
ARGS.add_argument(
    '--port', action="store", dest='port',
    default=8000, type=int, help='Port number')
ARGS.add_argument('filename')

def start_client(loop, url, filename):
    # send request
    ws = yield from aiohttp.ws_connect(url, autoclose=False, autoping=False)

    # handshake
    ws.send_str(json.dumps({'type': 'handshake', 'client': 'sample', 'protocol' : 'nlu'}))
    msg = yield from ws.receive()
    print(msg.data)

    # msg = yield from ws.receive()
    # print(msg.data)

    #for i in range(2):
    ws.send_str(json.dumps({'type': 'nlu', 'command': 'start'}))

    frame_size = 640
    with open(filename, 'rb') as file:
        while file.readable():
            data = file.read(frame_size)
            if  len(data) < frame_size:
                break
            ws.send_bytes(data)

    ws.send_str(json.dumps({'type': 'nlu', 'command': 'stop'}))

    output = yield from ws.receive() #asyncio.sleep(5)
    print(json.loads(output.data))


if __name__ == '__main__':
    args = ARGS.parse_args()
    if ':' in args.host:
        args.host, port = args.host.split(':', 1)
        args.port = int(port)

    url = 'http://{}:{}'.format(args.host, args.port)

    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)

    loop.add_signal_handler(signal.SIGINT, loop.stop)
    loop.run_until_complete(start_client(loop, url, args.filename))
