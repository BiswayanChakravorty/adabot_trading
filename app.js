const S={data:null,asset:"Bitcoin",days:1,chart:null};
const $=s=>document.querySelector(s);
const money=(v,c="USD")=>v==null||!Number.isFinite(Number(v))?"—":new Intl.NumberFormat("en-US",{style:"currency",currency:c,maximumFractionDigits:Number(v)>=1000?0:4}).format(Number(v));
const pct=v=>v==null?"—":`${Number(v)>=0?"+":""}${Number(v).toFixed(2)}%`;
const tm=v=>v?new Date(v).toLocaleString([],{month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit"}):"—";
async function load(){const r=await fetch(`./dashboard_data.json?t=${Date.now()}`,{cache:"no-store"});if(!r.ok)throw Error("dashboard data is not published yet");S.data=await r.json();render();await chart()}
function render(){const d=S.data||{},rows=d.market_snapshot||[];$("#last-updated").textContent=d.generated_at?`Agent ${tm(d.generated_at)}`:"Agent awaiting first scan";rows.forEach(x=>{const e=$(`#ticker-${CSS.escape(x.asset)}`);if(e)e.textContent=money(x.price,"INR")});renderWatch(rows);renderSignal(d.latest_signal||{});renderStrategies(d.strategy_summary||{});$("#modules-list").innerHTML=(d.modules||[]).map(m=>`<div class="module"><div class="module-top"><span class="module-name">${m.name}</span><span class="module-state">${m.state}</span></div><p>${m.description}</p></div>`).join("");const rc=d.risk_config||{};$("#risk-capital").textContent=money(rc.total_capital_inr,"INR");$("#risk-trade").textContent=money(rc.per_trade_allocation_inr,"INR");$("#risk-target").textContent=`${(rc.target_profit_pct||0)*100}%`;$("#risk-max").textContent=`${(rc.max_risk_pct||0)*100}%`}
function renderStrategies(s){const box=$("#strategy-grid");if(!box)return;const ev=s.evaluations||{};box.innerHTML=Object.entries(ev).map(([asset,d])=>{const names=Object.entries(d.strategies||{}).map(([n,v])=>`<span class="${v==="BUY"?"strategy-buy":"strategy-wait"}">${n}: ${v}</span>`).join(" · ");return `<div class="strategy-card"><strong>${asset}</strong><div class="vote ${d.consensus==="BUY"?"strategy-buy":"strategy-wait"}">${d.consensus} · ${d.buy_votes}/${d.total_strategies}</div><div class="ind">RSI ${d.indicators?.rsi?.toFixed?.(1)??"—"} · EMA21 ${d.indicators?.ema21?.toFixed?.(2)??"—"}<br>${names}</div></div>`}).join("")||'<div class="muted">Strategy data will appear after the next hourly scan.</div>'}
function renderWatch(rows){const box=$("#watchlist-grid");box.innerHTML="";["Bitcoin","Ethereum","Solana","XRP","Dogecoin"].forEach(n=>{const r=rows.find(x=>x.asset===n);if(!r)return;const c=document.createElement("div");c.className="coin-card"+(S.asset===n?" selected":"");c.innerHTML=`<div><span class="coin-name">${n}</span><span class="coin-symbol">${{Bitcoin:"BTC",Ethereum:"ETH",Solana:"SOL",XRP:"XRP",Dogecoin:"DOGE"}[n]}</span></div><div class="coin-price">${money(r.price,"INR")}</div><div class="coin-change ${Number(r["24h_change_pct"])>=0?"up":"down"}">${pct(r["24h_change_pct"])} 24H</div>`;c.onclick=()=>select(n);box.appendChild(c)})}
function renderSignal(s){const buy=s.action==="BUY";$("#signal-title").textContent=buy?`BUY ${s.asset||""}`:"No trade";const b=$("#signal-badge");b.textContent=buy?"BUY":"SKIP";b.className="badge "+(buy?"buy":"skip");$("#signal-rationale").textContent=s.rationale||"No qualifying candidate was published in the latest scan.";$("#signal-entry").textContent=s.entry_price?money(s.entry_price,"INR"):"—";$("#signal-target").textContent=s.target_price?money(s.target_price,"INR"):"—";$("#signal-stop").textContent=s.stop_loss_price?money(s.stop_loss_price,"INR"):"—";$("#signal-rr").textContent=s.risk_reward_ratio?Number(s.risk_reward_ratio).toFixed(2):"—";$("#signal-observed").textContent=s.observed_price?money(s.observed_price,"INR"):"—";const h=S.data?.history||[];$("#history-body").innerHTML=h.slice().reverse().slice(0,24).map(x=>`<tr><td>${tm(x.timestamp)}</td><td>${x.asset||"—"}</td><td class="${x.action==="BUY"?"action-buy":"action-skip"}">${x.action||"SKIP"}</td><td>${x.entry_price?money(x.entry_price,"INR"):"—"}</td><td>${x.risk_reward_ratio?Number(x.risk_reward_ratio).toFixed(2):"—"}</td><td class="${x.status==="signal_passed"?"status-pass":""}">${String(x.status||"").replaceAll("_"," ")}</td></tr>`).join("")||'<tr><td colspan="6" class="empty">No scans published yet.</td></tr>'}
async function chart(){
  if(!window.LightweightCharts)return;
  $("#chart-status").textContent="Loading chart data…";
  try{
    const all=(S.data&&S.data.chart_history&&S.data.chart_history[S.asset])||[];
    const cutoff=Date.now()/1000-S.days*86400;
    let points=all.filter(x=>Number(x.time)>=cutoff).map(x=>({time:Number(x.time),value:Number(x.value)})).filter(x=>Number.isFinite(x.value));
    let source="Agent-published historical data";
    if(points.length<2){
      const ids={Bitcoin:"bitcoin",Ethereum:"ethereum",Solana:"solana",XRP:"ripple",Dogecoin:"dogecoin"};
      const r=await fetch(`https://api.coingecko.com/api/v3/coins/${ids[S.asset]}/market_chart?vs_currency=usd&days=${S.days}`,{cache:"no-store"});
      if(!r.ok)throw Error("CoinGecko chart request failed");
      const payload=await r.json();
      points=(payload.prices||[]).map(x=>({time:Math.floor(Number(x[0])/1000),value:Number(x[1])})).filter(x=>Number.isFinite(x.time)&&Number.isFinite(x.value));
      source="Live CoinGecko chart fallback";
    }
    draw(points);
    const a=points.at(-1),f=points[0];
    if(a)$("#live-price").textContent=money(a.value);
    if(a&&f){const ch=(a.value-f.value)/f.value*100;$("#price-change").textContent=pct(ch);$("#price-change").className=ch>=0?"up":"down"}
    $("#chart-status").textContent=points.length?source:"No chart history available";
  }catch(e){$("#chart-status").textContent="Chart data unavailable";draw([])}
}
function draw(p){const el=$("#chart");if(S.chart)S.chart.remove();S.chart=LightweightCharts.createChart(el,{layout:{background:{type:"solid",color:"transparent"},textColor:"#7f8b9b"},grid:{vertLines:{color:"#141b24"},horzLines:{color:"#141b24"}},rightPriceScale:{borderColor:"#202a37"},timeScale:{borderColor:"#202a37",timeVisible:true},crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});const line=S.chart.addSeries(LightweightCharts.LineSeries,{color:"#20d69a",lineWidth:2});line.setData(p);S.chart.timeScale().fitContent()}
function select(a){S.asset=a;document.querySelectorAll(".asset-chip").forEach(b=>b.classList.toggle("active",b.dataset.asset===a));$("#asset-name").textContent=a;renderWatch(S.data.market_snapshot||[]);chart()}
document.querySelectorAll(".asset-chip").forEach(b=>b.onclick=()=>select(b.dataset.asset));document.querySelectorAll(".tf").forEach(b=>b.onclick=()=>{S.days=Number(b.dataset.days);document.querySelectorAll(".tf").forEach(x=>x.classList.toggle("active",x===b));chart()});$("#refresh-btn").onclick=()=>load().catch(e=>{$("#last-updated").textContent=e.message});load().catch(e=>{$("#last-updated").textContent=e.message;$("#chart-status").textContent="Waiting for first agent snapshot"});setInterval(()=>load().catch(()=>{}),300000);