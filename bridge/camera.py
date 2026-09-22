"""Upload local video/webcam frames to a selected backend upload session.
Ace Pro 2 teams can replace capture with their verified image callback and use Uploader.
"""
import argparse
import asyncio
import os
import time
import httpx


class Uploader:
    def __init__(self,url,session,token):
        self.url,self.session=url.rstrip('/'),session
        self.client=httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=5)
        self.sequence=0
        self.latest=None

    def put(self,jpeg:bytes,captured_at:float,capture_version:int|None=None):
        self.sequence+=1
        self.latest=(jpeg,captured_at,self.sequence,capture_version)

    async def pump(self):
        while True:
            if self.latest:
                jpeg,captured_at,sequence,capture_version=self.latest
                self.latest=None
                response=await self.client.post(self.url+'/api/frames',content=jpeg,headers={
                    'Content-Type':'image/jpeg','X-Source-Session':self.session,
                    'X-Sequence':str(sequence),'X-Captured-At':str(captured_at),
                    **({'X-Capture-State-Version':str(capture_version)} if capture_version is not None else {})})
                response.raise_for_status()
            else:await asyncio.sleep(.05)


async def capture(args,token):
    import cv2
    cap=cv2.VideoCapture(args.video if args.video else args.camera)
    if not cap.isOpened():raise RuntimeError('Cannot open local capture source')
    uploader=Uploader(args.url,args.session,token)
    async def read():
        while True:
            response=await uploader.client.get(uploader.url+'/api/capture-context')
            response.raise_for_status()
            context=response.json()
            if context['source_session_id']!=args.session:raise RuntimeError('Source session changed')
            ok,frame=await asyncio.to_thread(cap.read)
            if not ok:break
            scale=min(1,1280/max(frame.shape[:2]))
            if scale<1: frame=cv2.resize(frame,(int(frame.shape[1]*scale),int(frame.shape[0]*scale)))
            ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,80])
            # Recorded video has no verifiable relationship to today's physical lens.
            version=context['state_version'] if context['capture_allowed'] and not args.video else None
            if ok:uploader.put(jpeg.tobytes(),time.time(),version)
            await asyncio.sleep(.2)
    pump,reader=asyncio.create_task(uploader.pump()),asyncio.create_task(read())
    try:
        done,_=await asyncio.wait([pump,reader],return_when=asyncio.FIRST_COMPLETED)
        for task in done:task.result()
    finally:
        pump.cancel();reader.cancel()
        await asyncio.gather(pump,reader,return_exceptions=True)
        cap.release()
        await uploader.client.aclose()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='http://127.0.0.1:8000')
    p.add_argument('--session',required=True,help='Active upload/ace_bridge session shown by console')
    p.add_argument('--video',help='User-selected local video path on THIS PC')
    p.add_argument('--camera',type=int,default=0)
    args=p.parse_args()
    token=os.environ.get('OPTIC_DEVICE_TOKEN')
    if not token:p.error('Set OPTIC_DEVICE_TOKEN')
    asyncio.run(capture(args,token))


if __name__=='__main__':main()
