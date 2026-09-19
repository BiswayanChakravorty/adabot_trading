const CONFIG={
  assets:{
    Bitcoin:{symbol:"BTCUSDT",tv:"BINANCE:BTCUSDT"},
    Ethereum:{symbol:"ETHUSDT",tv:"BINANCE:ETHUSDT"},
    Solana:{symbol:"SOLUSDT",tv:"BINANCE:SOLUSDT"},
    XRP:{symbol:"XRPUSDT",tv:"BINANCE:XRPUSDT"},
    Dogecoin:{symbol:"DOGEUSDT",tv:"BINANCE:DOGEUSDT"}
  },
  order:["Bitcoin","Ethereum","Solana","XRP","Dogecoin"],
  api:"https://data-api.binance.vision/api/v3",
  stream:"wss://data-stream.binance.vision:443/stream"
};

const S={data:null,asset:"Bitcoin",candles:{},results:{},socket:null,reconnectTimer:null,scanRunning:false,lastScanAt:null,lastNotificationKey:localStorage.getItem("adabot-last-notification")||""};
const $=s=>document.querySelector(s);
const money=(v,c="USD")=>v==null||!Number.isFinite(Number(v))?"—":new Intl.NumberFormat("en-US",{style:"currency",currency:c,maximumFractionDigits:Number(v)>=1000?0:4}).format(Number(v));
const price=v=>v==null||!Number.isFinite(Number(v))?"—":Number(v)>=1000?Number(v).toLocaleString("en-US",{maximumFractionDigits:2}):Number(v)>=1?Number(v).toLocaleString("en-US",{maximumFractionDigits:4}):Number(v).toLocaleString("en-US",{maximumFractionDigits:6});
const tm=v=>v?new Date(v).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",second:"2-digit"}):"—";
const escapeHtml=v=>String(v??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));
function setText(id,value){const el=$("#"+id);if(el)el.textContent=value??"—"}

function tvConfig(symbol){return{
  autosize:true,symbol:symbol,interval:"1",timezone:"exchange",theme:"dark",style:"1",locale:"en",
  allow_symbol_change:true,hide_side_toolbar:false,hide_top_toolbar:false,hide_legend:false,hide_volume:false,
  withdateranges:true,save_image:true,details:true,hotlist:false,calendar:false,
  studies:["Volume@tv-basicstudies","MASimple@tv-basicstudies","RSI@tv-basicstudies","MACD@tv-basicstudies","BB@tv-basicstudies"],
  watchlist:["BINANCE:BTCUSDT","BINANCE:ETHUSDT","BINANCE:SOLUSDT","BINANCE:XRPUSDT","BINANCE:DOGEUSDT"],
  support_host:"https://www.tradingview.com"
}}

function loadTradingView(){
  const host=$("#tradingview_chart");if(!host)return;
  host.innerHTML="";
  const wrap=document.createElement("div");wrap.className="tradingview-widget-container";wrap.style.cssText="height:100%;width:100%";
  const inner=document.createElement("div");inner.className="tradingview-widget-container__widget";inner.style.cssText="height:100%;width:100%";
  wrap.appendChild(inner);host.appendChild(wrap);
  const script=document.createElement("script");script.type="text/javascript";script.src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";script.async=true;
  script.innerHTML=JSON.stringify(tvConfig(CONFIG.assets[S.asset].tv));inner.appendChild(script);
}

