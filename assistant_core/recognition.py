"""Optional Deepgram live recognition. Only activated request audio leaves the PC.

One bounded queue joins the microphone owner to an isolated asyncio connection.
Interim results are display-only; an acknowledged CloseStream is required before
returning final text. Failures never silently route audio to another provider.
"""
import asyncio
import json
import queue
import threading
import time


class RecognitionError(Exception):
    pass


class FinalTranscript:
    def __init__(self, partial):
        self.segments = {}
        self.partial = partial
        self.acknowledged = False
        self.previous = ''

    def accept(self, message):
        kind = message.get('type')
        if kind == 'Error':
            raise RecognitionError('Streaming recognition failed. Check the service in Settings.')
        if kind == 'Metadata':
            self.acknowledged = True
            return
        if kind != 'Results':
            return
        alternatives = message.get('channel', {}).get('alternatives', [])
        text = str(alternatives[0].get('transcript', '')).strip() if alternatives else ''
        if len(text) > 8000:
            raise RecognitionError('Recognition response is too long.')
        if message.get('is_final'):
            self.segments[float(message.get('start', 0))] = text
            text = ''
        preview = ' '.join([self.text(), text]).strip()
        if preview and preview != self.previous:
            self.partial(preview)
            self.previous = preview

    def text(self):
        text = ' '.join(self.segments[key] for key in sorted(self.segments)).strip()
        if len(text) > 8000:
            raise RecognitionError('Recognition response is too long.')
        return text


class StreamingRecognition:
    def __init__(self, key, language, pause, valid, partial):
        if not key:
            raise RecognitionError('Add your Deepgram API key in Settings to use streaming recognition.')
        self.key, self.language, self.pause = key, language, pause
        self.valid = valid
        self.transcript = FinalTranscript(lambda text: partial(text) if self._valid() else None)
        self.audio = queue.Queue(maxsize=500)  # At most ten seconds of 20 ms frames.
        self.ending = threading.Event()
        self.sent_close = threading.Event()
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.error = None
        self.loop = self.task = None
        self.bytes_sent = 0
        self.worker = threading.Thread(target=self._run, name='streaming-recognition', daemon=True)
        self.worker.start()

    def _valid(self):
        return not self.cancelled.is_set() and self.valid()

    def feed(self, pcm):
        if not self._valid():
            raise RecognitionError('Recognition cancelled.')
        if self.error or self.done.is_set():
            raise RecognitionError(self.error or 'Streaming recognition ended unexpectedly.')
        self.bytes_sent += len(pcm)
        if len(pcm) > 32000 or self.bytes_sent > 16000 * 2 * 33:
            self.close()
            raise RecognitionError('Streaming audio exceeded the request limit.')
        try:
            self.audio.put_nowait(bytes(pcm))
        except queue.Full:
            self.close()
            raise RecognitionError('Recognition connection is too slow. Please try again.') from None

    def finish(self, timeout=8):
        self.ending.set()
        deadline = time.monotonic() + timeout
        try:
            while not self.done.wait(.02):
                if not self._valid():
                    raise RecognitionError('Recognition cancelled.')
                if time.monotonic() >= deadline:
                    raise RecognitionError('Streaming recognition timed out. Please try again.')
            if not self._valid():
                raise RecognitionError('Recognition cancelled.')
            if self.error or not self.transcript.acknowledged:
                raise RecognitionError(self.error or 'Recognition ended without a final acknowledgment.')
            return self.transcript.text()
        finally:
            self.close()

    def close(self):
        self.cancelled.set()
        if self.loop is not None and self.task is not None:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass

    def _run(self):
        try:
            asyncio.run(self._connect())
        except asyncio.CancelledError:
            pass
        except Exception:
            # Provider errors may contain headers; never expose exception text.
            self.error = 'Deepgram could not complete recognition. Check your key, connection and service availability.'
        finally:
            self.key = ''
            self.done.set()

    async def _connect(self):
        import aiohttp
        self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
        if not self._valid():
            return
        params = {'model': 'nova-3', 'language': 'multi' if self.language == 'auto' else self.language.split('-')[0],
                  'encoding': 'linear16', 'sample_rate': '16000', 'channels': '1',
                  'interim_results': 'true', 'smart_format': 'true',
                  'endpointing': str(int(self.pause * 1000)), 'mip_opt_out': 'true'}
        timeout = aiohttp.ClientTimeout(total=45, connect=8, sock_connect=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect('wss://api.deepgram.com/v1/listen', params=params,
                    headers={'Authorization': 'Token ' + self.key}, max_msg_size=256*1024,
                    timeout=aiohttp.ClientWSTimeout(ws_receive=8, ws_close=1)) as socket:
                sender = asyncio.create_task(self._send(socket))
                try:
                    async for message in socket:
                        if not self._valid():
                            return
                        if message.type == aiohttp.WSMsgType.TEXT:
                            self.transcript.accept(json.loads(message.data))
                            if self.transcript.acknowledged:
                                if not self.sent_close.is_set():
                                    raise RecognitionError('Recognition ended early.')
                                return
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            raise RecognitionError('Recognition connection failed.')
                finally:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)

    async def _send(self, socket):
        last = time.monotonic()
        started = last
        try:
            while self._valid() and time.monotonic() - started < 42:
                try:
                    pcm = self.audio.get_nowait()
                except queue.Empty:
                    if self.ending.is_set():
                        await socket.send_json({'type': 'CloseStream'})
                        self.sent_close.set()
                        return
                    if time.monotonic() - last > 3:
                        await socket.send_json({'type': 'KeepAlive'})
                        last = time.monotonic()
                    await asyncio.sleep(.02)
                    continue
                if not self._valid():
                    return
                await socket.send_bytes(pcm)
                last = time.monotonic()
        finally:
            if not self.ending.is_set() or not self._valid():
                await socket.close()
