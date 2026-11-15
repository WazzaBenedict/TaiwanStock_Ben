/* ══════════════════════════════════════════════════════════════════
   V12.9.2 Multi-Portfolio Watchlist Manager
   Complete frontend JavaScript
   ══════════════════════════════════════════════════════════════════ */

function safeBind(id, evt, fn) {
  try { var el=document.getElementById(id); if(el) el.addEventListener(evt,fn); } catch(e){}
}

var FRONTEND_VERSION="15.2.1";
// 美股功能先收起來（程式碼保留）。要恢復請改成 true。
var ENABLE_US=false;

// ══ V13.2 交易成本：元大證券電子下單（全 App 共用，折扣可設定）══
function feeDisc(){try{var v=Number(localStorage.getItem("tw_fee_discount"));return v>0&&v<=1?v:0.6;}catch(e){return 0.6;}}
function feeQS(sep){return (sep||"&")+"fee_discount="+feeDisc();}
function initFeeSetting(){
  var i=$I("feeDiscIn"),b=$I("feeDiscBtn"),m=$I("feeDiscMsg"),tm=$I("tmDisc");
  if(i)i.value=feeDisc(); if(tm)tm.value=feeDisc();
  if(b&&!b.dataset.on){b.dataset.on="1";b.onclick=function(){var v=Number(i&&i.value);
    if(!(v>0&&v<=1)){if(m)m.textContent="請輸入 0.1～1 之間，例如 0.6 = 6 折";return;}
    try{localStorage.setItem("tw_fee_discount",String(v));}catch(e){}
    if(tm)tm.value=v; if(m)m.textContent="已儲存，之後的計算都用 "+(Math.round(v*1000)/100)+" 折";
    if(typeof CURRENT_ID!=="undefined"&&CURRENT_ID&&typeof loadTradePlanV2==="function")loadTradePlanV2(CURRENT_ID);};}
}
var RELEASE_NOTES=[
  "V15.2.1：手機上連點兩下不會再把畫面放大（兩指縮放仍可用），點輸入框也不會自動放大",
  "V15.2：團隊體檢與優化。打開更快（不再下載大型中文字型、腳本延後載入、後端提早喚醒）；回訪直接進總覽，自選股先顯示上次價格；個股 K 線圖修好、手機查詢後自動捲到結果；當沖總停損改成 10,000 元（帳本與風控都同步）；交易計畫建議股數不超過單筆上限 50,000 元；時光機的 ETF 改用 0.1% 證交稅；債券 ETF 免稅到 2026-12-31 後自動恢復課稅；當沖 5 檔在 19:00 用定稿收盤價重算；00631L 這類英文結尾的 ETF 可以查詢與加入自選；個股成交量少算 1000 倍的錯誤修正；持倉沒填目標或停損也能更新價格；帳本紀律檢查改用你在當沖風控存的上限；介面英文與用詞統一成中文（停損、偏多／觀察／避開），按鈕放大好點",
  "V15.1：每日報告自動匯入。交易日 06:50 的盤前報告與 13:45 的收盤總結會自動存進「報告」頁，保留最近 60 天；同時每天列出當沖 5 檔候選，收盤後自動對答案並累計模擬損益（已扣元大成本，屬模擬追蹤，不是買賣建議）",
  "V15.0：介面全面改版。拿掉英雄主題，換成簡潔的專業風格；手機底部只留總覽、當沖、個股、帳本四個常用分頁，其餘收在「更多」；首頁可以直接輸入代號查個股，常用功能一鍵到；換頁與數字有平順的動態（系統設定減少動態時會自動關閉）",
  "V14.3.2：研究室新增兩條選股規則，每天自動補資料並重新檢驗：「月營收加速前 10 名」與「跟投信買超前 5 名」。股票池是成交值前 150 檔，因為是事後挑的熱門股，這兩條改成要贏過「股票池平均」才算數，而且同一天進場的合併成一期計算。",
  "V14.3.1：研究室新增三條有文獻依據的規則（長期持有正2、正2 搭配 200 日線、高股息 ETF 除息前行情），並加上「外部研究怎麼說」十則證據摘要與「規則變動與複查日期」。持有類規則改用還原股利的價格比較。",
  "V14.3：「AI學習」改成「研究室」。每個交易日自動重算 8 條規則的評分表（當沖、隔夜、大跌後接、200 日線），全部扣元大成本並和 0050 比較，分成樣本內、樣本外、上線後三段；標籤（可用／研究中／未通過）由程式依固定門檻判定，變動會留下紀錄。",
  "V14.2.2：帳本匯入支援元大 App「資產總覽」的明細格式：只有股票名稱也能查到代號，並從「應收付」反推每筆實際手續費與交易稅；沒有成交時間的當沖不再被誤判成先賣後買。",
  "V14.2.1：總部新增「股癌紀律提醒」卡：把 Podcast 反覆出現的觀點整理成 10 條檢查清單，每天顯示一條；觀察名單有股票漲停、或大盤風險燈轉黃轉紅時，會自動換成對應的提醒。其中「漲停隔天開盤不要追」有回測支持，「抱緊創新高、連跌 5 天出場」回測未通過，所以只當提醒、不做成訊號。",
  "V14.2：新增「帳本」頁（取代原本的日誌分頁）。記錄真實成交後，自動扣元大手續費與交易稅算出淨損益，並和同一筆錢同期放在 0050 比較；附紀律檢查（每筆上限、每日與累計停損、13:00 後不進場、不先賣後買）和每週當沖獲利轉 0050 的結算。可手動輸入，也可匯入對帳單 CSV 或直接貼上表格。",
  "V14.1：總部最上方新增「今日」卡：每個交易日 06:50、13:45、19:00 自動更新，顯示今日結論、0050 開盤預估、大盤風險燈、隔夜行情、觀察名單、新聞，並累計開盤預估命中率。不必等後端喚醒；英雄的對話框會講當天的真實數字。",
  "V14.0.1：後端移除美股程式（少了約 830 行），系統檢查更快；觀察名單、權重、訊號歷史可備份到雲端，主機休眠後不再消失（需在 Render 設定金鑰後生效）。",
  "V14.0：地基整理。畫面與功能不變；網頁拆成獨立的樣式與腳本檔，移除舊版資料夾，之後合併到主線就會自動發布網頁，不必再開家用電腦。",
  "V13.3：⚡ 當沖 分頁新增「小資當沖風控（整張）」：下單前檢查每筆上限、股價 20～50、每日／總停損、13:00 後不進場，並提醒賣不掉時 T+2 要付的全額",
  "V13.2：交易成本改用元大證券電子下單：手續費 0.1425% × 6 折、整股每筆最低 20 元、零股最低 1 元、無條件捨去；證交稅 0.3%、當沖 0.15%、ETF 0.1%",
  "交易計畫卡、⚡ 當沖、台股時光機、個股回測、勝率統計全部改用同一套成本；首頁可改成你自己的手續費折扣",
  "個股回測與勝率之前沒扣成本，現在扣完手續費與證交稅後才算賺錢（數字會比以前保守）",
  "V13.0～13.1：首頁指揮中心、手機底部導覽列、美股功能先收起來、右上角版本號（當時的主題已在 V15 移除）"
];