function ema(values,period){
  if(values.length<period)return null;
  const k=2/(period+1);let e=values.slice(0,period).reduce((a,b)=>a+b,0)/period;
  for(let i=period;i<values.length;i++)e=values[i]*k+e*(1-k);return e;
}
function rsi(values,period=14){
  if(values.length<period+1)return null;
  let gain=0,loss=0;
  for(let i=1;i<=period;i++){const d=values[i]-values[i-1];if(d>=0)gain+=d;else loss-=d}
  gain/=period;loss/=period;
  for(let i=period+1;i<values.length;i++){const d=values[i]-values[i-1],g=Math.max(d,0),l=Math.max(-d,0);gain=(gain*(period-1)+g)/period;loss=(loss*(period-1)+l)/period}
  return loss===0?100:100-(100/(1+gain/loss));
}
function atr(candles,period=14){
  if(candles.length<period+1)return null;const tr=[];
  for(let i=1;i<candles.length;i++)tr.push(Math.max(candles[i].high-candles[i].low,Math.abs(candles[i].high-candles[i-1].close),Math.abs(candles[i].low-candles[i-1].close)));
  return tr.slice(-period).reduce((a,b)=>a+b,0)/period;
}
function macd(values){
  if(values.length<35)return null;
  const k12=2/13,k26=2/27,k9=2/10;let e12=values.slice(0,12).reduce((a,b)=>a+b,0)/12;let e26=values.slice(0,26).reduce((a,b)=>a+b,0)/26;const ms=[];
  for(let i=12;i<26;i++)e12=values[i]*k12+e12*(1-k12);
  for(let i=26;i<values.length;i++){e12=values[i]*k12+e12*(1-k12);e26=values[i]*k26+e26*(1-k26);ms.push(e12-e26)}
  if(ms.length<9)return null;let sig=ms.slice(0,9).reduce((a,b)=>a+b,0)/9;
  for(let i=9;i<ms.length;i++)sig=ms[i]*k9+sig*(1-k9);
  return{macd:ms.at(-1),signal:sig,hist:ms.at(-1)-sig};
}
function candlePattern(c){
  if(c.length<3)return"—";const a=c.at(-1),p=c.at(-2),body=Math.abs(a.close-a.open),range=Math.max(a.high-a.low,1e-12);
  const upper=a.high-Math.max(a.open,a.close),lower=Math.min(a.open,a.close)-a.low;
  if(body/range<.1)return"Doji";
  if(a.close>a.open&&p.close<p.open&&a.open<=p.close&&a.close>=p.open)return"Bullish engulfing";
  if(a.close<a.open&&p.close>p.open&&a.open>=p.close&&a.close<=p.open)return"Bearish engulfing";
  if(lower>body*2&&upper<body*1.2&&a.close>a.open)return"Hammer";
  if(upper>body*2&&lower<body*1.2&&a.close<a.open)return"Shooting star";
  return a.close>=a.open?"Bull candle":"Bear candle";
}
const average=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;

function analyze(name,candles){
  if(candles.length<60)throw Error("insufficient 1m candles");
  const closes=candles.map(x=>x.close),c=candles.at(-1),e9=ema(closes,9),e21=ema(closes,21),e50=ema(closes,50),R=rsi(closes),A=atr(candles),M=macd(closes);
  const avgVol=average(candles.slice(-21,-1).map(x=>x.volume)),vr=avgVol?c.volume/avgVol:1,prev20=candles.slice(-21,-1);
  const hi=Math.max(...prev20.map(x=>x.high)),lo=Math.min(...prev20.map(x=>x.low)),pattern=candlePattern(candles);
  let score=0,reasons=[];
  if(c.close>e9&&e9>e21&&e21>e50){score+=2;reasons.push("EMA trend bullish")}else if(c.close<e9&&e9<e21&&e21<e50){score-=2;reasons.push("EMA trend bearish")}else reasons.push("EMA structure mixed");
  if(R>=55&&R<=70){score++;reasons.push("RSI "+R.toFixed(1)+" bullish")}else if(R<=45&&R>=30){score--;reasons.push("RSI "+R.toFixed(1)+" bearish")}else if(R>70)reasons.push("RSI "+R.toFixed(1)+" overbought");else if(R<30)reasons.push("RSI "+R.toFixed(1)+" oversold");
  if(M&&M.hist>0){score++;reasons.push("MACD histogram positive")}else if(M&&M.hist<0){score--;reasons.push("MACD histogram negative")}
  if(vr>=1.2){if(c.close>=c.open){score++;reasons.push("volume "+vr.toFixed(1)+"x")}else{score--;reasons.push("selling volume "+vr.toFixed(1)+"x")}}
  if(c.close>hi){score++;reasons.push("20-bar breakout")}else if(c.close<lo){score--;reasons.push("20-bar breakdown")}
  if(["Bullish engulfing","Hammer"].includes(pattern)){score++;reasons.push(pattern)}else if(["Bearish engulfing","Shooting star"].includes(pattern)){score--;reasons.push(pattern)}
  const action=score>=4?"BUY":score<=-4?"SELL":"WATCH",risk=Math.max((A||c.close*.003)*1.5,c.close*.001),entry=c.close;
  return{asset:name,action,score,entry,target:action==="BUY"?entry+risk*2:action==="SELL"?entry-risk*2:null,stop:action==="BUY"?entry-risk:action==="SELL"?entry+risk:null,rr:action==="WATCH"?null:2,pattern,rsi:R,ema9:e9,ema21:e21,ema50:e50,macd:M?.macd??null,macdSignal:M?.signal??null,atr:A,volumeRatio:vr,closeTime:c.closeTime,rationale:reasons.slice(0,4).join(" • ")};
}

