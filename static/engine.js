/* Deterministic browser engine. Rules are verified against the Python engine. */
(function(scope){
  'use strict';
  const C=scope.NakedCSV, price=new Set(['opening_range','rolling_range','swing','ma','snapshot']);
  const conditions=new Set(['breakout','retest','candle','compare','and','or','sequence']);
  const clone=x=>JSON.parse(JSON.stringify(x));
  function canonical(v){if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';return JSON.stringify(v);}
  function versionIdentity(s){const normalized=clone(s);normalized.version=String(normalized.version);for(const key of ['stop_points','target_points','structure_source'])if(normalized.risk[key]==null)delete normalized.risk[key];return canonical(normalized);}
  function sha256(text){
    const data=new TextEncoder().encode(text),length=data.length,padded=new Uint8Array(Math.ceil((length+9)/64)*64);padded.set(data);padded[length]=128;
    const view=new DataView(padded.buffer);view.setUint32(padded.length-8,Math.floor(length/536870912));view.setUint32(padded.length-4,(length*8)>>>0);
    const K=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    const H=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19],W=new Uint32Array(64),r=(n,b)=>(n>>>b)|(n<<(32-b));
    for(let offset=0;offset<padded.length;offset+=64){for(let i=0;i<16;i++)W[i]=view.getUint32(offset+i*4);for(let i=16;i<64;i++){const a=W[i-15],b=W[i-2];W[i]=(W[i-16]+(r(a,7)^r(a,18)^(a>>>3))+W[i-7]+(r(b,17)^r(b,19)^(b>>>10)))>>>0;}
      let [a,b,c,d,e,f,g,h]=H;
      for(let i=0;i<64;i++){const t1=(h+(r(e,6)^r(e,11)^r(e,25))+((e&f)^(~e&g))+K[i]+W[i])>>>0,t2=((r(a,2)^r(a,13)^r(a,22))+((a&b)^(a&c)^(b&c)))>>>0;h=g;g=f;f=e;e=(d+t1)>>>0;d=c;c=b;b=a;a=(t1+t2)>>>0;}
      [a,b,c,d,e,f,g,h].forEach((n,i)=>H[i]=(H[i]+n)>>>0);
    }return H.map(n=>n.toString(16).padStart(8,'0')).join('');
  }
  function dependencies(b){const p=b.params;if(['breakout','retest','compare','event'].includes(b.type))return [p.source];if(b.type==='snapshot')return [p.source,p.trigger];if(['and','or','sequence'].includes(b.type))return p.inputs||[];return [];}
  function validate(s){
    const fail=message=>{throw Error(message);};
    if(!s||typeof s!=='object')fail('策略必須為物件');
    for(const k of ['strategy_id','version','instrument','timeframe','blocks','entries','exits','risk','limits','execution','costs'])if(!(k in s))fail('策略缺少 '+k);
    if(!s.strategy_id||!String(s.version))fail('策略 ID 與版本不可空白');
    if(![1,5,15].includes(s.timeframe)||!Array.isArray(s.blocks)||s.blocks.length>200)fail('策略週期或積木數量錯誤');
    const map=new Map();
    for(const b of s.blocks){if(!b||!['id','type','name','enabled','timeframe','params','output'].every(k=>k in b))fail('積木欄位不完整');if(typeof b.id!=='string'||!b.id||map.has(b.id))fail('積木 ID 必須唯一且非空白');
      if(!price.has(b.type)&&!conditions.has(b.type)&&b.type!=='event')fail('未知積木類型');
      if(![1,5,15].includes(b.timeframe)||typeof b.enabled!=='boolean'||!b.params||typeof b.params!=='object')fail('積木週期或參數錯誤');
      if(b.output!==(price.has(b.type)?'PriceLevel':b.type==='event'?'Event':'Condition'))fail('積木輸出型態錯誤');
      const p=b.params;for(const key of ['period','left','right','minutes','within'])if(key in p&&(!Number.isInteger(p[key])||p[key]<1||p[key]>10000))fail(key+' 必須為 1–10000 整數');
      if('direction'in p&&!['up','down'].includes(p.direction))fail('direction 須為 up/down');
      if('field'in p&&!['high','low','value'].includes(p.field))fail('field 須為 high/low/value');
      if('tolerance'in p&&(!Number.isFinite(p.tolerance)||p.tolerance<0))fail('回踩容許點數錯誤');
      if(['and','or','sequence'].includes(b.type)&&(!Array.isArray(p.inputs)||p.inputs.length<2||(b.type==='sequence'&&p.inputs.length!==2)))fail('AND/OR 至少兩個輸入；順序等待恰好兩個');
      map.set(b.id,b);
    }
    const ordered=[],visiting=new Set(),done=new Set();
    function visit(id){if(!map.has(id))fail('引用不存在的積木：'+id);if(visiting.has(id))fail('積木不可循環依賴');if(done.has(id))return;visiting.add(id);const b=map.get(id);dependencies(b).forEach((dep,i)=>{visit(dep);const source=map.get(dep),expected=['breakout','retest','compare'].includes(b.type)||(b.type==='snapshot'&&i===0)?'PriceLevel':'Condition';if(source.output!==expected)fail(`${id} 的輸入 ${dep} 必須是 ${expected}`);if(b.enabled&&!source.enabled)fail('引用未啟用的積木：'+dep);});visiting.delete(id);done.add(id);ordered.push(b);}
    for(const id of map.keys())visit(id);
    for(const section of ['entries','exits'])for(const side of ['long','short']){const id=s[section][side];if(id!=null&&(!map.has(id)||map.get(id).output==='PriceLevel'||!map.get(id).enabled))fail(`${section}.${side} 必須引用啟用的 Condition 或 Event`);}
    for(const k of ['stop_points','target_points'])if(s.risk[k]!=null&&(!Number.isFinite(s.risk[k])||s.risk[k]<=0))fail(k+' 必須為正數或空白');
    const src=s.risk.structure_source;if(src!=null&&(!map.has(src)||map.get(src).output!=='PriceLevel'||!map.get(src).enabled))fail('結構停損來源錯誤');
    for(const k of ['point_value','commission','tax_rate','tax_fixed','slippage','initial_capital'])if(!Number.isFinite(s.costs[k])||s.costs[k]<0||(['point_value','initial_capital'].includes(k)&&s.costs[k]===0))fail('成本參數錯誤：'+k);
    if(!['notional','fixed'].includes(s.costs.tax_mode))fail('交易稅模式錯誤');
    if(s.execution.entry!=='next_open'||s.execution.collision!=='stop_first'||Object.keys(s.execution).length!==2)fail('V1 成交規則固定為次棒開盤與停損優先');
    const l=s.limits;if(!/^\d{2}:\d{2}$/.test(l.entry_start)||!/^\d{2}:\d{2}$/.test(l.entry_end)||l.entry_start<'08:45'||l.entry_start>=l.entry_end||l.entry_end>'13:45'||!Number.isInteger(l.max_trades_per_day)||l.max_trades_per_day<1)fail('進場時段或每日交易數錯誤');
    return ordered;
  }
  function aggregate(bars,minutes){
    if(![1,5,15].includes(minutes))throw Error('只支援 1、5、15 分 K');
    const result=[];let group=[],bucket=null;
    function flush(){if(group.length!==minutes||group.some((b,i)=>b.start!==bucket+i*60000))return;result.push({start:bucket,open:group[0].open,high:Math.max(...group.map(b=>b.high)),low:Math.min(...group.map(b=>b.low)),close:group.at(-1).close,volume:group.every(b=>b.volume!=null)?group.reduce((a,b)=>a+b.volume,0):null,minutes});}
    for(const b of bars){if(!C.day(b.start))continue;const local=new Date(b.start+480*60000),offset=local.getUTCHours()*60+local.getUTCMinutes()-525,key=b.start-(offset%minutes)*60000;if(key!==bucket){flush();bucket=key;group=[];}group.push(b);}flush();return result;
  }
  function upper(array,value){let low=0,high=array.length;while(low<high){const mid=(low+high)>>>1;if(array[mid]<=value)low=mid+1;else high=mid;}return low;}
  class Evaluator{
    constructor(s,series){this.blocks=validate(s);this.series=series;this.ends=Object.fromEntries(Object.entries(series).map(([tf,bars])=>[tf,bars.map(b=>b.start+b.minutes*60000)]));this.values={};this.states={};this.processed={};}
    step(now){
      for(const b of this.blocks){if(!b.enabled)continue;const {id,type:kind,params:p,timeframe:tf}=b,count=upper(this.ends[tf],now);if(!count||this.processed[id]===count)continue;this.processed[id]=count;
        const bars=this.series[tf],current=bars[count-1],stamp=current.start+tf*60000,state=this.states[id]||(this.states[id]={});let value=null,detail='';
        if(kind==='opening_range'){const offset=Number(C.clock(current.start).slice(0,2))*60+Number(C.clock(current.start).slice(3))-525,anchor=current.start-offset*60000,end=anchor+(p.minutes??5)*60000;if(stamp>=end){const left=upper(this.ends[tf],anchor),right=upper(this.ends[tf],end),rows=bars.slice(left,right);if(rows.length*tf===(p.minutes??5)&&rows[0].start===anchor&&rows.at(-1).start+tf*60000===end)value={high:Math.max(...rows.map(x=>x.high)),low:Math.min(...rows.map(x=>x.low))};}}
        else if(kind==='snapshot'){const trigger=this.values[p.trigger],source=this.values[p.source],day=C.date(stamp);if(state.day!==day){delete state.level;state.day=day;}if(trigger?.value&&trigger.at===stamp&&source?.value)state.level={...source.value};value=state.level??null;}
        else if(kind==='ma'||kind==='rolling_range'){const n=p.period??20,end=kind==='ma'?count:count-1,rows=bars.slice(Math.max(0,end-n),end);if(rows.length===n)value=kind==='ma'?{value:rows.reduce((a,x)=>a+x.close,0)/n}:{high:Math.max(...rows.map(x=>x.high)),low:Math.min(...rows.map(x=>x.low))};}
        else if(kind==='swing'){const left=p.left??2,right=p.right??2,i=count-1-right;value={...(state.levels||{})};if(i>=left){const pivot=bars[i],neighbors=bars.slice(i-left,i).concat(bars.slice(i+1,i+right+1));if(neighbors.every(x=>pivot.high>x.high))value.high=pivot.high;if(neighbors.every(x=>pivot.low<x.low))value.low=pivot.low;state.levels=value;}if(!Object.keys(value).length)value=null;}
        else{let truth=false;
          if(['breakout','compare','retest'].includes(kind)){const source=this.values[p.source],level=source?.value?.[p.field??'high'];if(level!=null){const up=(p.direction??'up')==='up';detail=`收盤 ${current.close}，參考 ${p.source}.${p.field??'high'}=${level}，方向 ${p.direction??'up'}`;
            if(kind==='breakout'){const prev=count>=2?bars[count-2]:null;truth=!!prev&&(up?prev.close<=level&&level<current.close:prev.close>=level&&level>current.close);}
            else if(kind==='compare')truth=up?current.close>level:current.close<level;
            else{const tol=p.tolerance??2;detail+=`，高低區間 ${current.low}–${current.high}，容許 ${tol} 點`;truth=current.low<=level+tol&&current.high>=level-tol&&(up?current.close>level:current.close<level);}
          }}else if(kind==='candle'){truth=(p.direction??'up')==='up'?current.close>current.open:current.close<current.open;detail=`開盤 ${current.open}，收盤 ${current.close}`;}
          else if(['and','or','sequence'].includes(kind)){const inputs=p.inputs.map(dep=>this.values[dep]),flags=inputs.map(v=>!!(v&&v.value&&C.date(v.at)===C.date(stamp)));detail=p.inputs.map((dep,i)=>`${dep}=${flags[i]?'True':'False'}`).join(', ');
            if(kind==='and')truth=flags.every(Boolean);else if(kind==='or')truth=flags.some(Boolean);
            else{const [a,other]=inputs;let armed=state.armed??null;if(armed!=null&&(C.date(armed)!==C.date(stamp)||stamp-armed>(p.within??30)*60000))armed=null;if(flags[0]&&state.used_a!==a.at){armed=a.at;state.used_a=a.at;}if(armed!=null&&flags[1]&&other.at>armed){truth=true;detail=`A=${p.inputs[0]} 於 ${C.iso(armed)}；B=${p.inputs[1]} 於 ${C.iso(other.at)}`;armed=null;}state.armed=armed;}
          }else if(kind==='event'){const src=this.values[p.source],active=!!(src&&src.value&&C.date(src.at)===C.date(stamp));truth=active&&!state.active;state.active=active;detail=`來源 ${p.source} 由不成立轉為成立`;}
          value=truth;
        }
        this.values[id]={value,at:stamp,block_id:id,reason:`${b.name} (${id})：${value===true?'True':value===false?'False':JSON.stringify(value)}`+(detail?'；'+detail:'')};
      }return this.values;
    }
  }
  function metrics(trades,equity,capital){
    const wins=trades.filter(t=>t.net_pnl>0).map(t=>t.net_pnl),losses=trades.filter(t=>t.net_pnl<0).map(t=>t.net_pnl),profit=wins.reduce((a,b)=>a+b,0),loss=-losses.reduce((a,b)=>a+b,0);let peak=capital,drawdown=0,pct=0,streak=0,longest=0;const monthly={};
    for(const p of equity){peak=Math.max(peak,p.equity);drawdown=Math.max(drawdown,peak-p.equity);pct=Math.max(pct,peak>0?(peak-p.equity)/peak:0);}
    for(const t of trades){streak=t.net_pnl<0?streak+1:0;longest=Math.max(longest,streak);const month=t.exit_time.slice(0,7);monthly[month]=(monthly[month]||0)+t.net_pnl;}
    const net=trades.reduce((a,t)=>a+t.net_pnl,0);return {trade_count:trades.length,long_count:trades.filter(t=>t.side==='long').length,short_count:trades.filter(t=>t.side==='short').length,win_rate:trades.length?wins.length/trades.length:0,gross_profit:profit,gross_loss:loss,net_pnl:net,average_pnl:trades.length?net/trades.length:0,average_win:wins.length?profit/wins.length:0,average_loss:losses.length?-loss/losses.length:0,profit_factor:loss?profit/loss:null,profit_factor_note:loss?'':'無虧損；獲利因子無有限值',max_drawdown:drawdown,max_drawdown_pct:pct,longest_loss_streak:longest,monthly_pnl:monthly,final_equity:capital+net,total_cost:trades.reduce((a,t)=>a+t.cost,0),total_slippage_cost:trades.reduce((a,t)=>a+t.slippage_cost,0)};
  }
  function run(bars,s,settings={},progress=()=>{}){
    validate(s);const start=settings.start||'0000-01-01',end=settings.end||'9999-12-31';if(start>end)throw Error('開始日期不可晚於結束日期');
    const series={1:aggregate(bars,1),5:aggregate(bars,5),15:aggregate(bars,15)},minutes=series[1],evaluator=new Evaluator(s,series),costs=s.costs,risk=s.risk,limits=s.limits,capital=costs.initial_capital;
    let realized=0,position=null,pending=null;const trades=[],signals=[],equity=[],warnings=[],used=new Set(),daily=new Map(),last=new Map();for(const b of minutes)last.set(C.date(b.start),b);
    const fee=p=>({commission:costs.commission,tax:costs.tax_mode==='notional'?p*costs.point_value*costs.tax_rate:costs.tax_fixed}),sum=f=>f.commission+f.tax,fill=(raw,d,entering)=>raw+costs.slippage*d*(entering?1:-1),eventId=(id,at)=>sha256(canonical([s.strategy_id,s.version,id,C.iso(at)])).slice(0,24);
    function close(raw,at,reason,ambiguous=false,precision='bar_open'){const p=position,price=fill(raw,p.direction,false),exitFee=fee(price),gross=(price-p.entry_price)*p.direction*costs.point_value,total=sum(p.entry_fee)+sum(exitFee),net=gross-total;realized+=net;trades.push({...p,entry_time:C.iso(p.entry_time),exit_time:C.iso(at),exit_price:price,raw_exit_price:raw,exit_fee:exitFee,cost:total,slippage_cost:2*costs.slippage*costs.point_value,gross_pnl:gross,net_pnl:net,exit_reason:reason,ambiguous_order:ambiguous,exit_time_precision:precision,equity_after:capital+realized});position=null;}
    for(let index=0;index<minutes.length;index++){
      const b=minutes[index],today=C.date(b.start),at=b.start+60000,inRange=start<=today&&today<=end;let exited=false;
      if(index%10000===0)progress(index,minutes.length);
      if(inRange&&pending){if(pending.day===today){if(pending.kind==='exit'&&position){close(b.open,b.start,pending.reason);exited=true;}else if(pending.kind==='entry'&&!position&&limits.entry_start<=C.clock(b.start)&&C.clock(b.start)<limits.entry_end){const d=pending.direction,price=fill(b.open,d,true);let stop=risk.stop_points?price-d*risk.stop_points:null;if(risk.structure_source)stop=pending.structure_stop;
          if(stop!=null&&(price-stop)*d<=0)warnings.push(`${C.iso(b.start)}：跳空後結構停損位無效，取消進場`);
          else if(risk.structure_source&&stop==null)warnings.push(`${C.iso(b.start)}：結構停損位尚未確認，取消進場`);
          else{position={side:d===1?'long':'short',direction:d,quantity:1,entry_time:b.start,entry_price:price,raw_entry_price:b.open,entry_fee:fee(price),stop,target:risk.target_points?price+d*risk.target_points:null,entry_reason:pending.reason,signal_id:pending.signal_id,strategy_id:s.strategy_id,strategy_version:s.version};daily.set(today,(daily.get(today)||0)+1);}
      } }pending=null;}
      if(inRange&&position){const {direction:d,stop,target}=position,stopHit=stop!=null&&(d===1?b.low<=stop:b.high>=stop),targetHit=target!=null&&(d===1?b.high>=target:b.low<=target);if(stopHit){const gap=d===1?b.open<=stop:b.open>=stop;close(gap?b.open:stop,b.start,gap?'跳空停損':'固定／結構停損',targetHit,gap?'bar_open':'within_1m_bar');exited=true;}else if(targetHit){close(target,b.start,'觸價停利',false,'within_1m_bar');exited=true;}}
      const values=evaluator.step(at);if(!inRange)continue;
      for(const [id,v] of Object.entries(values))if(v.at===at&&v.value===true)signals.push({event_id:eventId(id,at),trigger_time:C.iso(at),strategy_version:s.version,strategy_id:s.strategy_id,block_id:id,reason:v.reason});
      if(last.get(today)===b){pending=null;if(position){close(b.close,at,'日盤結束強制平倉（資料不足時使用當日末棒）',false,'bar_close');exited=true;}}
      else if(position){const id=s.exits[position.side],signal=values[id];if(signal?.value===true&&signal.at===at)pending={kind:'exit',day:today,reason:signal.reason};}
      else if(!exited&&(daily.get(today)||0)<limits.max_trades_per_day){const candidates=[];for(const [side,d] of [['long',1],['short',-1]]){const id=s.entries[side],signal=values[id];if(signal?.value!==true||signal.at!==at)continue;const key=id+'|'+at;if(used.has(key))continue;used.add(key);if(!(limits.entry_start<=C.clock(at)&&C.clock(at)<limits.entry_end))continue;const source=values[risk.structure_source],level=source?.value?.[d===1?'low':'high']??null;candidates.push({kind:'entry',day:today,direction:d,reason:signal.reason,structure_stop:level,signal_id:eventId(id,at)});}if(candidates.length===1)pending=candidates[0];else if(candidates.length>1)warnings.push(`${C.iso(at)}：多空同時成立，保守略過`);}
      let liquidation=0;if(position){const mark=fill(b.close,position.direction,false);liquidation=(mark-position.entry_price)*position.direction*costs.point_value-sum(position.entry_fee)-sum(fee(mark));}equity.push({time:C.iso(at),equity:capital+realized+liquidation});
    }
    if(!equity.length)throw Error('所選日期範圍沒有可回測的日盤 1 分 K');
    return {engine_version:'1.0.0-browser',strategy:clone(s),settings:clone(settings),trades,signals,equity,warnings,assumptions:['台灣時間、日盤 08:45–13:45、單口且不跨日','同棒停損優先；盤中觸價僅知所在分鐘，不推估秒數','資金曲線以每分鐘收盤淨清算值計算，未含分鐘內最差浮虧','週末排除；未內建交易所假日與特殊交易日行事曆','成本預設為使用者可修改的模擬值，並非最新實際費率'],metrics:metrics(trades,equity,capital)};
  }
  scope.NakedEngine={canonical,versionIdentity,sha256,validate,aggregate,Evaluator,metrics,run};
})(typeof self!=='undefined'?self:globalThis);