function twNow(){
  var d=new Date();
  var parts={};
  try{new Intl.DateTimeFormat("en-GB",{timeZone:"Asia/Taipei",weekday:"short",hour:"2-digit",minute:"2-digit",hour12:false}).formatToParts(d).forEach(function(p){parts[p.type]=p.value;});}
  catch(e){var t=new Date(d.getTime()+(8*60+d.getTimezoneOffset())*60000);parts={weekday:["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][t.getDay()],hour:String(t.getHours()),minute:String(t.getMinutes())};}
  var h=parseInt(parts.hour,10)%24,m=parseInt(parts.minute,10);
  return {wd:parts.weekday,mins:h*60+m,label:(h<10?"0":"")+h+":"+(m<10?"0":"")+m};
}
function marketPhase(){
  var t=twNow(),wk=(t.wd==="Sat"||t.wd==="Sun");
  if(wk) return {key:"closed",label:"休市",t:t};
  if(t.mins<8*60+30) return {key:"pre",label:"盤前準備",t:t};
  if(t.mins<9*60) return {key:"open-soon",label:"即將開盤",t:t};
  if(t.mins<13*60+30) return {key:"live",label:"盤中",t:t};
  if(t.mins<14*60+30) return {key:"post",label:"收盤後",t:t};
  return {key:"night",label:"夜間",t:t};
}
var PHASE_BRIEF={
  "closed":"今天休市。適合整理帳本、複盤上週的交易，看看研究室哪些規則還站得住。",
  "pre":"盤前：先看今日報告與風險燈，再確認自選股的交易計畫（進場、停損、何時賣）。",
  "open-soon":"快開盤了。價位先抄好，09:15 後才看開盤區間突破，不追價。",
  "live":"盤中：照計畫的停損停利執行，13:00 後不再進場，當沖 13:25 前出場。",
  "post":"收盤了。把今天的成交記進帳本，檢查持倉停損。",
  "night":"夜間：適合複盤與準備明天，明早開盤前回來看今日報告。"
};
var HOME_ACTIONS=[
  {page:"p-reports",ic:"doc",t:"每日報告",d:"盤前、收盤與當沖 5 檔"},
  {page:"p-timemachine",ic:"bolt",t:"當沖候選",d:"今日進場、停損、停利價位"},
  {page:"p-ledger",ic:"book",t:"記一筆交易",d:"帳本：實際損益與紀律"},
  {page:"p-positions",ic:"shield",t:"檢查持倉",d:"損益與停損警示"},
  {page:"p-plans",ic:"target",t:"交易追蹤",d:"盯進場與出場價位"},
  {page:"p-learn",ic:"flask",t:"研究室",d:"哪些規則真的有效"}
];
function icon(n){return '<svg class="ic" aria-hidden="true"><use href="#i-'+n+'"/></svg>';}
function goHero(page,scrollId){
  showPage(page);
  if(scrollId){setTimeout(function(){var el=$I(scrollId);if(el)el.scrollIntoView({behavior:"smooth",block:"start"});},60);}
  else{try{window.scrollTo({top:0,behavior:"smooth"});}catch(e){window.scrollTo(0,0);}}
}
var NAV_SEC={"p-reports":1,"p-plans":1,"p-positions":1,"p-market":1,"p-learn":1,"p-account":1,"p-journal":1};
function navMore(open){
  var n=$I("mainNav"),b=$I("navMore"),sc=$I("navScrim");if(!n)return;
  if(open==null)open=!n.classList.contains("more-open");
  n.classList.toggle("more-open",open);if(sc)sc.classList.toggle("on",open);if(b)b.setAttribute("aria-expanded",open?"true":"false");
}
function navSync(pageId){
  var b=$I("navMore");if(b)b.classList.toggle("active",!!NAV_SEC[pageId]);
  navMore(false);
  var p=$I(pageId);if(p){p.classList.remove("enter");void p.offsetWidth;p.classList.add("enter");}
}
// 數字從 0 跑到目標值；只處理「+1.23%」這種單純的數字
function countUp(root){
  if(!root||(window.matchMedia&&matchMedia("(prefers-reduced-motion:reduce)").matches))return;
  root.querySelectorAll(".td-big span.up,.td-big span.down,[data-count]").forEach(function(el){
    var m=/^([+\-]?)(\d+(?:\.(\d+))?)(%?)$/.exec((el.textContent||"").trim());if(!m||el.__counted)return;el.__counted=1;
    var end=parseFloat(m[2]),dec=(m[3]||"").length,t0=null,final=el.textContent;
    function step(ts){if(t0==null)t0=ts;var k=Math.min(1,(ts-t0)/700),e=1-Math.pow(1-k,3);el.textContent=m[1]+(end*e).toFixed(dec)+m[4];if(k<1)requestAnimationFrame(step);else el.textContent=final;}
    requestAnimationFrame(step);
  });
}
function renderHQ(){
  var ph=marketPhase();
  var pe=$I("hqPhase");if(pe){pe.textContent=ph.label;pe.className="hm-phase"+(ph.key==="live"||ph.key==="open-soon"?" live":"");}
  var ce=$I("hqClock");if(ce)ce.textContent="台北 "+ph.t.label;
  var de=$I("hqDate");if(de){try{de.textContent=new Intl.DateTimeFormat("zh-TW",{timeZone:"Asia/Taipei",month:"long",day:"numeric",weekday:"long"}).format(new Date());}catch(e){}}
  var be=$I("hqBrief");if(be)be.textContent=(window.TODAY&&TODAY.conclusion)?TODAY.conclusion:(PHASE_BRIEF[ph.key]||"");
  var qk=$I("hqQuick");
  if(qk&&!qk.firstChild)qk.innerHTML=HOME_ACTIONS.map(function(m){return '<button class="hm-act" data-hq-go="'+m.page+'"><span class="hm-act-ic">'+icon(m.ic)+'</span><span class="hm-act-tx"><b>'+m.t+'</b><small>'+m.d+'</small></span>'+icon("chev")+'</button>';}).join("");
  initFeeSetting();
  var nl=$I("hqNotesList");if(nl&&!nl.firstChild)nl.innerHTML=RELEASE_NOTES.map(function(x){return "<li>"+x+"</li>";}).join("");
}
function applyFeatureFlags(){
  try{if(window.innerWidth<760){var hp=$I("systemHealthPanel"),hb=$I("btnHealthToggle");if(hp)hp.classList.add("compact");if(hb)hb.textContent="展開";}}catch(e){}
  document.querySelectorAll(".app-ver").forEach(function(e){e.textContent="V"+FRONTEND_VERSION;});
  if(!ENABLE_US){
    document.body.classList.add("no-us");
    var lm=$I("learnMarket");if(lm){var o=lm.querySelector('option[value="us"]');if(o)o.remove();lm.value="tw";}
    currentMarket="tw";
  }
}

document.addEventListener("click",function(e){
  var t=e.target&&e.target.closest?e.target:null;if(!t)return;
  if(t.closest("#navMore")){e.preventDefault();navMore();return;}
  if(t.closest("#navScrim")){navMore(false);return;}
  var g=t.closest("[data-hq-go]");
  if(g){e.preventDefault();goHero(g.getAttribute("data-hq-go"),g.getAttribute("data-hq-scroll"));}
});
document.addEventListener("keydown",function(e){
  if(e.key==="Escape"){navMore(false);return;}
  if(e.key!=="Enter"&&e.key!==" ")return;
  var g=e.target&&e.target.getAttribute&&e.target.getAttribute("role")==="button"&&e.target.hasAttribute("data-hq-go")?e.target:null;
  if(g){e.preventDefault();goHero(g.getAttribute("data-hq-go"),g.getAttribute("data-hq-scroll"));}
});
document.addEventListener("submit",function(e){
  if(!e.target||e.target.id!=="hmSearch")return;e.preventDefault();
  var v=($I("hmSid").value||"").trim();if(!v){$I("hmSid").focus();return;}
  showPage("p-trade");loadStock(v);$I("hmSid").value="";
});
setInterval(function(){var p=$I("p-hq");if(p&&p.classList.contains("active"))renderHQ();},60000);

var API = window.API_BASE_URL || "https://taiwanstock-ben-1.onrender.com";
var FB_CFG = window.FIREBASE_CONFIG || {};

// ── Global State ───────────────────────────────────────────────────
var currentUser = null, db = null, auth = null;
var currentMarket = "tw";
// TW state
var WL=[], WL_CACHE={}, CURRENT_ID=null, STOCK_DICT={};
var wlLeft=30, wlTimer=null, isRefreshWL=false, watchlistExpanded=false;
var autoOn=false, autoLeft=300, autoTimer=null;
// US state
var US_WL=[], US_WL_CACHE={}, US_CURRENT=null;
var usWlLeft=30, usWlTimer=null, usWlRefreshing=false;
// V12.9 Multi-Portfolio state
var PORTFOLIOS={tw:[],us:[]};
var ACTIVE_PORTFOLIO={tw:null,us:null};
// Trade Plan Center state
var TRADE_PLANS={tw:[],us:[]}, PLAN_FILTER="all", POSITIONS={tw:[],us:[]}, POSITION_FILTER="all", JOURNAL={tw:[],us:[]}, JOURNAL_FILTER="all", LAST_TW_DATA=null, LAST_TW_AI=null, LAST_US_DATA=null, LAST_US_AI=null;
// Charts
var lwChart=null, usLwChart=null, cjCharts={};

// ── Firebase ───────────────────────────────────────────────────────
function ensureFirebaseReady() {
  if(typeof firebase==="undefined"){showLoginError("Firebase SDK 載入失敗，請重新整理頁面。");return false;}
  if(!FB_CFG||!FB_CFG.projectId){showLoginError("Firebase 設定遺失，請確認 config.js。");return false;}
  try{if(!firebase.apps.length)firebase.initializeApp(FB_CFG);auth=firebase.auth();db=firebase.firestore();return true;}
  catch(e){showLoginError("Firebase 初始化失敗："+e.message);return false;}
}

function initFirebase() {
  if(!ensureFirebaseReady()){showLoginOverlay();return;}
  auth.onAuthStateChanged(function(user){
    var prev=currentUser; currentUser=user;
    if(user){
      if(prev&&prev.uid!==user.uid) clearAllState();
      try{localStorage.setItem("tw_was_logged_in","1");}catch(e){}
      var lo=$I("loginOverlay"); if(!lo||lo.style.display!=="none") hideLoginOverlay();
      refreshAuthHealthStatus();
      onUserLogin(user);
    } else {
      try{localStorage.removeItem("tw_was_logged_in");}catch(e){}
      clearAllState();
      showLoginOverlay();
      refreshAuthHealthStatus();
    }
  });
}

async function googleLogin() {
  clearLoginError();
  if(!ensureFirebaseReady()) return;
  try {
    var provider=new firebase.auth.GoogleAuthProvider();
    provider.setCustomParameters({prompt:"select_account"});
    await auth.signInWithPopup(provider);
  } catch(e) { showLoginError("Google 登入失敗："+(e.message||e.code||"未知錯誤")); }
}

async function googleLogout() {
  if(!auth) return;
  try { stopAllTimers(); clearAllState(); await auth.signOut(); }
  catch(e) { console.warn("logout:", e.message); }
}

function showLoginOverlay() { var o=$I("loginOverlay"); if(o)o.style.display="flex"; var nav=document.querySelector(".nav-tabs"); if(nav)nav.style.display="none"; document.querySelectorAll(".page").forEach(function(p){p.classList.remove("active");}); }
function hideLoginOverlay() { var o=$I("loginOverlay"); if(o)o.style.display="none"; var nav=document.querySelector(".nav-tabs"); if(nav)nav.style.display="flex"; showPage("p-hq"); }
function showLoginError(m) { var e=$I("loginError"); if(e){e.textContent=m;e.style.display="block";}else alert(m); }
function clearLoginError() { var e=$I("loginError"); if(e){e.textContent="";e.style.display="none";} }

// ── User login ─────────────────────────────────────────────────────
function refreshAuthHealthStatus(){
  try{
    setHealth("hFrontend","V"+FRONTEND_VERSION,"health-ok");
    setHealth("hFirestore",currentUser?"Connected":"待登入",currentUser?"health-ok":"health-warn");
    loadSystemHealth();
  }catch(e){console.warn("refresh auth health", e&&e.message?e.message:e);}
}

async function onUserLogin(user) {
  renderAccountUI(user);
  saveUserProfile(user).catch(function(){});
  await loadWatchlist();
  await loadPortfolios("tw");
  await loadTradePlans(); renderTradePlans();
  await loadPositions(); renderPositions();
  await loadJournal(); renderJournal();
  restoreWLCache(); renderWL(); refreshWL(); startWLTimer();
  checkLineStatus(); loadWeights();
  autoOn = localStorage.getItem("tw_auto_"+user.uid)==="1";
  updateAutoUI(); if(autoOn) startAutoTimer();
  setSyncBadge("ok");
  // US WL if on US page
  if(currentMarket==="us") { await loadUSWatchlist(); await loadPortfolios("us"); renderUSWL(); startUSWLTimer(); }
}

// ── Firestore refs ─────────────────────────────────────────────────
function userWLRef(uid) { return db&&uid?db.collection("users").doc(uid).collection("watchlists").doc("tw"):null; }
function userWLRefLegacy(uid) { return db&&uid?db.collection("users").doc(uid).collection("watchlist").doc("main"):null; }
function userProfileRef(uid) { return db&&uid?db.collection("users").doc(uid).collection("profile").doc("main"):null; }
function usWLRefFS(uid) { return db&&uid?db.collection("users").doc(uid).collection("watchlists").doc("us"):null; }
function portfolioColRef(uid) { return db&&uid?db.collection("users").doc(uid).collection("portfolios"):null; }
function portfolioDocRef(uid,pid) { return db&&uid&&pid?db.collection("users").doc(uid).collection("portfolios").doc(pid):null; }
function tradePlanRef(uid,mkt) { return db&&uid?db.collection("users").doc(uid).collection("trade_plans").doc(mkt):null; }
function positionRef(uid,mkt) { return db&&uid?db.collection("users").doc(uid).collection("positions").doc(mkt):null; }
function journalRef(uid,mkt) { return db&&uid?db.collection("users").doc(uid).collection("trade_journal").doc(mkt):null; }
function learningEventsRef(uid,mkt) { return db&&uid?db.collection("users").doc(uid).collection("ai_learning_events").doc(mkt):null; }
function aiWeightVersionRef(uid,mkt) { return db&&uid?db.collection("users").doc(uid).collection("ai_weight_versions").doc(mkt):null; }
function aiLearningSummaryRef(uid,mkt) { return db&&uid?db.collection("users").doc(uid).collection("ai_learning_summary").doc(mkt):null; }
function legacyDefaultRef() { return db?db.collection("watchlists").doc("default"):null; }

// ── V12.9 Multi-Portfolio Watchlist Manager ───────────────────────
function nowISO(){return new Date().toISOString();}
function safePortfolioId(market,name){
  var base=String(name||'default').trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g,'-').replace(/^-+|-+$/g,'').slice(0,32)||'default';
  return market+'_'+base+'_'+Math.random().toString(36).slice(2,7);
}
function defaultPortfolioName(market){return market==='us'?'Default US Portfolio':'預設台股組合';}
function normalizePortfolioDoc(id,d){
  d=d||{};return {id:id,name:d.name||defaultPortfolioName(d.market||'tw'),market:d.market||'tw',risk_profile:d.risk_profile||'balanced',color:d.color||'cyan',is_default:!!d.is_default,watchlist:Array.isArray(d.watchlist)?d.watchlist:[],created_at:d.created_at||nowISO(),updated_at:d.updated_at||nowISO(),migrated_from_legacy:!!d.migrated_from_legacy};
}
async function loadPortfolios(market){
  if(!currentUser||!db)return;
  var col=portfolioColRef(currentUser.uid); if(!col)return;
  var list=[];
  try{
    var snap=await col.get();
    snap.forEach(function(doc){var p=normalizePortfolioDoc(doc.id,doc.data()); if(p.market===market)list.push(p);});
  }catch(e){console.warn('loadPortfolios',market,e.message);}
  if(!list.length){
    var legacy=(market==='us'?US_WL:WL)||[];
    var id='default_'+market;
    var p=normalizePortfolioDoc(id,{name:defaultPortfolioName(market),market:market,is_default:true,watchlist:legacy,migrated_from_legacy:true,created_at:nowISO(),updated_at:nowISO()});
    list=[p];
    try{await portfolioDocRef(currentUser.uid,id).set(p,{merge:true});}catch(e){console.warn('create default portfolio',e.message);}
  }
  list.sort(function(a,b){return (b.is_default?1:0)-(a.is_default?1:0)||String(a.name).localeCompare(String(b.name),'zh-Hant');});
  PORTFOLIOS[market]=list;
  var savedKey='active_portfolio_'+market+'_'+currentUser.uid;
  var saved=localStorage.getItem(savedKey);
  var active=list.find(function(p){return p.id===saved;})||list.find(function(p){return p.is_default;})||list[0];
  ACTIVE_PORTFOLIO[market]=active.id;
  applyActivePortfolio(market);
  renderPortfolioUI(market);
}
function getActivePortfolio(market){return (PORTFOLIOS[market]||[]).find(function(p){return p.id===ACTIVE_PORTFOLIO[market];})||null;}
function applyActivePortfolio(market){
  var p=getActivePortfolio(market); if(!p)return;
  if(market==='us'){
    US_WL=(p.watchlist||[]).filter(function(x){return x&&x.symbol;});
    US_WL_CACHE={}; renderUSWL(); setTxt('userUsWlCount',US_WL.length+' 檔');
  }else{
    WL=normalizeWatchlist(p.watchlist||[]);
    WL_CACHE={}; renderWL(); setTxt('userWlCount',WL.length+' 檔');
  }
}
function renderPortfolioUI(market){
  var sel=$I(market==='us'?'usPortfolioSelect':'twPortfolioSelect');
  var stats=$I(market==='us'?'usPortfolioStats':'twPortfolioStats');
  var note=$I(market==='us'?'usPortfolioNote':'twPortfolioNote');
  var list=PORTFOLIOS[market]||[]; var active=getActivePortfolio(market);
  if(sel){
    sel.innerHTML=list.map(function(p){return '<option value="'+esc(p.id)+'" '+(active&&p.id===active.id?'selected':'')+'>'+esc(p.name)+' · '+(p.watchlist||[]).length+' 檔</option>';}).join('');
  }
  if(stats){
    var wl=market==='us'?US_WL:WL;
    var buy=0,watch=0,avoid=0,near=0;
    wl.forEach(function(it){var id=market==='us'?it.symbol:it.stock_id;var c=(market==='us'?US_WL_CACHE:WL_CACHE)[id]||{};var sig=c.signal||'WATCH';if(sig==='BUY')buy++;else if(sig==='AVOID')avoid++;else watch++;if(c.canEnter||c.entryStatus==='near'||c.entry_status==='near')near++;});
    stats.innerHTML='<span class="portfolio-chip">目前：<b>'+esc(active?active.name:'—')+'</b></span><span class="portfolio-chip">股票數 <b>'+wl.length+'</b></span><span class="portfolio-chip">觀察 <b>'+watch+'</b></span><span class="portfolio-chip">偏多 <b>'+buy+'</b></span><span class="portfolio-chip">避開 <b>'+avoid+'</b></span><span class="portfolio-chip">接近入場 <b>'+near+'</b></span>';
  }
  if(note&&active){note.textContent=(market==='us'?'Current portfolio: ':'目前組合：')+active.name+'｜Firestore: users/{uid}/portfolios/'+active.id;}
}
async function saveActivePortfolio(market){
  if(!currentUser)return;
  var p=getActivePortfolio(market); if(!p)return;
  var list=(market==='us'?US_WL:WL);
  p.watchlist=list; p.updated_at=nowISO();
  try{await portfolioDocRef(currentUser.uid,p.id).set(p,{merge:true});}catch(e){console.warn('save portfolio',e.message);}
  renderPortfolioUI(market);
}
async function onPortfolioChange(market){
  var sel=$I(market==='us'?'usPortfolioSelect':'twPortfolioSelect'); if(!sel)return;
  ACTIVE_PORTFOLIO[market]=sel.value;
  if(currentUser)localStorage.setItem('active_portfolio_'+market+'_'+currentUser.uid,sel.value);
  applyActivePortfolio(market);
  if(market==='us')refreshUSWL(); else refreshWL();
  renderPortfolioUI(market);
}
async function createPortfolio(market){
  if(!currentUser)return;
  var def=market==='us'?'US Growth':'短線觀察';
  var name=prompt(market==='us'?'Portfolio name':'投資組合名稱',def); if(!name)return;
  var risk=prompt(market==='us'?'Risk profile: conservative / balanced / aggressive':'風險屬性：conservative / balanced / aggressive','balanced')||'balanced';
  var id=safePortfolioId(market,name);
  var p=normalizePortfolioDoc(id,{name:name,market:market,risk_profile:risk,is_default:false,watchlist:[],created_at:nowISO(),updated_at:nowISO()});
  PORTFOLIOS[market].push(p);ACTIVE_PORTFOLIO[market]=id;if(currentUser)localStorage.setItem('active_portfolio_'+market+'_'+currentUser.uid,id);
  try{await portfolioDocRef(currentUser.uid,id).set(p,{merge:true});}catch(e){alert('建立組合失敗：'+e.message);}
  applyActivePortfolio(market);renderPortfolioUI(market);toast('已建立投資組合：'+name,'ok');
}
async function renamePortfolio(market){
  var p=getActivePortfolio(market); if(!p||!currentUser)return;
  var name=prompt(market==='us'?'New portfolio name':'新的投資組合名稱',p.name); if(!name)return;
  p.name=name;p.updated_at=nowISO();await portfolioDocRef(currentUser.uid,p.id).set({name:name,updated_at:p.updated_at},{merge:true});renderPortfolioUI(market);toast('投資組合已改名','ok');
}
async function deletePortfolio(market){
  var p=getActivePortfolio(market); if(!p||!currentUser)return;
  if((PORTFOLIOS[market]||[]).length<=1){alert('至少需要保留一個投資組合');return;}
  if(!confirm((market==='us'?'Delete portfolio ':'刪除投資組合「')+p.name+(market==='us'?'?':'」？\n組合內自選股會移除，但不會影響其他組合。')))return;
  try{await portfolioDocRef(currentUser.uid,p.id).delete();}catch(e){console.warn('delete portfolio',e.message);}
  PORTFOLIOS[market]=PORTFOLIOS[market].filter(function(x){return x.id!==p.id;});
  ACTIVE_PORTFOLIO[market]=(PORTFOLIOS[market][0]||{}).id||null;
  if(currentUser&&ACTIVE_PORTFOLIO[market])localStorage.setItem('active_portfolio_'+market+'_'+currentUser.uid,ACTIVE_PORTFOLIO[market]);
  applyActivePortfolio(market);renderPortfolioUI(market);toast('投資組合已刪除','ok');
}
function scanActivePortfolio(market){
  if(market==='us'){var sp=$I('usScanPool');if(sp)sp.value='watchlist';usAiScan('full','watchlist');}
  else{var sp2=$I('twScanPool');if(sp2)sp2.value='watchlist';aiScan('full','watchlist');}
}


async function saveUserProfile(user) {
  var ref=userProfileRef(user.uid); if(!ref) return;
  var now=new Date().toISOString();
  try { await ref.set({uid:user.uid,email:user.email,displayName:user.displayName,photoURL:user.photoURL,last_login:now},{merge:true}); }
  catch(e) {}
}

// ── TW Watchlist ───────────────────────────────────────────────────
async function loadWatchlist() {
  if(!currentUser) return;
  var uid=currentUser.uid; var ref=userWLRef(uid); if(!ref){WL=[];setSyncBadge("err");return;}
  setSyncBadge("ing");
  try {
    var snap=await ref.get();
    if(!snap.exists) { await runMigration(uid,[]); }
    else {
      var data=snap.data(); var stored=normalizeWatchlist(data.watchlist||[]);
      if(!data.migrated_from_legacy) { await runMigration(uid,stored); }
      else { WL=stored; setSyncBadge("ok"); }
    }
  } catch(e) {
    console.warn("loadWatchlist:",e.message);
    WL=loadLegacyWatchlist(); if(!WL.length){try{WL=JSON.parse(localStorage.getItem("tw_wl_v10")||"[]");}catch{}}
    setSyncBadge("err");
  }
  if(WL.length) lsSaveWL(WL);
}

async function runMigration(uid, existingItems) {
  existingItems=existingItems||[];
  var legacyItems=[].concat(existingItems);
  // Source 1: V10 Firestore path
  try { var lr=userWLRefLegacy(uid); if(lr){var s=await lr.get();if(s.exists){var it=normalizeWatchlist(s.data().watchlist||[]);if(it.length)legacyItems=legacyItems.concat(it);}} } catch(e){}
  // Source 2: localStorage
  legacyItems=legacyItems.concat(loadLegacyWatchlist());
  // Source 3: old shared Firestore
  try { var dr=legacyDefaultRef(); if(dr){var ds=await dr.get();if(ds.exists)legacyItems=legacyItems.concat(normalizeWatchlist(ds.data().watchlist||[]));} } catch(e){}
  // Source 4: backend
  if(!legacyItems.length){try{var r=await apiFetch(API+"/api/watchlist",{},8000);if(r.ok){var d=await r.json();legacyItems=legacyItems.concat(normalizeWatchlist(d.watchlist||[]));};}catch(e){}}
  var merged=mergeWL(legacyItems);
  if(!merged.length&&existingItems.length){WL=existingItems;return;}
  WL=merged;
  var ref=userWLRef(uid);
  if(ref&&merged.length>0){
    try{await ref.set({market:"tw",watchlist:merged,updated_at:new Date().toISOString(),migrated_from_legacy:true});}catch(e){}
    setSyncBadge(legacyItems.length>existingItems.length?"migrated":"ok");
  }
}

async function saveWatchlist() {
  if(!currentUser) return;
  lsSaveWL(WL);
  var ref=userWLRef(currentUser.uid); if(!ref) return;
  setSyncBadge("ing");
  try {
    await ref.set({market:"tw",watchlist:WL,updated_at:new Date().toISOString(),migrated_from_legacy:true});
    await saveActivePortfolio("tw");
    setTxt("userLastSync",new Date().toLocaleTimeString("zh-TW"));
    setTxt("userWlCount",WL.length+" 檔");
    setSyncBadge("ok");
  } catch(e) { setSyncBadge("err"); }
}

function normalizeWatchlist(raw) {
  if(!Array.isArray(raw)) return [];
  var r=[],seen=new Set();
  raw.forEach(function(item){
    var sid,sname;
    if(typeof item==="string"){sid=item.trim();sname=getLocalName(sid)||sid;}
    else if(item&&typeof item==="object"){sid=String(item.stock_id||item.id||"").trim();sname=item.stock_name||item.name||getLocalName(sid)||sid;}
    if(sid&&/^\d{4,6}[A-Z]?$/.test(sid)&&!seen.has(sid)){seen.add(sid);r.push({stock_id:sid,stock_name:sname});}
  });
  return r;
}
function mergeWL() {
  var seen=new Set(),m=[];
  Array.from(arguments).forEach(function(list){(list||[]).forEach(function(it){if(it&&it.stock_id&&!seen.has(it.stock_id)){seen.add(it.stock_id);m.push(it);}});});
  return m;
}
function loadLegacyWatchlist() {
  var keys=["tw_wl_v10","tw_wl_v9","watchlist","WL_KEY","tw_watchlist","wl","tw_wl_v1"],cands=[];
  keys.forEach(function(k){try{var raw=localStorage.getItem(k);if(!raw)return;var p=JSON.parse(raw);var arr=Array.isArray(p)?p:(Array.isArray(p&&p.watchlist)?p.watchlist:null);if(arr&&arr.length)cands=cands.concat(normalizeWatchlist(arr));}catch{}});
  return normalizeWatchlist(cands);
}
function lsSaveWL(items){try{localStorage.setItem("tw_wl_v10",JSON.stringify(items));}catch{}}
function lsGetWL(){try{return JSON.parse(localStorage.getItem("tw_wl_v10")||"[]");}catch{return [];}}
function getWLIds(){return WL.map(function(x){return x.stock_id;});}

function setSyncBadge(state) {
  var el=$I("syncBadge"); if(!el) return;
  var map={ok:["☁️ 已同步","sync-badge sync-ok"],migrated:["🔄 已從舊資料恢復","sync-badge sync-ok"],err:["⚠️ 同步失敗","sync-badge sync-err"],ing:["⏳ 同步中","sync-badge sync-ing"],local:["👤 本機模式","sync-badge sync-ing"]};
  var v=map[state]||map.err; el.textContent=v[0]; el.className=v[1];
}

// ── US Watchlist ────────────────────────────────────────────────────
async function loadUSWatchlist() {
  if(!currentUser) return;
  var ref=usWLRefFS(currentUser.uid); if(!ref){US_WL=[];return;}
  var badge=$I("usSyncBadge"); if(badge){badge.textContent="⏳";badge.className="sync-badge sync-ing";}
  try {
    var snap=await ref.get();
    US_WL=snap.exists?(snap.data().watchlist||[]).filter(function(x){return x&&x.symbol;}):[];
    if(badge){badge.textContent="☁️";badge.className="sync-badge sync-ok";}
    setTxt("userUsWlCount",US_WL.length+" 檔");
  } catch(e) { US_WL=[]; if(badge){badge.textContent="⚠️";badge.className="sync-badge sync-err";} }
}

async function saveUSWatchlist() {
  if(!currentUser) return;
  var ref=usWLRefFS(currentUser.uid); if(!ref) return;
  try { await ref.set({market:"us",watchlist:US_WL,updated_at:new Date().toISOString()}); await saveActivePortfolio("us"); setTxt("userUsWlCount",US_WL.length+" 檔"); }
  catch(e) { console.warn("saveUSWatchlist:",e.message); }
}

// ── Clear state ────────────────────────────────────────────────────
function clearAllState() {
  stopAllTimers();
  WL=[]; WL_CACHE={}; CURRENT_ID=null;
  ["wlGrid","wlGridCompact"].forEach(function(id){var e=$I(id);if(e)e.innerHTML="";});
  setTxt("wlCount","0 檔"); destroyChart();
  var dash=$I("dash"); if(dash) dash.style.display="none";
  US_WL=[]; US_WL_CACHE={}; US_CURRENT=null; PORTFOLIOS={tw:[],us:[]}; ACTIVE_PORTFOLIO={tw:null,us:null};
  TRADE_PLANS={tw:[],us:[]}; renderTradePlans();
  POSITIONS={tw:[],us:[]}; renderPositions();
  JOURNAL={tw:[],us:[]}; renderJournal();
  var ug=$I("usWlGrid"); if(ug) ug.innerHTML="";
  var ud=$I("usDash"); if(ud) ud.style.display="none";
  destroyUSChart();
}
function stopAllTimers() {
  clearInterval(wlTimer); wlTimer=null;
  clearInterval(autoTimer); autoTimer=null;
  clearInterval(usWlTimer); usWlTimer=null;
}

// ── Market switch ──────────────────────────────────────────────────
function switchMarket(mkt) {
  if(mkt==="us"&&!ENABLE_US){mkt="tw";}
  currentMarket=mkt;
  var tw=$I("pgTW"), us=$I("pgUS");
  var btnTW=$I("btnMktTW"), btnUS=$I("btnMktUS");
  if(mkt==="us") {
    if(tw) tw.style.display="none"; if(us) us.style.display="block";
    if(btnTW){btnTW.className="mkt-btn";} if(btnUS){btnUS.className="mkt-btn active-us";}
    if(currentUser&&!US_WL.length){loadUSWatchlist().then(function(){return loadPortfolios("us");}).then(function(){renderUSWL();startUSWLTimer();});}
    else if(US_WL.length) renderUSWL();
  } else {
    if(us) us.style.display="none"; if(tw) tw.style.display="block";
    if(btnTW){btnTW.className="mkt-btn active-tw";} if(btnUS){btnUS.className="mkt-btn";}
    showPage("p-trade");
  }
}

// ── Account UI ─────────────────────────────────────────────────────
function renderAccountUI(user) {
  var guest=$I("accountGuest"), logged=$I("accountUser"); if(!guest||!logged) return;
  if(user) {
    guest.style.display="none"; logged.style.display="block";
    setTxt("userName",user.displayName||"—"); setTxt("userEmail",user.email||"—");
    setTxt("userUid",(user.uid||"").slice(0,8)+"…"); setTxt("userWlCount",WL.length+" 檔");
    var av=$I("userAvatar"); if(av&&user.photoURL) av.src=user.photoURL;
  } else { guest.style.display="block"; logged.style.display="none"; }
}

// ── Stock master ───────────────────────────────────────────────────
async function loadStockMaster() {
  try { var r=await apiFetch(API+"/api/stocks/master",{},15000); if(r.ok){var d=await r.json();STOCK_DICT=d.stocks||{};} }
  catch(e) {}
}
function getLocalName(id) { return (STOCK_DICT[id]&&STOCK_DICT[id].name)||null; }

// ── Utilities ──────────────────────────────────────────────────────
var $I = function(id){return document.getElementById(id);};
function setTxt(id,v){var el=$I(id);if(el)el.textContent=v;}
function addCls(id,cls){var el=$I(id);if(!el)return;["up","down","flat","tw-up","tw-down","tw-flat","us-up","us-down"].forEach(function(c){el.classList.remove(c);});if(cls)el.classList.add(cls);}
function showErr(m){var el=$I("err");if(el){el.textContent="⚠️ "+m;el.style.display="block";}}
function hideErr(){var el=$I("err");if(el)el.style.display="none";}
function f(n,d){d=d||2;return(n==null||isNaN(Number(n)))?"—":Number(n).toFixed(d);}
function pct(n){if(n==null)return"—";return(Number(n)>0?"+":"")+Number(n).toFixed(2)+"%";}
function fvol(n){return n?Math.round(n/1000).toLocaleString()+"張":"—";}
function fvolLots(n){return n?Math.round(n).toLocaleString()+"張":"—";}  // 已經是張數（證交所即時資料）
function cc(v){return Number(v)>0?"up":Number(v)<0?"down":"flat";}
function twcc(v){return Number(v)>0?"tw-up":Number(v)<0?"tw-down":"tw-flat";}
function uscc(v){return Number(v)>0?"us-up":Number(v)<0?"us-down":"us-flat";}
function sigIcon(s){return s==="BUY"?"偏多":s==="AVOID"?"避開":"觀察";}
function usSigIcon(s){return s==="BUY"?"📈 BUY":s==="AVOID"?"🚫 AVOID":s==="HIGH_RISK"?"⚠️ HIGH RISK":"👀 WATCH";}
function dsn(id,name){return(name&&name!==id)?name+" ("+id+")":id;}
function fmtD(s){try{return new Date(s).toLocaleDateString("zh-TW");}catch{return s||"";}}
function fUS(n,d){d=d||2;return(n==null||isNaN(Number(n)))?"—":"$"+Number(n).toFixed(d);}
function pctUS(n){if(n==null)return"—";return(Number(n)>0?"+":"")+Number(n).toFixed(2)+"%";}
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}

function esc(s){return String(s==null?"":s).replace(/[&<>'"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c];});}
function toast(msg,type){var el=$I("toast");if(!el)return alert(msg);el.textContent=msg;el.className="toast show "+(type||"ok");clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(function(){el.className="toast "+(type||"ok");},2200);}
function twDisplayName(id){var c=WL_CACHE[id]||{},item=WL.find(function(x){return String(x.stock_id)===String(id);})||{};return c.name||item.stock_name||getLocalName(id)||id;}
function usDisplayName(sym,item){var c=US_WL_CACHE[sym]||{};item=item||US_WL.find(function(x){return String(x.symbol)===String(sym);})||{};return c.name||item.name||sym;}


async function apiFetch(url,opt,timeout) {
  timeout=timeout||30000;
  var c=new AbortController(),t=setTimeout(function(){c.abort();},timeout);
  opt=Object.assign({},opt||{});
  if((opt.method||"GET").toUpperCase()!=="GET"&&currentUser&&currentUser.getIdToken){
    try{var tok=await currentUser.getIdToken();opt.headers=Object.assign({},opt.headers||{},{"Authorization":"Bearer "+tok});}catch(e){}
  }
  try{return await fetch(url,Object.assign({},opt,{signal:c.signal}));}
  catch(e){if(e.name==="AbortError"){var err=new Error("請求逾時，Render 可能正在喚醒，請稍後再試。");err.name="TimeoutError";throw err;}throw e;}
  finally{clearTimeout(t);}
}

// ── Page nav ───────────────────────────────────────────────────────
function showPage(pageId) {
  document.querySelectorAll(".page").forEach(function(p){p.classList.remove("active");});
  document.querySelectorAll(".nav-tab").forEach(function(b){b.classList.remove("active");});
  var p=$I(pageId); if(p) p.classList.add("active");
  document.querySelectorAll(".nav-tab").forEach(function(b){if(b.dataset.page===pageId)b.classList.add("active");});
  if(pageId==="p-market"&&currentUser){loadMacro();loadSentiment();}
  if(pageId==="p-account") renderAccountUI(currentUser);
  try{
    if(pageId==="p-ledger"&&window.LEDGER) LEDGER.open();
    if(pageId==="p-learn"&&window.LAB) LAB.open();
    if(pageId==="p-reports"&&window.REPORTS) REPORTS.open();
  }catch(e){console.warn("page open",pageId,e);}
  try{if(pageId==="p-hq") renderHQ(); navSync(pageId);}catch(e){console.warn("home ui",e);}
  if(pageId==="p-plans") { loadTradePlans().then(function(){renderTradePlans(); refreshTradePlans(false);}); }
}

// ── Suggest ────────────────────────────────────────────────────────
var suggestTimer=null;
// 手機查詢後，結果在很下面，自動捲到結果（每次查詢只捲一次）
var _dashScrolledFor=null;
function scrollDashMobile(dash){try{if(window.innerWidth>760||_dashScrolledFor===CURRENT_ID)return;_dashScrolledFor=CURRENT_ID;dash.scrollIntoView({behavior:"smooth",block:"start"});}catch(e){}}
function initSearchSuggest() {
  var inp=$I("sid"),box=$I("suggestBox"); if(!inp||!box) return;
  inp.addEventListener("input",function(){clearTimeout(suggestTimer);var q=inp.value.trim();if(q.length<1){box.style.display="none";return;}suggestTimer=setTimeout(function(){fetchSuggest(q);},280);});
  inp.addEventListener("blur",function(){setTimeout(function(){if(box)box.style.display="none";},200);});
  inp.addEventListener("keydown",function(e){if(e.key==="Enter")doSearch();});
}
async function fetchSuggest(q) {
  try { var r=await apiFetch(API+"/api/stocks/search?q="+encodeURIComponent(q),{},8000); if(!r.ok)return; var d=await r.json(); showSuggest(d.results||[]); } catch{}
}
function showSuggest(results) {
  var box=$I("suggestBox"); if(!box) return;
  if(!results.length){box.style.display="none";return;}
  box.innerHTML=results.map(function(r){return'<div class="suggest-item" data-id="'+r.stock_id+'" data-name="'+r.stock_name+'"><span class="si-name">'+r.stock_name+'</span><span class="si-id">'+r.stock_id+'</span></div>';}).join("");
  box.style.display="block";
  box.querySelectorAll(".suggest-item").forEach(function(el){el.addEventListener("click",function(){var inp=$I("sid");if(inp)inp.value=el.dataset.id;box.style.display="none";doSearch();});});
}

// ── WL sort & render ───────────────────────────────────────────────
function sortWLIds(ids) {
  function key(c){if(!c||c.noData)return 60;var s=c.signal||"WATCH",q=c.scoreQuality||"none";if(s==="BUY"&&q==="full")return 10;if(s==="WATCH"&&q==="full")return 20;if(s==="WATCH"&&q==="partial")return 30;return 50;}
  return ids.slice().sort(function(a,b){var A=WL_CACHE[a]||{},B=WL_CACHE[b]||{};var kA=key(A),kB=key(B);if(kA!==kB)return kA-kB;return(B.confidence||0)-(A.confidence||0);});
}

function compactCard(id) {
  var c=WL_CACHE[id],item=WL.find(function(x){return x.stock_id===id;})||{};
  var nm=c?(c.name||item.stock_name||id):(item.stock_name||getLocalName(id)||id);
  if(!c) return '<div class="card-compact" style="position:relative" data-load="'+id+'"><button class="ghost sm" style="position:absolute;top:4px;right:4px;min-height:0;padding:0 6px;font-size:12px" data-del="'+id+'">×</button><div class="cc-name" title="'+nm+'">'+nm+'</div><div class="cc-id">'+id+'</div><div class="cc-price tw-flat" style="font-size:12px;color:var(--muted)">讀取中…</div></div>';
  if(c.noData) return '<div class="card-compact" style="position:relative" data-load="'+id+'"><button class="ghost sm" style="position:absolute;top:4px;right:4px;min-height:0;padding:0 6px;font-size:12px" data-del="'+id+'">×</button><div class="cc-name">'+nm+'</div><div class="cc-id">'+id+'</div><div class="cc-price tw-flat">暫無資料</div></div>';
  var clr=twcc(c.changePct||0), sig=c.signal||"WATCH", cls=sig==="BUY"?"buy":sig==="AVOID"?"avoid":"watch-sig";
  var sel=id===CURRENT_ID?" selected":"";
  return '<div class="card-compact '+cls+sel+'" style="position:relative" data-load="'+id+'">'+
    '<button class="ghost sm" style="position:absolute;top:4px;right:4px;min-height:0;padding:0 6px;font-size:12px" data-del="'+id+'">×</button>'+
    '<div class="cc-name" title="'+nm+'">'+nm+'</div>'+
    '<div class="cc-id">'+id+'</div>'+
    '<div class="cc-price '+clr+'">'+(c.price!=null?f(c.price):"—")+'</div>'+
    '<div class="cc-chg '+clr+'">'+pct(c.changePct)+'</div>'+
    '<div style="font-family:var(--mono);font-size:10px;margin-top:3px;display:flex;gap:4px;align-items:center">'+
    '<span style="font-size:10px;padding:1px 5px;border-radius:4px;background:'+(sig==="BUY"?"rgba(232,56,79,.15)":sig==="AVOID"?"rgba(0,184,107,.1)":"rgba(251,191,36,.12)")+';color:'+(sig==="BUY"?"var(--up)":sig==="AVOID"?"var(--down)":"var(--yellow)")+'" >'+sigIcon(sig)+'</span>'+
    '<span style="color:var(--muted)">'+(c.confidence!=null?c.confidence+"/100":"—")+'</span>'+
    '</div></div>';
}

function tickerItemHTML(id) {
  var c=WL_CACHE[id]||{};
  var nm=twDisplayName(id); var clr=twcc(c.changePct||0);
  return '<div class="ticker-item" data-load="'+esc(id)+'">'+
    '<span class="name-code">'+esc(nm)+' <span style="color:var(--muted)">'+esc(id)+'</span></span>'+
    '<span class="ticker-price '+clr+'">'+(c.price!=null?f(c.price):"—")+'</span>'+
    '<span class="ticker-chg '+clr+'">'+pct(c.changePct)+'</span>'+
    '</div>';
}

function renderWL() {
  setTxt("wlCount",WL.length+" 檔");
  var ids=sortWLIds(getWLIds());
  var COMPACT_N=4;
  var compact=ids.slice(0,COMPACT_N), tickers=ids.slice(COMPACT_N);

  if(watchlistExpanded) {
    var fg=$I("wlGridFull"),cg=$I("wlGridCompact"),tw=$I("wlTickerWrap");
    if(fg)fg.style.display="block";if(cg)cg.style.display="none";if(tw)tw.style.display="none";
    var g=$I("wlGrid");
    if(g){
      g.innerHTML=ids.length?ids.map(compactCard).join(""):'<div class="empty">尚無自選股</div>';
      bindWLCards(g);
    }
    setTxt("btnToggleWl","收合");
  } else {
    var fg=$I("wlGridFull");if(fg)fg.style.display="none";
    var cg=$I("wlGridCompact");
    if(cg){cg.style.display="grid";
      cg.innerHTML=compact.length?compact.map(compactCard).join(""):'<div class="empty" style="grid-column:1/-1;font-size:12px">輸入股票代號後按「＋ 加入自選」</div>';
      bindWLCards(cg);
    }
    var tw=$I("wlTickerWrap"),inner=$I("wlTickerInner");
    if(tw&&inner){
      if(tickers.length){
        tw.style.display="block";
        var items=tickers.map(tickerItemHTML).join("");
        inner.innerHTML=items+items;
        inner.querySelectorAll("[data-load]").forEach(function(el){el.addEventListener("click",function(){loadStock(el.dataset.load);});});
        requestAnimationFrame(function(){var hw=Math.round(inner.scrollWidth/2);var dur=Math.min(120,Math.max(20,tickers.length*8));tw.style.setProperty("--ticker-half","-"+hw+"px");inner.style.animation="ticker-scroll "+dur+"s linear infinite";});
      } else {tw.style.display="none";}
    }
    setTxt("btnToggleWl","展開");
  }
  renderPortfolioUI("tw");
}
function bindWLCards(container) {
  container.querySelectorAll("[data-load]").forEach(function(el){el.addEventListener("click",function(e){if(!e.target.closest("[data-del]"))loadStock(el.dataset.load);});});
  container.querySelectorAll("[data-del]").forEach(function(btn){btn.addEventListener("click",function(e){e.stopPropagation();removeWL(btn.dataset.del);});});
}
function toggleWatchlistExpanded(){watchlistExpanded=!watchlistExpanded;renderWL();}

// 自選股報價存在手機上，下次打開先顯示上次價格（標示為舊資料），後端醒來後再更新
function saveWLCache(){try{if(currentUser)localStorage.setItem("tw_wlcache_"+currentUser.uid,JSON.stringify(WL_CACHE));}catch(e){}}
function restoreWLCache(){try{if(!currentUser)return;var c=JSON.parse(localStorage.getItem("tw_wlcache_"+currentUser.uid)||"{}");Object.keys(c).forEach(function(k){if(!WL_CACHE[k]&&c[k]&&c[k].price!=null){c[k].stale=true;WL_CACHE[k]=c[k];}});}catch(e){}}
async function fetchOneWL(id) {
  var item=WL.find(function(x){return x.stock_id===id;})||{};
  try {
    // 第一次抓（後端可能還在冷啟動）給較長等待時間
    var first=!(WL_CACHE[id]&&WL_CACHE[id].price!=null&&!WL_CACHE[id].stale);
    var r=await apiFetch(API+"/api/stock-lite/"+id,{},first?45000:20000);
    if(!r.ok)throw new Error("status "+r.status);
    var d=await r.json();var ai=d.ai_signal||{};
    WL_CACHE[id]={name:d.stock_name||id,price:d.price,changePct:d.change_pct,signal:ai.signal||null,confidence:ai.confidence,scoreQuality:ai.score_quality||"none",entryPrice:ai.entry_price,targetPrice:ai.target_price,stopLoss:ai.stop_loss,entryStatus:ai.entry_status||"",entryStatusText:ai.entry_status_text||"",canEnter:ai.can_enter||false,error:false,noData:false};
    saveWLCache();
    var it=WL.find(function(x){return x.stock_id===id;});if(it&&d.stock_name&&d.stock_name!==id)it.stock_name=d.stock_name;
  } catch(e) {if(!WL_CACHE[id])WL_CACHE[id]={name:item.stock_name||id,error:false,noData:true};}
}
async function refreshWL() {
  if(!currentUser||isRefreshWL) return;
  isRefreshWL=true; var ids=getWLIds(); if(!ids.length){isRefreshWL=false;return;}
  try{for(var i=0;i<ids.length;i+=2){await Promise.allSettled(ids.slice(i,i+2).map(function(id){return fetchOneWL(id).catch(function(){});}));renderWL();if(i+2<ids.length)await sleep(500);}}
  finally{isRefreshWL=false;}
}
function startWLTimer(){
  clearInterval(wlTimer);wlLeft=30;
  wlTimer=setInterval(function(){wlLeft--;var bar=$I("wlBar");if(bar)bar.style.width=Math.max(0,wlLeft/30*100)+"%";setTxt("wlTick",Math.max(0,wlLeft)+"s 後刷新");if(wlLeft<=0){wlLeft=30;if(bar)bar.style.width="100%";refreshWL();}},1000);
}
async function addWL() {
  if(!currentUser){return;}
  var inp=$I("sid"),id=inp?inp.value.trim().toUpperCase():"";
  if(!/^\d{4,6}[A-Z]?$/.test(id)){showErr("請輸入 4~6 位股票代號");return;}
  if(WL.find(function(x){return x.stock_id===id;})){showErr(id+" 已在自選股");return;}
  WL.push({stock_id:id,stock_name:getLocalName(id)||id});renderWL();await saveWatchlist();await fetchOneWL(id);renderWL();
}
async function removeWL(id) {
  WL=WL.filter(function(x){return x.stock_id!==id;});delete WL_CACHE[id];renderWL();await saveWatchlist();
}
function loadStock(id){var inp=$I("sid");if(inp)inp.value=id;doSearch();}

// ── Scan alerts ────────────────────────────────────────────────────
async function scanAlerts(silent) {
  if(!currentUser) return null;
  var ids=getWLIds();
  if(!ids.length){if(!silent){var el=$I("scanResult");if(el){el.className="scan-result warn";el.textContent="⚠️ 自選股清單是空的";el.style.display="block";}}return null;}
  var el=$I("scanResult"); var wakeT=null;
  if(!silent&&el){el.className="scan-result";el.textContent="⏳ 掃描中（"+ids.length+" 檔）…";el.style.display="block";wakeT=setTimeout(function(){if(el)el.textContent+=" 後端喚醒中…";},12000);}
  try {
    var r=await apiFetch(API+"/api/alerts/check",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({watchlist:ids})},120000);
    if(wakeT)clearTimeout(wakeT);var d=await r.json();
    var alerts=d.alerts||[],sentLine=d.sent_line||[],checked=d.checked||ids.length,lineOk=d.line_enabled,dur=d.duration_seconds||0;
    var txt;
    if(!alerts.length)txt="✅ 掃描完成 "+checked+" 檔（"+dur+"s）\n目前自選股沒有符合條件的買點。";
    else{var lines=alerts.map(function(a){return"📈 "+dsn(a.stock_id,a.stock_name)+"  技術面評分："+a.confidence+"/100\n   "+(a.summary||"");});txt="📊 掃描 "+checked+" 檔（"+dur+"s），發現 "+alerts.length+" 檔符合條件（未驗證，僅供研究）\n\n"+lines.join("\n\n");if(sentLine.length)txt+="\n\n✅ LINE 已推播："+sentLine.join("、");else if(!lineOk)txt+="\n（LINE 未設定）";}
    if(!silent&&el){el.className="scan-result ok";el.textContent=txt;el.style.display="block";}
    return{txt:txt,alerts:alerts,sentLine:sentLine,checked:checked};
  } catch(e) {if(wakeT)clearTimeout(wakeT);if(!silent&&el){el.className="scan-result fail";el.textContent="❌ "+(e.message||"掃描失敗");el.style.display="block";}return null;}
}


// ── Recommendation History / Diversity helpers ─────────────────────
function recHistKey(market){return "rec_history_"+market+"_"+(currentUser?currentUser.uid:"guest");}
function getRecommendationHistory(market){try{return JSON.parse(localStorage.getItem(recHistKey(market))||"[]");}catch(e){return [];}}
function getRecommendationHistorySymbols(market){var cutoff=Date.now()-7*24*60*60*1000;return getRecommendationHistory(market).filter(function(x){return (x.ts||0)>=cutoff;}).map(function(x){return String(x.symbol||x.stock_id||"").toUpperCase();}).filter(Boolean).slice(0,120);}
function saveRecommendationHistory(market,data){
  try{
    var old=getRecommendationHistory(market);var now=Date.now();var zones=["enterable","watch_closely","fresh_discovery","pullback","breakout_watch","near_miss","risk_watch"];
    var add=[];zones.forEach(function(z){(data[z]||[]).slice(0,12).forEach(function(it){add.push({market:market,symbol:String(it.symbol||it.stock_id||"").toUpperCase(),category:z,final_score:it.final_score,diversified_score:it.diversified_score,diversity_group:it.diversity_group,ts:now});});});
    var merged=add.concat(old).filter(function(x){return x.symbol && (now-(x.ts||0))<14*24*60*60*1000;});
    var seen={};merged=merged.filter(function(x){var key=x.symbol+":"+x.category+":"+Math.floor((x.ts||0)/(12*60*60*1000));if(seen[key])return false;seen[key]=1;return true;}).slice(0,300);
    localStorage.setItem(recHistKey(market),JSON.stringify(merged));
  }catch(e){console.warn("saveRecommendationHistory failed",e);}
}

function isDomEvent(x){return !!(x && typeof x==="object" && (x.type||x.target||x.currentTarget||x.pointerId!==undefined) && (x.preventDefault||x.stopPropagation||x.isTrusted!==undefined));}
function cleanScanMode(v){if(isDomEvent(v))return "";var s=String(v||"").trim().toLowerCase().replace(/_/g,"-");if(!s||s==="undefined"||s==="null"||s.indexOf("pointerevent")>=0||s.indexOf("object ")>=0)return "";return s;}
function cleanDiversityMode(v){var s=cleanScanMode(v);var ok={"balanced":1,"fresh-discovery":1,"sector-rotation":1,"strict":1,"watchlist-priority":1};return ok[s]?s:"balanced";}
function displayModeName(v){v=cleanDiversityMode(v);return {"balanced":"balanced","fresh-discovery":"fresh-discovery","sector-rotation":"sector-rotation","strict":"strict","watchlist-priority":"watchlist-priority"}[v]||"balanced";}

// ── TW AI Scan ─────────────────────────────────────────────────────
async function aiScan(forceMode, forcePool) {
  if(isDomEvent(forceMode)){forceMode=null;forcePool=null;}
  if(!currentUser) return;
  var box=$I("aiScanTradeBox"); if(box)box.style.display="block";
  var sum=$I("aiScanSummary");
  var mode=cleanScanMode(forceMode) || (($I("twScanMode")||{}).value||"full");
  var pool=(isDomEvent(forcePool)?"":forcePool) || (($I("twScanPool")||{}).value||"all");
  var diversityMode=cleanDiversityMode(($I("twDiversityMode")||{}).value||"balanced");
  var endpoint="/api/tw/scan/diversified";
  var max=(mode==="quick")?20:60;
  var symbols=(pool==="watchlist")?WL.map(function(x){return x.stock_id||x;}).join(","):"";
  if(sum)sum.textContent=(mode==="quick"?"Quick Scan":"Full Scan")+" 掃描中…";
  ["aiZoneEnterable","aiZoneWatchClose","aiZoneFreshDiscovery","aiZonePullback","aiZoneBreakout","aiZoneNearMiss","aiZoneRiskWatch"].forEach(function(id){var el=$I(id);if(el)el.innerHTML="";});
  updateScanProgress("tw",8);
  var fake=beginFakeProgress("tw", mode==="quick"?12000:70000);
  var btn=$I("btnAiScan"),btn2=$I("btnAiScanAgain"); if(btn)btn.disabled=true; if(btn2)btn2.disabled=true;
  if(box)setTimeout(function(){box.scrollIntoView({behavior:"smooth",block:"start"});},200);
  try {
    var history=getRecommendationHistorySymbols("tw").join(",");
    var url=API+endpoint+"?min_score=55&max_stocks="+max+"&mode="+encodeURIComponent(mode)+"&pool="+encodeURIComponent(pool)+"&diversity_mode="+encodeURIComponent(diversityMode)+"&symbols="+encodeURIComponent(symbols)+"&history_symbols="+encodeURIComponent(history);
    var r=await apiFetch(url,{},mode==="quick"?45000:120000); var d=await r.json(); d=normalizeScanPayload(d);
    var s=d.summary||{}; if(sum)sum.textContent=(d.scan_label||"")+" | 掃描 "+safeVal(d.scanned,0)+" 檔 | 分類 "+safeVal(d.classified,0)+" | 失敗 "+safeVal(d.failed||d.error_count,0)+" | "+safeVal(d.duration_seconds,"—")+"s | 市場 "+safeVal(s.market_score??d.market_score,"—")+"/100"+(s.message?" — "+s.message:"");
    renderScanKpis("tw",d); setTxt("twScanCache","cache: "+(d.cache_status||"fresh")+" · "+(d.diversity_mode||diversityMode)); saveRecommendationHistory("tw",d); await recordLearningEventsFromScan("tw",d); updateScanProgress("tw",100); renderTWScan(d);
  } catch(e) { if(sum)sum.textContent="掃描失敗："+e.message; updateScanProgress("tw",0); }
  finally { clearInterval(fake); if(btn)btn.disabled=false; if(btn2)btn2.disabled=false; }
}

function normalizeScanPayload(d){d=d||{};var s=d.summary||{};["enterable","watch_closely","fresh_discovery","pullback","breakout_watch","near_miss","risk_watch","avoid"].forEach(function(k){d[k]=Array.isArray(d[k])?d[k]:[];});var total=d.enterable.length+d.watch_closely.length+d.fresh_discovery.length+d.pullback.length+d.breakout_watch.length+d.near_miss.length+d.risk_watch.length+d.avoid.length;d.scanned=d.scanned??s.scanned??d.attempted??total;d.classified=d.classified??s.classified??total;d.failed=d.failed??s.failed??d.error_count??0;d.duration_seconds=d.duration_seconds??s.duration_seconds??0;d.market_score=d.market_score??s.market_score??"—";d.summary=d.summary||{};d.summary.market_score=d.summary.market_score??d.market_score;return d;}
function updateScanProgress(prefix,pct){var el=$I(prefix+"ScanProgress");if(el)el.style.width=Math.max(0,Math.min(100,pct||0))+"%";}
function beginFakeProgress(prefix,ms){var start=Date.now();return setInterval(function(){var p=Math.min(92,8+(Date.now()-start)/ms*84);updateScanProgress(prefix,p);},500);}
function renderScanKpis(prefix,d){var el=$I(prefix+"ScanKpis");if(!el)return;var s=d.summary||{},ds=d.diversity_summary||{};el.style.display="grid";var mode=displayModeName(d.diversity_mode||s.diversity_mode||s.mode||'balanced');var overlap=(s.top10_overlap_rate??ds.top10_overlap_rate);if(typeof overlap==='number')overlap=Math.round(overlap*100)+'%';var items=[['Mode',mode],['Pool',d.pool||s.pool||'—'],['Scanned',d.scanned||0],['Fresh',(s.fresh_candidate_count??ds.fresh_candidate_count??(d.fresh_discovery||[]).length)],['Overlap',safeVal(overlap,'—')],['Sector',safeVal(s.sector_spread_count??ds.sector_spread_count,'—')],['Strategy',safeVal(s.strategy_spread_count??ds.strategy_spread_count,'—')],['Failed',d.failed||0],['Market',safeVal(s.market_score??d.market_score,'—')+'/100']];el.innerHTML=items.map(function(x){return '<div class="scan-kpi"><div class="k">'+x[0]+'</div><div class="v">'+escapeHTML(String(x[1]))+'</div></div>';}).join('');}

function renderTWScan(data) {
  function zone(elId, lbl, labelCss, items, emptyMsg) {
    var el=$I(elId); if(!el) return;
    if(!items||!items.length){el.innerHTML='<div class="scan-zone-lbl '+labelCss+'">'+lbl+' <span>0</span></div><div class="empty" style="padding:8px;font-size:11px">'+emptyMsg+'</div>';return;}
    el.innerHTML='<div class="scan-zone-lbl '+labelCss+'">'+lbl+' <span class="d-badge" style="font-size:10px">'+items.length+'</span></div><div class="scan-grid" style="margin-top:8px;margin-bottom:12px">'+items.map(twScanCard).join("")+'</div>';
    el.querySelectorAll("[data-load]").forEach(function(el2){el2.addEventListener("click",function(){loadStock(el2.dataset.load);});});
  }
  data=normalizeScanPayload(data);
  zone("aiZoneEnterable","✅ 可進場候選 ENTERABLE","sz-enterable",data.enterable,"目前沒有符合可進場條件的股票，建議等待更好的進場點。");
  zone("aiZoneWatchClose","👀 準備觀察 WATCH CLOSELY","sz-close",data.watch_closely,"目前沒有準備觀察候選。");
  zone("aiZoneFreshDiscovery","🌱 新發現 FRESH DISCOVERY","sz-fresh",data.fresh_discovery,"近期沒有新的高品質探索候選。");
  zone("aiZonePullback","⏳ 等回檔觀察 PULLBACK","sz-pullback",data.pullback,"—");
  zone("aiZoneBreakout","🔭 突破觀察 BREAKOUT WATCH","sz-breakout",data.breakout_watch,"—");
  zone("aiZoneNearMiss","💫 差一點候選 NEAR MISS","sz-near",data.near_miss,"—");
  zone("aiZoneRiskWatch","⚠️ 高風險觀察 RISK WATCH","sz-risk",data.risk_watch,"—");
}

function twScanCard(r) {
  var clr=twcc(r.change_pct||0);var sig=r.signal||"WATCH";var rr=r.risk_reward_ratio;
  var tv=r.trade_valid;var ts=r.technical_score;var fs=r.final_score;var ms=r.market_score;var rs=r.risk_score;
  var esText=r.entry_status_text||r.entry_status||"—";
  var sigBg=sig==="BUY"?"rgba(232,56,79,.15)":"rgba(251,191,36,.12)";var sigFg=sig==="BUY"?"var(--up)":"var(--yellow)";
  return '<div class="scan-card" data-load="'+r.stock_id+'">'+
    '<div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:6px">'+
    '<div><div style="font-weight:700;font-size:13px">'+dsn(r.stock_id,r.stock_name)+'</div>'+
    '<div style="font-family:var(--mono);font-size:10px;color:var(--muted)">'+(r.strategy_type||"")+'</div></div>'+
    '<div style="text-align:right">'+
    '<span style="font-family:var(--mono);font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;background:'+sigBg+';color:'+sigFg+'">'+sigIcon(sig)+'</span>'+
    (tv===true?'<div style="font-family:var(--mono);font-size:9px;color:var(--down);margin-top:2px">✅ Valid</div>':tv===false?'<div style="font-family:var(--mono);font-size:9px;color:var(--up);margin-top:2px">⚠️ Invalid</div>':'')+'</div></div>'+
    '<div style="font-family:var(--mono);font-size:16px;font-weight:700;margin-bottom:6px" class="'+clr+'">'+(r.price!=null?f(r.price):"—")+' <span style="font-size:12px">'+pct(r.change_pct)+'</span></div>'+
    '<div class="scan-meta">'+
    '<div><span class="lbl">入場</span> <span class="val">'+(r.entry_price!=null?f(r.entry_price):"—")+'</span></div>'+
    '<div><span class="lbl">目標</span> <span class="val up">'+(r.target_price!=null?f(r.target_price):"—")+'</span></div>'+
    '<div><span class="lbl">停損</span> <span class="val down">'+(r.stop_loss!=null?f(r.stop_loss):"—")+'</span></div>'+
    '<div><span class="lbl">RR</span> <span class="val '+((rr||0)>=1.5?"up":"down")+'">'+(rr!=null?rr+"x":"—")+'</span></div>'+
    (ts!=null?'<div><span class="lbl">技術</span> <span class="val">'+ts+'</span></div>':'')+
    (fs!=null?'<div><span class="lbl">Final</span> <span class="val">'+fs+'</span></div>':'')+
    (r.diversified_score!=null?'<div><span class="lbl">Diverse</span> <span class="val">'+r.diversified_score+'</span></div>':'')+
    (r.novelty_score!=null?'<div><span class="lbl">Novel</span> <span class="val">'+r.novelty_score+'</span></div>':'')+
    '</div>'+
    ((r.reasons&&r.reasons.length)?'<div class="scan-reasons" style="color:var(--down)">✅ '+r.reasons.slice(0,2).join(" ／ ")+'</div>':'')+
    ((r.risk_reason&&r.risk_reason.length)?'<div class="scan-reasons">⚠️ '+r.risk_reason[0]+'</div>':'')+
    (r.repeat_note?'<div class="scan-reasons">🔁 '+r.repeat_note+'</div>':'')+
    '</div>';
}

// ── Auto LINE ──────────────────────────────────────────────────────
function updateAutoUI(){var btn=$I("btnAuto");if(!btn)return;if(autoOn){btn.textContent="已開啟";btn.className="green-btn sm";}else{btn.textContent="已關閉";btn.className="ghost sm";}}
function toggleAuto(){autoOn=!autoOn;if(currentUser)localStorage.setItem("tw_auto_"+currentUser.uid,autoOn?"1":"0");updateAutoUI();if(autoOn)startAutoTimer();else{clearInterval(autoTimer);autoTimer=null;setTxt("autoCountdown","—");}}
function startAutoTimer(){clearInterval(autoTimer);autoLeft=300;autoTimer=setInterval(async function(){autoLeft--;var m=Math.floor(autoLeft/60),s=autoLeft%60;setTxt("autoCountdown",m+":"+(s<10?"0":"")+s);if(autoLeft<=0){autoLeft=300;setTxt("autoLastT",new Date().toLocaleTimeString("zh-TW"));var r=await scanAlerts(true);if(r){setTxt("autoScanned",r.checked+"檔");setTxt("autoPushed",r.sentLine.length+"檔");}}},1000);}

// ── Mobile Fast Data V12.9.2 ──────────────────────────────────────
function isMobileFastMode(){
  try{
    var c=navigator.connection||navigator.mozConnection||navigator.webkitConnection;
    var slow=c && (/2g|3g/.test(c.effectiveType||"") || c.saveData);
    return window.innerWidth<=768 || !!slow;
  }catch(e){return window.innerWidth<=768;}
}
function deferWork(fn,delay){
  if('requestIdleCallback' in window){requestIdleCallback(fn,{timeout:delay||2500});}
  else setTimeout(fn,delay||700);
}
function setMobileSpeed(msg,on){
  var box=$I('mobileSpeedBox'),txt=$I('mobileSpeedText');
  if(!box||!txt)return;
  txt.textContent=msg||'';
  box.classList.toggle('on',!!on);
}
function renderTwMobileFast(d){
  var dash=$I('dash');if(dash){dash.style.display='block';scrollDashMobile(dash);}
  var ai=d.ai_signal||{};
  setTxt('dId',d.stock_id||CURRENT_ID);setTxt('dName',dsn(d.stock_id||CURRENT_ID,d.stock_name));
  setTxt('dDate',d.quote_time?'即時報價：'+d.quote_time:'手機快速報價');
  setTxt('dSource','來源：'+(d.source||'Mobile Fast'));
  var mEl=$I('dMode');if(mEl){mEl.textContent='⚡ 快速';mEl.className='mode-rt';}
  var chg=Number(d.change||0);
  setTxt('dClose',d.price!=null?f(d.price):'—');addCls('dClose',cc(chg));
  setTxt('dChg',d.change!=null?(chg>0?'+':'')+f(d.change)+' ('+pct(d.change_pct)+')':'—');addCls('dChg',cc(chg));
  setTxt('dOpen',d.open!=null?f(d.open):'—');setTxt('dHigh',d.high!=null?f(d.high):'—');setTxt('dLow',d.low!=null?f(d.low):'—');setTxt('dVol',d.volume?fvolLots(d.volume):'—');
  var rtEl=$I('rtInfo');if(rtEl)rtEl.innerHTML='<span class="pill pill-ok">⚡ 手機快速資料</span>';
  var ce=$I('dConc');if(ce){ce.textContent='快速載入完成，完整分析背景更新中';ce.className='conclusion neu';}
  renderAI(ai);
}

function renderTwMobileTech(d){
  renderStockLite(d);
  var mEl=$I('dMode');if(mEl){mEl.textContent='📊 快判';mEl.className='mode-rt';}
  setTxt('dDate',d.quote_time?'技術快判：'+d.quote_time:'手機技術快判');
  var ce=$I('dConc');if(ce){ce.textContent='手機技術快判完成，可先判斷是否接近入場；完整分析與 K 線背景更新中。';ce.className='conclusion neu';}
  setMobileSpeed('📊 手機技術快判已完成，完整 K 線背景載入中…',true);
}
async function loadTwFullAnalysis(id,opts){
  opts=opts||{};
  var d4ES=$I('d4ExpandSection');
  var wakeT=null;
  try{
    if(!opts.silent)showErr('⏳ 載入完整分析中…');
    wakeT=setTimeout(function(){ if(!opts.silent)showErr('⏳ Render 可能正在喚醒，請稍候…'); },12000);
    var r2=await apiFetch(API+'/api/stock/'+id,{},opts.timeout||45000);
    clearTimeout(wakeT);hideErr();
    if(!r2.ok){var ed=await r2.json().catch(function(){return{};});throw new Error(ed.detail||'HTTP '+r2.status);}
    var d2=await r2.json();LAST_TW_DATA=d2;LAST_TW_AI=d2.ai_signal||{};renderStock(d2);
    var ai2=d2.ai_signal||{};
    WL_CACHE[id]={name:d2.stock_name||id,price:(d2.price||{}).close,changePct:(d2.price||{}).change_pct,signal:ai2.signal||null,confidence:ai2.confidence,scoreQuality:ai2.score_quality||'none',entryPrice:ai2.entry_price,targetPrice:ai2.target_price,stopLoss:ai2.stop_loss,entryStatus:ai2.entry_status||'',entryStatusText:ai2.entry_status_text||'',canEnter:ai2.can_enter||false,error:false,noData:false};
    renderWL();checkLineStatus();
    if(opts.mobile){deferWork(function(){renderCandlestickChart(d2.chart_data||[],d2.ai_signal||{});},1200);}else{renderCandlestickChart(d2.chart_data||[],d2.ai_signal||{});}
    if(d4ES)d4ES.style.display='block';
    setMobileSpeed('完整分析已更新',isMobileFastMode());
    setTimeout(function(){if(isMobileFastMode())setMobileSpeed('',false);},1800);
    return d2;
  }catch(e){if(wakeT)clearTimeout(wakeT); if(!opts.silent)showErr('查詢失敗：'+e.message); else setMobileSpeed('完整分析暫時未載入：'+e.message,true); return null;}
}

// ── Main TW search ─────────────────────────────────────────────────
// ── 交易計畫卡 v2（/api/v2/tradeplan）──────────────────────────────
var TP2_LAST=null;
function tp2Get(k,d){try{var v=localStorage.getItem(k);return v==null?d:v;}catch(e){return d;}}
function tp2Set(k,v){try{localStorage.setItem(k,v);}catch(e){}}
function tp2Ack(){try{return sessionStorage.getItem("tp2_ack")==="1";}catch(e){return false;}}
function tp2Copy(v){var live=$I("tp2Live");try{navigator.clipboard.writeText(String(v));if(live)live.textContent="已複製 "+v;toast("已複製 "+v,"ok");}catch(e){if(live)live.textContent="無法複製，請手動輸入 "+v;}}
function tp2Fmt(n){return n==null||isNaN(Number(n))?"—":Number(n).toLocaleString("zh-TW",{maximumFractionDigits:2});}
function tp2MD(s){return s?s.slice(5).replace("-","/"):"—";}
async function loadTradePlanV2(id){
  var card=$I("tp2Card");if(!card)return;
  card.style.display="block";card.innerHTML='<div class="tp2-sub">交易計畫計算中…（第一次查詢約需 10–30 秒）</div>';
  var cap=Number(tp2Get("tp2_capital","0"))||0,risk=Number(tp2Get("tp2_risk","1"))||1;
  var qs="?risk_pct="+risk+(cap>0?"&capital="+cap:"")+feeQS();
  try{
    var r=await apiFetch(API+"/api/v2/tradeplan/"+id+qs,{},45000);
    var d=await r.json();
    if(!r.ok)throw new Error(d.detail||("HTTP "+r.status));
    if(CURRENT_ID!==id)return;
    TP2_LAST=d;renderTradePlanV2(d);
  }catch(e){card.innerHTML='<div class="tp2-sub">交易計畫暫時無法取得：'+esc(e.message)+'</div>';}
}
function renderTradePlanV2(d){
  var card=$I("tp2Card");if(!card)return;
  var p=d.plan,h=d.history||{},rc=d.random_control||{};
  var head='<div class="tp2-head"><span class="tp2-title">交易計畫 · '+esc(d.stock_id)+' '+esc(d.stock_name||"")+(h.n?' <span class="tp2-sub">（歷史 '+h.n+' 筆）</span>':'')+'</span><span class="tp2-chip '+esc(d.status)+'">'+esc(d.status_text)+'</span></div>';
  var warn='<div class="tp2-warn">⚠ '+esc(d.label)+'。最壞情況是停損價被跳空跌破。</div>';
  if(!tp2Ack()){
    card.innerHTML=head+warn+'<div class="tp2-gate"><div class="tp2-sub">這些價位來自固定規則，還沒有證據顯示它能贏過 0050。</div><button class="primary" id="tp2AckBtn">我了解，顯示價位</button></div>';
    var b=$I("tp2AckBtn");if(b)b.onclick=function(){try{sessionStorage.setItem("tp2_ack","1");}catch(e){}renderTradePlanV2(d);};
    return;
  }
  if(!p){card.innerHTML=head+warn;return;}
  function row(lbl,val,sub){return '<div class="tp2-row"><div><div class="tp2-lbl">'+lbl+'</div><div class="tp2-val">'+tp2Fmt(val)+'</div>'+(sub?'<div class="tp2-sub">'+sub+'</div>':'')+'</div><button class="tp2-copy" aria-label="複製'+lbl+' '+val+'" onclick="tp2Copy('+val+')">複製</button></div>';}
  var pos=p.position,posHtml;
  if(pos&&pos.shares>0){
    var parts=[];if(pos.lots)parts.push(pos.lots+' 張（整股下單）');if(pos.odd_shares)parts.push('零股 '+pos.odd_shares+' 股（需用零股下單）');
    posHtml='<div class="tp2-row"><div><div class="tp2-lbl">建議數量（打到停損最多虧總資金 '+pos.risk_pct_of_capital+'%）</div><div class="tp2-val" style="font-size:18px">'+parts.join(' + ')+'</div><div class="tp2-sub">'+(parts.length>1?'要分兩筆委託；':'')+'約 '+tp2Fmt(pos.amount)+' 元；打到停損約虧 '+tp2Fmt(pos.risk_amount)+' 元'+(pos.capped_by?'；'+esc(pos.capped_by):'')+(pos.min_fee_warning?'；'+esc(pos.min_fee_warning):'')+'</div></div></div>';
  }else{posHtml='<div class="tp2-sub" style="margin-top:4px">輸入總資金可算出建議股數。</div>';}
  var cap='<div class="tp2-cap"><label for="tp2Cap">總資金</label><input id="tp2Cap" type="number" inputmode="numeric" min="0" step="10000" value="'+(Number(tp2Get("tp2_capital","0"))||"")+'" placeholder="例如 500000"><label for="tp2Risk">單筆風險 %</label><input id="tp2Risk" type="number" inputmode="decimal" min="0.25" max="5" step="0.25" value="'+(Number(tp2Get("tp2_risk","1"))||1)+'" style="width:70px"><button class="ghost sm" id="tp2CapBtn" style="min-height:44px">重算</button></div>';
  var grid='<div class="tp2-grid">'+
    row("限價買進（不追高）",p.entry,"有效到 "+esc(p.valid_until_md||p.valid_until)+" 收盤，沒成交就取消；開盤已低於停損就不買")+
    row("停損（跌破就賣）",p.stop,"每股風險 "+p.risk_pct+"%")+
    row("目標價（+2R 賣出）",p.target,"收盤站上 "+tp2Fmt(p.breakeven_trigger)+" 後停損移到成本")+
    posHtml+cap+'</div><div id="tp2Live" class="tp2-sub" aria-live="polite" style="min-height:16px"></div>';
  var sell='<div class="tp2-lbl" style="margin-top:6px">什麼時候賣（先到先出）</div><ol class="tp2-sell">'+(p.sell_rules||[]).map(function(s){return'<li>'+esc(s)+'</li>';}).join("")+'</ol>';
  var stats='';
  if(h.n){
    var ci=h.avg_ret_ci95_pct?'95% 區間 '+h.avg_ret_ci95_pct[0]+'% ~ '+h.avg_ret_ci95_pct[1]+'%':'筆數太少，不算區間';
    stats='<div class="tp2-lbl" style="margin-top:10px">同一套規則在此股過去的成績（已扣成本'+(h.sample_ok?'':'，<b style="color:var(--yellow)">樣本不足，只能參考</b>')+'）</div><div class="tp2-stats">'+
      '<div class="tp2-stat">規則每筆平均<b>'+h.avg_ret_pct+'%</b><span class="tp2-sub">'+ci+'</span></div>'+
      '<div class="tp2-stat">隨機進場對照<b>'+(rc.runs?rc.avg_ret_pct+'%':'—')+'</b><span class="tp2-sub">同樣出場規則'+(rc.avg_n?'、約 '+rc.avg_n+' 筆':'')+'</span></div>'+
      '<div class="tp2-stat">勝率 / 平均 R<b>'+h.win_rate+'% / '+h.avg_r+'R</b></div>'+
      '<div class="tp2-stat">最多連虧<b>'+h.max_consec_losses+' 筆</b><span class="tp2-sub">平均持有 '+h.avg_days+' 天</span></div>'+
      '<div class="tp2-stat">規則累積<b>'+h.total_ret_pct+'%</b><span class="tp2-sub">持有 '+(h.exposure_pct==null?'—':h.exposure_pct+'%')+' 的時間</span></div>'+
      '<div class="tp2-stat">同期 0050<b>'+(h.bench_0050_pct==null?'—':h.bench_0050_pct+'%')+'</b><span class="tp2-sub">一直持有、未含息</span></div></div>';
  }else{stats='<div class="tp2-sub" style="margin-top:10px">此股近幾年沒有觸發過這套規則，沒有歷史成績可看。</div>';}
  var levels=grid+sell;
  if(!d.actionable){levels='<details><summary>查看參考價位（'+esc(d.status_text)+'，不建議照此下單）</summary>'+levels+'</details>';}
  var more='<details><summary>規則細節與限制</summary><div class="tp2-sub" style="line-height:1.7">計畫依 '+esc(p.as_of)+' 收盤計算。'+(d.caveats||[]).map(function(c){return'<div>• '+esc(c)+'</div>';}).join("")+'</div></details>';
  card.innerHTML=head+warn+levels+stats+more;
  var cb=$I("tp2CapBtn");if(cb)cb.onclick=function(){var c=$I("tp2Cap"),k=$I("tp2Risk");tp2Set("tp2_capital",c&&c.value?c.value:"0");tp2Set("tp2_risk",k&&k.value?k.value:"1");loadTradePlanV2(d.stock_id);};
}

async function doSearch() {
  if(!currentUser) return;
  var inp=$I("sid"),id=inp?inp.value.trim().toUpperCase():"";
  if(!/^\d{4,6}[A-Z]?$/.test(id)){showErr("請輸入股票代號，例如 2330 或 00631L");return;}
  clearTimeout(suggestTimer);_dashScrolledFor=null;var box=$I("suggestBox");if(box)box.style.display="none";
  hideErr();CURRENT_ID=id;var btId=$I("btId");if(btId)btId.value=id;
  loadTradePlanV2(id);
  var d4ES=$I("d4ExpandSection");if(d4ES)d4ES.style.display="none";
  var d4C=$I("d4Container");if(d4C){d4C.classList.remove("open");d4C.innerHTML="";}
  var d4NS=$I("d4NewsSection");if(d4NS)d4NS.style.display="none";
  var dash=$I("dash");if(dash)dash.style.display="none";
  destroyChart();

  var mobile=isMobileFastMode();
  if(mobile){
    setMobileSpeed("手機快速模式：先載入即時報價，再快速載入技術快判，完整 K 線背景更新中…",true);
    try{
      var rm=await apiFetch(API+"/api/stock-mobile/"+id,{},8000);
      if(rm.ok){var dm=await rm.json();LAST_TW_DATA=dm;LAST_TW_AI=dm.ai_signal||{};renderTwMobileFast(dm);}
    }catch(e){setMobileSpeed("快速報價暫時失敗，改用一般載入…",true);}
    try{
      setMobileSpeed("📊 手機技術快判載入中：先判斷入場、RR、MA/RSI/MACD…",true);
      var rt=await apiFetch(API+"/api/stock-mobile-tech/"+id,{},14000);
      if(rt.ok){var dt=await rt.json();LAST_TW_DATA=dt;LAST_TW_AI=dt.ai_signal||{};renderTwMobileTech(dt);WL_CACHE[id]={name:dt.stock_name||id,price:dt.price,changePct:dt.change_pct,signal:(dt.ai_signal||{}).signal||null,confidence:(dt.ai_signal||{}).confidence,scoreQuality:(dt.ai_signal||{}).score_quality||"mobile_technical",entryPrice:(dt.ai_signal||{}).entry_price,targetPrice:(dt.ai_signal||{}).target_price,stopLoss:(dt.ai_signal||{}).stop_loss,entryStatus:(dt.ai_signal||{}).entry_status||"",entryStatusText:(dt.ai_signal||{}).entry_status_text||"",canEnter:(dt.ai_signal||{}).can_enter||false,error:false,noData:false};renderWL();}
    }catch(e){
      try{var rl=await apiFetch(API+"/api/stock-lite/"+id,{},12000);if(rl.ok){var dl=await rl.json();LAST_TW_DATA=dl;LAST_TW_AI=dl.ai_signal||{};renderStockLite(dl);WL_CACHE[id]={name:dl.stock_name||id,price:dl.price,changePct:dl.change_pct,signal:(dl.ai_signal||{}).signal||null,confidence:(dl.ai_signal||{}).confidence,scoreQuality:(dl.ai_signal||{}).score_quality||"none",entryPrice:(dl.ai_signal||{}).entry_price,targetPrice:(dl.ai_signal||{}).target_price,stopLoss:(dl.ai_signal||{}).stop_loss,entryStatus:(dl.ai_signal||{}).entry_status||"",entryStatusText:(dl.ai_signal||{}).entry_status_text||"",canEnter:(dl.ai_signal||{}).can_enter||false,error:false,noData:false};renderWL();}}catch(e2){}
    }
    deferWork(function(){loadTwFullAnalysis(id,{silent:true,mobile:true,timeout:45000});},1800);
    return;
  }

  // Desktop / tablet normal flow: lite first, then full analysis.
  try {
    var rl2=await apiFetch(API+"/api/stock-lite/"+id,{},20000);
    if(rl2.ok){var dl2=await rl2.json();LAST_TW_DATA=dl2;LAST_TW_AI=dl2.ai_signal||{};renderStockLite(dl2);WL_CACHE[id]={name:dl2.stock_name||id,price:dl2.price,changePct:dl2.change_pct,signal:(dl2.ai_signal||{}).signal||null,confidence:(dl2.ai_signal||{}).confidence,scoreQuality:(dl2.ai_signal||{}).score_quality||"none",entryPrice:(dl2.ai_signal||{}).entry_price,targetPrice:(dl2.ai_signal||{}).target_price,stopLoss:(dl2.ai_signal||{}).stop_loss,entryStatus:(dl2.ai_signal||{}).entry_status||"",entryStatusText:(dl2.ai_signal||{}).entry_status_text||"",canEnter:(dl2.ai_signal||{}).can_enter||false,error:false,noData:false};renderWL();}
  } catch(e) {}
  await loadTwFullAnalysis(id,{silent:false,mobile:false,timeout:45000});
}


function normalizeTwIndicators(d){
  // V12.9.2: backend now returns indicators directly; this fallback keeps old cached responses usable.
  var ind=(d&&d.indicators)||{};
  var cd=(d&&Array.isArray(d.chart_data))?d.chart_data:[];
  var last=cd.length?cd[cd.length-1]:{};
  function pick(){for(var i=0;i<arguments.length;i++){var v=arguments[i]; if(v!==undefined&&v!==null&&v!==""&&!Number.isNaN(Number(v)))return v;} return null;}
  return {
    ma5:pick(ind.ma5,last.ma5), ma20:pick(ind.ma20,last.ma20), ma60:pick(ind.ma60,last.ma60),
    rsi:pick(ind.rsi,last.rsi), macd:pick(ind.macd,last.macd), signal:pick(ind.signal,ind.signal_line,last.signal_line,last.signal),
    hist:pick(ind.hist,last.hist), bb_upper:pick(ind.bb_upper,last.bb_upper), bb_lower:pick(ind.bb_lower,last.bb_lower),
    atr:pick(ind.atr,last.atr), adx:pick(ind.adx,last.adx)
  };
}

function renderStockLite(d) {
  var dash=$I("dash");if(dash){dash.style.display="block";scrollDashMobile(dash);}
  var ai=d.ai_signal||{},rt=d.realtime_quote||{};
  setTxt("dId",d.stock_id);setTxt("dName",dsn(d.stock_id,d.stock_name));
  setTxt("dSource",(d.source||d.data_source)?"來源："+(d.source||d.data_source):"載入中…");
  var chg=d.change||0; setTxt("dClose",d.price!=null?f(d.price):"—");addCls("dClose",cc(chg));
  setTxt("dChg",d.change!=null?(chg>0?"+":"")+f(d.change)+" ("+pct(d.change_pct)+")":"—");addCls("dChg",cc(chg));
  var ce=$I("dConc");if(ce){ce.textContent=d.mobile_technical?"手機技術快判完成：可先看 AI 入場、RR、MA/RSI/MACD；完整 K 線背景載入中。":"載入中…";ce.className="conclusion neu";}
  var rtEl=$I("rtInfo");if(rtEl)rtEl.innerHTML=rt&&rt.price!=null?'<span class="pill pill-ok">⚡ '+(rt.source||"TWSE MIS")+'</span>':(d.mobile_technical?'<span class="pill pill-ok">📊 手機技術快判</span>':'<span class="pill pill-warn">休市或無成交</span>');
  if(d.indicators){
    var ind=normalizeTwIndicators(d);
    setTxt("dMa5",f(ind.ma5));setTxt("dMa20",f(ind.ma20));setTxt("dMa60",f(ind.ma60));
    setTxt("dRsi",f(ind.rsi));addCls("dRsi",ind.rsi>50?"up":"down");
    setTxt("dMacd",f(ind.macd,4));setTxt("dSig",f(ind.signal,4));setTxt("dHist",f(ind.hist,4));
    addCls("dHist",ind.hist>0?"up":"down");addCls("dMacd",ind.macd>ind.signal?"up":"down");
    setTxt("dBbU",f(ind.bb_upper));setTxt("dBbL",f(ind.bb_lower));
    var sc=d.score||{};var scoreVal=(sc.score!==undefined&&sc.score!==null)?Number(sc.score):Math.round(((ai&&ai.technical_score)||0)/20);
    if(!Number.isFinite(scoreVal))scoreVal=0;scoreVal=Math.max(0,Math.min(5,scoreVal));setTxt("dScore",scoreVal);addCls("dScore",scoreVal>=4?"up":scoreVal<=2?"down":"flat");
    var dots=$I("scoreDots");if(dots){dots.innerHTML="";for(var i=0;i<5;i++){var dt=document.createElement("div");dt.className="dot"+(i<scoreVal?" on":"");dots.appendChild(dt);}}
    var srEl=$I("scoreReasons");if(srEl)srEl.innerHTML=(sc.reasons||["手機技術快判已完成"]).map(function(r){return'<div class="reason">'+r+'</div>';}).join("");
  }
  renderAI(ai);
}

function renderStock(d) {
  var p=d.price||{},vol=d.volume||{},rt=d.realtime_quote||null,ai=d.ai_signal||{};
  if(d.data_warning)showErr(d.data_warning);
  setTxt("dId",d.stock_id);setTxt("dName",dsn(d.stock_id,d.stock_name));
  setTxt("dDate","資料日期："+d.last_date);setTxt("dSource",d.data_source?"來源："+d.data_source:"");
  var mEl=$I("dMode");if(mEl){mEl.textContent=p.mode==="realtime"?"⚡ 即時":"📅 日線";mEl.className=p.mode==="realtime"?"mode-rt":"mode-daily";}
  var cE=$I("dConc");if(cE){var conc=d.conclusion||"";cE.textContent=conc;cE.className="conclusion "+(conc.includes("偏多")?"bull":conc.includes("偏弱")?"bear":"neu");}
  var chg=p.change||0;setTxt("dClose",f(p.close));addCls("dClose",cc(chg));
  setTxt("dChg",(chg>0?"+":"")+f(p.change)+" ("+pct(p.change_pct)+")");addCls("dChg",cc(chg));
  setTxt("dOpen",f(p.open));
  var hiEl=$I("dHigh");if(hiEl){hiEl.textContent=f(p.high);hiEl.className="up";}
  var loEl=$I("dLow");if(loEl){loEl.textContent=f(p.low);loEl.className="down";}
  setTxt("dVol",vol.latest_volume?fvol(vol.latest_volume):(rt&&rt.volume?fvolLots(rt.volume):"—"));
  var rtEl=$I("rtInfo");if(rtEl)rtEl.innerHTML=rt&&rt.price!=null?'<span class="pill pill-ok">⚡ '+(rt.source||"TWSE MIS")+'</span>':'<span class="pill pill-warn">休市，顯示日線</span>';
  var vaEl=$I("volAlert");if(vaEl)vaEl.innerHTML=vol.alert?'<span class="pill pill-warn">⚠️ 成交量異常放大（'+vol.ratio+'x）</span>':'<span class="pill pill-ok">成交量正常（'+(vol.ratio||1)+'x）</span>';
  var ra=$I("rsiAlert");if(ra)ra.innerHTML=d.rsi_alert?'<span class="pill '+((d.rsi_alert||"").includes("過熱")?"pill-hot":"pill-warn")+'">'+d.rsi_alert+'</span>':"";
  var ind=normalizeTwIndicators(d);
  setTxt("dMa5",f(ind.ma5));setTxt("dMa20",f(ind.ma20));setTxt("dMa60",f(ind.ma60));
  setTxt("dRsi",f(ind.rsi));addCls("dRsi",ind.rsi>50?"up":"down");
  setTxt("dMacd",f(ind.macd,4));setTxt("dSig",f(ind.signal,4));setTxt("dHist",f(ind.hist,4));
  addCls("dHist",ind.hist>0?"up":"down");addCls("dMacd",ind.macd>ind.signal?"up":"down");
  setTxt("dBbU",f(ind.bb_upper));setTxt("dBbL",f(ind.bb_lower));
  var sc=d.score||{};
  var scoreVal=(sc.score!==undefined&&sc.score!==null)?Number(sc.score):Math.round(((ai&&ai.technical_score)||0)/20);
  if(!Number.isFinite(scoreVal))scoreVal=0; scoreVal=Math.max(0,Math.min(5,scoreVal));
  setTxt("dScore",scoreVal);
  addCls("dScore",scoreVal>=4?"up":scoreVal<=2?"down":"flat");
  var dots=$I("scoreDots");if(dots){dots.innerHTML="";for(var i=0;i<5;i++){var dt=document.createElement("div");dt.className="dot"+(i<scoreVal?" on":"");dots.appendChild(dt);}}
  var scoreReasons=(sc.reasons&&sc.reasons.length)?sc.reasons:((ai&&ai.technical_breakdown)?["技術分 "+(ai.technical_score||0)+"/100"]:[]);
  var srEl=$I("scoreReasons");if(srEl)srEl.innerHTML=scoreReasons.map(function(r){return'<div class="reason">'+r+'</div>';}).join("");
  var bt=d.backtest||{};setTxt("dWr",bt.trials?(bt.winrate||0)+"%":"—");addCls("dWr",bt.winrate>=60?"up":bt.winrate<45?"down":"flat");
  setTxt("dWrSub",bt.trials?"近一年回測結果":"樣本不足");setTxt("dTrials",bt.trials||0);setTxt("dWins",bt.wins||0);
  renderAI(ai);
  killCJCharts();mkCJCharts(d.chart_data||[]);
  var dash=$I("dash");if(dash){dash.style.display="block";scrollDashMobile(dash);}
}

function renderAI(ai) {
  LAST_TW_AI=ai||LAST_TW_AI;
  var badge=$I("aiBadge");if(badge)badge.className="ai-block "+(ai.signal==="BUY"?"ai-buy":ai.signal==="AVOID"?"ai-avoid":"ai-watch");
  setTxt("aiLabel",sigIcon(ai.signal||"WATCH"));setTxt("aiConf","技術面評分 "+(ai.confidence||0)+" / 100");
  var barEl=$I("confBar");if(barEl){barEl.style.width=(ai.confidence||0)+"%";barEl.style.background=(ai.confidence||0)>=75?"var(--up)":(ai.confidence||0)>=55?"var(--yellow)":"var(--down)";}
  setTxt("aiEp",ai.entry_price!=null?f(ai.entry_price):"—");setTxt("aiTp",ai.target_price!=null?f(ai.target_price):"—");setTxt("aiSl",ai.stop_loss!=null?f(ai.stop_loss):"—");
  var rrEl=$I("aiRr");if(rrEl){if(ai.risk_reward_ratio!=null){rrEl.textContent=ai.risk_reward_ratio+"x";rrEl.className="aiq-val "+((ai.risk_reward_ratio>=1.5)?"up":"down");}else{rrEl.textContent="—";rrEl.className="aiq-val";}}
  setTxt("aiSummary",ai.summary||"—");
  var tsEl=$I("tradeStatusBadge");if(tsEl){var ts=ai.trade_status||"WATCH";var tsL={"BUY_NOW":"舊評分偏多（看交易計畫卡）","BUY_PULLBACK":"⏳ 等回檔","WATCH":"👀 觀望","AVOID":"不符合"};tsEl.textContent=tsL[ts]||ts;tsEl.className="ts-badge ts-"+ts;}
  var esEl=$I("entryStatusBadge");if(esEl){var es=ai.entry_status||"";if(es){esEl.innerHTML='<span class="es-'+es+'">'+(ai.entry_status_text||es)+'</span>';}else esEl.innerHTML="";}
  var aeEl=$I("aiEntry");if(aeEl)aeEl.innerHTML=(ai.entry_reason||[]).length?(ai.entry_reason.map(function(r){return'<div class="reason" style="color:var(--down)">✅ '+r+'</div>';}).join("")):'<div class="reason">—</div>';
  var arEl=$I("aiRisk");if(arEl)arEl.innerHTML=(ai.risk_reason||[]).length?(ai.risk_reason.map(function(r){return'<div class="reason" style="color:var(--up)">⚠️ '+r+'</div>';}).join("")):'<div class="reason" style="color:var(--muted)">暫無明顯風險</div>';
  setTxt("aiDisc",ai.disclaimer||"");
  var terEl=$I("tooExtendedReasons");if(terEl){var reasons=ai.too_extended_reasons||[];terEl.innerHTML=reasons.length?reasons.map(function(r){return'<div class="reason">🚫 '+r+'</div>';}).join(""):"";terEl.style.display=reasons.length?"block":"none";}
  renderTradePlanV4(ai);
}

function renderTradePlanV4(ai) {
  var tpBox=$I("tradePlanBox"); if(!tpBox) return;
  var ez_lo=ai.entry_zone_low,ez_hi=ai.entry_zone_high,sup=ai.recent_support,res=ai.recent_resistance,strat=ai.strategy_type||"";
  var fs=ai.final_score;
  if(ez_lo||sup||res||strat){
    tpBox.style.display="block";
    setTxt("tpEntryZone",(ez_lo&&ez_hi)?f(ez_lo)+" ~ "+f(ez_hi):"—");
    setTxt("tpSupport",sup?f(sup):"—");setTxt("tpResistance",res?f(res):"—");
    setTxt("tpStrategy",({"Trend Following":"順勢","Pullback Entry":"拉回進場","Reversal Bounce":"超跌反彈","Range Bound":"區間盤整","ETF Trend":"ETF 趨勢"})[strat]||strat||"—");setTxt("tpFinalScore",fs!=null?fs+"/100":"—");
  } else tpBox.style.display="none";
  if(ai.trade_valid===false&&ai.signal==="BUY"){var s=$I("aiSummary");if(s)s.textContent="⚠️ 交易點位暫不合理，建議觀察。"+(ai.summary||"");}
  if(ai.trade_valid===false){var rrEl=$I("aiRr");if(rrEl){rrEl.textContent="—";rrEl.className="aiq-val";}}
}

// ── TW Lightweight Charts K-line ────────────────────────────────────
function destroyChart() {
  if(lwChart){try{lwChart.remove();}catch{}lwChart=null;}
}

function renderCandlestickChart(chartData, aiSignal) {
  var wrap=$I("klineWrap"),container=$I("klineContainer"); if(!wrap||!container) return;
  if(!chartData||!chartData.length){wrap.style.display="none";return;}
  wrap.style.display="block";destroyChart();
  var ph=container.querySelector(".kline-placeholder");if(ph)ph.remove();
  try {
    if(typeof LightweightCharts==="undefined"){wrap.style.display="none";return;}
    var h=window.innerWidth<=768?320:420; container.style.height=h+"px";
    lwChart=LightweightCharts.createChart(container,{
      width:container.offsetWidth,height:h,
      layout:{background:{color:"#0d1728"},textColor:"#6f86a8"},
      grid:{vertLines:{color:"rgba(29,49,80,.5)"},horzLines:{color:"rgba(29,49,80,.5)"}},
      crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
      rightPriceScale:{borderColor:"#1d3150"},timeScale:{borderColor:"#1d3150",timeVisible:true},
    });
    // TW: red=up, green=down
    var cs=lwChart.addCandlestickSeries({upColor:"#e8384f",downColor:"#00b86b",borderUpColor:"#e8384f",borderDownColor:"#00b86b",wickUpColor:"#e8384f",wickDownColor:"#00b86b"});
    var cd=chartData.filter(function(d){return d.open&&d.high&&d.low&&d.close;}).map(function(d){return{time:d.date,open:d.open,high:d.high,low:d.low,close:d.close};});
    if(cd.length)cs.setData(cd);
    // MAs
    [[function(d){return d.ma5;},"#fbbf24",0],[function(d){return d.ma20;},"#f97316",0],[function(d){return d.ma60;},"#e8384f",2]].forEach(function(m){var s=lwChart.addLineSeries({color:m[1],lineWidth:1,lineStyle:m[2],priceLineVisible:false});s.setData(chartData.filter(function(d){return m[0](d)!=null;}).map(function(d){return{time:d.date,value:m[0](d)};}));});
    // Trade lines
    var ai=aiSignal||{};
    if(ai.trade_valid!==false&&cd.length){
      if(ai.entry_price)cs.createPriceLine({price:ai.entry_price,color:"#fbbf24",lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:"入場"});
      if(ai.target_price)cs.createPriceLine({price:ai.target_price,color:"#e8384f",lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:"目標"});
      if(ai.stop_loss)cs.createPriceLine({price:ai.stop_loss,color:"#00b86b",lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:"停損"});
    }
    // Support / resistance
    if(cd.length){
      if(ai.recent_support){var sl=lwChart.addLineSeries({color:"rgba(59,130,246,.5)",lineWidth:1,lineStyle:3,priceLineVisible:false});sl.setData([{time:cd[0].time,value:ai.recent_support},{time:cd[cd.length-1].time,value:ai.recent_support}]);}
      if(ai.recent_resistance){var rl=lwChart.addLineSeries({color:"rgba(100,116,139,.4)",lineWidth:1,lineStyle:3,priceLineVisible:false});rl.setData([{time:cd[0].time,value:ai.recent_resistance},{time:cd[cd.length-1].time,value:ai.recent_resistance}]);}
    }
    // Volume
    var vs=lwChart.addHistogramSeries({color:"rgba(255,210,63,.3)",priceFormat:{type:"volume"},priceScaleId:"vol",scaleMargins:{top:0.8,bottom:0}});
    var vd=chartData.filter(function(d){return d.volume!=null&&d.close!=null;}).map(function(d){return{time:d.date,value:d.volume,color:d.close>=(d.open||d.close)?"rgba(232,56,79,.4)":"rgba(0,184,107,.4)"};});
    if(vd.length)vs.setData(vd);
    lwChart.timeScale().fitContent();
    setTxt("klineStatus",cd.length+" 根");
    try{var ro=new ResizeObserver(function(){if(lwChart&&container)lwChart.applyOptions({width:container.offsetWidth});});ro.observe(container);}catch{}
  } catch(e) { console.warn("kline:",e.message); wrap.style.display="none"; }
}

// ── TW 4D ──────────────────────────────────────────────────────────
async function load4d() {
  if(!currentUser||!CURRENT_ID){alert("請先查詢股票");return;}
  var container=$I("d4Container");if(container)container.classList.add("open");
  if(container)container.innerHTML='<div style="font-family:var(--mono);font-size:12px;color:var(--muted);padding:12px;text-align:center">四面向分析載入中…</div>';
  setTxt("btnLoad4d","🔄 重新載入");
  try {
    var r=await apiFetch(API+"/api/analysis-4d/"+CURRENT_ID,{},90000);
    if(!r.ok)throw new Error("四面向分析失敗");
    var d=await r.json();
    if(container)render4D(d.analysis_4d,d.news||[],container,d.ai_signal||{});
    var ns=$I("d4NewsSection");if(ns)ns.style.display="block";
    var nd=$I("d4News");if(nd)nd.innerHTML=renderNews(d.news||[]);
  } catch(e) { if(container)container.innerHTML='<div style="font-family:var(--mono);font-size:12px;padding:12px;color:var(--up)">⚠️ 四面向分析暫時無法取得：'+e.message+'</div>'; }
}

function render4D(a4,news,container,aiSig) {
  if(!a4){if(container)container.innerHTML='<div style="color:var(--muted);font-family:var(--mono);font-size:12px;padding:12px">四面向資料不可用</div>';return;}
  var fu=a4.fundamental||{},te=a4.technical||{},ch=a4.chip||{},nw=a4.news||{},ov=a4.overall||{};
  var ai=aiSig||{};
  var conf=ai.confidence||0; var barC=conf>=75?"var(--up)":conf>=55?"var(--yellow)":"var(--down)";
  var html='<div style="background:#0d1728;border:2px solid rgba(251,191,36,.3);border-radius:12px;padding:14px;margin-bottom:12px">'+
    '<div style="font-family:var(--mono);font-size:11px;color:var(--muted);margin-bottom:8px">🤖 四面向綜合交易建議</div>'+
    '<div style="display:flex;gap:12px;flex-wrap:wrap">'+
    '<div style="min-width:120px"><div class="ai-label">'+sigIcon(ai.signal||"WATCH")+'</div><div class="ai-conf">技術面評分 '+conf+' / 100</div>'+
    '<div style="height:5px;background:#172946;border-radius:3px;margin-top:8px;overflow:hidden"><div style="width:'+conf+'%;height:100%;background:'+barC+';border-radius:3px;transition:width .6s"></div></div></div>'+
    '<div style="flex:1;min-width:180px"><div style="display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-bottom:8px">'+
    '<div class="aiq"><div class="aiq-lbl">入場</div><div class="aiq-val">'+(ai.entry_price!=null?f(ai.entry_price):"—")+'</div></div>'+
    '<div class="aiq"><div class="aiq-lbl">目標</div><div class="aiq-val up">'+(ai.target_price!=null?f(ai.target_price):"—")+'</div></div>'+
    '<div class="aiq"><div class="aiq-lbl">停損</div><div class="aiq-val down">'+(ai.stop_loss!=null?f(ai.stop_loss):"—")+'</div></div>'+
    '<div class="aiq"><div class="aiq-lbl">RR</div><div class="aiq-val">'+(ai.risk_reward_ratio!=null?ai.risk_reward_ratio+"x":"—")+'</div></div>'+
    '</div><div style="font-size:12px;color:var(--muted);line-height:1.6">'+(ai.summary||"—")+'</div></div></div></div>';
  var ovScore=ov.overall_score;
  html+='<div style="background:#0d1728;border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:12px">'+
    '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'+
    '<div style="font-family:var(--mono);font-size:28px;font-weight:800" class="'+(ovScore!=null?(ovScore>=65?"up":ovScore>=50?"flat":"down"):"")+'">'+(ovScore!=null?Math.round(ovScore):"—")+'</div>'+
    '<div><div style="font-family:var(--mono);font-size:13px;font-weight:700">'+(ov.rating||"—")+'</div><div style="font-family:var(--mono);font-size:10px;color:var(--muted)">四面向加權總分</div></div></div>'+
    '<div style="font-size:12px;color:var(--muted)">'+(ov.summary||"")+'</div></div>';
  html+='<div class="d4-grid">';
  var cards=[
    {label:"💰 基本面",icon:"#3b82f6",data:fu},{label:"📈 技術面",icon:"var(--cyan)",data:te},
    {label:"🏦 籌碼面",icon:"var(--purple)",data:ch},{label:"📰 消息面",icon:"var(--yellow)",data:nw}
  ];
  cards.forEach(function(c){
    var s=c.data.score,rat=c.data.rating||"資料不足",p2=s!=null?Math.min(100,s):0;
    html+='<div class="d4-card"><div class="d4-card-title">'+c.label+'</div>'+
      '<div style="display:flex;align-items:center"><span class="d4-score '+(s!=null?(s>=70?"up":s>=50?"flat":"down"):"")+'">'+(s!=null?Math.round(s):"—")+'</span><span style="font-family:var(--mono);font-size:11px;color:var(--muted)">'+rat+'</span></div>'+
      '<div class="d4-bar"><div class="d4-bar-fill" style="width:'+p2+'%;background:'+c.icon+'"></div></div>'+
      '<div class="d4-reasons">'+(c.data.reasons||[]).slice(0,3).map(function(r){return'<div>✅ '+r+'</div>';}).join("")+(c.data.risks||[]).slice(0,2).map(function(r){return'<div style="color:var(--up)">⚠️ '+r+'</div>';}).join("")+'</div></div>';
  });
  html+='</div>';
  if(container)container.innerHTML=html;
}

function renderNews(news) {
  if(!news||!news.length)return'<div style="color:var(--muted);font-family:var(--mono);font-size:12px;padding:8px">暫無即時新聞資料</div>';
  return news.map(function(n){var cls=n.sentiment==="利多"?"s-bull":n.sentiment==="利空"?"s-bear":"s-neu";return'<div class="news-item"><a href="'+n.link+'" target="_blank" rel="noopener">'+n.title+'</a><div class="news-meta"><span class="stag '+cls+'">'+n.sentiment+'</span><span>'+fmtD(n.pub_date)+'</span></div></div>';}).join("");
}

// ── TW Macro ───────────────────────────────────────────────────────
async function loadMacro() {
  if(!currentUser) return;
  var grid=$I("macroGrid");if(!grid)return;
  grid.innerHTML='<div class="macro-item"><div class="macro-label">載入中</div><div class="macro-val">…</div></div>';
  try {
    var r=await apiFetch(API+"/api/macro",{},12000);var d=await r.json();
    var items=[{label:"USD/TWD",key:"usd_twd",dd:3},{label:"DXY 美元",key:"dxy",dd:2},{label:"NASDAQ Fut",key:"nasdaq_futures",dd:0},{label:"SOX",key:"sox",dd:0},{label:"美債10Y%",key:"us10y",dd:2}];
    grid.innerHTML=items.map(function(it){var v=d[it.key];return'<div class="macro-item"><div class="macro-label">'+it.label+'</div><div class="macro-val">'+(v!=null?Number(v).toFixed(it.dd):"—")+'</div></div>';}).join("");
    var noteEl=$I("macroNote");if(noteEl){var adj=d.macro_adj||0;noteEl.textContent=(d.risk_note||"")+(adj?"  宏觀調整："+(adj>0?"+":"")+adj:"");noteEl.style.color=adj>=0?"var(--down)":"var(--up)";}
  } catch(e) { if(grid)grid.innerHTML='<div class="macro-item"><div class="macro-label" style="color:var(--muted)">宏觀資料暫時無法取得</div></div>'; }
}

async function loadSentiment() {
  if(!currentUser) return;
  try {
    var r=await apiFetch(API+"/api/market-sentiment",{},30000);var d=await r.json();
    setTxt("sentLabel",d.sentiment||"—");
    var bar=$I("sentBar");if(bar){bar.style.width=(d.buy_pct||0)+"%";bar.style.background=d.buy_pct>=50?"var(--up)":"var(--down)";}
    setTxt("sentDetail",d.total?("偏多 "+d.buy_count+"／觀察 "+d.watch_count+"／避開 "+d.avoid_count+"（共掃描 "+d.total+" 檔）"):"尚無資料：先在個股頁查詢或執行選股");
  } catch(e) {}
}

// ── LINE ───────────────────────────────────────────────────────────
async function checkLineStatus() {
  try {
    var r=await apiFetch(API+"/health",{},10000),d=await r.json();
    var dot=$I("lineDot"),txt=$I("lineStatusTxt");
    if(d.line_configured&&d.line_enabled){if(dot)dot.style.cssText="background:var(--down);box-shadow:0 0 8px var(--down)";if(txt){txt.textContent="LINE 通知已啟用";txt.style.color="var(--down)";}}
    else{if(dot)dot.style.cssText="background:var(--muted);box-shadow:none";if(txt){txt.textContent=d.line_configured?"LINE 已設定但未啟用":"LINE 尚未設定";txt.style.color="var(--muted)";}}
  } catch(e) {}
}
async function testLine() {
  var r2=$I("lineResult");if(r2){r2.textContent="發送中…";r2.style.color="var(--muted)";}
  try{var res=await apiFetch(API+"/api/alerts/test",{method:"POST"},20000),d=await res.json();if(r2){r2.textContent=res.ok?"✅ "+d.message:"❌ "+d.detail;r2.style.color=res.ok?"var(--down)":"var(--up)";}}
  catch(e){if(r2){r2.textContent="❌ "+e.message;r2.style.color="var(--up)";}}
}

// ── TW Backtest ────────────────────────────────────────────────────
async function runBt() {
  var idEl=$I("btId"),dEl=$I("btDays"),sEl=$I("btScore");
  var id=(idEl?idEl.value.trim():"")||CURRENT_ID;var days=dEl?dEl.value:5;var score=sEl?sEl.value:75;
  if(!id||!/^\d{4,6}[A-Z]?$/.test(id)){alert("請輸入正確股票代號");return;}
  var loading=$I("btLoading"),result=$I("btResult");
  if(loading)loading.style.display="block";if(result)result.style.display="none";
  try {
    var r=await apiFetch(API+"/api/backtest/"+id+"?holding_days="+days+"&min_score="+score+"&lookback_days=400"+feeQS(),{},90000);
    var d=await r.json();if(!r.ok)throw new Error(d.detail||"回測失敗");var res=d.result;
    setTxt("btWr",res.winrate+"%");setTxt("btAvg",(res.avg_return>=0?"+":"")+res.avg_return+"%");setTxt("btDd","-"+res.max_drawdown+"%");setTxt("btPf",res.profit_factor+"x");
    setTxt("btTotal",res.total_trades+"筆");setTxt("btWl",res.wins+" / "+res.losses);setTxt("btBest","+"+res.best_return+"%");setTxt("btWorst",res.worst_return+"%");
    addCls("btWr",res.winrate>=60?"up":res.winrate<45?"down":"flat");addCls("btAvg",res.avg_return>0?"up":"down");
    var tbEl=$I("btTrades");if(tbEl)tbEl.innerHTML=(d.trades||[]).map(function(t){return'<tr class="'+(t.win?"win":"loss")+'"><td>'+t.date+'</td><td>'+f(t.entry_price)+'</td><td>'+f(t.exit_price)+'</td><td class="'+(t.return_pct>=0?"up":"down")+'">'+(t.return_pct>=0?"+":"")+t.return_pct+'%</td><td>'+t.confidence+'</td><td>'+t.signal+'</td></tr>';}).join("");
    if(result)result.style.display="block";
  } catch(e){alert("回測失敗："+e.message);}
  finally{if(loading)loading.style.display="none";}
}

// ── V12.9.2 Multi-Portfolio Watchlist Manager ───────────────────────────────────
var LAST_LEARNING_SUMMARY=null, LAST_SUGGESTED_WEIGHTS=null;
function getLearningMarket(){var el=$I('learnMarket');return (el&&el.value)||currentMarket||'tw';}
function baseWeightsForMarket(m){return m==='us'?{technical:0.40,market_context:0.25,fundamental:0.15,risk:0.15,news:0.05}:{technical:0.35,fundamental:0.25,chip:0.25,news:0.15};}
function weightLabels(m){return m==='us'?{technical:'技術面',market_context:'市場環境',fundamental:'基本面',risk:'風控',news:'消息'}:{technical:'技術面',fundamental:'基本面',chip:'籌碼面',news:'消息面'};}
async function getPersonalWeights(m){if(!currentUser||!db)return baseWeightsForMarket(m);try{var ref=aiWeightVersionRef(currentUser.uid,m);var s=await ref.get();var d=s.exists?s.data():{};return d.current_weights||baseWeightsForMarket(m);}catch(e){return baseWeightsForMarket(m);}}
async function savePersonalWeights(m,w,reason){if(!currentUser||!db)return;var ref=aiWeightVersionRef(currentUser.uid,m);var s=await ref.get();var d=s.exists?s.data():{};var hist=Array.isArray(d.history)?d.history:[];hist.unshift({created_at:new Date().toISOString(),weights:w,reason:reason||'',market:m});hist=hist.slice(0,30);await ref.set({market:m,current_weights:w,history:hist,updated_at:new Date().toISOString()},{merge:true});}
async function loadLearningEvents(m){if(!currentUser||!db)return[];try{var ref=learningEventsRef(currentUser.uid,m);var s=await ref.get();var d=s.exists?s.data():{};return Array.isArray(d.events)?d.events:[];}catch(e){console.warn('load learning events',e);return[];}}
async function saveLearningEvents(m,events){if(!currentUser||!db)return;try{var ref=learningEventsRef(currentUser.uid,m);await ref.set({market:m,events:(events||[]).slice(0,700),updated_at:new Date().toISOString()},{merge:true});}catch(e){console.warn('save learning events',e);}}
function eventKey(e){return [e.market,e.symbol||e.stock_id,e.event_type,e.scan_category,e.created_at&&String(e.created_at).slice(0,10)].join(':');}
function candidateToLearningEvent(m,it,cat,source){var sym=String(it.symbol||it.stock_id||'').toUpperCase();if(!sym)return null;return{market:m,symbol:sym,stock_id:it.stock_id||sym,name:it.name||it.stock_name||sym,event_type:'scan_candidate',source:source||'ai_scan',signal:it.signal||'WATCH',scan_category:(it.scan_category||cat||'NEAR_MISS').toUpperCase(),strategy_type:it.strategy_type||'Unclassified',entry_price:num(it.entry_price),entry_zone_low:num(it.entry_zone_low),entry_zone_high:num(it.entry_zone_high),target_price:num(it.target_price),stop_loss:num(it.stop_loss),rr:num(it.risk_reward_ratio),confidence:num(it.confidence),technical_score:num(it.technical_score),final_score:num(it.final_score),risk_score:num(it.risk_score),market_score:num(it.market_score),created_at:new Date().toISOString(),evaluated:false,result:null};}
async function recordLearningEventsFromScan(m,d){if(!currentUser||!db||!d)return;try{var zones=['enterable','watch_closely','fresh_discovery','pullback','breakout_watch','near_miss','risk_watch'];var add=[];zones.forEach(function(z){(d[z]||[]).slice(0,20).forEach(function(it){var ev=candidateToLearningEvent(m,it,z,'ai_scan_'+(d.diversity_mode||d.scan_mode||''));if(ev)add.push(ev);});});if(!add.length)return;var old=await loadLearningEvents(m);var merged=add.concat(old||[]);var seen={};merged=merged.filter(function(e){var k=eventKey(e);if(seen[k])return false;seen[k]=1;return true;}).slice(0,700);await saveLearningEvents(m,merged);}catch(e){console.warn('record learning failed',e);}}
function num(v){var n=Number(v);return Number.isFinite(n)?n:null;}
function tradeToLearningEvent(t){t=calcTrade(t);var m=t.market||'tw',sym=String(t.symbol||t.stock_id||'').toUpperCase();return{market:m,symbol:sym,stock_id:t.stock_id||sym,name:t.name||sym,event_type:'closed_trade',source:'trade_journal',signal:t.signal||'',scan_category:t.scan_category||'',strategy_type:t.strategy_type||'Unclassified',entry_price:num(t.entry_price||t.avg_price),target_price:num(t.target_price),stop_loss:num(t.stop_loss),rr:num(t.risk_reward_ratio),confidence:num(t.confidence),technical_score:num(t.technical_score),final_score:num(t.final_score),risk_score:num(t.risk_score),actual_return:num(t.return_pct),r_multiple:num(t.r_multiple),hit_target:!!t.hit_target,hit_stop:!!t.hit_stop,exit_reason:t.exit_reason||'',holding_days:t.hold_days,evaluated:true,success:!!t.win,created_at:t.created_at||t.entry_date||'',evaluated_at:t.closed_at||t.exit_date||new Date().toISOString()};}
async function latestPriceForLearning(m,sym){try{var url=m==='us'?API+'/api/us/stock-lite/'+encodeURIComponent(sym):API+'/api/stock-lite/'+encodeURIComponent(sym);var r=await apiFetch(url,{},12000);var d=await r.json();return num(d.price??d.current_price??d.close??d.last_price);}catch(e){return null;}}
async function evaluatePersonalLearningEvents(m){var events=await loadLearningEvents(m), now=Date.now(), changed=0;for(var i=0;i<events.length;i++){var e=events[i];if(e.evaluated)continue;var ts=Date.parse(e.created_at||'');if(!ts||now-ts<3*86400000)continue;var px=await latestPriceForLearning(m,e.symbol||e.stock_id);var entry=num(e.entry_price);if(px==null||entry==null||entry<=0)continue;var ret=(px-entry)/entry*100;var hitTarget=e.target_price!=null&&px>=Number(e.target_price);var hitStop=e.stop_loss!=null&&px<=Number(e.stop_loss);var rmult=(e.stop_loss!=null&&entry>Number(e.stop_loss))?(px-entry)/(entry-Number(e.stop_loss)):null;e.evaluated=true;e.evaluated_at=new Date().toISOString();e.actual_return=Number(ret.toFixed(2));e.r_multiple=rmult==null?null:Number(rmult.toFixed(2));e.hit_target=hitTarget;e.hit_stop=hitStop;e.success=(hitTarget||ret>2)&&!hitStop;e.result={final_return_pct:e.actual_return,r_multiple:e.r_multiple,hit_target:hitTarget,hit_stop:hitStop,success:e.success};changed++;if(changed>=25)break;}if(changed)await saveLearningEvents(m,events);return{updated:changed,events:events};}
function localLearningSummary(events,trades){events=events||[];var rows=events.concat((trades||[]).map(tradeToLearningEvent));var evals=rows.filter(function(r){return r.evaluated||r.success!==undefined||r.actual_return!=null;});var wins=evals.filter(function(r){return !!r.success;});var rs=evals.map(function(r){return num(r.r_multiple);}).filter(function(x){return x!=null;});var by={};evals.forEach(function(r){var k=r.strategy_type||'Unclassified';var d=by[k]||(by[k]={strategy_type:k,trades:0,wins:0,returns:[],rs:[]});d.trades++;if(r.success)d.wins++;var ar=num(r.actual_return);var rm=num(r.r_multiple);if(ar!=null)d.returns.push(ar);if(rm!=null)d.rs.push(rm);});var strat=Object.keys(by).map(function(k){var d=by[k];return{strategy_type:k,trades:d.trades,win_rate:d.trades?Number((d.wins/d.trades*100).toFixed(1)):0,avg_return:d.returns.length?Number((d.returns.reduce((a,b)=>a+b,0)/d.returns.length).toFixed(2)):0,avg_r:d.rs.length?Number((d.rs.reduce((a,b)=>a+b,0)/d.rs.length).toFixed(2)):null};}).sort(function(a,b){return b.win_rate-a.win_rate;});return{total:rows.length,evaluated:evals.length,pending:rows.length-evals.length,win_rate:evals.length?Number((wins.length/evals.length*100).toFixed(1)):0,avg_r:rs.length?Number((rs.reduce((a,b)=>a+b,0)/rs.length).toFixed(2)):0,strategy_stats:strat,rows:rows};}
async function buildLearningPayload(m){await loadJournal();var events=await loadLearningEvents(m);var trades=(JOURNAL[m]||[]).map(tradeToLearningEvent);var current=await getPersonalWeights(m);return{market:m,events:events,trades:trades,current_weights:current};}
async function loadWeights(){var m=getLearningMarket();var labels=weightLabels(m);var current=await getPersonalWeights(m);var wg=$I('weightsGrid');if(wg)wg.innerHTML=Object.keys(labels).map(function(k){return'<div class="w-item"><div class="w-lbl">'+labels[k]+'</div><div class="w-val">'+Math.round((current[k]||0)*100)+'%</div></div>';}).join('');try{var payload=await buildLearningPayload(m);var local=localLearningSummary(payload.events,payload.trades);var r=await apiFetch(API+'/api/learning/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)},20000);var d=await r.json();var s=(d.summary)||local;LAST_LEARNING_SUMMARY=s;setTxt('lSamples',s.total||0);setTxt('lEval',s.evaluated||0);setTxt('lPending',s.pending||0);setTxt('lWr',(s.win_rate||0)+'%');renderLearningSources(payload);renderLearningStrategy(s);var lm=$I('learnMsg');if(lm)lm.textContent=(s.total?'已載入 '+s.total+' 筆學習資料，其中 '+s.evaluated+' 筆已評估。':'目前尚未累積可學習資料。請先執行 AI 選股、加入交易追蹤，或完成交易日誌。');}catch(e){var payload=await buildLearningPayload(m);var s=localLearningSummary(payload.events,payload.trades);LAST_LEARNING_SUMMARY=s;setTxt('lSamples',s.total||0);setTxt('lEval',s.evaluated||0);setTxt('lPending',s.pending||0);setTxt('lWr',(s.win_rate||0)+'%');renderLearningSources(payload);renderLearningStrategy(s);var lm=$I('learnMsg');if(lm)lm.textContent='後端學習摘要暫時失敗，已使用前端資料計算：'+e.message;}}
function renderLearningSources(payload){var el=$I('learningSourceGrid');if(!el)return;var ev=payload.events||[],tr=payload.trades||[];var scan=ev.filter(function(x){return x.event_type==='scan_candidate';}).length;var evals=ev.filter(function(x){return x.evaluated;}).length;var items=[['AI選股紀錄',scan],['交易日誌',tr.length],['已評估事件',evals],['資料市場',String(payload.market||'tw').toUpperCase()]];el.innerHTML=items.map(function(x){return'<div class="bt-item"><div class="bt-lbl">'+x[0]+'</div><div class="bt-val">'+x[1]+'</div></div>';}).join('');}
function renderLearningStrategy(s){var el=$I('learningStrategyBox');if(!el)return;var arr=s.strategy_stats||[];if(!arr.length){el.textContent='尚無策略統計。完成幾筆 AI 掃描與交易日誌後，這裡會顯示策略勝率。';return;}el.innerHTML='<table class="strategy-table"><thead><tr><th>策略</th><th>筆數</th><th>勝率</th><th>平均報酬</th><th>平均 R</th></tr></thead><tbody>'+arr.slice(0,12).map(function(x){return'<tr><td>'+esc(x.strategy_type)+'</td><td>'+x.trades+'</td><td>'+x.win_rate+'%</td><td>'+(x.avg_return??'—')+'%</td><td>'+(x.avg_r==null?'—':x.avg_r)+'</td></tr>';}).join('')+'</tbody></table>';}
async function suggestLearningWeights(){var m=getLearningMarket();var box=$I('learningSuggestionBox');if(box)box.textContent='計算建議權重中…';try{var payload=await buildLearningPayload(m);var r=await apiFetch(API+'/api/learning/calibrate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)},30000);var d=await r.json();var c=d.calibration||{};LAST_SUGGESTED_WEIGHTS=c.suggested_weights||null;renderWeightSuggestion(m,c);await aiLearningSummaryRef(currentUser.uid,m).set({market:m,calibration:c,updated_at:new Date().toISOString()},{merge:true});}catch(e){if(box)box.textContent='產生建議失敗：'+e.message;}}
function renderWeightSuggestion(m,c){var box=$I('learningSuggestionBox');if(!box)return;var labels=weightLabels(m), cur=c.current_weights||baseWeightsForMarket(m), sug=c.suggested_weights||cur;var html='<div style="margin-bottom:8px">'+esc(c.reason||'—')+'</div><table class="strategy-table"><thead><tr><th>項目</th><th>目前</th><th>建議</th></tr></thead><tbody>';Object.keys(sug).forEach(function(k){html+='<tr><td>'+esc(labels[k]||k)+'</td><td>'+Math.round((cur[k]||0)*100)+'%</td><td>'+Math.round((sug[k]||0)*100)+'%</td></tr>';});html+='</tbody></table>';if(c.sample_count!=null)html+='<div style="margin-top:8px;color:var(--muted);font-size:11px">根據已評估樣本：'+c.sample_count+' 筆</div>';box.innerHTML=html;}
async function applySuggestedWeights(){var m=getLearningMarket();if(!LAST_SUGGESTED_WEIGHTS){toast('請先產生建議權重','warn');return;}if(!confirm('套用 '+m.toUpperCase()+' 建議權重？'))return;await savePersonalWeights(m,LAST_SUGGESTED_WEIGHTS,'V12.8 suggested weights');if(m==='tw'){try{await apiFetch(API+'/api/learning/apply-weights',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({market:m,weights:LAST_SUGGESTED_WEIGHTS})},15000);}catch(e){console.warn(e);}}toast('已套用建議權重','ok');await loadWeights();}
async function showWeightHistory(){var m=getLearningMarket();try{var ref=aiWeightVersionRef(currentUser.uid,m);var s=await ref.get();var d=s.exists?s.data():{};var hist=d.history||[];var lm=$I('learnMsg');if(lm)lm.textContent=hist.length?hist.slice(0,20).map(function(x){return'['+(x.created_at||'').slice(0,19)+'] '+Object.keys(x.weights||{}).map(function(k){return k+':'+Math.round((x.weights[k]||0)*100)+'%';}).join(' / ')+'  '+(x.reason||'');}).join('\n'):'尚無權重版本紀錄';}catch(e){toast('讀取權重歷史失敗','err');}}
async function showLearningHistory(){var m=getLearningMarket();var ev=await loadLearningEvents(m);var lm=$I('learnMsg');if(lm)lm.textContent=ev.length?ev.slice(0,60).map(function(x){return'['+(x.evaluated?'✅':'⏳')+'] '+(x.name||x.symbol)+' '+(x.scan_category||'')+' '+(x.strategy_type||'')+' F'+(x.final_score??'—')+(x.actual_return!=null?' → '+x.actual_return+'%':'');}).join('\n'):'尚無學習事件。請先執行 AI Scan。';}
async function learnAction(type){if(type==='eval'){var m=getLearningMarket();var btn=$I('btnEval');if(btn)btn.disabled=true;try{var res=await evaluatePersonalLearningEvents(m);toast('已評估 '+res.updated+' 筆學習事件','ok');await loadWeights();}catch(e){toast('評估失敗：'+e.message,'err');}finally{if(btn)btn.disabled=false;}return;}if(type==='retrain'){await suggestLearningWeights();return;}if(type==='history'){await showLearningHistory();return;}await loadWeights();}

// ── Chart.js charts ────────────────────────────────────────────────
function killCJCharts(){Object.values(cjCharts).forEach(function(c){try{c.destroy();}catch{}});cjCharts={};}
var CX={responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
  plugins:{legend:{labels:{color:"#6f86a8",font:{family:"Consolas",size:10},boxWidth:12}},
    tooltip:{backgroundColor:"#0d1728",borderColor:"#1d3150",borderWidth:1,titleColor:"#e5eefc",bodyColor:"#6f86a8",titleFont:{family:"Consolas"},bodyFont:{family:"Consolas",size:10}}},
  scales:{x:{grid:{color:"rgba(29,49,80,.5)"},ticks:{color:"#6f86a8",font:{family:"Consolas",size:9},maxTicksLimit:8}},
    y:{grid:{color:"rgba(29,49,80,.5)"},ticks:{color:"#6f86a8",font:{family:"Consolas",size:9}}}}};
function cloneOpt(){return JSON.parse(JSON.stringify(CX));}
function swTab(name,btn){document.querySelectorAll(".tab").forEach(function(b){b.classList.remove("on");});document.querySelectorAll(".tpane").forEach(function(p){p.classList.remove("on");});if(btn)btn.classList.add("on");var tp=$I("tp-"+name);if(tp)tp.classList.add("on");}

function mkCJCharts(data) {
  if(!data||!data.length)return; var lbl=data.map(function(d){return d.date;});
  var chPrice=$I("chPrice");if(!chPrice)return;
  cjCharts.price=new Chart(chPrice,{type:"line",data:{labels:lbl,datasets:[
    {label:"收盤",data:data.map(function(d){return d.close;}),borderColor:"#00d4ff",backgroundColor:"rgba(255,210,63,.04)",borderWidth:1.5,pointRadius:0,fill:true,tension:.3},
    {label:"MA5",data:data.map(function(d){return d.ma5;}),borderColor:"#fbbf24",borderWidth:1,pointRadius:0,tension:.3},
    {label:"MA20",data:data.map(function(d){return d.ma20;}),borderColor:"#f97316",borderWidth:1,pointRadius:0,tension:.3},
    {label:"MA60",data:data.map(function(d){return d.ma60;}),borderColor:"#e8384f",borderWidth:1,pointRadius:0,tension:.3}
  ]},options:cloneOpt()});
  var chVol=$I("chVol");if(chVol)cjCharts.vol=new Chart(chVol,{type:"bar",data:{labels:lbl,datasets:[{label:"成交量",data:data.map(function(d){return d.volume;}),backgroundColor:data.map(function(d,i){return i===0||d.close>=(data[i-1]&&data[i-1].close||d.close)?"rgba(232,56,79,.6)":"rgba(0,184,107,.6)";}),borderWidth:0}]},options:cloneOpt()});
  var chRsi=$I("chRsi");if(chRsi)cjCharts.rsi=new Chart(chRsi,{type:"line",data:{labels:lbl,datasets:[{label:"RSI(14)",data:data.map(function(d){return d.rsi;}),borderColor:"#a78bfa",borderWidth:1.5,pointRadius:0,tension:.4},{label:"超買(70)",data:data.map(function(){return 70;}),borderColor:"rgba(232,56,79,.4)",borderWidth:1,borderDash:[4,4],pointRadius:0},{label:"超賣(30)",data:data.map(function(){return 30;}),borderColor:"rgba(0,184,107,.4)",borderWidth:1,borderDash:[4,4],pointRadius:0}]},options:cloneOpt()});
  var chMacd=$I("chMacd");if(chMacd)cjCharts.macd=new Chart(chMacd,{type:"bar",data:{labels:lbl,datasets:[{type:"bar",label:"Histogram",data:data.map(function(d){return d.hist;}),backgroundColor:data.map(function(d){return(d.hist||0)>=0?"rgba(232,56,79,.5)":"rgba(0,184,107,.5)";}),borderWidth:0},{type:"line",label:"MACD",data:data.map(function(d){return d.macd;}),borderColor:"#00d4ff",borderWidth:1.5,pointRadius:0,tension:.4},{type:"line",label:"Signal",data:data.map(function(d){return d.signal_line;}),borderColor:"#fbbf24",borderWidth:1,pointRadius:0,tension:.4}]},options:cloneOpt()});
}

// ══════════════════════════════════════════════════════════════════
// US ENGINE (frontend)
// ══════════════════════════════════════════════════════════════════
function destroyUSChart(){if(usLwChart){try{usLwChart.remove();}catch{}usLwChart=null;}}
function usColorCls(n){return Number(n)>0?"us-up":Number(n)<0?"us-down":"us-flat";}
function usSigCls(sig){return sig==="BUY"?"us-buy":sig==="AVOID"?"us-avoid":"us-watch";}
function setTxtUS(id,v){var el=$I(id);if(el)el.textContent=v;}

function usCompactCard(item) {
  var sym=item.symbol,c=US_WL_CACHE[sym]||{},name=c.name||item.name||sym;
  var clr=usColorCls(c.changePct||0),sig=c.signal||"WATCH",cls=usSigCls(sig);
  var sel=sym===US_CURRENT?" selected":"";
  var price=c.price!=null?"$"+Number(c.price).toFixed(2):"—";
  var chgStr=c.changePct!=null?pctUS(c.changePct):"—";
  var sigBg=sig==="BUY"?"rgba(34,197,94,.15)":sig==="AVOID"?"rgba(239,68,68,.1)":"rgba(251,191,36,.12)";
  var sigFg=sig==="BUY"?"#22c55e":sig==="AVOID"?"#ef4444":"#fbbf24";
  return '<div class="us-card '+cls+sel+'" style="position:relative" data-us-load="'+sym+'">'+
    '<button style="position:absolute;top:4px;right:6px;background:none;border:none;color:var(--muted);cursor:pointer;font-size:13px;min-height:0;padding:0" data-us-del="'+sym+'">×</button>'+
    '<div style="font-family:var(--mono);font-size:13px;font-weight:700;margin-bottom:1px">'+sym+'</div>'+
    '<div style="font-family:var(--mono);font-size:10px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:3px">'+name+'</div>'+
    '<div style="font-family:var(--mono);font-size:17px;font-weight:700" class="'+clr+'">'+price+'</div>'+
    '<div style="font-family:var(--mono);font-size:11px" class="'+clr+'">'+chgStr+'</div>'+
    '<div style="display:flex;gap:4px;align-items:center;margin-top:3px">'+
    '<span style="font-family:var(--mono);font-size:10px;font-weight:700;padding:1px 6px;border-radius:4px;background:'+sigBg+';color:'+sigFg+'">'+usSigIcon(sig)+'</span>'+
    '<span style="font-family:var(--mono);font-size:10px;color:var(--muted)">'+(c.confidence!=null?c.confidence+"/100":"—")+'</span>'+
    '</div></div>';
}

function usTickerItemHTML(item) {
  var sym=item.symbol,c=US_WL_CACHE[sym]||{},clr=usColorCls(c.changePct||0),name=usDisplayName(sym,item);
  return '<div class="ticker-item" data-us-load="'+esc(sym)+'">'+
    '<span class="name-code">'+esc(name)+' <span style="color:var(--muted)">'+esc(sym)+'</span></span>'+
    '<span class="ticker-price '+clr+'">'+(c.price!=null?"$"+Number(c.price).toFixed(2):"—")+'</span>'+
    '<span class="ticker-chg '+clr+'">'+pctUS(c.changePct)+'</span>'+
    '</div>';
}

function renderUSWL() {
  setTxt("usWlCount",US_WL.length+" stocks");
  var COMPACT_N=4;
  var compact=US_WL.slice(0,COMPACT_N),tickers=US_WL.slice(COMPACT_N);
  var cg=$I("usWlGrid");
  if(cg){
    cg.innerHTML=compact.length?compact.map(usCompactCard).join(""):'<div class="empty" style="grid-column:1/-1">Search a symbol and click ＋ Watchlist</div>';
    cg.querySelectorAll("[data-us-load]").forEach(function(el){el.addEventListener("click",function(e){if(!e.target.closest("[data-us-del]"))usLoadStock(el.dataset.usLoad);});});
    cg.querySelectorAll("[data-us-del]").forEach(function(btn){btn.addEventListener("click",function(e){e.stopPropagation();removeUSWL(btn.dataset.usDel);});});
  }
  var tw=$I("usTickerWrap"),inner=$I("usTickerInner");
  if(tw&&inner){
    if(tickers.length){
      tw.style.display="block";
      var items=tickers.map(usTickerItemHTML).join("");inner.innerHTML=items+items;
      inner.querySelectorAll("[data-us-load]").forEach(function(el){el.addEventListener("click",function(){usLoadStock(el.dataset.usLoad);});});
      requestAnimationFrame(function(){var hw=Math.round(inner.scrollWidth/2);var dur=Math.min(120,Math.max(20,tickers.length*8));tw.style.setProperty("--ticker-half","-"+hw+"px");inner.style.animation="ticker-scroll "+dur+"s linear infinite";});
    } else tw.style.display="none";
  }
  renderPortfolioUI("us");
}

async function fetchUSLite(sym) {
  try {
    var r=await apiFetch(API+"/api/us/stock-lite/"+sym,{},12000);if(!r.ok)return;
    var d=await r.json();var ai=d.ai_signal||{};
    US_WL_CACHE[sym]={name:d.name||sym,price:d.price,changePct:d.change_pct,signal:ai.signal||"WATCH",confidence:ai.confidence};
  } catch(e){}
}
async function refreshUSWL(){
  if(usWlRefreshing||!US_WL.length)return;usWlRefreshing=true;
  try{for(var i=0;i<US_WL.length;i+=3){await Promise.allSettled(US_WL.slice(i,i+3).map(function(item){return fetchUSLite(item.symbol).catch(function(){});}));renderUSWL();if(i+3<US_WL.length)await sleep(700);}}
  finally{usWlRefreshing=false;}
}
function startUSWLTimer(){clearInterval(usWlTimer);usWlLeft=30;usWlTimer=setInterval(function(){usWlLeft--;var bar=$I("usWlBar");if(bar)bar.style.width=Math.max(0,usWlLeft/30*100)+"%";setTxt("usWlTick",Math.max(0,usWlLeft)+"s");if(usWlLeft<=0){usWlLeft=30;refreshUSWL();}},1000);}

async function addUSWL() {
  if(!currentUser) return;
  var inp=$I("usSymbol"),raw=inp?inp.value.trim().toUpperCase():"";
  if(!raw||!/^[A-Z.\-]{1,12}$/.test(raw)){alert("Please enter a valid US symbol (letters only)");return;}
  if(US_WL.find(function(x){return x.symbol===raw;})){alert(raw+" is already in watchlist");return;}
  var name=raw,exchange="US";
  try{var r=await apiFetch(API+"/api/us/suggest?q="+encodeURIComponent(raw),{},5000);if(r.ok){var d=await r.json();var hit=(d.results||[]).find(function(x){return x.symbol===raw;});if(hit){name=hit.name;exchange=hit.exchange;}}}catch{}
  US_WL.push({symbol:raw,name:name,exchange:exchange});renderUSWL();await saveUSWatchlist();await fetchUSLite(raw);renderUSWL();
}
function removeUSWL(sym){US_WL=US_WL.filter(function(x){return x.symbol!==sym;});delete US_WL_CACHE[sym];renderUSWL();saveUSWatchlist();}

function renderUSMobileFast(d){
  var dash=$I("usDash");if(dash)dash.style.display="block";
  renderUSQuote(d);
  renderUSAI(d.ai_signal||{});
  setTxtUS("usAiSummary", "Mobile fast quote loaded. Full analysis is updating in background…");
}

function renderUSMobileTech(d){
  var dash=$I("usDash");if(dash)dash.style.display="block";
  renderUSQuote(d);
  renderUSAI(d.ai_signal||{});
  setTxtUS("usAiSummary", "Mobile technical quick read ready. Full chart/profile update is loading in background…");
}
async function loadUSFullAnalysis(sym,opts){
  opts=opts||{};
  try{
    var r=await apiFetch(API+"/api/us/stock/"+sym,{},opts.timeout||45000);if(!r.ok)throw new Error("HTTP "+r.status);
    var d=await r.json();if(d.error){setTxtUS("usAiSummary",d.error);return null;}
    LAST_US_DATA=d;LAST_US_AI=d.ai_signal||{};renderUSQuote(d);renderUSAI(d.ai_signal||{});
    if(opts.mobile){deferWork(function(){renderUSKline(d.chart_data||[],d.ai_signal||{});},1200);}else{renderUSKline(d.chart_data||[],d.ai_signal||{});}
    var ai=d.ai_signal||{};
    US_WL_CACHE[sym]={name:d.name||sym,price:d.price,changePct:d.change_pct,signal:ai.signal||"WATCH",confidence:ai.confidence};
    renderUSWL();
    if(d.market_context)renderUSCtxInline(d.market_context);
    return d;
  }catch(e){if(!opts.silent)setTxtUS("usAiSummary","Data unavailable: "+e.message); return null;}
}
async function usLoadStock(sym) {
  if(!currentUser) return;
  sym=sym.toUpperCase();US_CURRENT=sym;
  var inp=$I("usSymbol");if(inp)inp.value=sym;
  var dash=$I("usDash");if(dash)dash.style.display="block";
  var kw=$I("usKlineWrap");if(kw)kw.style.display="none";
  destroyUSChart();
  setTxtUS("usName",sym);setTxtUS("usSymbolDisplay","");setTxtUS("usPrice","…");setTxtUS("usChg","");setTxtUS("usAiSummary","Loading…");
  var mobile=isMobileFastMode();
  if(mobile){
    try{var rm=await apiFetch(API+"/api/us/stock-mobile/"+sym,{},8000);if(rm.ok){var dm=await rm.json();LAST_US_DATA=dm;LAST_US_AI=dm.ai_signal||{};renderUSMobileFast(dm);}}
    catch(e){setTxtUS("usAiSummary","Mobile quote unavailable, loading lite…");}
    try{var rt=await apiFetch(API+"/api/us/stock-mobile-tech/"+sym,{},14000);if(rt.ok){var dt=await rt.json();LAST_US_DATA=dt;LAST_US_AI=dt.ai_signal||{};renderUSMobileTech(dt);}}
    catch(e){try{var rl=await apiFetch(API+"/api/us/stock-lite/"+sym,{},10000);if(rl.ok){var dl=await rl.json();LAST_US_DATA=dl;LAST_US_AI=dl.ai_signal||{};renderUSQuote(dl);renderUSAI(dl.ai_signal||{});}}catch(e2){}}
    deferWork(function(){loadUSFullAnalysis(sym,{silent:true,mobile:true,timeout:45000});},1800);
    return;
  }
  try{var rl2=await apiFetch(API+"/api/us/stock-lite/"+sym,{},12000);if(rl2.ok){var dl2=await rl2.json();LAST_US_DATA=dl2;LAST_US_AI=dl2.ai_signal||{};renderUSQuote(dl2);renderUSAI(dl2.ai_signal||{});}}catch{}
  await loadUSFullAnalysis(sym,{silent:false,mobile:false,timeout:45000});
}


function renderUSQuote(d) {
  var clr=usColorCls(d.change_pct||0);
  setTxtUS("usName",d.name||d.symbol||"—");setTxtUS("usSymbolDisplay",d.symbol||"");
  setTxtUS("usExchange",d.exchange||"");setTxtUS("usSector",d.sector||"");
  setTxtUS("usQuoteTime",d.quote_time||"");setTxtUS("usMarketState",d.market_state?"Market: "+d.market_state:"");
  var prEl=$I("usPrice");if(prEl){prEl.textContent=d.price!=null?"$"+Number(d.price).toFixed(2):"—";prEl.className=clr;}
  var chgEl=$I("usChg");if(chgEl){chgEl.textContent=(d.change!=null&&d.change_pct!=null)?(d.change>0?"+":"")+Number(d.change).toFixed(2)+" ("+pctUS(d.change_pct)+")":"—";chgEl.className=clr;}
  setTxtUS("usOpen",d.open!=null?"$"+Number(d.open).toFixed(2):"—");
  var hi=$I("usHigh");if(hi){hi.textContent=d.high!=null?"$"+Number(d.high).toFixed(2):"—";hi.className="us-up";}
  var lo=$I("usLow");if(lo){lo.textContent=d.low!=null?"$"+Number(d.low).toFixed(2):"—";lo.className="us-down";}
  setTxtUS("usVol",d.volume?Math.round(d.volume/1000).toLocaleString()+"K":"—");
  setTxtUS("us52H",d.fifty_two_week_high!=null?"$"+Number(d.fifty_two_week_high).toFixed(2):"—");
  setTxtUS("us52L",d.fifty_two_week_low!=null?"$"+Number(d.fifty_two_week_low).toFixed(2):"—");
  setTxtUS("usDataQuality",d.data_quality?"Data: "+d.data_quality:"");
}

function renderUSAI(ai) {
  LAST_US_AI=ai||LAST_US_AI;
  var sig=ai.signal||"WATCH";
  var badge=$I("usAiBadge");if(badge)badge.className="ai-block "+(sig==="BUY"?"ai-us-buy":sig==="AVOID"?"ai-us-avoid":"ai-us-watch");
  setTxtUS("usAiLabel",usSigIcon(sig));var conf=ai.confidence||0;
  setTxtUS("usAiConf","Confidence "+conf+" / 100");
  var bar=$I("usConfBar");if(bar){bar.style.width=conf+"%";bar.style.background=conf>=75?"#22c55e":conf>=52?"#fbbf24":"#ef4444";}
  var tsEl=$I("usTradeStatus");if(tsEl){var ts=ai.trade_status||"WATCH";var tsL={"BUY_NOW":"Setup (unverified)","BUY_PULLBACK":"⏳ Wait Pullback","WATCH":"👀 Watch","AVOID":"No setup"};var tsBg=ts==="BUY_NOW"?"rgba(255,210,63,.1)":ts==="BUY_PULLBACK"?"rgba(251,191,36,.12)":"rgba(100,116,139,.15)";var tsFg=ts==="BUY_NOW"?"#00d4ff":ts==="BUY_PULLBACK"?"#fbbf24":"#64748b";tsEl.innerHTML='<span style="font-family:var(--mono);font-size:11px;font-weight:700;padding:3px 10px;border-radius:6px;background:'+tsBg+';color:'+tsFg+'">'+(tsL[ts]||ts)+'</span>'+(ai.entry_status?'<span style="font-family:var(--mono);font-size:10px;padding:2px 7px;border-radius:4px;background:#172946;color:var(--muted);margin-left:5px">'+(ai.entry_status_text||ai.entry_status)+'</span>':'');}
  setTxtUS("usAiEp",ai.entry_price!=null?fUS(ai.entry_price,2):"—");
  setTxtUS("usAiTp",ai.target_price!=null?fUS(ai.target_price,2):"—");
  setTxtUS("usAiSl",ai.stop_loss!=null?fUS(ai.stop_loss,2):"—");
  var rrEl=$I("usAiRr");if(rrEl){if(ai.risk_reward_ratio!=null){rrEl.textContent=ai.risk_reward_ratio+"x";rrEl.className="aiq-val "+((ai.risk_reward_ratio>=1.5)?"us-up":"us-down");}else rrEl.textContent="—";}
  var ezLo=ai.entry_zone_low,ezHi=ai.entry_zone_high;
  setTxtUS("usAiZone",(ezLo&&ezHi)?"$"+Number(ezLo).toFixed(2)+" ~ $"+Number(ezHi).toFixed(2):"—");
  var ts2=ai.technical_score,fs=ai.final_score;
  setTxtUS("usAiScores",(ts2!=null?ts2:"—")+" / "+(fs!=null?fs:"—"));
  var tagsEl=$I("usAiTags");if(tagsEl){var tags=[];
    if(ai.strategy_type)tags.push('<span style="font-family:var(--mono);font-size:10px;padding:2px 8px;background:rgba(96,165,250,.12);border:1px solid rgba(96,165,250,.3);border-radius:4px;color:#60a5fa">'+ai.strategy_type+'</span>');
    if(ai.trade_valid===true)tags.push('<span style="font-family:var(--mono);font-size:10px;padding:2px 8px;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.3);border-radius:4px;color:#22c55e">✅ Valid Setup</span>');
    if(ai.trade_valid===false)tags.push('<span style="font-family:var(--mono);font-size:10px;padding:2px 8px;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);border-radius:4px;color:#ef4444">⚠️ Invalid Setup</span>');
    (ai.overheat_flags||[]).slice(0,1).forEach(function(f2){tags.push('<span style="font-family:var(--mono);font-size:10px;padding:2px 8px;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);border-radius:4px;color:#ef4444">🌡 '+f2+'</span>');});
    tagsEl.innerHTML=tags.join("");}
  var srEl=$I("usAiSupRes");if(srEl){var parts=[];if(ai.recent_support)parts.push('Support: <b style="color:#60a5fa">$'+Number(ai.recent_support).toFixed(2)+'</b>');if(ai.recent_resistance)parts.push('Resistance: <b style="color:#f97316">$'+Number(ai.recent_resistance).toFixed(2)+'</b>');if(ai.market_score!=null)parts.push('Market: <b>'+(ai.market_score||0)+'/100</b>');srEl.innerHTML=parts.join(' &nbsp;|&nbsp; ');}
  var rrReasonEl=$I("usAiRiskReasons");if(rrReasonEl)rrReasonEl.innerHTML=(ai.risk_reason||[]).map(function(r){return'<div style="font-family:var(--mono);font-size:11px;color:#ef4444;margin-top:2px">⚠️ '+r+'</div>';}).join("");
  setTxtUS("usAiSummary",ai.summary||(sig==="AVOID"?"Technical conditions weak, avoid for now.":"—"));
}

function renderUSKline(chartData,aiSignal) {
  var wrap=$I("usKlineWrap"),container=$I("usKlineContainer");if(!wrap||!container)return;
  if(!chartData||!chartData.length){wrap.style.display="none";return;}
  wrap.style.display="block";destroyUSChart();
  try {
    if(typeof LightweightCharts==="undefined"){wrap.style.display="none";return;}
    var h=window.innerWidth<=768?320:420;container.style.height=h+"px";
    usLwChart=LightweightCharts.createChart(container,{width:container.offsetWidth,height:h,layout:{background:{color:"#0d1728"},textColor:"#6f86a8"},grid:{vertLines:{color:"rgba(29,49,80,.5)"},horzLines:{color:"rgba(29,49,80,.5)"}},crosshair:{mode:LightweightCharts.CrosshairMode.Normal},rightPriceScale:{borderColor:"#1d3150"},timeScale:{borderColor:"#1d3150",timeVisible:true}});
    // US: green=up, red=down
    var cs=usLwChart.addCandlestickSeries({upColor:"#22c55e",downColor:"#ef4444",borderUpColor:"#22c55e",borderDownColor:"#ef4444",wickUpColor:"#22c55e",wickDownColor:"#ef4444"});
    var cd=chartData.filter(function(d){return d.open&&d.high&&d.low&&d.close;}).map(function(d){return{time:d.date,open:d.open,high:d.high,low:d.low,close:d.close};});
    if(cd.length)cs.setData(cd);
    [[function(d){return d.ma5;},"#fbbf24",0],[function(d){return d.ma20;},"#f97316",0],[function(d){return d.ma60;},"#ef4444",2]].forEach(function(m){var s=usLwChart.addLineSeries({color:m[1],lineWidth:1,lineStyle:m[2],priceLineVisible:false});s.setData(chartData.filter(function(d){return m[0](d)!=null;}).map(function(d){return{time:d.date,value:m[0](d)};}));});
    var ai=aiSignal||{};
    if(ai.trade_valid!==false&&cd.length){
      if(ai.entry_price)cs.createPriceLine({price:ai.entry_price,color:"#fbbf24",lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:"Entry"});
      if(ai.target_price)cs.createPriceLine({price:ai.target_price,color:"#22c55e",lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:"Target"});
      if(ai.stop_loss)cs.createPriceLine({price:ai.stop_loss,color:"#ef4444",lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,axisLabelVisible:true,title:"Stop"});
    }
    if(cd.length&&ai.recent_support){var sl2=usLwChart.addLineSeries({color:"rgba(96,165,250,.5)",lineWidth:1,lineStyle:3,priceLineVisible:false});sl2.setData([{time:cd[0].time,value:ai.recent_support},{time:cd[cd.length-1].time,value:ai.recent_support}]);}
    if(cd.length&&ai.recent_resistance){var rl2=usLwChart.addLineSeries({color:"rgba(249,115,22,.4)",lineWidth:1,lineStyle:3,priceLineVisible:false});rl2.setData([{time:cd[0].time,value:ai.recent_resistance},{time:cd[cd.length-1].time,value:ai.recent_resistance}]);}
    var vs=usLwChart.addHistogramSeries({color:"rgba(34,197,94,.3)",priceFormat:{type:"volume"},priceScaleId:"vol",scaleMargins:{top:0.8,bottom:0}});
    var vd=chartData.filter(function(d){return d.volume!=null&&d.close!=null;}).map(function(d){return{time:d.date,value:d.volume,color:d.close>=(d.open||d.close)?"rgba(34,197,94,.4)":"rgba(239,68,68,.4)"};});
    if(vd.length)vs.setData(vd);
    usLwChart.timeScale().fitContent();setTxtUS("usKlineStatus",cd.length+" bars");
    try{var ro=new ResizeObserver(function(){if(usLwChart&&container)usLwChart.applyOptions({width:container.offsetWidth});});ro.observe(container);}catch{}
  } catch(e){console.warn("US kline:",e.message);wrap.style.display="none";}
}

// ── US Market Context ──────────────────────────────────────────────
async function loadUSMarketContext() {
  var box=$I("usCtxBox");if(box)box.style.display="block";
  try {
    var r=await apiFetch(API+"/api/us/market-context",{},15000);var d=await r.json();
    renderUSCtxInline(d);
  } catch(e){setTxtUS("usCtxScore","?");}
}

function renderUSCtxInline(ctx) {
  var box=$I("usCtxBox");if(box)box.style.display="block";
  if(!ctx) return;
  var sc=ctx.market_score||50;
  var scoreEl=$I("usCtxScore");if(scoreEl){scoreEl.textContent=sc;scoreEl.className="ctx-score "+(sc>=65?"us-up":sc>=45?"":"us-down");}
  setTxtUS("usCtxSentiment",ctx.sentiment||"—");
  var ex=(ctx.explanations||[]).slice(0,4).map(function(x){return (x.impact>0?"+":"")+x.impact+" "+x.text;}).join(" | ");
  setTxtUS("usCtxNote",ex||ctx.note||"—");
  var grid=$I("usCtxGrid");if(grid){
    var keys=["spy","qqq","soxx","vix","us10y","btc"];
    grid.innerHTML=keys.map(function(k){var v=(ctx.components||{})[k];if(!v)return'<div class="ctx-item"><div class="ctx-lbl">'+k.toUpperCase()+'</div><div class="ctx-val">—</div></div>';var clr=usColorCls(v.change_pct);return'<div class="ctx-item"><div class="ctx-lbl">'+k.toUpperCase()+'</div><div class="ctx-val">'+Number(v.price).toFixed(k==="btc"?0:2)+'</div><div class="ctx-chg '+clr+'">'+pctUS(v.change_pct)+'</div></div>';}).join("");
  }
}

// ── US AI Scan ─────────────────────────────────────────────────────
var usSuggestTimer=null;
function initUSSuggest() {
  var inp=$I("usSymbol"),box=$I("usSuggestBox");if(!inp||!box)return;
  inp.addEventListener("input",function(){clearTimeout(usSuggestTimer);var q=inp.value.trim();if(q.length<1){box.style.display="none";return;}usSuggestTimer=setTimeout(function(){fetchUSSuggest(q);},250);});
  inp.addEventListener("keydown",function(e){if(e.key==="Enter")usDoSearch();});
  inp.addEventListener("blur",function(){setTimeout(function(){box.style.display="none";},200);});
  box.addEventListener("mousedown",function(e){var item=e.target.closest("[data-us-sym]");if(item){inp.value=item.dataset.usSym;box.style.display="none";usDoSearch();}});
}
async function fetchUSSuggest(q) {
  var box=$I("usSuggestBox");if(!box)return;
  try{var r=await apiFetch(API+"/api/us/suggest?q="+encodeURIComponent(q),{},5000);if(!r.ok)return;var d=await r.json();var results=d.results||[];if(!results.length){box.style.display="none";return;}box.innerHTML=results.map(function(r2){return'<div class="us-suggest-item" data-us-sym="'+r2.symbol+'"><div><span class="us-sym">'+r2.symbol+'</span> <span class="us-sname">'+r2.name+'</span></div><span class="us-exch">'+(r2.exchange||r2.type||"")+'</span></div>';}).join("");box.style.display="block";}catch{}
}
function usDoSearch(){var inp=$I("usSymbol");var sym=inp?inp.value.trim().toUpperCase():"";if(/^[A-Z.\-]{1,12}$/.test(sym))usLoadStock(sym);else if(sym)alert("Please enter a valid US symbol (letters only)");}

async function usAiScan(forceMode, forcePool) {
  if(isDomEvent(forceMode)){forceMode=null;forcePool=null;}
  if(!currentUser)return;
  var box=$I("usAiScanBox");if(box)box.style.display="block";
  var sum=$I("usAiScanSummary");
  var mode=cleanScanMode(forceMode) || (($I("usScanMode")||{}).value||"full");
  var pool=(isDomEvent(forcePool)?"":forcePool) || (($I("usScanPool")||{}).value||"all");
  var diversityMode=cleanDiversityMode(($I("usDiversityMode")||{}).value||"balanced");
  var endpoint="/api/us/scan/diversified";
  var max=(mode==="quick")?20:60;
  var symbols=(pool==="watchlist")?US_WL.map(function(x){return x.symbol||x;}).join(","):"";
  if(sum)sum.textContent=(mode==="quick"?"Quick Scan":"Full Scan")+" scanning…";
  ["usZoneEnterable","usZoneWatchClose","usZoneFreshDiscovery","usZonePullback","usZoneBreakout","usZoneNearMiss","usZoneRisk"].forEach(function(id){var el=$I(id);if(el)el.innerHTML="";});
  updateScanProgress("us",8); var fake=beginFakeProgress("us",mode==="quick"?12000:80000);
  var btn=$I("btnUsScan"),btn2=$I("btnUsScanAgain");if(btn)btn.disabled=true;if(btn2)btn2.disabled=true;
  if(box)setTimeout(function(){box.scrollIntoView({behavior:"smooth",block:"start"});},200);
  try {
    var history=getRecommendationHistorySymbols("us").join(",");
    var url=API+endpoint+"?min_score=0&max_stocks="+max+"&mode="+encodeURIComponent(mode)+"&pool="+encodeURIComponent(pool)+"&diversity_mode="+encodeURIComponent(diversityMode)+"&symbols="+encodeURIComponent(symbols)+"&history_symbols="+encodeURIComponent(history);
    var r=await apiFetch(url,{},mode==="quick"?45000:120000);
    if(!r.ok){throw new Error("US scan API failed: HTTP "+r.status);}
    var d=await r.json(); d=normalizeUSScanPayload(d);
    var s=d.summary||{};
    if(sum)sum.textContent=(d.scan_label||"")+" | Scanned "+safeVal(d.scanned,0)+" | Classified "+safeVal(d.classified,0)+" | Failed "+safeVal(d.failed||d.error_count,0)+" | "+safeVal(d.duration_seconds,"—")+"s | Market "+safeVal(s.market_score??d.market_score,"—")+"/100"+(s.message?" — "+s.message:"");
    renderScanKpis("us",d); setTxtUS("usScanCache","cache: "+(d.cache_status||"fresh")+" · "+(d.diversity_mode||diversityMode)); saveRecommendationHistory("us",d); await recordLearningEventsFromScan("us",d); updateScanProgress("us",100); renderUSScan(d);
  } catch(e){
    console.error("US AI scan failed", e); if(sum)sum.textContent="Scan failed: "+(e.message||e); updateScanProgress("us",0);
    var risk=$I("usZoneRisk"); if(risk)risk.innerHTML='<div class="scan-zone-lbl sz-risk">⚠️ US Scan Error</div><div class="empty" style="padding:8px;font-size:11px">'+escapeHTML(String(e.message||e))+'</div>';
  }
  finally{clearInterval(fake);if(btn)btn.disabled=false;if(btn2)btn2.disabled=false;}
}

function normalizeUSScanPayload(d){
  d=d||{};var s=d.summary||{};
  d.enterable=Array.isArray(d.enterable)?d.enterable:[];
  d.watch_closely=Array.isArray(d.watch_closely)?d.watch_closely:[];
  d.fresh_discovery=Array.isArray(d.fresh_discovery)?d.fresh_discovery:[];
  d.pullback=Array.isArray(d.pullback)?d.pullback:[];
  d.breakout_watch=Array.isArray(d.breakout_watch)?d.breakout_watch:[];
  d.risk_watch=Array.isArray(d.risk_watch)?d.risk_watch:[];
  d.avoid=Array.isArray(d.avoid)?d.avoid:[];
  d.near_miss=Array.isArray(d.near_miss)?d.near_miss:[];
  var total=d.enterable.length+d.watch_closely.length+d.fresh_discovery.length+d.pullback.length+d.breakout_watch.length+d.risk_watch.length+d.avoid.length+d.near_miss.length;
  d.scanned=d.scanned??s.scanned??s.attempted??d.attempted??(total+(d.error_count||0));
  d.classified=d.classified??s.classified??total;
  d.failed=d.failed??s.failed??d.error_count??0;
  d.found=d.found??s.found??(d.enterable.length+d.pullback.length+d.breakout_watch.length+d.risk_watch.length+d.near_miss.length);
  d.duration_seconds=d.duration_seconds??s.duration_seconds??0;
  d.market_score=d.market_score??s.market_score??"—";
  if(!d.summary)d.summary={};
  d.summary.market_score=d.summary.market_score??d.market_score;
  return d;
}

function escapeHTML(str){return String(str).replace(/[&<>'"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c];});}

function renderUSScan(data) {
  data=normalizeUSScanPayload(data);
  function zone(elId,lbl,css,items,emptyMsg){
    var el=$I(elId);if(!el)return;
    items=Array.isArray(items)?items:[];
    if(!items.length){el.innerHTML='<div class="scan-zone-lbl '+css+'">'+lbl+' <span>0</span></div><div class="empty" style="padding:8px;font-size:11px">'+emptyMsg+'</div>';return;}
    el.innerHTML='<div class="scan-zone-lbl '+css+'">'+lbl+' <span class="d-badge" style="font-size:10px">'+items.length+'</span></div><div class="scan-grid" style="margin-top:8px;margin-bottom:12px">'+items.map(usScanCard).join("")+'</div>';
    el.querySelectorAll("[data-us-load]").forEach(function(el2){el2.addEventListener("click",function(){usLoadStock(el2.dataset.usLoad);});});
  }
  zone("usZoneEnterable","✅ Enterable Candidates","sz-us-enter",data.enterable,"No stocks meet entry criteria. Patience is key.");
  zone("usZoneWatchClose","👀 Watch Closely","sz-close",data.watch_closely,"No watch-closely candidates yet.");
  zone("usZoneFreshDiscovery","🌱 Fresh Discovery","sz-fresh",data.fresh_discovery,"No fresh high-quality discovery candidates yet.");
  zone("usZonePullback","⏳ Watch / Wait Pullback","sz-us-pull",data.pullback,"目前沒有等回檔候選。");
  zone("usZoneBreakout","🔭 Breakout Watch","sz-breakout",data.breakout_watch,"目前沒有突破觀察候選。");
  zone("usZoneNearMiss","💫 Near Miss","sz-near",data.near_miss,"目前沒有差一點候選；若可進場為 0，代表條件仍距離較遠或資料暫不足。");
  var riskCombined=(data.risk_watch||[]).concat(data.avoid||[]);
  zone("usZoneRisk","⚠️ Avoid / Risk Watch","sz-risk",riskCombined,"目前沒有風險觀察 / 避免清單。");
}

function usScanCard(r) {
  var clr=usColorCls(r.change_pct||0);var sig=r.signal||"WATCH";var rr=r.risk_reward_ratio;var tv=r.trade_valid;var ts=r.technical_score;var fs=r.final_score;var ms=r.market_score;
  var sigBg=sig==="BUY"?"rgba(34,197,94,.15)":sig==="AVOID"?"rgba(239,68,68,.1)":"rgba(251,191,36,.12)";var sigFg=sig==="BUY"?"#22c55e":sig==="AVOID"?"#ef4444":"#fbbf24";
  return '<div class="scan-card" data-us-load="'+r.symbol+'">'+
    '<div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:6px">'+
    '<div><div style="font-weight:700;font-size:13px">'+r.symbol+'</div>'+
    '<div style="font-family:var(--mono);font-size:10px;color:var(--muted)">'+(r.name||"")+' '+(r.strategy_type?'<span style="font-size:9px">'+r.strategy_type+'</span>':'')+'</div></div>'+
    '<div style="text-align:right"><span style="font-family:var(--mono);font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;background:'+sigBg+';color:'+sigFg+'">'+usSigIcon(sig)+'</span>'+
    (tv===true?'<div style="font-family:var(--mono);font-size:9px;color:#22c55e;margin-top:2px">✅ Valid</div>':tv===false?'<div style="font-family:var(--mono);font-size:9px;color:#ef4444;margin-top:2px">⚠️ Invalid</div>':'')+'</div></div>'+
    '<div style="font-family:var(--mono);font-size:16px;font-weight:700;margin-bottom:6px" class="'+clr+'">'+(r.price!=null?"$"+Number(r.price).toFixed(2):"—")+' <span style="font-size:12px">'+pctUS(r.change_pct)+'</span></div>'+
    '<div class="scan-meta">'+
    '<div><span class="lbl">Entry</span> '+(r.entry_price!=null?fUS(r.entry_price,2):"—")+'</div>'+
    '<div><span class="lbl">Target</span> <span class="us-up">'+(r.target_price!=null?fUS(r.target_price,2):"—")+'</span></div>'+
    '<div><span class="lbl">Stop</span> <span class="us-down">'+(r.stop_loss!=null?fUS(r.stop_loss,2):"—")+'</span></div>'+
    '<div><span class="lbl">RR</span> <span class="'+((rr||0)>=1.5?"us-up":"us-down")+'">'+(rr!=null?rr+"x":"—")+'</span></div>'+
    (ts!=null?'<div><span class="lbl">Tech</span> <span class="val">'+ts+'</span></div>':'')+
    (ms!=null?'<div><span class="lbl">Mkt</span> <span class="val">'+ms+'</span></div>':'')+
    (r.diversified_score!=null?'<div><span class="lbl">Diverse</span> <span class="val">'+r.diversified_score+'</span></div>':'')+
    (r.novelty_score!=null?'<div><span class="lbl">Novel</span> <span class="val">'+r.novelty_score+'</span></div>':'')+
    '</div>'+
    ((r.reasons&&r.reasons.length)?'<div class="scan-reasons" style="color:#22c55e">✅ '+r.reasons.slice(0,2).join(" / ")+'</div>':'')+
    ((r.risk_reason&&r.risk_reason.length)?'<div class="scan-reasons">⚠️ '+r.risk_reason[0]+'</div>':'')+
    (r.repeat_note?'<div class="scan-reasons">🔁 '+r.repeat_note+'</div>':'')+
    '</div>';
}



// ── Trade Plan Center (V12.9.2 polish) ─────────────────────────────
function planKey(p){return (p.market||'tw')+":"+(p.symbol||p.stock_id||'');}
function normalizePlanMarket(m){return (m==='us')?'us':'tw';}
async function loadTradePlans(){
  TRADE_PLANS={tw:[],us:[]};
  if(!currentUser||!db)return TRADE_PLANS;
  for(var i=0;i<2;i++){
    var m=i===0?'tw':'us', ref=tradePlanRef(currentUser.uid,m);
    try{var snap=await ref.get();if(snap.exists){var data=snap.data()||{};TRADE_PLANS[m]=Array.isArray(data.plans)?data.plans:[];}}
    catch(e){console.warn('load trade plans',m,e);}
  }
  return TRADE_PLANS;
}
async function saveTradePlans(mkt){
  mkt=normalizePlanMarket(mkt); if(!currentUser||!db)return;
  var ref=tradePlanRef(currentUser.uid,mkt); if(!ref)return;
  await ref.set({market:mkt,plans:TRADE_PLANS[mkt]||[],updated_at:new Date().toISOString()},{merge:true});
}
function buildPlanFromCurrent(mkt){
  mkt=normalizePlanMarket(mkt);
  var ai=mkt==='us'?LAST_US_AI:LAST_TW_AI, data=mkt==='us'?LAST_US_DATA:LAST_TW_DATA;
  if(!data||!ai){toast(mkt==='us'?'Please search a US stock first':'請先查詢股票','warn');return null;}
  var sym=mkt==='us'?(data.symbol||data.stock_id):(data.stock_id||data.symbol);
  if(!sym){toast('找不到股票代號','err');return null;}
  var entry=ai.entry_price, elo=ai.entry_zone_low, ehi=ai.entry_zone_high, target=ai.target_price, stop=ai.stop_loss;
  if(entry==null&&elo!=null&&ehi!=null)entry=(Number(elo)+Number(ehi))/2;
  var p={
    id:String(sym),market:mkt,symbol:String(sym),stock_id:String(sym),
    name:mkt==='us'?(data.name||sym):(data.stock_name||data.name||getLocalName(sym)||sym),
    price:data.price,change_pct:data.change_pct,
    entry_price:entry,entry_zone_low:elo,entry_zone_high:ehi,target_price:target,stop_loss:stop,
    risk_reward_ratio:ai.risk_reward_ratio,signal:ai.signal||ai.trade_status||'WATCH',trade_status:ai.trade_status||'WATCH',
    strategy_type:ai.strategy_type||'',final_score:ai.final_score,technical_score:ai.technical_score,risk_score:ai.risk_score,
    summary:ai.summary||'',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),status:'WAITING_ENTRY'
  };
  return p;
}
async function addCurrentTradePlan(mkt){
  var p=buildPlanFromCurrent(mkt); if(!p)return;
  var arr=TRADE_PLANS[p.market]||(TRADE_PLANS[p.market]=[]); var k=planKey(p), found=false;
  for(var i=0;i<arr.length;i++){if(planKey(arr[i])===k){p.created_at=arr[i].created_at||p.created_at;arr[i]=Object.assign({},arr[i],p,{updated_at:new Date().toISOString()});found=true;break;}}
  if(!found)arr.unshift(p);
  await saveTradePlans(p.market); renderTradePlans(); toast(found?'已更新交易追蹤':'已加入交易追蹤','ok');
}
async function removeTradePlan(mkt,id){
  mkt=normalizePlanMarket(mkt); TRADE_PLANS[mkt]=(TRADE_PLANS[mkt]||[]).filter(function(p){return String(p.symbol||p.stock_id)!==String(id);});
  await saveTradePlans(mkt); renderTradePlans(); toast('已移除交易追蹤','ok');
}
function getAllPlans(){return (TRADE_PLANS.tw||[]).concat(TRADE_PLANS.us||[]);}
function planStatusLabel(st){return {WAITING_ENTRY:'等待入場',ENTERABLE_NOW:'進入入場區',ABOVE_ENTRY_ZONE:'高於入場區',NEAR_TARGET:'接近目標',NEAR_STOP:'接近停損',STOP_BROKEN:'跌破停損',TARGET_REACHED:'達到目標',INVALIDATED:'已失效',NO_PRICE:'無現價'}[st]||st||'等待入場';}
function planStatusClass(st){if(st==='ENTERABLE_NOW'||st==='TARGET_REACHED')return 'ok'; if(st==='NEAR_TARGET'||st==='WAITING_ENTRY')return 'watch'; if(st==='NEAR_STOP'||st==='STOP_BROKEN'||st==='INVALIDATED')return 'risk'; return 'neutral';}
function localCheckPlan(p){
  var cp=Number(p.current_price||p.price), lo=Number(p.entry_zone_low||p.entry_price), hi=Number(p.entry_zone_high||p.entry_price), tp=Number(p.target_price), sl=Number(p.stop_loss); var st='WAITING_ENTRY';
  if(!cp||isNaN(cp))st='NO_PRICE'; else if(tp&&cp>=tp)st='TARGET_REACHED'; else if(sl&&cp<=sl)st='STOP_BROKEN'; else if(sl&&cp<=sl*1.05)st='NEAR_STOP'; else if(tp&&cp>=tp*0.95)st='NEAR_TARGET'; else if(lo&&hi&&cp>=lo&&cp<=hi)st='ENTERABLE_NOW'; else if(hi&&cp>hi)st='ABOVE_ENTRY_ZONE'; else st='WAITING_ENTRY';
  var distEntry=(cp&&lo&&hi)?(cp<lo?(lo-cp)/cp*100:(cp>hi?(cp-hi)/cp*100:0)):null;
  return Object.assign({},p,{status:st,distance_to_entry_pct:distEntry==null?null:Number(distEntry.toFixed(2)),checked_at:new Date().toISOString()});
}
async function refreshTradePlans(showMsg){
  if(showMsg!==false)toast('正在重新檢查交易追蹤…','warn');
  for(var m of ['tw','us']){
    for(var i=0;i<(TRADE_PLANS[m]||[]).length;i++){
      var p=TRADE_PLANS[m][i],sym=p.symbol||p.stock_id;
      try{
        var url=API+(m==='us'?'/api/us/stock-lite/':'/api/stock-lite/')+encodeURIComponent(sym);
        var r=await apiFetch(url,{},12000); if(r.ok){var d=await r.json();p.current_price=d.price;p.price=d.price;p.change_pct=d.change_pct;p.name=d.name||d.stock_name||p.name;}
      }catch(e){}
      TRADE_PLANS[m][i]=localCheckPlan(p);
    }
    try{await saveTradePlans(m);}catch(e){}
  }
  renderTradePlans(); if(showMsg!==false)toast('交易追蹤已更新','ok');
}
function renderTradePlans(){
  var all=getAllPlans().map(localCheckPlan); var filtered=all.filter(function(p){return PLAN_FILTER==='all'||p.market===PLAN_FILTER||p.status===PLAN_FILTER;});
  setTxt('planTotalBadge',all.length+' 筆');
  var counts={WAITING_ENTRY:0,ENTERABLE_NOW:0,NEAR_TARGET:0,NEAR_STOP:0,STOP_BROKEN:0,TARGET_REACHED:0,ABOVE_ENTRY_ZONE:0,NO_PRICE:0};
  all.forEach(function(p){counts[p.status]=(counts[p.status]||0)+1;});
  var sg=$I('planSummaryGrid'); if(sg){sg.innerHTML=[['全部',all.length],['等待入場',counts.WAITING_ENTRY],['入場區',counts.ENTERABLE_NOW],['接近目標',counts.NEAR_TARGET],['接近停損',counts.NEAR_STOP+counts.STOP_BROKEN]].map(function(x){return '<div class="plan-stat"><div class="k">'+x[0]+'</div><div class="v">'+x[1]+'</div></div>';}).join('');}
  var grid=$I('tradePlanGrid'),empty=$I('tradePlanEmpty'); if(!grid)return;
  if(empty)empty.style.display=filtered.length?'none':'block';
  grid.innerHTML=filtered.map(function(p){var sym=p.symbol||p.stock_id,name=p.name||sym,m=p.market||'tw',up=m==='us'?'us-up':'tw-up',down=m==='us'?'us-down':'tw-down';var ch=Number(p.change_pct||0);var clr=ch>0?up:(ch<0?down:'tw-flat');return '<div class="plan-card '+m+'" data-plan-open="'+m+':'+esc(sym)+'">'+
    '<div class="plan-top"><div><div class="plan-name">'+esc(name)+'</div><div class="plan-code">'+esc(sym)+' · '+m.toUpperCase()+'</div></div><span class="plan-status '+planStatusClass(p.status)+'">'+planStatusLabel(p.status)+'</span></div>'+
    '<div class="plan-metrics"><span class="lbl">現價</span><span class="val '+clr+'">'+(m==='us'?fUS(p.price):f(p.price))+'</span><span class="lbl">入場區</span><span class="val">'+(p.entry_zone_low?f(p.entry_zone_low)+'~'+f(p.entry_zone_high||p.entry_zone_low):'—')+'</span><span class="lbl">目標</span><span class="val">'+(p.target_price?f(p.target_price):'—')+'</span><span class="lbl">停損</span><span class="val">'+(p.stop_loss?f(p.stop_loss):'—')+'</span><span class="lbl">RR</span><span class="val">'+(p.risk_reward_ratio?p.risk_reward_ratio+'x':'—')+'</span><span class="lbl">距離入場</span><span class="val">'+(p.distance_to_entry_pct!=null?p.distance_to_entry_pct+'%':'—')+'</span></div>'+
    '<div class="plan-note">'+esc(p.strategy_type||p.summary||'—')+'</div><div class="plan-actions"><button class="ghost sm" data-plan-open-btn="'+m+':'+esc(sym)+'">打開</button><button class="ghost sm" data-plan-convert="'+m+':'+esc(sym)+'">轉為持倉</button><button class="ghost sm danger" data-plan-remove="'+m+':'+esc(sym)+'">移除</button></div></div>';}).join('');
}
function openTradePlan(mkt,id){if(mkt==='us'&&!ENABLE_US){toast('美股功能目前收起來了','warn');return;}switchMarket(mkt);if(mkt==='us')usLoadStock(id);else loadStock(id);showPage('p-trade');}


// ── Portfolio / Position Center (V12.3) ────────────────────────────
function positionKey(p){return (p.market||'tw')+":"+(p.symbol||p.stock_id||'');}
function normalizePositionMarket(m){return (m==='us')?'us':'tw';}
async function loadPositions(){
  POSITIONS={tw:[],us:[]};
  if(!currentUser||!db)return POSITIONS;
  for(var i=0;i<2;i++){
    var m=i===0?'tw':'us', ref=positionRef(currentUser.uid,m);
    try{var snap=await ref.get();if(snap.exists){var data=snap.data()||{};POSITIONS[m]=Array.isArray(data.positions)?data.positions:[];}}
    catch(e){console.warn('load positions',m,e);}
  }
  return POSITIONS;
}
async function savePositions(mkt){
  mkt=normalizePositionMarket(mkt); if(!currentUser||!db)return;
  var ref=positionRef(currentUser.uid,mkt); if(!ref)return;
  await ref.set({market:mkt,positions:POSITIONS[mkt]||[],updated_at:new Date().toISOString()},{merge:true});
}
function getAllPositions(){return (POSITIONS.tw||[]).concat(POSITIONS.us||[]);}
function positionStatusLabel(st){return {HOLDING_NORMAL:'正常持有',NEAR_TARGET:'接近目標',TARGET_REACHED:'達到目標',NEAR_STOP:'接近停損',STOP_BROKEN:'跌破停損',RISK_UP:'風險升高',REVIEW_REQUIRED:'建議檢查',NO_PRICE:'無現價'}[st]||st||'正常持有';}
function positionStatusClass(st){if(st==='TARGET_REACHED'||st==='NEAR_TARGET')return 'ok'; if(st==='HOLDING_NORMAL')return 'neutral'; if(st==='RISK_UP'||st==='REVIEW_REQUIRED')return 'watch'; if(st==='NEAR_STOP'||st==='STOP_BROKEN')return 'risk'; return 'neutral';}
function localCheckPosition(p){
  var cp=Number(p.current_price||p.price), avg=Number(p.avg_price), sh=Number(p.shares), tp=Number(p.target_price), sl=Number(p.stop_loss); var st='HOLDING_NORMAL', alerts=[];
  if(!cp||isNaN(cp))st='NO_PRICE'; else if(tp&&cp>=tp){st='TARGET_REACHED';alerts.push('已達到目標價');} else if(sl&&cp<=sl){st='STOP_BROKEN';alerts.push('已跌破停損');} else if(sl&&cp<=sl*1.05){st='NEAR_STOP';alerts.push('接近停損價');} else if(tp&&cp>=tp*0.95){st='NEAR_TARGET';alerts.push('接近目標價');} else if(avg&&cp<avg*0.92){st='RISK_UP';alerts.push('未實現損益明顯轉弱');}
  var pnl=(cp&&avg&&sh)?(cp-avg)*sh:null, pnlPct=(cp&&avg)?(cp-avg)/avg*100:null, risk=(avg&&sl&&sh)?Math.max(0,(avg-sl)*sh):null;
  var distT=(cp&&tp)?(tp-cp)/cp*100:null, distS=(cp&&sl)?(sl-cp)/cp*100:null;
  return Object.assign({},p,{status:st,alerts:alerts,unrealized_pnl:pnl==null?null:Number(pnl.toFixed(2)),unrealized_pnl_pct:pnlPct==null?null:Number(pnlPct.toFixed(2)),risk_amount:risk==null?null:Number(risk.toFixed(2)),distance_to_target_pct:distT==null?null:Number(distT.toFixed(2)),distance_to_stop_pct:distS==null?null:Number(distS.toFixed(2)),checked_at:new Date().toISOString()});
}
function buildPositionFromPlan(mkt,id){
  mkt=normalizePositionMarket(mkt); var arr=TRADE_PLANS[mkt]||[]; var p=arr.find(function(x){return String(x.symbol||x.stock_id)===String(id);});
  if(!p){toast('找不到交易追蹤計畫','err');return null;}
  var defaultPrice=p.current_price||p.price||p.entry_price||p.entry_zone_low||'';
  var avg=prompt('買入價 / Average Price', defaultPrice); if(avg===null)return null;
  var shares=prompt(mkt==='us'?'Shares':'股數', '1'); if(shares===null)return null;
  var pos={id:String(id),market:mkt,symbol:String(id),stock_id:String(id),name:p.name||id,avg_price:Number(avg),shares:Number(shares),price:p.current_price||p.price||null,current_price:p.current_price||p.price||null,target_price:p.target_price||null,stop_loss:p.stop_loss||null,strategy_type:p.strategy_type||'',signal:p.signal||p.trade_status||'',notes:p.summary||'',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),status:'HOLDING_NORMAL'};
  return localCheckPosition(pos);
}
async function convertPlanToPosition(mkt,id){
  var pos=buildPositionFromPlan(mkt,id); if(!pos)return;
  var arr=POSITIONS[pos.market]||(POSITIONS[pos.market]=[]), k=positionKey(pos), found=false;
  for(var i=0;i<arr.length;i++){if(positionKey(arr[i])===k){pos.created_at=arr[i].created_at||pos.created_at;arr[i]=Object.assign({},arr[i],pos,{updated_at:new Date().toISOString()});found=true;break;}}
  if(!found)arr.unshift(pos);
  await savePositions(pos.market); renderPositions(); toast(found?'已更新持倉':'已轉為持倉','ok'); showPage('p-positions');
}
async function manualAddPosition(){
  var m=prompt('市場 tw/us', currentMarket||'tw'); if(!m)return; m=normalizePositionMarket(String(m).toLowerCase());
  var sym=prompt(m==='us'?'美股代號':'台股代號', m==='us'?'AAPL':'2330'); if(!sym)return; sym=String(sym).trim().toUpperCase();
  var name=prompt('股票名稱', sym)||sym;
  var avg=prompt('買入價', ''); if(avg===null||avg==='')return;
  var shares=prompt(m==='us'?'Shares':'股數', '1'); if(shares===null||shares==='')return;
  var target=prompt('目標價（可空白）', ''); var stop=prompt('停損價（可空白）', '');
  var pos=localCheckPosition({id:sym,market:m,symbol:sym,stock_id:sym,name:name,avg_price:Number(avg),shares:Number(shares),target_price:target?Number(target):null,stop_loss:stop?Number(stop):null,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),status:'HOLDING_NORMAL'});
  var arr=POSITIONS[m]||(POSITIONS[m]=[]), k=positionKey(pos), found=false;
  for(var i=0;i<arr.length;i++){if(positionKey(arr[i])===k){pos.created_at=arr[i].created_at||pos.created_at;arr[i]=Object.assign({},arr[i],pos,{updated_at:new Date().toISOString()});found=true;break;}}
  if(!found)arr.unshift(pos);
  await savePositions(m); renderPositions(); toast(found?'已更新持倉':'已新增持倉','ok');
}
async function removePosition(mkt,id){
  mkt=normalizePositionMarket(mkt); POSITIONS[mkt]=(POSITIONS[mkt]||[]).filter(function(p){return String(p.symbol||p.stock_id)!==String(id);});
  await savePositions(mkt); renderPositions(); toast('已移除持倉','ok');
}
async function refreshPositions(showMsg){
  if(showMsg!==false)toast('正在重新檢查持倉…','warn');
  for(var m of ['tw','us']){
    for(var i=0;i<(POSITIONS[m]||[]).length;i++){
      var p=POSITIONS[m][i],sym=p.symbol||p.stock_id;
      try{
        // 沒填的欄位不要送空字串，否則後端回 422、價格不會更新
        var qs=new URLSearchParams({market:m,symbol:sym});[['avg_price',p.avg_price],['shares',p.shares],['target',p.target_price],['stop',p.stop_loss]].forEach(function(kv){if(kv[1]!=null&&kv[1]!=='')qs.append(kv[0],kv[1]);});
        var url=API+'/api/position/check?'+qs.toString();
        var r=await apiFetch(url,{},12000); if(r.ok){var d=await r.json();p.current_price=d.price;p.price=d.price;p.name=d.name||p.name;var ps=d.position_status||{};p.status=ps.status||p.status;p.unrealized_pnl=ps.unrealized_pnl;p.unrealized_pnl_pct=ps.unrealized_pnl_pct;p.risk_amount=ps.risk_amount;p.distance_to_target_pct=ps.distance_to_target_pct;p.distance_to_stop_pct=ps.distance_to_stop_pct;p.alerts=ps.alerts||[];p.checked_at=d.checked_at;}
        else { POSITIONS[m][i]=localCheckPosition(p); }
      }catch(e){POSITIONS[m][i]=localCheckPosition(p);}
    }
    try{await savePositions(m);}catch(e){}
  }
  renderPositions(); if(showMsg!==false)toast('持倉已更新','ok');
}
function renderPositions(){
  var all=getAllPositions().map(localCheckPosition); var filtered=all.filter(function(p){return POSITION_FILTER==='all'||p.market===POSITION_FILTER||p.status===POSITION_FILTER;});
  setTxt('positionTotalBadge',all.length+' 檔');
  var counts={HOLDING_NORMAL:0,NEAR_TARGET:0,TARGET_REACHED:0,NEAR_STOP:0,STOP_BROKEN:0,RISK_UP:0,NO_PRICE:0}; var totalPnl=0;
  all.forEach(function(p){counts[p.status]=(counts[p.status]||0)+1;if(Number.isFinite(Number(p.unrealized_pnl)))totalPnl+=Number(p.unrealized_pnl);});
  var sg=$I('positionSummaryGrid'); if(sg){sg.innerHTML=[['全部',all.length],['未實現損益',Number(totalPnl.toFixed(2))],['接近目標',counts.NEAR_TARGET+counts.TARGET_REACHED],['接近停損',counts.NEAR_STOP+counts.STOP_BROKEN],['風險升高',counts.RISK_UP]].map(function(x){var cls=(x[0]==='未實現損益'?(Number(x[1])>=0?'down':'up'):'');return '<div class="position-stat"><div class="k">'+x[0]+'</div><div class="v '+cls+'">'+x[1]+'</div></div>';}).join('');}
  var grid=$I('positionGrid'),empty=$I('positionEmpty'); if(!grid)return;
  if(empty)empty.style.display=filtered.length?'none':'block';
  grid.innerHTML=filtered.map(function(p){var sym=p.symbol||p.stock_id,name=p.name||sym,m=p.market||'tw',up=m==='us'?'us-up':'tw-up',down=m==='us'?'us-down':'tw-down';var pnl=Number(p.unrealized_pnl||0);var pnlCls=pnl>=0?up:down;var curr=m==='us'?fUS(p.price):f(p.price);var curVal=(Number(p.price||0)*Number(p.shares||0));var alerts=(p.alerts||[]).slice(0,2).join('；');return '<div class="position-card '+m+'" data-position-open="'+m+':'+esc(sym)+'">'+
    '<div class="position-top"><div><div class="position-name">'+esc(name)+'</div><div class="position-code">'+esc(sym)+' · '+m.toUpperCase()+'</div></div><span class="position-status '+positionStatusClass(p.status)+'">'+positionStatusLabel(p.status)+'</span></div>'+ 
    '<div class="position-metrics"><span class="lbl">現價</span><span class="val">'+curr+'</span><span class="lbl">買入價</span><span class="val">'+(m==='us'?fUS(p.avg_price):f(p.avg_price))+'</span><span class="lbl">股數</span><span class="val">'+(p.shares||'—')+'</span><span class="lbl">市值</span><span class="val">'+(curVal?Number(curVal.toFixed(2)):'—')+'</span><span class="lbl">未實現損益</span><span class="val '+pnlCls+'">'+(p.unrealized_pnl!=null?p.unrealized_pnl+' ('+(p.unrealized_pnl_pct||0)+'%)':'—')+'</span><span class="lbl">最大風險</span><span class="val">'+(p.risk_amount!=null?p.risk_amount:'—')+'</span><span class="lbl">目標</span><span class="val">'+(p.target_price?f(p.target_price):'—')+'</span><span class="lbl">停損</span><span class="val">'+(p.stop_loss?f(p.stop_loss):'—')+'</span></div>'+ 
    (alerts?'<div class="position-alert">⚠️ '+esc(alerts)+'</div>':'')+'<div class="position-note">'+esc(p.strategy_type||p.notes||'—')+'</div><div class="position-actions"><button class="ghost sm" data-position-open-btn="'+m+':'+esc(sym)+'">打開</button><button class="ghost sm" data-position-close="'+m+':'+esc(sym)+'">結束交易</button><button class="ghost sm danger" data-position-remove="'+m+':'+esc(sym)+'">移除</button></div></div>';}).join('');
}
function openPosition(mkt,id){if(mkt==='us'&&!ENABLE_US){toast('美股功能目前收起來了','warn');return;}switchMarket(mkt);if(mkt==='us')usLoadStock(id);else loadStock(id);showPage('p-trade');}


// ── Trade Journal / Performance / Report Center (V12.7) ─────────────
function journalRefSafe(uid,mkt){return journalRef(uid,mkt);} 
function normalizeJournalTrade(t,mkt){
  t=t||{};var sym=t.symbol||t.stock_id||t.code||t.ticker||t.id||'';
  return Object.assign({},t,{market:normalizePositionMarket(t.market||mkt||'tw'),symbol:String(sym||'').toUpperCase(),stock_id:t.stock_id||String(sym||'').toUpperCase(),name:t.name||t.stock_name||t.title||sym,closed_at:t.closed_at||t.exit_date||t.updated_at||t.created_at||nowISO()});
}
function journalMergeKey(t){return [t.market||'tw',String(t.symbol||t.stock_id||''),String(t.closed_at||t.exit_date||t.created_at||''),String(t.exit_price||t.sell_price||''),String(t.entry_price||t.avg_price||t.buy_price||'')].join('|');}
function mergeJournalRows(base,extra,mkt){
  var out=[],seen={};
  (base||[]).concat(extra||[]).forEach(function(x){if(!x)return;var t=normalizeJournalTrade(x,mkt);var k=journalMergeKey(t);if(!seen[k]){seen[k]=1;out.push(t);}});
  return out.sort(function(a,b){return new Date(b.closed_at||b.exit_date||b.created_at||0)-new Date(a.closed_at||a.exit_date||a.created_at||0);});
}
function extractJournalArrays(d){
  d=d||{};var arr=[];['trades','records','items','journal','closed_trades','history','data'].forEach(function(k){if(Array.isArray(d[k]))arr=arr.concat(d[k]);});
  return arr;
}
async function getDocJournalRows(ref,mkt){
  var rows=[];try{var s=await ref.get();if(s&&s.exists)rows=rows.concat(extractJournalArrays(s.data()));}catch(e){console.warn('journal doc read skipped',e.message||e);}
  try{var qs=await ref.collection('trades').get();qs.forEach(function(doc){rows.push(Object.assign({id:doc.id},doc.data()||{}));});}catch(e){}
  try{var qs2=await ref.collection('items').get();qs2.forEach(function(doc){rows.push(Object.assign({id:doc.id},doc.data()||{}));});}catch(e){}
  return rows.map(function(x){return normalizeJournalTrade(x,mkt);});
}
async function recoverJournalRows(uid,mkt){
  var rows=[];if(!db||!uid)return rows;
  var user=db.collection('users').doc(uid);
  var refs=[
    user.collection('trade_journal').doc(mkt),
    user.collection('trade_journals').doc(mkt),
    user.collection('journals').doc(mkt),
    user.collection('closed_trades').doc(mkt),
    user.collection('tradeHistory').doc(mkt),
    user.collection('trade_journal_'+mkt).doc('main')
  ];
  for(var i=0;i<refs.length;i++){rows=mergeJournalRows(rows,await getDocJournalRows(refs[i],mkt),mkt);}
  ['aipicker_trade_journal_','trade_journal_','journal_','AIPICKER_JOURNAL_'].forEach(function(prefix){
    try{var raw=localStorage.getItem(prefix+uid+'_'+mkt)||localStorage.getItem(prefix+mkt+'_'+uid)||localStorage.getItem(prefix+mkt);if(raw){var v=JSON.parse(raw);rows=mergeJournalRows(rows,Array.isArray(v)?v:extractJournalArrays(v),mkt);}}catch(e){}
  });
  return rows;
}
async function loadJournal(autoRepair){
  JOURNAL={tw:[],us:[]}; if(!currentUser||!db)return JOURNAL;var recoveredCount=0;
  for(var m of ['tw','us']){
    try{
      var canonical=journalRefSafe(currentUser.uid,m), canonicalRows=[];
      if(canonical){var s=await canonical.get();var d=s.exists?s.data():{};canonicalRows=Array.isArray(d.trades)?d.trades:extractJournalArrays(d);}
      var allRows=autoRepair?await recoverJournalRows(currentUser.uid,m):canonicalRows;
      JOURNAL[m]=mergeJournalRows([],allRows,m);
      if(autoRepair&&JOURNAL[m].length>canonicalRows.length){recoveredCount+=JOURNAL[m].length-canonicalRows.length;await saveJournal(m);}
    }catch(e){console.warn('load journal',m,e);}
  }
  if(autoRepair&&recoveredCount>0)toast('已修復交易日誌 '+recoveredCount+' 筆','ok');
  return JOURNAL;
}
async function reloadJournal(autoRepair){await loadJournal(!!autoRepair);renderJournal();toast(autoRepair?'交易日誌已重新掃描並修復':'交易日誌已重新載入','ok');}
async function saveJournal(mkt){mkt=normalizePositionMarket(mkt);if(!currentUser||!db)return;var ref=journalRefSafe(currentUser.uid,mkt);if(!ref)return;await ref.set({market:mkt,trades:mergeJournalRows([],JOURNAL[mkt]||[],mkt),updated_at:new Date().toISOString()},{merge:true});}
function allJournal(){return (JOURNAL.tw||[]).concat(JOURNAL.us||[]);}
function tradeKey(t){return (t.market||'tw')+":"+String(t.symbol||t.stock_id||t.id)+":"+String(t.closed_at||t.exit_date||t.created_at||'');}
function calcTrade(t){
  var entry=Number(t.avg_price||t.entry_price||t.buy_price), exitp=Number(t.exit_price||t.sell_price), shares=Number(t.shares||1), stop=Number(t.stop_loss), target=Number(t.target_price);
  var pnl=null,pct=null,rm=null;if(Number.isFinite(entry)&&Number.isFinite(exitp)){pnl=(exitp-entry)*shares;pct=entry?(exitp-entry)/entry*100:null;if(Number.isFinite(stop)&&entry>stop)rm=(exitp-entry)/(entry-stop);} 
  var ed=t.entry_date||t.created_at, xd=t.exit_date||t.closed_at, days=null;try{if(ed&&xd)days=Math.max(0,Math.round((new Date(xd)-new Date(ed))/86400000));}catch(e){}
  return Object.assign({},t,{pnl:pnl==null?null:Number(pnl.toFixed(2)),return_pct:pct==null?null:Number(pct.toFixed(2)),r_multiple:rm==null?null:Number(rm.toFixed(2)),hold_days:days,win:pnl!=null&&pnl>0,hit_target:Number.isFinite(target)&&Number.isFinite(exitp)&&exitp>=target,hit_stop:Number.isFinite(stop)&&Number.isFinite(exitp)&&exitp<=stop});
}
function journalSummary(){
  var rows=allJournal().map(calcTrade), closed=rows.filter(function(t){return t.pnl!=null;});var total=closed.length,wins=closed.filter(function(t){return t.pnl>0;});
  var pnl=closed.reduce(function(a,t){return a+Number(t.pnl||0);},0);var avg=total?closed.reduce(function(a,t){return a+Number(t.return_pct||0);},0)/total:0;var rRows=closed.filter(function(t){return t.r_multiple!=null});var avgR=rRows.length?rRows.reduce(function(a,t){return a+Number(t.r_multiple||0);},0)/rRows.length:0;
  var by={};closed.forEach(function(t){var k=t.strategy_type||'Unclassified';if(!by[k])by[k]={trades:0,wins:0,pnl:0,rs:[]};by[k].trades++;if(t.pnl>0)by[k].wins++;by[k].pnl+=Number(t.pnl||0);if(t.r_multiple!=null)by[k].rs.push(Number(t.r_multiple));});
  var stats=Object.keys(by).map(function(k){var d=by[k];return{strategy_type:k,trades:d.trades,win_rate:d.trades?Number((d.wins/d.trades*100).toFixed(1)):0,pnl:Number(d.pnl.toFixed(2)),avg_r:d.rs.length?Number((d.rs.reduce(function(a,b){return a+b;},0)/d.rs.length).toFixed(2)):null};}).sort(function(a,b){return b.pnl-a.pnl;});
  return{rows:rows,closed:closed,total:total,wins:wins.length,losses:total-wins.length,win_rate:total?Number((wins.length/total*100).toFixed(1)):0,total_pnl:Number(pnl.toFixed(2)),avg_return_pct:Number(avg.toFixed(2)),avg_r_multiple:Number(avgR.toFixed(2)),strategy_stats:stats};
}
async function closePosition(mkt,id){
  mkt=normalizePositionMarket(mkt);var arr=POSITIONS[mkt]||[],idx=arr.findIndex(function(p){return String(p.symbol||p.stock_id)===String(id);});if(idx<0){toast('找不到持倉','err');return;}
  var p=arr[idx];var def=p.current_price||p.price||p.avg_price||'';var exitp=prompt('賣出價 / Exit Price',def);if(exitp===null||exitp==='')return;var reason=prompt('賣出原因（達到目標/停損出場/手動獲利/風險升高/其他）','手動結束')||'手動結束';var note=prompt('備註（可空白）','')||'';
  var t=calcTrade(Object.assign({},p,{id:String(id)+'_'+Date.now(),market:mkt,symbol:p.symbol||p.stock_id,stock_id:p.stock_id||p.symbol,name:p.name||id,entry_price:p.avg_price,exit_price:Number(exitp),exit_reason:reason,notes:note,exit_date:new Date().toISOString().slice(0,10),closed_at:new Date().toISOString()}));
  JOURNAL[mkt]=JOURNAL[mkt]||[];JOURNAL[mkt].unshift(t);POSITIONS[mkt].splice(idx,1);await saveJournal(mkt);await savePositions(mkt);renderPositions();renderJournal();toast('已結束交易並移入日誌','ok');showPage('p-journal');
}
async function removeJournalTrade(mkt,key){mkt=normalizePositionMarket(mkt);JOURNAL[mkt]=(JOURNAL[mkt]||[]).filter(function(t){return tradeKey(t)!==key;});await saveJournal(mkt);renderJournal();toast('已刪除交易日誌','ok');}
function renderJournal(){
  var sum=journalSummary(), rows=sum.rows.filter(function(t){return JOURNAL_FILTER==='all'||t.market===JOURNAL_FILTER||(JOURNAL_FILTER==='win'&&t.win)||(JOURNAL_FILTER==='loss'&&t.pnl!=null&&!t.win);});
  setTxt('journalTotalBadge',sum.total+' 筆');var sg=$I('journalSummaryGrid');if(sg){sg.innerHTML=[['總交易',sum.total],['勝率',sum.win_rate+'%'],['總損益',sum.total_pnl],['平均報酬',sum.avg_return_pct+'%'],['平均 R',sum.avg_r_multiple],['勝/敗',sum.wins+' / '+sum.losses]].map(function(x){var cls=(x[0]==='總損益'||x[0]==='平均報酬'||x[0]==='平均 R')?(Number(String(x[1]).replace('%',''))>=0?'down':'up'):'';return'<div class="journal-stat"><div class="k">'+x[0]+'</div><div class="v '+cls+'">'+x[1]+'</div></div>';}).join('');}
  var grid=$I('journalGrid'),empty=$I('journalEmpty');if(grid){if(empty)empty.style.display=rows.length?'none':'block';grid.innerHTML=rows.map(function(t){t=calcTrade(t);var sym=t.symbol||t.stock_id,name=t.name||sym,m=t.market||'tw',pnl=Number(t.pnl||0),cls=pnl>=0?(m==='us'?'us-up':'tw-up'):(m==='us'?'us-down':'tw-down'),key=tradeKey(t);return'<div class="journal-card"><div class="journal-top"><div><div class="journal-name">'+esc(name)+'</div><div class="journal-code">'+esc(sym)+' · '+m.toUpperCase()+' · '+esc(t.exit_reason||'')+'</div></div><span class="journal-status '+(t.win?'ok':'risk')+'">'+(t.win?'WIN':'LOSS')+'</span></div><div class="journal-metrics"><span class="lbl">買入</span><span class="val">'+(m==='us'?fUS(t.entry_price||t.avg_price):f(t.entry_price||t.avg_price))+'</span><span class="lbl">賣出</span><span class="val">'+(m==='us'?fUS(t.exit_price):f(t.exit_price))+'</span><span class="lbl">損益</span><span class="val '+cls+'">'+(t.pnl!=null?t.pnl:'—')+'</span><span class="lbl">報酬</span><span class="val '+cls+'">'+(t.return_pct!=null?t.return_pct+'%':'—')+'</span><span class="lbl">R</span><span class="val">'+(t.r_multiple!=null?t.r_multiple+'R':'—')+'</span><span class="lbl">天數</span><span class="val">'+(t.hold_days!=null?t.hold_days:'—')+'</span></div><div class="journal-note">策略：'+esc(t.strategy_type||'—')+'｜'+esc(t.notes||'')+'</div><div class="position-actions"><button class="ghost sm" data-journal-open="'+m+':'+esc(sym)+'">打開</button><button class="ghost sm danger" data-journal-remove="'+m+':'+esc(key)+'">刪除</button></div></div>';}).join('');}
  var sb=$I('strategyStatsBox');if(sb){sb.innerHTML=sum.strategy_stats.length?'<table class="strategy-table"><thead><tr><th>策略</th><th>交易</th><th>勝率</th><th>損益</th><th>平均 R</th></tr></thead><tbody>'+sum.strategy_stats.map(function(s){return'<tr><td>'+esc(s.strategy_type)+'</td><td>'+s.trades+'</td><td>'+s.win_rate+'%</td><td>'+s.pnl+'</td><td>'+(s.avg_r==null?'—':s.avg_r)+'</td></tr>';}).join('')+'</tbody></table>':'<div class="empty">尚無策略統計</div>';}
  generateReportText(false);
}
function generateReportText(show){var s=journalSummary();var best=s.strategy_stats[0]?s.strategy_stats[0].strategy_type:'—';var txt='台股作戰室 V'+FRONTEND_VERSION+' 交易績效報告\n生成時間：'+new Date().toLocaleString('zh-TW')+'\n\n總交易數：'+s.total+'\n勝率：'+s.win_rate+'%\n總損益：'+s.total_pnl+'\n平均報酬：'+s.avg_return_pct+'%\n平均 R：'+s.avg_r_multiple+'\n最佳策略：'+best+'\n\nAI 回顧：'+(s.total?'目前已累積交易樣本，可開始觀察哪些 strategy_type 較適合你。若平均 R 低於 1，建議檢查是否太早出場或 RR 不足。':'目前尚無已結束交易，先從持倉管理結束交易後累積樣本。');setTxt('reportText',txt);if(show)toast('報告已產生','ok');return txt;}
function exportJournalCsv(){var rows=journalSummary().rows;if(!rows.length){toast('沒有日誌可匯出','warn');return;}var cols=['market','symbol','name','entry_price','exit_price','shares','pnl','return_pct','r_multiple','strategy_type','exit_reason','exit_date'];var csv=[cols.join(',')].concat(rows.map(function(r){r=calcTrade(r);return cols.map(function(c){return '"'+String(r[c]==null?'':r[c]).replace(/"/g,'""')+'"';}).join(',');})).join('\n');var blob=new Blob([csv],{type:'text/csv;charset=utf-8;'});var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='aipicker_trade_journal_'+new Date().toISOString().slice(0,10)+'.csv';a.click();URL.revokeObjectURL(a.href);}
async function copyReport(){var txt=generateReportText(false);try{await navigator.clipboard.writeText(txt);toast('報告已複製','ok');}catch(e){prompt('複製以下報告',txt);}}

// ── System Health / Version Check ─────────────────────────────────
function safeVal(v, fallback){ if(v===undefined||v===null||Number.isNaN(v)) return fallback||"—"; return v; }
function setHealth(id, text, cls){var el=$I(id);if(!el)return;el.textContent=text;el.className=cls||"";}
function statusCls(st){st=String(st||"").toLowerCase();return st==="ok"?"health-ok":(st==="partial"||st==="degraded"?"health-warn":"health-bad");}
async function loadSystemHealth(){
  setTxt("sysHealthShort","檢查中…");
  setHealth("hFrontend","V"+FRONTEND_VERSION,"health-ok");
  setHealth("hFirestore",currentUser?"Connected":"待登入",currentUser?"health-ok":"health-warn");
  try{
    var r=await apiFetch(API+"/api/health/full",{},15000);
    var d=await r.json();
    if(!r.ok)throw new Error(d.detail||"health failed");
    var bv=d.version||((d.backend||{}).version)||"—";
    setHealth("hBackend","V"+bv,bv===FRONTEND_VERSION?"health-ok":"health-warn");
    var tw=((d.data_health||{}).tw||{}).checks||{};
    setHealth("hYahoo",((tw.macro||{}).status||"—"),statusCls((tw.macro||{}).status));
    setHealth("hTwse",((tw.twse_mis||{}).status||"—"),statusCls((tw.twse_mis||{}).status));
    var st=d.storage||{};setHealth("hBackup",st.enabled?(st.last_error?"錯誤":"已啟用"):"未設定",st.enabled&&!st.last_error?"health-ok":"health-warn");
    var vw=$I("versionWarn");
    if(vw){
      if(bv!==FRONTEND_VERSION){vw.style.display="block";vw.textContent="前後端版本不一致：Frontend V"+FRONTEND_VERSION+"，Backend V"+bv+"。請確認 Render 是否已部署最新版本，或按 Ctrl+F5。";}
      else{vw.style.display="none";vw.textContent="";}
    }
    var twh=((d.data_health||{}).tw||{}).overall;setTxt("sysHealthShort","後端 V"+bv+" · 台股資料"+(twh==="ok"?"正常":(twh?"："+twh:"—")));setHdrDot(twh==="ok"?"ok":"warn");
  }catch(e){
    console.warn("system health failed",e);
    setTxt("sysHealthShort","後端連不上（可能正在喚醒，約 1 分鐘）");setHdrDot("off");
    setHealth("hBackend","檢查失敗","health-bad");
  }
}

// ── Scroll to anchor ────────────────────────────────────────────────
function scrollToAnchor(id){var el=$I(id);if(el)el.scrollIntoView({behavior:"smooth",block:"start"});}

// ── Clock ─────────────────────────────────────────────────────────
setInterval(function(){setTxt("clock",new Date().toLocaleString("zh-TW",{timeZone:"Asia/Taipei"}));},1000);
function setHdrDot(st){var d=$I("hdrDot");if(!d)return;d.classList.remove("off","warn");if(st!=="ok")d.classList.add(st);d.title=st==="ok"?"系統正常":st==="warn"?"資料部分異常":"後端連不上";}

// ══════════════════════════════════════════════════════════════════
// initApp
// ══════════════════════════════════════════════════════════════════
function bindAllButtons() {
  // Login
  safeBind("btnLoginOverlay","click",googleLogin);
  safeBind("btnGoogleLogin","click",googleLogin);
  safeBind("btnLogout","click",googleLogout);
  // TW nav
  document.querySelectorAll(".nav-tab").forEach(function(btn){btn.addEventListener("click",function(){if(btn.dataset.page)showPage(btn.dataset.page);});});
  // TW chart tabs
  document.querySelectorAll(".tab[data-tab]").forEach(function(btn){btn.addEventListener("click",function(){swTab(btn.dataset.tab,btn);});});
  // TW search
  safeBind("btnSearch","click",doSearch);safeBind("btnAdd","click",addWL);safeBind("btnLoadFullMobile","click",function(){if(CURRENT_ID)loadTwFullAnalysis(CURRENT_ID,{silent:false,mobile:false,timeout:45000});});initSearchSuggest();
  // TW WL
  safeBind("btnRefresh","click",function(){if(!currentUser)return;isRefreshWL=false;wlLeft=30;refreshWL();});
  safeBind("btnScan","click",function(){scanAlerts(false);});
  safeBind("btnScan2","click",function(){scanAlerts(false);});
  safeBind("btnAiScan","click",function(){aiScan();});safeBind("btnAiScanAgain","click",function(){aiScan();});
  safeBind("btnTwQuickScan","click",function(){aiScan("quick");});
  safeBind("btnTwFullScan","click",function(){aiScan("full");});
  safeBind("btnToggleWl","click",toggleWatchlistExpanded);
  safeBind("twPortfolioSelect","change",function(){onPortfolioChange("tw");});
  safeBind("btnTwPortfolioNew","click",function(){createPortfolio("tw");});
  safeBind("btnTwPortfolioRename","click",function(){renamePortfolio("tw");});
  safeBind("btnTwPortfolioDelete","click",function(){deletePortfolio("tw");});
  safeBind("btnTwPortfolioScan","click",function(){scanActivePortfolio("tw");});
  // TW quick nav
  safeBind("qnAiScan","click",function(){aiScan();});
  safeBind("qnKline","click",function(){scrollToAnchor("anchorKline");});
  safeBind("qnA4d","click",function(){scrollToAnchor("anchorA4d");});
  // TW 4D
  safeBind("btnLoad4d","click",load4d);
  // TW auto
  safeBind("btnAuto","click",toggleAuto);
  // TW LINE
  safeBind("btnTestLine","click",testLine);
  // TW backtest & learn
  safeBind("btnBt","click",runBt);
  safeBind("btnWeights","click",loadWeights);
  safeBind("btnEval","click",function(){learnAction("eval");});
  safeBind("btnRetrain","click",function(){learnAction("retrain");});
  safeBind("btnHistory","click",function(){learnAction("history");});
  safeBind("btnApplySuggestedWeights","click",applySuggestedWeights);
  safeBind("btnWeightHistory","click",showWeightHistory);
  safeBind("learnMarket","change",loadWeights);
  // TW macro/sentiment
  safeBind("btnLoadMacro","click",loadMacro);
  safeBind("btnLoadSentiment","click",loadSentiment);
  // TW account
  safeBind("btnManualSync","click",function(){if(!currentUser)return;setSyncBadge("ing");saveWatchlist();});
  safeBind("btnRestoreLegacy","click",function(){if(!currentUser)return;runMigration(currentUser.uid,[]).then(function(){renderWL();setSyncBadge("migrated");});});
  // Market switcher
  var btnTW=$I("btnMktTW"),btnUS=$I("btnMktUS");
  if(btnTW)btnTW.addEventListener("click",function(){switchMarket("tw");});
  if(btnUS)btnUS.addEventListener("click",function(){switchMarket("us");});
  // US buttons
  safeBind("btnUsSearch","click",usDoSearch);
  safeBind("btnUsAdd","click",addUSWL);
  safeBind("btnUsRefresh","click",function(){usWlLeft=30;refreshUSWL();});
  safeBind("btnUsScan","click",function(){usAiScan();});
  safeBind("btnUsScanAgain","click",function(){usAiScan();});
  safeBind("btnUsQuickScan","click",function(){usAiScan("quick");});
  safeBind("btnUsFullScan","click",function(){usAiScan("full");});
  safeBind("btnUsCtx","click",loadUSMarketContext);
  safeBind("usPortfolioSelect","change",function(){onPortfolioChange("us");});
  safeBind("btnUsPortfolioNew","click",function(){createPortfolio("us");});
  safeBind("btnUsPortfolioRename","click",function(){renamePortfolio("us");});
  safeBind("btnUsPortfolioDelete","click",function(){deletePortfolio("us");});
  safeBind("btnUsPortfolioScan","click",function(){scanActivePortfolio("us");});
  safeBind("btnSavePlanTw","click",function(){addCurrentTradePlan("tw");});
  safeBind("btnSavePlanUs","click",function(){addCurrentTradePlan("us");});
  safeBind("btnRefreshPlans","click",function(){refreshTradePlans(true);});
  safeBind("btnAddPosition","click",manualAddPosition);
  safeBind("btnRefreshPositions","click",function(){refreshPositions(true);});
  safeBind("btnJournalRefresh","click",function(){reloadJournal(false);});
  safeBind("btnJournalRepair","click",function(){reloadJournal(true);});
  safeBind("btnJournalExport","click",exportJournalCsv);
  safeBind("btnReportCopy","click",copyReport);
  safeBind("btnReportGenerate","click",function(){generateReportText(true);});
  safeBind("btnHealthRefresh","click",loadSystemHealth);
  safeBind("btnHealthToggle","click",function(){var p=$I("systemHealthPanel"),b=$I("btnHealthToggle");if(!p)return;p.classList.toggle("compact");if(b)b.textContent=p.classList.contains("compact")?"展開":"收合";});
  initUSSuggest();
}

async function initApp() {
  applyFeatureFlags();
  try{renderHQ();}catch(e){console.warn("hq",e);}
  // 曾登入過的使用者先直接顯示總覽，等 Firebase 還原登入；還原失敗時回呼會再顯示登入畫面
  var wasIn=false;try{wasIn=localStorage.getItem("tw_was_logged_in")==="1";}catch(e){}
  if(wasIn) hideLoginOverlay(); else showLoginOverlay();
  bindAllButtons();
  initFirebase();
  loadStockMaster();
  // 健康檢查改由登入狀態回呼觸發，避免重複呼叫；Firebase 載入失敗時才在這裡補一次
  if(!ensureFirebaseReady()) loadSystemHealth();
  var statusEl=$I("usMasterStatus");if(statusEl)setTimeout(function(){statusEl.textContent="Symbol master: 80+ built-in symbols loaded. Background update running…";},2000);
}

document.addEventListener("click",function(e){
  var f=e.target&&e.target.getAttribute&&e.target.getAttribute("data-plan-filter");if(f){PLAN_FILTER=f;renderTradePlans();return;}
  var pf=e.target&&e.target.getAttribute&&e.target.getAttribute("data-position-filter");if(pf){POSITION_FILTER=pf;renderPositions();return;}
  var conv=e.target&&e.target.getAttribute&&e.target.getAttribute("data-plan-convert");if(conv){e.stopPropagation();var cc=conv.split(":");convertPlanToPosition(cc[0],cc.slice(1).join(":"));return;}
  var rm=e.target&&e.target.getAttribute&&e.target.getAttribute("data-plan-remove");if(rm){e.stopPropagation();var a=rm.split(":");removeTradePlan(a[0],a.slice(1).join(":"));return;}
  var prm=e.target&&e.target.getAttribute&&e.target.getAttribute("data-position-remove");if(prm){e.stopPropagation();var pa=prm.split(":");removePosition(pa[0],pa.slice(1).join(":"));return;}
  var pcl=e.target&&e.target.getAttribute&&e.target.getAttribute("data-position-close");if(pcl){e.stopPropagation();var px=pcl.split(":");closePosition(px[0],px.slice(1).join(":"));return;}
  var jf=e.target&&e.target.getAttribute&&e.target.getAttribute("data-journal-filter");if(jf){JOURNAL_FILTER=jf;renderJournal();return;}
  var jrm=e.target&&e.target.getAttribute&&e.target.getAttribute("data-journal-remove");if(jrm){e.stopPropagation();var jr=jrm.split(":");removeJournalTrade(jr[0],jr.slice(1).join(":"));return;}
  var jop=e.target&&e.target.getAttribute&&e.target.getAttribute("data-journal-open");if(jop){e.stopPropagation();var jo=jop.split(":");openPosition(jo[0],jo.slice(1).join(":"));return;}
  var op=e.target&&e.target.getAttribute&&e.target.getAttribute("data-plan-open-btn");if(op){e.stopPropagation();var b=op.split(":");openTradePlan(b[0],b[1]);return;}
  var pop=e.target&&e.target.getAttribute&&e.target.getAttribute("data-position-open-btn");if(pop){e.stopPropagation();var pb=pop.split(":");openPosition(pb[0],pb[1]);return;}
  var pcard=e.target&&e.target.closest&&e.target.closest("[data-position-open]");if(pcard){var pc=pcard.getAttribute("data-position-open").split(":");openPosition(pc[0],pc[1]);return;}
  var card=e.target&&e.target.closest&&e.target.closest("[data-plan-open]");if(card){var c=card.getAttribute("data-plan-open").split(":");openTradePlan(c[0],c[1]);}
});
document.addEventListener("DOMContentLoaded",initApp);
