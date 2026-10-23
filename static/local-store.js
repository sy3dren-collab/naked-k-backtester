/* Standalone browser persistence. The Windows server continues to use SQLite. */
(function(scope){
  'use strict';
  function createAPI(templates,progress=()=>{}){
    const C=scope.NakedCSV,E=scope.NakedEngine,mem={datasets:new Map(),data:new Map(),strategies:new Map(),runs:new Map(),results:new Map()};
    let db=null,storageMode='session',cached=null;
    const ready=new Promise(resolve=>{
      try{const request=indexedDB.open('naked-k-lab-browser-v1',1);request.onupgradeneeded=()=>{for(const name of Object.keys(mem))if(!request.result.objectStoreNames.contains(name))request.result.createObjectStore(name,{keyPath:'id'});};request.onsuccess=()=>{db=request.result;storageMode='persistent';resolve();};request.onerror=()=>resolve();request.onblocked=()=>resolve();}catch(_){resolve();}
    });
    const operation=(store,method,key)=>new Promise((resolve,reject)=>{try{const tx=db.transaction(store,'readonly'),request=tx.objectStore(store)[method](key);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);}catch(e){reject(e);}});
    async function get(store,id){if(mem[store].has(id))return mem[store].get(id);return db?operation(store,'get',id):undefined;}
    async function list(store){const persisted=db?await operation(store,'getAll'):[];const combined=new Map(persisted.map(x=>[x.id,x]));for(const [id,row]of mem[store])combined.set(id,row);return [...combined.values()].reverse();}
    async function write(records){
      if(db){try{await new Promise((resolve,reject)=>{const tx=db.transaction([...new Set(records.map(r=>r[0]))],'readwrite');for(const [store,value]of records)tx.objectStore(store).put(value);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});return;}catch(_){storageMode='session';}}
      for(const [store,value]of records)mem[store].set(value.id,value);
    }
    async function saveStrategy(strategy){E.validate(strategy);const id=JSON.stringify([strategy.strategy_id,String(strategy.version)]),old=await get('strategies',id);if(old&&E.versionIdentity(old.document)!==E.versionIdentity(strategy))throw Error('相同策略 ID／版本已有不同內容；請增加版本號以保留可重現性');if(!old)await write([['strategies',{id,document:strategy}]]);}
    return async function request(path,body){
      await ready;let value;
      if(path==='templates')value=templates;
      else if(path==='datasets')value=await list('datasets');
      else if(path==='strategies'&&body){await saveStrategy(body.strategy);value={status:'saved',storage_mode:storageMode};}
      else if(path==='strategies')value=(await list('strategies')).map(x=>x.document);
      else if(path==='import'){
        if(typeof body.csv!=='string')throw Error('CSV 必須為文字');
        progress('import');
        const columns=C.columns(body.csv),mapping=body.mapping||C.guess(columns.map(c=>c.key),columns.map(c=>c.name)),parsed=C.parse(body.csv,mapping),id=E.sha256(body.csv+'\0'+E.canonical(mapping)+'\0'+C.PARSER_VERSION);
        parsed.report.source_encoding=mapping._source_encoding||'utf-8';
        const row={id,name:body.name||'import.csv',report:parsed.report,first:parsed.bars.length?C.iso(parsed.bars[0].start):null,last:parsed.bars.length?C.iso(parsed.bars.at(-1).start):null};
        await write([['datasets',row],['data',{id,csv:body.csv,mapping}]]);cached={id,bars:parsed.bars};value={...row,storage_mode:storageMode};
      }
      else if(path==='run'){
        const dataset=await get('datasets',body.dataset_id);if(!dataset)throw Error('找不到匯入資料');if(dataset.report.errors.length)throw Error('資料檢查有錯誤：'+dataset.report.errors[0]);
        if(!cached||cached.id!==dataset.id){const raw=await get('data',dataset.id);if(!raw)throw Error('找不到行情內容，請重新匯入 CSV');cached={id:dataset.id,bars:C.parse(raw.csv,raw.mapping).bars};}
        const settings=body.settings||{};if(Object.keys(settings).some(k=>!['start','end'].includes(k)))throw Error('回測設定只支援 start/end 日期');
        await saveStrategy(body.strategy);
        const result=E.run(cached.bars,body.strategy,settings,(done,total)=>progress('run',done,total));result.data_report=dataset.report;
        const id=E.sha256(E.canonical([result.engine_version,dataset.id,body.strategy,settings]));
        await write([['results',{id,result}],['runs',{id,dataset_id:dataset.id,strategy_id:body.strategy.strategy_id,strategy_version:body.strategy.version,settings,metrics:result.metrics}]]);
        value={id,...result,storage_mode:storageMode};
      }
      else if(path==='runs')value=await list('runs');
      else if(path.startsWith('runs/')){const row=await get('results',path.slice(5));if(!row)throw Error('找不到回測結果');value={id:row.id,...row.result,storage_mode:storageMode};}
      else throw Error('找不到操作：'+path);
      return value;
    };
  }
  scope.NakedLocal={createAPI};
})(typeof self!=='undefined'?self:globalThis);
