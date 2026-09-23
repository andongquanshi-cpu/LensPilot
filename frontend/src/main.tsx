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
const steps = ['接收画面','分析场景','给出建议']
type Show={stage:string;count:number;requestId:string|null;target:string|null;reason:string;subject:string;lens?:string}
type Phase='wait'|'count'|'look'|'pick'
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
  const started=useRef(0),requestRef=useRef<string|null>(null)
  const demoActive=demo!==null
  const lens=live.lens??'waiting'
  const show:Show=demoActive?{stage:'ready',count:6,requestId:'demo-'+run,target:demo,reason:demo==='KEEP'?'这一帧没有明确的换镜依据，所以保持现在的样子。':'画面里有分开的点状亮光，建议试星光镜。',subject:'点状亮光'}:live
  const selected=lenses.find(l=>l.id===show.target),keep=phase==='pick'&&!selected,result=phase==='pick'
  const step=result?2:phase==='look'?1:0
  useEffect(()=>{
    let dead=false,timer:ReturnType<typeof setTimeout>
    async function poll(){
      try{
        const response=await fetch('/api/show',{signal:AbortSignal.timeout(4500),cache:'no-store'})
        if(!response.ok)throw new Error('unavailable')
        const data=await response.json() as Show
        if(!dead){setLive(data);setOnline(true)}
      }catch{if(!dead)setOnline(false)}
      if(!dead)timer=setTimeout(poll,1000)
    }
    void poll()
    return()=>{dead=true;clearTimeout(timer)}
  },[])
  useEffect(()=>{
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
  const headline=phase==='wait'?<>好画面，<br/>差一点<span className="highlight">「光」。</span></>:phase==='count'?<>这一刻，<br/><span className="highlight">收到了。</span></>:phase==='look'?<>正在寻找，<br/><span className="highlight">光的搭档。</span></>:keep?<>这一刻，<br/><span className="highlight">保持就好。</span></>:<>{selected?.title.split('，')[0]}，<br/><span className="highlight">{selected?.title.split('，')[1]??selected?.name}</span></>
  const subtitle=phase==='wait'?'等下一批照片。想先看选镜过程，点下方演示。':phase==='count'?(demoActive?'这些是演示画面，不是相机刚传来的。':'收到 '+show.count+' 张，先看第一张。'):phase==='look'?'正在从四片镜里选一片。':show.reason
  return <main className={'shell phase-'+phase+(demoActive?' demo-on':'')}>
    <header className="header">
      <a className="brand" href="/" aria-label="光随 AI · LensPilot 首页"><Aperture size={29} strokeWidth={2.5}/><span>光随 AI<span className="brand-dot">.</span></span><small>LensPilot</small></a>
      <div className="status-group">
        <span className={'connection '+(online?'online':'')}><i/>{online?'接收端已连接':'等待接收端'}</span>
        <span className={'connection lens '+(lens==='connected'?'online':lens==='synchronizing'?'sync':'')}><i/>{lens==='connected'?'镜片板已连接':lens==='synchronizing'?'镜片板同步中':'镜片板未连接'}</span>
        {demoActive&&<span className="demo-badge">演示</span>}
      </div>
    </header>
    <div className="progress" aria-label="当前进度"><ol>{steps.map((label,i)=><li key={label} className={i===step?'current':i<step?'done':''} aria-current={i===step?'step':undefined}><span className="step-number">{i<step?<Check size={11}/>:String(i+1).padStart(2,'0')}</span>{label}{i<steps.length-1&&<span className="step-line"/>}</li>)}</ol></div>
    <section className="hero" aria-live="polite"><h1 key={phase+(result?show.target??'keep':'')}>{headline}</h1><p className="subtitle">{subtitle}</p></section>
    <section className={'stage '+(phase==='wait'||phase==='count'?'gallery-stage':'')} aria-label="创作流程">
      {(phase==='wait'||phase==='count')?<>
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
      <div className="demo-tools">{demoActive?<>
        <button className={demo==='STAR'?'is-on':''} onClick={()=>play('STAR')}>星光镜</button>
        <button className={demo==='KEEP'?'is-on':''} onClick={()=>play('KEEP')}>保持原样</button>
        <button onClick={()=>demo&&play(demo)}><RotateCcw size={13}/>重播</button>
        <button onClick={()=>setDemo(null)}>回到实时</button>
      </>:<button className={phase==='wait'?'demo-start':'demo-quiet'} onClick={()=>play('STAR')}>看一遍演示 <ArrowUpRight size={14}/></button>}</div>
    </footer>
  </main>
}
createRoot(document.getElementById('root')!).render(<App/>)
