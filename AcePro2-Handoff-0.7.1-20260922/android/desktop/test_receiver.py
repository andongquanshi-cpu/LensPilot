import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import socket
from zipfile import ZipFile
from http.server import HTTPServer
from receiver import Receiver, save_batch


def payload(extra=None):
    data=io.BytesIO()
    with ZipFile(data, 'w') as z:
        z.writestr('manifest.json', json.dumps({'requestId':'test', 'frames':[{'file':'frame-01.jpg'}]}))
        z.writestr('frame-01.jpg', b'jpeg-test')
        if extra: z.writestr(extra, b'bad')
    return data.getvalue()


class ReceiverTest(unittest.TestCase):
    def test_http_whole_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=HTTPServer(('127.0.0.1',0),Receiver)
            server.output=Path(tmp)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                base=f'http://127.0.0.1:{server.server_port}'
                with urllib.request.urlopen(base+'/health') as response:
                    self.assertEqual(response.status,200)
                request=urllib.request.Request(base+'/batch',data=payload(),headers={'Content-Type':'application/zip'})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(json.load(response)['status'],'received')
                batches=list(Path(tmp).glob('batch-*'))
                self.assertEqual(len(batches),1)
                self.assertEqual((batches[0]/'frame-01.jpg').read_bytes(),b'jpeg-test')
                # A full but invalid archive must identify validation, not upload failure.
                bad=urllib.request.Request(base+'/batch',data=b'not-a-zip')
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(bad)
                with raised.exception as response:
                    detail=json.load(response)
                self.assertEqual(detail['stage'],'validate_and_save')
                self.assertEqual(detail['receivedBytes'],9)
                self.assertEqual(detail['type'],'BadZipFile')
                # Truncated body must report the actual bytes read and publish nothing.
                with socket.create_connection(server.server_address) as client:
                    client.sendall(b'POST /batch HTTP/1.0\r\nContent-Length: 100\r\n\r\nabc')
                    client.shutdown(socket.SHUT_WR)
                    with client.makefile('rb') as response:
                        raw=response.read()
                detail=json.loads(raw.split(b'\r\n\r\n',1)[1])
                self.assertEqual(detail['stage'],'upload')
                self.assertEqual(detail['receivedBytes'],3)
                self.assertEqual(detail['expectedBytes'],100)
                self.assertEqual(len(list(Path(tmp).glob('batch-*'))),1)

            finally:
                server.shutdown();thread.join();server.server_close()
    def test_rejects_unexpected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): save_batch(payload('../escape'),Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()),[])

if __name__ == '__main__': unittest.main()