async function fetchKlines(name){
  const symbol=CONFIG.assets[name].symbol,r=await fetch(CONFIG.api+"/klines?symbol="+symbol+"&interval=1m&limit=240",{cache:"no-store"});
  if(!r.ok)throw Error(name+" market API "+r.status);const raw=await r.json();
  return raw.map(k=>({time:Number(k[0])/1000,open:Number(k[1]),high:Number(k[2]),low:Number(k[3]),close:Number(k[4]),volume:Number(k[5]),closeTime:Number(k[6])})).filter(k=>[k.time,k.open,k.high,k.low,k.close,k.volume].every(Number.isFinite));
}

async function scanAll(reason="scheduled"){
  if(S.scanRunning)return;S.scanRunning=true;setAgentState("SCANNING • ALL 5 COINS");
  const settled=await Promise.allSettled(CONFIG.order.map(async name=>({name,candles:await fetchKlines(name)}))),results={};let scanned=0;
  settled.forEach(r=>{if(r.status==="fulfilled"){const{name,candles}=r.value;S.candles[name]=candles;try{results[name]=analyze(name,candles);scanned++}catch(e){console.warn(e)}}});
  S.results=results;renderLiveBoard();const ranked=Object.values(results).sort((a,b)=>Math.abs(b.score)-Math.abs(a.score)||b.score-a.score),best=ranked[0];
  renderAgent(best,reason);renderWatch();updatePrices(results);S.lastScanAt=Date.now();setText("agent-scan-time",tm(S.lastScanAt));setText("scan-count",scanned+"/5 scanned • "+reason);setAgentState(scanned===5?"LIVE • 1-MINUTE SCANNER":"LIVE • PARTIAL MARKET DATA");S.scanRunning=false;
  if(best&&best.action!=="WATCH")notifyTrade(best);
}

function renderAgent(best,reason){
  const card=$("#agent-card");if(!best){setText("agent-headline","Market data unavailable");setText("agent-action","WATCH");setText("agent-coin","—");setText("agent-reason","The scanner could not obtain enough live candles.");return}
  const action=$("#agent-action"),cls=best.action==="BUY"?"buy":best.action==="SELL"?"sell":"watch";
  action.textContent=best.action;action.className="agent-action "+cls;setText("agent-headline",best.action==="WATCH"?"No qualifying trade":"Trade signal detected");setText("agent-coin",best.asset);
  setText("agent-reason",best.rationale+". Pattern: "+best.pattern+". "+(reason==="websocket"?"Closed 1m candle.":"Fresh 1m market scan."));
  setText("agent-entry",price(best.entry));setText("agent-target",best.target?price(best.target):"—");setText("agent-stop",best.stop?price(best.stop):"—");setText("agent-score",(best.score>0?"+":"")+best.score);setText("agent-rr",best.rr?best.rr.toFixed(1)+"R":"—");card.classList.toggle("alerting",best.action!=="WATCH");
}

function renderLiveBoard(){
  const box=$("#agent-board-grid");if(!box)return;
  box.innerHTML="";
  CONFIG.order.forEach(name=>{
    const r=S.results[name];
    const card=document.createElement("button");
    card.className="agent-mini "+(r?(r.action==="BUY"?"buy":r.action==="SELL"?"sell":"watch"):"loading");
    card.dataset.agentAsset=name;
    const top=document.createElement("div");top.className="mini-top";
    const n=document.createElement("b");n.textContent=name;
    const act=document.createElement("strong");act.textContent=r?r.action:"WAIT";
    top.append(n,act);
    const p=document.createElement("div");p.className="mini-price";p.textContent=r?price(r.entry):"—";
    const stats=document.createElement("div");stats.className="mini-stats";
    stats.textContent=r?"Score "+(r.score>0?"+":"")+r.score+" • RSI "+r.rsi.toFixed(1)+" • Vol "+r.volumeRatio.toFixed(1)+"x":"waiting for data…";
    const pattern=document.createElement("div");pattern.className="mini-pattern";pattern.textContent=r?r.pattern:"";
    card.append(top,p,stats,pattern);
    card.onclick=()=>select(name);
    box.appendChild(card);
  });
}

