const fs = require('fs');
const path = require('path');
const {spawn} = require('child_process');
const {once} = require('events');
const deps = 'C:/Users/35552/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/';
const {chromium} = require(deps+'playwright');
const sharp = require(deps+'sharp');
const root = path.resolve(__dirname,'..');
const out = path.join(root,'outputs','photo-pop');
const work = path.join(root,'tmp','photo-pop');
fs.mkdirSync(out,{recursive:true}); fs.mkdirSync(work,{recursive:true});
const sources = [
 'C:/Users/35552/AppData/Local/Temp/codex-clipboard-ba6598b8-5586-4720-a50e-5a50bc5653ee.png',
 'C:/Users/35552/AppData/Local/Temp/codex-clipboard-53073c36-3b66-41b9-bdd4-243e2a788394.png',
 'C:/Users/35552/AppData/Local/Temp/codex-clipboard-38276c74-4b30-407d-8a33-71513a630b7e.jpg'
];
const times = [.10,1.20,2.30];
function audio(){
 const rate=48000,n=rate*4,b=Buffer.alloc(44+n*4);
 b.write('RIFF'); b.writeUInt32LE(b.length-8,4); b.write('WAVE',8); b.write('fmt ',12);
 b.writeUInt32LE(16,16); b.writeUInt16LE(1,20); b.writeUInt16LE(2,22); b.writeUInt32LE(rate,24); b.writeUInt32LE(rate*4,28); b.writeUInt16LE(4,32); b.writeUInt16LE(16,34); b.write('data',36); b.writeUInt32LE(n*4,40);
 let seed=71; const rand=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296*2-1;};
 for(let k=0;k<n;k++){
  const t=k/rate; let v=0;
  for(const start of times){const q=t-start;
   if(q>=0&&q<.13){v+=.34*rand()*Math.exp(-q*105)+.14*Math.sin(2*Math.PI*175*q)*Math.exp(-q*58);}
   const r=q-.042; if(r>=0&&r<.10)v+=.24*rand()*Math.exp(-r*125);
  }
  const z=Math.round(Math.max(-1,Math.min(1,v))*32767); b.writeInt16LE(z,44+k*4);b.writeInt16LE(z,46+k*4);
 }
 const p=path.join(work,'shutter.wav');fs.writeFileSync(p,b);return p;
}
async function main(){
 const ffdir=path.join(root,'tmp/video-tools/imageio_ffmpeg/binaries');
 const ff=path.join(ffdir,fs.readdirSync(ffdir).find(n=>n.endsWith('.exe')));
 const browser=await chromium.launch({executablePath:'C:/Users/35552/AppData/Local/ms-playwright/chromium-1148/chrome-win/chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1980,height:1080},deviceScaleFactor:1});
 const photos=await Promise.all(sources.map(async p=>'data:image/jpeg;base64,'+(await sharp(p).rotate().resize({height:1500,withoutEnlargement:true}).jpeg({quality:96}).toBuffer()).toString('base64')));
 await page.setContent('<html><body style="margin:0"><canvas width="1980" height="1080"></canvas></body></html>');
 await page.evaluate(async({photos,times})=>{
  const c=document.querySelector('canvas'),ctx=c.getContext('2d');
  const images=await Promise.all(photos.map(src=>new Promise(resolve=>{const im=new Image();im.onload=()=>resolve(im);im.src=src;})));
  const positions=[[432,521,-6],[990,517,4],[1547,523,-3]];
  const words=['这样！','这样！','这样的！'];
  function line(points,width=6,color='#E26D51'){ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.lineJoin='round';ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();}
  function anger(x,y,s){ctx.save();ctx.translate(x,y);ctx.scale(s,s);line([[-17,-31],[-17,-17],[-31,-17]],7);line([[17,-31],[17,-17],[31,-17]],7);line([[-31,17],[-17,17],[-17,31]],7);line([[31,17],[17,17],[17,31]],7);ctx.restore();}
  window.drawFrame=(t)=>{
   ctx.fillStyle='#F7F3EB';ctx.fillRect(0,0,1980,1080);
   for(let i=0;i<3;i++){
    const d=t-times[i];if(d<0)continue;
    const spring=Math.exp(-d*15)*Math.cos(d*24);const scale=1+.23*spring;
    const [x,y,a]=positions[i];
    ctx.save();ctx.translate(x,y-75*Math.exp(-d*19));ctx.rotate((a+8*Math.exp(-d*15)*Math.sin(d*21))*Math.PI/180);ctx.scale(scale,scale);
    ctx.shadowColor='rgba(55,40,28,.17)';ctx.shadowBlur=24;ctx.shadowOffsetX=3;ctx.shadowOffsetY=12;
    ctx.fillStyle='#FFFEFA';ctx.fillRect(-215,-401,430,802);ctx.shadowColor='transparent';
    ctx.drawImage(images[i],-191,-378,382,680);
    ctx.strokeStyle='rgba(40,32,26,.08)';ctx.lineWidth=1;ctx.strokeRect(-191,-378,382,680);
    const td=Math.max(0,d-.07);const ts=1+.16*Math.exp(-td*14)*Math.sin(td*26);
    ctx.save();ctx.translate(0,350);ctx.scale(ts,ts);ctx.rotate(Math.sin(td*32)*Math.exp(-td*11)*.035);
    ctx.font='900 '+(i===2?83:94)+'px "Microsoft YaHei",sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.lineJoin='round';
    ctx.strokeStyle='#FFFEFA';ctx.lineWidth=19;ctx.strokeText(words[i],0,0);
    ctx.strokeStyle='#332C2B';ctx.lineWidth=10;ctx.strokeText(words[i],0,3);
    ctx.fillStyle=i===2?'#ED957F':'#F5B19C';ctx.fillText(words[i],0,0);ctx.restore();
    const dd=Math.min(1,d*7);
    if(i===0){line([[222,-305],[246,-319]],5);line([[230,-277],[257,-277]],5);}
    if(i===1)anger(202,-362,.75*dd);
    if(i===2){anger(202,-360,dd);line([[-225,309],[-248,296]],6);line([[-231,338],[-257,338]],6);}
    ctx.restore();
   }
  };
 },{photos,times});
 const silent=path.join(work,'silent.mp4');
 const encoder=spawn(ff,['-y','-hide_banner','-loglevel','error','-f','image2pipe','-vcodec','png','-framerate','30','-i','pipe:0','-an','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',silent],{stdio:['pipe','ignore','pipe'],windowsHide:true});
 let err='';encoder.stderr.on('data',b=>err+=b);const done=new Promise((resolve,reject)=>encoder.on('close',code=>code?reject(Error(err)):resolve()));
 for(let f=0;f<120;f++){
  const frame=await page.evaluate(t=>{window.drawFrame(t);return document.querySelector('canvas').toDataURL('image/png').split(',')[1];},f/30);
  const bytes=Buffer.from(frame,'base64');
  if([20,55,98].includes(f))fs.writeFileSync(path.join(work,`preview-${f}.png`),bytes);
  if(!encoder.stdin.write(bytes))await once(encoder.stdin,'drain');
  if(f%30===0)console.log(`Rendered ${f}/120`);
 }
 encoder.stdin.end();await done;await browser.close();
 const dest=path.join(out,'这样这样这样的_1980x1080_4秒.mp4');
 const mux=spawn(ff,['-y','-hide_banner','-loglevel','error','-i',silent,'-i',audio(),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t','4','-movflags','+faststart',dest],{stdio:'inherit',windowsHide:true});
 await new Promise((r,j)=>mux.on('close',c=>c?j(Error('mux failed')):r()));
 fs.copyFileSync(silent,path.join(out,'这样这样这样的_1980x1080_4秒_无声版.mp4'));
 fs.copyFileSync(path.join(work,'preview-98.png'),path.join(out,'效果预览.png'));
 console.log(JSON.stringify({output:dest,bytes:fs.statSync(dest).size}));
}
main().catch(e=>{console.error(e);process.exit(1);});
