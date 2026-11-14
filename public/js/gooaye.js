/* 股癌紀律提醒（v14.2.1）：把 Podcast 反覆出現的觀點整理成檢查清單，用自己的話摘要，不是逐字內容。
   只有通過「扣元大成本、對照 0050、分段檢驗」的才標成有回測支持，其餘一律只當提醒，不是買賣訊號。
   回測程式與結果：research/gooaye/。 */
(function(){
  function $(id){return document.getElementById(id);}
  function e(s){return String(s==null?"":s).replace(/[&<>'"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c];});}
  var TAG={ok:["有回測支持","gy-ok"],fail:["回測未通過","gy-fail"],note:["紀律提醒","gy-note"]};
  var RULES=[
    {id:"chase",tag:"ok",title:"昨天漲停的股票，今天開盤不要追",
     text:"節目多次提到「隔日沖」：前一天鎖漲停，隔天常被倒貨。",
     test:"回測 2015/7–2026/11、成交值前 200 大、5,804 次漲停：隔天開盤買、當天收盤賣，扣成本平均 −0.55%，勝率 42%，12 年裡 11 年是負的。"},
    {id:"slow",tag:"note",title:"盤整或震盪時，先縮小部位、放慢腳步",
     text:"沒買到就放掉，等量縮拉回再看；頻繁追價的磨損會一點一點吃掉本金。"},
    {id:"ytd",tag:"note",title:"今年賺得不多，就守得更嚴",
     text:"防守強度看今年累積損益：獲利墊厚才容許較深的回檔，獲利薄就嚴格停損。帳本頁可以看今年的淨損益。"},
    {id:"own",tag:"note",title:"不跟單，停損自己負責",
     text:"節目自己說不是報牌。聽來的標的也要有自己的進場理由和停損價，套牢時照計畫執行。"},
    {id:"lever",tag:"note",title:"槓桿只用在短期事件，不長抱",
     text:"高槓桿的淨值曲線抱久了很容易歸零。這和本站 00631L 研究的結論一致：用均線與波動控管部位。"},
    {id:"short",tag:"note",title:"多頭時不摸頭放空",
     text:"趨勢明確轉壞才考慮空單；散戶在多頭裡避險常常越避越險。本站的當沖風控也不允許先賣後買。"},
    {id:"priced",tag:"note",title:"大消息出來，先別急著下結論",
     text:"市場通常已提前反映，直覺的方向常常是錯的。看不懂就先離開會被第一排波及的標的，等情況明朗。"},
    {id:"basket",tag:"note",title:"新題材初期用一籃子，不單押",
     text:"每個次領域挑 1–2 檔分散，方向對比挑到最強的那一檔重要。大部分資金仍放在 0050 這類被動 ETF。"},
    {id:"foreign",tag:"note",title:"「外資」不是同一個人",
     text:"外資買賣超混了很多不同的資金，別對單日數字過度解讀。本站實測：外資買超對隔天漲跌幾乎沒有預測力。"},
    {id:"newhigh",tag:"fail",title:"「抱緊創新高、連跌 5 天就出場」不能當訊號",
     text:"這是媒體報導過的做法。它像是個人裁量的習慣，不是可以照抄的機械規則。",
     test:"回測 2014–2026：年化 23.2%、最大回檔 −38%、夏普 0.94；同期 0050 是 21.3%、−34%、1.09。2014–2019 只有 9.9%，輸 0050 的 13.8%。風險較高卻沒有穩定贏，所以本站不做成訊號。"}
  ];
  function pick(d){
    var w=(d&&d.watchlist)||[],r=(d&&d.risk)||{};
    var hot=w.filter(function(x){return x.chg_pct!=null&&Number(x.chg_pct)>=9.5;}).map(function(x){return x.code;});
    if(hot.length)return {rule:RULES[0],why:hot.join("、")+" 上一個交易日漲停"};
    if(r.color==="red")return {rule:RULES[1],why:"大盤風險燈是紅燈"};
    if(r.color==="yellow")return {rule:RULES[2],why:"大盤風險燈是黃燈"};
    var n=Math.floor((Date.now()+8*36e5)/864e5);
    return {rule:RULES[1+n%(RULES.length-2)],why:""};
  }
  function item(x){
    var t=TAG[x.tag];
    return '<li class="gy-item"><div class="gy-title"><span class="gy-tag '+t[1]+'">'+t[0]+'</span>'+e(x.title)+'</div><div class="gy-text">'+e(x.text)+'</div>'+(x.test?'<div class="gy-test">'+e(x.test)+'</div>':"")+'</li>';
  }
  window.renderGooaye=function(d){
    var box=$("gyCard");if(!box)return;
    var p=pick(d),open=box.querySelector("details")&&box.querySelector("details").open;
    var h='<div class="gy-head"><span class="gy-kicker">股癌紀律提醒</span><span class="gy-src">整理自 Podcast 重點，不是訊號</span></div>';
    h+='<div class="gy-today">'+(p.why?'<div class="gy-why">'+e(p.why)+'</div>':"")+'<div class="gy-title"><span class="gy-tag '+TAG[p.rule.tag][1]+'">'+TAG[p.rule.tag][0]+'</span>'+e(p.rule.title)+'</div><div class="gy-text">'+e(p.rule.text)+'</div>'+(p.rule.test?'<div class="gy-test">'+e(p.rule.test)+'</div>':"")+'</div>';
    h+='<details'+(open?" open":"")+'><summary>全部 '+RULES.length+' 條</summary><ul class="gy-list">'+RULES.map(item).join("")+'</ul>';
    h+='<div class="gy-foot">內容是把節目與公開筆記的觀點用自己的話整理，不代表節目立場，也不是投資建議。回測宇宙是今天成交值前 200 大，有倖存者偏誤，數字偏樂觀。</div></details>';
    box.innerHTML=h;box.style.display="block";
  };
  window.GOOAYE_RULES=RULES;
  function boot(){window.renderGooaye(window.TODAY||null);}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot);else boot();
})();