function updatePrices(results){
  Object.values(results).forEach(r=>{const el=$("#ticker-"+CSS.escape(r.asset));if(el)el.textContent=price(r.entry)});
  const active=results[S.asset];if(active){setText("live-price",money(active.entry));setText("price-change","RSI "+active.rsi.toFixed(1));$("#price-change").className=active.score>=0?"up":"down"}
}
function notifyTrade(signal){
  const key=signal.asset+":"+signal.action+":"+signal.closeTime;if(key===S.lastNotificationKey)return;
  S.lastNotificationKey=key;localStorage.setItem("adabot-last-notification",key);const title="AdaBot "+signal.action+": "+signal.asset,body=signal.asset+" "+signal.action+" • score "+signal.score+" • entry "+price(signal.entry);
  showToast(title,body);if("Notification"in window&&Notification.permission==="granted"){try{new Notification(title,{body:body,tag:"adabot-trade"})}catch(e){}}
}
async function enableNotifications(){
  if(!("Notification"in window)){showToast("Notifications unavailable","This browser does not expose the Notifications API.");return}
  const p=await Notification.requestPermission();$("#notify-btn").textContent=p==="granted"?"Notifications enabled":p==="denied"?"Notifications blocked":"Enable trade notifications";
  showToast(p==="granted"?"Notifications enabled":"Permission not granted",p==="granted"?"AdaBot will alert on new BUY/SELL signals.":"Change site notification settings in the browser.");
}
function showToast(title,body){const t=$("#toast");t.innerHTML="<b>"+escapeHtml(title)+"</b><span>"+escapeHtml(body)+"</span>";t.classList.add("show");clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>t.classList.remove("show"),7000)}
function setAgentState(v){setText("agent-state",v);setText("agent-top-label",v);setText("agent-top-time",new Date().toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}))}
function select(asset){if(!CONFIG.assets[asset])return;S.asset=asset;document.querySelectorAll(".asset-chip").forEach(b=>b.classList.toggle("active",b.dataset.asset===asset));setText("asset-name",asset);loadTradingView();renderWatch();updatePrices(S.results)}

function renderWatch(){
  const box=$("#watchlist-grid");if(!box)return;
  box.innerHTML=CONFIG.order.map(name=>{const r=S.results[name],selected=S.asset===name;return'<button class="coin-card '+(selected?"selected":"")+'" data-coin="'+name+'"><div><span class="coin-name">'+name+'</span><span class="coin-symbol">'+CONFIG.assets[name].symbol.replace("USDT","")+'</span></div><div class="coin-price">'+(r?money(r.entry):"—")+'</div><div class="coin-change '+(r?.score>=0?"up":"down")+'">'+(r?"Score "+(r.score>0?"+":"")+r.score:"Waiting")+'</div></button>'}).join("");
  box.querySelectorAll("[data-coin]").forEach(b=>b.onclick=()=>select(b.dataset.coin));
}

