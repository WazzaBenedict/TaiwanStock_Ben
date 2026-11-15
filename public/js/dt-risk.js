  (function(){
    var DEF={cash:5000,credit:200000,maxN:50000,day:1000,total:10000};
    function ld(k,d){try{var v=JSON.parse(localStorage.getItem(k));return v==null?d:v;}catch(e){return d;}}
    function sv(k,v){try{localStorage.setItem(k,JSON.stringify(v));}catch(e){}}
    function cfg(){var c=ld("tw_dt_risk_cfg",{});if(Number(c.total)===2500){c.total=10000;sv("tw_dt_risk_cfg",c);}var o={};for(var k in DEF)o[k]=Number(c[k])>0?Number(c[k]):DEF[k];return o;}
    function log(){var l=ld("tw_dt_risk_log",[]);return Array.isArray(l)?l:[];}
    function twNow(){var d=new Date(Date.now()+8*3600e3);return {date:d.toISOString().slice(0,10),min:d.getUTCHours()*60+d.getUTCMinutes()};}
    function disc(){return window.feeDisc?feeDisc():0.6;}
    function fee(n){return Math.max(20,Math.floor(n*0.001425*disc()));}
    function nt(x){x=Math.round(x);return (x<0?"-":"")+"NT$"+Math.abs(x).toLocaleString();}
    function tick(p){return p<10?0.01:p<50?0.05:p<100?0.1:p<500?0.5:p<1000?1:5;}
    function totals(){var t=twNow().date,day=0,all=0;log().forEach(function(e){all+=e.p;if(e.d===t)day+=e.p;});return {day:day,all:all};}
    function fill(){var c=cfg();["cash","credit","maxN","day","total"].forEach(function(k){var i=$I("rk"+k.charAt(0).toUpperCase()+k.slice(1));if(i)i.value=c[k];});}
    function drawLog(){var c=cfg(),T=totals(),el=$I("rkLog");if(!el)return;
      var cls=function(x){return x>0?"up":x<0?"down":"flat";};
      el.innerHTML='今日損益 <b class="'+cls(T.day)+'">'+nt(T.day)+'</b>（每日停損 '+nt(-c.day)+'）　累計 <b class="'+cls(T.all)+'">'+nt(T.all)+'</b>（總停損 '+nt(-c.total)+'）'+
        (T.all<=-c.total?'<br><b class="dt-neg">⛔ 已到總停損：停止真錢當沖，回到模擬交易。</b>':T.day<=-c.day?'<br><b class="dt-neg">⛔ 今天已到每日停損：收工，明天再說。</b>':'');}
    function check(){
      var c=cfg(),px=Number($I("rkPx").value),lots=Math.floor(Number($I("rkLots").value)||0),sp=Number($I("rkStop").value)||0,out=$I("rkOut");
      if(!(px>0)||lots<1){out.innerHTML='<span class="dt-neg">請輸入股價和張數</span>';return;}
      var n=px*1000*lots,cost=fee(n)*2+Math.floor(n*0.0015),be=cost/n*100,loss=n*sp/100+cost,T=totals(),now=twNow(),bad=[],warn=[];
      if(n>c.maxN)bad.push("金額 "+nt(n)+" 超過每筆上限 "+nt(c.maxN));
      if(n>c.credit)bad.push("超過當沖額度 "+nt(c.credit));
      if(px<20||px>50)bad.push("股價不在 20～50 元（太低跳動比例大、太高 1 張就太重）");
      if(T.all<=-c.total)bad.push("已到總停損，停止真錢當沖");
      else if(T.day<=-c.day)bad.push("今天已到每日停損");
      else if(T.day-loss< -c.day)bad.push("這筆若停損，今天會虧到 "+nt(T.day-loss)+"，超過每日停損");
      if(now.min>=13*60&&now.min<13*60+30)bad.push("13:00 後不再進場");
      if(n>c.cash)warn.push("賣不掉時 T+2 要付 "+nt(n)+"，你的交割金只有 "+nt(c.cash)+"，請確定 2 天內拿得出差額 "+nt(n-c.cash));
      if(sp>2)warn.push("停損 "+sp+"% 偏寬");
      out.innerHTML=(bad.length?'<b class="dt-neg">⛔ 不要下單</b>：'+bad.map(esc).join("；"):'<b class="dt-pass">✅ 在上限內</b>（仍然只是風控，不代表會賺）')+
        '<br>買進金額 '+nt(n)+'　來回成本 '+nt(cost)+'（要漲 '+be.toFixed(2)+'% ＋ 滑價才打平；1 跳 = '+(tick(px)/px*100).toFixed(2)+'%）'+
        '<br>停損 '+sp+'% 的虧損約 '+nt(loss)+'　停損價 ≈ '+(px*(1-sp/100)).toFixed(2)+
        (warn.length?'<br><span class="dt-neg">⚠️ '+warn.map(esc).join("<br>⚠️ ")+'</span>':'');
    }
    function init(){
      if(!$I("rkCheck")||$I("rkCheck").dataset.on)return; $I("rkCheck").dataset.on="1"; fill(); drawLog();
      $I("rkCheck").onclick=check;
      $I("rkSave").onclick=function(){var o={};["cash","credit","maxN","day","total"].forEach(function(k){o[k]=Number($I("rk"+k.charAt(0).toUpperCase()+k.slice(1)).value);});sv("tw_dt_risk_cfg",o);fill();drawLog();};
      $I("rkAdd").onclick=function(){var p=Number($I("rkPnl").value);if(!isFinite(p)||$I("rkPnl").value==="")return;var l=log();l.push({d:twNow().date,p:Math.round(p)});sv("tw_dt_risk_log",l.slice(-500));$I("rkPnl").value="";drawLog();};
      $I("rkReset").onclick=function(){if(confirm("清除所有損益紀錄？"))sv("tw_dt_risk_log",[]);drawLog();};
    }
    if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
  })();
