(function(){"use strict";const _=window.AgomTUIRuntimeCore||{},o={catalog:null,screen:null,screenBadges:{},screenBadgeDrilldowns:{},homePanelBadges:{},lastAction:null,lastParams:{},lastRaw:null,lastPager:null,currentViewModel:null,currentColumns:[],currentRows:[],visibleRows:[],selectedRowContext:null,filterText:"",selectedRowIndex:0,activeMenu:null,lastFormTriggerRef:"",lastFormTriggerAt:0,showSupportTasks:!1,showAdvancedQueries:!1,actionFilterText:"",completedActionsByScreen:{},railCollapsed:!1,inspectorCollapsed:!1,inspectorWidth:null,themeKey:"B",pinnedScreenKeys:new Set,preferredHomeLane:"decision",lastNonHomeScreen:"",pendingRequestId:0,latestRequestId:0,pendingController:null,slowActionTimer:null,clientPage:1,clientPageSize:100,operatorHomePayload:null,operatorHomePromise:null,modalReturnFocus:null,menuSourceButton:null},c={app:document.querySelector("[data-tui-app]"),railPanel:document.querySelector("[data-rail-panel]"),moduleTree:document.querySelector("[data-module-tree]"),screenTitle:document.querySelector("[data-screen-title]"),screenStatus:document.querySelector("[data-screen-status]"),actions:document.querySelector("[data-actions-panel]"),mainTitle:document.querySelector("[data-main-title]"),main:document.querySelector("[data-main-panel]"),workflowStrip:document.querySelector("[data-workflow-strip]"),inspector:document.querySelector("[data-inspector-panel]"),rawDrawer:document.querySelector("[data-raw-drawer]"),rawPanel:document.querySelector("[data-raw-panel]"),rawToggle:document.querySelector("[data-raw-toggle]"),rawClose:document.querySelector("[data-raw-close]"),pager:document.querySelector("[data-pager-status]"),clock:document.querySelector("[data-tui-clock]"),menuPopover:document.querySelector("[data-menu-popover]"),filterBar:document.querySelector("[data-filter-bar]"),filterInput:document.querySelector("[data-filter-input]"),filterClear:document.querySelector("[data-filter-clear]"),modal:document.querySelector("[data-tui-modal]"),modalTitle:document.querySelector("[data-modal-title]"),modalBody:document.querySelector("[data-modal-body]"),modalClose:document.querySelector("[data-modal-close]"),status:document.querySelector("[data-workbench-status]"),lastRefresh:document.querySelector("[data-last-refresh]"),currentLocation:document.querySelector("[data-current-location]"),railToggle:document.querySelector("[data-toggle-rail]"),inspectorShell:document.querySelector("[data-inspector-panel-shell]"),inspectorToggle:document.querySelector("[data-toggle-inspector]"),inspectorResizeHandle:document.querySelector("[data-inspector-resize-handle]"),themeStatus:document.querySelector("[data-theme-status]"),themeIndicatorCode:document.querySelector("[data-theme-indicator-code]")},gr={file:[["refresh","\u5237\u65B0\u5F53\u524D\u89C6\u56FE","F5"],["export","\u5BFC\u51FA\u5F53\u524D\u8868\u683C","F8"]],module:[["toggle-rail","\u5C55\u5F00/\u6536\u8D77\u6A21\u5757\u5BFC\u822A","F2"],["previous-workflow","\u4E0A\u4E00\u4E2A\u6D41\u7A0B\u5C4F","F3"],["next-workflow","\u4E0B\u4E00\u4E2A\u6D41\u7A0B\u5C4F","F4"]],action:[["run-next-primary","\u6267\u884C\u4E0B\u4E00\u4E3B\u6D41\u7A0B","F6"],["focus-actions","\u5B9A\u4F4D\u4EFB\u52A1\u533A","F9"],["row-detail","\u6253\u5F00\u9009\u4E2D\u884C","Enter"]],view:[["filter","\u7B5B\u9009\u8868\u683C","F7"],["filter-actions","\u7B5B\u9009\u5F53\u524D\u4EFB\u52A1","\u83DC\u5355"],["toggle-inspector","\u5C55\u5F00/\u6536\u8D77\u8BF4\u660E\u680F","F10"],["reset-progress","\u91CD\u7F6E\u672C\u5C4F\u8FDB\u5EA6","\u83DC\u5355"],["raw","\u539F\u59CB\u54CD\u5E94","\u83DC\u5355"]],help:[["help","\u952E\u76D8\u5E2E\u52A9","F1"]]},Pt={F1:"help",F2:"toggle-rail",F3:"previous-workflow",F4:"next-workflow",F5:"refresh",F6:"run-next-primary",F7:"filter",F8:"export",F9:"focus-actions",F10:"toggle-inspector"},Rt="agom-tui-primary-progress:v1",Ft="agom-tui-theme:v1",Et="agom-tui-inspector-width:v1",je="agom-tui-last-non-home-screen:v1",qt="agom-tui-pinned-screen-keys:v1",Bt="agom-tui-preferred-home-lane:v1",ke="agom-tui-resume-on-boot:v1",Oe=220,Ht=640,hr=980,br=.56,wr=250,Sr=120,kr=250,$r=15e3,vr=2*1024*1024,$e=["A","B","C"],_r={A:{background:"#001A8D",panelBackground:"#000B55",primaryText:"#FFFFFF",secondaryText:"#C0C0C0",border:"#00FFFF",highlight:"#FFFF00",accent:"#C0C0C0",success:"#00FF80",warning:"#FFFF00",error:"#FF4040",grid:"#002070"},B:{background:"#07090F",panelBackground:"#101827",primaryText:"#E8EEF8",secondaryText:"#AAB6C5",border:"#58708F",highlight:"#F7C948",accent:"#38BDF8",success:"#2EE59D",warning:"#F7C948",error:"#FF5A5F",grid:"#263449"},C:{background:"#02060A",panelBackground:"#071018",primaryText:"#BFFFE0",secondaryText:"#6FAF93",border:"#123B33",highlight:"#39FF88",accent:"#2DE2E6",success:"#39FF88",warning:"#FFCC66",error:"#FF3B3B",grid:"#0E2A24"}},w=window.__AGOMTUI_RUNTIME__||{},ze=String(w.apiBase||"/api/tui").replace(/\/+$/,""),K=typeof _.createRuntimeUrls=="function"?_.createRuntimeUrls(w):null,C=typeof _.runtimeHooks=="function"?_.runtimeHooks(w):w.hooks||{},Ar=w.allowSvgDataImages!==!1,ne=new Map;function Ue(e){try{return window[e]||null}catch{return null}}function O(e,t,n=null){try{return Ue(e)?.getItem(t)??n}catch{return n}}function z(e,t,n){try{Ue(e)?.setItem(t,n)}catch{}}function Ve(e,t){try{Ue(e)?.removeItem(t)}catch{}}function L(e){const t=String(c.app?.dataset.userKey||"anonymous").trim().replace(/[^a-zA-Z0-9_-]+/g,"_");return`${e}:user:${t||"anonymous"}`}function It(){try{return new URL(window.location.href).searchParams.get("screen")?.trim()||""}catch{return""}}function Me(){try{return new URL(window.location.href).searchParams.get("action")?.trim()||""}catch{return""}}function Kt(){try{const e={};return new URL(window.location.href).searchParams.forEach((t,n)=>{["screen","action"].includes(n)||(e[n]=t)}),e}catch{return{}}}function Dt(e,t={}){const n=String(e||"").trim();if(!n||!window.history?.pushState)return;const r=new URL(window.location.href);if(r.searchParams.get("screen")===n&&(t.preserveAction||!r.searchParams.has("action")))return;r.searchParams.set("screen",n),t.preserveAction||r.searchParams.delete("action");const a=t.replace?"replaceState":"pushState";window.history[a]({screenKey:n},"",r)}const We=new Set(["datagrid","detail","message","chart","image","line","bar","pie","kpi-trend","kpi_trend","table-chart","table_chart","host-slot","host_slot"]);function Nt(e,t){const n=String(e||"").trim();return!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(n)||typeof t!="function"?!1:(ne.set(n,t),!0)}const jt=window.AgomTUIRenderers||{};window.AgomTUIRenderers={register:Nt,get(e){return ne.get(String(e||"").trim())||null},has(e){return ne.has(String(e||"").trim())}},Array.isArray(jt.pending)&&jt.pending.forEach(e=>{Array.isArray(e)&&Nt(e[0],e[1])});function xr(){return K?K.catalog():`${ze}/catalog/`}function Cr(e){return K?K.screen(e):`${ze}/screens/${encodeURIComponent(e)}/`}function Ge(e){return K?K.action(e):`${ze}/actions/${encodeURIComponent(e)}/run/`}function Lr(e=""){return K?K.bootstrap(e):""}function Tr(){return String(w.host?.operatorHomeUrl||"")}function Pr(e=""){const t=String(w.host?.governanceQueueUrl||"");if(!t)return"";const n=e?`?domain=${encodeURIComponent(e)}`:"";return`${t}${n}`}function A(e){return typeof C.isOperatorHomeScreen=="function"?!!C.isOperatorHomeScreen(e):!1}function Ot(e){return(w.host?.homeActionKeys||[]).includes(String(e||""))}function Rr(e){const t=String(e?.action_key||"").trim(),n=String(w.host?.homePanelActionPrefix||"");return!n||!t.startsWith(n)||Ot(t)?"":t.slice(n.length)}function i(e){return String(e??"").replace(/[&<>"']/g,t=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[t])}function Je(e){return(e||[]).reduce((t,n)=>{const r=String(n?.severity||"").trim().toLowerCase();return r==="blocked"?t.blockedCount+=1:r==="warning"&&(t.warningCount+=1),t},{blockedCount:0,warningCount:0})}function Fr(e){return(e||[]).reduce((t,n)=>(t.blockedCount+=Number(n?.blockedCount||0),t.warningCount+=Number(n?.warningCount||0),t),{blockedCount:0,warningCount:0})}function zt(e){return Fr((e||[]).map(t=>o.screenBadges[t]||{}))}function Ut(e){return Number(e?.blockedCount||0)>0||Number(e?.warningCount||0)>0}function re(e,t={}){if(!Ut(e))return"";const n=Number(e?.blockedCount||0),r=Number(e?.warningCount||0),a=n>0?"blocked":"warning",s=n>0?n:r,l=n>0?"\u963B\u65AD":"\u9884\u8B66",u=t.compact?" tui-badge--compact":"";return`<span class="tui-badge tui-badge--${i(a)}${u}" aria-label="${i(l)} ${s}">${i(s)}</span>`}function Vt(e){return e==="blocked"?0:e==="warning"?1:2}function Er(e){return(e||[]).reduce((t,n)=>{const r=String(n?.severity||"").trim().toLowerCase(),a=String(n?.target_screen||"").trim(),s=String(n?.target_action_key||"").trim();if(!["blocked","warning"].includes(r)||!a||!s)return t;const l={screenKey:a,actionKey:s,severity:r,title:String(n?.title||"").trim(),nextAction:String(n?.next_action||"").trim()},u=t[a];return(!u||Vt(r)<Vt(u.severity))&&(t[a]=l),t},{})}function Mt(e){return o.screenBadgeDrilldowns[String(e||"").trim()]||null}function Wt(e){return e?c.actions.querySelector(`[data-action-ui-key="${CSS.escape(U(e))}"]`):null}function Gt(e){const t=o.screenBadges[e];if(!Ut(t))return"";const n=Mt(e),r=re(t,{compact:!0});if(!n?.actionKey)return r;const a=n.title||n.nextAction||"\u67E5\u770B\u6CBB\u7406\u6458\u8981";return`
            <button
                class="tui-badge-button"
                type="button"
                data-badge-screen-key="${i(e)}"
                title="${i(a)}"
                aria-label="${i(a)}"
            >${r}</button>
        `}async function qr(e){const t=String(e||"").trim();if(!t)return null;const n=Mt(t);if(!n?.actionKey)return S(t);const r=await S(t,{suppressAutoAction:!0});if(!r)return r;const a=v(n.actionKey);return a&&await $(a.key,Wt(a)),r}function Br(e){const t=document.cookie?document.cookie.split(";"):[];for(const n of t){const[r,...a]=n.trim().split("=");if(r===e)return decodeURIComponent(a.join("="))}return""}function m(e){c.status&&(c.status.textContent=e)}function Qe(e){return $e.includes(e)?e:"B"}function Hr(e){const t=String(e||"").replace("#","");return/^[0-9a-f]{6}$/i.test(t)?{r:Number.parseInt(t.slice(0,2),16),g:Number.parseInt(t.slice(2,4),16),b:Number.parseInt(t.slice(4,6),16)}:null}function Jt(e,t){const n=Hr(e);return n?`rgba(${n.r}, ${n.g}, ${n.b}, ${t})`:`rgba(0, 0, 0, ${t})`}function ve(e,t){const n=encodeURIComponent(String(t||"#ffffff"));return`url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='17' height='17' viewBox='0 0 17 17'%3E%3Cpath d='${{up:"M8 4 L3 11 H13 Z",down:"M3 6 H13 L8 13 Z",left:"M4 8 L11 3 V13 Z",right:"M6 3 L13 8 L6 13 Z"}[e]}' fill='${n}'/%3E%3C/svg%3E")`}function Qt(e,t={}){const n=Qe(e),r=_r[n],a=document.documentElement,s={"--tui-bg":r.background,"--tui-bg-deep":r.background,"--tui-panel":r.panelBackground,"--tui-panel-strong":r.border,"--tui-border":r.border,"--tui-border-dim":r.grid,"--tui-text":r.primaryText,"--tui-muted":r.secondaryText,"--tui-inverse":r.background,"--tui-command":r.background,"--tui-accent":r.highlight,"--tui-accent-strong":r.accent,"--tui-warn":r.warning,"--tui-danger":r.error,"--tui-green":r.success,"--tui-scroll-face":r.border,"--tui-scroll-light":r.primaryText,"--tui-scroll-track":r.grid,"--tui-scroll-shadow":r.background,"--tui-scroll-dark":r.background,"--tui-menubar-bg":r.grid,"--tui-menubar-text":r.primaryText,"--tui-footer-bg":r.grid,"--tui-footer-text":r.primaryText,"--tui-footer-divider":r.border,"--tui-footer-hotkey":r.highlight,"--tui-footer-emphasis":r.warning,"--tui-system-source-accent":r.accent,"--tui-grid-strong":Jt(r.primaryText,.66),"--tui-overlay":Jt(r.background,.82),"--tui-scroll-arrow-up":ve("up",r.primaryText),"--tui-scroll-arrow-down":ve("down",r.primaryText),"--tui-scroll-arrow-left":ve("left",r.primaryText),"--tui-scroll-arrow-right":ve("right",r.primaryText)};return Object.entries(s).forEach(([l,u])=>{a.style.setProperty(l,u)}),a.dataset.tuiTheme=n,o.themeKey=n,c.themeStatus&&(c.themeStatus.textContent=`STYLE: ${n}`),c.themeIndicatorCode&&(c.themeIndicatorCode.textContent=`T:${n}`),t.silent||z("localStorage",Ft,n),n}function Ir(){return Qe(O("localStorage",Ft,"B"))}function Kr(){const e=$e.indexOf(Qe(o.themeKey)),t=$e[(e+1)%$e.length];Qt(t),m(`\u4E3B\u9898\u5DF2\u5207\u6362: ${t}`)}function ae(e){return String(e).padStart(2,"0")}function Yt(){const e=new Date;return[e.getFullYear(),ae(e.getMonth()+1),ae(e.getDate())].join("-")+" "+[ae(e.getHours()),ae(e.getMinutes()),ae(e.getSeconds())].join(":")}function Ye(){c.lastRefresh&&(c.lastRefresh.textContent=Yt())}function Zt(e){if(!c.currentLocation)return;const t=o.screen?.screen||{},n=o.screen?.module||{},r=t.key||"boot",a=e?.key?`screen:${r} action:${e.key}`:`screen:${r}`,s=[n.label,t.label,e?.label].filter(Boolean).join(" / ");c.currentLocation.value!==a&&(c.currentLocation.value=a),c.currentLocation.dataset.currentAddress=a,c.currentLocation.title=s?`${s} | ${a}`:a}function Dr(e){const t=String(e||"").trim();if(!t)return"";const n=t.match(/^screen:([^\s]+)(?:\s+action:.+)?$/i);return n?n[1]:/^[a-z0-9][a-z0-9._-]*$/i.test(t)?t:""}function Ze(){c.currentLocation&&(c.currentLocation.value=c.currentLocation.dataset.currentAddress||`screen:${o.screen?.screen?.key||"boot"}`)}function Nr(){if(!c.currentLocation)return;const e=Dr(c.currentLocation.value);if(!e){Ze(),m("\u4F4D\u7F6E\u683C\u5F0F\u65E0\u6548");return}c.currentLocation.blur(),S(e)}function jr(){try{const e=O("sessionStorage",L(Rt));if(!e)return;const t=JSON.parse(e);Object.entries(t||{}).forEach(([n,r])=>{Array.isArray(r)&&(o.completedActionsByScreen[n]=new Set(r.filter(Boolean)))})}catch{o.completedActionsByScreen={}}}function Or(){try{o.lastNonHomeScreen=String(O("localStorage",L(je),"")).trim();const e=String(O("localStorage",L(Bt),"decision")).trim();o.preferredHomeLane=e==="governance"?"governance":"decision";const t=O("localStorage",L(qt)),n=t?JSON.parse(t):[];o.pinnedScreenKeys=new Set(Array.isArray(n)?n.map(r=>String(r||"").trim()).filter(Boolean):[])}catch{o.lastNonHomeScreen="",o.preferredHomeLane="decision",o.pinnedScreenKeys=new Set}}function Xt(){try{const e={};Object.entries(o.completedActionsByScreen||{}).forEach(([t,n])=>{n&&n.size&&(e[t]=Array.from(n))}),z("sessionStorage",L(Rt),JSON.stringify(e))}catch{}}function zr(e){const t=String(e||"").trim();o.lastNonHomeScreen=t,t?z("localStorage",L(je),t):Ve("localStorage",L(je))}function en(e){o.preferredHomeLane=e==="governance"?"governance":"decision",z("localStorage",L(Bt),o.preferredHomeLane)}function Ur(){z("localStorage",L(qt),JSON.stringify(Array.from(o.pinnedScreenKeys)))}function tn(){return O("sessionStorage",L(ke))==="1"}function nn(){Ve("sessionStorage",L(ke))}function Vr(){o.screen?.screen?.key&&!A(o.screen.screen.key)?z("sessionStorage",L(ke),"1"):Ve("sessionStorage",L(ke))}function Mr(){window.open("/terminal/","_blank","noopener,noreferrer"),m("CLI \u5DF2\u5728\u65B0\u6807\u7B7E\u9875\u6253\u5F00")}function Wr(){const e=String(o.lastNonHomeScreen||"").trim();return e?(S(e),!0):(m("\u6CA1\u6709\u53EF\u6062\u590D\u7684\u6700\u8FD1\u5DE5\u4F5C\u533A"),!1)}function oe(e){const t=String(e||"").trim();return typeof C.runHomeAction=="function"?!!C.runHomeAction(t,{loadScreen:S,openCliSurface:Mr,persistPreferredLane:en,restoreLastWorkspace:Wr}):!1}function rn(e){return typeof C.inferHomeLane=="function"?String(C.inferHomeLane(e)||""):""}function Gr(e){const t={};return(e||[]).forEach(n=>{const r=String(n?.severity||"").trim().toLowerCase();if(!["blocked","warning"].includes(r))return;const a=String(n?.target_screen||"").trim();a&&(t[a]||(t[a]={blockedCount:0,warningCount:0}),r==="blocked"?t[a].blockedCount+=1:t[a].warningCount+=1)}),t}function an(){!A(o.screen?.screen?.key)||!c.main||c.main.querySelectorAll("[data-dashboard-panel]").forEach(e=>{const t=e.dataset.dashboardPanel,n=o.homePanelBadges[t],r=e.querySelector("[data-panel-badge]");r&&(r.innerHTML=re(n,{compact:!0}))})}function on(e){const t=e?.counts_by_screen||{};o.screenBadges=Object.fromEntries(Object.entries(t).map(([n,r])=>[n,{blockedCount:Number(r?.blocked_count||0),warningCount:Number(r?.warning_count||0)}])),o.catalog&&ot(),an()}async function sn(){if(o.operatorHomePayload)return o.operatorHomePayload;if(!o.operatorHomePromise){const e=Tr();if(!e)return null;o.operatorHomePromise=R(e).then(t=>(o.operatorHomePayload=t,on(t?.navigation_badges),t)).finally(()=>{o.operatorHomePromise=null})}return o.operatorHomePromise}async function se(){try{if(typeof C.loadNavigationBadges=="function"){const t=await C.loadNavigationBadges({fetchJson:R,screen:o.screen});if(t){on(t);return}}if(A(o.screen?.screen?.key)){await sn();return}}catch{return}const e=Pr();if(e)try{const t=await R(e);o.screenBadges=Gr(t.items||[]),o.screenBadgeDrilldowns=Er(t.items||[]),o.catalog&&ot(),an()}catch{o.screenBadges={},o.screenBadgeDrilldowns={},o.catalog&&ot()}}function Xe(){return c.inspectorShell?.closest?.(".tui-workspace-grid")||null}function _e(){const e=Xe();if(!e||window.matchMedia?.(`(max-width: ${hr}px)`)?.matches)return null;const t=e.getBoundingClientRect().width||window.innerWidth,n=Math.max(Oe,Math.min(Ht,Math.round(t*br)));return{min:Oe,max:n}}function Jr(e){const t=_e();return t?Math.round(Math.min(t.max,Math.max(t.min,Number(e)||t.min))):null}function ie(e,t={}){const n=Xe(),r=Jr(e);if(!n||!r)return null;if(o.inspectorWidth=r,n.style.setProperty("--tui-inspector-user-width",`${r}px`),c.inspectorResizeHandle){const a=_e();c.inspectorResizeHandle.setAttribute("aria-valuemin",String(a?.min||Oe)),c.inspectorResizeHandle.setAttribute("aria-valuemax",String(a?.max||Ht)),c.inspectorResizeHandle.setAttribute("aria-valuenow",String(r))}return t.persist&&z("localStorage",Et,String(r)),r}function Qr(){const e=O("localStorage",Et);if(e==null)return;const t=Number(e);Number.isFinite(t)&&ie(t)}function ps(e){return{read:"\u7ACB\u5373\u6253\u5F00",ai:"AI \u534F\u52A9",write:"\u63D0\u4EA4\u786E\u8BA4",unsafe:"\u53D7\u9650\u5DE5\u5177",admin:"\u7BA1\u7406\u5DE5\u5177"}[String(e||"").toLowerCase()]||"\u4EFB\u52A1"}function ce(e){const t=String(e.risk||"read").toLowerCase(),n=String(e.effect||"").toLowerCase(),r=String(e.intent||"").toLowerCase(),a=String(e.label||"").toLowerCase(),s={create:"\u521B\u5EFA\u8BB0\u5F55",update:"\u4FDD\u5B58\u4FEE\u6539",toggle:"\u5207\u6362\u72B6\u6001",delete:"\u5220\u9664\u6216\u64A4\u9500",execute:t==="ai"?"\u53D1\u8D77\u95EE\u7B54":"\u6267\u884C\u4EFB\u52A1"};return s[n]?s[n]:t==="ai"?"\u53D1\u8D77\u95EE\u7B54":(e.fields||[]).some(l=>l.input_type!=="hidden")?"\u6309\u6761\u4EF6\u67E5\u8BE2":r.includes("health")||r.includes("status")||a.includes("\u68C0\u67E5")?"\u8FD0\u884C\u68C0\u67E5":e.view_type==="datagrid"?"\u6253\u5F00\u6E05\u5355":e.view_type==="detail"||e.view_type==="status"?"\u67E5\u770B\u8BE6\u60C5":"\u751F\u6210\u89C6\u56FE"}function cn(e){const t=k(e),n=String(e.risk||"read").toLowerCase();return t==="operation"?n==="ai"?"AI \u64CD\u4F5C":n==="write"?"\u53EF\u6267\u884C\u64CD\u4F5C":n==="admin"?"\u7BA1\u7406\u64CD\u4F5C":"\u64CD\u4F5C":t==="primary"?"\u4E3B\u6D41\u7A0B":t==="advanced"?"\u6761\u4EF6\u67E5\u8BE2":"\u652F\u6491\u68C0\u67E5"}function ln(e,t){const n=[];t&&n.push("\u5DF2\u5B8C\u6210"),n.push(cn(e)),n.push(ce(e));const r=(e.fields||[]).filter(a=>a.input_type!=="hidden").length;return r&&n.push(`${r} \u9879\u53C2\u6570`),e.confirmation_required&&n.push("\u6267\u884C\u524D\u786E\u8BA4"),n.join(" / ")}function un(e){return{status:"\u72B6\u6001",detail:"\u8BE6\u60C5",datagrid:"\u8868\u683C",message:"\u8BF4\u660E",queue_workbench:"\u961F\u5217",auto:"\u81EA\u52A8"}[String(e||"").toLowerCase()]||"\u5DE5\u4F5C\u533A"}function x(e){return String(e??"").replace(/自动批准的只读/g,"\u5DF2\u53D1\u5E03\u7684").replace(/只读详情工具/g,"\u8BE6\u60C5\u5DE5\u5177").replace(/只读/g,"\u53EF\u67E5\u770B").replace(/读取业务视图/g,"\u6253\u5F00\u4E1A\u52A1\u89C6\u56FE").replace(/直接读取/g,"\u76F4\u63A5\u6253\u5F00")}function q(e){if(e==null||e==="")return"-";if(typeof e=="object")try{return JSON.stringify(e,null,2)}catch{return"\u7ED3\u6784\u5316\u6570\u636E"}return String(e)}function Yr(e){const t={account_id:"\u8D26\u6237ID",asset_code:"\u6807\u7684\u4EE3\u7801",asset_codes:"\u8D44\u4EA7\u4EE3\u7801",fund_code:"\u57FA\u91D1\u4EE3\u7801",id:"ID",pk:"\u8BB0\u5F55ID",portfolio_id:"\u7EC4\u5408ID",provider_id:"\u6570\u636E\u6E90ID",risk_level:"\u98CE\u9669\u7B49\u7EA7",short_code:"\u77ED\u7801",task_id:"\u4EFB\u52A1ID"},n=String(e||"");return t[n]?t[n]:n.replace(/[_-]+/g," ").replace(/\b\w/g,r=>r.toUpperCase()).replace(/\bId\b/g,"ID").replace(/\bPct\b/g,"\u6BD4\u4F8B").replace(/\bAt\b/g,"\u65F6\u95F4")}function Zr(e){return o.currentColumns.find(n=>n.key===e)?.label||Yr(e)}function dn(e,t=1/0){if(!e)return[];const n=[];return o.currentColumns.forEach(r=>{Object.prototype.hasOwnProperty.call(e,r.key)&&n.push(r.key)}),Object.keys(e).forEach(r=>{r.startsWith("__")||n.includes(r)||n.push(r)}),n.slice(0,t).map(r=>[Zr(r),q(e[r])])}function U(e){return e.ui_key||e.key}function v(e){return(o.screen&&o.screen.actions||[]).find(t=>t.key===e||U(t)===e)||null}function Ae(e){return e?.dataset?.actionUiKey||e?.dataset?.actionKey||""}function xe(e){const t=Ae(e);if(!t){m("\u4EFB\u52A1\u672A\u627E\u5230");return}const n=Date.now();if(o.lastFormTriggerRef===t&&n-o.lastFormTriggerAt<wr)return;o.lastFormTriggerRef=t,o.lastFormTriggerAt=n;const r={},a=String(e?.dataset?.dashboardResultPanelKey||"").trim(),s=String(e?.dataset?.dashboardRefreshPanelKey||"").trim(),l=String(e?.dataset?.dashboardPanelKey||"").trim();a&&(r.dashboardResultPanelKey=a),s&&(r.dashboardRefreshPanelKey=s),l&&(r.dashboardPanelKey=l),$(t,e,r)}async function R(e,t){const n=t||{},r=(n.method||"GET").toUpperCase(),a={Accept:"application/json",...n.headers||{}};r!=="GET"&&(a["Content-Type"]="application/json",a["X-CSRFToken"]=Br("csrftoken"));const s=await fetch(e,{credentials:"same-origin",...n,headers:a}),l=s.headers.get("content-type")||"";if(!s.ok){let u=null;if(l.includes("application/json"))try{u=await s.json()}catch{u=null}const d=new Error("\u4E1A\u52A1\u8BF7\u6C42\u672A\u5B8C\u6210");throw d.status=s.status,d.payload=u,d}if(!l.includes("application/json"))throw new Error("\u4E1A\u52A1\u6570\u636E\u683C\u5F0F\u4E0D\u53EF\u6E32\u67D3");return s.json()}function pn(e){const t=Number(e?.status||0),n=e?.payload&&typeof e.payload=="object"?e.payload:{},r=String(n.error_code||"").startsWith("tui_"),s={403:["\u65E0\u6743\u8BBF\u95EE","\u5F53\u524D\u8D26\u53F7\u4E0D\u80FD\u5B8C\u6210\u8FD9\u9879\u64CD\u4F5C\u3002"],404:["\u5185\u5BB9\u4E0D\u5B58\u5728","\u76EE\u6807\u5185\u5BB9\u6CA1\u6709\u53D1\u5E03\uFF0C\u6216\u5DF2\u88AB\u79FB\u9664\u3002"],502:["\u670D\u52A1\u6682\u65F6\u4E0D\u53EF\u7528","\u670D\u52A1\u6682\u65F6\u65E0\u6CD5\u5B8C\u6210\u8BF7\u6C42\uFF0C\u8BF7\u7A0D\u540E\u91CD\u8BD5\u3002"],503:["\u670D\u52A1\u6B63\u5728\u6062\u590D","\u670D\u52A1\u5C1A\u672A\u5C31\u7EEA\uFF0C\u8BF7\u7A0D\u540E\u91CD\u8BD5\u3002"]}[t]||["\u6682\u65F6\u65E0\u6CD5\u5B8C\u6210\u8BF7\u6C42","\u8BF7\u7A0D\u540E\u91CD\u8BD5\uFF0C\u6216\u8FD4\u56DE\u53EF\u7528\u5DE5\u4F5C\u533A\u3002"],l=r&&Array.isArray(n.recovery_actions)?n.recovery_actions.filter(u=>u&&typeof u=="object"&&u.screen_key).map(u=>({label:String(u.label||"\u524D\u5F80\u53EF\u7528\u5DE5\u4F5C\u533A"),screenKey:String(u.screen_key)})):[];return{title:r?String(n.title||s[0]):s[0],detail:r?String(n.detail||s[1]):s[1],traceId:r?String(n.trace_id||""):"",recoveryActions:l}}function et(e,t){const n=pn(t),r=String(e?.error_message||n.detail);return`
            <div class="tui-panel-error" role="status">
                <strong>${i(n.title)}</strong>
                <p>${i(r)}</p>
                ${n.traceId?`<small>\u8FFD\u8E2A\u7F16\u53F7\uFF1A${i(n.traceId)}</small>`:""}
                <div class="tui-panel-error-actions">
                    <button class="tui-panel-retry" type="button" data-panel-retry>\u91CD\u8BD5</button>
                    ${n.recoveryActions.map(a=>`
                        <button
                            class="tui-panel-recovery"
                            type="button"
                            data-panel-recovery-screen="${i(a.screenKey)}"
                        >${i(a.label)}</button>
                    `).join("")}
                </div>
                ${e.note?`<small>${i(e.note)}</small>`:""}
            </div>
        `}function tt(e,t){e.querySelector("[data-panel-retry]")?.addEventListener("click",()=>fe(t)),e.querySelectorAll("[data-panel-recovery-screen]").forEach(n=>{n.addEventListener("click",()=>S(n.dataset.panelRecoveryScreen))})}function le(e,t={}){w.debug===!0&&window.console?.error&&window.console.error("TUI request failed",e);const n=pn(e);c.mainTitle.textContent=n.title,c.main.innerHTML=`
            <section class="tui-application-error" role="alert">
                <strong>${i(n.title)}</strong>
                <p>${i(n.detail)}</p>
                ${n.traceId?`<small>\u8FFD\u8E2A\u7F16\u53F7\uFF1A${i(n.traceId)}</small>`:""}
                <div class="tui-panel-error-actions">
                    <button class="tui-panel-retry" type="button" data-application-retry>\u91CD\u8BD5</button>
                    ${n.recoveryActions.map(r=>`
                        <button
                            class="tui-panel-recovery"
                            type="button"
                            data-panel-recovery-screen="${i(r.screenKey)}"
                        >${i(r.label)}</button>
                    `).join("")}
                </div>
            </section>
        `,c.main.querySelector("[data-application-retry]")?.addEventListener("click",()=>{const r=String(t.retryScreenKey||o.screen?.screen?.key||o.catalog?.default_screen||"home");S(r)}),c.main.querySelectorAll("[data-panel-recovery-screen]").forEach(r=>{r.addEventListener("click",()=>S(r.dataset.panelRecoveryScreen))}),m("\u8BF7\u6C42\u672A\u5B8C\u6210")}let nt=0;function D(e={}){const{abort:t=!1}=e;if(o.slowActionTimer&&(window.clearTimeout(o.slowActionTimer),o.slowActionTimer=null),t&&o.pendingController)try{o.pendingController.abort()}catch{}o.pendingController=null,o.pendingRequestId=0}function fn(e){return D({abort:!0}),nt+=1,o.pendingRequestId=nt,o.latestRequestId=nt,o.pendingController=e,o.pendingRequestId}function J(e){return e===o.latestRequestId}function rt(e,t,n={}){const r=n.waitingCopy||"\u6B63\u5728\u8BFB\u53D6\u4E1A\u52A1\u6570\u636E...";c.main.innerHTML=`
            <section class="tui-entry-state">
                <div class="tui-view-status">\u52A0\u8F7D\u4E2D / ${i(e.label||"\u9ED8\u8BA4\u4EFB\u52A1")}</div>
                <div class="tui-entry-copy">
                    <strong>${i(r)}</strong>
                    <p>${i(t?.screen?.summary||"\u7CFB\u7EDF\u6B63\u5728\u51C6\u5907\u9ED8\u8BA4\u7ED3\u679C\u3002")}</p>
                </div>
            </section>
        `,m("\u8BFB\u53D6\u6570\u636E")}function mn(e,t){new Set(w.host?.slowActionKeys||[]).has(t.key)&&(o.slowActionTimer=window.setTimeout(()=>{o.pendingRequestId===e&&Xr(t)},$r))}function Xr(e){const t=(w.host?.slowActionScreens||[]).filter(n=>n?.key&&n?.label).map(n=>`<button type="button" data-slow-screen="${i(n.key)}">${i(n.label)}</button>`).join("");c.main.innerHTML=`
            <section class="tui-entry-state">
                <div class="tui-view-status">\u54CD\u5E94\u8F83\u6162 / ${i(e.label||"")}</div>
                <div class="tui-entry-copy">
                    <strong>\u5F53\u524D\u54CD\u5E94\u8F83\u6162\uFF0C\u53EF\u7EE7\u7EED\u7B49\u5F85\u3001\u91CD\u8BD5\u6216\u53D6\u6D88\u3002</strong>
                    <p>\u5F53\u524D\u8BF7\u6C42\u4ECD\u5728\u6267\u884C\u4E2D\uFF0C\u4E5F\u53EF\u4EE5\u5207\u6362\u5230\u5BBF\u4E3B\u63D0\u4F9B\u7684\u5176\u4ED6\u5165\u53E3\u3002</p>
                </div>
                <div class="tui-entry-actions">
                    <button type="button" data-slow-command="wait">\u7EE7\u7EED\u7B49\u5F85</button>
                    <button type="button" data-slow-command="retry">\u91CD\u8BD5</button>
                    ${t}
                    <button type="button" data-slow-command="cancel">\u53D6\u6D88\u672C\u6B21\u8BF7\u6C42</button>
                </div>
            </section>
        `,c.main.querySelectorAll("[data-slow-command]").forEach(n=>{n.addEventListener("click",()=>{const r=n.dataset.slowCommand;r==="wait"?(rt(e,o.screen,{waitingCopy:"\u7EE7\u7EED\u7B49\u5F85\u8FDC\u7AEF\u54CD\u5E94..."}),mn(o.pendingRequestId,e)):r==="retry"?(D({abort:!0}),$(e.key,null,{params:{...o.lastParams}})):r==="cancel"&&(D({abort:!0}),c.main.innerHTML=T("\u5DF2\u53D6\u6D88\u5F53\u524D\u8BF7\u6C42\u3002",["\u4F60\u53EF\u4EE5\u91CD\u8BD5\uFF0C\u6216\u5207\u6362\u5230\u5176\u4ED6\u5165\u53E3\u7EE7\u7EED\u3002"]),m("\u5DF2\u53D6\u6D88"))})}),c.main.querySelectorAll("[data-slow-screen]").forEach(n=>{n.addEventListener("click",()=>{D({abort:!0}),S(n.dataset.slowScreen)})}),m("\u54CD\u5E94\u8F83\u6162")}function ea(e){const t=v(e);if(!t){m("\u9ED8\u8BA4\u4EFB\u52A1\u672A\u627E\u5230");return}const n=c.actions.querySelector(`[data-action-ui-key="${CSS.escape(U(t))}"]`);n?.scrollIntoView({block:"nearest"}),n?.querySelector("input:not([type='hidden']),select,textarea,button")?.focus(),m(`\u5DF2\u5B9A\u4F4D\u5230 ${t.label}`)}function at(e){o.catalog=e;const t=e.groups||[];let n=0;const r=document.activeElement?.closest?.("[data-screen-key]")?.dataset?.screenKey||"",a=c.moduleTree.scrollTop;c.moduleTree.innerHTML=t.map(s=>`
            <section class="tui-group">
                <div class="tui-group-title">${i(s.label)}</div>
                ${(s.modules||[]).map(l=>`
                    <div class="tui-tree-module">
                        ${ta(s,l)?"":`
                            <div class="tui-tree-module-title">
                                <span>${i(l.label)}</span>
                                <div class="tui-tree-module-meta">
                                    <span data-module-badge-screens="${i((l.screens||[]).map(u=>u.key).join(","))}">${re(zt((l.screens||[]).map(u=>u.key)),{compact:!0})}</span>
                                    <small>${i(l.action_count||0)}</small>
                                </div>
                            </div>
                        `}
                        ${(l.screens||[]).map(u=>`
                            <div class="tui-screen-row">
                                <button class="tui-screen-button" type="button" data-screen-key="${i(u.key)}">
                                    <span>${++n} ${i(u.label)}</span>
                                    <small>${i(un(u.view_type))} / ${i(u.action_count)} \u9879</small>
                                </button>
                                <div class="tui-screen-tools">
                                    <span data-screen-badge-host="${i(u.key)}">${Gt(u.key)}</span>
                                    <button
                                        class="tui-screen-pin${o.pinnedScreenKeys.has(u.key)?" is-active":""}"
                                        type="button"
                                        data-pin-screen-key="${i(u.key)}"
                                        aria-label="${i(`${o.pinnedScreenKeys.has(u.key)?"\u53D6\u6D88\u6536\u85CF\u5DE5\u4F5C\u533A":"\u6536\u85CF\u5DE5\u4F5C\u533A"}\uFF1A${u.label}`)}"
                                        title="${i(`${o.pinnedScreenKeys.has(u.key)?"\u53D6\u6D88\u6536\u85CF\u5DE5\u4F5C\u533A":"\u6536\u85CF\u5DE5\u4F5C\u533A"}\uFF1A${u.label}`)}"
                                        aria-pressed="${o.pinnedScreenKeys.has(u.key)?"true":"false"}"
                                    >${o.pinnedScreenKeys.has(u.key)?"\u2605":"\u2606"}</button>
                                </div>
                            </div>
                        `).join("")}
                    </div>
                `).join("")}
            </section>
        `).join(""),c.moduleTree.querySelectorAll("[data-screen-key]").forEach(s=>{s.addEventListener("click",()=>S(s.dataset.screenKey))}),gn(),c.moduleTree.querySelectorAll("[data-pin-screen-key]").forEach(s=>{s.addEventListener("click",l=>{l.preventDefault(),l.stopPropagation();const u=String(s.dataset.pinScreenKey||"").trim();u&&(o.pinnedScreenKeys.has(u)?o.pinnedScreenKeys.delete(u):o.pinnedScreenKeys.add(u),Ur(),at(o.catalog))})}),c.moduleTree.scrollTop=a,r&&c.moduleTree.querySelector(`[data-screen-key="${CSS.escape(r)}"]`)?.focus(),o.screen?.screen?.key&&hn(o.screen.screen.key)}function yn(e){const t=String(e||"").trim();if(!t)return"";for(const n of o.catalog?.groups||[])for(const r of n.modules||[]){const a=(r.screens||[]).find(s=>s.key===t);if(a)return String(a.label||"").trim()}return""}function ta(e,t){const n=Array.isArray(e?.modules)?e.modules:[],r=String(e?.label||"").trim().toLocaleLowerCase(),a=String(t?.label||"").trim().toLocaleLowerCase();return n.length===1&&r!==""&&r===a}function gn(){c.moduleTree.querySelectorAll("[data-badge-screen-key]").forEach(e=>{e.dataset.badgeBound!=="true"&&(e.dataset.badgeBound="true",e.addEventListener("click",t=>{t.preventDefault(),t.stopPropagation(),qr(e.dataset.badgeScreenKey)}))})}function ot(){!o.catalog||!c.moduleTree||(c.moduleTree.querySelectorAll("[data-screen-badge-host]").forEach(e=>{e.innerHTML=Gt(e.dataset.screenBadgeHost)}),c.moduleTree.querySelectorAll("[data-module-badge-screens]").forEach(e=>{const t=zt(String(e.dataset.moduleBadgeScreens||"").split(",").filter(Boolean));e.innerHTML=re(t,{compact:!0})}),gn())}function hn(e){let t=null;c.moduleTree.querySelectorAll("[data-screen-key]").forEach(n=>{const r=n.dataset.screenKey===e;n.classList.toggle("is-active",r),r&&(t=n)}),bn(t)}function bn(e){!e||o.railCollapsed||window.requestAnimationFrame(()=>{const t=c.moduleTree.getBoundingClientRect(),n=e.getBoundingClientRect();n.top>=t.top&&n.bottom<=t.bottom||e.scrollIntoView({block:"nearest",inline:"nearest"})})}function wn(e,t){const n=`tui-${e.key}-${t.key}`,r=t.default??"",a=String(t.value_type||"").toLowerCase(),s=["json","object","list"].includes(a)||r!==null&&typeof r=="object",l=s?typeof r=="string"?r:JSON.stringify(r,null,2):r,u=t.required?"required":"";if(t.input_type==="hidden")return`<input id="${i(n)}" name="${i(t.key)}" type="hidden" value="${i(l)}">`;if(t.input_type==="select"){const d=t.options||[],f=!t.required&&l===""?'<option value=""></option>':"";return`
                <label class="tui-field" for="${i(n)}">
                    <span>${i(t.label)}</span>
                    <select id="${i(n)}" name="${i(t.key)}" ${u}>
                        ${f}${d.map(p=>{const y=typeof p=="string"?p:p.value,g=typeof p=="string"?p:p.label;return`<option value="${i(y)}" ${String(y)===String(l)?"selected":""}>${i(g)}</option>`}).join("")}
                    </select>
                </label>
            `}if(t.input_type==="checkbox"){const d=l===!0||String(l).toLowerCase()==="true"||String(l)==="1";return`
                <label class="tui-field tui-field-checkbox" for="${i(n)}">
                    <input id="${i(n)}" name="${i(t.key)}" type="checkbox" value="true" ${d?"checked":""}>
                    <span>${i(t.label)}</span>
                </label>
            `}return t.input_type==="textarea"||s?`
                <label class="tui-field" for="${i(n)}">
                    <span>${i(t.label)}</span>
                    <textarea id="${i(n)}" name="${i(t.key)}" rows="${s?"5":"3"}" ${u} placeholder="${i(t.placeholder||"")}">${i(l)}</textarea>
                </label>
            `:t.input_type==="file"?`
                <label class="tui-field tui-field-file" for="${i(n)}">
                    <span>${i(t.label)}</span>
                    <input id="${i(n)}" name="${i(t.key)}" type="file" ${u} accept="${i(t.accept||"")}">
                </label>
            `:`
            <label class="tui-field" for="${i(n)}">
                <span>${i(t.label)}</span>
                <input id="${i(n)}" name="${i(t.key)}" type="${i(t.input_type||"text")}" value="${i(l)}" ${u} placeholder="${i(t.placeholder||"")}">
            </label>
        `}function Sn(e,t,n){const r=String(e.value_type||e.input_type||"text").toLowerCase();if(e.input_type==="checkbox")return!!n;const a=String(t??"").trim();if(a==="")return"";if(r==="boolean")return["true","1","yes","on"].includes(a.toLowerCase())?!0:["false","0","no","off"].includes(a.toLowerCase())?!1:a;if(r==="integer"||r==="int"||e.input_type==="number"){const s=Number(a);return Number.isFinite(s)?s:a}if(r==="float"){const s=Number.parseFloat(a);return Number.isFinite(s)?s:a}if(r==="list"){if(a.startsWith("[")&&a.endsWith("]"))try{const s=JSON.parse(a);return Array.isArray(s)?s:a}catch{return a.split(",").map(l=>l.trim()).filter(Boolean)}return a.split(",").map(s=>s.trim()).filter(Boolean)}if(r==="json"||r==="object")try{return JSON.parse(a)}catch{return a}return a}function st(e={}){const t=!!e.preserveRowContext;o.currentViewModel=null,o.currentColumns=[],o.currentRows=[],o.visibleRows=[],o.lastPager=null,o.selectedRowIndex=0,t||(o.selectedRowContext=null),o.filterText="",c.filterInput&&(c.filterInput.value=""),xt()}function Ce(e){const t=c.main.closest(".tui-workspace-grid");if(t){if(!e){delete t.dataset.viewKind;return}t.dataset.viewKind=String(e)}}function kn(e,t={}){o.screen=e,o.lastRaw=null,o.lastPager=null,o.homePanelBadges={},st();const n=e.screen,r=rn(n);r&&en(r),A(n.key)||zr(n.key),Vr(),c.screenTitle.textContent=n.label.toUpperCase(),c.screenStatus.textContent=n.status.toUpperCase(),c.mainTitle.textContent=n.label.toUpperCase(),Zt(null),hn(n.key),sa(n.workflow||{});const a=_n(n)&&n.entry_state?.mode!=="parameter_gate",s=de(n);if(c.actions.closest(".tui-panel").hidden=s,c.inspector.closest(".tui-panel").hidden=s,c.main.closest(".tui-workspace-grid").classList.toggle("is-dashboard",a),Ce(a?"dashboard":"idle"),o.showSupportTasks=!1,o.showAdvancedQueries=!1,o.actionFilterText="",a&&!s&&Bn(e.actions||[],n),a){ca(e,{suppressAutoActions:Za(e,t.deepLinkedActionKey)}),we(null),N(),Ye(),m(s?"\u7CFB\u7EDF\u9996\u9875":"\u6982\u89C8\u5DF2\u52A0\u8F7D");return}Bn(e.actions||[],n);const l=ye(e.actions||[]),u=n.business_context||{},d=ue(n);te({title:n.label,body:$n(n),rows:[["\u4E3B\u4EFB\u52A1",d.primaryTask],["\u76EE\u6807\u7ED3\u679C",d.primaryOutcome],["\u5DE5\u4F5C\u533A",e.module.label],["\u89C6\u56FE",un(n.view_type)],["\u4E3B\u6D41\u7A0B",l.primary],["\u652F\u6491\u68C0\u67E5",l.support],["\u9AD8\u7EA7\u67E5\u8BE2",l.advanced],["\u53EF\u6267\u884C\u64CD\u4F5C",l.operation],["\u9700\u786E\u8BA4",l.write],["AI \u4EA4\u4E92",l.ai]],sections:[...vn(n),...ct(u),{title:"\u64CD\u4F5C\u63D0\u793A",body:[l.operation?"\u672C\u5DE5\u4F5C\u533A\u5305\u542B\u63D0\u4EA4\u6216 AI \u534F\u52A9\u52A8\u4F5C\uFF0C\u5DF2\u7F6E\u9876\u663E\u793A\uFF1B\u63D0\u4EA4\u524D\u4F1A\u6309\u7B56\u7565\u8981\u6C42\u786E\u8BA4\u3002":"\u672C\u5DE5\u4F5C\u533A\u5F53\u524D\u63D0\u4F9B\u6253\u5F00\u3001\u67E5\u8BE2\u548C\u68C0\u67E5\u4EFB\u52A1\uFF1B\u7ED3\u679C\u6309\u4E1A\u52A1\u89C6\u56FE\u5448\u73B0\uFF0C\u4E0D\u5C55\u793A\u5185\u90E8\u63A5\u53E3\u3002"],rows:[]}]}),we(null),N();const f=n.entry_state||{},p=na(e);if(f.mode==="parameter_gate"&&p)ra(e,p,f),m("\u7B49\u5F85\u9009\u62E9");else if(p&&!t.suppressAutoAction){const y=c.actions.querySelector(`[data-action-ui-key="${CSS.escape(U(p))}"]`);rt(p,e,{waitingCopy:f.empty_copy}),$(p.key,y)}else c.main.innerHTML=`<div class="tui-empty-state">${i(f.empty_copy||Le(n,n.summary))}<br>\u8BF7\u9009\u62E9\u5DE6\u4FA7\u4EFB\u52A1\u6216\u6309 F6 \u6267\u884C\u4E0B\u4E00\u4E3B\u6D41\u7A0B\u3002</div>`,m("\u5DE5\u4F5C\u533A\u5C31\u7EEA")}function na(e){const t=e.actions||[];if(!t.length)return null;const n=e.screen||{},r=n.entry_state||{};if(r.mode==="dashboard")return null;const s=t.find(u=>u.key===n.default_action_key)||t[0];return s?r.mode==="parameter_gate"?s:it(s).length?null:s:null}function it(e){return(e?.fields||[]).filter(t=>t.required&&t.input_type!=="hidden").filter(t=>t.default===void 0||t.default===null||t.default==="")}function ra(e,t,n){const r=String(n.field_key||""),a=(t.fields||[]).find(l=>l.key===r)||it(t)[0];if(!a){c.main.innerHTML=T(n.empty_copy||Le(e.screen,e.screen.summary),n.help_steps||["\u8BF7\u9009\u62E9\u5DE6\u4FA7\u4EFB\u52A1\u7EE7\u7EED\u3002"]);return}if(String(a.input_type||"").toLowerCase()==="select"&&Array.isArray(a.options)&&a.options.length){aa(e,t,n,a);return}oa(e,t,n,a)}function aa(e,t,n,r){const a=(r.options||[]).filter(l=>l&&typeof l=="object"?String(l.value??"").trim()!=="":String(l??"").trim()!==""),s=a.map((l,u)=>{const d=typeof l=="object"?l.value:l,f=typeof l=="object"?l.label:l,p=typeof l=="object"?[l.account_name,l.account_type,l.summary].filter(Boolean).join(" / "):"";return`
                <button type="button" class="tui-entry-card" data-entry-option-index="${u}" data-entry-option-value="${i(d)}">
                    <strong>${i(f)}</strong>
                    <span>${i(p||"\u9009\u62E9\u540E\u81EA\u52A8\u8FDB\u5165\u9ED8\u8BA4\u7ED3\u679C\u3002")}</span>
                    <small>${i(t.label)}</small>
                </button>
            `}).join("");c.main.innerHTML=`
            <section class="tui-entry-state">
                <div class="tui-view-status">\u5165\u53E3\u9009\u62E9 / ${i(e.screen.label)}</div>
                <div class="tui-entry-copy">
                    <strong>${i(n.empty_copy||Le(e.screen,`\u5148\u9009\u62E9${r.label}`))}</strong>
                    ${(n.help_steps||[]).map(l=>`<p>${i(l)}</p>`).join("")}
                </div>
                <div class="tui-entry-grid">${s}</div>
            </section>
        `,c.main.querySelectorAll("[data-entry-option-index]").forEach((l,u)=>{l.addEventListener("click",()=>{const d=a[u],f=typeof d=="object"?d.value:d;$(t.key,null,{params:{[r.key]:f}})})})}function oa(e,t,n,r){c.main.innerHTML=`
            <section class="tui-entry-state">
                <div class="tui-view-status">\u4EFB\u52A1\u8D77\u6B65 / ${i(e.screen.label)}</div>
                <div class="tui-entry-copy">
                    <strong>${i(n.empty_copy||Le(e.screen,`\u5148\u8865\u5145${r.label}`))}</strong>
                    ${(n.help_steps||[]).map(a=>`<p>${i(a)}</p>`).join("")}
                </div>
                <div class="tui-entry-actions">
                    <button type="button" data-focus-default-action>\u6253\u5F00\u9ED8\u8BA4\u4EFB\u52A1</button>
                </div>
            </section>
        `,c.main.querySelector("[data-focus-default-action]")?.addEventListener("click",()=>{ea(t.key)})}function ue(e){const t=e&&typeof e.user_experience=="object"?e.user_experience:{};return{journey:String(t.journey||"").trim(),primaryTask:x(t.primary_task||e?.summary||e?.label||""),primaryOutcome:x(t.primary_outcome||e?.summary||e?.label||""),emptyStateHint:x(t.empty_state_hint||e?.summary||"\u5148\u8FD0\u884C\u672C\u5C4F\u4E3B\u4EFB\u52A1\uFF0C\u5FC5\u8981\u65F6\u8865\u5145\u53C2\u6570\u3002"),nextStepHint:x(t.next_step_hint||"\u6839\u636E\u7ED3\u679C\u7EE7\u7EED\u4E0B\u4E00\u9879\u4E3B\u6D41\u7A0B\uFF0C\u6216\u8FDB\u5165\u53EF\u6267\u884C\u64CD\u4F5C\u3002")}}function $n(e){const t=ue(e);return ht([t.primaryTask,t.primaryOutcome!==t.primaryTask?t.primaryOutcome:""]).join(`
`)}function Le(e,t=""){return ue(e).emptyStateHint||x(t||e?.summary||"\u5148\u8FD0\u884C\u672C\u5C4F\u4E3B\u4EFB\u52A1\u3002")}function vn(e){const t=ue(e),n=[["\u4E3B\u4EFB\u52A1",t.primaryTask],["\u76EE\u6807\u7ED3\u679C",t.primaryOutcome]],r=ht([t.emptyStateHint,t.nextStepHint]);return[{title:"\u7528\u6237\u4EFB\u52A1",rows:n,body:r}]}function _n(e){return Array.isArray(e?.dashboard_panels)&&e.dashboard_panels.length>0}function de(e){return _n(e)&&String(e?.chrome_mode||"").toLowerCase()==="immersive"}function ct(e){if(!e||!e.objective&&!e.decision_output&&!(e.checkpoints||[]).length)return[];const t=[];e.objective&&t.push({label:"\u76EE\u6807",value:x(e.objective)}),e.decision_output&&t.push({label:"\u4EA7\u51FA",value:x(e.decision_output)});const n=(e.checkpoints||[]).map((r,a)=>`${a+1}. ${x(r)}`);return[{title:"\u4E1A\u52A1\u76EE\u6807",rows:t,body:n}]}function sa(e){if(!c.workflowStrip)return;if(A(o.screen?.screen?.key)){c.workflowStrip.hidden=!0,c.workflowStrip.innerHTML="";return}const t=e||{};if(!t.name){c.workflowStrip.hidden=!0,c.workflowStrip.innerHTML="";return}const n=t.previous||{},r=t.next||{},a=w.host?.workflowActionKeys||[],s=(typeof C.getHomeActions=="function"?C.getHomeActions({lastWorkspace:o.lastNonHomeScreen,lastWorkspaceLabel:yn(o.lastNonHomeScreen),preferredLane:o.preferredHomeLane}):[]).filter(f=>a.includes(f.key)),l=String(w.host?.workflowActionsLane||""),d=s.length&&l&&rn({workflow:t})===l?`
                <div class="tui-workflow-tools">
                    ${s.map(f=>`
                        <button type="button" data-home-action-key="${i(f.key)}">${i(f.label)}</button>
                    `).join("")}
                </div>
            `:"";c.workflowStrip.hidden=!1,c.workflowStrip.innerHTML=`
            <div class="tui-workflow-main">
                <span>${i(t.name)}</span>
                <strong>${i(String(t.step||"-").padStart(2,"0"))}/${i(t.total||"-")}</strong>
                <span>${i(t.label||"")}</span>
            </div>
            <div class="tui-workflow-role">${i(t.role||"")}</div>
            <div class="tui-workflow-nav">
                ${n.key?`<button type="button" data-workflow-target="${i(n.key)}">&lt; ${i(n.label)}</button>`:"<span>\u8D77\u70B9</span>"}
                ${r.key?`<button type="button" data-workflow-target="${i(r.key)}">${i(r.label)} &gt;</button>`:"<span>\u7EC8\u70B9</span>"}
            </div>
            ${d}
        `,c.workflowStrip.querySelectorAll("[data-workflow-target]").forEach(f=>{f.addEventListener("click",()=>S(f.dataset.workflowTarget))}),c.workflowStrip.querySelectorAll("[data-home-action-key]").forEach(f=>{f.addEventListener("click",()=>oe(f.dataset.homeActionKey))})}function ia(){const e=typeof C.getHomeActions=="function"?C.getHomeActions({lastWorkspace:o.lastNonHomeScreen,lastWorkspaceLabel:yn(o.lastNonHomeScreen),preferredLane:o.preferredHomeLane,availableActionKeys:new Set((o.screen?.actions||[]).map(t=>String(t.key||"")))}):[];return!Array.isArray(e)||!e.length?"":`
            <section class="tui-home-actions" aria-label="\u7EDF\u4E00\u9996\u9875\u4E3B\u52A8\u4F5C">
                ${e.map(t=>`
                    <button type="button" class="tui-home-action${t.active?" is-active":""}" data-home-action-key="${i(t.key)}">
                        <strong>${i(t.label)}</strong>
                        <span>${i(t.description||"")}</span>
                    </button>
                `).join("")}
            </section>
        `}function ca(e,t={}){const n=e.screen,r=n.dashboard_panels||[],a=de(n),s=ye(e.actions||[]),l=n.business_context||{},u=ue(n),d=ma(r,n);if(Ce("dashboard"),c.mainTitle.textContent=a?"\u7CFB\u7EDF\u9996\u9875":`${n.label} \u6982\u89C8`,c.main.innerHTML=`
            ${A(n.key)?ia():""}
            <div class="tui-dashboard-grid${d.contentFlow?" is-content-flow":""}" style="${i(d.gridStyle)}">
                ${r.map((g,h)=>`
                    <article class="tui-dash-panel" style="grid-area: ${i(d.areas[h])};" data-dashboard-panel="${i(g.key)}" data-panel-priority="${i(pe(g))}" data-panel-semantic="${i(lt(g))}">
                        ${B(g,'<div class="tui-loading">\u8BFB\u53D6\u4E1A\u52A1\u6570\u636E...</div>')}
                    </article>
                `).join("")}
            </div>
        `,te({title:n.label,body:$n(n),rows:[["\u4E3B\u4EFB\u52A1",u.primaryTask],["\u76EE\u6807\u7ED3\u679C",u.primaryOutcome],["\u5DE5\u4F5C\u533A",e.module.label],["\u5E03\u5C40",a?"\u7CFB\u7EDF\u9996\u9875\u603B\u63A7\u53F0":"\u4E1A\u52A1\u6982\u89C8\u9762\u677F"],["\u4E3B\u6D41\u7A0B",s.primary],["\u652F\u6491\u68C0\u67E5",s.support],["\u4EFB\u52A1",n.action_count]],sections:[...vn(n),...ct(l),{title:"\u64CD\u4F5C\u63D0\u793A",body:[a?"\u603B\u89C8\u9762\u677F\u6765\u81EA\u5DF2\u5BA1\u6838 action\uFF1B\u70B9\u51FB\u9762\u677F\u53EF\u8FDB\u5165\u5BF9\u5E94\u4E1A\u52A1\u5C4F\u7EE7\u7EED\u5904\u7406\u3002":"\u6982\u89C8\u9762\u677F\u7528\u4E8E\u5148\u770B\u5168\u5C40\u6458\u8981\uFF1B\u5DE6\u4FA7\u4EFB\u52A1\u533A\u53EF\u4EE5\u7EE7\u7EED\u6253\u5F00\u660E\u7EC6\u6216\u6267\u884C\u8865\u5145\u67E5\u8BE2\u3002"],rows:[]}]}),H(c.main),c.main.querySelectorAll("[data-home-action-key]").forEach(g=>{g.addEventListener("click",()=>oe(g.dataset.homeActionKey))}),t.suppressAutoActions&&!a)return;const f=r.filter(g=>pe(g)==="p0"),p=r.filter(g=>pe(g)!=="p0");f.forEach(g=>fe(g));const y=()=>p.forEach(g=>fe(g));typeof window.requestIdleCallback=="function"?window.requestIdleCallback(y,{timeout:kr}):window.setTimeout(y,0)}function An(e){return String(e.target_screen||e.screen_key||"")}function la(e,t){const n=String(e||"").trim(),r=String(t||"").trim(),a=String(o.screen?.screen?.key||"").trim();if(n&&n!==a){S(n);return}if(r){const s=v(r);if(s&&!Cn(s)){ar();const l=yt(s);Kn(l),m(`\u8BF7\u586B\u5199\u201C${s.label}\u201D\u540E\u7EE7\u7EED`);return}$(r,null,{params:{}});return}}function Te(e){const t=v(e);return!t||!Array.isArray(t.result_semantics)?[]:t.result_semantics.map(n=>String(n||"").trim()).filter(Boolean)}function pe(e){return String(e?.user_priority||"p2").trim().toLowerCase()||"p2"}function lt(e){const t=String(e?.presentation_semantic||"").trim();return t||Te(e?.action_key)[0]||""}function ua(e){const t=String(e||"").trim().toLowerCase();return t==="p0"?"P0":t==="p1"?"P1":"P2"}function da(e){return{primary_status:"\u72B6\u6001",primary_list:"\u4E3B\u4EFB\u52A1",supporting_list:"\u652F\u6491\u5217\u8868",copyable_secret:"\u51ED\u8BC1",endpoint_list:"\u5730\u5740",multiline_prompt:"\u63D0\u793A\u8BCD",setup_guide:"\u63A5\u5165\u6307\u5F15",next_step:"\u4E0B\u4E00\u6B65",supporting_detail:"\u6458\u8981",debug_only:"\u8C03\u8BD5"}[String(e||"").trim()]||"\u6982\u89C8"}function Q(e,t){return(e||[]).includes(t)}function pa(e){const t=new Set;return(e||[]).filter(n=>{const r=String(n||"").trim();return!r||t.has(r)?!1:(t.add(r),!0)})}function fa(e){return pa([lt(e),...Te(e?.action_key)])}function ma(e,t){const n=ya(e),r=_a(t),a=r===1||A(t?.key),s=a?"auto":"minmax(190px, auto)",l=a?"auto":"minmax(190px, 1fr)";return{areas:n,contentFlow:a,gridStyle:[`--tui-dashboard-areas-desktop: ${ut(n,r,!0)}`,`--tui-dashboard-areas-tablet: ${ut(n,2)}`,`--tui-dashboard-areas-mobile: ${ut(n,1)}`,`--tui-dashboard-rows-desktop: ${dt(n,r,s)}`,`--tui-dashboard-rows-tablet: ${dt(n,2,l)}`,`--tui-dashboard-rows-mobile: ${dt(n,1,"auto")}`].join("; ")}}function ya(e){const t=new Map;return e.map((n,r)=>{const a=n.layout_area||n.key||`panel-${r+1}`,s=ga(a)||`panel_${r+1}`,l=t.get(s)||0;return t.set(s,l+1),l?`${s}_${l+1}`:s})}function ga(e){const t=String(e||"").trim().toLowerCase().replace(/[^a-z0-9_-]+/g,"_").replace(/^[-0-9]+/,"").replace(/_+/g,"_").replace(/^_+|_+$/g,"");return t&&t!=="none"?t:""}function ut(e,t,n=!1){return xn(e,t).map(a=>`"${(n?ha(a):ba(a,t)).join(" ")}"`).join(" ")}function dt(e,t,n){const r=Math.max(1,xn(e,t).length);return Array.from({length:r},()=>n).join(" ")}function xn(e,t){const n=e.length?e:["panel_1"],r=[];for(let a=0;a<n.length;a+=t)r.push(n.slice(a,a+t));return r}function ha(e){const t=Math.floor(12/e.length);let n=12-t*e.length;return e.flatMap(r=>{const a=t+(n>0?1:0);return n-=1,Array.from({length:a},()=>r)})}function ba(e,t){const n=[...e],r=n.at(-1)||"panel_1";for(;n.length<t;)n.push(r);return n}function Cn(e){if(!e)return!1;const t=String(e.method||"GET").trim().toUpperCase(),n=String(e.risk||"read").trim().toLowerCase(),r=o.screen?.screen||{},a=String(r.audience||"")==="admin"&&String(e.screen_key||"")===String(r.key||"");return["GET","HEAD","OPTIONS"].includes(t)&&(n==="read"||n==="admin"&&a)&&it(e).length===0}async function fe(e){const t=c.main.querySelector(`[data-dashboard-panel="${CSS.escape(e.key)}"]`);if(!t)return;if(!e.action_key){t.innerHTML=B(e,M(e,e.empty_message||"\u7B49\u5F85\u53D1\u5E03\u6570\u636E\u6E90\u3002")),H(t);return}const n=A(o.screen?.screen?.key)?Rr(e):"",r=v(e.action_key);if(!n&&!Cn(r)){t.innerHTML=B(e,wa(e,r)),H(t);return}try{let a=null,s=null;if(typeof C.loadDashboardPanel=="function"){const l=await C.loadDashboardPanel(e,{actionRunUrl:Ge,fetchJson:R,screen:o.screen});l&&(a=l.view_model||l,s=l.badge||Je(a.rows||[]))}if(!a)if(n){const u=(await sn())?.[n]||{};a=va(e,u),s=u?.badge?{blockedCount:Number(u.badge.blocked_count||0),warningCount:Number(u.badge.warning_count||0)}:Je(a.rows||[])}else a=(await R(Ge(e.action_key),{method:"POST",body:JSON.stringify({params:{}})})).view_model,s=Je(Array.isArray(a?.rows)?a.rows:[]);if(A(o.screen?.screen?.key)&&(o.homePanelBadges[e.key]=s),$a(e,a,t)||(t.innerHTML=B(e,Ln(e,a)),me(t),pt(t,e),H(t),Be(t)),A(o.screen?.screen?.key)){const l=t.querySelector("[data-panel-badge]");l&&(l.innerHTML=re(o.homePanelBadges[e.key],{compact:!0}))}Ye()}catch(a){t.innerHTML=B(e,et(e,a)),H(t),tt(t,e)}}function B(e,t){const n=`
            <h3>
                <span>${i(e.title)}</span>
                <span class="tui-panel-heading-tools">
                    <span class="tui-panel-priority">${i(ua(pe(e)))}</span>
                    <span class="tui-panel-semantic">${i(da(lt(e)))}</span>
                    <span data-panel-badge></span>
                    ${ka(e)}
                </span>
            </h3>
            ${e.note?`<div class="tui-panel-caption">${i(e.note)}</div>`:""}
            ${t}
        `;return Sa(e)?`
            <details class="tui-panel-disclosure">
                <summary>\u5C55\u5F00${i(e.title)}</summary>
                ${n}
            </details>
        `:n}function wa(e,t){if(!t)return M(e,e.empty_message||"\u5F53\u524D\u4EFB\u52A1\u6682\u4E0D\u53EF\u7528\u3002");const n=String(t.submit_label||t.label||"\u7EE7\u7EED").trim(),r=String(e.note||"").trim(),a=String(t.description||"").trim(),s=a&&a!==r?a:r?"":"\u586B\u5199\u5FC5\u8981\u4FE1\u606F\u540E\u7EE7\u7EED\u3002";return`
            <div class="tui-dashboard-action-prompt">
                ${s?`<p>${i(s)}</p>`:""}
                <button
                    type="button"
                    class="tui-entry-action"
                    data-dashboard-open
                    data-dashboard-target="${i(An(e))}"
                    data-dashboard-action="${i(t.key)}"
                >${i(n)}</button>
            </div>
        `}function Sa(e){return pe(e)==="p2"&&!A(o.screen?.screen?.key)}function ka(e){const t=An(e),n=String(e?.action_key||"").trim();return!t&&!n?"":`
            <button
                class="tui-dashboard-open"
                type="button"
                data-dashboard-open
                data-dashboard-target="${i(t)}"
                data-dashboard-action="${i(n)}"
                aria-label="\u6253\u5F00${i(e.title||"\u9762\u677F")}"
            >\u6253\u5F00</button>
        `}function H(e){e.querySelectorAll("[data-dashboard-open]").forEach(t=>{t.dataset.dashboardOpenBound!=="true"&&(t.dataset.dashboardOpenBound="true",t.addEventListener("click",n=>{n.preventDefault(),n.stopPropagation(),la(t.dataset.dashboardTarget,t.dataset.dashboardAction)}))})}function $a(e,t,n){const r=String(t?.renderer||"").trim();if(!r||We.has(r))return!1;const a=ne.get(r);if(!a)return!1;n.innerHTML=B(e,`<div class="tui-extension-host is-dashboard" data-renderer="${i(r)}"></div>`);const s=n.querySelector(".tui-extension-host");try{a({viewModel:t,container:s,runtimeConfig:w,escapeHtml:i})}catch{s.innerHTML=T("\u6269\u5C55\u89C6\u56FE\u6682\u65F6\u4E0D\u53EF\u7528\u3002",["\u8BF7\u7A0D\u540E\u91CD\u8BD5\uFF0C\u6216\u6539\u7528\u9ED8\u8BA4\u4EFB\u52A1\u67E5\u770B\u6570\u636E\u3002"])}return me(n),H(n),!0}function Ln(e,t){return t?t.stale&&e.stale_message?M(e,e.stale_message):jn(t)?kt(t):e.kind==="regime_quadrant"?xa(t):t.kind==="chart"?St(t,{compact:!0}):t.kind==="image"?Un(t,{compact:!0}):t.kind==="kpi_trend"?Mn(t,{compact:!0}):t.kind==="table_chart"?Wn(t,{compact:!0}):t.kind==="host_slot"?Gn(t,{compact:!0}):t.kind==="custom"?kt(t):t.kind==="datagrid"?Pn(e,t):t.kind==="detail"?Fa(e,t):`<div class="tui-message">${i(t.message||t.status||"\u6B63\u5E38")}</div>`:M(e,e.empty_message||"\u6682\u65E0\u53EF\u663E\u793A\u6570\u636E\u3002")}function va(e,t){const n=Array.isArray(t?.rows)?t.rows:[],r=(Array.isArray(e?.columns)?e.columns:[]).map(a=>({key:String(a?.key||"").trim(),label:String(a?.label||a?.key||"").trim()})).filter(a=>a.key);return{kind:"datagrid",title:e?.title||"",status:String(t?.status||"ok"),columns:r,rows:n,total:Number(t?.total||n.length||0),empty_message:"\u6682\u65E0\u6570\u636E",empty_guidance:[]}}function _a(e){if(typeof _.dashboardDesktopColumns=="function")return _.dashboardDesktopColumns(e,w.host||{});throw new Error("AgomTUI Runtime core is missing dashboardDesktopColumns")}function Aa(e){const t=String(e||"").trim().toLowerCase();return[{aliases:["recovery","\u590D\u82CF"],left:"25%",top:"25%",label:"\u590D\u82CF\u8C61\u9650"},{aliases:["overheat","\u8FC7\u70ED"],left:"75%",top:"25%",label:"\u8FC7\u70ED\u8C61\u9650"},{aliases:["deflation","recession","\u901A\u7F29","\u8870\u9000"],left:"25%",top:"75%",label:"\u901A\u7F29\u8C61\u9650"},{aliases:["stagflation","\u6EDE\u80C0"],left:"75%",top:"75%",label:"\u6EDE\u80C0\u8C61\u9650"}].find(r=>r.aliases.some(a=>t.includes(a)))||null}function xa(e){const t=Da(e.fields||[]),n=Re(t,["current_regime","dominant_regime","regime","regime_name","state","name"]),r=Re(t,["confidence","regime_confidence","confidence_pct"]),a=Re(t,["trend","movement","transition_target","status"]),s=Re(t,["warning","transition_warning","risk","alerts"]);if(![n,r,a,s].every(V))return`
                <div class="tui-panel-placeholder tui-contract-error" data-render-contract-error="regime_quadrant">
                    <div>Regime \u7ED3\u679C\u6570\u636E\u4E0D\u5B8C\u6574\uFF0C\u5DF2\u505C\u6B62\u5C55\u793A\u5360\u4F4D\u5224\u65AD\u3002</div>
                    <small>\u8BF7\u5237\u65B0\u540E\u91CD\u8BD5\uFF1B\u82E5\u6301\u7EED\u51FA\u73B0\uFF0C\u8BF7\u68C0\u67E5\u6570\u636E\u540C\u6B65\u4E0E\u7ED3\u679C\u6295\u5F71\u3002</small>
                </div>
            `;const l=Tn(r),u=Aa(n);return`
            <div class="tui-quadrant">
                <div class="q q-recovery">\u590D\u82CF<br><strong>RECOVERY</strong></div>
                <div class="q q-overheat">\u8FC7\u70ED<br><strong>OVERHEAT</strong></div>
                <div class="q q-recession">\u8870\u9000<br><strong>RECESSION</strong></div>
                <div class="q q-stagflation">\u6EDE\u80C0<br><strong>STAGFLATION</strong></div>
                <div class="q-axis-x"></div>
                <div class="q-axis-y"></div>
                ${u?`<div class="q-marker" style="left:${u.left};top:${u.top}" role="img" aria-label="${i(u.label)}">\u25C6</div>`:""}
            </div>
            <div class="tui-dash-lines">
                <div>\u5F53\u524D\u5224\u65AD: <strong class="tui-green">${i(n)}</strong></div>
                <div>\u7F6E\u4FE1\u5EA6: <strong>${i(l)}</strong>\u3000\u8D8B\u52BF: <strong class="tui-green">${i(a)}</strong></div>
                <div>\u62D0\u70B9\u9884\u8B66: ${i(s)}</div>
            </div>
        `}function Tn(e){if(!V(e))return q(e);const t=Number(e);return Number.isFinite(t)?`${(Math.abs(t)<=1?t*100:t).toFixed(1).replace(/\.0$/,"")}%`:q(e)}function Pn(e,t){const n=(t.rows||[]).slice(0,Number(e.max_rows||8)),a=(Array.isArray(e.columns)?e.columns:[]).filter(f=>n.some(p=>Object.prototype.hasOwnProperty.call(p,f.key))),l=(a.length?a:t.columns||[]).filter(f=>n.some(p=>Object.prototype.hasOwnProperty.call(p,f.key))).slice(0,6);if(!n.length||!l.length)return M(e,e.empty_message||"\u6682\u65E0\u8868\u683C\u6570\u636E\u3002");const u=Array.isArray(e.row_actions)?e.row_actions:[],d=l.map(f=>f.label||f.key);return u.length&&d.push("\u64CD\u4F5C"),`
            <div class="tui-table-scroll" tabindex="0" aria-label="${i(e.title||"\u8868\u683C")}">
            <table class="tui-mini-table">
                <thead><tr>${d.map((f,p)=>`<th class="${u.length&&p===d.length-1?"tui-row-actions-header":""}">${i(f)}</th>`).join("")}</tr></thead>
                <tbody>
                    ${n.map(f=>`
                        <tr>
                            ${l.map(p=>{const y=q(f[p.key]);return`<td class="${ft(y,p.label||p.key)}">${i(y)}</td>`}).join("")}
                            ${u.length?`<td class="tui-row-actions-cell">${Ca(e,f)}</td>`:""}
                        </tr>
                    `).join("")}
                </tbody>
            </table>
            </div>
        `}function Ca(e,t){return`<div class="tui-row-actions">${(Array.isArray(e?.row_actions)?e.row_actions:[]).map(r=>{const a=v(r.action_key),s=Object.fromEntries(Object.entries(r.param_map||{}).map(([u,d])=>[u,t?.[d]])),l=La(r.label_template,t);return`
                <button
                    class="tui-row-action"
                    type="button"
                    data-dashboard-row-action
                    data-row-action-key="${i(r.action_key)}"
                    data-row-action-params="${i(JSON.stringify(s))}"
                    data-row-action-row="${i(JSON.stringify(t))}"
                    aria-label="${i(l)}"
                    title="${i(l)}"
                >${i(a?.label||"\u64CD\u4F5C")}</button>
            `}).join("")}</div>`}function La(e,t){return String(e||"\u64CD\u4F5C").replace(/\{([^{}]+)\}/g,(n,r)=>String(t?.[r]??"-"))}function Ta(e){const t=String(e?.method||"GET").trim().toUpperCase();return["POST","PUT","PATCH","DELETE"].includes(t)?(e?.fields||[]).some(n=>n.input_type!=="hidden"&&String(n.binding||"body").trim().toLowerCase()==="body"):!1}function Pa(e,t,n,r){let a=0;return(t?.fields||[]).forEach(s=>{const l=ge(e,s.key);if(!l||s.input_type==="password")return;let u=Object.prototype.hasOwnProperty.call(r,s.key)?r[s.key]:Fe(n,s,t);u!=null&&(typeof u=="object"&&(u=JSON.stringify(u,null,2)),l.type==="checkbox"?l.checked=!!u:l.value=String(u),a+=1)}),a}function Ra(e,t,n,r,a){const s=yt(e);if(!s)return m(`\u8BF7\u5148\u6253\u5F00\u201C${e?.label||"\u7F16\u8F91\u4EFB\u52A1"}\u201D\u8868\u5355`),!0;o.selectedRowContext=W(r),s.dataset.dashboardPanelKey=t.key||"",s.dataset.dashboardResultPanelKey=n.result_panel_key||"",s.dataset.dashboardRefreshPanelKey=n.refresh_panel_key||"",s.hidden=!1,s.closest("details")?.setAttribute("open",""),s.closest(".tui-action-group")?.removeAttribute("hidden");const l=Pa(s,e,r,a);return s.scrollIntoView({block:"nearest"}),s.querySelector("input:not([type='hidden']),select,textarea")?.focus(),m(l?`\u5DF2\u4ECE\u5F53\u524D\u884C\u586B\u5145 ${l} \u9879\uFF0C\u8BF7\u4FEE\u6539\u540E\u63D0\u4EA4`:`\u8BF7\u586B\u5199\u201C${e?.label||"\u7F16\u8F91\u4EFB\u52A1"}\u201D\u540E\u63D0\u4EA4`),!0}function pt(e,t){e.querySelectorAll("[data-dashboard-row-action]").forEach(n=>{n.dataset.rowActionBound!=="true"&&(n.dataset.rowActionBound="true",n.addEventListener("click",async r=>{r.preventDefault(),r.stopPropagation();let a={};try{a=JSON.parse(n.dataset.rowActionParams||"{}")}catch{m("\u884C\u64CD\u4F5C\u53C2\u6570\u4E0D\u53EF\u7528");return}try{const s=v(n.dataset.rowActionKey),l=(t.row_actions||[]).find(y=>y.action_key===n.dataset.rowActionKey)||{};if(Ta(s)){const y=JSON.parse(n.dataset.rowActionRow||"{}");Ra(s,t,l,y,a);return}n.disabled=!0;const u=String(s?.method||"GET").trim().toUpperCase(),d=!["GET","HEAD","OPTIONS"].includes(u),f=String(l.result_panel_key||"").trim(),p=String(l.refresh_panel_key||"").trim();if(f||p){await $(n.dataset.rowActionKey,null,{params:a,dashboardResultPanelKey:f,dashboardRefreshPanelKey:p});return}await $(n.dataset.rowActionKey,null,d?{params:a,dashboardPanelKey:t.key}:{params:a})}finally{n.disabled=!1}}))})}function Fa(e,t){const n=fa(e);if(n.length)return Rn(t,n,{compact:!0,panel:e});const r=Fn(t.fields||[],e).slice(0,Number(e.max_rows||8));if(!r.length){const a=(t.nested||[]).slice(0,Number(e.max_rows||8));return a.length?qn(["\u9879\u76EE","\u6570\u91CF"],a.map(s=>[s.label,s.count])):M(e,"\u6682\u65E0\u6458\u8981\u6570\u636E\u3002")}return`
            ${qn(["\u9879\u76EE","\u503C"],r.map(a=>[a.label,a.value]))}
            ${e.note?`<div class="tui-panel-note">${i(e.note)}</div>`:""}
        `}function Ea(){return Te(o.lastAction)}function Rn(e,t,n={}){const r=Fn(e.fields||[],n.panel).slice(0,Number(n.panel?.max_rows||12)),a=(e.nested||[]).slice(0,Number(n.panel?.max_rows||12)),s=["tui-semantic-detail",n.compact?"is-compact":"",Q(t,"primary_status")?"is-primary-status":"",Q(t,"copyable_secret")?"is-copyable-secret":"",Q(t,"endpoint_list")?"is-endpoint-list":"",Q(t,"multiline_prompt")?"is-multiline-prompt":"",Q(t,"setup_guide")?"is-setup-guide":""].filter(Boolean).join(" "),l=Q(t,"primary_status")?`
                <div class="tui-status-hero">
                    <strong>${i(e.title||"\u72B6\u6001")}</strong>
                    <span class="tui-status-pill">${i(e.status||"\u6B63\u5E38")}</span>
                </div>
            `:"",u=r.filter(h=>Pe(h)==="secret"&&V(h.value)),d=r.filter(h=>Pe(h)==="copyable"&&V(h.value)),f=r.filter(h=>Pe(h)==="multiline"&&V(h.value)),p=r.filter(h=>Pe(h)==="metadata"),y=[u.length?Ba(u):"",d.length?Ha(d):"",p.length?En(p):"",f.length?Ia(f):""].filter(Boolean).join(""),g=a.length?`<div class="tui-nested-list">${a.map(h=>`<span>${i(h.label)}: ${i(h.count)} \u884C</span>`).join("")}</div>`:"";return`
            <section class="${s}">
                ${l}
                ${y||M(n.panel||{},"\u6682\u65E0\u6458\u8981\u6570\u636E\u3002")}
                ${g}
            </section>
        `}function V(e){return e!=null&&String(e).trim()!==""&&String(e).trim()!=="-"}function Fn(e,t){const n=Array.isArray(t?.field_rules)?t.field_rules:[],r=new Map(n.map(a=>[String(a?.label||"").trim(),a]));return(e||[]).flatMap(a=>{const s=r.get(String(a?.label||"").trim());return s?.visible===!1?[]:[{...a,value:qa(a?.value,s?.format)}]})}function qa(e,t){const n=String(t||"text").trim();if(n==="money"){if(!V(e))return q(e);const r=Number(e);return Number.isFinite(r)?`${r.toLocaleString("zh-CN",{maximumFractionDigits:2})} \u5143`:q(e)}if(n==="percentage")return Tn(e);if(n==="datetime"){const r=Date.parse(String(e||""));return Number.isFinite(r)?new Date(r).toLocaleString("zh-CN",{hour12:!1}):q(e)}return q(e)}function En(e){return e.length?`
            <dl class="tui-detail-grid">
                ${e.map(t=>`
                    <dt>${i(t.label)}</dt>
                    <dd>${i(q(t.value))}</dd>
                `).join("")}
            </dl>
        `:""}function Pe(e){const t=String(e?.presentation||"metadata").trim().toLowerCase();return["secret","copyable","multiline","metadata"].includes(t)?t:"metadata"}function Ba(e){return`
            <div class="tui-copy-stack">
                ${e.map(t=>`
                    <div class="tui-copy-row is-secret">
                        <div class="tui-copy-head">
                            <span>${i(t.label)}</span>
                            <span class="tui-copy-controls">
                                <button
                                    class="tui-copy-action"
                                    type="button"
                                    data-secret-toggle
                                    data-secret-visible="false"
                                    data-secret-label="${i(t.label)}"
                                    aria-label="\u663E\u793A${i(t.label)}"
                                >\u663E\u793A</button>
                                <button
                                    class="tui-copy-action"
                                    type="button"
                                    data-copy-value="${i(t.value)}"
                                    data-copy-label="${i(t.label)}"
                                >\u590D\u5236</button>
                            </span>
                        </div>
                        <code data-secret-value="${i(t.value)}">\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022</code>
                    </div>
                `).join("")}
            </div>
        `}function Ha(e){return e.length?`
            <div class="tui-copy-stack">
                ${e.map(t=>`
                    <div class="tui-copy-row">
                        <div class="tui-copy-head">
                            <span>${i(t.label)}</span>
                            <button
                                class="tui-copy-action"
                                type="button"
                                data-copy-value="${i(t.value)}"
                                data-copy-label="${i(t.label)}"
                            >\u590D\u5236</button>
                        </div>
                        <code>${i(t.value)}</code>
                    </div>
                `).join("")}
            </div>
        `:""}function Ia(e){return e.length?`
            <div class="tui-copy-stack">
                ${e.map(t=>{const n=String(t?.key||"")==="access_package";return`
                    <section class="tui-copy-block-card${n?" is-dominant":""}">
                        <div class="tui-copy-head">
                            <strong>${i(t.label)}</strong>
                            <button
                                class="tui-copy-action"
                                type="button"
                                data-copy-value="${i(t.value)}"
                                data-copy-label="${i(t.label)}"
                            >${n?"\u590D\u5236\u5B8C\u6574\u63A5\u5165\u5305":"\u590D\u5236"}</button>
                        </div>
                        <pre class="tui-copy-block">${i(t.value)}</pre>
                    </section>
                `}).join("")}
            </div>
        `:""}async function Ka(e){const t=String(e??"");if(navigator.clipboard&&typeof navigator.clipboard.writeText=="function"){await navigator.clipboard.writeText(t);return}const n=document.createElement("textarea");n.value=t,n.setAttribute("readonly","readonly"),n.style.position="fixed",n.style.opacity="0",n.style.pointerEvents="none",document.body.appendChild(n),n.select(),document.execCommand("copy"),document.body.removeChild(n)}function me(e=document){e.querySelectorAll("[data-secret-toggle]").forEach(t=>{t.dataset.secretBound!=="true"&&(t.dataset.secretBound="true",t.addEventListener("click",n=>{n.preventDefault(),n.stopPropagation();const r=t.closest(".tui-copy-row")?.querySelector("[data-secret-value]");if(!r)return;const a=t.dataset.secretVisible==="true",s=String(t.dataset.secretLabel||"\u51ED\u8BC1");t.dataset.secretVisible=a?"false":"true",t.textContent=a?"\u663E\u793A":"\u9690\u85CF",t.setAttribute("aria-label",`${a?"\u663E\u793A":"\u9690\u85CF"}${s}`),r.textContent=a?"\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022":r.dataset.secretValue}))}),e.querySelectorAll("[data-copy-value]").forEach(t=>{t.dataset.copyBound!=="true"&&(t.dataset.copyBound="true",t.addEventListener("click",async n=>{n.preventDefault(),n.stopPropagation();const r=String(t.dataset.copyLabel||"\u5185\u5BB9").trim(),a=t.textContent;try{await Ka(t.dataset.copyValue||""),t.textContent="\u5DF2\u590D\u5236",m(`${r}\u5DF2\u590D\u5236`)}catch{t.textContent="\u590D\u5236\u5931\u8D25",m(`${r}\u590D\u5236\u5931\u8D25`)}window.setTimeout(()=>{t.textContent=a},1200)}))})}function Da(e){return e.reduce((t,n)=>(t[String(n.key||n.label||"").toLowerCase()]=n.value,t[String(n.label||"").toLowerCase()]=n.value,t),{})}function Re(e,t){for(const n of t){const r=e[String(n).toLowerCase()];if(r!=null&&r!=="")return r}return""}function M(e,t){return`
            <div class="tui-panel-placeholder">
                <div>${i(t)}</div>
                ${e.note?`<small>${i(e.note)}</small>`:""}
            </div>
        `}function qn(e,t,n){return`
            <div class="tui-table-scroll" tabindex="0" aria-label="\u8868\u683C">
            <table class="tui-mini-table">
                <thead><tr>${e.map(r=>`<th>${i(r)}</th>`).join("")}</tr></thead>
                <tbody>
                    ${t.map((r,a)=>`
                        <tr class="${a===n?"is-hot":""}">
                            ${r.map((s,l)=>`<td class="${ft(s,e[l])}">${i(s)}</td>`).join("")}
                        </tr>
                    `).join("")}
                </tbody>
            </table>
            </div>
        `}function ft(e,t=""){const n=String(e),r=String(t||""),a=[];return(/^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/.test(n.trim())||["\u65E5\u671F","\u65F6\u95F4","\u89C2\u6D4B","\u57FA\u51C6\u65E5"].some(s=>r.includes(s)))&&a.push("is-nowrap"),["\u6807\u7684","\u4EE3\u7801","\u540D\u79F0","\u80A1\u7968","\u8D44\u4EA7","\u8BC1\u5238"].some(s=>r.includes(s))?a.join(" "):/^-\d+(?:\.\d+)?%?$/.test(n.trim())||n.includes("\u6682\u505C")||n.includes("\u89E6\u53D1")||n.includes("\u5931\u8D25")||n.includes("\u672A\u8FD0\u884C")?(a.push("is-red"),a.join(" ")):n.includes("\u89C2\u5BDF")||/(进行中|运行中|处理中|同步中|排队中)/.test(n)?(a.push("is-yellow"),a.join(" ")):((n.includes("\u6B63\u5E38")||n.includes("\u8FD0\u884C")||n.includes("\u6210\u529F")||n.includes("%"))&&a.push("is-green"),a.join(" "))}function k(e){const t=String(e.task_tier||"").toLowerCase();return["primary","support","advanced","operation"].includes(t)?t:"support"}function ye(e){return e.reduce((t,n)=>{const r=k(n);r==="advanced"?t.advanced+=1:r==="support"?t.support+=1:r==="operation"?t.operation+=1:t.primary+=1;const a=String(n.risk||"").toLowerCase();return a==="write"&&(t.write+=1),a==="ai"&&(t.ai+=1),t},{primary:0,support:0,advanced:0,operation:0,write:0,ai:0})}function Bn(e,t){if(!e.length){c.actions.innerHTML='<div class="tui-empty-state">\u5F53\u524D\u5DE5\u4F5C\u533A\u6682\u65E0\u53EF\u6267\u884C\u4EFB\u52A1\u3002</div>';return}const n=e.filter(h=>k(h)==="primary"),r=e.filter(h=>k(h)==="support"),a=e.filter(h=>k(h)==="advanced"),s=n.length>0,l=ye(e),u=Ke(e),d=za(e),f=Ua(t),p={remaining:f.primaryOperationLimit};c.actions.innerHTML=`
            <div class="tui-action-brief">
                <div>
                    <strong>${i(t&&t.label||"\u5F53\u524D\u5DE5\u4F5C\u533A")}</strong>
                    <span data-action-summary>\u4E3B\u6D41\u7A0B ${u.completed}/${u.total} / \u64CD\u4F5C ${l.operation} / \u652F\u6491 ${l.support} / \u9AD8\u7EA7 ${l.advanced}</span>
                </div>
                <label class="tui-action-filter">
                    <span>\u4EFB\u52A1</span>
                    <input type="search" value="${i(o.actionFilterText)}" placeholder="\u8F93\u5165\u4E1A\u52A1\u8BCD" data-action-filter>
                    <button type="button" data-clear-action-filter ${o.actionFilterText?"":"hidden"}>\u6E05</button>
                </label>
                ${r.length?`
                    <button class="tui-action-toggle" type="button" data-toggle-support>
                        ${o.showSupportTasks||!s?"\u9690\u85CF\u652F\u6491":"\u663E\u793A\u652F\u6491"}
                    </button>
                `:""}
                ${a.length?`
                    <button class="tui-action-toggle" type="button" data-toggle-advanced>
                        ${o.showAdvancedQueries||!s?"\u9690\u85CF\u9AD8\u7EA7":"\u663E\u793A\u9AD8\u7EA7"}
                    </button>
                `:""}
            </div>
            ${d.map(h=>Va(h,f,p)).join("")}
            <div class="tui-empty-state" data-action-filter-empty hidden>\u6CA1\u6709\u5339\u914D\u4EFB\u52A1\u3002\u6E05\u7A7A\u7B5B\u9009\u540E\u67E5\u770B\u5168\u90E8\u3002</div>
        `,c.actions.dataset.renderedScreenKey=t&&t.key||"";const y=c.actions.querySelector("[data-action-filter]"),g=()=>{o.actionFilterText=y?y.value:o.actionFilterText,I(e,t)};y?.addEventListener("input",h=>{h.isComposing||g()}),y?.addEventListener("compositionend",g),c.actions.querySelector("[data-clear-action-filter]")?.addEventListener("click",()=>{o.actionFilterText="",y.value="",I(e,t),y.focus(),m("\u4EFB\u52A1\u7B5B\u9009\u5DF2\u6E05\u9664")}),c.actions.querySelector("[data-toggle-support]")?.addEventListener("click",()=>{o.showSupportTasks=!o.showSupportTasks,I(e,t),m(o.showSupportTasks?"\u652F\u6491\u68C0\u67E5\u5DF2\u663E\u793A":"\u652F\u6491\u68C0\u67E5\u5DF2\u9690\u85CF")}),c.actions.querySelector("[data-toggle-advanced]")?.addEventListener("click",()=>{o.showAdvancedQueries=!o.showAdvancedQueries,I(e,t),m(o.showAdvancedQueries?"\u9AD8\u7EA7\u67E5\u8BE2\u5DF2\u663E\u793A":"\u9AD8\u7EA7\u67E5\u8BE2\u5DF2\u9690\u85CF")}),ja(),I(e,t),Ee()}function Na(e,t,n){if(n)return Oa(e,n);if(!t)return!0;const r=k(e);return r==="operation"||r==="primary"?!0:r==="support"?o.showSupportTasks:r==="advanced"?o.showAdvancedQueries:!1}function I(e,t){const n=e.some(g=>k(g)==="primary"),r=o.actionFilterText.trim().toLowerCase();let a=0;c.actions.querySelectorAll("[data-action-ui-key]").forEach(g=>{const h=v(Ae(g)),b=!!(h&&Na(h,n,r));if(g.hidden=!b,b&&(a+=1),h){const P=Ie(h.key);g.classList.toggle("is-completed",P);const E=g.querySelector("[data-action-meta]");E&&(E.textContent=ln(h,P))}}),c.actions.querySelectorAll(".tui-action-group").forEach(g=>{g.hidden=!g.querySelector("[data-action-ui-key]:not([hidden])")});const s=ye(e),l=Ke(e),u=c.actions.querySelector("[data-action-summary]");u&&(u.textContent=`\u4E3B\u6D41\u7A0B ${l.completed}/${l.total} / \u64CD\u4F5C ${s.operation} / \u652F\u6491 ${s.support} / \u9AD8\u7EA7 ${s.advanced}${r?` / \u5339\u914D ${a}`:""}`);const d=c.actions.querySelector("[data-action-filter-empty]");d&&(d.hidden=a>0);const f=c.actions.querySelector("[data-clear-action-filter]");f&&(f.hidden=!r);const p=c.actions.querySelector("[data-toggle-support]");p&&(p.textContent=o.showSupportTasks||!n?"\u9690\u85CF\u652F\u6491":"\u663E\u793A\u652F\u6491");const y=c.actions.querySelector("[data-toggle-advanced]");y&&(y.textContent=o.showAdvancedQueries||!n?"\u9690\u85CF\u9AD8\u7EA7":"\u663E\u793A\u9AD8\u7EA7")}function ja(){c.actions.querySelectorAll("[data-action-ui-key]").forEach(e=>{e.addEventListener("submit",r=>{r.preventDefault(),r.stopPropagation(),xe(e)}),e.querySelector(".tui-action-button")?.addEventListener("click",r=>{r.preventDefault(),r.stopPropagation(),xe(e)}),e.querySelector("[data-fill-from-row]")?.addEventListener("click",r=>{r.preventDefault(),r.stopPropagation(),mt(e)})})}function Oa(e,t){return[e.label,e.description,e.task_group,cn(e),ce(e),...(e.fields||[]).map(r=>`${r.label} ${r.key}`)].join(" ").toLowerCase().includes(t)}function za(e){const t=[],n=new Map;return e.forEach(r=>{const a=k(r),s=a==="operation"?"00 \u53EF\u6267\u884C\u64CD\u4F5C":r.task_group||"\u6838\u5FC3\u4EFB\u52A1";if(!n.has(s)){const u={label:s,tier:a,actions:[],sequence:a==="operation"?-100:Number(r.sequence||999)};n.set(s,u),t.push(u)}const l=n.get(s);l.sequence=Math.min(l.sequence,a==="operation"?-100:Number(r.sequence||999)),l.actions.push(r)}),t.sort((r,a)=>r.sequence-a.sequence),t.forEach(r=>{r.actions.sort((a,s)=>Number(a.sequence||999)-Number(s.sequence||999))}),t}function Ua(e){const t=e?.action_density||{},n=Number(t.primary_operation_limit),r=Number(t.task_group_limit);return{primaryOperationLimit:Number.isFinite(n)&&n>0?n:Number.POSITIVE_INFINITY,taskGroupLimit:Number.isFinite(r)&&r>0?r:Number.POSITIVE_INFINITY}}function Va(e,t,n){const r=[],a=[];let s=0;return e.actions.forEach(l=>{const u=k(l),d=u==="primary"||u==="operation",f=s<t.taskGroupLimit,p=n.remaining>0;if(!d||f&&p){r.push(l),d&&(s+=1,n.remaining-=1);return}a.push(l)}),`
            <section class="tui-action-group tui-action-group-${i(e.tier)}">
                <div class="tui-action-group-title">${i(e.label)}</div>
                ${r.map(l=>Hn(l)).join("")}
                ${a.length?`
                    <details class="tui-action-overflow">
                        <summary>\u66F4\u591A\u4EFB\u52A1\uFF08${a.length}\uFF09</summary>
                        ${a.map(l=>Hn(l)).join("")}
                    </details>
                `:""}
            </section>
        `}function Hn(e){const t=(e.fields||[]).some(s=>s.input_type!=="hidden"),n=Ie(e.key),r=x(e.description||""),a=Ma(e);return`
            <form class="tui-action-form tui-action-risk-${i(e.risk||"read")} ${n?"is-completed":""}" data-action-ui-key="${i(U(e))}" novalidate>
                <button class="tui-action-button" type="button">
                    <span>
                        ${i(e.label)}
                        <span class="tui-action-meta" data-action-meta>${i(ln(e,n))}</span>
                    </span>
                </button>
                ${t?'<button class="tui-row-fill-button" type="button" data-fill-from-row>\u4ECE\u9009\u4E2D\u884C\u586B\u5145</button>':""}
                ${e.confirmation_required?'<div class="tui-action-confirm">\u63D0\u4EA4\u524D\u4F1A\u8981\u6C42\u786E\u8BA4</div>':""}
                ${r?`<div class="tui-action-desc">${i(r)}</div>`:""}
                ${(e.fields||[]).map(s=>wn(e,s)).join("")}
                <button class="tui-action-submit" type="submit">${i(a)}</button>
            </form>
        `}function Ma(e){return String(e.submit_label||"\u6267\u884C")}function In(e){let t=String(e||"").split(".").filter(Boolean);const n=new Set(["pk","id","int","str","uuid","slug","path","bool","float","decimal","date","datetime"]),r=[];(t[0]==="auto"||t[0]==="param")&&(t=t.slice(1)),t[0]==="api"&&t[2]==="api"&&(t=t.slice(3));for(const a of t){if(n.has(a))break;r.push(a)}return r.join(".")}function W(e){if(!e)return null;const t=v(o.lastAction);return{...e,__tui_source_action_key:t?t.key:"",__tui_source_resource_base:In(t?t.key:"")}}function Wa(e,t,n){const r=String(n||"");if(!["pk","id"].includes(r))return!0;const a=String(t&&t.__tui_source_resource_base?t.__tui_source_resource_base:""),s=In(e&&e.key);return!a||!s?!0:a===s}function Ga(e,t){if(!e||!t)return!1;const n=(e.fields||[]).filter(r=>r.input_type!=="hidden");return n.length?n.some(r=>Fe(t,r,e)!==void 0):!1}async function Ja(e,t){const n={};if(!e)return n;const r=t&&t.fields||[];for(const a of r){const s=ge(e,a.key);if(!s)continue;if(a.input_type==="file"){s.files&&s.files.length&&(n[a.key]=await Qa(s.files[0]));continue}const l=Sn(a,s.value,s.checked);(a.input_type==="checkbox"||l!=="")&&(n[a.key]=l)}return n}function Qa(e){return new Promise((t,n)=>{if(e&&Number(e.size)>vr){n(new Error("\u6587\u4EF6\u8D85\u8FC7 2MB\uFF0C\u8BF7\u6539\u7528\u66F4\u5C0F\u7684\u6587\u672C\u6587\u4EF6"));return}const r=new FileReader;r.addEventListener("load",()=>t(String(r.result||""))),r.addEventListener("error",()=>n(r.error||new Error("\u6587\u4EF6\u8BFB\u53D6\u5931\u8D25"))),r.readAsText(e,"utf-8")})}function Ya(e,t={}){const{onlyIfEmpty:n=!1,silent:r=!1,focus:a=!1}=t;if(!e)return r||m("\u6CA1\u6709\u53EF\u586B\u5145\u7684\u4EFB\u52A1"),!1;const s=Dn();if(!s)return r||m("\u5148\u5728\u8868\u683C\u4E2D\u9009\u62E9\u4E00\u884C"),!1;const l=v(Ae(e));if(!l)return r||m("\u4EFB\u52A1\u672A\u627E\u5230"),!1;const u=er(s,l),d=l.fields||[];let f=0;return d.forEach(p=>{if(p.input_type==="hidden")return;const y=ge(e,p.key);if(!y||n&&(y.type==="checkbox"&&y.checked||y.type!=="checkbox"&&String(y.value||"").trim()!==""))return;const g=u[p.key];g==null||g===""||(y.type==="checkbox"?y.checked=!!g:y.value=String(g),f+=1)}),f?(r||m(`\u5DF2\u4ECE\u9009\u4E2D\u884C\u586B\u5145 ${f} \u9879`),a&&e.querySelector("input:not([type='hidden']),select,textarea")?.focus(),!0):(r||m("\u9009\u4E2D\u884C\u6CA1\u6709\u53EF\u5339\u914D\u5B57\u6BB5"),!1)}function mt(e){return Ya(e,{focus:!0})}function Fe(e,t,n){const r=typeof t=="object"&&t?t:(n&&n.fields||[]).find(l=>l.key===t)||{key:t},a=r.key,s=String(r.presentation_semantic||r.semantic||"").toLowerCase();if(!(r.input_type==="password"||["api_token","copyable_secret","secret"].includes(s))&&Wa(n,e,a))for(const l of Xa(r,n)){const u=`__raw_${l}`;if(Object.prototype.hasOwnProperty.call(e,u)&&e[u]!==void 0&&e[u]!==null&&e[u]!=="")return e[u];if(Object.prototype.hasOwnProperty.call(e,l)&&e[l]!==void 0&&e[l]!==null&&e[l]!=="")return e[l]}}function ge(e,t){if(!e||!e.elements)return null;const n=typeof e.elements.namedItem=="function"?e.elements.namedItem(t):null;return n?typeof n.length=="number"&&!n.tagName?n[0]||null:n:e.querySelector(`[name="${CSS.escape(t)}"]`)}function yt(e,t=o.screen){if(!e)return null;const n=k(e);n==="support"&&(o.showSupportTasks=!0),n==="advanced"&&(o.showAdvancedQueries=!0),o.actionFilterText="",I(t?.actions||[],t?.screen||{});const r=Wt(e);return r?.closest("details")?.setAttribute("open",""),r}function Za(e,t){const n=String(t||"").trim(),r=(e?.actions||[]).find(l=>l.key===n);if(!r||!(["read","admin"].includes(String(r.risk||"read").toLowerCase())&&String(r.method||"GET").toUpperCase()==="GET"&&!r.confirmation_required))return!1;const s=Kt();return(r.fields||[]).filter(l=>l.required).every(l=>Object.prototype.hasOwnProperty.call(s,l.key))}function gt(e,t){const n=String(t||"").trim();if(!n)return;const r=(e?.actions||[]).find(p=>p.key===n);if(!r){m("\u94FE\u63A5\u4E2D\u7684\u4EFB\u52A1\u5728\u5F53\u524D\u8D26\u53F7\u4E0B\u4E0D\u53EF\u7528");return}const a=(e?.screen?.dashboard_panels||[]).find(p=>p.action_key===n);if(a&&de(e?.screen)){const p=c.main.querySelector(`[data-dashboard-panel="${CSS.escape(a.key)}"]`);if(!p){m("\u94FE\u63A5\u4E2D\u7684\u4EFB\u52A1\u6682\u65F6\u65E0\u6CD5\u5B9A\u4F4D");return}p.scrollIntoView({block:"nearest"}),(p.querySelector("button, a, input, select, textarea")||p).focus?.(),m(`\u5DF2\u5B9A\u4F4D\u5230 ${r.label}`);return}const s=yt(r,e);if(!s){m("\u94FE\u63A5\u4E2D\u7684\u4EFB\u52A1\u6682\u65F6\u65E0\u6CD5\u5B9A\u4F4D");return}const l=Kt(),u={};(r.fields||[]).forEach(p=>{if(!(p.key in l))return;const y=ge(s,p.key);if(!(!y||["file","password"].includes(p.input_type))){if(p.input_type==="checkbox"){y.checked=["1","true","yes","on"].includes(String(l[p.key]).toLowerCase()),u[p.key]=y.checked;return}y.value=l[p.key],u[p.key]=l[p.key]}});const d=(r.fields||[]).filter(p=>p.required).every(p=>Object.prototype.hasOwnProperty.call(u,p.key));if(["read","admin"].includes(String(r.risk||"read").toLowerCase())&&String(r.method||"GET").toUpperCase()==="GET"&&!r.confirmation_required&&d){$(n,null,{params:u});return}Kn(s),m(`\u5DF2\u5B9A\u4F4D\u5230 ${r.label}`)}function Kn(e){if(!e)return;const t=()=>{e.scrollIntoView({block:"nearest",inline:"nearest"}),(e.querySelector("textarea, input:not([type='hidden']), select")||e.querySelector("button"))?.focus({preventScroll:!0})};t();const n=()=>{t(),window.setTimeout(()=>{e.scrollIntoView({block:"nearest",inline:"nearest"})},0)};typeof window.requestAnimationFrame=="function"?window.requestAnimationFrame(n):window.setTimeout(n,0)}function Dn(){const e=W(o.visibleRows[o.selectedRowIndex]);return e||(o.currentViewModel&&o.currentViewModel.kind==="datagrid"?null:o.selectedRowContext)}function Ee(){const e=Dn();c.actions.querySelectorAll("[data-action-ui-key]").forEach(t=>{const n=t.querySelector("[data-fill-from-row]");if(!n)return;const r=v(Ae(t)),a=Ga(r,e);n.disabled=!a,n.title=a?"\u4ECE\u5F53\u524D\u9009\u4E2D\u884C\u586B\u5145\u53EF\u5339\u914D\u53C2\u6570":"\u5F53\u524D\u9009\u4E2D\u884C\u6CA1\u6709\u53EF\u5339\u914D\u5B57\u6BB5"})}function Xa(e,t){const n=typeof e=="object"&&e?e:(t&&t.fields||[]).find(l=>l.key===e)||{key:e},r=String(n.key||""),a=String(n.semantic||"").trim(),s=[];return s.push(r),a&&(s.push(a),s.push(...Nn(a))),Array.isArray(n.aliases)&&s.push(...n.aliases),s.push(...Nn(r)),ht(s)}function Nn(e){const t=String(e||""),n=eo();return Array.isArray(n[t])?n[t]:[]}function eo(){return{...w.field_aliases||w.fieldAliases||{},...o.catalog&&o.catalog.field_aliases||{},...o.screen&&o.screen.field_aliases||{}}}function ht(e){return e.filter((t,n,r)=>String(t||"").trim()&&r.indexOf(t)===n)}async function S(e,t={}){const n=new AbortController,r=fn(n);try{j(),F(),c.main.innerHTML='<div class="tui-loading">\u6B63\u5728\u52A0\u8F7D\u5DE5\u4F5C\u533A...</div>',m("\u52A0\u8F7D\u5DE5\u4F5C\u533A");const a=await R(Cr(e),{signal:n.signal});return J(r)?(D(),A(a?.screen?.key)&&(o.operatorHomePayload=null,o.operatorHomePromise=null),kn(a,{...t,suppressAutoAction:!!t.deepLinkedActionKey||t.suppressAutoAction}),gt(a,t.deepLinkedActionKey||""),t.suppressHistory||Dt(a?.screen?.key||e,{replace:!!t.replaceHistory,preserveAction:!!t.preserveAction}),se(),a):null}catch(a){return!J(r)||a?.name==="AbortError"||(D(),Ze(),le(a,{retryScreenKey:e})),null}}const to=new Set(["cancelled","completed","failed","timed_out","orphaned"]);function he(e){return{accepted:"\u5DF2\u63A5\u53D7",queued:"\u5DF2\u6392\u961F",claimed:"\u5DF2\u63A5\u6536",running:"\u6267\u884C\u4E2D",waiting_approval:"\u7B49\u5F85\u5BA1\u6279",cancel_requested:"\u6B63\u5728\u53D6\u6D88",cancelled:"\u5DF2\u53D6\u6D88",completed:"\u5DF2\u5B8C\u6210",failed:"\u6267\u884C\u5931\u8D25",timed_out:"\u6267\u884C\u8D85\u65F6",orphaned:"\u6267\u884C\u8BB0\u5F55\u5F85\u6062\u590D"}[String(e||"").trim()]||"\u72B6\u6001\u5F85\u786E\u8BA4"}function no(e,t,n,r){const a=r.map(u=>String(u?.event_type||"").trim()).filter(Boolean),s=Array.isArray(e.fields)?e.fields.map(u=>({...u})):[];return new Map([["run_status",he(n)],["event_summary",a.length?a.slice(-8).join(" \u2192 "):"\u7B49\u5F85\u670D\u52A1\u5668\u7AEF Worker \u8FD4\u56DE\u8FDB\u5EA6"]]).forEach((u,d)=>{const f=s.find(p=>String(p?.key||"")===d);f&&(f.value=u)}),{...e,status:he(n),fields:s,queued_run:{...t,status:n,event_cursor:r.reduce((u,d)=>Math.max(u,Number(d?.sequence||0)),Number(t.event_cursor||0)),events:r.slice(-20)},business_summary:`\u670D\u52A1\u5668\u7AEF\u4EFB\u52A1 ${t.run_id}\uFF1A${he(n)}\u3002`}}async function ro(e,t){const n=e?.queued_run;if(!n||!n.status_url||!n.events_url)return;let r={...n},a=Array.isArray(n.events)?[...n.events]:[],s=String(n.status||"queued");const l=20;for(let u=0;u<l;u+=1){if(!J(t))return;try{const f=Number(r.event_cursor||0),p=String(r.events_url).includes("?")?"&":"?",y=await R(`${r.events_url}${p}after=${encodeURIComponent(f)}`),g=Array.isArray(y?.events)?y.events.filter(h=>h&&typeof h=="object"):[];g.length&&(a=[...a,...g])}catch{}try{const f=await R(r.status_url);if(f&&typeof f=="object"){if(f.run_id&&f.run_id!==r.run_id)throw new Error("queued run identity changed");s=String(f.status||s),r={...r,status_url:f.status_url||r.status_url,events_url:f.events_url||r.events_url,cancel_url:f.cancel_url||r.cancel_url}}}catch{m("\u670D\u52A1\u5668\u7AEF\u4EFB\u52A1\u72B6\u6001\u6682\u65F6\u4E0D\u53EF\u7528");return}const d=no(e,r,s,a);if(o.currentViewModel=d,Z(d),to.has(s)){m(`\u670D\u52A1\u5668\u7AEF\u4EFB\u52A1${he(s)}`);return}m(`\u670D\u52A1\u5668\u7AEF\u4EFB\u52A1${he(s)}`),u<l-1&&await new Promise(f=>setTimeout(f,1e3))}m("\u670D\u52A1\u5668\u7AEF\u4EFB\u52A1\u4ECD\u5728\u8FD0\u884C\uFF0C\u53EF\u7A0D\u540E\u5237\u65B0\u72B6\u6001")}async function $(e,t,n={}){const r=v(e);if(!r){m("\u4EFB\u52A1\u672A\u627E\u5230");return}const a=r.key;if(Ot(a)){oe(a);return}const s=new AbortController,l=fn(s);try{const u=String(n.dashboardResultPanelKey||"").trim(),d=String(n.dashboardRefreshPanelKey||"").trim(),f=!!u,p=!!d,y=f||p,g=n.params?{...n.params}:t?await Ja(t,r):{};if(!J(l))return;if(a==="cli.agent_queue"&&!g.client_request_id){const E=typeof crypto<"u"&&typeof crypto.randomUUID=="function"?crypto.randomUUID():`${Date.now()}-${Math.random().toString(36).slice(2)}`;g.client_request_id=`request-tui-${E}`}o.lastAction=a,o.lastParams=g,o.selectedRowIndex=0,Zt(r),j(),F(),f?(Object.prototype.hasOwnProperty.call(n,"dashboardResultPanelMarkup")||(n.dashboardResultPanelMarkup=so(u)),io(u,r)):!n.dashboardPanelKey&&!y&&(rt(r,o.screen),mn(l,r));const h={params:g,confirmed:!!n.confirmed};n.confirmation&&(h.confirmation=n.confirmation),n.reauth&&(h.reauth=n.reauth);const b=await R(Ge(a),{method:"POST",body:JSON.stringify(h),signal:s.signal});if(!J(l))return;if(D(),Array.isArray(b.missing_fields)&&b.missing_fields.length){o.lastRaw=null,!n.dashboardPanelKey&&!y&&Z(b.view_model),bt(n),Oo(b,a,g,n),N(),m("\u7B49\u5F85\u8865\u586B");return}if(b.confirmation_required){o.lastRaw=null,!n.dashboardPanelKey&&!y&&Z(b.view_model),bt(n),zo(b,a,g,n),N(),m("\u7B49\u5F85\u786E\u8BA4");return}if(b.password_challenge_required){o.lastRaw=null,!n.dashboardPanelKey&&!y&&Z(b.view_model),bt(n),Uo(b,a,g,n),N(),m("\u7B49\u5F85\u9A8C\u5BC6");return}if(as(r),o.lastRaw=b.debug?.raw_response??null,y){f&&co(u,b.view_model,r),p&&d!==u&&await oo(d),N(),m(p?"\u64CD\u4F5C\u5B8C\u6210\uFF0C\u6CBB\u7406\u5DE5\u4F5C\u533A\u5DF2\u66F4\u65B0":"\u8BE6\u60C5\u5DF2\u5728\u5F53\u524D\u9875\u9762\u6253\u5F00"),se();return}if(n.dashboardPanelKey){N(),await ao(),m("\u64CD\u4F5C\u5B8C\u6210\uFF0C\u5217\u8868\u5DF2\u5237\u65B0"),se();return}de(o.screen?.screen)||I(o.screen.actions||[],o.screen.screen),Z(b.view_model),Eo(b,b.view_model);const P=!!b.view_model?.queued_run;if(P&&await ro(b.view_model,l),N(),!P){const E=!!n.confirmed;m(E?"\u64CD\u4F5C\u5B8C\u6210":"\u8BFB\u53D6\u5B8C\u6210")}se()}catch(u){if(!J(l))return;if(u?.name==="AbortError"){m("\u8BF7\u6C42\u5DF2\u53D6\u6D88");return}D();const d=String(n.dashboardResultPanelKey||"").trim();if(d){lo(d,u);return}if(n.dashboardPanelKey){const p=(Array.isArray(o.screen?.screen?.dashboard_panels)?o.screen.screen.dashboard_panels:[]).find(g=>g.key===n.dashboardPanelKey),y=p?c.main.querySelector(`[data-dashboard-panel="${CSS.escape(p.key)}"]`):null;p&&y?(y.innerHTML=B(p,et(p,u)),H(y),tt(y,p)):le(u)}else le(u)}}async function ao(){const e=Array.isArray(o.screen?.screen?.dashboard_panels)?o.screen.screen.dashboard_panels:[];await Promise.all(e.map(t=>fe(t)))}function Y(e){return(Array.isArray(o.screen?.screen?.dashboard_panels)?o.screen.screen.dashboard_panels:[]).find(n=>n.key===e)||null}async function oo(e){const t=Y(e);t&&await fe(t)}function so(e){const t=Y(e);return(t?c.main.querySelector(`[data-dashboard-panel="${CSS.escape(t.key)}"]`):null)?.innerHTML||""}function bt(e={}){const t=String(e.dashboardResultPanelKey||"").trim();if(!t||!Object.prototype.hasOwnProperty.call(e,"dashboardResultPanelMarkup"))return;const n=Y(t),r=n?c.main.querySelector(`[data-dashboard-panel="${CSS.escape(n.key)}"]`):null;!n||!r||(r.innerHTML=e.dashboardResultPanelMarkup,me(r),pt(r,n),H(r),Be(r))}function io(e,t){const n=Y(e),r=n?c.main.querySelector(`[data-dashboard-panel="${CSS.escape(n.key)}"]`):null;!n||!r||(r.innerHTML=B(n,`<div class="tui-loading">\u6B63\u5728\u6267\u884C${i(t.label||"\u5F53\u524D\u64CD\u4F5C")}...</div>`))}function co(e,t,n){const r=Y(e),a=r?c.main.querySelector(`[data-dashboard-panel="${CSS.escape(r.key)}"]`):null;if(!r||!a)return;const s=Te(n.key),l={...r,action_key:n.key,presentation_semantic:s[0]||r.presentation_semantic};a.innerHTML=B(r,Ln(l,t)),me(a),H(a),pt(a,l),Be(a)}function lo(e,t){const n=Y(e),r=n?c.main.querySelector(`[data-dashboard-panel="${CSS.escape(n.key)}"]`):null;if(!n||!r){le(t);return}r.innerHTML=B(n,et(n,t)),H(r),tt(r,n)}function Z(e){if(!e){qo("\u6CA1\u6709\u8FD4\u56DE\u53EF\u6E32\u67D3\u7684\u4E1A\u52A1\u89C6\u56FE\u3002");return}o.currentViewModel=e,Ce(e.kind||"message"),c.mainTitle.textContent=(e.title||"\u89C6\u56FE").toUpperCase(),po(e,c.main)?st({preserveRowContext:!0}):e.kind==="datagrid"?fo(e):(st({preserveRowContext:!0}),uo(e)),Po(),me(c.main),e.kind!=="datagrid"&&we(e.pager||null),Ee()}function uo(e){if(jn(e)){zn(e);return}({detail:To,chart:ho,image:bo,kpi_trend:wo,table_chart:So,host_slot:ko,custom:zn,message:Yn}[e.kind]||Yn)(e)}function po(e,t){const n=String(e.renderer||"").trim();if(!n||We.has(n))return!1;const r=ne.get(n);if(!r)return!1;t.innerHTML=`
            <div class="tui-view-status">${i(e.status||"\u6B63\u5E38")} / ${i(e.title||n)}</div>
            ${be(e)}
            <div class="tui-extension-host" data-renderer="${i(n)}"></div>
        `;const a=t.querySelector(".tui-extension-host");try{r({viewModel:e,container:a,runtimeConfig:w,escapeHtml:i})}catch{a.innerHTML=T("\u6269\u5C55\u89C6\u56FE\u6682\u65F6\u4E0D\u53EF\u7528\u3002",["\u8BF7\u7A0D\u540E\u91CD\u8BD5\uFF0C\u6216\u6539\u7528\u9ED8\u8BA4\u4EFB\u52A1\u67E5\u770B\u6570\u636E\u3002"])}return!0}function jn(e){const t=String(e.renderer||"").trim();return!t||We.has(t)?!1:["chart","kpi_trend","table_chart","host_slot","custom"].includes(e.kind)}function fo(e){o.currentViewModel=e,o.currentColumns=e.columns||[],o.currentRows=e.rows||[],o.clientPage=1,qe(!1)}function mo(e){const t=o.filterText.trim().toLowerCase();return t?Object.values(e||{}).some(n=>String(n??"").toLowerCase().includes(t)):!0}function qe(e){if(!o.currentViewModel||o.currentViewModel.kind!=="datagrid"){e&&m("\u5F53\u524D\u89C6\u56FE\u4E0D\u53EF\u7B5B\u9009");return}e&&(o.clientPage=1),o.visibleRows=o.currentRows.filter(mo),o.selectedRowIndex=Math.min(o.selectedRowIndex,Math.max(0,o.visibleRows.length-1)),On(),e&&m(o.filterText?`\u7B5B\u9009 ${o.visibleRows.length}/${o.currentRows.length}`:"\u7B5B\u9009\u5DF2\u6E05\u9664")}function On(){const e=o.currentViewModel,t=o.currentColumns,n=o.visibleRows,r=!e.pager&&typeof _.clientPage=="function"?_.clientPage(n,o.clientPage,o.clientPageSize):{rows:n,pager:null},a=r.rows,s=e.pager||r.pager;o.lastPager=s;const l=r.pager?(r.pager.page-1)*o.clientPageSize:0,u=o.filterText?` / \u7B5B\u9009: ${o.filterText} (${n.length}/${o.currentRows.length})`:"",d=o.filterText?"\u6CA1\u6709\u5339\u914D\u7684\u8BB0\u5F55\u3002":e.empty_message||"\u6682\u65E0\u53EF\u663E\u793A\u6570\u636E\u3002",f=a.length&&t.length?`
                <table>
                    <thead>
                        <tr>${t.map(p=>`<th>${i(p.label)}</th>`).join("")}</tr>
                    </thead>
                    <tbody>
                        ${a.map((p,y)=>{const g=l+y;return`
                            <tr data-row-index="${g}" class="${g===o.selectedRowIndex?"is-selected":""}">
                                ${t.map(h=>{const b=q(p[h.key]);return`<td class="${ft(b,h.label||h.key)}" title="${i(b)}">${i(b)}</td>`}).join("")}
                            </tr>
                        `}).join("")}
                    </tbody>
                </table>
            `:T(d,o.filterText?["\u6E05\u7A7A\u7B5B\u9009\u540E\u67E5\u770B\u5168\u90E8\u8BB0\u5F55\u3002"]:e.empty_guidance,o.filterText?[]:e.next_steps);c.main.innerHTML=`
            <div class="tui-view-status">${i(e.status)} / ${i(e.title)}${i(u)}</div>
            ${be(e)}
            <div class="tui-datagrid" role="grid" tabindex="0" aria-label="${i(e.title)}">
                ${f}
            </div>
            ${yo(s)}
        `,c.main.querySelectorAll("[data-row-index]").forEach(p=>{p.addEventListener("click",()=>Xn(Number(p.dataset.rowIndex||0))),p.addEventListener("dblclick",()=>At())}),c.main.querySelectorAll("[data-page-delta]").forEach(p=>{p.addEventListener("click",()=>_t(Number(p.dataset.pageDelta||0)))}),wt(c.main,e.next_steps),a.length?((o.selectedRowIndex<l||o.selectedRowIndex>=l+a.length)&&(o.selectedRowIndex=l),l===0?o.selectedRowContext=W(a[o.selectedRowIndex]):o.selectedRowContext=W(o.visibleRows[o.selectedRowIndex])):o.selectedRowContext=null,we(s),vt(),Ee()}function yo(e){if(!e)return"";const t=e.page??"-",n=e.total_pages??"-",r=e.total_rows??0;return`
            <div class="tui-datagrid-pager" aria-label="\u5206\u9875">
                <button type="button" data-page-delta="-1" ${e.has_previous?"":"disabled"}>\u4E0A\u4E00\u9875</button>
                <span>\u7B2C ${i(t)} / ${i(n)} \u9875</span>
                <span>\u5171 ${i(r)} \u884C</span>
                <button type="button" data-page-delta="1" ${e.has_next?"":"disabled"}>\u4E0B\u4E00\u9875</button>
            </div>
        `}function T(e,t,n=[]){const r=(t||[]).filter(Boolean),a=Array.isArray(n)?n:[];return`
            <div class="tui-empty-state tui-empty-guidance">
                <strong>${i(e)}</strong>
                ${r.length?`
                    <ul>
                        ${r.map(s=>`<li>${i(s)}</li>`).join("")}
                    </ul>
                `:""}
                ${a.length?`
                    <div class="tui-entry-actions">
                        ${a.map((s,l)=>`
                            <button type="button" data-next-step-index="${l}">
                                ${i(s.label||"\u7EE7\u7EED")}
                            </button>
                        `).join("")}
                    </div>
                `:""}
            </div>
        `}function wt(e,t){e.querySelectorAll("[data-next-step-index]").forEach(n=>{n.addEventListener("click",()=>{const r=Number(n.dataset.nextStepIndex||0);go((t||[])[r])})})}function go(e){if(e){if(e.action_key){const t=e.params&&typeof e.params=="object"?{...e.params}:{};$(e.action_key,null,{params:t});return}if(e.screen_key){S(e.screen_key);return}m(e.hint||"\u5DF2\u8BB0\u5F55\u4E0B\u4E00\u6B65")}}function ho(e){X(e,"\u56FE\u8868",St)}function bo(e){X(e,"\u56FE\u7247",Un)}function wo(e){X(e,"\u6307\u6807\u8D8B\u52BF",Mn)}function So(e){X(e,"\u8868\u683C\u56FE\u8868",Wn)}function ko(e){X(e,"\u5BBF\u4E3B\u63D2\u69FD",Gn),Be(c.main)}function zn(e){X(e,"\u81EA\u5B9A\u4E49\u89C6\u56FE",kt)}function X(e,t,n){c.main.innerHTML=`
            <div class="tui-view-status">${i(e.status||"\u6B63\u5E38")} / ${i(e.title||t)}</div>
            ${be(e)}
            ${n(e)}
        `}function St(e,t={}){const n=!!t.compact,r=String(e.chart_type||e.renderer||"line").toLowerCase(),a=Jn(e);if(!a.flatMap(d=>d.points).length)return T(e.empty_message||"\u6682\u65E0\u56FE\u8868\u6570\u636E\u3002",e.empty_guidance,e.next_steps);const l=r==="pie"?Lo(a[0].points):r==="bar"?Co(a[0].points):xo(a),u=r==="line"?a.map((d,f)=>{const p=d.points[d.points.length-1];return`
                    <span class="tui-chart-series-legend">
                        <i class="series-${f%6}"></i>
                        ${i(d.label)} ${i(ee(p.value))}
                    </span>
                `}).join(""):a[0].points.slice(0,n?4:8).map(d=>`
                <span><i></i>${i(d.label)} ${i(ee(d.value))}</span>
            `).join("");return`
            <section class="tui-rich-view tui-chart-view ${n?"is-compact":""}">
                <div class="tui-rich-header">
                    <strong>${i(e.title||"Chart")}</strong>
                    <span>${i(r.toUpperCase())}</span>
                </div>
                ${l}
                <div class="tui-chart-legend">${u}</div>
                ${_o(a,e)}
            </section>
        `}function Un(e,t={}){const n=$o(e);if(!n)return T(e.empty_message||"\u6682\u65E0\u56FE\u7247\u94FE\u63A5\u3002",[]);const r=String(e.alt||e.caption||e.title||"Image"),a=String(e.caption||""),s=String(e.title||"Image");return`
            <figure class="tui-rich-view tui-image-view ${t.compact?"is-compact":""}">
                <div class="tui-rich-header">
                    <strong>${i(s)}</strong>
                    <span>IMAGE</span>
                </div>
                <button class="tui-image-frame" type="button"
                        data-image-preview
                        data-image-src="${i(n)}"
                        data-image-alt="${i(r)}"
                        data-image-caption="${i(a)}"
                        data-image-title="${i(s)}">
                    <img src="${i(n)}" alt="${i(r)}" loading="lazy" decoding="async">
                </button>
                ${a?`<figcaption>${i(a)}</figcaption>`:""}
            </figure>
        `}function $o(e){const t=[e.url,e.src,e.image_url,e.imageUrl,e.href];for(const n of t){const r=Vn(n);if(r)return r}return""}function Vn(e){const t=String(e||"").trim();if(!t)return"";try{const n=new URL(t,window.location.href);if(n.protocol==="http:"||n.protocol==="https:"||n.protocol==="data:"&&/^data:image\/(?:apng|avif|gif|jpe?g|png|webp);/i.test(t)||n.protocol==="data:"&&Ar&&/^data:image\/svg\+xml(?:[;,]|$)/i.test(t))return t}catch{return""}return""}function Mn(e,t={}){const n=(e.trend||[]).map($t).filter(Boolean),r=n.map(f=>f.value),a=Number.parseFloat(e.value);if(!r.length&&!Number.isFinite(a))return`
                <div class="tui-panel-placeholder tui-contract-error" data-render-contract-error="kpi_trend">
                    <div>\u6307\u6807\u7ED3\u679C\u6570\u636E\u4E0D\u5B8C\u6574\uFF0C\u5DF2\u505C\u6B62\u5C55\u793A\u5360\u4F4D\u6570\u503C\u3002</div>
                    <small>\u8BF7\u5237\u65B0\u540E\u91CD\u8BD5\uFF1B\u82E5\u6301\u7EED\u51FA\u73B0\uFF0C\u8BF7\u68C0\u67E5\u6570\u636E\u540C\u6B65\u4E0E\u7ED3\u679C\u6295\u5F71\u3002</small>
                </div>
            `;const s=r.length?r[0]:a,l=r.length?r[r.length-1]:a,u=l-s,d=u>=0?"is-up":"is-down";return`
            <section class="tui-rich-view tui-kpi-view ${t.compact?"is-compact":""}">
                <div class="tui-kpi-main">
                    <span>${i(e.label||e.title||"KPI")}</span>
                    <strong>${i(V(e.value)?e.value:ee(l))}</strong>
                    <em class="${d}">${u>=0?"+":""}${i(ee(u))}</em>
                </div>
                ${n.length?`<div class="tui-kpi-spark">${Ao(n,{spark:!0})}</div>`:""}
            </section>
        `}function Wn(e,t={}){const n=e.chart||{},r=e.table||{};return`
            <section class="tui-rich-view tui-table-chart-view ${t.compact?"is-compact":""}">
                ${St({...n,title:n.title||e.title},{compact:t.compact})}
                <div class="tui-table-chart-grid">
                    ${Pn({max_rows:t.compact?4:10,columns:r.columns||[]},r)}
                </div>
            </section>
        `}function Gn(e,t={}){const n=!!w.allowHostHtmlSlots,r=String(e.partial_html||""),a=e.fallback_message||"\u5BBF\u4E3B\u63D2\u69FD\u5185\u5BB9\u7531\u5BBF\u4E3B\u5E94\u7528\u63A7\u5236\u3002";return!n||!r?`
                <section class="tui-rich-view tui-host-slot ${t.compact?"is-compact":""}">
                    <div class="tui-rich-header">
                        <strong>${i(e.slot_key||e.title||"host-slot")}</strong>
                        <span>HOST SLOT</span>
                    </div>
                    ${T(a,n?[]:["\u5F53\u524D runtime \u672A\u5F00\u542F allowHostHtmlSlots\u3002"])}
                </section>
            `:`
            <section class="tui-rich-view tui-host-slot ${t.compact?"is-compact":""}" data-host-slot="${i(e.slot_key||"")}">
                ${r}
            </section>
        `}function Be(e){w.allowHostHtmlSlots&&window.htmx&&typeof window.htmx.process=="function"&&e.querySelectorAll(".tui-host-slot").forEach(t=>window.htmx.process(t))}function kt(e){const t=String(e.renderer||"").trim()||"custom";return T(e.fallback_message||`\u6CA1\u6709\u6CE8\u518C renderer: ${t}`,["\u5BBF\u4E3B\u53EF\u4EE5\u901A\u8FC7 window.AgomTUIRenderers.register(name, rendererFn) \u6CE8\u518C\u6269\u5C55\u3002"])}function vo(e){return Jn(e)[0]?.points||[]}function Jn(e){const n=(Array.isArray(e.series)?e.series:[]).filter(a=>Array.isArray(a?.points)).map((a,s)=>({key:String(a.key||`series-${s+1}`),label:String(a.label||a.name||`\u5E8F\u5217 ${s+1}`),points:a.points.map($t).filter(Boolean)})).filter(a=>a.points.length);if(n.length)return n;const r=(Array.isArray(e.points)?e.points:[]).map($t).filter(Boolean);return r.length?[{key:"value",label:String(e.label||e.title||"\u6570\u503C"),points:r}]:[]}function _o(e,t){const n=String(t.x_axis_label||"\u6A2A\u8F74");return`
            <dl class="tui-chart-accessible-summary" aria-label="\u56FE\u8868\u6587\u672C\u6458\u8981">
                <div><dt>\u6A2A\u8F74</dt><dd>${i(n)}</dd></div>
                ${e.map(r=>{const a=r.points[0],s=r.points[r.points.length-1];return`
                        <div>
                            <dt>${i(r.label)}</dt>
                            <dd>${i(a.label)} ${i(ee(a.value))}
                                \u81F3 ${i(s.label)} ${i(ee(s.value))}</dd>
                        </div>
                    `}).join("")}
            </dl>
        `}function $t(e,t=0){if(e==null)return null;if(typeof e=="number")return{label:String(t+1),value:e};const n=Number.parseFloat(e.value??e.y??e.count??e.total);return Number.isFinite(n)?{label:String(e.label??e.x??e.name??t+1),value:n}:null}function Qn(e,t,n,r){const a=e.map(d=>d.value),s=Math.min(0,...a),u=Math.max(1,...a)-s||1;return{x(d){return e.length<=1?t/2:r+d/(e.length-1)*(t-r*2)},y(d){return n-r-(d-s)/u*(n-r*2)}}}function Ao(e,t={}){const n=t.spark?240:640,r=t.spark?72:220,a=t.spark?8:28,s=Qn(e,n,r,a),l=e.map((u,d)=>`${d===0?"M":"L"}${s.x(d).toFixed(1)} ${s.y(u.value).toFixed(1)}`).join(" ");return`
            <svg class="tui-chart-svg ${t.spark?"is-spark":""}" viewBox="0 0 ${n} ${r}" aria-hidden="true">
                <path class="tui-chart-gridline" d="M${a} ${r-a}H${n-a}"></path>
                <path class="tui-chart-line" d="${i(l)}"></path>
                ${e.map((u,d)=>`<circle class="tui-chart-point" cx="${s.x(d).toFixed(1)}" cy="${s.y(u.value).toFixed(1)}" r="${t.spark?2:3}"></circle>`).join("")}
            </svg>
        `}function xo(e){const a=e.flatMap(d=>d.points),s=[...new Set(a.map(d=>d.label))],l=Qn(a,640,220,28),u=d=>s.length<=1?640/2:28+Math.max(0,s.indexOf(d))/(s.length-1)*584;return`
            <svg class="tui-chart-svg" viewBox="0 0 640 220" aria-hidden="true">
                <path class="tui-chart-gridline" d="M28 192H612"></path>
                ${e.map((d,f)=>{const p=d.points.map((y,g)=>`${g===0?"M":"L"}${u(y.label).toFixed(1)} ${l.y(y.value).toFixed(1)}`).join(" ");return`
                        <path class="tui-chart-line series-${f%6}" d="${i(p)}"></path>
                        ${d.points.map(y=>`<circle class="tui-chart-point series-${f%6}" cx="${u(y.label).toFixed(1)}" cy="${l.y(y.value).toFixed(1)}" r="3"></circle>`).join("")}
                    `}).join("")}
            </svg>
        `}function Co(e){const a=e.map(g=>g.value),s=Math.max(0,...a),l=Math.min(0,...a),u=s-l||1,d=g=>192-(g-l)/u*164,f=d(0),p=8,y=Math.max(8,(584-p*(e.length-1))/e.length);return`
            <svg class="tui-chart-svg" viewBox="0 0 640 220" aria-hidden="true">
                <path class="tui-chart-gridline" d="M28 ${f.toFixed(1)}H612"></path>
                ${e.map((g,h)=>{const b=28+h*(y+p),P=d(g.value),E=Math.min(f,P),Ne=Math.max(2,Math.abs(P-f));return`<rect class="tui-chart-bar" x="${b.toFixed(1)}" y="${E.toFixed(1)}" width="${y.toFixed(1)}" height="${Ne.toFixed(1)}"></rect>`}).join("")}
            </svg>
        `}function Lo(e){const t=e.reduce((a,s)=>a+Math.max(0,s.value),0)||1;let n=0;return`
            <svg class="tui-chart-svg tui-chart-pie" viewBox="0 0 200 200" aria-hidden="true">
                ${e.map((a,s)=>{const u=Math.max(0,a.value)/t*100,d=`<circle class="tui-chart-pie-slice slice-${s%6}" r="70" cx="100" cy="100" pathLength="100" stroke-dasharray="${u} ${100-u}" stroke-dashoffset="${-n}"></circle>`;return n+=u,d}).join("")}
                <circle class="tui-chart-pie-hole" r="38" cx="100" cy="100"></circle>
            </svg>
        `}function ee(e){if(e==null||String(e).trim()==="")return"-";const t=Number(e);return Number.isFinite(t)?Math.abs(t)>=100?t.toFixed(0):t.toFixed(2).replace(/\.00$/,""):String(e??"-")}function To(e){const t=Ea(),n=t.length?Rn(e,t):En(e.fields||[]),r=!n,a=t.length?[]:e.nested||[];c.main.innerHTML=`
            <div class="tui-view-status">${i(e.status)} / ${i(e.title)}</div>
            ${be(e)}
            ${n||T(e.empty_message||"\u6682\u65E0\u6458\u8981\u6570\u636E\u3002",e.empty_guidance,e.next_steps)}
            ${a.length?`
                <div class="tui-nested-list">
                    ${a.map(s=>`<span>${i(s.label)}: ${i(s.count)} \u884C</span>`).join("")}
                </div>
            `:""}
            ${!r&&Array.isArray(e.next_steps)&&e.next_steps.length?T("\u5EFA\u8BAE\u4E0B\u4E00\u6B65",[],e.next_steps):""}
        `,wt(c.main,e.next_steps)}function Yn(e){const t=Array.isArray(e.sections)?e.sections:[],n=t.length?t.map(r=>`
                <section class="tui-message-section">
                    <h4>${i(r.title||"\u6458\u8981")}</h4>
                    ${(r.body||[]).map(a=>`<p>${i(a)}</p>`).join("")}
                    ${(r.rows||[]).length?`
                        <dl class="tui-message-fields">
                            ${r.rows.map(a=>`
                                <dt>${i(a.label)}</dt>
                                <dd>${i(a.value)}</dd>
                            `).join("")}
                        </dl>
                    `:""}
                </section>
            `).join(""):`<div class="tui-message">${i(e.message||"")}</div>`;c.main.innerHTML=`
            <div class="tui-view-status">${i(e.status||"\u6B63\u5E38")} / ${i(e.title||"\u6D88\u606F")}</div>
            ${be(e)}
            <div class="tui-message-list">${n}</div>
            ${Array.isArray(e.next_steps)&&e.next_steps.length?T("\u5EFA\u8BAE\u4E0B\u4E00\u6B65",[],e.next_steps):""}
        `,wt(c.main,e.next_steps)}function be(e){const t=o.screen?.screen||{},n=t.business_context||{};if(!n.decision_output&&!n.objective&&!e?.business_summary)return"";const a=(t.workflow||{}).next||{},s=o.screen&&o.screen.actions||[],l=ye(s),u=Ro(e),f=[["\u5224\u65AD\u4EA7\u51FA",String(e?.business_summary||"").trim()||n.decision_output||n.objective],["\u5F53\u524D\u8BC1\u636E",u]];e?.blocking_reason&&f.push(["\u5F53\u524D\u963B\u65AD",e.blocking_reason]);const p=[];l.operation&&f.push(["\u53EF\u6267\u884C\u64CD\u4F5C",`${l.operation} \u9879\uFF0C\u63D0\u4EA4\u524D\u786E\u8BA4`]);const y=Ke(s);y.total&&f.push(["\u672C\u5C4F\u8FDB\u5EA6",`${y.completed}/${y.total}`]);const g=Lt();return g&&(f.push(["\u672C\u5C4F\u4E0B\u4E00\u9879",g.label]),p.push({command:"next-primary",label:g.label,key:"F6",title:"\u8FD0\u884C\u4E0B\u4E00\u4E3B\u6D41\u7A0B"})),a.label&&(f.push(["\u4E0B\u4E00\u6B65",a.label]),p.push({command:"workflow-next",label:a.label,key:"F4",title:"\u8FDB\u5165\u6D41\u7A0B\u4E0B\u4E00\u5C4F"})),`
            <section class="tui-decision-cue">
                ${f.map(([h,b])=>`
                    <div>
                        <span>${i(h)}</span>
                        <strong>${i(b)}</strong>
                    </div>
                `).join("")}
                ${p.length?`
                    <div class="tui-decision-actions">
                        <span>\u7EE7\u7EED</span>
                        <strong>
                            ${p.map(h=>`
                                <button type="button" data-decision-action="${i(h.command)}">
                                    ${i(h.title)}: ${i(h.label)}
                                    <kbd>${i(h.key)}</kbd>
                                </button>
                            `).join("")}
                        </strong>
                    </div>
                `:""}
            </section>
        `}function Po(){c.main.querySelectorAll("[data-decision-action]").forEach(e=>{e.addEventListener("click",()=>{const t=e.dataset.decisionAction;t==="next-primary"?dr():t==="workflow-next"&&Ct(1)})})}function Ro(e){if(!e)return"\u5C1A\u672A\u8FD4\u56DE\u4E1A\u52A1\u89C6\u56FE";if(e.kind==="datagrid"){const n=e.pager?.total_rows??o.currentRows.length;return o.filterText?`\u7B5B\u9009\u540E ${o.visibleRows.length}/${o.currentRows.length} \u884C`:`\u8868\u683C ${o.currentRows.length}/${n} \u884C`}if(e.kind==="detail"){const n=(e.fields||[]).length,r=(e.nested||[]).reduce((a,s)=>a+Number(s.count||0),0);return r?`\u8BE6\u60C5 ${n} \u9879\uFF0C\u5173\u8054 ${r} \u884C`:`\u8BE6\u60C5 ${n} \u9879`}if(e.kind==="chart")return`\u56FE\u8868 ${vo(e).length} \u70B9`;if(e.kind==="kpi_trend"){const n=(e.trend||[]).length;return n?`\u6307\u6807\u8D8B\u52BF ${n} \u70B9`:"\u6307\u6807\u8D8B\u52BF"}if(e.kind==="table_chart")return`\u56FE\u8868\u8868\u683C ${e.table?.rows?.length||0} \u884C`;if(e.kind==="host_slot")return"\u5BBF\u4E3B\u63D2\u69FD";if(e.kind==="custom")return`\u81EA\u5B9A\u4E49 ${e.renderer||"renderer"}`;const t=(e.sections||[]).length;return t?`\u6D88\u606F ${t} \u6BB5`:"\u6D88\u606F\u7ED3\u679C"}function te(e){const t=Array.isArray(e.sections)?e.sections:[],n=Zn(e.rows||[]),r=x(e.body||"").split(/\n+/).map(s=>s.trim()).filter(Boolean),a=x(e.rowsTitle||"\u6D41\u7A0B\u72B6\u6001");c.inspector.innerHTML=`
            <section class="tui-inspector-card tui-inspector-summary">
                <div class="tui-inspector-title">${i(e.title||"\u8BF4\u660E")}</div>
                ${r.map(s=>`<p>${i(s)}</p>`).join("")}
            </section>
            ${n.length?`
                <section class="tui-inspector-card">
                    <div class="tui-inspector-title">${i(a)}</div>
                    <dl class="tui-inspector-grid">
                        ${n.map(s=>`
                            <dt>${i(s.label)}</dt>
                            <dd>${i(s.value)}</dd>
                        `).join("")}
                    </dl>
                </section>
            `:""}
            ${t.length?`
                <div class="tui-inspector-sections">
                    ${t.map(s=>`
                        <section class="tui-message-section">
                            <h4>${i(x(s.title||"\u6458\u8981"))}</h4>
                            ${(s.body||[]).map(l=>`<p>${i(x(l))}</p>`).join("")}
                            ${(s.actions||[]).length?`
                                <div class="tui-inspector-actions">
                                    ${s.actions.map(l=>`
                                        <button type="button" data-inspector-action="${i(l.ui_key)}">
                                            <span>${i(l.label)}</span>
                                            <kbd>${i(l.verb)}</kbd>
                                        </button>
                                    `).join("")}
                                </div>
                            `:""}
                            ${(s.rows||[]).length?`
                                <dl class="tui-message-fields">
                                    ${Zn(s.rows).map(l=>`
                                        <dt>${i(l.label)}</dt>
                                        <dd>${i(l.value)}</dd>
                                    `).join("")}
                                </dl>
                            `:""}
                        </section>
                    `).join("")}
                </div>
            `:""}
        `,c.inspector.querySelectorAll("[data-inspector-action]").forEach(s=>{s.addEventListener("click",()=>Ho(s.dataset.inspectorAction))})}function Zn(e){return(e||[]).map(t=>Array.isArray(t)?{label:t[0],value:t[1]}:{label:t.label,value:t.value}).filter(t=>t.label!==void 0&&t.value!==void 0).map(t=>({label:x(t.label),value:x(t.value)}))}function Fo(e){const t=Ke(),n=Lt(),r=(o.screen&&o.screen.actions||[]).filter(s=>k(s)==="operation").length,a=[["\u64CD\u4F5C\u65B9\u5F0F",ce(e.action)],["\u672C\u5C4F\u8FDB\u5EA6",`${t.completed}/${t.total}`]];return n&&n.key!==e.action.key&&a.push(["\u4E0B\u4E00\u9879",n.label]),r&&a.push(["\u53EF\u6267\u884C\u64CD\u4F5C",`${r} \u9879`]),e.action.confirmation_required&&a.push(["\u786E\u8BA4\u7B56\u7565","\u63D0\u4EA4\u524D\u4F1A\u8981\u6C42\u786E\u8BA4"]),a}function Eo(e,t){const n=o.screen?.screen?.business_context||{},r=ct(n),a=(o.screen&&o.screen.actions||[]).filter(u=>k(u)==="operation").slice(0,5).map(u=>`${u.label} / ${ce(u)}`),s=Fo(e),l=[...r,...a.length?[{title:"\u540E\u7EED\u52A8\u4F5C",body:a,rows:[]}]:[]];if(!t){te({title:e.action.label,body:e.action.description||"",rows:s,sections:l});return}if(t.kind==="detail"){te({title:"\u64CD\u4F5C\u8BF4\u660E",body:e.action.description||"\u4E2D\u95F4\u4E3B\u9762\u677F\u663E\u793A\u5B8C\u6574\u4E1A\u52A1\u660E\u7EC6\uFF0C\u53F3\u680F\u53EA\u4FDD\u7559\u6D41\u7A0B\u3001\u8BC1\u636E\u4E0E\u540E\u7EED\u52A8\u4F5C\u3002",rowsTitle:"\u6D41\u7A0B\u72B6\u6001",rows:s,sections:[{title:"\u9605\u8BFB\u63D0\u793A",body:["\u5B8C\u6574\u4E1A\u52A1\u660E\u7EC6\u5DF2\u5728\u4E2D\u95F4\u4E3B\u9762\u677F\u663E\u793A\u3002\u53F3\u680F\u4E0D\u518D\u91CD\u590D\u6E32\u67D3\u540C\u4E00\u5BF9\u8C61\u3002"],rows:[]},...l]});return}if(t.kind==="message"){te({title:"\u64CD\u4F5C\u8BF4\u660E",body:e.action.description||"\u4E2D\u95F4\u4E3B\u9762\u677F\u663E\u793A\u5F53\u524D\u7ED3\u679C\u8BF4\u660E\uFF0C\u53F3\u680F\u4FDD\u7559\u5BFC\u822A\u4E0E\u540E\u7EED\u52A8\u4F5C\u3002",rowsTitle:"\u6D41\u7A0B\u72B6\u6001",rows:s,sections:[{title:"\u9605\u8BFB\u63D0\u793A",body:["\u7ED3\u679C\u8BF4\u660E\u5DF2\u5728\u4E2D\u95F4\u4E3B\u9762\u677F\u663E\u793A\u3002\u53F3\u680F\u4FDD\u7559\u6D41\u7A0B\u5BFC\u822A\u3001\u4E1A\u52A1\u76EE\u6807\u4E0E\u540E\u7EED\u52A8\u4F5C\u3002"],rows:[]},...l]});return}vt([...s,...a.slice(0,3).map((u,d)=>[`\u53EF\u6267\u884C\u52A8\u4F5C ${d+1}`,u])])}function qo(e){c.main.innerHTML=`<div class="tui-error">${i(e)}</div>`,we(null),m("\u9519\u8BEF")}function we(e){if(o.lastPager=e,!e){c.pager.textContent="",c.pager.hidden=!0;return}c.pager.hidden=!1,c.pager.textContent=`\u9875 ${e.page}/${e.total_pages} | ${e.total_rows} \u884C | ${e.has_previous?"PgUp":"--"} / ${e.has_next?"PgDn":"--"}`}function N(){c.rawPanel.textContent=o.lastRaw===null?"\u5C1A\u672A\u52A0\u8F7D\u539F\u59CB\u54CD\u5E94\u3002":JSON.stringify(o.lastRaw,null,2)}function He(e){c.rawDrawer.hidden=typeof e=="boolean"?!e:!c.rawDrawer.hidden,m(c.rawDrawer.hidden?"\u539F\u59CB\u54CD\u5E94\u5173\u95ED":"\u539F\u59CB\u54CD\u5E94\u6253\u5F00")}function Xn(e){o.selectedRowIndex=e,c.main.querySelectorAll("[data-row-index]").forEach(n=>{n.classList.toggle("is-selected",Number(n.dataset.rowIndex||0)===e)});const t=o.visibleRows[e];o.selectedRowContext=W(t),t&&(m(`\u884C ${e+1}/${o.visibleRows.length}`),vt()),Ee()}function vt(e=[]){if(!o.currentViewModel||o.currentViewModel.kind!=="datagrid")return;const t=o.visibleRows[o.selectedRowIndex],n=t?dn(t,14):[["\u72B6\u6001",o.filterText?"\u6CA1\u6709\u5339\u914D\u8BB0\u5F55":"\u6682\u65E0\u8BB0\u5F55"]],r=W(t),a=r?Bo(r):[],s=[];a.length&&s.push({title:"\u9009\u4E2D\u884C\u53EF\u505A",body:["\u76F4\u63A5\u4F7F\u7528\u9009\u4E2D\u8BB0\u5F55\u586B\u5165\u53C2\u6570\u3002"],actions:a.map(l=>({ui_key:U(l),label:l.label,verb:ce(l)})),rows:[]}),s.push({title:"\u952E\u76D8\u64CD\u4F5C",body:["\u65B9\u5411\u952E\u79FB\u52A8\uFF0CEnter \u6253\u5F00\u8BE6\u60C5\uFF0CF7 \u7B5B\u9009\uFF0CF9 \u8FDB\u5165\u4EFB\u52A1\u533A\uFF0CF8 \u5BFC\u51FA\u3002"],rows:[]}),te({title:t?`\u9009\u4E2D\u8BB0\u5F55 ${o.selectedRowIndex+1}/${o.visibleRows.length}`:"\u8868\u683C\u72B6\u6001",body:o.currentViewModel.title||"",rows:[...e,...n],sections:s})}function Bo(e){return(o.screen&&o.screen.actions||[]).filter(n=>{const r=(n.fields||[]).filter(a=>a.input_type!=="hidden");return r.length?r.some(a=>Fe(e,a,n)!==void 0):!1}).sort((n,r)=>{const a={operation:0,advanced:1,primary:2,support:3};return(a[k(n)]??9)-(a[k(r)]??9)||Number(n.sequence||999)-Number(r.sequence||999)}).slice(0,5)}function er(e,t){const n={};return(t&&t.fields||[]).forEach(a=>{if(a.input_type==="hidden")return;const s=Fe(e,a,t);s!=null&&s!==""&&(n[a.key]=s)}),n}function Ho(e){const t=W(o.visibleRows[o.selectedRowIndex]),n=v(e);if(!t||!n){m("\u6CA1\u6709\u53EF\u6267\u884C\u7684\u9009\u4E2D\u884C\u4EFB\u52A1");return}const r=er(t,n),a=(n.fields||[]).filter(s=>s.required&&!s.default&&s.input_type!=="hidden").filter(s=>r[s.key]===void 0||r[s.key]===null||String(r[s.key]).trim()==="");if(a.length){m(`\u9009\u4E2D\u884C\u7F3A\u5C11\u53C2\u6570: ${a.map(s=>s.label).join(", ")}`);return}$(n.key,null,{params:r})}function tr(e){const t=c.main.querySelectorAll("[data-row-index]");if(!t.length)return;const n=Number(t[0].dataset.rowIndex||0),r=Number(t[t.length-1].dataset.rowIndex||0),a=Math.max(n,Math.min(r,o.selectedRowIndex+e));Xn(a),c.main.querySelector(`[data-row-index="${a}"]`)?.scrollIntoView({block:"nearest"})}async function _t(e){if(o.lastPager?.client_side){if(e<0&&!o.lastPager.has_previous){m("\u5DF2\u7ECF\u662F\u7B2C\u4E00\u9875");return}if(e>0&&!o.lastPager.has_next){m("\u5DF2\u7ECF\u662F\u6700\u540E\u4E00\u9875");return}o.clientPage=Math.max(1,o.clientPage+e),o.selectedRowIndex=(o.clientPage-1)*o.clientPageSize,On(),m(`\u7B2C ${o.clientPage} \u9875`);return}if(o.pendingController){m("\u7FFB\u9875\u4E2D\uFF0C\u8BF7\u7A0D\u5019");return}if(!o.lastAction||!o.lastPager){m("\u5F53\u524D\u89C6\u56FE\u4E0D\u53EF\u7FFB\u9875");return}const t=v(o.lastAction);if(!t){m("\u4EFB\u52A1\u672A\u627E\u5230");return}if(e<0&&!o.lastPager.has_previous){m("\u5DF2\u7ECF\u662F\u7B2C\u4E00\u9875");return}if(e>0&&!o.lastPager.has_next){m("\u5DF2\u7ECF\u662F\u6700\u540E\u4E00\u9875");return}const n=Io(t,o.lastPager,o.lastParams,e);if(!n){m("\u5F53\u524D\u5206\u9875\u53C2\u6570\u4E0D\u53EF\u63A8\u65AD");return}await $(o.lastAction,null,{params:{...o.lastParams,...n}})}function Io(e,t,n,r){const a=e.pagination||{},s=String(t.pagination_mode||t.mode||""),l=a.mode||(s==="limit_offset"?"offset":s)||Ko(e);if(l==="cursor"){const h=a.cursor_param||Se(e,["cursor","nextCursor","next_cursor"]),b=r>0?nr(t,a.next_cursor_path||"next_cursor"):nr(t,a.previous_cursor_path||"previous_cursor");return h&&b?{[h]:b}:null}if(l==="offset"){const h=a.offset_param||Se(e,["offset","start"]),b=a.limit_param||Se(e,["limit","pageSize","page_size"]),P=Number(n[b]||t.page_size||t.limit||10),E=Number(n[h]||t.offset||0);if(!h||!Number.isFinite(P)||!Number.isFinite(E))return null;const Ne=Math.max(0,E+r*P);return b?{[h]:Ne,[b]:P}:{[h]:Ne}}const u=a.page_param||Se(e,["page","pageNum","page_num","pageNo","page_no"]),d=a.page_size_param||Se(e,["page_size","pageSize","limit","size"]),f=Number(n[u]||t.page||1);if(!u||!Number.isFinite(f))return null;const p=Math.max(1,f+r),y={[u]:p},g=Number(n[d]||t.page_size||t.pageSize||0);return d&&Number.isFinite(g)&&g>0&&(y[d]=g),y}function Ko(e){const t=(e.fields||[]).map(n=>String(n.key||""));return t.some(n=>["cursor","nextCursor","next_cursor"].includes(n))?"cursor":t.some(n=>["offset","start"].includes(n))?"offset":"page"}function Se(e,t){const n=(e.fields||[]).map(r=>String(r.key||""));return t.find(r=>n.includes(r))||t[0]||""}function nr(e,t){if(t)return String(t).split(".").reduce((n,r)=>{if(n&&Object.prototype.hasOwnProperty.call(n,r))return n[r]},e)}function G(e,t,n={}){o.modalReturnFocus=document.activeElement instanceof HTMLElement?document.activeElement:null,c.modalTitle.textContent=e,c.modalBody.innerHTML=t,c.modal.classList.remove("is-image-preview");const r=c.modal.dataset.modalClass||"";r&&c.modal.classList.remove(r),n.className&&c.modal.classList.add(n.className),c.modal.dataset.modalClass=n.className||"",c.modal.hidden=!1,c.modalClose.focus()}function Do(){return!c.modal||c.modal.hidden?[]:Array.from(c.modal.querySelectorAll("button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")).filter(e=>!e.hidden&&e.getAttribute("aria-hidden")!=="true")}function No(e){if(e.key!=="Tab"||c.modal.hidden)return!1;const t=Do();if(!t.length)return e.preventDefault(),c.modalClose.focus(),!0;const n=t[0],r=t[t.length-1];return e.shiftKey&&(document.activeElement===n||!c.modal.contains(document.activeElement))?(e.preventDefault(),r.focus(),!0):!e.shiftKey&&(document.activeElement===r||!c.modal.contains(document.activeElement))?(e.preventDefault(),n.focus(),!0):!1}function jo(e){const t=Vn(e.dataset.imageSrc||"");if(!t){m("\u56FE\u7247\u94FE\u63A5\u4E0D\u53EF\u7528");return}const n=e.dataset.imageTitle||"\u56FE\u7247\u9884\u89C8",r=e.dataset.imageAlt||n,a=e.dataset.imageCaption||"";G(n,`
            <figure class="tui-image-lightbox">
                <div class="tui-image-lightbox-frame">
                    <img src="${i(t)}" alt="${i(r)}" loading="eager" decoding="async">
                </div>
                <figcaption>
                    ${a?`<span>${i(a)}</span>`:""}
                    <a href="${i(t)}" target="_blank" rel="noopener noreferrer">\u6253\u5F00\u539F\u56FE</a>
                </figcaption>
            </figure>
        `,{className:"is-image-preview"}),m("\u56FE\u7247\u9884\u89C8")}function Oo(e,t,n,r={}){const a=e.missing_fields||[],s=e.action||v(t)||{key:t||"missing-fields"};G("\u8865\u586B\u53C2\u6570",`
            <form class="tui-confirmation tui-missing-fields" data-missing-fields-form>
                <p>${i(e.view_model?.message||"\u8865\u9F50\u53C2\u6570\u540E\u7EE7\u7EED\u6267\u884C\u3002")}</p>
                <div class="tui-missing-fields-list">
                    ${a.map(d=>wn(s,{...d,default:n[d.key]??d.default??""})).join("")}
                </div>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="submit">\u7EE7\u7EED</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>\u53D6\u6D88</button>
                </div>
            </form>
        `);const l=c.modalBody.querySelector("[data-missing-fields-form]"),u=c.modalBody.querySelector("[data-cancel-action]");l.addEventListener("submit",d=>{d.preventDefault();const f={...n};a.forEach(p=>{const y=l.querySelector(`[name="${CSS.escape(p.key)}"]`);y&&(f[p.key]=Sn(p,y.value,y.checked))}),F(),$(t,null,{...r,params:f})}),u.addEventListener("click",()=>{F(),m("\u5DF2\u53D6\u6D88")}),l.querySelector("select, input, textarea")?.focus()}function zo(e,t,n,r={}){const a=e.confirmation||{};G(a.title||"\u786E\u8BA4\u64CD\u4F5C",`
            <div class="tui-confirmation">
                <p>${i(a.message||"\u786E\u8BA4\u540E\u6267\u884C\u6B64\u64CD\u4F5C\u3002")}</p>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="button" data-confirm-action>${i(a.confirm_label||"\u786E\u8BA4\u6267\u884C")}</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>${i(a.cancel_label||"\u53D6\u6D88")}</button>
                </div>
            </div>
        `);const s=c.modalBody.querySelector("[data-confirm-action]"),l=c.modalBody.querySelector("[data-cancel-action]");s.addEventListener("click",()=>{F(),$(t,null,{...r,confirmed:!0,params:n,confirmation:{confirmed:!0,confirmed_at:new Date().toISOString(),message:a.message||""}})}),l.addEventListener("click",()=>{F(),m("\u5DF2\u53D6\u6D88")}),s.focus()}function Uo(e,t,n,r={}){const a=e.password_challenge||{};G("\u91CD\u65B0\u9A8C\u8BC1\u8EAB\u4EFD",`
            <form class="tui-confirmation" data-password-challenge-form>
                <p>${i(a.message||"\u8BE5\u64CD\u4F5C\u9700\u8981\u91CD\u65B0\u9A8C\u8BC1\u8EAB\u4EFD\u3002")}</p>
                <label class="tui-field">
                    <span>\u5BC6\u7801</span>
                    <input name="password" type="password" autocomplete="current-password" required>
                </label>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="submit">\u9A8C\u8BC1\u5E76\u7EE7\u7EED</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>\u53D6\u6D88</button>
                </div>
            </form>
        `);const s=c.modalBody.querySelector("[data-password-challenge-form]"),l=c.modalBody.querySelector("[data-cancel-action]");s.addEventListener("submit",u=>{u.preventDefault();const d=s.querySelector("[name='password']")?.value||"";F(),$(t,null,{...r,params:n,reauth:{method:"password",credential:d,challenge_id:a.challenge_id||"",submitted_at:new Date().toISOString()}})}),l.addEventListener("click",()=>{F(),m("\u5DF2\u53D6\u6D88")}),s.querySelector("input")?.focus()}function F(){if(c.modal){const e=!c.modal.hidden;c.modal.hidden=!0,c.modal.classList.remove("is-image-preview"),c.modalBody.innerHTML="",e&&o.modalReturnFocus&&document.contains(o.modalReturnFocus)&&o.modalReturnFocus.focus(),o.modalReturnFocus=null}}function At(){const e=o.visibleRows[o.selectedRowIndex];if(!e){m("\u672A\u9009\u62E9\u884C");return}const t=dn(e).map(([s,l])=>`
            <dt>${i(s)}</dt>
            <dd>${i(l)}</dd>
        `).join(""),n=String(e?.target_screen||"").trim(),r=String(e?.target_action_key||"").trim(),a=!!(n||r);G(`\u7B2C ${o.selectedRowIndex+1} \u884C`,`
                <dl class="tui-detail-grid">${t}</dl>
                ${a?`
                    <div class="tui-modal-actions">
                        <button type="button" data-row-target-screen="${i(n)}" data-row-target-action="${i(r)}">\u8FDB\u5165\u5904\u7406\u5C4F</button>
                    </div>
                `:""}
            `),c.modalBody?.querySelector("[data-row-target-screen], [data-row-target-action]")?.addEventListener("click",async()=>{F();const s=n||o.screen?.screen?.key||"";s&&(await S(s),r&&v(r)&&$(r,null,{params:{}}))}),m("\u884C\u8BE6\u60C5")}function Vo(){G("\u5E2E\u52A9",`
            <div class="tui-help-grid">
                <span>F1</span><span>\u6253\u5F00\u5E2E\u52A9</span>
                <span>F2</span><span>\u5C55\u5F00\u6216\u6536\u8D77\u6A21\u5757\u5BFC\u822A</span>
                <span>F3</span><span>\u8FDB\u5165\u6D41\u7A0B\u4E0A\u4E00\u5C4F</span>
                <span>F4</span><span>\u8FDB\u5165\u6D41\u7A0B\u4E0B\u4E00\u5C4F</span>
                <span>F5</span><span>\u5237\u65B0\u5F53\u524D\u5DE5\u4F5C\u533A\u6216\u4EFB\u52A1</span>
                <span>F6</span><span>\u6267\u884C\u672C\u5C4F\u4E0B\u4E00\u4E3B\u6D41\u7A0B\u4EFB\u52A1</span>
                <span>F7</span><span>\u7B5B\u9009\u5F53\u524D\u8868\u683C</span>
                <span>F8</span><span>\u5BFC\u51FA\u5F53\u524D\u8868\u683C CSV</span>
                <span>F9</span><span>\u5B9A\u4F4D\u4EFB\u52A1\u533A</span>
                <span>F10</span><span>\u5C55\u5F00\u6216\u6536\u8D77\u8BF4\u660E\u680F</span>
                <span>Alt+T</span><span>\u5FAA\u73AF\u5207\u6362\u4E3B\u9898 A / B / C</span>
                <span>Alt+S/M/R/V/H</span><span>\u6253\u5F00\u9876\u90E8\u5BF9\u5E94\u83DC\u5355</span>
                <span>Alt+Shift+T</span><span>\u67E5\u770B\u5F53\u524D\u4E3B\u9898\u4E0E\u4E09\u5957\u98CE\u683C</span>
                <span>\u65B9\u5411\u952E</span><span>\u79FB\u52A8\u8868\u683C\u9009\u4E2D\u884C</span>
                <span>Enter</span><span>\u6253\u5F00\u9009\u4E2D\u884C\u8BE6\u60C5</span>
                <span>PgUp/PgDn</span><span>\u5B58\u5728\u5206\u9875\u65F6\u7FFB\u9875</span>
                <span>Esc</span><span>\u5173\u95ED\u83DC\u5355\u3001\u7B5B\u9009\u3001\u8C03\u8BD5\u62BD\u5C49\u6216\u5F39\u7A97</span>
            </div>
        `),m("\u5E2E\u52A9")}function Mo(){G("\u4E3B\u9898",`
            <div class="tui-help-grid">
                <span>\u5F53\u524D</span><span>STYLE: ${i(o.themeKey)}</span>
                <span>A</span><span>Norton PCTOOLS \u84DD\u5E95\u9EC4\u5B57\u98CE\u683C</span>
                <span>B</span><span>\u4E2D\u6027\u91D1\u878D\u4E13\u4E1A\u7EC8\u7AEF\u98CE\u683C</span>
                <span>C</span><span>\u98CE\u63A7 / \u63A7\u5236\u53F0\u98CE\u683C</span>
                <span>Alt+T</span><span>\u5FAA\u73AF\u5207\u6362\uFF0C\u4E0D\u5237\u65B0\u9875\u9762\uFF0C\u4E0D\u4E22\u5931\u5F53\u524D\u72B6\u6001</span>
            </div>
        `),m(`\u5F53\u524D\u4E3B\u9898: ${o.themeKey}`)}function Wo(){if(!o.currentViewModel||o.currentViewModel.kind!=="datagrid"){m("\u5F53\u524D\u89C6\u56FE\u4E0D\u53EF\u7B5B\u9009");return}c.filterBar.hidden=!1,c.filterInput.value=o.filterText,c.filterInput.focus(),c.filterInput.select(),m("\u7B5B\u9009\u5C31\u7EEA")}function xt(){c.filterBar&&(c.filterBar.hidden=!0)}function Go(){o.filterText="",c.filterInput&&(c.filterInput.value=""),qe(!0)}function rr(e){let t=String(e??"");return/^[=+\-@]/.test(t)&&(t=`'${t}`),/[",\n\r]/.test(t)?`"${t.replace(/"/g,'""')}"`:t}function Jo(){if(!o.currentViewModel||o.currentViewModel.kind!=="datagrid"){m("\u5F53\u524D\u89C6\u56FE\u4E0D\u53EF\u5BFC\u51FA");return}const e=o.currentColumns,t=o.visibleRows,n=[e.map(u=>rr(u.label)).join(","),...t.map(u=>e.map(d=>rr(u[d.key])).join(","))].join(`\r
`),r=new Blob(["\uFEFF"+n],{type:"text/csv;charset=utf-8"}),a=URL.createObjectURL(r),s=document.createElement("a"),l=(o.currentViewModel.title||"tui-grid").toLowerCase().replace(/[^a-z0-9一-龥]+/g,"-").replace(/^-|-$/g,"")||"tui-grid";s.href=a,s.download=`${l}.csv`,document.body.appendChild(s),s.click(),s.remove(),URL.revokeObjectURL(a),m(`\u5DF2\u5BFC\u51FA ${t.length} \u884C`)}async function Qo(){const e=o.lastAction?v(o.lastAction):null,t=["write","admin"].includes(String(e?.risk||"").toLowerCase());e&&!t?await $(o.lastAction,null,{params:{...o.lastParams}}):o.screen?.screen?.key?await S(o.screen.screen.key):await yr()}function Yo(){or(!1);const e=c.moduleTree.querySelector(".tui-screen-button.is-active")||c.moduleTree.querySelector(".tui-screen-button");e&&(bn(e),e.focus(),m("\u6A21\u5757\u5BFC\u822A"))}function ar(){const e=c.main.closest(".tui-workspace-grid");e?.classList.contains("is-dashboard")&&(e.classList.remove("is-dashboard"),Ce("idle"));const t=o.screen?.actions||[];t.some(a=>k(a)==="support")&&(o.showSupportTasks=!0),t.some(a=>k(a)==="advanced")&&(o.showAdvancedQueries=!0),t.length&&I(t,o.screen?.screen||{});const n=c.actions.querySelector("[data-action-filter]");if(n){n.focus(),n.select(),m("\u4EFB\u52A1\u533A");return}const r=c.actions.querySelector(".tui-action-button");r&&(r.focus(),m("\u4EFB\u52A1\u533A"))}function Zo(){ir(!1);const e=c.inspector.querySelector("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")||c.inspectorShell;e&&(e.focus(),m("\u8BF4\u660E\u680F"))}function or(e){o.railCollapsed=!!e,c.app?.classList.toggle("is-rail-collapsed",o.railCollapsed),c.moduleTree&&(c.moduleTree.hidden=o.railCollapsed,c.moduleTree.inert=o.railCollapsed,c.moduleTree.setAttribute("aria-hidden",String(o.railCollapsed))),c.railToggle&&(c.railToggle.setAttribute("aria-expanded",String(!o.railCollapsed)),c.railToggle.setAttribute("aria-label",o.railCollapsed?"\u5C55\u5F00\u6A21\u5757\u5BFC\u822A":"\u6536\u8D77\u6A21\u5757\u5BFC\u822A"),c.railToggle.textContent=o.railCollapsed?"\u25BA":"\u25C4"),o.railCollapsed&&c.railPanel?.contains(document.activeElement)&&c.main.querySelector(".tui-datagrid")?.focus()}function sr(){or(!o.railCollapsed),o.railCollapsed?m("\u6A21\u5757\u5BFC\u822A\u5DF2\u6536\u8D77"):Yo()}function ir(e){o.inspectorCollapsed=!!e,c.app?.classList.toggle("is-inspector-collapsed",o.inspectorCollapsed),c.inspectorToggle&&(c.inspectorToggle.setAttribute("aria-expanded",String(!o.inspectorCollapsed)),c.inspectorToggle.setAttribute("aria-label",o.inspectorCollapsed?"\u5C55\u5F00\u8BF4\u660E\u680F":"\u6536\u8D77\u8BF4\u660E\u680F"),c.inspectorToggle.textContent=o.inspectorCollapsed?"\u25C4":"\u25BA"),o.inspectorCollapsed&&c.inspectorShell?.contains(document.activeElement)&&c.main.querySelector(".tui-datagrid")?.focus()}function cr(){ir(!o.inspectorCollapsed),o.inspectorCollapsed?m("\u8BF4\u660E\u680F\u5DF2\u6536\u8D77"):Zo()}function lr(e){const t=Xe();return t?t.getBoundingClientRect().right-e.clientX:null}function Xo(e){if(o.inspectorCollapsed||e.button!==0||!_e())return;e.preventDefault(),e.stopPropagation(),c.app?.classList.add("is-inspector-resizing"),c.inspectorResizeHandle?.setPointerCapture?.(e.pointerId),ie(lr(e));const t=r=>{r.preventDefault(),ie(lr(r))},n=r=>{r.preventDefault(),c.app?.classList.remove("is-inspector-resizing"),c.inspectorResizeHandle?.releasePointerCapture?.(e.pointerId),c.inspectorResizeHandle?.removeEventListener("pointermove",t),c.inspectorResizeHandle?.removeEventListener("pointerup",n),c.inspectorResizeHandle?.removeEventListener("pointercancel",n),ie(o.inspectorWidth,{persist:!0}),m(`\u8BF4\u660E\u680F\u5BBD\u5EA6 ${o.inspectorWidth}px`)};c.inspectorResizeHandle?.addEventListener("pointermove",t),c.inspectorResizeHandle?.addEventListener("pointerup",n),c.inspectorResizeHandle?.addEventListener("pointercancel",n)}function es(e){if(o.inspectorCollapsed)return;const t=_e();if(!t)return;const n=o.inspectorWidth||c.inspectorShell?.getBoundingClientRect().width||t.min;let r=null;if(e.key==="ArrowLeft"?r=n+(e.shiftKey?48:16):e.key==="ArrowRight"?r=n-(e.shiftKey?48:16):e.key==="Home"?r=t.min:e.key==="End"&&(r=t.max),r===null)return;e.preventDefault(),e.stopPropagation();const a=ie(r,{persist:!0});a&&m(`\u8BF4\u660E\u680F\u5BBD\u5EA6 ${a}px`)}function ts(){const e=c.actions.querySelector("[data-action-filter]");e&&(e.focus(),e.select(),m("\u7B5B\u9009\u5F53\u524D\u4EFB\u52A1"))}function ns(e){const t=Array.from(c.moduleTree.querySelectorAll("[data-screen-key]"));if(!t.length)return;const r=(Math.max(0,t.findIndex(a=>a.classList.contains("is-active")))+e+t.length)%t.length;S(t[r].dataset.screenKey)}function Ct(e){if(A(o.screen?.screen?.key)){const r=w.host?.laneActionKeys?.[o.preferredHomeLane];r&&oe(r);return}const t=o.screen?.screen?.workflow||{},n=e<0?t.previous:t.next;if(n&&n.key){S(n.key);return}ns(e)}function rs(){return(o.screen&&o.screen.actions||[]).map((t,n)=>({action:t,index:n})).filter(t=>k(t.action)==="primary").sort((t,n)=>Number(t.action.sequence||999)-Number(n.action.sequence||999)||t.index-n.index).map(t=>t.action)}function Lt(){const e=rs();return e.length&&e.find(t=>!Ie(t.key))||null}function ur(e=o.screen?.screen?.key){const t=e||"";return t?(o.completedActionsByScreen[t]||(o.completedActionsByScreen[t]=new Set),o.completedActionsByScreen[t]):new Set}function Ie(e){return ur().has(e)}function as(e){!e||k(e)!=="primary"||(ur(e.screen_key).add(e.key),Xt())}function Ke(e=o.screen&&o.screen.actions||[]){const t=e.filter(r=>k(r)==="primary");return{completed:t.filter(r=>Ie(r.key)).length,total:t.length}}function os(){const e=o.screen?.screen?.key;if(!e){m("\u6CA1\u6709\u53EF\u91CD\u7F6E\u7684\u5DE5\u4F5C\u533A");return}o.completedActionsByScreen[e]=new Set,Xt(),de(o.screen?.screen)||I(o.screen.actions||[],o.screen.screen),o.currentViewModel&&Z(o.currentViewModel),m("\u672C\u5C4F\u8FDB\u5EA6\u5DF2\u91CD\u7F6E")}function dr(){if(A(o.screen?.screen?.key)){const r=w.host?.laneActionKeys?.[o.preferredHomeLane];r&&oe(r);return}const e=Lt();if(!e){m("\u672C\u5C4F\u4E3B\u6D41\u7A0B\u5DF2\u5B8C\u6210");return}const t=c.actions.querySelector(`[data-action-ui-key="${CSS.escape(U(e))}"]`),n=(e.fields||[]).filter(r=>r.required&&!r.default);if(n.length&&t){mt(t);const r=n.filter(a=>{const s=ge(t,a.key);return!s||!s.checked&&String(s.value||"").trim()===""});if(r.length){t.scrollIntoView({block:"nearest"}),t.querySelector("input:not([type='hidden']),select,textarea")?.focus(),m(`\u4E0B\u4E00\u9879\u9700\u8981\u53C2\u6570: ${r.map(a=>a.label).join(", ")}`);return}}$(e.key,t)}function pr(e,t){const n=gr[e]||[];o.menuSourceButton&&o.menuSourceButton!==t&&o.menuSourceButton.setAttribute("aria-expanded","false"),o.activeMenu=e,o.menuSourceButton=t,t.setAttribute("aria-expanded","true"),c.menuPopover.innerHTML=`
            <div class="tui-menu-title">${i(e.toUpperCase())}</div>
            ${n.map(([s,l,u])=>`
                <button type="button" role="menuitem" data-menu-action="${i(s)}">
                    <span>${i(l)}</span>
                    <kbd>${i(u)}</kbd>
                </button>
            `).join("")}
        `;const r=t.getBoundingClientRect();c.menuPopover.style.left=`${Math.max(4,r.left)}px`,c.menuPopover.style.top=`${r.bottom+2}px`,c.menuPopover.hidden=!1;const a=c.menuPopover.querySelector("button");a&&a.focus()}function j(e={}){const t=o.menuSourceButton;o.activeMenu=null,o.menuSourceButton=null,t?.setAttribute("aria-expanded","false"),c.menuPopover&&(c.menuPopover.hidden=!0,c.menuPopover.innerHTML=""),e.restoreFocus&&t&&document.contains(t)&&t.focus()}async function fr(e){j(),e==="refresh"?(Ye(),await Qo()):e==="export"?Jo():e==="toggle-rail"?sr():e==="focus-actions"?ar():e==="previous-workflow"?Ct(-1):e==="next-workflow"?Ct(1):e==="run-next-primary"?dr():e==="filter-actions"?ts():e==="row-detail"?At():e==="filter"?Wo():e==="reset-progress"?os():e==="toggle-inspector"?cr():e==="raw"?He():e==="help"&&Vo()}function De(e){return!!e?.closest?.("input, textarea, select, [contenteditable='true']")}function Tt(e){return!!e?.closest?.("button, a, input, textarea, select, summary, [role='button'], [role='separator'], [contenteditable='true']")}function ss(){return c.modal.hidden?c.filterBar.hidden?c.menuPopover.hidden?c.rawDrawer.hidden?!1:(He(!1),!0):(j({restoreFocus:!0}),!0):(xt(),!0):(F(),!0)}function is(e){const t=String(e.key||""),n=t.toLowerCase();if(e.altKey&&!e.ctrlKey&&!e.shiftKey&&n==="t")return"cycle-theme";if(e.altKey&&!e.ctrlKey&&e.shiftKey&&n==="t")return"theme-status";if(e.altKey&&!e.ctrlKey&&!e.shiftKey){const r={s:"file",m:"module",r:"action",v:"view",h:"help"};if(r[n])return`open-menu:${r[n]}`}return!e.altKey&&!e.ctrlKey&&!e.metaKey&&Pt[t]?Pt[t]:e.ctrlKey&&!e.altKey&&!e.metaKey&&t==="Enter"?"run-next-primary":""}function cs(e){if(e.isComposing||e.metaKey||!c.modal.hidden)return!1;const t=is(e);if(!t)return!1;if(e.preventDefault(),e.stopPropagation(),t.startsWith("open-menu:")){const n=t.slice(10),r=document.querySelector(`[data-menu-command="${CSS.escape(n)}"]`);r&&pr(n,r)}else t==="cycle-theme"?Kr():t==="theme-status"?Mo():fr(t);return!0}function ls(){const e=typeof _.debounce=="function"?_.debounce(()=>qe(!0),Sr):()=>qe(!0);c.actions?.addEventListener("submit",t=>{const n=t.target?.closest?.("[data-action-ui-key]");n&&(t.preventDefault(),xe(n))}),c.actions?.addEventListener("click",t=>{const n=t.target?.closest?.("[data-fill-from-row]");if(n){t.preventDefault(),mt(n.closest("[data-action-ui-key]"));return}const r=t.target?.closest?.(".tui-action-button");if(!r)return;const a=r.closest("[data-action-ui-key]");a&&(t.preventDefault(),xe(a))}),c.main?.addEventListener("click",t=>{const n=t.target?.closest?.("[data-image-preview]");n&&(t.preventDefault(),jo(n))}),c.currentLocation?.addEventListener("focus",()=>{c.currentLocation.select()}),c.currentLocation?.addEventListener("keydown",t=>{t.key==="Enter"?(t.preventDefault(),Nr()):t.key==="Escape"&&(t.preventDefault(),Ze(),c.currentLocation.blur())}),c.rawToggle.addEventListener("click",()=>He()),c.rawClose.addEventListener("click",()=>He(!1)),c.modalClose.addEventListener("click",F),c.filterInput.addEventListener("input",()=>{o.filterText=c.filterInput.value,e()}),c.filterInput.addEventListener("keydown",t=>{t.key==="Enter"&&(t.preventDefault(),xt(),c.main.querySelector(".tui-datagrid")?.focus())}),c.filterClear.addEventListener("click",Go),c.railToggle?.addEventListener("click",sr),c.inspectorToggle?.addEventListener("click",cr),c.inspectorResizeHandle?.addEventListener("pointerdown",Xo),c.inspectorResizeHandle?.addEventListener("keydown",es),document.querySelectorAll("[data-menu-command]").forEach(t=>{t.addEventListener("click",n=>{n.stopPropagation();const r=t.dataset.menuCommand;o.activeMenu===r&&!c.menuPopover.hidden?j():pr(r,t)})}),c.menuPopover.addEventListener("click",t=>{const n=t.target.closest("[data-menu-action]");n&&fr(n.dataset.menuAction)}),c.menuPopover.addEventListener("keydown",t=>{const n=Array.from(c.menuPopover.querySelectorAll("[role='menuitem']")),r=n.indexOf(document.activeElement);let a=r;if(t.key==="ArrowDown")a=(r+1+n.length)%n.length;else if(t.key==="ArrowUp")a=(r-1+n.length)%n.length;else if(t.key==="Home")a=0;else if(t.key==="End")a=n.length-1;else if(t.key==="Escape"){t.preventDefault(),j({restoreFocus:!0});return}else if(t.key==="Tab"){j();return}else return;n.length&&(t.preventDefault(),n[a]?.focus())}),document.addEventListener("click",t=>{!c.menuPopover.hidden&&!t.target.closest("[data-menu-popover]")&&!t.target.closest("[data-menu-command]")&&j()}),document.addEventListener("keydown",t=>{No(t)||cs(t)||(t.key==="Escape"?ss()&&t.preventDefault():t.key==="Enter"&&!Tt(t.target)?(t.preventDefault(),At()):t.key==="ArrowDown"&&!De(t.target)&&!Tt(t.target)?(t.preventDefault(),tr(1)):t.key==="ArrowUp"&&!De(t.target)&&!Tt(t.target)?(t.preventDefault(),tr(-1)):t.key==="PageDown"&&!De(t.target)?o.lastPager&&(t.preventDefault(),_t(1)):t.key==="PageUp"&&!De(t.target)&&o.lastPager&&(t.preventDefault(),_t(-1)))},{capture:!0})}function mr(){c.clock&&(c.clock.textContent=Yt())}async function yr(){_.mark?.("bootstrap-start");try{c.moduleTree.innerHTML='<div class="tui-loading">\u6B63\u5728\u52A0\u8F7D\u76EE\u5F55...</div>',m("\u542F\u52A8\u4E2D");const e=It(),t=Me(),n=e||(tn()&&o.lastNonHomeScreen?o.lastNonHomeScreen:""),r=Lr(n);if(r)try{const d=await R(r);if(d?.contract==="tui-bootstrap.v1"&&d.catalog&&d.screen){at(d.catalog),nn(),A(d.screen?.screen?.key)&&(o.operatorHomePayload=null,o.operatorHomePromise=null),kn(d.screen,{suppressAutoAction:!!t,deepLinkedActionKey:t}),gt(d.screen,t),Dt(d.screen?.screen?.key,{replace:!0,preserveAction:!!t}),se(),n&&d.resolved_screen!==n&&m("\u4E0A\u6B21\u5DE5\u4F5C\u533A\u5DF2\u4E0D\u53EF\u7528\uFF0C\u5DF2\u8FD4\u56DE\u9996\u9875"),_.mark?.("p0-ready"),_.measure?.("bootstrap-to-p0","bootstrap-start","p0-ready");return}}catch(d){if(![0,404,405].includes(Number(d?.status||0)))throw d}const a=await R(xr());at(a);const s=!!(!e&&tn()&&o.lastNonHomeScreen),l=e||(s?o.lastNonHomeScreen:a.default_screen);nn(),!await S(l,{replaceHistory:!0,preserveAction:!!t,deepLinkedActionKey:t})&&(s||e)&&(m(e?"\u94FE\u63A5\u4E2D\u7684\u5DE5\u4F5C\u533A\u4E0D\u53EF\u7528\uFF0C\u5DF2\u8FD4\u56DE\u9996\u9875":"\u4E0A\u6B21\u5DE5\u4F5C\u533A\u5DF2\u4E0D\u53EF\u7528\uFF0C\u5DF2\u8FD4\u56DE\u9996\u9875"),await S(a.default_screen,{replaceHistory:!0})),_.mark?.("p0-ready"),_.measure?.("bootstrap-to-p0","bootstrap-start","p0-ready")}catch(e){c.moduleTree.innerHTML='<div class="tui-error">\u5BFC\u822A\u6682\u65F6\u4E0D\u53EF\u7528</div>',le(e)}}function us(){return["app","moduleTree","screenTitle","screenStatus","actions","mainTitle","main","inspector","rawDrawer","rawPanel","rawToggle","rawClose","pager","menuPopover","filterBar","filterInput","filterClear","modal","modalTitle","modalBody","modalClose","status"].filter(n=>!c[n]).length?(document.body.innerHTML=`
            <main class="tui-error" role="alert">
                \u5DE5\u4F5C\u53F0\u9875\u9762\u7ED3\u6784\u4E0D\u5B8C\u6574\uFF0C\u8BF7\u5237\u65B0\u9875\u9762\u6216\u8054\u7CFB\u7CFB\u7EDF\u7BA1\u7406\u5458\u3002
            </main>
        `,!1):!0}function ds(){us()&&(jr(),Or(),Qt(Ir(),{silent:!0}),Qr(),ls(),window.addEventListener("popstate",()=>{const e=It();e&&e!==o.screen?.screen?.key?S(e,{suppressHistory:!0,preserveAction:!0,deepLinkedActionKey:Me()}):e&&gt(o.screen,Me())}),mr(),window.setInterval(mr,1e3),yr())}ds()})();