function renderServerData(){
  const d=S.data||{},rows=d.market_snapshot||[];setText("last-updated",d.generated_at?"Server "+tm(d.generated_at):"Server snapshot unavailable");
  rows.forEach(x=>{const e=$("#ticker-"+CSS.escape(x.asset));if(e)e.textContent=money(x.price,"INR")});renderWatch();renderStrategies(d.strategy_summary||{});
  const rc=d.risk_config||{};setText("risk-capital",money(rc.total_capital_inr,"INR"));setText("risk-trade",money(rc.per_trade_allocation_inr,"INR"));setText("risk-target",(rc.target_profit_pct||0)*100+"%");setText("risk-max",(rc.max_risk_pct||0)*100+"%");
  $("#live-modules").innerHTML=[
    ["Market stream","1-minute Binance kline stream across BTC/ETH/SOL/XRP/DOGE"],
    ["Technical engine","EMA 9/21/50 • RSI • MACD • ATR • volume ratio • breakout"],
    ["Pattern engine","Doji • engulfing • hammer • shooting star"],
    ["Signal ranker","Ranks all five markets and surfaces the strongest current setup"]
  ].map(x=>'<div class="module"><div class="module-top"><span class="module-name">'+x[0]+'</span><span class="module-state">LIVE</span></div><p>'+x[1]+'</p></div>').join("");
  const h=d.history||[];$("#history-body").innerHTML=h.slice().reverse().slice(0,24).map(x=>'<tr><td>'+tm(x.timestamp)+'</td><td>'+escapeHtml(x.asset||"—")+'</td><td class="'+(x.action==="BUY"?"action-buy":"")+'">'+(x.action||"SKIP")+'</td><td>'+(x.entry_price?money(x.entry_price,"INR"):"—")+'</td><td>'+(x.risk_reward_ratio?Number(x.risk_reward_ratio).toFixed(2):"—")+'</td><td>'+escapeHtml(String(x.status||"").replaceAll("_"," "))+'</td></tr>').join("")||'<tr><td colspan="6" class="empty">No server scans published yet.</td></tr>';
}
function renderStrategies(s){
  const box=$("#strategy-grid");if(!box)return;const ev=s.evaluations||{};
  box.innerHTML=Object.entries(ev).map(([asset,d])=>{const names=Object.entries(d.strategies||{}).map(([n,v])=>'<span class="'+(v==="BUY"?"strategy-buy":"strategy-wait")+'">'+n+": "+v+"</span>").join(" · ");
    return'<div class="strategy-card"><strong>'+asset+'</strong><div class="vote '+(d.consensus==="BUY"?"strategy-buy":"strategy-wait")+'">'+d.consensus+" · "+d.buy_votes+"/"+d.total_strategies+'</div><div class="ind">RSI '+(d.indicators?.rsi?.toFixed?.(1)??"—")+" · EMA21 "+(d.indicators?.ema21?.toFixed?.(2)??"—")+"<br>"+names+"</div></div>";
  }).join("")||'<div class="muted">Server strategy snapshot will appear after the next scheduled scan.</div>';
}

function connectStream(){
  if(S.socket){try{S.socket.close()}catch(e){}}
  const streams=CONFIG.order.map(n=>CONFIG.assets[n].symbol.toLowerCase()+"@kline_1m").join("/");
  try{S.socket=new WebSocket(CONFIG.stream+"?streams="+streams)}catch(e){scheduleReconnect();return}
  S.socket.onopen=()=>{setAgentState("LIVE • WEBSOCKET CONNECTED");scanAll("websocket")};
  S.socket.onmessage=event=>{try{
    const k=JSON.parse(event.data).data?.k;if(!k)return;const name=CONFIG.order.find(n=>CONFIG.assets[n].symbol===k.s);if(!name)return;
    const c={time:Number(k.t)/1000,open:Number(k.o),high:Number(k.h),low:Number(k.l),close:Number(k.c),volume:Number(k.v),closeTime:Number(k.T)},arr=S.candles[name]||[];
    if(arr.length&&arr.at(-1).time===c.time)arr[arr.length-1]=c;else arr.push(c);S.candles[name]=arr.slice(-300);if(k.x)scanAll("websocket");
  }catch(e){console.warn("stream parse",e)}};
  S.socket.onerror=()=>{setAgentState("STREAM ERROR • RECONNECTING");try{S.socket.close()}catch(e){}};
  S.socket.onclose=()=>scheduleReconnect();
}
function scheduleReconnect(){clearTimeout(S.reconnectTimer);S.reconnectTimer=setTimeout(()=>connectStream(),5000)}
async function loadServer(){try{const r=await fetch("./dashboard_data.json?t="+Date.now(),{cache:"no-store"});if(!r.ok)throw Error("server snapshot unavailable");S.data=await r.json();renderServerData()}catch(e){console.warn(e);setText("last-updated","Live browser agent active")}}

document.querySelectorAll(".asset-chip").forEach(b=>b.onclick=()=>select(b.dataset.asset));
$("#refresh-btn").onclick=()=>scanAll("manual");
$("#notify-btn").onclick=enableNotifications;
loadTradingView();loadServer();scanAll("startup");connectStream();
setInterval(()=>scanAll("fallback-minute"),60000);
setInterval(loadServer,300000);
setInterval(()=>{if(!S.socket||S.socket.readyState!==WebSocket.OPEN)connectStream()},15000);
