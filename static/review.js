'use strict';
const replay={data:null,playing:false,timer:null,request:0,selected:null};
function stopReplay(){replay.playing=false;clearTimeout(replay.timer);$('review-play').textContent='▶ 播放';}
function localTime(iso){return iso?iso.slice(0,16):'';}
async function loadReview(at=null){
  if(!result?.id)throw Error('請先執行回測或從歷史紀錄選擇結果。');
  const request=++replay.request,params=new URLSearchParams({timeframe:$('review-tf').value,limit:innerWidth<760?'100':'260'});
  const chosen=at||($('review-at').value?$('review-at').value+':00+08:00':null);if(chosen)params.set('at',chosen);
  $('review-info').textContent='正在載入已完成的行情…';
  const data=await api('runs/'+result.id+'/review?'+params);
  if(request!==replay.request)return;
  replay.data=data;$('review-at').value=localTime(data.cursor);
  $('review-info').textContent=`${data.timeframe} 分 K · 游標 ${data.cursor||'無資料'} · 已完成 ${data.total_completed} / ${data.total} 根；紅漲白跌，成交量在下方。`;
  drawCandles(data);renderSelectedTrade();return data;
}
function drawCandles(data){
  const canvas=$('candles'),ctx=canvas.getContext('2d'),width=canvas.width,height=canvas.height;
  ctx.fillStyle='#101318';ctx.fillRect(0,0,width,height);
  const bars=data.bars;if(!bars.length){ctx.fillStyle='#a8b4c0';ctx.font='18px sans-serif';ctx.fillText('游標前尚無完成的 K 棒',40,60);return;}
  const margin=74,top=28,priceHeight=410,volumeTop=480,volumeHeight=75,plotWidth=width-margin-20,step=plotWidth/bars.length,candleWidth=Math.max(1,Math.min(12,step*.68));
  const times=bars.map(b=>Date.parse(b.start)),end=Date.parse(data.cursor),first=times[0];
  let low=Infinity,high=-Infinity,maxVolume=1;
  for(const b of bars){low=Math.min(low,b.low);high=Math.max(high,b.high);maxVolume=Math.max(maxVolume,b.volume||0);}
  const pad=Math.max((high-low)*.08,1);low-=pad;high+=pad;
  const y=value=>top+(high-value)/(high-low)*priceHeight;
  function x(at){const time=Date.parse(at);let i=0;while(i<times.length&&times[i]<time)i++;return margin+Math.min(i,bars.length)*step+step/2;}
  ctx.font='12px sans-serif';ctx.lineWidth=1;
  for(let i=0;i<6;i++){const value=low+(high-low)*i/5,pos=y(value);ctx.strokeStyle='#26323e';ctx.beginPath();ctx.moveTo(margin,pos);ctx.lineTo(width-20,pos);ctx.stroke();ctx.fillStyle='#8394a4';ctx.fillText(fmt(value,1),5,pos+4);}
  // Draw each overlay only from its actual confirmation time until its next update.
  const groups=new Map();for(const overlay of data.overlay_history||[]){if(!groups.has(overlay.block_id))groups.set(overlay.block_id,[]);groups.get(overlay.block_id).push(overlay);}
  for(const overlays of groups.values())for(let i=0;i<overlays.length;i++){
    const overlay=overlays[i],from=Math.max(margin,x(overlay.time)),to=i+1<overlays.length?Math.min(width-20,x(overlays[i+1].time)):width-20;
    if(from>=width-20||to<=from)continue;
    const colors={opening_range:'#ddb75d',support_resistance:'#669ccc',box:'#be8bde',swing:'#7acb95',ma:'#e1a36b',rolling_range:'#7f9e8c',gap:'#aaa85a',previous_day:'#9198af',day_range:'#7f9e8c'};
    ctx.strokeStyle=colors[overlay.type]||'#708b9d';ctx.globalAlpha=.7;ctx.setLineDash([5,4]);
    for(const key of ['high','low','value']){const value=overlay.value?.[key];if(typeof value!=='number')continue;ctx.beginPath();ctx.moveTo(from,y(value));ctx.lineTo(to,y(value));ctx.stroke();}
    if(['opening_range','support_resistance','box','gap'].includes(overlay.type)&&overlay.value?.high!=null&&overlay.value?.low!=null){ctx.fillStyle=ctx.strokeStyle;ctx.globalAlpha=.08;ctx.fillRect(from,y(overlay.value.high),to-from,y(overlay.value.low)-y(overlay.value.high));}
    ctx.globalAlpha=1;ctx.setLineDash([]);
  }
  for(const overlay of data.levels||[])for(const zone of overlay.meta?.zones||[]){
    if(!zone.confirmed_at||Date.parse(zone.confirmed_at)>end)continue;
    const from=Math.max(margin,x(zone.confirmed_at));if(from>=width-20)continue;
    ctx.fillStyle=zone.role==='support'?'#5ebc8c':'#bd89d5';ctx.globalAlpha=.13;ctx.fillRect(from,y(zone.high),width-20-from,Math.max(1,y(zone.low)-y(zone.high)));ctx.globalAlpha=.8;ctx.font='10px sans-serif';ctx.fillText((zone.role==='support'?'支撐':'壓力')+' '+zone.tests+' 次'+(zone.broken_at?' · 已突破':''),Math.min(from+4,width-150),y(zone.high)-4);ctx.globalAlpha=1;
  }
  for(let i=0;i<bars.length;i++){
    const b=bars[i],center=margin+(i+.5)*step,rising=b.close>=b.open,color=rising?'#ff555c':'#f0f2f5';ctx.strokeStyle=color;ctx.fillStyle=rising?color:'#101318';
    ctx.beginPath();ctx.moveTo(center,y(b.high));ctx.lineTo(center,y(b.low));ctx.stroke();const bodyTop=y(Math.max(b.open,b.close)),bodyHeight=Math.max(1,Math.abs(y(b.open)-y(b.close)));ctx.fillRect(center-candleWidth/2,bodyTop,candleWidth,bodyHeight);ctx.strokeRect(center-candleWidth/2,bodyTop,candleWidth,bodyHeight);
    if(b.volume!=null){const volume=b.volume/maxVolume*volumeHeight;ctx.globalAlpha=.65;ctx.fillStyle=color;ctx.fillRect(center-candleWidth/2,volumeTop+volumeHeight-volume,candleWidth,volume);ctx.globalAlpha=1;}
  }
  ctx.fillStyle='#8594a2';ctx.fillText('VOL',10,volumeTop+15);ctx.fillText(bars[0].start.slice(0,16).replace('T',' '),margin,height-17);ctx.textAlign='right';ctx.fillText(bars.at(-1).start.slice(0,16).replace('T',' '),width-20,height-17);ctx.textAlign='left';
  for(const updates of [data.protection||[]])for(let i=0;i<updates.length;i++){
    const u=updates[i],following=updates.slice(i+1).find(n=>n.position_id===u.position_id),trade=data.trades.find(t=>t.position_id===u.position_id),stopAt=following?.time||trade?.exit_time||data.cursor;
    if(Date.parse(stopAt)<first||Date.parse(u.time)>end)continue;const from=Math.max(margin,x(u.time)),to=Math.min(width-20,x(stopAt));ctx.setLineDash([3,3]);
    for(const [key,color]of [['stop','#e97b65'],['target','#69b7dc']])if(u[key]!=null){ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(from,y(u[key]));ctx.lineTo(to,y(u[key]));ctx.stroke();}ctx.setLineDash([]);
  }
  for(const trade of data.trades){for(const [at,price,label,color]of [[trade.entry_time,trade.entry_price,trade.side==='long'?'▲ 多':'▼ 空','#f1c456'],[trade.exit_time,trade.exit_price,'× 出','#64cbd3']]){
    if(!at||Date.parse(at)<first||Date.parse(at)>end)continue;const pos=x(at);if(pos>width-20)continue;ctx.fillStyle=color;ctx.font='bold 13px sans-serif';ctx.fillText(label,pos-10,y(price)-10);ctx.beginPath();ctx.arc(pos,y(price),3,0,Math.PI*2);ctx.fill();
  }}
  const drawn=new Set();for(const overlay of data.overlay_history||[])for(const pivot of overlay.meta?.pivots||[]){if(drawn.has(pivot.candidate_time+pivot.kind)||Date.parse(pivot.candidate_time)<first)continue;drawn.add(pivot.candidate_time+pivot.kind);ctx.fillStyle='#88cc95';ctx.font='11px sans-serif';ctx.fillText(pivot.kind==='high'?'H':'L',x(pivot.candidate_time)-3,y(pivot.price)+(pivot.kind==='high'?-20:22));}
}
function renderSelectedTrade(){
  const data=replay.data;if(!data)return;const trade=data.trades.find(t=>t.position_id===replay.selected)||data.trades.at(-1);
  $('review-trade').innerHTML=trade?`<div class="review-detail"><strong>第 ${trade.position_id||''} 筆 · ${trade.side==='long'?'多單':'空單'} ${trade.quantity} 口</strong><br>進場 ${esc(trade.entry_time)} @ ${fmt(trade.entry_price,2)} · 手續費 ${fmt(trade.entry_fee?.commission,2)}／交易稅 ${fmt(trade.entry_fee?.tax,2)}<br>${trade.exit_time?'出場 '+esc(trade.exit_time)+' @ '+fmt(trade.exit_price,2)+' · 淨損益 '+fmt(trade.net_pnl,2)+' · 出場手續費 '+fmt(trade.exit_fee?.commission,2)+'／交易稅 '+fmt(trade.exit_fee?.tax,2):'此游標尚未平倉；不提前顯示最終損益'}<br>${esc(trade.entry_reason)}${trade.exit_reason?'<br>'+esc(trade.exit_reason):''}${trade.entry_intrabar_uncertain?'<br>⚑ 觸價進場所在分鐘的價格路徑不確定':''}${trade.ambiguous_order?'<br>⚑ 同分鐘停損／停利順序不明，已採停損優先':''}</div>`:'<p class="hint">游標前尚無進場紀錄。</p>';
}
window.setupTradeReview=function(){
  stopReplay();replay.data=null;$('review-at').value='';
  $('trades').querySelectorAll('tr').forEach((row,i)=>{const trade=result.trades[tradePage*100+i];if(!trade)return;row.classList.add('review-link');row.tabIndex=0;row.title='點擊在 K 棒上檢討這筆交易';const open=()=>guard(async()=>{replay.selected=trade.position_id;tab('review');const at=new Date(Date.parse(trade.exit_time)+(trade.exit_time_precision==='within_1m_bar'?60000:0)+480*60000).toISOString().slice(0,19)+'+08:00';await loadReview(at);});row.onclick=open;row.onkeydown=e=>{if(e.key==='Enter')open();};});
};
const originalTrades=renderTrades;renderTrades=function(){originalTrades();if(window.setupTradeReview)window.setupTradeReview();};
document.querySelector('[data-tab="review"]').addEventListener('click',()=>guard(()=>loadReview()));
$('review-load').onclick=()=>guard(async()=>{stopReplay();await loadReview();});
$('review-tf').onchange=()=>guard(async()=>{stopReplay();await loadReview();});
$('review-prev').onclick=()=>guard(async()=>{stopReplay();if(!replay.data)await loadReview();if(replay.data.previous_time)await loadReview(replay.data.previous_time);});
$('review-next').onclick=()=>guard(async()=>{stopReplay();if(!replay.data)await loadReview();if(replay.data.next_time)await loadReview(replay.data.next_time);});
$('review-play').onclick=()=>guard(async()=>{
  if(replay.playing){stopReplay();return;}
  if(!replay.data)await loadReview();if(!replay.data.next_time)await loadReview(replay.data.first_time);
  replay.playing=true;$('review-play').textContent='Ⅱ 暫停';
  async function tick(){if(!replay.playing)return;if(!replay.data.next_time){stopReplay();return;}try{await loadReview(replay.data.next_time);}catch(error){stopReplay();message(error.message,true);return;}if(replay.playing)replay.timer=setTimeout(tick,450);}
  replay.timer=setTimeout(tick,450);
});
