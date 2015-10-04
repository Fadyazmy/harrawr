import argparse
import json
import os
import socket
import signal
import time
import asyncio
import traceback

import aiohttp
import aiohttp.server
from aiohttp import websocket


import base64
import binascii
import datetime
import email.utils
import hashlib
import hmac
import json
import os
import pprint
import struct
import sys
import urllib.parse
import uuid

import asyncio

import aiohttp
from aiohttp import websocket

#import speex


URL = 'https://httpapi.labs.nuance.com/v1'
APP_ID = 'NMDPPRODUCTION_Usman_Gul_horror_20151002223822'
APP_KEY = 'a53fddcec74a8d44b829ccb3a99030cbe9222da979a7ccf1702f3b399949f03e88cd0d4f179a93d0c360836cf0b338d9d565834f0c4f407c7f7cb618c5a6574e'
DEVICE_ID = 'WearHacks Horror Demo'
CONTEXT_TAG = 'V3_Project764_App361'
WS_KEY = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class HttpRequestHandler(aiohttp.server.ServerHttpProtocol):
    _writer = None
    _reader = None
    transaction_id = 0
    muse_clients = None

    def __init__(self, *args, muse_clients=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.muse_clients = muse_clients

    @asyncio.coroutine
    def handle_request(self, message, payload):
        print('Client connected')
        upgrade = 'websocket' in message.headers.get('UPGRADE', '').lower()

        if not upgrade:
            response = aiohttp.Response(
                self.writer, 426, http_version=message.version)
            response.add_header('Content-type', 'application/json')
            response.send_headers()
            response.write(json.dumps({'error': 'WebSockets Required'}))
            yield from response.write_eof()
            return

        print ('Upgrading connection')

        # websocket handshake
        status, headers, parser, writer, protocol = websocket.do_handshake(
            message.method, message.headers, self.transport)

        resp = aiohttp.Response(
            self.writer, status, http_version=message.version)
        resp.add_headers(*headers)
        resp.send_headers()

        # install websocket parser
        self._reader = self.reader.set_parser(parser)
        self._writer = writer

        # Expect
        # {"type": "handshake", "client": "<name>", "protocol" : "<protocol>"}
        try:
            msg = yield from self.get_json()
            assert msg['type'] == 'handshake'
            protocol = msg['protocol']
            print(protocol)
            client = msg['client']
        except:
            traceback.print_exc()
            self.send_json(error='Invalid Handshake')
            return

        print('{} client connected'.format(client))
        self.send_json(type='handshake',
                       message='Connected')

        if protocol == 'nlu':
            yield from self.handle_nlu()
        elif protocol == 'muse':
            yield from self.handle_muse()
        elif protocol == 'muse_src':
            yield from self.handle_muse_src()
        else:
            pass # return error
        writer.close()

    @asyncio.coroutine
    def handle_muse_source(self):
        while True:
            msg = yield from self.get_json()
            for client in self.muse_clients:
                client.send_json(msg)

    @asyncio.coroutine
    def handle_muse(self):
        try:
            self.muse_clients.append(self)
            while True:
                yield from asyncio.sleep(1)
        finally:
            self.muse_clients.pop()

    @asyncio.coroutine
    def handle_nlu(self):
        #encoder = speex.WBEncoder()
        #frame_size = encoder.frame_size * 2 # two bytes per sample
        client = WebsocketConnection()
        yield from client.connect(URL, APP_ID, binascii.unhexlify(APP_KEY))

        client.send_message({
            'message': 'connect',
            'device_id': DEVICE_ID,
            'codec': 'audio/L16;rate=16000' #'audio/x-speex;mode=wb'
        })

        tp, msg = yield from client.receive()
        log(msg) # Should be a connected message

        while True:
            print('Waiting for NLU transaction')

            # Expect:
            # {"type": "nlu", "command": "start"}
            try:
                msg = yield from self.get_json()
                assert msg['type'] == 'nlu'
                assert msg['command'] == 'start'
            except:
                traceback.print_exc()
                self.send_json(error='Expected NLU transaction')
                return

            print('Starting NLU transaction')

            self.transaction_id += 1

            client.send_message({
                'message': 'query_begin',
                'transaction_id': self.transaction_id,
                'command': 'NDSP_ASR_APP_CMD',
                'language': 'eng-USA',
                'context_tag': CONTEXT_TAG,
            })

            client.send_message({
                'message': 'query_parameter',
                'transaction_id': self.transaction_id,
                'parameter_name': 'AUDIO_INFO',
                'parameter_type': 'audio',
                'audio_id': self.transaction_id
            })

            client.send_message({
                'message': 'query_end',
                'transaction_id': self.transaction_id
            })

            client.send_message({
                'message': 'audio',
                'audio_id': self.transaction_id,
            })

            print('Streaming audio')

            while True:
                try:
                    msg = yield from self._reader.read()
                    if msg.tp == websocket.MSG_TEXT:
                        break;

                    assert msg.tp == websocket.MSG_BINARY
                    #assert len(msg.data) == frame_size
                except:
                    traceback.print_exc()
                    self.send_json(error='Bad Audio Format')
                    return

                #frame = encoder.encode(msg.data)
                #client.send_audio(frame)
                client.send_audio(msg.data)

            # Expect:
            # {"type": "nlu", "command": "end"}
            try:
                assert msg.tp == websocket.MSG_TEXT
                msg = json.loads(msg.data)
                assert msg['type'] == 'nlu'
                assert msg['command'] == 'stop'
            except:
                traceback.print_exc()
                self.send_json(error='Expected NLU transaction terminator')
                return

            print('Done streaming audio')

            client.send_message({
                'message': 'audio_end',
                'audio_id': self.transaction_id,
            })

            print('Waiting for result')

            while True:
                tp,msg = yield from client.receive()
                log(msg)

                if msg['message'] == 'query_response' and msg['final_response'] == 1:
                    result = msg

                if msg['message'] == 'query_end':
                    break
            self.send_json(result=result)

        client.close()
        # writer.close()

    @asyncio.coroutine
    def get_json(self):
        msg = yield from self._reader.read()
        assert msg.tp == websocket.MSG_TEXT
        return json.loads(msg.data)

    def send_json(self, **kwargs):
        data = json.dumps(kwargs)
        self._writer.send(data)


class WebsocketConnection:
    MSG_JSON = 1
    MSG_AUDIO = 2

    @asyncio.coroutine
    def connect(self, url, app_id, app_key, use_plaintext=True):
        date = datetime.datetime.utcnow()
        sec_key = base64.b64encode(os.urandom(16))

        if use_plaintext:
            params = {'app_id': app_id, 'algorithm': 'key', 'app_key': binascii.hexlify(app_key)}
        else:
            datestr = date.replace(microsecond=0).isoformat()
            params = {
                'date': datestr,
                'app_id': app_id,
                'algorithm': 'HMAC-SHA-256',
                'signature': hmac.new(app_key,datestr.encode('ascii')+b' '+app_id.encode('utf-8'),hashlib.sha256).hexdigest()
            }

        response = yield from aiohttp.request(
            'get', url + '?' + urllib.parse.urlencode(params),
            headers={
                'UPGRADE': 'WebSocket',
                'CONNECTION': 'Upgrade',
                'SEC-WEBSOCKET-VERSION': '13',
                'SEC-WEBSOCKET-KEY': sec_key.decode(),
            })

        if response.status == 401 and not use_plaintext:
            if 'Date' in response.headers:
                server_date = email.utils.parsedate_to_datetime(response.headers['Date'])
                if server_date.tzinfo is not None:
                    server_date = (server_date - server_date.utcoffset()).replace(tzinfo=None)
            else:
                server_date = yield from response.read()
                server_date = datetime.datetime.strptime(server_date[:19].decode('ascii'), "%Y-%m-%dT%H:%M:%S")

            # Use delta on future requests
            date_delta = server_date - date

            print("Retrying authorization (delta=%s)" % date_delta)

            datestr = (date+date_delta).replace(microsecond=0).isoformat()
            params = {
                'date': datestr,
                'algorithm': 'HMAC-SHA-256',
                'app_id': app_id,
                'signature': hmac.new(app_key,datestr.encode('ascii')+b' '+app_id.encode('utf-8'),hashlib.sha256).hexdigest()
            }
    
            response = yield from aiohttp.request(
                'get', url + '?' + urllib.parse.urlencode(params),
                headers={
                    'UPGRADE': 'WebSocket',
                    'CONNECTION': 'Upgrade',
                    'SEC-WEBSOCKET-VERSION': '13',
                    'SEC-WEBSOCKET-KEY': sec_key.decode(),
                })


        if response.status != 101:
            info = "%s %s\n" % (response.status, response.reason)
            for (k,v) in response.headers.items():
                info += '%s: %s\n' % (k,v)
            info += '\n%s' % (yield from response.read()).decode('utf-8')

            if response.status == 401:
                raise RuntimeError("Authorization failure:\n%s" % info)
            elif response.status >= 500 and response.status < 600:
                raise RuntimeError("Server error:\n%s" %  info)
            elif response.headers.get('upgrade', '').lower() != 'websocket':
                raise ValueError("Handshake error - Invalid upgrade header")
            elif response.headers.get('connection', '').lower() != 'upgrade':
                raise ValueError("Handshake error - Invalid connection header")
            else:
                raise ValueError("Handshake error: Invalid response status:\n%s" % info)


        key = response.headers.get('sec-websocket-accept', '').encode()
        match = base64.b64encode(hashlib.sha1(sec_key + WS_KEY).digest())
        if key != match:
            raise ValueError("Handshake error - Invalid challenge response")

        # switch to websocket protocol
        self.connection = response.connection
        self.stream = self.connection.reader.set_parser(websocket.WebSocketParser)
        self.writer = websocket.WebSocketWriter(self.connection.writer)
        self.response = response

    @asyncio.coroutine
    def receive(self):
        wsmsg = yield from self.stream.read()
        if wsmsg.tp == 1:
            return (self.MSG_JSON, json.loads(wsmsg.data))
        else:
            return (self.MSG_AUDIO, wsmsg.data)

    def send_message(self, msg):
        log(msg,sending=True)
        self.writer.send(json.dumps(msg))

    def send_audio(self, audio):
        self.writer.send(audio, binary=True)

    def close(self):
        self.writer.close()
        self.response.close()
        self.connection.close()

def log(obj,sending=False):
    print('>>>>' if sending else '<<<<')
    print('%s' % datetime.datetime.now())
    pprint.pprint(obj)
    print()

loop = asyncio.get_event_loop()
muse_clients = []
server = loop.create_server(lambda: HttpRequestHandler(muse_clients=muse_clients), '127.0.0.1', 8080)
loop.run_until_complete(server)
loop.run_forever()
