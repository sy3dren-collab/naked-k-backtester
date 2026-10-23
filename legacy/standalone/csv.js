/* CSV decoding and validation shared by the server UI and standalone worker. */
(function(scope){
  'use strict';
  const PARSER_VERSION='1.1.0';
  const aliases={datetime:['datetime','timestamp','date time','日期時間','日期時間戳記','時間戳記','交易時間','時間'],date:['date','日期','交易日期'],time:['time','時間','交易時刻'],open:['open','開盤','開盤價'],high:['high','最高','最高價'],low:['low','最低','最低價'],close:['close','收盤','收盤價'],volume:['volume','vol','成交量','交易量','總成交量'],contract:['contract','symbol','合約','商品合約','合約月份','契約'],source:['source','資料來源','來源']};
  const normalize=s=>String(s).trim().toLowerCase().replace(/[\s_\-()（）]/g,'');
  function decode(buffer, encoding='auto') {
    const bytes=new Uint8Array(buffer);
    let selected=encoding;
    if(selected==='auto'){
      if(bytes[0]===255&&bytes[1]===254)selected='utf-16le';
      else if(bytes[0]===254&&bytes[1]===255)selected='utf-16be';
      else{try{new TextDecoder('utf-8',{fatal:true}).decode(bytes);selected='utf-8';}catch(_){selected='big5';}}
    }
    let text;
    try{text=new TextDecoder(selected,{fatal:true}).decode(bytes).replace(/^\uFEFF/,'');}
    catch(_){throw Error(`無法以 ${selected} 解碼，請切換 CSV 編碼，或另存成 UTF-8 CSV。`);}
    if(text.includes('\uFFFD'))throw Error('檔案已含有替代字元「�」，請回到原始檔重新匯出，或選擇正確編碼。');
    return {text,encoding:selected};
  }
  function delimiter(text){const first=text.replace(/^\uFEFF/,'').split(/\r?\n/,1)[0];let best=',',count=-1;for(const d of [',','\t',';']){let n=0,q=false;for(let i=0;i<first.length;i++){if(first[i]==='"'){if(q&&first[i+1]==='"')i++;else q=!q;}else if(!q&&first[i]===d)n++;}if(n>count){count=n;best=d;}}return best;}
  function* rows(text, separator=delimiter(text)) {
    let row=[],field='',quoted=false;
    text=text.replace(/^\uFEFF/,'');
    for(let i=0;i<text.length;i++){
      const c=text[i];
      if(c==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else if(quoted||field==='')quoted=!quoted;else throw Error('CSV 引號位置錯誤');}
      else if(c===separator&&!quoted){row.push(field);field='';}
      else if((c==='\n'||c==='\r')&&!quoted){row.push(field);if(row.some(x=>x!==''))yield row;row=[];field='';if(c==='\r'&&text[i+1]==='\n')i++;}
      else field+=c;
    }
    if(quoted)throw Error('CSV 有未閉合的雙引號');
    row.push(field);if(row.some(x=>x!==''))yield row;
  }
  function columnKeys(names){
    const counts=new Map(),reserved=new Set(names),used=new Set();for(const name of names)counts.set(name,(counts.get(name)||0)+1);
    return names.map((name,index)=>{const renamed=!name.trim()||counts.get(name)>1;let key=renamed?`${name.trim()?name:'未命名欄位'} [第 ${index+1} 欄]`:name;if(renamed)while(reserved.has(key)||used.has(key))key+='#';used.add(key);return {key,name,column:index+1,renamed};});
  }
  function columns(text){return columnKeys(rows(text).next().value||[]);}
  function headers(text){return columns(text).map(c=>c.key);}
  function guess(headers,originals=headers){
    const matches=key=>headers.filter((h,i)=>aliases[key].some(a=>normalize(a)===normalize(originals[i])));
    const find=key=>{const candidates=matches(key);return candidates.length===1?candidates[0]:'';};
    const hasDate=matches('date').length>0;
    const mapping={datetime:hasDate?find('date'):find('datetime'),time:hasDate?find('time'):'',open:find('open'),high:find('high'),low:find('low'),close:find('close'),volume:find('volume'),contract:find('contract'),source:find('source')};
    return mapping;
  }
  function timestamp(value,timeValue=''){
    value=String(value).trim();timeValue=String(timeValue||'').trim();
    if(timeValue)value=value+' '+timeValue;
    let match=value.match(/^(\d{3,4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](.+))?$/);
    if(!match){const packed=value.match(/^(\d{7,8})(?:[ T](.+))?$/);if(packed){const d=packed[1],y=d.slice(0,-4);match=[value,y,d.slice(-4,-2),d.slice(-2),packed[2]];}}
    if(!match)throw Error('日期格式須為 YYYY-MM-DD、YYYY/MM/DD 或 YYYYMMDD，可另對應時間欄');
    let year=Number(match[1]),month=Number(match[2]),day=Number(match[3]);if(match[1].length===3)year+=1911;
    let clock=match[4]||'00:00';let offset=480;
    const zone=clock.match(/(Z|[+-]\d{2}:?\d{2})$/i);
    if(zone){clock=clock.slice(0,-zone[1].length);if(zone[1].toUpperCase()==='Z')offset=0;else{const z=zone[1].replace(':',''),h=Number(z.slice(1,3)),m=Number(z.slice(3,5));if(h>23||m>59)throw Error('時區偏移不合法');offset=(z[0]==='-'?-1:1)*(h*60+m);}}
    let t=clock.match(/^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/);
    if(!t){if(/^\d{4}$/.test(clock))t=[clock,clock.slice(0,2),clock.slice(2,4),'0'];else if(/^\d{6}$/.test(clock))t=[clock,clock.slice(0,2),clock.slice(2,4),clock.slice(4,6)];}
    if(!t)throw Error('時間格式須為 HH:MM[:SS]、HHMM 或 HHMMSS');
    const hour=Number(t[1]),minute=Number(t[2]),second=Number(t[3]||0);
    if(hour>23||minute>59||second!==0||(t[4]&&Number(t[4])!==0))throw Error('時間須為合法整分鐘');
    const local=Date.UTC(year,month-1,day,hour,minute),check=new Date(local);
    if(check.getUTCFullYear()!==year||check.getUTCMonth()!==month-1||check.getUTCDate()!==day)throw Error('日期不存在');
    return local-offset*60000;
  }
  const iso=ms=>new Date(ms+480*60000).toISOString().slice(0,19)+'+08:00';
  const date=ms=>iso(ms).slice(0,10);
  const clock=ms=>iso(ms).slice(11,16);
  const day=ms=>{const d=new Date(ms+480*60000);return d.getUTCDay()>0&&d.getUTCDay()<6&&clock(ms)>='08:45'&&clock(ms)<'13:45';};
  function number(raw){const text=String(raw??'').trim();if(text.includes(',')&&!/^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?(?:[eE][+-]?\d+)?$/.test(text))return NaN;const cleaned=text.replace(/,/g,'');return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(cleaned)?Number(cleaned):NaN;}
  function parse(text,mapping){
    const iterator=rows(text),originals=iterator.next().value||[],cols=columnKeys(originals),head=cols.map(c=>c.key);mapping=mapping||guess(head,originals);
    const report={parser_version:PARSER_VERSION,errors:[],warnings:[],missing_minutes:[],night_rows:0,outside_session_rows:0,volume_missing_rows:0,rows:0};
    report.columns=cols;if(cols.some(c=>c.renamed))report.warnings.push('重複或空白欄名已按原始欄位位置區分；同名必要欄位請手動對應，不需修改 CSV');
    const required=['datetime','open','high','low','close'];
    const absent=required.filter(k=>!mapping[k]||!head.includes(mapping[k]));
    if(absent.length){report.errors.push('請對應必要欄位：'+absent.join('、'));return {bars:[],report};}
    if(new Set(required.map(k=>mapping[k])).size!==required.length){report.errors.push('日期與 OHLC 必須對應不同欄位');return {bars:[],report};}
    const idx=Object.fromEntries(Object.entries(mapping).map(([k,v])=>[k,head.indexOf(v)]));
    const bars=[],seen=new Set(),daily=new Map();let previous=null,line=1;
    for(const row of iterator){line++;report.rows++;
      try{
        const start=timestamp(row[idx.datetime],idx.time>=0?row[idx.time]:'');
        const values=['open','high','low','close'].map(k=>number(row[idx[k]]));
        const [open,high,low,close]=values;
        if(!values.every(v=>Number.isFinite(v)&&v>0)||!(low<=Math.min(open,close)&&Math.max(open,close)<=high))throw Error('OHLC 非有限正值或高低價關係不合法');
        const raw=idx.volume>=0?String(row[idx.volume]??'').trim():'';const volume=raw===''?null:number(raw);
        if(volume!==null&&(!Number.isFinite(volume)||volume<0))throw Error('成交量不合法');
        if(volume===null)report.volume_missing_rows++;
        if(seen.has(start))report.errors.push(`第 ${line} 列：重複時間 ${iso(start)}`);
        if(previous!==null&&start<previous)report.errors.push(`第 ${line} 列：資料未按時間排序`);
        seen.add(start);previous=start;bars.push({start,open,high,low,close,volume,minutes:1});
        if(day(start)){const key=date(start);if(!daily.has(key))daily.set(key,new Set());daily.get(key).add(start);}
        else{report.outside_session_rows++;if(clock(start)>='15:00'||clock(start)<'05:00')report.night_rows++;}
      }catch(e){report.errors.push(`第 ${line} 列：${e.message}`);}
    }
    for(const [key,stamps] of daily){let first=Infinity,last=-Infinity;for(const stamp of stamps){first=Math.min(first,stamp);last=Math.max(last,stamp);}for(let cursor=first;cursor<=last;cursor+=60000)if(!stamps.has(cursor))report.missing_minutes.push(iso(cursor));if(clock(first)!=='08:45'||clock(last)!=='13:44')report.warnings.push(`${key}：非完整日盤，末筆 K 棒將作為當日強制平倉點`);}
    if(report.missing_minutes.length)report.warnings.push(`日盤缺棒 ${report.missing_minutes.length} 根；不補價，缺棒區間不合成高週期 K`);
    if(report.volume_missing_rows)report.warnings.push('部分或全部成交量缺漏；純價格策略仍可執行');
    if(report.outside_session_rows)report.warnings.push('非日盤資料保留，但 V1 不執行交易；未內建交易所假日行事曆');
    if(!bars.length)report.errors.push('CSV 沒有行情資料');
    return {bars,report};
  }
  scope.NakedCSV={PARSER_VERSION,decode,delimiter,rows,columns,headers,guess,timestamp,iso,date,clock,day,parse};
})(typeof self!=='undefined'?self:globalThis);
