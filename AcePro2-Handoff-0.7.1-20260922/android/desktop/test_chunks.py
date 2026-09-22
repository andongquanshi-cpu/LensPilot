import hashlib
import unittest
from chunk_upload import Uploads, UploadConflict

ID='12345678-1234-1234-1234-123456789abc'
class ChunkTest(unittest.TestCase):
    def test_duplicate_chunk_and_commit_publish_once(self):
        uploads=Uploads();data=b'a'*8192+b'b'*400
        digest=hashlib.sha256(data).hexdigest();published=[]
        def send(offset,chunk,commit=False):
            return uploads.accept(ID,len(data),digest,offset,chunk,commit,
                lambda body: published.append(bytes(body)) or {'status':'received'})
        self.assertEqual(send(0,data[:8192])['nextOffset'],8192)
        self.assertEqual(send(0,data[:8192])['nextOffset'],8192)
        send(8192,data[8192:])
        self.assertEqual(published,[])
        self.assertTrue(send(len(data),b'',True)['completed'])
        self.assertTrue(send(len(data),b'',True)['completed'])
        self.assertEqual(published,[data])
    def test_rejects_checksum_and_never_publishes(self):
        uploads=Uploads();published=[]
        uploads.accept(ID,3,'0'*64,0,b'abc',False,lambda _:published.append(True))
        with self.assertRaisesRegex(ValueError,'checksum'):
            uploads.accept(ID,3,'0'*64,3,b'',True,lambda _:published.append(True))
        self.assertEqual(published,[])
    def test_out_of_order_returns_resume_offset(self):
        with self.assertRaises(UploadConflict) as error:
            Uploads().accept(ID,10,'0'*64,8,b'ab',False,lambda _:None)
        self.assertEqual(error.exception.offset,0)
    def test_partial_commit_rejected(self):
        uploads=Uploads();uploads.accept(ID,10,'0'*64,0,b'abc',False,lambda _:None)
        with self.assertRaises(UploadConflict) as error:
            uploads.accept(ID,10,'0'*64,10,b'',True,lambda _:self.fail('partial publish'))
        self.assertEqual(error.exception.offset,3)


class ChunkHttpTest(unittest.TestCase):
    def test_wire_protocol_and_repeated_commit(self):
        import io,json,tempfile,threading,urllib.request,uuid
        from pathlib import Path
        from zipfile import ZipFile
        from http.server import HTTPServer
        from receiver import Receiver
        buffer=io.BytesIO()
        with ZipFile(buffer,'w') as archive:
            archive.writestr('manifest.json',json.dumps({'requestId':'http-test','frames':[{'file':'frame-01.jpg'}]}))
            archive.writestr('frame-01.jpg',b'x'*18000)
        body=buffer.getvalue();digest=hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            server=HTTPServer(('127.0.0.1',0),Receiver);server.output=Path(tmp)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            upload=str(uuid.uuid4())
            def request(offset,data,commit=0):
                url=f'http://127.0.0.1:{server.server_port}/batch?upload={upload}&total={len(body)}&sha256={digest}&offset={offset}&commit={commit}'
                with urllib.request.urlopen(urllib.request.Request(url,data=data)) as response:
                    return json.load(response)
            try:
                for offset in range(0,len(body),8192):
                    result=request(offset,body[offset:offset+8192])
                    self.assertEqual(result['nextOffset'],min(offset+8192,len(body)))
                self.assertEqual(list(Path(tmp).iterdir()),[])
                self.assertTrue(request(len(body),b'',1)['completed'])
                self.assertTrue(request(len(body),b'',1)['completed'])
                self.assertEqual(len(list(Path(tmp).glob('batch-*'))),1)
            finally:
                server.shutdown();worker.join();server.server_close()

class KeepAliveTest(unittest.TestCase):
    def test_reuses_connection_for_chunks(self):
        import http.client,json,tempfile,threading
        from pathlib import Path
        from http.server import ThreadingHTTPServer
        from receiver import Receiver
        data=b'x'*16384;digest=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            server=ThreadingHTTPServer(('127.0.0.1',0),Receiver);server.output=Path(tmp)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
            try:
                first=None
                for offset in [0,8192]:
                    client.request('POST',f'/batch?upload={ID}&total={len(data)}&sha256={digest}&offset={offset}',data[offset:offset+8192])
                    response=client.getresponse();reply=json.loads(response.read())
                    self.assertEqual(reply['nextOffset'],offset+8192)
                    if first is None:first=client.sock
                    else:self.assertIs(client.sock,first)
                self.assertIsNotNone(first)
            finally:
                client.close();server.shutdown();worker.join();server.server_close()

if __name__=='__main__':unittest.main()
