import {useEffect, useRef, useState} from 'react'
import type {CSSProperties} from 'react'
import {createRoot} from 'react-dom/client'
import {ArrowUpRight, Aperture, Check, Focus, Pause, RotateCcw, Sparkles, Waves} from 'lucide-react'
import './style.css'

const lenses = [
  {id:'CPL',name:'偏振镜',english:'POLARIZER',icon:Waves,title:'让反光，轻一点。',hint:'留住风景里的清晰。'},
  {id:'CLOSE_UP',name:'近摄镜',english:'CLOSE UP',icon:Focus,title:'小细节，也有大世界。',hint:'把目光，放近一点。'},
  {id:'BLACK_MIST',name:'黑柔镜',english:'BLACK MIST',icon:Sparkles,title:'给这一刻，一点柔光。',hint:'让高光拥有柔软的边缘。'},
  {id:'STAR',name:'星光镜',english:'STAR FILTER',icon:Aperture,title:'让灯光，长出星芒。',hint:'为点状亮光，添一点表达。'},
]
const steps = ['接收画面','分析场景','给出建议','等待拍摄','成片展示']
const signals = ['CPL','CLOSE_UP','BLACK_MIST','STAR','KEEP'] as const
const boardName = 'ESP32_LensPilot'
const boardService = '4fafc201-1fb5-459e-8fcc-c5c9c331914b'
const boardCharacteristic = 'beb5483e-36e1-4688-b7f5-ea07361b26a8'
type Signal = typeof signals[number]
type BoardLink = { writeValue: (value: BufferSource) => Promise<void> }
type Show={stage:string;count:number;requestId:string|null;target:string|null;reason:string;subject:string;lens?:string;photoRequestId?:string;commandTarget?:string;executionNote?:string}
function signalFor(target: string | null): Signal {
  return (signals as readonly string[]).includes(target ?? '') ? target as Signal : 'KEEP'
}
type Phase='wait'|'count'|'look'|'pick'|'shoot'|'done'
type Demo='STAR'|'KEEP'
const waiting:Show={stage:'waiting',count:0,requestId:null,target:null,reason:'',subject:'',lens:'waiting'}
function Photo({src,label}:{src:string;label:string}){
  const [failed,setFailed]=useState(false)
  return failed?<span className="photo-missing">预览暂不可用</span>:<img src={src} alt={label} onError={()=>setFailed(true)}/>
}
function App(){
  const [live,setLive]=useState<Show>(waiting),[online,setOnline]=useState(false)
  const [demo,setDemo]=useState<Demo|null>(null),[run,setRun]=useState(0)
  const [phase,setPhase]=useState<Phase>('wait'),[hot,setHot]=useState(0)
  const [delay,setDelay]=useState(3),[flowError,setFlowError]=useState(''),[retry,setRetry]=useState(0)
  const armed=useRef<string|null>(null),epoch=useRef(0)
  const [boardOn,setBoardOn]=useState(false),[sent,setSent]=useState<Signal|null>(null),[boardMissing,setBoardMissing]=useState(false)
  const started=useRef(0),requestRef=useRef<string|null>(null)
  const boardLink=useRef<BoardLink|null>(null),sentFor=useRef<string|null>(null)
  const demoActive=demo!==null
  const show:Show=demoActive?{stage:'ready',count:6,requestId:'demo-'+run,target:demo,reason:demo==='KEEP'?'这一帧没有明确的换镜依据，所以保持现在的样子。':'画面里有分开的点状亮光，建议试星光镜。',subject:'点状亮光'}:live
  const selected=lenses.find(l=>l.id===show.target),keep=phase==='pick'&&!selected,result=phase==='pick'
  const step=phase==='done'?4:phase==='shoot'?3:result?2:phase==='look'?1:0
  useEffect(()=>{
    let dead=false,timer:ReturnType<typeof setTimeout>
    async function poll(){
      const generation=epoch.current
      try{
        const response=await fetch('/api/show',{signal:AbortSignal.timeout(4500),cache:'no-store'})
        if(!response.ok)throw new Error('unavailable')
        const data=await response.json() as Show
        if(!dead&&generation===epoch.current){setLive(data);setOnline(true)}
      }catch{if(!dead)setOnline(false)}
      if(!dead)timer=setTimeout(poll,1000)
    }
    void poll()
    return()=>{dead=true;clearTimeout(timer)}
  },[])
  useEffect(()=>{
    if(show.stage==='capture'){setPhase('shoot');return}
    if(show.stage==='complete'){setPhase('done');return}
    if(!show.requestId||show.stage==='waiting'){requestRef.current=null;setPhase('wait');return}
    if(requestRef.current!==show.requestId){requestRef.current=show.requestId;started.current=Date.now();setPhase('count')}
    const elapsed=Date.now()-started.current,timers:number[]=[]
    if(elapsed<1600)timers.push(window.setTimeout(()=>setPhase('look'),1600-elapsed))
    else setPhase(show.stage==='ready'&&elapsed>=4300?'pick':'look')
    if(show.stage==='ready')timers.push(window.setTimeout(()=>setPhase('pick'),Math.max(0,4300-elapsed)))
    return()=>timers.forEach(window.clearTimeout)
  },[show.requestId,show.stage])
  useEffect(()=>{
    if(phase!=='look')return
    const timer=setInterval(()=>setHot(v=>(v+1)%4),460)
    return()=>clearInterval(timer)
  },[phase])
  function preview(index:number){return '/api/show/frame?request_id='+encodeURIComponent(show.requestId??'')+'&index='+index}
  function play(target:Demo){setDemo(target);setRun(v=>v+1)}
  async function resetRound(){
    epoch.current++
    try{
      const response=await fetch('/api/show/reset',{method:'POST',signal:AbortSignal.timeout(4500)})
      if(!response.ok)throw new Error()
      epoch.current++;armed.current=null;setSent(null);setDemo(null);setFlowError('');setLive(await response.json())
    }catch{setFlowError('无法开始下一轮，请检查接收端后重试。')}
  }
  useEffect(()=>{
    if(phase!=='pick')return
    if(demoActive){const timer=setTimeout(()=>setPhase('shoot'),delay*1000);return()=>clearTimeout(timer)}
    if(!live.requestId||armed.current===live.requestId)return
    const requestId=live.requestId
    armed.current=requestId
    void fetch('/api/show/arm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({requestId,delaySeconds:delay}),signal:AbortSignal.timeout(4500)})
      .then(response=>{if(!response.ok)throw new Error();setFlowError('')})
      .catch(()=>{armed.current=null;setFlowError('暂未接通拍摄等待，请点击重试。')})
  },[phase,demoActive,live.requestId,delay,retry])
  async function publish(requestId:string,target:string|null){
    const link=boardLink.current
    if(!link||sentFor.current===requestId)return
    const signal=signalFor(target)
    sentFor.current=requestId // Claim before awaiting BLE; no duplicate physical commands.
    await link.writeValue(new TextEncoder().encode(signal))
    setSent(signal)
  }
  useEffect(()=>{
    if(demoActive||phase!=='pick'||!live.requestId)return
    const requestId=live.requestId,target=live.commandTarget??live.target
    void publish(requestId,target).catch(()=>{boardLink.current=null;setBoardOn(false);setSent(null);setFlowError('镜片指令未确认发送，请检查硬件；页面按辅助演示继续。')})
  },[demoActive,phase,live.requestId,live.target,live.commandTarget])
  async function connectBoard(){
    const bluetooth=(navigator as Navigator&{bluetooth?:{requestDevice:(options:{filters:{name:string}[];optionalServices:string[]})=>Promise<{gatt?:{connect:()=>Promise<{getPrimaryService:(uuid:string)=>Promise<{getCharacteristic:(uuid:string)=>Promise<BoardLink>}>}>};addEventListener:(type:string,listener:()=>void)=>void}>}}).bluetooth
    if(!bluetooth){setBoardMissing(true);return}
    try{
      const device=await bluetooth.requestDevice({filters:[{name:boardName}],optionalServices:[boardService]})
      const server=await device.gatt?.connect()
      if(!server)return
      const service=await server.getPrimaryService(boardService)
      boardLink.current=await service.getCharacteristic(boardCharacteristic)
      setBoardOn(true)
      device.addEventListener('gattserverdisconnected',()=>{boardLink.current=null;setBoardOn(false);setSent(null)})
      if(!demoActive&&phase==='pick'&&live.requestId)await publish(live.requestId,live.commandTarget??live.target)
    }catch{/* 用户取消选择设备时留在未连接。 */}
  }
  const headline=phase==='wait'?<>好画面，<br/>差一点<span className="highlight">「光」。</span></>:phase==='count'?<>这一刻，<br/><span className="highlight">收到了。</span></>:phase==='look'?<>正在寻找，<br/><span className="highlight">光的搭档。</span></>:keep?<>这一刻，<br/><span className="highlight">保持就好。</span></>:<>{selected?.title.split('，')[0]}，<br/><span className="highlight">{selected?.title.split('，')[1]??selected?.name}</span></>
  const subtitle=phase==='wait'?'等下一批照片。想先看选镜过程，点下方演示。':phase==='count'?(demoActive?'这些是演示画面，不是相机刚传来的。':'收到 '+show.count+' 张，先看第一张。'):phase==='look'?'正在从四片镜里选一片。':show.reason
  return <main className={'shell phase-'+phase+(demoActive?' demo-on':'')}>
    <header className="header">
      <a className="brand" href="/" aria-label="光随 AI · LensPilot 首页"><Aperture size={29} strokeWidth={2.5}/><span>光随 AI<span className="brand-dot">.</span></span><small>LensPilot</small></a>
      <div className="status-group">
        <span className={'connection '+(online?'online':'')}><i/>{online?'接收端已连接':'等待接收端'}</span>
        <button type="button" className={'connection lens '+(boardOn?'online':'')} onClick={()=>void connectBoard()}><i/>{boardMissing?'请用 Chrome 连接':boardOn?(sent&&!demoActive?'已发送 '+sent:'镜片板已连接'):'连接镜片板'}</button>
        {demoActive&&<span className="demo-badge">演示</span>}
      </div>
    </header>
    <div className="progress" aria-label="当前进度"><ol>{steps.map((label,i)=><li key={label} className={i===step?'current':i<step?'done':''} aria-current={i===step?'step':undefined}><span className="step-number">{i<step?<Check size={11}/>:String(i+1).padStart(2,'0')}</span>{label}{i<steps.length-1&&<span className="step-line"/>}</li>)}</ol></div>
    <section className="hero" aria-live="polite"><h1 key={phase+(result?show.target??'keep':'')}>{phase==='shoot'?<>镜片调整中，<br/><span className="highlight">等你按下快门。</span></>:phase==='done'?<>这一刻，<br/><span className="highlight">拍好了。</span></>:headline}</h1><p className="subtitle">{phase==='shoot'?'完成镜片调整后，按相机快门。正在等待本次照片回传。':phase==='done'?'相机拍摄的原始照片已回传。':subtitle}</p></section>
    <section className={'stage '+(phase==='wait'||phase==='count'?'gallery-stage':'')} aria-label="创作流程">
      {phase==='shoot'?<div className="capture-wait"><Aperture size={62} strokeWidth={1}/><h2>{selected?'本次建议 · '+selected.name:'保持当前镜片'}</h2><p><span className="pulse-dot"/> 等待新拍照片</p><small>{demoActive?'界面演示：不会发送指令或接收实拍照片。点击回到实时继续。':sent?'指令已发送；请人工确认镜片到位。':'镜片板未确认发送，请由现场同学辅助完成。'}</small><small>联动演示 · 换镜人工辅助 · 不以计时判断到位</small></div>:phase==='done'?<div className="capture-result"><Photo key={show.photoRequestId} src={'/api/show/frame?request_id='+encodeURIComponent(show.photoRequestId??'')+'&index=1'} label="本轮相机拍摄照片"/><span>本次拍摄 · 原图回传</span></div>:(phase==='wait'||phase==='count')?<>
        <div className="photo-fan">{Array.from({length:phase==='wait'?5:Math.min(5,show.count)},(_,i)=><article key={(show.requestId??'wait')+'-'+i} className="photo-card" style={{'--i':i,'--rotation':(i-2)*6+'deg'} as CSSProperties}><div className="photo-content">{phase==='wait'||demoActive?<div className={'graphic graphic-'+i}><span/><i/><b/>{i===2&&<Aperture size={62} strokeWidth={.8}/>}</div>:<Photo src={preview(i+1)} label={'本批第 '+(i+1)+' 张画面'}/>}</div></article>)}</div>
        <div className="gallery-caption">{phase==='wait'?<><span className="pulse-dot"/>等待下一批照片</>:demoActive?'演示中的一批画面':<><b>{String(show.count).padStart(2,'0')}</b> 张照片已接收</>}</div>
      </>:<>
        <div className={'lens-board '+(result&&selected?'has-winner':'')+(keep?' keep':'')}>
          {lenses.map((lens,i)=>{const Icon=lens.icon,chosen=result&&show.target===lens.id,mark=chosen?'本次建议':phase==='look'&&hot===i?'正在看':''
            return <div key={lens.id} className={'lens-cell cell-'+i+(phase==='look'&&hot===i?' hot':'')+(chosen?' chosen':'')}>
            <div className="cell-top"><span>0{i+1} / {lens.english}</span><ArrowUpRight size={19}/></div>
            <div className="lens-disc"><div className="disc-inner"><Icon strokeWidth={1.1}/></div></div>
            <div className="cell-bottom"><h2>{lens.name}</h2>{mark&&<span>{mark}</span>}</div>
            {chosen&&<div className="winner-info"><span className="recommend-tag"><Check size={13}/>建议这片</span><p>{lens.hint}</p></div>}
            {chosen&&!demoActive&&<div className="source-photo"><Photo key={show.requestId} src={preview(1)} label="本次分析的画面"/><span>看的是这张</span></div>}
          </div>})}
          {keep&&<div className="keep-message"><span className="keep-icon"><Pause size={29} fill="currentColor"/></span><h2>保持当前镜片</h2><p>这一帧先不换。</p></div>}
        </div>
      </>}
    </section>
    <footer>
      {!demoActive&&show.executionNote&&<p className="execution-note">{show.executionNote}</p>}
      {flowError&&<p className="flow-error" role="alert">{flowError}<button onClick={()=>setRetry(v=>v+1)}>重试等待连接</button></p>}
      <div className="demo-tools">{demoActive?<>
        <button className={demo==='STAR'?'is-on':''} onClick={()=>play('STAR')}>星光镜</button>
        <button className={demo==='KEEP'?'is-on':''} onClick={()=>play('KEEP')}>保持原样</button>
        <button onClick={()=>demo&&play(demo)}><RotateCcw size={13}/>重播</button>
        <button onClick={()=>setDemo(null)}>回到实时</button>
      </>:<><button className={phase==='wait'?'demo-start':'demo-quiet'} onClick={()=>play('STAR')}>看一遍演示 <ArrowUpRight size={14}/></button><button onClick={()=>void resetRound()}>开始下一轮</button></>}</div>
      <label className="delay-control">建议展示 <select value={delay} disabled={!['wait','done'].includes(phase)} onChange={e=>setDelay(Number(e.target.value))}>{[1,3,5,8,10].map(n=><option key={n} value={n}>{n} 秒</option>)}</select> 后等待拍摄</label>
    </footer>
  </main>
}
createRoot(document.getElementById('root')!).render(<App/>)
