(function(){"use strict";const _=window.AgomTUIRuntimeCore||{},o={catalog:null,screen:null,screenBadges:{},screenBadgeDrilldowns:{},homePanelBadges:{},lastAction:null,lastParams:{},lastRaw:null,lastPager:null,currentViewModel:null,currentColumns:[],currentRows:[],visibleRows:[],selectedRowContext:null,filterText:"",selectedRowIndex:0,activeMenu:null,lastFormTriggerRef:"",lastFormTriggerAt:0,showSupportTasks:!1,showAdvancedQueries:!1,actionFilterText:"",completedActionsByScreen:{},railCollapsed:!1,inspectorCollapsed:!1,inspectorWidth:null,themeKey:"B",pinnedScreenKeys:new Set,preferredHomeLane:"decision",lastNonHomeScreen:"",pendingRequestId:0,latestRequestId:0,pendingController:null,slowActionTimer:null,clientPage:1,clientPageSize:100,operatorHomePayload:null,operatorHomePromise:null,modalReturnFocus:null,menuSourceButton:null},i={app:document.querySelector("[data-tui-app]"),railPanel:document.querySelector("[data-rail-panel]"),moduleTree:document.querySelector("[data-module-tree]"),screenTitle:document.querySelector("[data-screen-title]"),screenStatus:document.querySelector("[data-screen-status]"),actions:document.querySelector("[data-actions-panel]"),mainTitle:document.querySelector("[data-main-title]"),main:document.querySelector("[data-main-panel]"),workflowStrip:document.querySelector("[data-workflow-strip]"),inspector:document.querySelector("[data-inspector-panel]"),rawDrawer:document.querySelector("[data-raw-drawer]"),rawPanel:document.querySelector("[data-raw-panel]"),rawToggle:document.querySelector("[data-raw-toggle]"),rawClose:document.querySelector("[data-raw-close]"),pager:document.querySelector("[data-pager-status]"),clock:document.querySelector("[data-tui-clock]"),menuPopover:document.querySelector("[data-menu-popover]"),filterBar:document.querySelector("[data-filter-bar]"),filterInput:document.querySelector("[data-filter-input]"),filterClear:document.querySelector("[data-filter-clear]"),modal:document.querySelector("[data-tui-modal]"),modalTitle:document.querySelector("[data-modal-title]"),modalBody:document.querySelector("[data-modal-body]"),modalClose:document.querySelector("[data-modal-close]"),status:document.querySelector("[data-workbench-status]"),lastRefresh:document.querySelector("[data-last-refresh]"),currentLocation:document.querySelector("[data-current-location]"),railToggle:document.querySelector("[data-toggle-rail]"),inspectorShell:document.querySelector("[data-inspector-panel-shell]"),inspectorToggle:document.querySelector("[data-toggle-inspector]"),inspectorResizeHandle:document.querySelector("[data-inspector-resize-handle]"),themeStatus:document.querySelector("[data-theme-status]"),themeIndicatorCode:document.querySelector("[data-theme-indicator-code]")},cr={file:[["refresh","\u5237\u65B0\u5F53\u524D\u89C6\u56FE","F5"],["export","\u5BFC\u51FA\u5F53\u524D\u8868\u683C","F8"]],module:[["toggle-rail","\u5C55\u5F00/\u6536\u8D77\u6A21\u5757\u5BFC\u822A","F2"],["previous-workflow","\u4E0A\u4E00\u4E2A\u6D41\u7A0B\u5C4F","F3"],["next-workflow","\u4E0B\u4E00\u4E2A\u6D41\u7A0B\u5C4F","F4"]],action:[["run-next-primary","\u6267\u884C\u4E0B\u4E00\u4E3B\u6D41\u7A0B","F6"],["focus-actions","\u5B9A\u4F4D\u4EFB\u52A1\u533A","F9"],["row-detail","\u6253\u5F00\u9009\u4E2D\u884C","Enter"]],view:[["filter","\u7B5B\u9009\u8868\u683C","F7"],["filter-actions","\u7B5B\u9009\u5F53\u524D\u4EFB\u52A1","\u83DC\u5355"],["toggle-inspector","\u5C55\u5F00/\u6536\u8D77\u8BF4\u660E\u680F","F10"],["reset-progress","\u91CD\u7F6E\u672C\u5C4F\u8FDB\u5EA6","\u83DC\u5355"],["raw","\u539F\u59CB\u54CD\u5E94","\u83DC\u5355"]],help:[["help","\u952E\u76D8\u5E2E\u52A9","F1"]]},_t={F1:"help",F2:"toggle-rail",F3:"previous-workflow",F4:"next-workflow",F5:"refresh",F6:"run-next-primary",F7:"filter",F8:"export",F9:"focus-actions",F10:"toggle-inspector"},xt="agom-tui-primary-progress:v1",At="agom-tui-theme:v1",Ct="agom-tui-inspector-width:v1",He="agom-tui-last-non-home-screen:v1",Lt="agom-tui-pinned-screen-keys:v1",Tt="agom-tui-preferred-home-lane:v1",ye="agom-tui-resume-on-boot:v1",Ie=220,Pt=640,lr=980,ur=.56,dr=250,pr=120,fr=250,mr=15e3,gr=2*1024*1024,be=["A","B","C"],yr={A:{background:"#001A8D",panelBackground:"#000B55",primaryText:"#FFFFFF",secondaryText:"#C0C0C0",border:"#00FFFF",highlight:"#FFFF00",accent:"#C0C0C0",success:"#00FF80",warning:"#FFFF00",error:"#FF4040",grid:"#002070"},B:{background:"#07090F",panelBackground:"#101827",primaryText:"#E8EEF8",secondaryText:"#AAB6C5",border:"#58708F",highlight:"#F7C948",accent:"#38BDF8",success:"#2EE59D",warning:"#F7C948",error:"#FF5A5F",grid:"#263449"},C:{background:"#02060A",panelBackground:"#071018",primaryText:"#BFFFE0",secondaryText:"#6FAF93",border:"#123B33",highlight:"#39FF88",accent:"#2DE2E6",success:"#39FF88",warning:"#FFCC66",error:"#FF3B3B",grid:"#0E2A24"}},w=window.__AGOMTUI_RUNTIME__||{},De=String(w.apiBase||"/api/tui").replace(/\/+$/,""),B=typeof _.createRuntimeUrls=="function"?_.createRuntimeUrls(w):null,C=typeof _.runtimeHooks=="function"?_.runtimeHooks(w):w.hooks||{},br=w.allowSvgDataImages!==!1,Y=new Map;function Ne(e){try{return window[e]||null}catch{return null}}function K(e,t,n=null){try{return Ne(e)?.getItem(t)??n}catch{return n}}function j(e,t,n){try{Ne(e)?.setItem(t,n)}catch{}}function Ke(e,t){try{Ne(e)?.removeItem(t)}catch{}}function L(e){const t=String(i.app?.dataset.userKey||"anonymous").trim().replace(/[^a-zA-Z0-9_-]+/g,"_");return`${e}:user:${t||"anonymous"}`}function Rt(){try{return new URL(window.location.href).searchParams.get("screen")?.trim()||""}catch{return""}}function Ft(e,t={}){const n=String(e||"").trim();if(!n||!window.history?.pushState)return;const r=new URL(window.location.href);if(r.searchParams.get("screen")===n)return;r.searchParams.set("screen",n);const a=t.replace?"replaceState":"pushState";window.history[a]({screenKey:n},"",r)}const je=new Set(["datagrid","detail","message","chart","image","line","bar","pie","kpi-trend","kpi_trend","table-chart","table_chart","host-slot","host_slot"]);function Et(e,t){const n=String(e||"").trim();return!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(n)||typeof t!="function"?!1:(Y.set(n,t),!0)}const qt=window.AgomTUIRenderers||{};window.AgomTUIRenderers={register:Et,get(e){return Y.get(String(e||"").trim())||null},has(e){return Y.has(String(e||"").trim())}},Array.isArray(qt.pending)&&qt.pending.forEach(e=>{Array.isArray(e)&&Et(e[0],e[1])});function hr(){return B?B.catalog():`${De}/catalog/`}function wr(e){return B?B.screen(e):`${De}/screens/${encodeURIComponent(e)}/`}function Oe(e){return B?B.action(e):`${De}/actions/${encodeURIComponent(e)}/run/`}function Sr(e=""){return B?B.bootstrap(e):""}function kr(){return String(w.host?.operatorHomeUrl||"")}function $r(e=""){const t=String(w.host?.governanceQueueUrl||"");if(!t)return"";const n=e?`?domain=${encodeURIComponent(e)}`:"";return`${t}${n}`}function x(e){return typeof C.isOperatorHomeScreen=="function"?!!C.isOperatorHomeScreen(e):!1}function Bt(e){return(w.host?.homeActionKeys||[]).includes(String(e||""))}function vr(e){const t=String(e?.action_key||"").trim(),n=String(w.host?.homePanelActionPrefix||"");return!n||!t.startsWith(n)||Bt(t)?"":t.slice(n.length)}function c(e){return String(e??"").replace(/[&<>"']/g,t=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[t])}function ze(e){return(e||[]).reduce((t,n)=>{const r=String(n?.severity||"").trim().toLowerCase();return r==="blocked"?t.blockedCount+=1:r==="warning"&&(t.warningCount+=1),t},{blockedCount:0,warningCount:0})}function _r(e){return(e||[]).reduce((t,n)=>(t.blockedCount+=Number(n?.blockedCount||0),t.warningCount+=Number(n?.warningCount||0),t),{blockedCount:0,warningCount:0})}function Ht(e){return _r((e||[]).map(t=>o.screenBadges[t]||{}))}function It(e){return Number(e?.blockedCount||0)>0||Number(e?.warningCount||0)>0}function Z(e,t={}){if(!It(e))return"";const n=Number(e?.blockedCount||0),r=Number(e?.warningCount||0),a=n>0?"blocked":"warning",s=n>0?n:r,l=n>0?"\u963B\u65AD":"\u9884\u8B66",u=t.compact?" tui-badge--compact":"";return`<span class="tui-badge tui-badge--${c(a)}${u}" aria-label="${c(l)} ${s}">${c(s)}</span>`}function Dt(e){return e==="blocked"?0:e==="warning"?1:2}function xr(e){return(e||[]).reduce((t,n)=>{const r=String(n?.severity||"").trim().toLowerCase(),a=String(n?.target_screen||"").trim(),s=String(n?.target_action_key||"").trim();if(!["blocked","warning"].includes(r)||!a||!s)return t;const l={screenKey:a,actionKey:s,severity:r,title:String(n?.title||"").trim(),nextAction:String(n?.next_action||"").trim()},u=t[a];return(!u||Dt(r)<Dt(u.severity))&&(t[a]=l),t},{})}function Nt(e){return o.screenBadgeDrilldowns[String(e||"").trim()]||null}function Kt(e){return e?i.actions.querySelector(`[data-action-ui-key="${CSS.escape(O(e))}"]`):null}function jt(e){const t=o.screenBadges[e];if(!It(t))return"";const n=Nt(e),r=Z(t,{compact:!0});if(!n?.actionKey)return r;const a=n.title||n.nextAction||"\u67E5\u770B\u6CBB\u7406\u6458\u8981";return`
            <button
                class="tui-badge-button"
                type="button"
                data-badge-screen-key="${c(e)}"
                title="${c(a)}"
                aria-label="${c(a)}"
            >${r}</button>
        `}async function Ar(e){const t=String(e||"").trim();if(!t)return null;const n=Nt(t);if(!n?.actionKey)return S(t);const r=await S(t,{suppressAutoAction:!0});if(!r)return r;const a=k(n.actionKey);return a&&await $(a.key,Kt(a)),r}function Cr(e){const t=document.cookie?document.cookie.split(";"):[];for(const n of t){const[r,...a]=n.trim().split("=");if(r===e)return decodeURIComponent(a.join("="))}return""}function p(e){i.status&&(i.status.textContent=e)}function Ve(e){return be.includes(e)?e:"B"}function Lr(e){const t=String(e||"").replace("#","");return/^[0-9a-f]{6}$/i.test(t)?{r:Number.parseInt(t.slice(0,2),16),g:Number.parseInt(t.slice(2,4),16),b:Number.parseInt(t.slice(4,6),16)}:null}function Ot(e,t){const n=Lr(e);return n?`rgba(${n.r}, ${n.g}, ${n.b}, ${t})`:`rgba(0, 0, 0, ${t})`}function he(e,t){const n=encodeURIComponent(String(t||"#ffffff"));return`url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='17' height='17' viewBox='0 0 17 17'%3E%3Cpath d='${{up:"M8 4 L3 11 H13 Z",down:"M3 6 H13 L8 13 Z",left:"M4 8 L11 3 V13 Z",right:"M6 3 L13 8 L6 13 Z"}[e]}' fill='${n}'/%3E%3C/svg%3E")`}function zt(e,t={}){const n=Ve(e),r=yr[n],a=document.documentElement,s={"--tui-bg":r.background,"--tui-bg-deep":r.background,"--tui-panel":r.panelBackground,"--tui-panel-strong":r.border,"--tui-border":r.border,"--tui-border-dim":r.grid,"--tui-text":r.primaryText,"--tui-muted":r.secondaryText,"--tui-inverse":r.background,"--tui-command":r.background,"--tui-accent":r.highlight,"--tui-accent-strong":r.accent,"--tui-warn":r.warning,"--tui-danger":r.error,"--tui-green":r.success,"--tui-scroll-face":r.border,"--tui-scroll-light":r.primaryText,"--tui-scroll-track":r.grid,"--tui-scroll-shadow":r.background,"--tui-scroll-dark":r.background,"--tui-menubar-bg":r.grid,"--tui-menubar-text":r.primaryText,"--tui-footer-bg":r.grid,"--tui-footer-text":r.primaryText,"--tui-footer-divider":r.border,"--tui-footer-hotkey":r.highlight,"--tui-footer-emphasis":r.warning,"--tui-system-source-accent":r.accent,"--tui-grid-strong":Ot(r.primaryText,.66),"--tui-overlay":Ot(r.background,.82),"--tui-scroll-arrow-up":he("up",r.primaryText),"--tui-scroll-arrow-down":he("down",r.primaryText),"--tui-scroll-arrow-left":he("left",r.primaryText),"--tui-scroll-arrow-right":he("right",r.primaryText)};return Object.entries(s).forEach(([l,u])=>{a.style.setProperty(l,u)}),a.dataset.tuiTheme=n,o.themeKey=n,i.themeStatus&&(i.themeStatus.textContent=`STYLE: ${n}`),i.themeIndicatorCode&&(i.themeIndicatorCode.textContent=`T:${n}`),t.silent||j("localStorage",At,n),n}function Tr(){return Ve(K("localStorage",At,"B"))}function Pr(){const e=be.indexOf(Ve(o.themeKey)),t=be[(e+1)%be.length];zt(t),p(`\u4E3B\u9898\u5DF2\u5207\u6362: ${t}`)}function X(e){return String(e).padStart(2,"0")}function Vt(){const e=new Date;return[e.getFullYear(),X(e.getMonth()+1),X(e.getDate())].join("-")+" "+[X(e.getHours()),X(e.getMinutes()),X(e.getSeconds())].join(":")}function Me(){i.lastRefresh&&(i.lastRefresh.textContent=Vt())}function Mt(e){if(!i.currentLocation)return;const t=o.screen?.screen||{},n=o.screen?.module||{},r=t.key||"boot",a=e?.key?`screen:${r} action:${e.key}`:`screen:${r}`,s=[n.label,t.label,e?.label].filter(Boolean).join(" / ");i.currentLocation.value!==a&&(i.currentLocation.value=a),i.currentLocation.dataset.currentAddress=a,i.currentLocation.title=s?`${s} | ${a}`:a}function Rr(e){const t=String(e||"").trim();if(!t)return"";const n=t.match(/^screen:([^\s]+)(?:\s+action:.+)?$/i);return n?n[1]:/^[a-z0-9][a-z0-9._-]*$/i.test(t)?t:""}function Ue(){i.currentLocation&&(i.currentLocation.value=i.currentLocation.dataset.currentAddress||`screen:${o.screen?.screen?.key||"boot"}`)}function Fr(){if(!i.currentLocation)return;const e=Rr(i.currentLocation.value);if(!e){Ue(),p("\u4F4D\u7F6E\u683C\u5F0F\u65E0\u6548");return}i.currentLocation.blur(),S(e)}function Er(){try{const e=K("sessionStorage",L(xt));if(!e)return;const t=JSON.parse(e);Object.entries(t||{}).forEach(([n,r])=>{Array.isArray(r)&&(o.completedActionsByScreen[n]=new Set(r.filter(Boolean)))})}catch{o.completedActionsByScreen={}}}function qr(){try{o.lastNonHomeScreen=String(K("localStorage",L(He),"")).trim();const e=String(K("localStorage",L(Tt),"decision")).trim();o.preferredHomeLane=e==="governance"?"governance":"decision";const t=K("localStorage",L(Lt)),n=t?JSON.parse(t):[];o.pinnedScreenKeys=new Set(Array.isArray(n)?n.map(r=>String(r||"").trim()).filter(Boolean):[])}catch{o.lastNonHomeScreen="",o.preferredHomeLane="decision",o.pinnedScreenKeys=new Set}}function Ut(){try{const e={};Object.entries(o.completedActionsByScreen||{}).forEach(([t,n])=>{n&&n.size&&(e[t]=Array.from(n))}),j("sessionStorage",L(xt),JSON.stringify(e))}catch{}}function Br(e){const t=String(e||"").trim();o.lastNonHomeScreen=t,t?j("localStorage",L(He),t):Ke("localStorage",L(He))}function Wt(e){o.preferredHomeLane=e==="governance"?"governance":"decision",j("localStorage",L(Tt),o.preferredHomeLane)}function Hr(){j("localStorage",L(Lt),JSON.stringify(Array.from(o.pinnedScreenKeys)))}function Gt(){return K("sessionStorage",L(ye))==="1"}function Jt(){Ke("sessionStorage",L(ye))}function Ir(){o.screen?.screen?.key&&!x(o.screen.screen.key)?j("sessionStorage",L(ye),"1"):Ke("sessionStorage",L(ye))}function Dr(){window.open("/terminal/","_blank","noopener,noreferrer"),p("CLI \u5DF2\u5728\u65B0\u6807\u7B7E\u9875\u6253\u5F00")}function Nr(){const e=String(o.lastNonHomeScreen||"").trim();return e?(S(e),!0):(p("\u6CA1\u6709\u53EF\u6062\u590D\u7684\u6700\u8FD1\u5DE5\u4F5C\u533A"),!1)}function ee(e){const t=String(e||"").trim();return typeof C.runHomeAction=="function"?!!C.runHomeAction(t,{loadScreen:S,openCliSurface:Dr,persistPreferredLane:Wt,restoreLastWorkspace:Nr}):!1}function Qt(e){return typeof C.inferHomeLane=="function"?String(C.inferHomeLane(e)||""):""}function Kr(e){const t={};return(e||[]).forEach(n=>{const r=String(n?.severity||"").trim().toLowerCase();if(!["blocked","warning"].includes(r))return;const a=String(n?.target_screen||"").trim();a&&(t[a]||(t[a]={blockedCount:0,warningCount:0}),r==="blocked"?t[a].blockedCount+=1:t[a].warningCount+=1)}),t}function Yt(){!x(o.screen?.screen?.key)||!i.main||i.main.querySelectorAll("[data-dashboard-panel]").forEach(e=>{const t=e.dataset.dashboardPanel,n=o.homePanelBadges[t],r=e.querySelector("[data-panel-badge]");r&&(r.innerHTML=Z(n,{compact:!0}))})}function Zt(e){const t=e?.counts_by_screen||{};o.screenBadges=Object.fromEntries(Object.entries(t).map(([n,r])=>[n,{blockedCount:Number(r?.blocked_count||0),warningCount:Number(r?.warning_count||0)}])),o.catalog&&Xe(),Yt()}async function Xt(){if(o.operatorHomePayload)return o.operatorHomePayload;if(!o.operatorHomePromise){const e=kr();if(!e)return null;o.operatorHomePromise=E(e).then(t=>(o.operatorHomePayload=t,Zt(t?.navigation_badges),t)).finally(()=>{o.operatorHomePromise=null})}return o.operatorHomePromise}async function te(){try{if(typeof C.loadNavigationBadges=="function"){const t=await C.loadNavigationBadges({fetchJson:E,screen:o.screen});if(t){Zt(t);return}}if(x(o.screen?.screen?.key)){await Xt();return}}catch{return}const e=$r();if(e)try{const t=await E(e);o.screenBadges=Kr(t.items||[]),o.screenBadgeDrilldowns=xr(t.items||[]),o.catalog&&Xe(),Yt()}catch{o.screenBadges={},o.screenBadgeDrilldowns={},o.catalog&&Xe()}}function We(){return i.inspectorShell?.closest?.(".tui-workspace-grid")||null}function we(){const e=We();if(!e||window.matchMedia?.(`(max-width: ${lr}px)`)?.matches)return null;const t=e.getBoundingClientRect().width||window.innerWidth,n=Math.max(Ie,Math.min(Pt,Math.round(t*ur)));return{min:Ie,max:n}}function jr(e){const t=we();return t?Math.round(Math.min(t.max,Math.max(t.min,Number(e)||t.min))):null}function ne(e,t={}){const n=We(),r=jr(e);if(!n||!r)return null;if(o.inspectorWidth=r,n.style.setProperty("--tui-inspector-user-width",`${r}px`),i.inspectorResizeHandle){const a=we();i.inspectorResizeHandle.setAttribute("aria-valuemin",String(a?.min||Ie)),i.inspectorResizeHandle.setAttribute("aria-valuemax",String(a?.max||Pt)),i.inspectorResizeHandle.setAttribute("aria-valuenow",String(r))}return t.persist&&j("localStorage",Ct,String(r)),r}function Or(){const e=K("localStorage",Ct);if(e==null)return;const t=Number(e);Number.isFinite(t)&&ne(t)}function Jo(e){return{read:"\u7ACB\u5373\u6253\u5F00",ai:"AI \u534F\u52A9",write:"\u63D0\u4EA4\u786E\u8BA4",unsafe:"\u53D7\u9650\u5DE5\u5177",admin:"\u7BA1\u7406\u5DE5\u5177"}[String(e||"").toLowerCase()]||"\u4EFB\u52A1"}function re(e){const t=String(e.risk||"read").toLowerCase(),n=String(e.effect||"").toLowerCase(),r=String(e.intent||"").toLowerCase(),a=String(e.label||"").toLowerCase(),s={create:"\u521B\u5EFA\u8BB0\u5F55",update:"\u4FDD\u5B58\u4FEE\u6539",toggle:"\u5207\u6362\u72B6\u6001",delete:"\u5220\u9664\u6216\u64A4\u9500",execute:t==="ai"?"\u53D1\u8D77\u95EE\u7B54":"\u6267\u884C\u4EFB\u52A1"};return s[n]?s[n]:t==="ai"?"\u53D1\u8D77\u95EE\u7B54":(e.fields||[]).some(l=>l.input_type!=="hidden")?"\u6309\u6761\u4EF6\u67E5\u8BE2":r.includes("health")||r.includes("status")||a.includes("\u68C0\u67E5")?"\u8FD0\u884C\u68C0\u67E5":e.view_type==="datagrid"?"\u6253\u5F00\u6E05\u5355":e.view_type==="detail"||e.view_type==="status"?"\u67E5\u770B\u8BE6\u60C5":"\u751F\u6210\u89C6\u56FE"}function en(e){const t=v(e),n=String(e.risk||"read").toLowerCase();return t==="operation"?n==="ai"?"AI \u64CD\u4F5C":n==="write"?"\u53EF\u6267\u884C\u64CD\u4F5C":n==="admin"?"\u7BA1\u7406\u64CD\u4F5C":"\u64CD\u4F5C":t==="primary"?"\u4E3B\u6D41\u7A0B":t==="advanced"?"\u6761\u4EF6\u67E5\u8BE2":"\u652F\u6491\u68C0\u67E5"}function tn(e,t){const n=[];t&&n.push("\u5DF2\u5B8C\u6210"),n.push(en(e)),n.push(re(e));const r=(e.fields||[]).filter(a=>a.input_type!=="hidden").length;return r&&n.push(`${r} \u9879\u53C2\u6570`),e.confirmation_required&&n.push("\u6267\u884C\u524D\u786E\u8BA4"),n.join(" / ")}function nn(e){return{status:"\u72B6\u6001",detail:"\u8BE6\u60C5",datagrid:"\u8868\u683C",message:"\u8BF4\u660E",queue_workbench:"\u961F\u5217",auto:"\u81EA\u52A8"}[String(e||"").toLowerCase()]||"\u5DE5\u4F5C\u533A"}function A(e){return String(e??"").replace(/自动批准的只读/g,"\u5DF2\u53D1\u5E03\u7684").replace(/只读详情工具/g,"\u8BE6\u60C5\u5DE5\u5177").replace(/只读/g,"\u53EF\u67E5\u770B").replace(/读取业务视图/g,"\u6253\u5F00\u4E1A\u52A1\u89C6\u56FE").replace(/直接读取/g,"\u76F4\u63A5\u6253\u5F00")}function H(e){if(e==null||e==="")return"-";if(typeof e=="object")try{return JSON.stringify(e,null,2)}catch{return"\u7ED3\u6784\u5316\u6570\u636E"}return String(e)}function zr(e){const t={account_id:"\u8D26\u6237ID",asset_code:"\u6807\u7684\u4EE3\u7801",asset_codes:"\u8D44\u4EA7\u4EE3\u7801",fund_code:"\u57FA\u91D1\u4EE3\u7801",id:"ID",pk:"\u8BB0\u5F55ID",portfolio_id:"\u7EC4\u5408ID",provider_id:"\u6570\u636E\u6E90ID",risk_level:"\u98CE\u9669\u7B49\u7EA7",short_code:"\u77ED\u7801",task_id:"\u4EFB\u52A1ID"},n=String(e||"");return t[n]?t[n]:n.replace(/[_-]+/g," ").replace(/\b\w/g,r=>r.toUpperCase()).replace(/\bId\b/g,"ID").replace(/\bPct\b/g,"\u6BD4\u4F8B").replace(/\bAt\b/g,"\u65F6\u95F4")}function Vr(e){return o.currentColumns.find(n=>n.key===e)?.label||zr(e)}function rn(e,t=1/0){if(!e)return[];const n=[];return o.currentColumns.forEach(r=>{Object.prototype.hasOwnProperty.call(e,r.key)&&n.push(r.key)}),Object.keys(e).forEach(r=>{r.startsWith("__")||n.includes(r)||n.push(r)}),n.slice(0,t).map(r=>[Vr(r),H(e[r])])}function O(e){return e.ui_key||e.key}function k(e){return(o.screen&&o.screen.actions||[]).find(t=>t.key===e||O(t)===e)||null}function Se(e){return e?.dataset?.actionUiKey||e?.dataset?.actionKey||""}function ke(e){const t=Se(e);if(!t){p("\u4EFB\u52A1\u672A\u627E\u5230");return}const n=Date.now();o.lastFormTriggerRef===t&&n-o.lastFormTriggerAt<dr||(o.lastFormTriggerRef=t,o.lastFormTriggerAt=n,$(t,e))}async function E(e,t){const n=t||{},r=(n.method||"GET").toUpperCase(),a={Accept:"application/json",...n.headers||{}};r!=="GET"&&(a["Content-Type"]="application/json",a["X-CSRFToken"]=Cr("csrftoken"));const s=await fetch(e,{credentials:"same-origin",...n,headers:a}),l=s.headers.get("content-type")||"";if(!s.ok){let u=null;if(l.includes("application/json"))try{u=await s.json()}catch{u=null}const d=new Error("\u4E1A\u52A1\u8BF7\u6C42\u672A\u5B8C\u6210");throw d.status=s.status,d.payload=u,d}if(!l.includes("application/json"))throw new Error("\u4E1A\u52A1\u6570\u636E\u683C\u5F0F\u4E0D\u53EF\u6E32\u67D3");return s.json()}function an(e){const t=Number(e?.status||0),n=e?.payload&&typeof e.payload=="object"?e.payload:{},r=String(n.error_code||"").startsWith("tui_"),s={403:["\u65E0\u6743\u8BBF\u95EE","\u5F53\u524D\u8D26\u53F7\u4E0D\u80FD\u5B8C\u6210\u8FD9\u9879\u64CD\u4F5C\u3002"],404:["\u5185\u5BB9\u4E0D\u5B58\u5728","\u76EE\u6807\u5185\u5BB9\u6CA1\u6709\u53D1\u5E03\uFF0C\u6216\u5DF2\u88AB\u79FB\u9664\u3002"],502:["\u670D\u52A1\u6682\u65F6\u4E0D\u53EF\u7528","\u670D\u52A1\u6682\u65F6\u65E0\u6CD5\u5B8C\u6210\u8BF7\u6C42\uFF0C\u8BF7\u7A0D\u540E\u91CD\u8BD5\u3002"],503:["\u670D\u52A1\u6B63\u5728\u6062\u590D","\u670D\u52A1\u5C1A\u672A\u5C31\u7EEA\uFF0C\u8BF7\u7A0D\u540E\u91CD\u8BD5\u3002"]}[t]||["\u6682\u65F6\u65E0\u6CD5\u5B8C\u6210\u8BF7\u6C42","\u8BF7\u7A0D\u540E\u91CD\u8BD5\uFF0C\u6216\u8FD4\u56DE\u53EF\u7528\u5DE5\u4F5C\u533A\u3002"],l=r&&Array.isArray(n.recovery_actions)?n.recovery_actions.filter(u=>u&&typeof u=="object"&&u.screen_key).map(u=>({label:String(u.label||"\u524D\u5F80\u53EF\u7528\u5DE5\u4F5C\u533A"),screenKey:String(u.screen_key)})):[];return{title:r?String(n.title||s[0]):s[0],detail:r?String(n.detail||s[1]):s[1],traceId:r?String(n.trace_id||""):"",recoveryActions:l}}function Ge(e,t){const n=an(t),r=String(e?.error_message||n.detail);return`
            <div class="tui-panel-error" role="status">
                <strong>${c(n.title)}</strong>
                <p>${c(r)}</p>
                ${n.traceId?`<small>\u8FFD\u8E2A\u7F16\u53F7\uFF1A${c(n.traceId)}</small>`:""}
                <div class="tui-panel-error-actions">
                    <button class="tui-panel-retry" type="button" data-panel-retry>\u91CD\u8BD5</button>
                    ${n.recoveryActions.map(a=>`
                        <button
                            class="tui-panel-recovery"
                            type="button"
                            data-panel-recovery-screen="${c(a.screenKey)}"
                        >${c(a.label)}</button>
                    `).join("")}
                </div>
                ${e.note?`<small>${c(e.note)}</small>`:""}
            </div>
        `}function Je(e,t){e.querySelector("[data-panel-retry]")?.addEventListener("click",()=>le(t)),e.querySelectorAll("[data-panel-recovery-screen]").forEach(n=>{n.addEventListener("click",()=>S(n.dataset.panelRecoveryScreen))})}function ae(e,t={}){w.debug===!0&&window.console?.error&&window.console.error("TUI request failed",e);const n=an(e);i.mainTitle.textContent=n.title,i.main.innerHTML=`
            <section class="tui-application-error" role="alert">
                <strong>${c(n.title)}</strong>
                <p>${c(n.detail)}</p>
                ${n.traceId?`<small>\u8FFD\u8E2A\u7F16\u53F7\uFF1A${c(n.traceId)}</small>`:""}
                <div class="tui-panel-error-actions">
                    <button class="tui-panel-retry" type="button" data-application-retry>\u91CD\u8BD5</button>
                    ${n.recoveryActions.map(r=>`
                        <button
                            class="tui-panel-recovery"
                            type="button"
                            data-panel-recovery-screen="${c(r.screenKey)}"
                        >${c(r.label)}</button>
                    `).join("")}
                </div>
            </section>
        `,i.main.querySelector("[data-application-retry]")?.addEventListener("click",()=>{const r=String(t.retryScreenKey||o.screen?.screen?.key||o.catalog?.default_screen||"home");S(r)}),i.main.querySelectorAll("[data-panel-recovery-screen]").forEach(r=>{r.addEventListener("click",()=>S(r.dataset.panelRecoveryScreen))}),p("\u8BF7\u6C42\u672A\u5B8C\u6210")}let Qe=0;function I(e={}){const{abort:t=!1}=e;if(o.slowActionTimer&&(window.clearTimeout(o.slowActionTimer),o.slowActionTimer=null),t&&o.pendingController)try{o.pendingController.abort()}catch{}o.pendingController=null,o.pendingRequestId=0}function on(e){return I({abort:!0}),Qe+=1,o.pendingRequestId=Qe,o.latestRequestId=Qe,o.pendingController=e,o.pendingRequestId}function oe(e){return e===o.latestRequestId}function Ye(e,t,n={}){const r=n.waitingCopy||"\u6B63\u5728\u8BFB\u53D6\u4E1A\u52A1\u6570\u636E...";i.main.innerHTML=`
            <section class="tui-entry-state">
                <div class="tui-view-status">\u52A0\u8F7D\u4E2D / ${c(e.label||"\u9ED8\u8BA4\u4EFB\u52A1")}</div>
                <div class="tui-entry-copy">
                    <strong>${c(r)}</strong>
                    <p>${c(t?.screen?.summary||"\u7CFB\u7EDF\u6B63\u5728\u51C6\u5907\u9ED8\u8BA4\u7ED3\u679C\u3002")}</p>
                </div>
            </section>
        `,p("\u8BFB\u53D6\u6570\u636E")}function sn(e,t){new Set(w.host?.slowActionKeys||[]).has(t.key)&&(o.slowActionTimer=window.setTimeout(()=>{o.pendingRequestId===e&&Mr(t)},mr))}function Mr(e){const t=(w.host?.slowActionScreens||[]).filter(n=>n?.key&&n?.label).map(n=>`<button type="button" data-slow-screen="${c(n.key)}">${c(n.label)}</button>`).join("");i.main.innerHTML=`
            <section class="tui-entry-state">
                <div class="tui-view-status">\u54CD\u5E94\u8F83\u6162 / ${c(e.label||"")}</div>
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
        `,i.main.querySelectorAll("[data-slow-command]").forEach(n=>{n.addEventListener("click",()=>{const r=n.dataset.slowCommand;r==="wait"?(Ye(e,o.screen,{waitingCopy:"\u7EE7\u7EED\u7B49\u5F85\u8FDC\u7AEF\u54CD\u5E94..."}),sn(o.pendingRequestId,e)):r==="retry"?(I({abort:!0}),$(e.key,null,{params:{...o.lastParams}})):r==="cancel"&&(I({abort:!0}),i.main.innerHTML=T("\u5DF2\u53D6\u6D88\u5F53\u524D\u8BF7\u6C42\u3002",["\u4F60\u53EF\u4EE5\u91CD\u8BD5\uFF0C\u6216\u5207\u6362\u5230\u5176\u4ED6\u5165\u53E3\u7EE7\u7EED\u3002"]),p("\u5DF2\u53D6\u6D88"))})}),i.main.querySelectorAll("[data-slow-screen]").forEach(n=>{n.addEventListener("click",()=>{I({abort:!0}),S(n.dataset.slowScreen)})}),p("\u54CD\u5E94\u8F83\u6162")}function Ur(e){const t=k(e);if(!t){p("\u9ED8\u8BA4\u4EFB\u52A1\u672A\u627E\u5230");return}const n=i.actions.querySelector(`[data-action-ui-key="${CSS.escape(O(t))}"]`);n?.scrollIntoView({block:"nearest"}),n?.querySelector("input:not([type='hidden']),select,textarea,button")?.focus(),p(`\u5DF2\u5B9A\u4F4D\u5230 ${t.label}`)}function Ze(e){o.catalog=e;const t=e.groups||[];let n=0;const r=document.activeElement?.closest?.("[data-screen-key]")?.dataset?.screenKey||"",a=i.moduleTree.scrollTop;i.moduleTree.innerHTML=t.map(s=>`
            <section class="tui-group">
                <div class="tui-group-title">${c(s.label)}</div>
                ${(s.modules||[]).map(l=>`
                    <div class="tui-tree-module">
                        ${Wr(s,l)?"":`
                            <div class="tui-tree-module-title">
                                <span>${c(l.label)}</span>
                                <div class="tui-tree-module-meta">
                                    <span data-module-badge-screens="${c((l.screens||[]).map(u=>u.key).join(","))}">${Z(Ht((l.screens||[]).map(u=>u.key)),{compact:!0})}</span>
                                    <small>${c(l.action_count||0)}</small>
                                </div>
                            </div>
                        `}
                        ${(l.screens||[]).map(u=>`
                            <div class="tui-screen-row">
                                <button class="tui-screen-button" type="button" data-screen-key="${c(u.key)}">
                                    <span>${++n} ${c(u.label)}</span>
                                    <small>${c(nn(u.view_type))} / ${c(u.action_count)} \u9879</small>
                                </button>
                                <div class="tui-screen-tools">
                                    <span data-screen-badge-host="${c(u.key)}">${jt(u.key)}</span>
                                    <button
                                        class="tui-screen-pin${o.pinnedScreenKeys.has(u.key)?" is-active":""}"
                                        type="button"
                                        data-pin-screen-key="${c(u.key)}"
                                        aria-label="${c(`${o.pinnedScreenKeys.has(u.key)?"\u53D6\u6D88\u6536\u85CF\u5DE5\u4F5C\u533A":"\u6536\u85CF\u5DE5\u4F5C\u533A"}\uFF1A${u.label}`)}"
                                        title="${c(`${o.pinnedScreenKeys.has(u.key)?"\u53D6\u6D88\u6536\u85CF\u5DE5\u4F5C\u533A":"\u6536\u85CF\u5DE5\u4F5C\u533A"}\uFF1A${u.label}`)}"
                                        aria-pressed="${o.pinnedScreenKeys.has(u.key)?"true":"false"}"
                                    >${o.pinnedScreenKeys.has(u.key)?"\u2605":"\u2606"}</button>
                                </div>
                            </div>
                        `).join("")}
                    </div>
                `).join("")}
            </section>
        `).join(""),i.moduleTree.querySelectorAll("[data-screen-key]").forEach(s=>{s.addEventListener("click",()=>S(s.dataset.screenKey))}),cn(),i.moduleTree.querySelectorAll("[data-pin-screen-key]").forEach(s=>{s.addEventListener("click",l=>{l.preventDefault(),l.stopPropagation();const u=String(s.dataset.pinScreenKey||"").trim();u&&(o.pinnedScreenKeys.has(u)?o.pinnedScreenKeys.delete(u):o.pinnedScreenKeys.add(u),Hr(),Ze(o.catalog))})}),i.moduleTree.scrollTop=a,r&&i.moduleTree.querySelector(`[data-screen-key="${CSS.escape(r)}"]`)?.focus(),o.screen?.screen?.key&&ln(o.screen.screen.key)}function Wr(e,t){const n=Array.isArray(e?.modules)?e.modules:[],r=String(e?.label||"").trim().toLocaleLowerCase(),a=String(t?.label||"").trim().toLocaleLowerCase();return n.length===1&&r!==""&&r===a}function cn(){i.moduleTree.querySelectorAll("[data-badge-screen-key]").forEach(e=>{e.dataset.badgeBound!=="true"&&(e.dataset.badgeBound="true",e.addEventListener("click",t=>{t.preventDefault(),t.stopPropagation(),Ar(e.dataset.badgeScreenKey)}))})}function Xe(){!o.catalog||!i.moduleTree||(i.moduleTree.querySelectorAll("[data-screen-badge-host]").forEach(e=>{e.innerHTML=jt(e.dataset.screenBadgeHost)}),i.moduleTree.querySelectorAll("[data-module-badge-screens]").forEach(e=>{const t=Ht(String(e.dataset.moduleBadgeScreens||"").split(",").filter(Boolean));e.innerHTML=Z(t,{compact:!0})}),cn())}function ln(e){let t=null;i.moduleTree.querySelectorAll("[data-screen-key]").forEach(n=>{const r=n.dataset.screenKey===e;n.classList.toggle("is-active",r),r&&(t=n)}),un(t)}function un(e){!e||o.railCollapsed||window.requestAnimationFrame(()=>{const t=i.moduleTree.getBoundingClientRect(),n=e.getBoundingClientRect();n.top>=t.top&&n.bottom<=t.bottom||e.scrollIntoView({block:"nearest",inline:"nearest"})})}function dn(e,t){const n=`tui-${e.key}-${t.key}`,r=t.default??"",a=String(t.value_type||"").toLowerCase(),s=["json","object","list"].includes(a)||r!==null&&typeof r=="object",l=s?typeof r=="string"?r:JSON.stringify(r,null,2):r,u=t.required?"required":"";if(t.input_type==="hidden")return`<input id="${c(n)}" name="${c(t.key)}" type="hidden" value="${c(l)}">`;if(t.input_type==="select"){const d=t.options||[],m=!t.required&&l===""?'<option value=""></option>':"";return`
                <label class="tui-field" for="${c(n)}">
                    <span>${c(t.label)}</span>
                    <select id="${c(n)}" name="${c(t.key)}" ${u}>
                        ${m}${d.map(f=>{const g=typeof f=="string"?f:f.value,b=typeof f=="string"?f:f.label;return`<option value="${c(g)}" ${String(g)===String(l)?"selected":""}>${c(b)}</option>`}).join("")}
                    </select>
                </label>
            `}if(t.input_type==="checkbox"){const d=l===!0||String(l).toLowerCase()==="true"||String(l)==="1";return`
                <label class="tui-field tui-field-checkbox" for="${c(n)}">
                    <input id="${c(n)}" name="${c(t.key)}" type="checkbox" value="true" ${d?"checked":""}>
                    <span>${c(t.label)}</span>
                </label>
            `}return t.input_type==="textarea"||s?`
                <label class="tui-field" for="${c(n)}">
                    <span>${c(t.label)}</span>
                    <textarea id="${c(n)}" name="${c(t.key)}" rows="${s?"5":"3"}" ${u} placeholder="${c(t.placeholder||"")}">${c(l)}</textarea>
                </label>
            `:t.input_type==="file"?`
                <label class="tui-field tui-field-file" for="${c(n)}">
                    <span>${c(t.label)}</span>
                    <input id="${c(n)}" name="${c(t.key)}" type="file" ${u} accept="${c(t.accept||"")}">
                </label>
            `:`
            <label class="tui-field" for="${c(n)}">
                <span>${c(t.label)}</span>
                <input id="${c(n)}" name="${c(t.key)}" type="${c(t.input_type||"text")}" value="${c(l)}" ${u} placeholder="${c(t.placeholder||"")}">
            </label>
        `}function pn(e,t,n){const r=String(e.value_type||e.input_type||"text").toLowerCase();if(e.input_type==="checkbox"||r==="boolean")return!!n;const a=String(t??"").trim();if(a==="")return"";if(r==="integer"||r==="int"||e.input_type==="number"){const s=Number(a);return Number.isFinite(s)?s:a}if(r==="float"){const s=Number.parseFloat(a);return Number.isFinite(s)?s:a}if(r==="list"){if(a.startsWith("[")&&a.endsWith("]"))try{const s=JSON.parse(a);return Array.isArray(s)?s:a}catch{return a.split(",").map(l=>l.trim()).filter(Boolean)}return a.split(",").map(s=>s.trim()).filter(Boolean)}if(r==="json"||r==="object")try{return JSON.parse(a)}catch{return a}return a}function et(e={}){const t=!!e.preserveRowContext;o.currentViewModel=null,o.currentColumns=[],o.currentRows=[],o.visibleRows=[],o.lastPager=null,o.selectedRowIndex=0,t||(o.selectedRowContext=null),o.filterText="",i.filterInput&&(i.filterInput.value=""),St()}function $e(e){const t=i.main.closest(".tui-workspace-grid");if(t){if(!e){delete t.dataset.viewKind;return}t.dataset.viewKind=String(e)}}function fn(e,t={}){o.screen=e,o.lastRaw=null,o.lastPager=null,o.homePanelBadges={},et();const n=e.screen,r=Qt(n);r&&Wt(r),x(n.key)||Br(n.key),Ir(),i.screenTitle.textContent=n.label.toUpperCase(),i.screenStatus.textContent=n.status.toUpperCase(),i.mainTitle.textContent=n.label.toUpperCase(),Mt(null),ln(n.key),Zr(n.workflow||{});const a=yn(n)&&n.entry_state?.mode!=="parameter_gate",s=_e(n);if(i.actions.closest(".tui-panel").hidden=s,i.inspector.closest(".tui-panel").hidden=s,i.main.closest(".tui-workspace-grid").classList.toggle("is-dashboard",a),$e(a?"dashboard":"idle"),o.showSupportTasks=!1,o.showAdvancedQueries=!1,o.actionFilterText="",a&&!s&&Cn(e.actions||[],n),a){ea(e),me(null),D(),Me(),p(s?"\u7CFB\u7EDF\u9996\u9875":"\u6982\u89C8\u5DF2\u52A0\u8F7D");return}Cn(e.actions||[],n);const l=de(e.actions||[]),u=n.business_context||{},d=se(n);Q({title:n.label,body:mn(n),rows:[["\u4E3B\u4EFB\u52A1",d.primaryTask],["\u76EE\u6807\u7ED3\u679C",d.primaryOutcome],["\u5DE5\u4F5C\u533A",e.module.label],["\u89C6\u56FE",nn(n.view_type)],["\u4E3B\u6D41\u7A0B",l.primary],["\u652F\u6491\u68C0\u67E5",l.support],["\u9AD8\u7EA7\u67E5\u8BE2",l.advanced],["\u53EF\u6267\u884C\u64CD\u4F5C",l.operation],["\u9700\u786E\u8BA4",l.write],["AI \u4EA4\u4E92",l.ai]],sections:[...gn(n),...nt(u),{title:"\u64CD\u4F5C\u63D0\u793A",body:[l.operation?"\u672C\u5DE5\u4F5C\u533A\u5305\u542B\u63D0\u4EA4\u6216 AI \u534F\u52A9\u52A8\u4F5C\uFF0C\u5DF2\u7F6E\u9876\u663E\u793A\uFF1B\u63D0\u4EA4\u524D\u4F1A\u6309\u7B56\u7565\u8981\u6C42\u786E\u8BA4\u3002":"\u672C\u5DE5\u4F5C\u533A\u5F53\u524D\u63D0\u4F9B\u6253\u5F00\u3001\u67E5\u8BE2\u548C\u68C0\u67E5\u4EFB\u52A1\uFF1B\u7ED3\u679C\u6309\u4E1A\u52A1\u89C6\u56FE\u5448\u73B0\uFF0C\u4E0D\u5C55\u793A\u5185\u90E8\u63A5\u53E3\u3002"],rows:[]}]}),me(null),D();const m=n.entry_state||{},f=Gr(e);if(m.mode==="parameter_gate"&&f)Jr(e,f,m),p("\u7B49\u5F85\u9009\u62E9");else if(f&&!t.suppressAutoAction){const g=i.actions.querySelector(`[data-action-ui-key="${CSS.escape(O(f))}"]`);Ye(f,e,{waitingCopy:m.empty_copy}),$(f.key,g)}else i.main.innerHTML=`<div class="tui-empty-state">${c(m.empty_copy||ve(n,n.summary))}<br>\u8BF7\u9009\u62E9\u5DE6\u4FA7\u4EFB\u52A1\u6216\u6309 F6 \u6267\u884C\u4E0B\u4E00\u4E3B\u6D41\u7A0B\u3002</div>`,p("\u5DE5\u4F5C\u533A\u5C31\u7EEA")}function Gr(e){const t=e.actions||[];if(!t.length)return null;const n=e.screen||{},r=n.entry_state||{};if(r.mode==="dashboard")return null;const s=t.find(u=>u.key===n.default_action_key)||t[0];return s?r.mode==="parameter_gate"?s:tt(s).length?null:s:null}function tt(e){return(e?.fields||[]).filter(t=>t.required&&t.input_type!=="hidden").filter(t=>t.default===void 0||t.default===null||t.default==="")}function Jr(e,t,n){const r=String(n.field_key||""),a=(t.fields||[]).find(l=>l.key===r)||tt(t)[0];if(!a){i.main.innerHTML=T(n.empty_copy||ve(e.screen,e.screen.summary),n.help_steps||["\u8BF7\u9009\u62E9\u5DE6\u4FA7\u4EFB\u52A1\u7EE7\u7EED\u3002"]);return}if(String(a.input_type||"").toLowerCase()==="select"&&Array.isArray(a.options)&&a.options.length){Qr(e,t,n,a);return}Yr(e,t,n,a)}function Qr(e,t,n,r){const a=(r.options||[]).filter(l=>l&&typeof l=="object"?String(l.value??"").trim()!=="":String(l??"").trim()!==""),s=a.map((l,u)=>{const d=typeof l=="object"?l.value:l,m=typeof l=="object"?l.label:l,f=typeof l=="object"?[l.account_name,l.account_type,l.summary].filter(Boolean).join(" / "):"";return`
                <button type="button" class="tui-entry-card" data-entry-option-index="${u}" data-entry-option-value="${c(d)}">
                    <strong>${c(m)}</strong>
                    <span>${c(f||"\u9009\u62E9\u540E\u81EA\u52A8\u8FDB\u5165\u9ED8\u8BA4\u7ED3\u679C\u3002")}</span>
                    <small>${c(t.label)}</small>
                </button>
            `}).join("");i.main.innerHTML=`
            <section class="tui-entry-state">
                <div class="tui-view-status">\u5165\u53E3\u9009\u62E9 / ${c(e.screen.label)}</div>
                <div class="tui-entry-copy">
                    <strong>${c(n.empty_copy||ve(e.screen,`\u5148\u9009\u62E9${r.label}`))}</strong>
                    ${(n.help_steps||[]).map(l=>`<p>${c(l)}</p>`).join("")}
                </div>
                <div class="tui-entry-grid">${s}</div>
            </section>
        `,i.main.querySelectorAll("[data-entry-option-index]").forEach((l,u)=>{l.addEventListener("click",()=>{const d=a[u],m=typeof d=="object"?d.value:d;$(t.key,null,{params:{[r.key]:m}})})})}function Yr(e,t,n,r){i.main.innerHTML=`
            <section class="tui-entry-state">
                <div class="tui-view-status">\u4EFB\u52A1\u8D77\u6B65 / ${c(e.screen.label)}</div>
                <div class="tui-entry-copy">
                    <strong>${c(n.empty_copy||ve(e.screen,`\u5148\u8865\u5145${r.label}`))}</strong>
                    ${(n.help_steps||[]).map(a=>`<p>${c(a)}</p>`).join("")}
                </div>
                <div class="tui-entry-actions">
                    <button type="button" data-focus-default-action>\u6253\u5F00\u9ED8\u8BA4\u4EFB\u52A1</button>
                </div>
            </section>
        `,i.main.querySelector("[data-focus-default-action]")?.addEventListener("click",()=>{Ur(t.key)})}function se(e){const t=e&&typeof e.user_experience=="object"?e.user_experience:{};return{journey:String(t.journey||"").trim(),primaryTask:A(t.primary_task||e?.summary||e?.label||""),primaryOutcome:A(t.primary_outcome||e?.summary||e?.label||""),emptyStateHint:A(t.empty_state_hint||e?.summary||"\u5148\u8FD0\u884C\u672C\u5C4F\u4E3B\u4EFB\u52A1\uFF0C\u5FC5\u8981\u65F6\u8865\u5145\u53C2\u6570\u3002"),nextStepHint:A(t.next_step_hint||"\u6839\u636E\u7ED3\u679C\u7EE7\u7EED\u4E0B\u4E00\u9879\u4E3B\u6D41\u7A0B\uFF0C\u6216\u8FDB\u5165\u53EF\u6267\u884C\u64CD\u4F5C\u3002")}}function mn(e){const t=se(e);return dt([t.primaryTask,t.primaryOutcome!==t.primaryTask?t.primaryOutcome:""]).join(`
`)}function ve(e,t=""){return se(e).emptyStateHint||A(t||e?.summary||"\u5148\u8FD0\u884C\u672C\u5C4F\u4E3B\u4EFB\u52A1\u3002")}function gn(e){const t=se(e),n=[["\u4E3B\u4EFB\u52A1",t.primaryTask],["\u76EE\u6807\u7ED3\u679C",t.primaryOutcome]],r=dt([t.emptyStateHint,t.nextStepHint]);return[{title:"\u7528\u6237\u4EFB\u52A1",rows:n,body:r}]}function yn(e){return Array.isArray(e?.dashboard_panels)&&e.dashboard_panels.length>0}function _e(e){return yn(e)&&String(e?.chrome_mode||"").toLowerCase()==="immersive"}function nt(e){if(!e||!e.objective&&!e.decision_output&&!(e.checkpoints||[]).length)return[];const t=[];e.objective&&t.push({label:"\u76EE\u6807",value:A(e.objective)}),e.decision_output&&t.push({label:"\u4EA7\u51FA",value:A(e.decision_output)});const n=(e.checkpoints||[]).map((r,a)=>`${a+1}. ${A(r)}`);return[{title:"\u4E1A\u52A1\u76EE\u6807",rows:t,body:n}]}function Zr(e){if(!i.workflowStrip)return;if(x(o.screen?.screen?.key)){i.workflowStrip.hidden=!0,i.workflowStrip.innerHTML="";return}const t=e||{};if(!t.name){i.workflowStrip.hidden=!0,i.workflowStrip.innerHTML="";return}const n=t.previous||{},r=t.next||{},a=w.host?.workflowActionKeys||[],s=(typeof C.getHomeActions=="function"?C.getHomeActions({lastWorkspace:o.lastNonHomeScreen,preferredLane:o.preferredHomeLane}):[]).filter(m=>a.includes(m.key)),l=String(w.host?.workflowActionsLane||""),d=s.length&&l&&Qt({workflow:t})===l?`
                <div class="tui-workflow-tools">
                    ${s.map(m=>`
                        <button type="button" data-home-action-key="${c(m.key)}">${c(m.label)}</button>
                    `).join("")}
                </div>
            `:"";i.workflowStrip.hidden=!1,i.workflowStrip.innerHTML=`
            <div class="tui-workflow-main">
                <span>${c(t.name)}</span>
                <strong>${c(String(t.step||"-").padStart(2,"0"))}/${c(t.total||"-")}</strong>
                <span>${c(t.label||"")}</span>
            </div>
            <div class="tui-workflow-role">${c(t.role||"")}</div>
            <div class="tui-workflow-nav">
                ${n.key?`<button type="button" data-workflow-target="${c(n.key)}">&lt; ${c(n.label)}</button>`:"<span>\u8D77\u70B9</span>"}
                ${r.key?`<button type="button" data-workflow-target="${c(r.key)}">${c(r.label)} &gt;</button>`:"<span>\u7EC8\u70B9</span>"}
            </div>
            ${d}
        `,i.workflowStrip.querySelectorAll("[data-workflow-target]").forEach(m=>{m.addEventListener("click",()=>S(m.dataset.workflowTarget))}),i.workflowStrip.querySelectorAll("[data-home-action-key]").forEach(m=>{m.addEventListener("click",()=>ee(m.dataset.homeActionKey))})}function Xr(){const e=typeof C.getHomeActions=="function"?C.getHomeActions({lastWorkspace:o.lastNonHomeScreen,preferredLane:o.preferredHomeLane,availableActionKeys:new Set((o.screen?.actions||[]).map(t=>String(t.key||"")))}):[];return!Array.isArray(e)||!e.length?"":`
            <section class="tui-home-actions" aria-label="\u7EDF\u4E00\u9996\u9875\u4E3B\u52A8\u4F5C">
                ${e.map(t=>`
                    <button type="button" class="tui-home-action${t.active?" is-active":""}" data-home-action-key="${c(t.key)}">
                        <strong>${c(t.label)}</strong>
                        <span>${c(t.description||"")}</span>
                    </button>
                `).join("")}
            </section>
        `}function ea(e){const t=e.screen,n=t.dashboard_panels||[],r=_e(t),a=de(e.actions||[]),s=t.business_context||{},l=se(t),u=sa(n,t);$e("dashboard"),i.mainTitle.textContent=r?"\u7CFB\u7EDF\u9996\u9875":`${t.label} \u6982\u89C8`,i.main.innerHTML=`
            ${x(t.key)?Xr():""}
            <div class="tui-dashboard-grid${u.contentFlow?" is-content-flow":""}" style="${c(u.gridStyle)}">
                ${n.map((g,b)=>`
                    <article class="tui-dash-panel" style="grid-area: ${c(u.areas[b])};" data-dashboard-panel="${c(g.key)}" data-panel-priority="${c(ie(g))}" data-panel-semantic="${c(rt(g))}">
                        ${R(g,'<div class="tui-loading">\u8BFB\u53D6\u4E1A\u52A1\u6570\u636E...</div>')}
                    </article>
                `).join("")}
            </div>
        `,Q({title:t.label,body:mn(t),rows:[["\u4E3B\u4EFB\u52A1",l.primaryTask],["\u76EE\u6807\u7ED3\u679C",l.primaryOutcome],["\u5DE5\u4F5C\u533A",e.module.label],["\u5E03\u5C40",r?"\u7CFB\u7EDF\u9996\u9875\u603B\u63A7\u53F0":"\u4E1A\u52A1\u6982\u89C8\u9762\u677F"],["\u4E3B\u6D41\u7A0B",a.primary],["\u652F\u6491\u68C0\u67E5",a.support],["\u4EFB\u52A1",t.action_count]],sections:[...gn(t),...nt(s),{title:"\u64CD\u4F5C\u63D0\u793A",body:[r?"\u603B\u89C8\u9762\u677F\u6765\u81EA\u5DF2\u5BA1\u6838 action\uFF1B\u70B9\u51FB\u9762\u677F\u53EF\u8FDB\u5165\u5BF9\u5E94\u4E1A\u52A1\u5C4F\u7EE7\u7EED\u5904\u7406\u3002":"\u6982\u89C8\u9762\u677F\u7528\u4E8E\u5148\u770B\u5168\u5C40\u6458\u8981\uFF1B\u5DE6\u4FA7\u4EFB\u52A1\u533A\u53EF\u4EE5\u7EE7\u7EED\u6253\u5F00\u660E\u7EC6\u6216\u6267\u884C\u8865\u5145\u67E5\u8BE2\u3002"],rows:[]}]}),F(i.main),i.main.querySelectorAll("[data-home-action-key]").forEach(g=>{g.addEventListener("click",()=>ee(g.dataset.homeActionKey))});const d=n.filter(g=>ie(g)==="p0"),m=n.filter(g=>ie(g)!=="p0");d.forEach(g=>le(g));const f=()=>m.forEach(g=>le(g));typeof window.requestIdleCallback=="function"?window.requestIdleCallback(f,{timeout:fr}):window.setTimeout(f,0)}function bn(e){return String(e.target_screen||e.screen_key||"")}function ta(e,t){const n=String(e||"").trim(),r=String(t||"").trim(),a=String(o.screen?.screen?.key||"").trim();if(n&&n!==a){S(n);return}if(r){const s=k(r);if(s&&String(s.effect||"read")!=="read"){Qn();const l=Kt(s);l?.scrollIntoView({block:"nearest"}),(l?.querySelector("textarea, input:not([type='hidden']), select")||l?.querySelector("button"))?.focus(),p(`\u8BF7\u586B\u5199\u201C${s.label}\u201D\u540E\u7EE7\u7EED`);return}$(r,null,{params:{}});return}}function xe(e){const t=k(e);return!t||!Array.isArray(t.result_semantics)?[]:t.result_semantics.map(n=>String(n||"").trim()).filter(Boolean)}function ie(e){return String(e?.user_priority||"p2").trim().toLowerCase()||"p2"}function rt(e){const t=String(e?.presentation_semantic||"").trim();return t||xe(e?.action_key)[0]||""}function na(e){const t=String(e||"").trim().toLowerCase();return t==="p0"?"P0":t==="p1"?"P1":"P2"}function ra(e){return{primary_status:"\u72B6\u6001",primary_list:"\u4E3B\u4EFB\u52A1",supporting_list:"\u652F\u6491\u5217\u8868",copyable_secret:"\u51ED\u8BC1",endpoint_list:"\u5730\u5740",multiline_prompt:"\u63D0\u793A\u8BCD",next_step:"\u4E0B\u4E00\u6B65",supporting_detail:"\u6458\u8981",debug_only:"\u8C03\u8BD5"}[String(e||"").trim()]||"\u6982\u89C8"}function ce(e,t){return(e||[]).includes(t)}function aa(e){const t=new Set;return(e||[]).filter(n=>{const r=String(n||"").trim();return!r||t.has(r)?!1:(t.add(r),!0)})}function oa(e){return aa([rt(e),...xe(e?.action_key)])}function sa(e,t){const n=ia(e),r=ba(t),a=r===1||x(t?.key),s=a?"auto":"minmax(190px, auto)",l=a?"auto":"minmax(190px, 1fr)";return{areas:n,contentFlow:a,gridStyle:[`--tui-dashboard-areas-desktop: ${at(n,r,!0)}`,`--tui-dashboard-areas-tablet: ${at(n,2)}`,`--tui-dashboard-areas-mobile: ${at(n,1)}`,`--tui-dashboard-rows-desktop: ${ot(n,r,s)}`,`--tui-dashboard-rows-tablet: ${ot(n,2,l)}`,`--tui-dashboard-rows-mobile: ${ot(n,1,"auto")}`].join("; ")}}function ia(e){const t=new Map;return e.map((n,r)=>{const a=n.layout_area||n.key||`panel-${r+1}`,s=ca(a)||`panel_${r+1}`,l=t.get(s)||0;return t.set(s,l+1),l?`${s}_${l+1}`:s})}function ca(e){const t=String(e||"").trim().toLowerCase().replace(/[^a-z0-9_-]+/g,"_").replace(/^[-0-9]+/,"").replace(/_+/g,"_").replace(/^_+|_+$/g,"");return t&&t!=="none"?t:""}function at(e,t,n=!1){return hn(e,t).map(a=>`"${(n?la(a):ua(a,t)).join(" ")}"`).join(" ")}function ot(e,t,n){const r=Math.max(1,hn(e,t).length);return Array.from({length:r},()=>n).join(" ")}function hn(e,t){const n=e.length?e:["panel_1"],r=[];for(let a=0;a<n.length;a+=t)r.push(n.slice(a,a+t));return r}function la(e){const t=Math.floor(12/e.length);let n=12-t*e.length;return e.flatMap(r=>{const a=t+(n>0?1:0);return n-=1,Array.from({length:a},()=>r)})}function ua(e,t){const n=[...e],r=n.at(-1)||"panel_1";for(;n.length<t;)n.push(r);return n}function da(e){if(!e)return!1;const t=String(e.method||"GET").trim().toUpperCase(),n=String(e.risk||"read").trim().toLowerCase(),r=o.screen?.screen||{},a=String(r.audience||"")==="admin"&&String(e.screen_key||"")===String(r.key||"");return["GET","HEAD","OPTIONS"].includes(t)&&(n==="read"||n==="admin"&&a)&&tt(e).length===0}async function le(e){const t=i.main.querySelector(`[data-dashboard-panel="${CSS.escape(e.key)}"]`);if(!t)return;if(!e.action_key){t.innerHTML=R(e,z(e,e.empty_message||"\u7B49\u5F85\u53D1\u5E03\u6570\u636E\u6E90\u3002")),F(t);return}const n=x(o.screen?.screen?.key)?vr(e):"",r=k(e.action_key);if(!n&&!da(r)){t.innerHTML=R(e,pa(e,r)),F(t);return}try{let a=null,s=null;if(typeof C.loadDashboardPanel=="function"){const l=await C.loadDashboardPanel(e,{actionRunUrl:Oe,fetchJson:E,screen:o.screen});l&&(a=l.view_model||l,s=l.badge||ze(a.rows||[]))}if(!a)if(n){const u=(await Xt())?.[n]||{};a=ya(e,u),s=u?.badge?{blockedCount:Number(u.badge.blocked_count||0),warningCount:Number(u.badge.warning_count||0)}:ze(a.rows||[])}else a=(await E(Oe(e.action_key),{method:"POST",body:JSON.stringify({params:{}})})).view_model,s=ze(Array.isArray(a?.rows)?a.rows:[]);if(x(o.screen?.screen?.key)&&(o.homePanelBadges[e.key]=s),ga(e,a,t)||(t.innerHTML=R(e,wn(e,a)),ue(t),st(t,e),F(t),Pe(t)),x(o.screen?.screen?.key)){const l=t.querySelector("[data-panel-badge]");l&&(l.innerHTML=Z(o.homePanelBadges[e.key],{compact:!0}))}Me()}catch(a){t.innerHTML=R(e,Ge(e,a)),F(t),Je(t,e)}}function R(e,t){const n=`
            <h3>
                <span>${c(e.title)}</span>
                <span class="tui-panel-heading-tools">
                    <span class="tui-panel-priority">${c(na(ie(e)))}</span>
                    <span class="tui-panel-semantic">${c(ra(rt(e)))}</span>
                    <span data-panel-badge></span>
                    ${ma(e)}
                </span>
            </h3>
            ${e.note?`<div class="tui-panel-caption">${c(e.note)}</div>`:""}
            ${t}
        `;return fa(e)?`
            <details class="tui-panel-disclosure">
                <summary>\u5C55\u5F00${c(e.title)}</summary>
                ${n}
            </details>
        `:n}function pa(e,t){if(!t)return z(e,e.empty_message||"\u5F53\u524D\u4EFB\u52A1\u6682\u4E0D\u53EF\u7528\u3002");const n=String(t.submit_label||t.label||"\u7EE7\u7EED").trim();return`
            <div class="tui-dashboard-action-prompt">
                <p>${c(e.note||t.description||"\u586B\u5199\u5FC5\u8981\u4FE1\u606F\u540E\u7EE7\u7EED\u3002")}</p>
                <button
                    type="button"
                    class="tui-entry-action"
                    data-dashboard-open
                    data-dashboard-target="${c(bn(e))}"
                    data-dashboard-action="${c(t.key)}"
                >${c(n)}</button>
            </div>
        `}function fa(e){return ie(e)==="p2"&&!x(o.screen?.screen?.key)}function ma(e){const t=bn(e),n=String(e?.action_key||"").trim();return!t&&!n?"":`
            <button
                class="tui-dashboard-open"
                type="button"
                data-dashboard-open
                data-dashboard-target="${c(t)}"
                data-dashboard-action="${c(n)}"
                aria-label="\u6253\u5F00${c(e.title||"\u9762\u677F")}"
            >\u6253\u5F00</button>
        `}function F(e){e.querySelectorAll("[data-dashboard-open]").forEach(t=>{t.dataset.dashboardOpenBound!=="true"&&(t.dataset.dashboardOpenBound="true",t.addEventListener("click",n=>{n.preventDefault(),n.stopPropagation(),ta(t.dataset.dashboardTarget,t.dataset.dashboardAction)}))})}function ga(e,t,n){const r=String(t?.renderer||"").trim();if(!r||je.has(r))return!1;const a=Y.get(r);if(!a)return!1;n.innerHTML=R(e,`<div class="tui-extension-host is-dashboard" data-renderer="${c(r)}"></div>`);const s=n.querySelector(".tui-extension-host");try{a({viewModel:t,container:s,runtimeConfig:w,escapeHtml:c})}catch{s.innerHTML=T("\u6269\u5C55\u89C6\u56FE\u6682\u65F6\u4E0D\u53EF\u7528\u3002",["\u8BF7\u7A0D\u540E\u91CD\u8BD5\uFF0C\u6216\u6539\u7528\u9ED8\u8BA4\u4EFB\u52A1\u67E5\u770B\u6570\u636E\u3002"])}return ue(n),F(n),!0}function wn(e,t){return t?t.stale&&e.stale_message?z(e,e.stale_message):Fn(t)?gt(t):e.kind==="regime_quadrant"?wa(t):t.kind==="chart"?mt(t,{compact:!0}):t.kind==="image"?Bn(t,{compact:!0}):t.kind==="kpi_trend"?In(t,{compact:!0}):t.kind==="table_chart"?Dn(t,{compact:!0}):t.kind==="host_slot"?Nn(t,{compact:!0}):t.kind==="custom"?gt(t):t.kind==="datagrid"?kn(e,t):t.kind==="detail"?$a(e,t):`<div class="tui-message">${c(t.message||t.status||"\u6B63\u5E38")}</div>`:z(e,e.empty_message||"\u6682\u65E0\u53EF\u663E\u793A\u6570\u636E\u3002")}function ya(e,t){const n=Array.isArray(t?.rows)?t.rows:[],r=(Array.isArray(e?.columns)?e.columns:[]).map(a=>({key:String(a?.key||"").trim(),label:String(a?.label||a?.key||"").trim()})).filter(a=>a.key);return{kind:"datagrid",title:e?.title||"",status:String(t?.status||"ok"),columns:r,rows:n,total:Number(t?.total||n.length||0),empty_message:"\u6682\u65E0\u6570\u636E",empty_guidance:[]}}function ba(e){if(typeof _.dashboardDesktopColumns=="function")return _.dashboardDesktopColumns(e,w.host||{});throw new Error("AgomTUI Runtime core is missing dashboardDesktopColumns")}function ha(e){const t=String(e||"").trim().toLowerCase();return[{aliases:["recovery","\u590D\u82CF"],left:"25%",top:"25%",label:"\u590D\u82CF\u8C61\u9650"},{aliases:["overheat","\u8FC7\u70ED"],left:"75%",top:"25%",label:"\u8FC7\u70ED\u8C61\u9650"},{aliases:["deflation","recession","\u901A\u7F29","\u8870\u9000"],left:"25%",top:"75%",label:"\u901A\u7F29\u8C61\u9650"},{aliases:["stagflation","\u6EDE\u80C0"],left:"75%",top:"75%",label:"\u6EDE\u80C0\u8C61\u9650"}].find(r=>r.aliases.some(a=>t.includes(a)))||null}function wa(e){const t=Ta(e.fields||[]),n=Ce(t,["current_regime","dominant_regime","regime","regime_name","state","name"])||"UNKNOWN",r=Sn(Ce(t,["confidence","regime_confidence","confidence_pct"])),a=Ce(t,["trend","movement","transition_target","status"])||"-",s=Ce(t,["warning","transition_warning","risk","alerts"])||"-",l=ha(n);return`
            <div class="tui-quadrant">
                <div class="q q-recovery">\u590D\u82CF<br><strong>RECOVERY</strong></div>
                <div class="q q-overheat">\u8FC7\u70ED<br><strong>OVERHEAT</strong></div>
                <div class="q q-recession">\u8870\u9000<br><strong>RECESSION</strong></div>
                <div class="q q-stagflation">\u6EDE\u80C0<br><strong>STAGFLATION</strong></div>
                <div class="q-axis-x"></div>
                <div class="q-axis-y"></div>
                ${l?`<div class="q-marker" style="left:${l.left};top:${l.top}" role="img" aria-label="${c(l.label)}">\u25C6</div>`:""}
            </div>
            <div class="tui-dash-lines">
                <div>\u5F53\u524D\u5224\u65AD: <strong class="tui-green">${c(n)}</strong></div>
                <div>\u7F6E\u4FE1\u5EA6: <strong>${c(r)}</strong>\u3000\u8D8B\u52BF: <strong class="tui-green">${c(a)}</strong></div>
                <div>\u62D0\u70B9\u9884\u8B66: ${c(s)}</div>
            </div>
        `}function Sn(e){const t=Number(e);return Number.isFinite(t)?`${(Math.abs(t)<=1?t*100:t).toFixed(1).replace(/\.0$/,"")}%`:H(e)}function kn(e,t){const n=(t.rows||[]).slice(0,Number(e.max_rows||8)),a=(Array.isArray(e.columns)?e.columns:[]).filter(m=>n.some(f=>Object.prototype.hasOwnProperty.call(f,m.key))),l=(a.length?a:t.columns||[]).filter(m=>n.some(f=>Object.prototype.hasOwnProperty.call(f,m.key))).slice(0,6);if(!n.length||!l.length)return z(e,e.empty_message||"\u6682\u65E0\u8868\u683C\u6570\u636E\u3002");const u=Array.isArray(e.row_actions)?e.row_actions:[],d=l.map(m=>m.label||m.key);return u.length&&d.push("\u64CD\u4F5C"),`
            <table class="tui-mini-table">
                <thead><tr>${d.map((m,f)=>`<th class="${u.length&&f===d.length-1?"tui-row-actions-header":""}">${c(m)}</th>`).join("")}</tr></thead>
                <tbody>
                    ${n.map(m=>`
                        <tr>
                            ${l.map(f=>{const g=H(m[f.key]);return`<td class="${An(g,f.label||f.key)}">${c(g)}</td>`}).join("")}
                            ${u.length?`<td class="tui-row-actions-cell">${Sa(e,m)}</td>`:""}
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `}function Sa(e,t){return`<div class="tui-row-actions">${(Array.isArray(e?.row_actions)?e.row_actions:[]).map(r=>{const a=k(r.action_key),s=Object.fromEntries(Object.entries(r.param_map||{}).map(([u,d])=>[u,t?.[d]])),l=ka(r.label_template,t);return`
                <button
                    class="tui-row-action"
                    type="button"
                    data-dashboard-row-action
                    data-row-action-key="${c(r.action_key)}"
                    data-row-action-params="${c(JSON.stringify(s))}"
                    aria-label="${c(l)}"
                    title="${c(l)}"
                >${c(a?.label||"\u64CD\u4F5C")}</button>
            `}).join("")}</div>`}function ka(e,t){return String(e||"\u64CD\u4F5C").replace(/\{([^{}]+)\}/g,(n,r)=>String(t?.[r]??"-"))}function st(e,t){e.querySelectorAll("[data-dashboard-row-action]").forEach(n=>{n.dataset.rowActionBound!=="true"&&(n.dataset.rowActionBound="true",n.addEventListener("click",async r=>{r.preventDefault(),r.stopPropagation();let a={};try{a=JSON.parse(n.dataset.rowActionParams||"{}")}catch{p("\u884C\u64CD\u4F5C\u53C2\u6570\u4E0D\u53EF\u7528");return}n.disabled=!0;try{const s=k(n.dataset.rowActionKey),l=String(s?.method||"GET").trim().toUpperCase(),u=!["GET","HEAD","OPTIONS"].includes(l),d=(t.row_actions||[]).find(g=>g.action_key===n.dataset.rowActionKey)||{},m=String(d.result_panel_key||"").trim(),f=String(d.refresh_panel_key||"").trim();if(m||f){await $(n.dataset.rowActionKey,null,{params:a,dashboardResultPanelKey:m,dashboardRefreshPanelKey:f});return}await $(n.dataset.rowActionKey,null,u?{params:a,dashboardPanelKey:t.key}:{params:a})}finally{n.disabled=!1}}))})}function $a(e,t){const n=oa(e);if(n.length)return $n(t,n,{compact:!0,panel:e});const r=vn(t.fields||[],e).slice(0,Number(e.max_rows||8));if(!r.length){const a=(t.nested||[]).slice(0,Number(e.max_rows||8));return a.length?xn(["\u9879\u76EE","\u6570\u91CF"],a.map(s=>[s.label,s.count])):z(e,"\u6682\u65E0\u6458\u8981\u6570\u636E\u3002")}return`
            ${xn(["\u9879\u76EE","\u503C"],r.map(a=>[a.label,a.value]))}
            ${e.note?`<div class="tui-panel-note">${c(e.note)}</div>`:""}
        `}function va(){return xe(o.lastAction)}function $n(e,t,n={}){const r=vn(e.fields||[],n.panel).slice(0,Number(n.panel?.max_rows||12)),a=(e.nested||[]).slice(0,Number(n.panel?.max_rows||12)),s=["tui-semantic-detail",n.compact?"is-compact":"",ce(t,"primary_status")?"is-primary-status":"",ce(t,"copyable_secret")?"is-copyable-secret":"",ce(t,"endpoint_list")?"is-endpoint-list":"",ce(t,"multiline_prompt")?"is-multiline-prompt":""].filter(Boolean).join(" "),l=ce(t,"primary_status")?`
                <div class="tui-status-hero">
                    <strong>${c(e.title||"\u72B6\u6001")}</strong>
                    <span class="tui-status-pill">${c(e.status||"\u6B63\u5E38")}</span>
                </div>
            `:"",u=r.filter(y=>Ae(y)==="secret"&&it(y.value)),d=r.filter(y=>Ae(y)==="copyable"&&it(y.value)),m=r.filter(y=>Ae(y)==="multiline"&&it(y.value)),f=r.filter(y=>Ae(y)==="metadata"),g=[u.length?xa(u):"",d.length?Aa(d):"",f.length?_n(f):"",m.length?Ca(m):""].filter(Boolean).join(""),b=a.length?`<div class="tui-nested-list">${a.map(y=>`<span>${c(y.label)}: ${c(y.count)} \u884C</span>`).join("")}</div>`:"";return`
            <section class="${s}">
                ${l}
                ${g||z(n.panel||{},"\u6682\u65E0\u6458\u8981\u6570\u636E\u3002")}
                ${b}
            </section>
        `}function it(e){return e!=null&&String(e).trim()!==""&&String(e).trim()!=="-"}function vn(e,t){const n=Array.isArray(t?.field_rules)?t.field_rules:[],r=new Map(n.map(a=>[String(a?.label||"").trim(),a]));return(e||[]).flatMap(a=>{const s=r.get(String(a?.label||"").trim());return s?.visible===!1?[]:[{...a,value:_a(a?.value,s?.format)}]})}function _a(e,t){const n=String(t||"text").trim();if(n==="money"){const r=Number(e);return Number.isFinite(r)?`${r.toLocaleString("zh-CN",{maximumFractionDigits:2})} \u5143`:H(e)}if(n==="percentage")return Sn(e);if(n==="datetime"){const r=Date.parse(String(e||""));return Number.isFinite(r)?new Date(r).toLocaleString("zh-CN",{hour12:!1}):H(e)}return H(e)}function _n(e){return e.length?`
            <dl class="tui-detail-grid">
                ${e.map(t=>`
                    <dt>${c(t.label)}</dt>
                    <dd>${c(H(t.value))}</dd>
                `).join("")}
            </dl>
        `:""}function Ae(e){const t=String(e?.presentation||"metadata").trim().toLowerCase();return["secret","copyable","multiline","metadata"].includes(t)?t:"metadata"}function xa(e){return`
            <div class="tui-copy-stack">
                ${e.map(t=>`
                    <div class="tui-copy-row is-secret">
                        <div class="tui-copy-head">
                            <span>${c(t.label)}</span>
                            <span class="tui-copy-controls">
                                <button
                                    class="tui-copy-action"
                                    type="button"
                                    data-secret-toggle
                                    data-secret-visible="false"
                                    data-secret-label="${c(t.label)}"
                                    aria-label="\u663E\u793A${c(t.label)}"
                                >\u663E\u793A</button>
                                <button
                                    class="tui-copy-action"
                                    type="button"
                                    data-copy-value="${c(t.value)}"
                                    data-copy-label="${c(t.label)}"
                                >\u590D\u5236</button>
                            </span>
                        </div>
                        <code data-secret-value="${c(t.value)}">\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022</code>
                    </div>
                `).join("")}
            </div>
        `}function Aa(e){return e.length?`
            <div class="tui-copy-stack">
                ${e.map(t=>`
                    <div class="tui-copy-row">
                        <div class="tui-copy-head">
                            <span>${c(t.label)}</span>
                            <button
                                class="tui-copy-action"
                                type="button"
                                data-copy-value="${c(t.value)}"
                                data-copy-label="${c(t.label)}"
                            >\u590D\u5236</button>
                        </div>
                        <code>${c(t.value)}</code>
                    </div>
                `).join("")}
            </div>
        `:""}function Ca(e){return e.length?`
            <div class="tui-copy-stack">
                ${e.map(t=>{const n=String(t?.key||"")==="access_package";return`
                    <section class="tui-copy-block-card${n?" is-dominant":""}">
                        <div class="tui-copy-head">
                            <strong>${c(t.label)}</strong>
                            <button
                                class="tui-copy-action"
                                type="button"
                                data-copy-value="${c(t.value)}"
                                data-copy-label="${c(t.label)}"
                            >${n?"\u590D\u5236\u5B8C\u6574\u63A5\u5165\u5305":"\u590D\u5236"}</button>
                        </div>
                        <pre class="tui-copy-block">${c(t.value)}</pre>
                    </section>
                `}).join("")}
            </div>
        `:""}async function La(e){const t=String(e??"");if(navigator.clipboard&&typeof navigator.clipboard.writeText=="function"){await navigator.clipboard.writeText(t);return}const n=document.createElement("textarea");n.value=t,n.setAttribute("readonly","readonly"),n.style.position="fixed",n.style.opacity="0",n.style.pointerEvents="none",document.body.appendChild(n),n.select(),document.execCommand("copy"),document.body.removeChild(n)}function ue(e=document){e.querySelectorAll("[data-secret-toggle]").forEach(t=>{t.dataset.secretBound!=="true"&&(t.dataset.secretBound="true",t.addEventListener("click",n=>{n.preventDefault(),n.stopPropagation();const r=t.closest(".tui-copy-row")?.querySelector("[data-secret-value]");if(!r)return;const a=t.dataset.secretVisible==="true",s=String(t.dataset.secretLabel||"\u51ED\u8BC1");t.dataset.secretVisible=a?"false":"true",t.textContent=a?"\u663E\u793A":"\u9690\u85CF",t.setAttribute("aria-label",`${a?"\u663E\u793A":"\u9690\u85CF"}${s}`),r.textContent=a?"\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022":r.dataset.secretValue}))}),e.querySelectorAll("[data-copy-value]").forEach(t=>{t.dataset.copyBound!=="true"&&(t.dataset.copyBound="true",t.addEventListener("click",async n=>{n.preventDefault(),n.stopPropagation();const r=String(t.dataset.copyLabel||"\u5185\u5BB9").trim(),a=t.textContent;try{await La(t.dataset.copyValue||""),t.textContent="\u5DF2\u590D\u5236",p(`${r}\u5DF2\u590D\u5236`)}catch{t.textContent="\u590D\u5236\u5931\u8D25",p(`${r}\u590D\u5236\u5931\u8D25`)}window.setTimeout(()=>{t.textContent=a},1200)}))})}function Ta(e){return e.reduce((t,n)=>(t[String(n.key||n.label||"").toLowerCase()]=n.value,t[String(n.label||"").toLowerCase()]=n.value,t),{})}function Ce(e,t){for(const n of t){const r=e[String(n).toLowerCase()];if(r!=null&&r!=="")return r}return""}function z(e,t){return`
            <div class="tui-panel-placeholder">
                <div>${c(t)}</div>
                ${e.note?`<small>${c(e.note)}</small>`:""}
            </div>
        `}function xn(e,t,n){return`
            <table class="tui-mini-table">
                <thead><tr>${e.map(r=>`<th>${c(r)}</th>`).join("")}</tr></thead>
                <tbody>
                    ${t.map((r,a)=>`
                        <tr class="${a===n?"is-hot":""}">
                            ${r.map((s,l)=>`<td class="${An(s,e[l])}">${c(s)}</td>`).join("")}
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `}function An(e,t=""){const n=String(e),r=String(t||"");return["\u6807\u7684","\u4EE3\u7801","\u540D\u79F0","\u80A1\u7968","\u8D44\u4EA7","\u8BC1\u5238"].some(a=>r.includes(a))?"":/^-\d+(?:\.\d+)?%?$/.test(n.trim())||n.includes("\u6682\u505C")||n.includes("\u89E6\u53D1")||n.includes("\u5931\u8D25")||n.includes("\u672A\u8FD0\u884C")?"is-red":n.includes("\u89C2\u5BDF")||/(进行中|运行中|处理中|同步中|排队中)/.test(n)?"is-yellow":n.includes("\u6B63\u5E38")||n.includes("\u8FD0\u884C")||n.includes("\u6210\u529F")||n.includes("%")?"is-green":""}function v(e){const t=String(e.task_tier||"").toLowerCase();return["primary","support","advanced","operation"].includes(t)?t:"support"}function de(e){return e.reduce((t,n)=>{const r=v(n);r==="advanced"?t.advanced+=1:r==="support"?t.support+=1:r==="operation"?t.operation+=1:t.primary+=1;const a=String(n.risk||"").toLowerCase();return a==="write"&&(t.write+=1),a==="ai"&&(t.ai+=1),t},{primary:0,support:0,advanced:0,operation:0,write:0,ai:0})}function Cn(e,t){if(!e.length){i.actions.innerHTML='<div class="tui-empty-state">\u5F53\u524D\u5DE5\u4F5C\u533A\u6682\u65E0\u53EF\u6267\u884C\u4EFB\u52A1\u3002</div>';return}const n=e.filter(y=>v(y)==="primary"),r=e.filter(y=>v(y)==="support"),a=e.filter(y=>v(y)==="advanced"),s=n.length>0,l=de(e),u=Ee(e),d=Ea(e),m=qa(t),f={remaining:m.primaryOperationLimit};i.actions.innerHTML=`
            <div class="tui-action-brief">
                <div>
                    <strong>${c(t&&t.label||"\u5F53\u524D\u5DE5\u4F5C\u533A")}</strong>
                    <span data-action-summary>\u4E3B\u6D41\u7A0B ${u.completed}/${u.total} / \u64CD\u4F5C ${l.operation} / \u652F\u6491 ${l.support} / \u9AD8\u7EA7 ${l.advanced}</span>
                </div>
                <label class="tui-action-filter">
                    <span>\u4EFB\u52A1</span>
                    <input type="search" value="${c(o.actionFilterText)}" placeholder="\u8F93\u5165\u4E1A\u52A1\u8BCD" data-action-filter>
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
            ${d.map(y=>Ba(y,m,f)).join("")}
            <div class="tui-empty-state" data-action-filter-empty hidden>\u6CA1\u6709\u5339\u914D\u4EFB\u52A1\u3002\u6E05\u7A7A\u7B5B\u9009\u540E\u67E5\u770B\u5168\u90E8\u3002</div>
        `,i.actions.dataset.renderedScreenKey=t&&t.key||"";const g=i.actions.querySelector("[data-action-filter]"),b=()=>{o.actionFilterText=g?g.value:o.actionFilterText,V(e,t)};g?.addEventListener("input",y=>{y.isComposing||b()}),g?.addEventListener("compositionend",b),i.actions.querySelector("[data-clear-action-filter]")?.addEventListener("click",()=>{o.actionFilterText="",g.value="",V(e,t),g.focus(),p("\u4EFB\u52A1\u7B5B\u9009\u5DF2\u6E05\u9664")}),i.actions.querySelector("[data-toggle-support]")?.addEventListener("click",()=>{o.showSupportTasks=!o.showSupportTasks,V(e,t),p(o.showSupportTasks?"\u652F\u6491\u68C0\u67E5\u5DF2\u663E\u793A":"\u652F\u6491\u68C0\u67E5\u5DF2\u9690\u85CF")}),i.actions.querySelector("[data-toggle-advanced]")?.addEventListener("click",()=>{o.showAdvancedQueries=!o.showAdvancedQueries,V(e,t),p(o.showAdvancedQueries?"\u9AD8\u7EA7\u67E5\u8BE2\u5DF2\u663E\u793A":"\u9AD8\u7EA7\u67E5\u8BE2\u5DF2\u9690\u85CF")}),Ra(),V(e,t),Le()}function Pa(e,t,n){if(n)return Fa(e,n);if(!t)return!0;const r=v(e);return r==="operation"||r==="primary"?!0:r==="support"?o.showSupportTasks:r==="advanced"?o.showAdvancedQueries:!1}function V(e,t){const n=e.some(b=>v(b)==="primary"),r=o.actionFilterText.trim().toLowerCase();let a=0;i.actions.querySelectorAll("[data-action-ui-key]").forEach(b=>{const y=k(Se(b)),h=!!(y&&Pa(y,n,r));if(b.hidden=!h,h&&(a+=1),y){const q=Fe(y.key);b.classList.toggle("is-completed",q);const U=b.querySelector("[data-action-meta]");U&&(U.textContent=tn(y,q))}}),i.actions.querySelectorAll(".tui-action-group").forEach(b=>{b.hidden=!b.querySelector("[data-action-ui-key]:not([hidden])")});const s=de(e),l=Ee(e),u=i.actions.querySelector("[data-action-summary]");u&&(u.textContent=`\u4E3B\u6D41\u7A0B ${l.completed}/${l.total} / \u64CD\u4F5C ${s.operation} / \u652F\u6491 ${s.support} / \u9AD8\u7EA7 ${s.advanced}${r?` / \u5339\u914D ${a}`:""}`);const d=i.actions.querySelector("[data-action-filter-empty]");d&&(d.hidden=a>0);const m=i.actions.querySelector("[data-clear-action-filter]");m&&(m.hidden=!r);const f=i.actions.querySelector("[data-toggle-support]");f&&(f.textContent=o.showSupportTasks||!n?"\u9690\u85CF\u652F\u6491":"\u663E\u793A\u652F\u6491");const g=i.actions.querySelector("[data-toggle-advanced]");g&&(g.textContent=o.showAdvancedQueries||!n?"\u9690\u85CF\u9AD8\u7EA7":"\u663E\u793A\u9AD8\u7EA7")}function Ra(){i.actions.querySelectorAll("[data-action-ui-key]").forEach(e=>{e.addEventListener("submit",r=>{r.preventDefault(),r.stopPropagation(),ke(e)}),e.querySelector(".tui-action-button")?.addEventListener("click",r=>{r.preventDefault(),r.stopPropagation(),ke(e)}),e.querySelector("[data-fill-from-row]")?.addEventListener("click",r=>{r.preventDefault(),r.stopPropagation(),ct(e)})})}function Fa(e,t){return[e.label,e.description,e.task_group,en(e),re(e),...(e.fields||[]).map(r=>`${r.label} ${r.key}`)].join(" ").toLowerCase().includes(t)}function Ea(e){const t=[],n=new Map;return e.forEach(r=>{const a=v(r),s=a==="operation"?"00 \u53EF\u6267\u884C\u64CD\u4F5C":r.task_group||"\u6838\u5FC3\u4EFB\u52A1";if(!n.has(s)){const u={label:s,tier:a,actions:[],sequence:a==="operation"?-100:Number(r.sequence||999)};n.set(s,u),t.push(u)}const l=n.get(s);l.sequence=Math.min(l.sequence,a==="operation"?-100:Number(r.sequence||999)),l.actions.push(r)}),t.sort((r,a)=>r.sequence-a.sequence),t.forEach(r=>{r.actions.sort((a,s)=>Number(a.sequence||999)-Number(s.sequence||999))}),t}function qa(e){const t=e?.action_density||{},n=Number(t.primary_operation_limit),r=Number(t.task_group_limit);return{primaryOperationLimit:Number.isFinite(n)&&n>0?n:Number.POSITIVE_INFINITY,taskGroupLimit:Number.isFinite(r)&&r>0?r:Number.POSITIVE_INFINITY}}function Ba(e,t,n){const r=[],a=[];let s=0;return e.actions.forEach(l=>{const u=v(l),d=u==="primary"||u==="operation",m=s<t.taskGroupLimit,f=n.remaining>0;if(!d||m&&f){r.push(l),d&&(s+=1,n.remaining-=1);return}a.push(l)}),`
            <section class="tui-action-group tui-action-group-${c(e.tier)}">
                <div class="tui-action-group-title">${c(e.label)}</div>
                ${r.map(l=>Ln(l)).join("")}
                ${a.length?`
                    <details class="tui-action-overflow">
                        <summary>\u66F4\u591A\u4EFB\u52A1\uFF08${a.length}\uFF09</summary>
                        ${a.map(l=>Ln(l)).join("")}
                    </details>
                `:""}
            </section>
        `}function Ln(e){const t=(e.fields||[]).some(s=>s.input_type!=="hidden"),n=Fe(e.key),r=A(e.description||""),a=Ha(e);return`
            <form class="tui-action-form tui-action-risk-${c(e.risk||"read")} ${n?"is-completed":""}" data-action-ui-key="${c(O(e))}" novalidate>
                <button class="tui-action-button" type="button">
                    <span>
                        ${c(e.label)}
                        <span class="tui-action-meta" data-action-meta>${c(tn(e,n))}</span>
                    </span>
                </button>
                ${t?'<button class="tui-row-fill-button" type="button" data-fill-from-row>\u4ECE\u9009\u4E2D\u884C\u586B\u5145</button>':""}
                ${e.confirmation_required?'<div class="tui-action-confirm">\u63D0\u4EA4\u524D\u4F1A\u8981\u6C42\u786E\u8BA4</div>':""}
                ${r?`<div class="tui-action-desc">${c(r)}</div>`:""}
                ${(e.fields||[]).map(s=>dn(e,s)).join("")}
                <button class="tui-action-submit" type="submit">${c(a)}</button>
            </form>
        `}function Ha(e){return String(e.submit_label||"\u6267\u884C")}function Tn(e){let t=String(e||"").split(".").filter(Boolean);const n=new Set(["pk","id","int","str","uuid","slug","path","bool","float","decimal","date","datetime"]),r=[];(t[0]==="auto"||t[0]==="param")&&(t=t.slice(1)),t[0]==="api"&&t[2]==="api"&&(t=t.slice(3));for(const a of t){if(n.has(a))break;r.push(a)}return r.join(".")}function W(e){if(!e)return null;const t=k(o.lastAction);return{...e,__tui_source_action_key:t?t.key:"",__tui_source_resource_base:Tn(t?t.key:"")}}function Ia(e,t,n){const r=String(n||"");if(!["pk","id"].includes(r))return!0;const a=String(t&&t.__tui_source_resource_base?t.__tui_source_resource_base:""),s=Tn(e&&e.key);return!a||!s?!0:a===s}function Da(e,t){if(!e||!t)return!1;const n=(e.fields||[]).filter(r=>r.input_type!=="hidden");return n.length?n.some(r=>lt(t,r.key,e)!==void 0):!1}async function Na(e,t){const n={};if(!e)return n;const r=t&&t.fields||[];for(const a of r){const s=ut(e,a.key);if(!s)continue;if(a.input_type==="file"){s.files&&s.files.length&&(n[a.key]=await Ka(s.files[0]));continue}const l=pn(a,s.value,s.checked);(a.input_type==="checkbox"||l!=="")&&(n[a.key]=l)}return n}function Ka(e){return new Promise((t,n)=>{if(e&&Number(e.size)>gr){n(new Error("\u6587\u4EF6\u8D85\u8FC7 2MB\uFF0C\u8BF7\u6539\u7528\u66F4\u5C0F\u7684\u6587\u672C\u6587\u4EF6"));return}const r=new FileReader;r.addEventListener("load",()=>t(String(r.result||""))),r.addEventListener("error",()=>n(r.error||new Error("\u6587\u4EF6\u8BFB\u53D6\u5931\u8D25"))),r.readAsText(e,"utf-8")})}function ja(e,t={}){const{onlyIfEmpty:n=!1,silent:r=!1,focus:a=!1}=t;if(!e)return r||p("\u6CA1\u6709\u53EF\u586B\u5145\u7684\u4EFB\u52A1"),!1;const s=Pn();if(!s)return r||p("\u5148\u5728\u8868\u683C\u4E2D\u9009\u62E9\u4E00\u884C"),!1;const l=k(Se(e));if(!l)return r||p("\u4EFB\u52A1\u672A\u627E\u5230"),!1;const u=Un(s,l),d=l.fields||[];let m=0;return d.forEach(f=>{if(f.input_type==="hidden")return;const g=ut(e,f.key);if(!g||n&&(g.type==="checkbox"&&g.checked||g.type!=="checkbox"&&String(g.value||"").trim()!==""))return;const b=u[f.key];b==null||b===""||(g.type==="checkbox"?g.checked=!!b:g.value=String(b),m+=1)}),m?(r||p(`\u5DF2\u4ECE\u9009\u4E2D\u884C\u586B\u5145 ${m} \u9879`),a&&e.querySelector("input:not([type='hidden']),select,textarea")?.focus(),!0):(r||p("\u9009\u4E2D\u884C\u6CA1\u6709\u53EF\u5339\u914D\u5B57\u6BB5"),!1)}function ct(e){return ja(e,{focus:!0})}function lt(e,t,n){const r=typeof t=="object"&&t?t.key:t;if(Ia(n,e,r))for(const a of Oa(t,n)){const s=`__raw_${a}`;if(Object.prototype.hasOwnProperty.call(e,s)&&e[s]!==void 0&&e[s]!==null&&e[s]!=="")return e[s];if(Object.prototype.hasOwnProperty.call(e,a)&&e[a]!==void 0&&e[a]!==null&&e[a]!=="")return e[a]}}function ut(e,t){if(!e||!e.elements)return null;const n=typeof e.elements.namedItem=="function"?e.elements.namedItem(t):null;return n?typeof n.length=="number"&&!n.tagName?n[0]||null:n:e.querySelector(`[name="${CSS.escape(t)}"]`)}function Pn(){const e=W(o.visibleRows[o.selectedRowIndex]);return e||(o.currentViewModel&&o.currentViewModel.kind==="datagrid"?null:o.selectedRowContext)}function Le(){const e=Pn();i.actions.querySelectorAll("[data-action-ui-key]").forEach(t=>{const n=t.querySelector("[data-fill-from-row]");if(!n)return;const r=k(Se(t)),a=Da(r,e);n.disabled=!a,n.title=a?"\u4ECE\u5F53\u524D\u9009\u4E2D\u884C\u586B\u5145\u53EF\u5339\u914D\u53C2\u6570":"\u5F53\u524D\u9009\u4E2D\u884C\u6CA1\u6709\u53EF\u5339\u914D\u5B57\u6BB5"})}function Oa(e,t){const n=typeof e=="object"&&e?e:(t&&t.fields||[]).find(l=>l.key===e)||{key:e},r=String(n.key||""),a=String(n.semantic||"").trim(),s=[];return s.push(r),a&&(s.push(a),s.push(...Rn(a))),Array.isArray(n.aliases)&&s.push(...n.aliases),s.push(...Rn(r)),dt(s)}function Rn(e){const t=String(e||""),n=za();return Array.isArray(n[t])?n[t]:[]}function za(){return{...w.field_aliases||w.fieldAliases||{},...o.catalog&&o.catalog.field_aliases||{},...o.screen&&o.screen.field_aliases||{}}}function dt(e){return e.filter((t,n,r)=>String(t||"").trim()&&r.indexOf(t)===n)}async function S(e,t={}){const n=new AbortController,r=on(n);try{N(),P(),i.main.innerHTML='<div class="tui-loading">\u6B63\u5728\u52A0\u8F7D\u5DE5\u4F5C\u533A...</div>',p("\u52A0\u8F7D\u5DE5\u4F5C\u533A");const a=await E(wr(e),{signal:n.signal});return oe(r)?(I(),x(a?.screen?.key)&&(o.operatorHomePayload=null,o.operatorHomePromise=null),fn(a,t),t.suppressHistory||Ft(a?.screen?.key||e,{replace:!!t.replaceHistory}),te(),a):null}catch(a){return!oe(r)||a?.name==="AbortError"||(I(),Ue(),ae(a,{retryScreenKey:e})),null}}async function $(e,t,n={}){const r=k(e);if(!r){p("\u4EFB\u52A1\u672A\u627E\u5230");return}const a=r.key;if(Bt(a)){ee(a);return}const s=new AbortController,l=on(s);try{const u=String(n.dashboardResultPanelKey||"").trim(),d=String(n.dashboardRefreshPanelKey||"").trim(),m=!!u,f=!!d,g=m||f,b=n.params?{...n.params}:t?await Na(t,r):{};if(!oe(l))return;o.lastAction=a,o.lastParams=b,o.selectedRowIndex=0,Mt(r),N(),P(),m?(Object.prototype.hasOwnProperty.call(n,"dashboardResultPanelMarkup")||(n.dashboardResultPanelMarkup=Ua(u)),Wa(u,r)):!n.dashboardPanelKey&&!g&&(Ye(r,o.screen),sn(l,r));const y={params:b,confirmed:!!n.confirmed};n.confirmation&&(y.confirmation=n.confirmation),n.reauth&&(y.reauth=n.reauth);const h=await E(Oe(a),{method:"POST",body:JSON.stringify(y),signal:s.signal});if(!oe(l))return;if(I(),Array.isArray(h.missing_fields)&&h.missing_fields.length){o.lastRaw=null,!n.dashboardPanelKey&&!g&&pe(h.view_model),pt(n),xo(h,a,b,n),D(),p("\u7B49\u5F85\u8865\u586B");return}if(h.confirmation_required){o.lastRaw=null,!n.dashboardPanelKey&&!g&&pe(h.view_model),pt(n),Ao(h,a,b,n),D(),p("\u7B49\u5F85\u786E\u8BA4");return}if(h.password_challenge_required){o.lastRaw=null,!n.dashboardPanelKey&&!g&&pe(h.view_model),pt(n),Co(h,a,b,n),D(),p("\u7B49\u5F85\u9A8C\u5BC6");return}if(jo(r),o.lastRaw=h.debug?.raw_response??null,g){m&&Ga(u,h.view_model,r),f&&d!==u&&await Ma(d),D(),p(f?"\u64CD\u4F5C\u5B8C\u6210\uFF0C\u6CBB\u7406\u5DE5\u4F5C\u533A\u5DF2\u66F4\u65B0":"\u8BE6\u60C5\u5DF2\u5728\u5F53\u524D\u9875\u9762\u6253\u5F00"),te();return}if(n.dashboardPanelKey){D(),await Va(),p("\u64CD\u4F5C\u5B8C\u6210\uFF0C\u5217\u8868\u5DF2\u5237\u65B0"),te();return}_e(o.screen?.screen)||V(o.screen.actions||[],o.screen.screen),pe(h.view_model),yo(h,h.view_model),D(),p("\u8BFB\u53D6\u5B8C\u6210"),te()}catch(u){if(!oe(l))return;if(u?.name==="AbortError"){p("\u8BF7\u6C42\u5DF2\u53D6\u6D88");return}I();const d=String(n.dashboardResultPanelKey||"").trim();if(d){Ja(d,u);return}if(n.dashboardPanelKey){const f=(Array.isArray(o.screen?.screen?.dashboard_panels)?o.screen.screen.dashboard_panels:[]).find(b=>b.key===n.dashboardPanelKey),g=f?i.main.querySelector(`[data-dashboard-panel="${CSS.escape(f.key)}"]`):null;f&&g?(g.innerHTML=R(f,Ge(f,u)),F(g),Je(g,f)):ae(u)}else ae(u)}}async function Va(){const e=Array.isArray(o.screen?.screen?.dashboard_panels)?o.screen.screen.dashboard_panels:[];await Promise.all(e.map(t=>le(t)))}function G(e){return(Array.isArray(o.screen?.screen?.dashboard_panels)?o.screen.screen.dashboard_panels:[]).find(n=>n.key===e)||null}async function Ma(e){const t=G(e);t&&await le(t)}function Ua(e){const t=G(e);return(t?i.main.querySelector(`[data-dashboard-panel="${CSS.escape(t.key)}"]`):null)?.innerHTML||""}function pt(e={}){const t=String(e.dashboardResultPanelKey||"").trim();if(!t||!Object.prototype.hasOwnProperty.call(e,"dashboardResultPanelMarkup"))return;const n=G(t),r=n?i.main.querySelector(`[data-dashboard-panel="${CSS.escape(n.key)}"]`):null;!n||!r||(r.innerHTML=e.dashboardResultPanelMarkup,ue(r),st(r,n),F(r),Pe(r))}function Wa(e,t){const n=G(e),r=n?i.main.querySelector(`[data-dashboard-panel="${CSS.escape(n.key)}"]`):null;!n||!r||(r.innerHTML=R(n,`<div class="tui-loading">\u6B63\u5728\u6267\u884C${c(t.label||"\u5F53\u524D\u64CD\u4F5C")}...</div>`))}function Ga(e,t,n){const r=G(e),a=r?i.main.querySelector(`[data-dashboard-panel="${CSS.escape(r.key)}"]`):null;if(!r||!a)return;const s=xe(n.key),l={...r,action_key:n.key,presentation_semantic:s[0]||r.presentation_semantic};a.innerHTML=R(r,wn(l,t)),ue(a),F(a),st(a,l),Pe(a)}function Ja(e,t){const n=G(e),r=n?i.main.querySelector(`[data-dashboard-panel="${CSS.escape(n.key)}"]`):null;if(!n||!r){ae(t);return}r.innerHTML=R(n,Ge(n,t)),F(r),Je(r,n)}function pe(e){if(!e){bo("\u6CA1\u6709\u8FD4\u56DE\u53EF\u6E32\u67D3\u7684\u4E1A\u52A1\u89C6\u56FE\u3002");return}o.currentViewModel=e,$e(e.kind||"message"),i.mainTitle.textContent=(e.title||"\u89C6\u56FE").toUpperCase(),Ya(e,i.main)?et({preserveRowContext:!0}):e.kind==="datagrid"?Za(e):(et({preserveRowContext:!0}),Qa(e)),fo(),ue(i.main),e.kind!=="datagrid"&&me(e.pager||null),Le()}function Qa(e){if(Fn(e)){qn(e);return}({detail:po,chart:no,image:ro,kpi_trend:ao,table_chart:oo,host_slot:so,custom:qn,message:zn}[e.kind]||zn)(e)}function Ya(e,t){const n=String(e.renderer||"").trim();if(!n||je.has(n))return!1;const r=Y.get(n);if(!r)return!1;t.innerHTML=`
            <div class="tui-view-status">${c(e.status||"\u6B63\u5E38")} / ${c(e.title||n)}</div>
            ${fe(e)}
            <div class="tui-extension-host" data-renderer="${c(n)}"></div>
        `;const a=t.querySelector(".tui-extension-host");try{r({viewModel:e,container:a,runtimeConfig:w,escapeHtml:c})}catch{a.innerHTML=T("\u6269\u5C55\u89C6\u56FE\u6682\u65F6\u4E0D\u53EF\u7528\u3002",["\u8BF7\u7A0D\u540E\u91CD\u8BD5\uFF0C\u6216\u6539\u7528\u9ED8\u8BA4\u4EFB\u52A1\u67E5\u770B\u6570\u636E\u3002"])}return!0}function Fn(e){const t=String(e.renderer||"").trim();return!t||je.has(t)?!1:["chart","kpi_trend","table_chart","host_slot","custom"].includes(e.kind)}function Za(e){o.currentViewModel=e,o.currentColumns=e.columns||[],o.currentRows=e.rows||[],o.clientPage=1,Te(!1)}function Xa(e){const t=o.filterText.trim().toLowerCase();return t?Object.values(e||{}).some(n=>String(n??"").toLowerCase().includes(t)):!0}function Te(e){if(!o.currentViewModel||o.currentViewModel.kind!=="datagrid"){e&&p("\u5F53\u524D\u89C6\u56FE\u4E0D\u53EF\u7B5B\u9009");return}e&&(o.clientPage=1),o.visibleRows=o.currentRows.filter(Xa),o.selectedRowIndex=Math.min(o.selectedRowIndex,Math.max(0,o.visibleRows.length-1)),En(),e&&p(o.filterText?`\u7B5B\u9009 ${o.visibleRows.length}/${o.currentRows.length}`:"\u7B5B\u9009\u5DF2\u6E05\u9664")}function En(){const e=o.currentViewModel,t=o.currentColumns,n=o.visibleRows,r=!e.pager&&typeof _.clientPage=="function"?_.clientPage(n,o.clientPage,o.clientPageSize):{rows:n,pager:null},a=r.rows,s=e.pager||r.pager;o.lastPager=s;const l=r.pager?(r.pager.page-1)*o.clientPageSize:0,u=o.filterText?` / \u7B5B\u9009: ${o.filterText} (${n.length}/${o.currentRows.length})`:"",d=o.filterText?"\u6CA1\u6709\u5339\u914D\u7684\u8BB0\u5F55\u3002":e.empty_message||"\u6682\u65E0\u53EF\u663E\u793A\u6570\u636E\u3002",m=a.length&&t.length?`
                <table>
                    <thead>
                        <tr>${t.map(f=>`<th>${c(f.label)}</th>`).join("")}</tr>
                    </thead>
                    <tbody>
                        ${a.map((f,g)=>{const b=l+g;return`
                            <tr data-row-index="${b}" class="${b===o.selectedRowIndex?"is-selected":""}">
                                ${t.map(y=>{const h=H(f[y.key]);return`<td title="${c(h)}">${c(h)}</td>`}).join("")}
                            </tr>
                        `}).join("")}
                    </tbody>
                </table>
            `:T(d,o.filterText?["\u6E05\u7A7A\u7B5B\u9009\u540E\u67E5\u770B\u5168\u90E8\u8BB0\u5F55\u3002"]:e.empty_guidance,o.filterText?[]:e.next_steps);i.main.innerHTML=`
            <div class="tui-view-status">${c(e.status)} / ${c(e.title)}${c(u)}</div>
            ${fe(e)}
            <div class="tui-datagrid" role="grid" tabindex="0" aria-label="${c(e.title)}">
                ${m}
            </div>
            ${eo(s)}
        `,i.main.querySelectorAll("[data-row-index]").forEach(f=>{f.addEventListener("click",()=>Mn(Number(f.dataset.rowIndex||0))),f.addEventListener("dblclick",()=>wt())}),i.main.querySelectorAll("[data-page-delta]").forEach(f=>{f.addEventListener("click",()=>ht(Number(f.dataset.pageDelta||0)))}),ft(i.main,e.next_steps),a.length?((o.selectedRowIndex<l||o.selectedRowIndex>=l+a.length)&&(o.selectedRowIndex=l),l===0?o.selectedRowContext=W(a[o.selectedRowIndex]):o.selectedRowContext=W(o.visibleRows[o.selectedRowIndex])):o.selectedRowContext=null,me(s),bt(),Le()}function eo(e){if(!e)return"";const t=e.page??"-",n=e.total_pages??"-",r=e.total_rows??0;return`
            <div class="tui-datagrid-pager" aria-label="\u5206\u9875">
                <button type="button" data-page-delta="-1" ${e.has_previous?"":"disabled"}>\u4E0A\u4E00\u9875</button>
                <span>\u7B2C ${c(t)} / ${c(n)} \u9875</span>
                <span>\u5171 ${c(r)} \u884C</span>
                <button type="button" data-page-delta="1" ${e.has_next?"":"disabled"}>\u4E0B\u4E00\u9875</button>
            </div>
        `}function T(e,t,n=[]){const r=(t||[]).filter(Boolean),a=Array.isArray(n)?n:[];return`
            <div class="tui-empty-state tui-empty-guidance">
                <strong>${c(e)}</strong>
                ${r.length?`
                    <ul>
                        ${r.map(s=>`<li>${c(s)}</li>`).join("")}
                    </ul>
                `:""}
                ${a.length?`
                    <div class="tui-entry-actions">
                        ${a.map((s,l)=>`
                            <button type="button" data-next-step-index="${l}">
                                ${c(s.label||"\u7EE7\u7EED")}
                            </button>
                        `).join("")}
                    </div>
                `:""}
            </div>
        `}function ft(e,t){e.querySelectorAll("[data-next-step-index]").forEach(n=>{n.addEventListener("click",()=>{const r=Number(n.dataset.nextStepIndex||0);to((t||[])[r])})})}function to(e){if(e){if(e.action_key){const t=e.params&&typeof e.params=="object"?{...e.params}:{};$(e.action_key,null,{params:t});return}if(e.screen_key){S(e.screen_key);return}p(e.hint||"\u5DF2\u8BB0\u5F55\u4E0B\u4E00\u6B65")}}function no(e){J(e,"\u56FE\u8868",mt)}function ro(e){J(e,"\u56FE\u7247",Bn)}function ao(e){J(e,"\u6307\u6807\u8D8B\u52BF",In)}function oo(e){J(e,"\u8868\u683C\u56FE\u8868",Dn)}function so(e){J(e,"\u5BBF\u4E3B\u63D2\u69FD",Nn),Pe(i.main)}function qn(e){J(e,"\u81EA\u5B9A\u4E49\u89C6\u56FE",gt)}function J(e,t,n){i.main.innerHTML=`
            <div class="tui-view-status">${c(e.status||"\u6B63\u5E38")} / ${c(e.title||t)}</div>
            ${fe(e)}
            ${n(e)}
        `}function mt(e,t={}){const n=!!t.compact,r=String(e.chart_type||e.renderer||"line").toLowerCase(),a=Kn(e);if(!a.length)return T(e.empty_message||"\u6682\u65E0\u56FE\u8868\u6570\u636E\u3002",[]);const s=r==="pie"?uo(a):r==="bar"?lo(a):On(a);return`
            <section class="tui-rich-view tui-chart-view ${n?"is-compact":""}">
                <div class="tui-rich-header">
                    <strong>${c(e.title||"Chart")}</strong>
                    <span>${c(r.toUpperCase())}</span>
                </div>
                ${s}
                <div class="tui-chart-legend">
                    ${a.slice(0,n?4:8).map(l=>`
                        <span><i></i>${c(l.label)} ${c(yt(l.value))}</span>
                    `).join("")}
                </div>
            </section>
        `}function Bn(e,t={}){const n=io(e);if(!n)return T(e.empty_message||"\u6682\u65E0\u56FE\u7247\u94FE\u63A5\u3002",[]);const r=String(e.alt||e.caption||e.title||"Image"),a=String(e.caption||""),s=String(e.title||"Image");return`
            <figure class="tui-rich-view tui-image-view ${t.compact?"is-compact":""}">
                <div class="tui-rich-header">
                    <strong>${c(s)}</strong>
                    <span>IMAGE</span>
                </div>
                <button class="tui-image-frame" type="button"
                        data-image-preview
                        data-image-src="${c(n)}"
                        data-image-alt="${c(r)}"
                        data-image-caption="${c(a)}"
                        data-image-title="${c(s)}">
                    <img src="${c(n)}" alt="${c(r)}" loading="lazy" decoding="async">
                </button>
                ${a?`<figcaption>${c(a)}</figcaption>`:""}
            </figure>
        `}function io(e){const t=[e.url,e.src,e.image_url,e.imageUrl,e.href];for(const n of t){const r=Hn(n);if(r)return r}return""}function Hn(e){const t=String(e||"").trim();if(!t)return"";try{const n=new URL(t,window.location.href);if(n.protocol==="http:"||n.protocol==="https:"||n.protocol==="data:"&&/^data:image\/(?:apng|avif|gif|jpe?g|png|webp);/i.test(t)||n.protocol==="data:"&&br&&/^data:image\/svg\+xml(?:[;,]|$)/i.test(t))return t}catch{return""}return""}function In(e,t={}){const n=(e.trend||[]).map(jn).filter(Boolean),r=n.map(d=>d.value),a=r[0]||0,s=r.length?r[r.length-1]:Number.parseFloat(e.value)||0,l=s-a,u=l>=0?"is-up":"is-down";return`
            <section class="tui-rich-view tui-kpi-view ${t.compact?"is-compact":""}">
                <div class="tui-kpi-main">
                    <span>${c(e.label||e.title||"KPI")}</span>
                    <strong>${c(e.value||yt(s))}</strong>
                    <em class="${u}">${l>=0?"+":""}${c(yt(l))}</em>
                </div>
                ${n.length?`<div class="tui-kpi-spark">${On(n,{spark:!0})}</div>`:""}
            </section>
        `}function Dn(e,t={}){const n=e.chart||{},r=e.table||{};return`
            <section class="tui-rich-view tui-table-chart-view ${t.compact?"is-compact":""}">
                ${mt({...n,title:n.title||e.title},{compact:t.compact})}
                <div class="tui-table-chart-grid">
                    ${kn({max_rows:t.compact?4:10,columns:r.columns||[]},r)}
                </div>
            </section>
        `}function Nn(e,t={}){const n=!!w.allowHostHtmlSlots,r=String(e.partial_html||""),a=e.fallback_message||"\u5BBF\u4E3B\u63D2\u69FD\u5185\u5BB9\u7531\u5BBF\u4E3B\u5E94\u7528\u63A7\u5236\u3002";return!n||!r?`
                <section class="tui-rich-view tui-host-slot ${t.compact?"is-compact":""}">
                    <div class="tui-rich-header">
                        <strong>${c(e.slot_key||e.title||"host-slot")}</strong>
                        <span>HOST SLOT</span>
                    </div>
                    ${T(a,n?[]:["\u5F53\u524D runtime \u672A\u5F00\u542F allowHostHtmlSlots\u3002"])}
                </section>
            `:`
            <section class="tui-rich-view tui-host-slot ${t.compact?"is-compact":""}" data-host-slot="${c(e.slot_key||"")}">
                ${r}
            </section>
        `}function Pe(e){w.allowHostHtmlSlots&&window.htmx&&typeof window.htmx.process=="function"&&e.querySelectorAll(".tui-host-slot").forEach(t=>window.htmx.process(t))}function gt(e){const t=String(e.renderer||"").trim()||"custom";return T(e.fallback_message||`\u6CA1\u6709\u6CE8\u518C renderer: ${t}`,["\u5BBF\u4E3B\u53EF\u4EE5\u901A\u8FC7 window.AgomTUIRenderers.register(name, rendererFn) \u6CE8\u518C\u6269\u5C55\u3002"])}function Kn(e){const n=(Array.isArray(e.series)?e.series:[]).find(a=>Array.isArray(a?.points));return(n?n.points:Array.isArray(e.points)?e.points:[]).map(jn).filter(Boolean)}function jn(e,t=0){if(e==null)return null;if(typeof e=="number")return{label:String(t+1),value:e};const n=Number.parseFloat(e.value??e.y??e.count??e.total);return Number.isFinite(n)?{label:String(e.label??e.x??e.name??t+1),value:n}:null}function co(e,t,n,r){const a=e.map(d=>d.value),s=Math.min(0,...a),u=Math.max(1,...a)-s||1;return{x(d){return e.length<=1?t/2:r+d/(e.length-1)*(t-r*2)},y(d){return n-r-(d-s)/u*(n-r*2)}}}function On(e,t={}){const n=t.spark?240:640,r=t.spark?72:220,a=t.spark?8:28,s=co(e,n,r,a),l=e.map((u,d)=>`${d===0?"M":"L"}${s.x(d).toFixed(1)} ${s.y(u.value).toFixed(1)}`).join(" ");return`
            <svg class="tui-chart-svg ${t.spark?"is-spark":""}" viewBox="0 0 ${n} ${r}" role="img">
                <path class="tui-chart-gridline" d="M${a} ${r-a}H${n-a}"></path>
                <path class="tui-chart-line" d="${c(l)}"></path>
                ${e.map((u,d)=>`<circle class="tui-chart-point" cx="${s.x(d).toFixed(1)}" cy="${s.y(u.value).toFixed(1)}" r="${t.spark?2:3}"></circle>`).join("")}
            </svg>
        `}function lo(e){const a=e.map(b=>b.value),s=Math.max(0,...a),l=Math.min(0,...a),u=s-l||1,d=b=>192-(b-l)/u*164,m=d(0),f=8,g=Math.max(8,(584-f*(e.length-1))/e.length);return`
            <svg class="tui-chart-svg" viewBox="0 0 640 220" role="img">
                <path class="tui-chart-gridline" d="M28 ${m.toFixed(1)}H612"></path>
                ${e.map((b,y)=>{const h=28+y*(g+f),q=d(b.value),U=Math.min(m,q),Be=Math.max(2,Math.abs(q-m));return`<rect class="tui-chart-bar" x="${h.toFixed(1)}" y="${U.toFixed(1)}" width="${g.toFixed(1)}" height="${Be.toFixed(1)}"></rect>`}).join("")}
            </svg>
        `}function uo(e){const t=e.reduce((a,s)=>a+Math.max(0,s.value),0)||1;let n=0;return`
            <svg class="tui-chart-svg tui-chart-pie" viewBox="0 0 200 200" role="img">
                ${e.map((a,s)=>{const u=Math.max(0,a.value)/t*100,d=`<circle class="tui-chart-pie-slice slice-${s%6}" r="70" cx="100" cy="100" pathLength="100" stroke-dasharray="${u} ${100-u}" stroke-dashoffset="${-n}"></circle>`;return n+=u,d}).join("")}
                <circle class="tui-chart-pie-hole" r="38" cx="100" cy="100"></circle>
            </svg>
        `}function yt(e){const t=Number(e);return Number.isFinite(t)?Math.abs(t)>=100?t.toFixed(0):t.toFixed(2).replace(/\.00$/,""):String(e??"-")}function po(e){const t=va(),n=t.length?$n(e,t):_n(e.fields||[]),r=t.length?[]:e.nested||[];i.main.innerHTML=`
            <div class="tui-view-status">${c(e.status)} / ${c(e.title)}</div>
            ${fe(e)}
            ${n||T("\u6682\u65E0\u6458\u8981\u6570\u636E\u3002",[])}
            ${r.length?`
                <div class="tui-nested-list">
                    ${r.map(a=>`<span>${c(a.label)}: ${c(a.count)} \u884C</span>`).join("")}
                </div>
            `:""}
            ${Array.isArray(e.next_steps)&&e.next_steps.length?T("\u5EFA\u8BAE\u4E0B\u4E00\u6B65",[],e.next_steps):""}
        `,ft(i.main,e.next_steps)}function zn(e){const t=Array.isArray(e.sections)?e.sections:[],n=t.length?t.map(r=>`
                <section class="tui-message-section">
                    <h4>${c(r.title||"\u6458\u8981")}</h4>
                    ${(r.body||[]).map(a=>`<p>${c(a)}</p>`).join("")}
                    ${(r.rows||[]).length?`
                        <dl class="tui-message-fields">
                            ${r.rows.map(a=>`
                                <dt>${c(a.label)}</dt>
                                <dd>${c(a.value)}</dd>
                            `).join("")}
                        </dl>
                    `:""}
                </section>
            `).join(""):`<div class="tui-message">${c(e.message||"")}</div>`;i.main.innerHTML=`
            <div class="tui-view-status">${c(e.status||"\u6B63\u5E38")} / ${c(e.title||"\u6D88\u606F")}</div>
            ${fe(e)}
            <div class="tui-message-list">${n}</div>
            ${Array.isArray(e.next_steps)&&e.next_steps.length?T("\u5EFA\u8BAE\u4E0B\u4E00\u6B65",[],e.next_steps):""}
        `,ft(i.main,e.next_steps)}function fe(e){const t=o.screen?.screen||{},n=t.business_context||{};if(!n.decision_output&&!n.objective&&!e?.business_summary)return"";const a=(t.workflow||{}).next||{},s=o.screen&&o.screen.actions||[],l=de(s),u=mo(e),m=[["\u5224\u65AD\u4EA7\u51FA",String(e?.business_summary||"").trim()||n.decision_output||n.objective],["\u5F53\u524D\u8BC1\u636E",u]];e?.blocking_reason&&m.push(["\u5F53\u524D\u963B\u65AD",e.blocking_reason]);const f=[];l.operation&&m.push(["\u53EF\u6267\u884C\u64CD\u4F5C",`${l.operation} \u9879\uFF0C\u63D0\u4EA4\u524D\u786E\u8BA4`]);const g=Ee(s);g.total&&m.push(["\u672C\u5C4F\u8FDB\u5EA6",`${g.completed}/${g.total}`]);const b=$t();return b&&(m.push(["\u672C\u5C4F\u4E0B\u4E00\u9879",b.label]),f.push({command:"next-primary",label:b.label,key:"F6",title:"\u8FD0\u884C\u4E0B\u4E00\u4E3B\u6D41\u7A0B"})),a.label&&(m.push(["\u4E0B\u4E00\u6B65",a.label]),f.push({command:"workflow-next",label:a.label,key:"F4",title:"\u8FDB\u5165\u6D41\u7A0B\u4E0B\u4E00\u5C4F"})),`
            <section class="tui-decision-cue">
                ${m.map(([y,h])=>`
                    <div>
                        <span>${c(y)}</span>
                        <strong>${c(h)}</strong>
                    </div>
                `).join("")}
                ${f.length?`
                    <div class="tui-decision-actions">
                        <span>\u7EE7\u7EED</span>
                        <strong>
                            ${f.map(y=>`
                                <button type="button" data-decision-action="${c(y.command)}">
                                    ${c(y.title)}: ${c(y.label)}
                                    <kbd>${c(y.key)}</kbd>
                                </button>
                            `).join("")}
                        </strong>
                    </div>
                `:""}
            </section>
        `}function fo(){i.main.querySelectorAll("[data-decision-action]").forEach(e=>{e.addEventListener("click",()=>{const t=e.dataset.decisionAction;t==="next-primary"?rr():t==="workflow-next"&&kt(1)})})}function mo(e){if(!e)return"\u5C1A\u672A\u8FD4\u56DE\u4E1A\u52A1\u89C6\u56FE";if(e.kind==="datagrid"){const n=e.pager?.total_rows??o.currentRows.length;return o.filterText?`\u7B5B\u9009\u540E ${o.visibleRows.length}/${o.currentRows.length} \u884C`:`\u8868\u683C ${o.currentRows.length}/${n} \u884C`}if(e.kind==="detail"){const n=(e.fields||[]).length,r=(e.nested||[]).reduce((a,s)=>a+Number(s.count||0),0);return r?`\u8BE6\u60C5 ${n} \u9879\uFF0C\u5173\u8054 ${r} \u884C`:`\u8BE6\u60C5 ${n} \u9879`}if(e.kind==="chart")return`\u56FE\u8868 ${Kn(e).length} \u70B9`;if(e.kind==="kpi_trend"){const n=(e.trend||[]).length;return n?`\u6307\u6807\u8D8B\u52BF ${n} \u70B9`:"\u6307\u6807\u8D8B\u52BF"}if(e.kind==="table_chart")return`\u56FE\u8868\u8868\u683C ${e.table?.rows?.length||0} \u884C`;if(e.kind==="host_slot")return"\u5BBF\u4E3B\u63D2\u69FD";if(e.kind==="custom")return`\u81EA\u5B9A\u4E49 ${e.renderer||"renderer"}`;const t=(e.sections||[]).length;return t?`\u6D88\u606F ${t} \u6BB5`:"\u6D88\u606F\u7ED3\u679C"}function Q(e){const t=Array.isArray(e.sections)?e.sections:[],n=Vn(e.rows||[]),r=A(e.body||"").split(/\n+/).map(s=>s.trim()).filter(Boolean),a=A(e.rowsTitle||"\u6D41\u7A0B\u72B6\u6001");i.inspector.innerHTML=`
            <section class="tui-inspector-card tui-inspector-summary">
                <div class="tui-inspector-title">${c(e.title||"\u8BF4\u660E")}</div>
                ${r.map(s=>`<p>${c(s)}</p>`).join("")}
            </section>
            ${n.length?`
                <section class="tui-inspector-card">
                    <div class="tui-inspector-title">${c(a)}</div>
                    <dl class="tui-inspector-grid">
                        ${n.map(s=>`
                            <dt>${c(s.label)}</dt>
                            <dd>${c(s.value)}</dd>
                        `).join("")}
                    </dl>
                </section>
            `:""}
            ${t.length?`
                <div class="tui-inspector-sections">
                    ${t.map(s=>`
                        <section class="tui-message-section">
                            <h4>${c(A(s.title||"\u6458\u8981"))}</h4>
                            ${(s.body||[]).map(l=>`<p>${c(A(l))}</p>`).join("")}
                            ${(s.actions||[]).length?`
                                <div class="tui-inspector-actions">
                                    ${s.actions.map(l=>`
                                        <button type="button" data-inspector-action="${c(l.ui_key)}">
                                            <span>${c(l.label)}</span>
                                            <kbd>${c(l.verb)}</kbd>
                                        </button>
                                    `).join("")}
                                </div>
                            `:""}
                            ${(s.rows||[]).length?`
                                <dl class="tui-message-fields">
                                    ${Vn(s.rows).map(l=>`
                                        <dt>${c(l.label)}</dt>
                                        <dd>${c(l.value)}</dd>
                                    `).join("")}
                                </dl>
                            `:""}
                        </section>
                    `).join("")}
                </div>
            `:""}
        `,i.inspector.querySelectorAll("[data-inspector-action]").forEach(s=>{s.addEventListener("click",()=>wo(s.dataset.inspectorAction))})}function Vn(e){return(e||[]).map(t=>Array.isArray(t)?{label:t[0],value:t[1]}:{label:t.label,value:t.value}).filter(t=>t.label!==void 0&&t.value!==void 0).map(t=>({label:A(t.label),value:A(t.value)}))}function go(e){const t=Ee(),n=$t(),r=(o.screen&&o.screen.actions||[]).filter(s=>v(s)==="operation").length,a=[["\u64CD\u4F5C\u65B9\u5F0F",re(e.action)],["\u672C\u5C4F\u8FDB\u5EA6",`${t.completed}/${t.total}`]];return n&&n.key!==e.action.key&&a.push(["\u4E0B\u4E00\u9879",n.label]),r&&a.push(["\u53EF\u6267\u884C\u64CD\u4F5C",`${r} \u9879`]),e.action.confirmation_required&&a.push(["\u786E\u8BA4\u7B56\u7565","\u63D0\u4EA4\u524D\u4F1A\u8981\u6C42\u786E\u8BA4"]),a}function yo(e,t){const n=o.screen?.screen?.business_context||{},r=nt(n),a=(o.screen&&o.screen.actions||[]).filter(u=>v(u)==="operation").slice(0,5).map(u=>`${u.label} / ${re(u)}`),s=go(e),l=[...r,...a.length?[{title:"\u540E\u7EED\u52A8\u4F5C",body:a,rows:[]}]:[]];if(!t){Q({title:e.action.label,body:e.action.description||"",rows:s,sections:l});return}if(t.kind==="detail"){Q({title:"\u64CD\u4F5C\u8BF4\u660E",body:e.action.description||"\u4E2D\u95F4\u4E3B\u9762\u677F\u663E\u793A\u5B8C\u6574\u4E1A\u52A1\u660E\u7EC6\uFF0C\u53F3\u680F\u53EA\u4FDD\u7559\u6D41\u7A0B\u3001\u8BC1\u636E\u4E0E\u540E\u7EED\u52A8\u4F5C\u3002",rowsTitle:"\u6D41\u7A0B\u72B6\u6001",rows:s,sections:[{title:"\u9605\u8BFB\u63D0\u793A",body:["\u5B8C\u6574\u4E1A\u52A1\u660E\u7EC6\u5DF2\u5728\u4E2D\u95F4\u4E3B\u9762\u677F\u663E\u793A\u3002\u53F3\u680F\u4E0D\u518D\u91CD\u590D\u6E32\u67D3\u540C\u4E00\u5BF9\u8C61\u3002"],rows:[]},...l]});return}if(t.kind==="message"){Q({title:"\u64CD\u4F5C\u8BF4\u660E",body:e.action.description||"\u4E2D\u95F4\u4E3B\u9762\u677F\u663E\u793A\u5F53\u524D\u7ED3\u679C\u8BF4\u660E\uFF0C\u53F3\u680F\u4FDD\u7559\u5BFC\u822A\u4E0E\u540E\u7EED\u52A8\u4F5C\u3002",rowsTitle:"\u6D41\u7A0B\u72B6\u6001",rows:s,sections:[{title:"\u9605\u8BFB\u63D0\u793A",body:["\u7ED3\u679C\u8BF4\u660E\u5DF2\u5728\u4E2D\u95F4\u4E3B\u9762\u677F\u663E\u793A\u3002\u53F3\u680F\u4FDD\u7559\u6D41\u7A0B\u5BFC\u822A\u3001\u4E1A\u52A1\u76EE\u6807\u4E0E\u540E\u7EED\u52A8\u4F5C\u3002"],rows:[]},...l]});return}bt([...s,...a.slice(0,3).map((u,d)=>[`\u53EF\u6267\u884C\u52A8\u4F5C ${d+1}`,u])])}function bo(e){i.main.innerHTML=`<div class="tui-error">${c(e)}</div>`,me(null),p("\u9519\u8BEF")}function me(e){if(o.lastPager=e,!e){i.pager.textContent="\u9875 -/- | 0 \u884C";return}i.pager.textContent=`\u9875 ${e.page}/${e.total_pages} | ${e.total_rows} \u884C | ${e.has_previous?"PgUp":"--"} / ${e.has_next?"PgDn":"--"}`}function D(){i.rawPanel.textContent=o.lastRaw===null?"\u5C1A\u672A\u52A0\u8F7D\u539F\u59CB\u54CD\u5E94\u3002":JSON.stringify(o.lastRaw,null,2)}function Re(e){i.rawDrawer.hidden=typeof e=="boolean"?!e:!i.rawDrawer.hidden,p(i.rawDrawer.hidden?"\u539F\u59CB\u54CD\u5E94\u5173\u95ED":"\u539F\u59CB\u54CD\u5E94\u6253\u5F00")}function Mn(e){o.selectedRowIndex=e,i.main.querySelectorAll("[data-row-index]").forEach(n=>{n.classList.toggle("is-selected",Number(n.dataset.rowIndex||0)===e)});const t=o.visibleRows[e];o.selectedRowContext=W(t),t&&(p(`\u884C ${e+1}/${o.visibleRows.length}`),bt()),Le()}function bt(e=[]){if(!o.currentViewModel||o.currentViewModel.kind!=="datagrid")return;const t=o.visibleRows[o.selectedRowIndex],n=t?rn(t,14):[["\u72B6\u6001",o.filterText?"\u6CA1\u6709\u5339\u914D\u8BB0\u5F55":"\u6682\u65E0\u8BB0\u5F55"]],r=W(t),a=r?ho(r):[],s=[];a.length&&s.push({title:"\u9009\u4E2D\u884C\u53EF\u505A",body:["\u76F4\u63A5\u4F7F\u7528\u9009\u4E2D\u8BB0\u5F55\u586B\u5165\u53C2\u6570\u3002"],actions:a.map(l=>({ui_key:O(l),label:l.label,verb:re(l)})),rows:[]}),s.push({title:"\u952E\u76D8\u64CD\u4F5C",body:["\u65B9\u5411\u952E\u79FB\u52A8\uFF0CEnter \u6253\u5F00\u8BE6\u60C5\uFF0CF7 \u7B5B\u9009\uFF0CF9 \u8FDB\u5165\u4EFB\u52A1\u533A\uFF0CF8 \u5BFC\u51FA\u3002"],rows:[]}),Q({title:t?`\u9009\u4E2D\u8BB0\u5F55 ${o.selectedRowIndex+1}/${o.visibleRows.length}`:"\u8868\u683C\u72B6\u6001",body:o.currentViewModel.title||"",rows:[...e,...n],sections:s})}function ho(e){return(o.screen&&o.screen.actions||[]).filter(n=>{const r=(n.fields||[]).filter(a=>a.input_type!=="hidden");return r.length?r.some(a=>lt(e,a.key,n)!==void 0):!1}).sort((n,r)=>{const a={operation:0,advanced:1,primary:2,support:3};return(a[v(n)]??9)-(a[v(r)]??9)||Number(n.sequence||999)-Number(r.sequence||999)}).slice(0,5)}function Un(e,t){const n={};return(t&&t.fields||[]).forEach(a=>{if(a.input_type==="hidden")return;const s=lt(e,a.key,t);s!=null&&s!==""&&(n[a.key]=s)}),n}function wo(e){const t=W(o.visibleRows[o.selectedRowIndex]),n=k(e);if(!t||!n){p("\u6CA1\u6709\u53EF\u6267\u884C\u7684\u9009\u4E2D\u884C\u4EFB\u52A1");return}const r=Un(t,n),a=(n.fields||[]).filter(s=>s.required&&!s.default&&s.input_type!=="hidden").filter(s=>r[s.key]===void 0||r[s.key]===null||String(r[s.key]).trim()==="");if(a.length){p(`\u9009\u4E2D\u884C\u7F3A\u5C11\u53C2\u6570: ${a.map(s=>s.label).join(", ")}`);return}$(n.key,null,{params:r})}function Wn(e){const t=i.main.querySelectorAll("[data-row-index]");if(!t.length)return;const n=Number(t[0].dataset.rowIndex||0),r=Number(t[t.length-1].dataset.rowIndex||0),a=Math.max(n,Math.min(r,o.selectedRowIndex+e));Mn(a),i.main.querySelector(`[data-row-index="${a}"]`)?.scrollIntoView({block:"nearest"})}async function ht(e){if(o.lastPager?.client_side){if(e<0&&!o.lastPager.has_previous){p("\u5DF2\u7ECF\u662F\u7B2C\u4E00\u9875");return}if(e>0&&!o.lastPager.has_next){p("\u5DF2\u7ECF\u662F\u6700\u540E\u4E00\u9875");return}o.clientPage=Math.max(1,o.clientPage+e),o.selectedRowIndex=(o.clientPage-1)*o.clientPageSize,En(),p(`\u7B2C ${o.clientPage} \u9875`);return}if(o.pendingController){p("\u7FFB\u9875\u4E2D\uFF0C\u8BF7\u7A0D\u5019");return}if(!o.lastAction||!o.lastPager){p("\u5F53\u524D\u89C6\u56FE\u4E0D\u53EF\u7FFB\u9875");return}const t=k(o.lastAction);if(!t){p("\u4EFB\u52A1\u672A\u627E\u5230");return}if(e<0&&!o.lastPager.has_previous){p("\u5DF2\u7ECF\u662F\u7B2C\u4E00\u9875");return}if(e>0&&!o.lastPager.has_next){p("\u5DF2\u7ECF\u662F\u6700\u540E\u4E00\u9875");return}const n=So(t,o.lastPager,o.lastParams,e);if(!n){p("\u5F53\u524D\u5206\u9875\u53C2\u6570\u4E0D\u53EF\u63A8\u65AD");return}await $(o.lastAction,null,{params:{...o.lastParams,...n}})}function So(e,t,n,r){const a=e.pagination||{},s=String(t.pagination_mode||t.mode||""),l=a.mode||(s==="limit_offset"?"offset":s)||ko(e);if(l==="cursor"){const y=a.cursor_param||ge(e,["cursor","nextCursor","next_cursor"]),h=r>0?Gn(t,a.next_cursor_path||"next_cursor"):Gn(t,a.previous_cursor_path||"previous_cursor");return y&&h?{[y]:h}:null}if(l==="offset"){const y=a.offset_param||ge(e,["offset","start"]),h=a.limit_param||ge(e,["limit","pageSize","page_size"]),q=Number(n[h]||t.page_size||t.limit||10),U=Number(n[y]||t.offset||0);if(!y||!Number.isFinite(q)||!Number.isFinite(U))return null;const Be=Math.max(0,U+r*q);return h?{[y]:Be,[h]:q}:{[y]:Be}}const u=a.page_param||ge(e,["page","pageNum","page_num","pageNo","page_no"]),d=a.page_size_param||ge(e,["page_size","pageSize","limit","size"]),m=Number(n[u]||t.page||1);if(!u||!Number.isFinite(m))return null;const f=Math.max(1,m+r),g={[u]:f},b=Number(n[d]||t.page_size||t.pageSize||0);return d&&Number.isFinite(b)&&b>0&&(g[d]=b),g}function ko(e){const t=(e.fields||[]).map(n=>String(n.key||""));return t.some(n=>["cursor","nextCursor","next_cursor"].includes(n))?"cursor":t.some(n=>["offset","start"].includes(n))?"offset":"page"}function ge(e,t){const n=(e.fields||[]).map(r=>String(r.key||""));return t.find(r=>n.includes(r))||t[0]||""}function Gn(e,t){if(t)return String(t).split(".").reduce((n,r)=>{if(n&&Object.prototype.hasOwnProperty.call(n,r))return n[r]},e)}function M(e,t,n={}){o.modalReturnFocus=document.activeElement instanceof HTMLElement?document.activeElement:null,i.modalTitle.textContent=e,i.modalBody.innerHTML=t,i.modal.classList.remove("is-image-preview");const r=i.modal.dataset.modalClass||"";r&&i.modal.classList.remove(r),n.className&&i.modal.classList.add(n.className),i.modal.dataset.modalClass=n.className||"",i.modal.hidden=!1,i.modalClose.focus()}function $o(){return!i.modal||i.modal.hidden?[]:Array.from(i.modal.querySelectorAll("button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")).filter(e=>!e.hidden&&e.getAttribute("aria-hidden")!=="true")}function vo(e){if(e.key!=="Tab"||i.modal.hidden)return!1;const t=$o();if(!t.length)return e.preventDefault(),i.modalClose.focus(),!0;const n=t[0],r=t[t.length-1];return e.shiftKey&&(document.activeElement===n||!i.modal.contains(document.activeElement))?(e.preventDefault(),r.focus(),!0):!e.shiftKey&&(document.activeElement===r||!i.modal.contains(document.activeElement))?(e.preventDefault(),n.focus(),!0):!1}function _o(e){const t=Hn(e.dataset.imageSrc||"");if(!t){p("\u56FE\u7247\u94FE\u63A5\u4E0D\u53EF\u7528");return}const n=e.dataset.imageTitle||"\u56FE\u7247\u9884\u89C8",r=e.dataset.imageAlt||n,a=e.dataset.imageCaption||"";M(n,`
            <figure class="tui-image-lightbox">
                <div class="tui-image-lightbox-frame">
                    <img src="${c(t)}" alt="${c(r)}" loading="eager" decoding="async">
                </div>
                <figcaption>
                    ${a?`<span>${c(a)}</span>`:""}
                    <a href="${c(t)}" target="_blank" rel="noopener noreferrer">\u6253\u5F00\u539F\u56FE</a>
                </figcaption>
            </figure>
        `,{className:"is-image-preview"}),p("\u56FE\u7247\u9884\u89C8")}function xo(e,t,n,r={}){const a=e.missing_fields||[],s=e.action||k(t)||{key:t||"missing-fields"};M("\u8865\u586B\u53C2\u6570",`
            <form class="tui-confirmation tui-missing-fields" data-missing-fields-form>
                <p>${c(e.view_model?.message||"\u8865\u9F50\u53C2\u6570\u540E\u7EE7\u7EED\u6267\u884C\u3002")}</p>
                <div class="tui-missing-fields-list">
                    ${a.map(d=>dn(s,{...d,default:n[d.key]??d.default??""})).join("")}
                </div>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="submit">\u7EE7\u7EED</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>\u53D6\u6D88</button>
                </div>
            </form>
        `);const l=i.modalBody.querySelector("[data-missing-fields-form]"),u=i.modalBody.querySelector("[data-cancel-action]");l.addEventListener("submit",d=>{d.preventDefault();const m={...n};a.forEach(f=>{const g=l.querySelector(`[name="${CSS.escape(f.key)}"]`);g&&(m[f.key]=pn(f,g.value,g.checked))}),P(),$(t,null,{...r,params:m})}),u.addEventListener("click",()=>{P(),p("\u5DF2\u53D6\u6D88")}),l.querySelector("select, input, textarea")?.focus()}function Ao(e,t,n,r={}){const a=e.confirmation||{};M(a.title||"\u786E\u8BA4\u64CD\u4F5C",`
            <div class="tui-confirmation">
                <p>${c(a.message||"\u786E\u8BA4\u540E\u6267\u884C\u6B64\u64CD\u4F5C\u3002")}</p>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="button" data-confirm-action>${c(a.confirm_label||"\u786E\u8BA4\u6267\u884C")}</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>${c(a.cancel_label||"\u53D6\u6D88")}</button>
                </div>
            </div>
        `);const s=i.modalBody.querySelector("[data-confirm-action]"),l=i.modalBody.querySelector("[data-cancel-action]");s.addEventListener("click",()=>{P(),$(t,null,{...r,confirmed:!0,params:n,confirmation:{confirmed:!0,confirmed_at:new Date().toISOString(),message:a.message||""}})}),l.addEventListener("click",()=>{P(),p("\u5DF2\u53D6\u6D88")}),s.focus()}function Co(e,t,n,r={}){const a=e.password_challenge||{};M("\u91CD\u65B0\u9A8C\u8BC1\u8EAB\u4EFD",`
            <form class="tui-confirmation" data-password-challenge-form>
                <p>${c(a.message||"\u8BE5\u64CD\u4F5C\u9700\u8981\u91CD\u65B0\u9A8C\u8BC1\u8EAB\u4EFD\u3002")}</p>
                <label class="tui-field">
                    <span>\u5BC6\u7801</span>
                    <input name="password" type="password" autocomplete="current-password" required>
                </label>
                <div class="tui-confirmation-actions">
                    <button class="tui-confirm-button" type="submit">\u9A8C\u8BC1\u5E76\u7EE7\u7EED</button>
                    <button class="tui-confirm-button" type="button" data-cancel-action>\u53D6\u6D88</button>
                </div>
            </form>
        `);const s=i.modalBody.querySelector("[data-password-challenge-form]"),l=i.modalBody.querySelector("[data-cancel-action]");s.addEventListener("submit",u=>{u.preventDefault();const d=s.querySelector("[name='password']")?.value||"";P(),$(t,null,{...r,params:n,reauth:{method:"password",credential:d,challenge_id:a.challenge_id||"",submitted_at:new Date().toISOString()}})}),l.addEventListener("click",()=>{P(),p("\u5DF2\u53D6\u6D88")}),s.querySelector("input")?.focus()}function P(){if(i.modal){const e=!i.modal.hidden;i.modal.hidden=!0,i.modal.classList.remove("is-image-preview"),i.modalBody.innerHTML="",e&&o.modalReturnFocus&&document.contains(o.modalReturnFocus)&&o.modalReturnFocus.focus(),o.modalReturnFocus=null}}function wt(){const e=o.visibleRows[o.selectedRowIndex];if(!e){p("\u672A\u9009\u62E9\u884C");return}const t=rn(e).map(([s,l])=>`
            <dt>${c(s)}</dt>
            <dd>${c(l)}</dd>
        `).join(""),n=String(e?.target_screen||"").trim(),r=String(e?.target_action_key||"").trim(),a=!!(n||r);M(`\u7B2C ${o.selectedRowIndex+1} \u884C`,`
                <dl class="tui-detail-grid">${t}</dl>
                ${a?`
                    <div class="tui-modal-actions">
                        <button type="button" data-row-target-screen="${c(n)}" data-row-target-action="${c(r)}">\u8FDB\u5165\u5904\u7406\u5C4F</button>
                    </div>
                `:""}
            `),i.modalBody?.querySelector("[data-row-target-screen], [data-row-target-action]")?.addEventListener("click",async()=>{P();const s=n||o.screen?.screen?.key||"";s&&(await S(s),r&&k(r)&&$(r,null,{params:{}}))}),p("\u884C\u8BE6\u60C5")}function Lo(){M("\u5E2E\u52A9",`
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
        `),p("\u5E2E\u52A9")}function To(){M("\u4E3B\u9898",`
            <div class="tui-help-grid">
                <span>\u5F53\u524D</span><span>STYLE: ${c(o.themeKey)}</span>
                <span>A</span><span>Norton PCTOOLS \u84DD\u5E95\u9EC4\u5B57\u98CE\u683C</span>
                <span>B</span><span>\u4E2D\u6027\u91D1\u878D\u4E13\u4E1A\u7EC8\u7AEF\u98CE\u683C</span>
                <span>C</span><span>\u98CE\u63A7 / \u63A7\u5236\u53F0\u98CE\u683C</span>
                <span>Alt+T</span><span>\u5FAA\u73AF\u5207\u6362\uFF0C\u4E0D\u5237\u65B0\u9875\u9762\uFF0C\u4E0D\u4E22\u5931\u5F53\u524D\u72B6\u6001</span>
            </div>
        `),p(`\u5F53\u524D\u4E3B\u9898: ${o.themeKey}`)}function Po(){if(!o.currentViewModel||o.currentViewModel.kind!=="datagrid"){p("\u5F53\u524D\u89C6\u56FE\u4E0D\u53EF\u7B5B\u9009");return}i.filterBar.hidden=!1,i.filterInput.value=o.filterText,i.filterInput.focus(),i.filterInput.select(),p("\u7B5B\u9009\u5C31\u7EEA")}function St(){i.filterBar&&(i.filterBar.hidden=!0)}function Ro(){o.filterText="",i.filterInput&&(i.filterInput.value=""),Te(!0)}function Jn(e){let t=String(e??"");return/^[=+\-@]/.test(t)&&(t=`'${t}`),/[",\n\r]/.test(t)?`"${t.replace(/"/g,'""')}"`:t}function Fo(){if(!o.currentViewModel||o.currentViewModel.kind!=="datagrid"){p("\u5F53\u524D\u89C6\u56FE\u4E0D\u53EF\u5BFC\u51FA");return}const e=o.currentColumns,t=o.visibleRows,n=[e.map(u=>Jn(u.label)).join(","),...t.map(u=>e.map(d=>Jn(u[d.key])).join(","))].join(`\r
`),r=new Blob(["\uFEFF"+n],{type:"text/csv;charset=utf-8"}),a=URL.createObjectURL(r),s=document.createElement("a"),l=(o.currentViewModel.title||"tui-grid").toLowerCase().replace(/[^a-z0-9一-龥]+/g,"-").replace(/^-|-$/g,"")||"tui-grid";s.href=a,s.download=`${l}.csv`,document.body.appendChild(s),s.click(),s.remove(),URL.revokeObjectURL(a),p(`\u5DF2\u5BFC\u51FA ${t.length} \u884C`)}async function Eo(){const e=o.lastAction?k(o.lastAction):null,t=["write","admin"].includes(String(e?.risk||"").toLowerCase());e&&!t?await $(o.lastAction,null,{params:{...o.lastParams}}):o.screen?.screen?.key?await S(o.screen.screen.key):await ir()}function qo(){Yn(!1);const e=i.moduleTree.querySelector(".tui-screen-button.is-active")||i.moduleTree.querySelector(".tui-screen-button");e&&(un(e),e.focus(),p("\u6A21\u5757\u5BFC\u822A"))}function Qn(){const e=i.main.closest(".tui-workspace-grid");e?.classList.contains("is-dashboard")&&(e.classList.remove("is-dashboard"),$e("idle"));const t=i.actions.querySelector("[data-action-filter]");if(t){t.focus(),t.select(),p("\u4EFB\u52A1\u533A");return}const n=i.actions.querySelector(".tui-action-button");n&&(n.focus(),p("\u4EFB\u52A1\u533A"))}function Bo(){Xn(!1);const e=i.inspector.querySelector("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")||i.inspectorShell;e&&(e.focus(),p("\u8BF4\u660E\u680F"))}function Yn(e){o.railCollapsed=!!e,i.app?.classList.toggle("is-rail-collapsed",o.railCollapsed),i.moduleTree&&(i.moduleTree.hidden=o.railCollapsed,i.moduleTree.inert=o.railCollapsed,i.moduleTree.setAttribute("aria-hidden",String(o.railCollapsed))),i.railToggle&&(i.railToggle.setAttribute("aria-expanded",String(!o.railCollapsed)),i.railToggle.setAttribute("aria-label",o.railCollapsed?"\u5C55\u5F00\u6A21\u5757\u5BFC\u822A":"\u6536\u8D77\u6A21\u5757\u5BFC\u822A"),i.railToggle.textContent=o.railCollapsed?"\u25BA":"\u25C4"),o.railCollapsed&&i.railPanel?.contains(document.activeElement)&&i.main.querySelector(".tui-datagrid")?.focus()}function Zn(){Yn(!o.railCollapsed),o.railCollapsed?p("\u6A21\u5757\u5BFC\u822A\u5DF2\u6536\u8D77"):qo()}function Xn(e){o.inspectorCollapsed=!!e,i.app?.classList.toggle("is-inspector-collapsed",o.inspectorCollapsed),i.inspectorToggle&&(i.inspectorToggle.setAttribute("aria-expanded",String(!o.inspectorCollapsed)),i.inspectorToggle.setAttribute("aria-label",o.inspectorCollapsed?"\u5C55\u5F00\u8BF4\u660E\u680F":"\u6536\u8D77\u8BF4\u660E\u680F"),i.inspectorToggle.textContent=o.inspectorCollapsed?"\u25C4":"\u25BA"),o.inspectorCollapsed&&i.inspectorShell?.contains(document.activeElement)&&i.main.querySelector(".tui-datagrid")?.focus()}function er(){Xn(!o.inspectorCollapsed),o.inspectorCollapsed?p("\u8BF4\u660E\u680F\u5DF2\u6536\u8D77"):Bo()}function tr(e){const t=We();return t?t.getBoundingClientRect().right-e.clientX:null}function Ho(e){if(o.inspectorCollapsed||e.button!==0||!we())return;e.preventDefault(),e.stopPropagation(),i.app?.classList.add("is-inspector-resizing"),i.inspectorResizeHandle?.setPointerCapture?.(e.pointerId),ne(tr(e));const t=r=>{r.preventDefault(),ne(tr(r))},n=r=>{r.preventDefault(),i.app?.classList.remove("is-inspector-resizing"),i.inspectorResizeHandle?.releasePointerCapture?.(e.pointerId),i.inspectorResizeHandle?.removeEventListener("pointermove",t),i.inspectorResizeHandle?.removeEventListener("pointerup",n),i.inspectorResizeHandle?.removeEventListener("pointercancel",n),ne(o.inspectorWidth,{persist:!0}),p(`\u8BF4\u660E\u680F\u5BBD\u5EA6 ${o.inspectorWidth}px`)};i.inspectorResizeHandle?.addEventListener("pointermove",t),i.inspectorResizeHandle?.addEventListener("pointerup",n),i.inspectorResizeHandle?.addEventListener("pointercancel",n)}function Io(e){if(o.inspectorCollapsed)return;const t=we();if(!t)return;const n=o.inspectorWidth||i.inspectorShell?.getBoundingClientRect().width||t.min;let r=null;if(e.key==="ArrowLeft"?r=n+(e.shiftKey?48:16):e.key==="ArrowRight"?r=n-(e.shiftKey?48:16):e.key==="Home"?r=t.min:e.key==="End"&&(r=t.max),r===null)return;e.preventDefault(),e.stopPropagation();const a=ne(r,{persist:!0});a&&p(`\u8BF4\u660E\u680F\u5BBD\u5EA6 ${a}px`)}function Do(){const e=i.actions.querySelector("[data-action-filter]");e&&(e.focus(),e.select(),p("\u7B5B\u9009\u5F53\u524D\u4EFB\u52A1"))}function No(e){const t=Array.from(i.moduleTree.querySelectorAll("[data-screen-key]"));if(!t.length)return;const r=(Math.max(0,t.findIndex(a=>a.classList.contains("is-active")))+e+t.length)%t.length;S(t[r].dataset.screenKey)}function kt(e){if(x(o.screen?.screen?.key)){const r=w.host?.laneActionKeys?.[o.preferredHomeLane];r&&ee(r);return}const t=o.screen?.screen?.workflow||{},n=e<0?t.previous:t.next;if(n&&n.key){S(n.key);return}No(e)}function Ko(){return(o.screen&&o.screen.actions||[]).map((t,n)=>({action:t,index:n})).filter(t=>v(t.action)==="primary").sort((t,n)=>Number(t.action.sequence||999)-Number(n.action.sequence||999)||t.index-n.index).map(t=>t.action)}function $t(){const e=Ko();return e.length&&e.find(t=>!Fe(t.key))||null}function nr(e=o.screen?.screen?.key){const t=e||"";return t?(o.completedActionsByScreen[t]||(o.completedActionsByScreen[t]=new Set),o.completedActionsByScreen[t]):new Set}function Fe(e){return nr().has(e)}function jo(e){!e||v(e)!=="primary"||(nr(e.screen_key).add(e.key),Ut())}function Ee(e=o.screen&&o.screen.actions||[]){const t=e.filter(r=>v(r)==="primary");return{completed:t.filter(r=>Fe(r.key)).length,total:t.length}}function Oo(){const e=o.screen?.screen?.key;if(!e){p("\u6CA1\u6709\u53EF\u91CD\u7F6E\u7684\u5DE5\u4F5C\u533A");return}o.completedActionsByScreen[e]=new Set,Ut(),_e(o.screen?.screen)||V(o.screen.actions||[],o.screen.screen),o.currentViewModel&&pe(o.currentViewModel),p("\u672C\u5C4F\u8FDB\u5EA6\u5DF2\u91CD\u7F6E")}function rr(){if(x(o.screen?.screen?.key)){const r=w.host?.laneActionKeys?.[o.preferredHomeLane];r&&ee(r);return}const e=$t();if(!e){p("\u672C\u5C4F\u4E3B\u6D41\u7A0B\u5DF2\u5B8C\u6210");return}const t=i.actions.querySelector(`[data-action-ui-key="${CSS.escape(O(e))}"]`),n=(e.fields||[]).filter(r=>r.required&&!r.default);if(n.length&&t){ct(t);const r=n.filter(a=>{const s=ut(t,a.key);return!s||!s.checked&&String(s.value||"").trim()===""});if(r.length){t.scrollIntoView({block:"nearest"}),t.querySelector("input:not([type='hidden']),select,textarea")?.focus(),p(`\u4E0B\u4E00\u9879\u9700\u8981\u53C2\u6570: ${r.map(a=>a.label).join(", ")}`);return}}$(e.key,t)}function ar(e,t){const n=cr[e]||[];o.menuSourceButton&&o.menuSourceButton!==t&&o.menuSourceButton.setAttribute("aria-expanded","false"),o.activeMenu=e,o.menuSourceButton=t,t.setAttribute("aria-expanded","true"),i.menuPopover.innerHTML=`
            <div class="tui-menu-title">${c(e.toUpperCase())}</div>
            ${n.map(([s,l,u])=>`
                <button type="button" role="menuitem" data-menu-action="${c(s)}">
                    <span>${c(l)}</span>
                    <kbd>${c(u)}</kbd>
                </button>
            `).join("")}
        `;const r=t.getBoundingClientRect();i.menuPopover.style.left=`${Math.max(4,r.left)}px`,i.menuPopover.style.top=`${r.bottom+2}px`,i.menuPopover.hidden=!1;const a=i.menuPopover.querySelector("button");a&&a.focus()}function N(e={}){const t=o.menuSourceButton;o.activeMenu=null,o.menuSourceButton=null,t?.setAttribute("aria-expanded","false"),i.menuPopover&&(i.menuPopover.hidden=!0,i.menuPopover.innerHTML=""),e.restoreFocus&&t&&document.contains(t)&&t.focus()}async function or(e){N(),e==="refresh"?(Me(),await Eo()):e==="export"?Fo():e==="toggle-rail"?Zn():e==="focus-actions"?Qn():e==="previous-workflow"?kt(-1):e==="next-workflow"?kt(1):e==="run-next-primary"?rr():e==="filter-actions"?Do():e==="row-detail"?wt():e==="filter"?Po():e==="reset-progress"?Oo():e==="toggle-inspector"?er():e==="raw"?Re():e==="help"&&Lo()}function qe(e){return!!e?.closest?.("input, textarea, select, [contenteditable='true']")}function vt(e){return!!e?.closest?.("button, a, input, textarea, select, summary, [role='button'], [role='separator'], [contenteditable='true']")}function zo(){return i.modal.hidden?i.filterBar.hidden?i.menuPopover.hidden?i.rawDrawer.hidden?!1:(Re(!1),!0):(N({restoreFocus:!0}),!0):(St(),!0):(P(),!0)}function Vo(e){const t=String(e.key||""),n=t.toLowerCase();if(e.altKey&&!e.ctrlKey&&!e.shiftKey&&n==="t")return"cycle-theme";if(e.altKey&&!e.ctrlKey&&e.shiftKey&&n==="t")return"theme-status";if(e.altKey&&!e.ctrlKey&&!e.shiftKey){const r={s:"file",m:"module",r:"action",v:"view",h:"help"};if(r[n])return`open-menu:${r[n]}`}return!e.altKey&&!e.ctrlKey&&!e.metaKey&&_t[t]?_t[t]:e.ctrlKey&&!e.altKey&&!e.metaKey&&t==="Enter"?"run-next-primary":""}function Mo(e){if(e.isComposing||e.metaKey||!i.modal.hidden)return!1;const t=Vo(e);if(!t)return!1;if(e.preventDefault(),e.stopPropagation(),t.startsWith("open-menu:")){const n=t.slice(10),r=document.querySelector(`[data-menu-command="${CSS.escape(n)}"]`);r&&ar(n,r)}else t==="cycle-theme"?Pr():t==="theme-status"?To():or(t);return!0}function Uo(){const e=typeof _.debounce=="function"?_.debounce(()=>Te(!0),pr):()=>Te(!0);i.actions?.addEventListener("submit",t=>{const n=t.target?.closest?.("[data-action-ui-key]");n&&(t.preventDefault(),ke(n))}),i.actions?.addEventListener("click",t=>{const n=t.target?.closest?.("[data-fill-from-row]");if(n){t.preventDefault(),ct(n.closest("[data-action-ui-key]"));return}const r=t.target?.closest?.(".tui-action-button");if(!r)return;const a=r.closest("[data-action-ui-key]");a&&(t.preventDefault(),ke(a))}),i.main?.addEventListener("click",t=>{const n=t.target?.closest?.("[data-image-preview]");n&&(t.preventDefault(),_o(n))}),i.currentLocation?.addEventListener("focus",()=>{i.currentLocation.select()}),i.currentLocation?.addEventListener("keydown",t=>{t.key==="Enter"?(t.preventDefault(),Fr()):t.key==="Escape"&&(t.preventDefault(),Ue(),i.currentLocation.blur())}),i.rawToggle.addEventListener("click",()=>Re()),i.rawClose.addEventListener("click",()=>Re(!1)),i.modalClose.addEventListener("click",P),i.filterInput.addEventListener("input",()=>{o.filterText=i.filterInput.value,e()}),i.filterInput.addEventListener("keydown",t=>{t.key==="Enter"&&(t.preventDefault(),St(),i.main.querySelector(".tui-datagrid")?.focus())}),i.filterClear.addEventListener("click",Ro),i.railToggle?.addEventListener("click",Zn),i.inspectorToggle?.addEventListener("click",er),i.inspectorResizeHandle?.addEventListener("pointerdown",Ho),i.inspectorResizeHandle?.addEventListener("keydown",Io),document.querySelectorAll("[data-menu-command]").forEach(t=>{t.addEventListener("click",n=>{n.stopPropagation();const r=t.dataset.menuCommand;o.activeMenu===r&&!i.menuPopover.hidden?N():ar(r,t)})}),i.menuPopover.addEventListener("click",t=>{const n=t.target.closest("[data-menu-action]");n&&or(n.dataset.menuAction)}),i.menuPopover.addEventListener("keydown",t=>{const n=Array.from(i.menuPopover.querySelectorAll("[role='menuitem']")),r=n.indexOf(document.activeElement);let a=r;if(t.key==="ArrowDown")a=(r+1+n.length)%n.length;else if(t.key==="ArrowUp")a=(r-1+n.length)%n.length;else if(t.key==="Home")a=0;else if(t.key==="End")a=n.length-1;else if(t.key==="Escape"){t.preventDefault(),N({restoreFocus:!0});return}else if(t.key==="Tab"){N();return}else return;n.length&&(t.preventDefault(),n[a]?.focus())}),document.addEventListener("click",t=>{!i.menuPopover.hidden&&!t.target.closest("[data-menu-popover]")&&!t.target.closest("[data-menu-command]")&&N()}),document.addEventListener("keydown",t=>{vo(t)||Mo(t)||(t.key==="Escape"?zo()&&t.preventDefault():t.key==="Enter"&&!vt(t.target)?(t.preventDefault(),wt()):t.key==="ArrowDown"&&!qe(t.target)&&!vt(t.target)?(t.preventDefault(),Wn(1)):t.key==="ArrowUp"&&!qe(t.target)&&!vt(t.target)?(t.preventDefault(),Wn(-1)):t.key==="PageDown"&&!qe(t.target)?o.lastPager&&(t.preventDefault(),ht(1)):t.key==="PageUp"&&!qe(t.target)&&o.lastPager&&(t.preventDefault(),ht(-1)))},{capture:!0})}function sr(){i.clock&&(i.clock.textContent=Vt())}async function ir(){_.mark?.("bootstrap-start");try{i.moduleTree.innerHTML='<div class="tui-loading">\u6B63\u5728\u52A0\u8F7D\u76EE\u5F55...</div>',p("\u542F\u52A8\u4E2D");const e=Rt(),t=e||(Gt()&&o.lastNonHomeScreen?o.lastNonHomeScreen:""),n=Sr(t);if(n)try{const u=await E(n);if(u?.contract==="tui-bootstrap.v1"&&u.catalog&&u.screen){Ze(u.catalog),Jt(),x(u.screen?.screen?.key)&&(o.operatorHomePayload=null,o.operatorHomePromise=null),fn(u.screen),Ft(u.screen?.screen?.key,{replace:!0}),te(),t&&u.resolved_screen!==t&&p("\u4E0A\u6B21\u5DE5\u4F5C\u533A\u5DF2\u4E0D\u53EF\u7528\uFF0C\u5DF2\u8FD4\u56DE\u9996\u9875"),_.mark?.("p0-ready"),_.measure?.("bootstrap-to-p0","bootstrap-start","p0-ready");return}}catch(u){if(![0,404,405].includes(Number(u?.status||0)))throw u}const r=await E(hr());Ze(r);const a=!!(!e&&Gt()&&o.lastNonHomeScreen),s=e||(a?o.lastNonHomeScreen:r.default_screen);Jt(),!await S(s,{replaceHistory:!0})&&(a||e)&&(p(e?"\u94FE\u63A5\u4E2D\u7684\u5DE5\u4F5C\u533A\u4E0D\u53EF\u7528\uFF0C\u5DF2\u8FD4\u56DE\u9996\u9875":"\u4E0A\u6B21\u5DE5\u4F5C\u533A\u5DF2\u4E0D\u53EF\u7528\uFF0C\u5DF2\u8FD4\u56DE\u9996\u9875"),await S(r.default_screen,{replaceHistory:!0})),_.mark?.("p0-ready"),_.measure?.("bootstrap-to-p0","bootstrap-start","p0-ready")}catch(e){i.moduleTree.innerHTML='<div class="tui-error">\u5BFC\u822A\u6682\u65F6\u4E0D\u53EF\u7528</div>',ae(e)}}function Wo(){return["app","moduleTree","screenTitle","screenStatus","actions","mainTitle","main","inspector","rawDrawer","rawPanel","rawToggle","rawClose","pager","menuPopover","filterBar","filterInput","filterClear","modal","modalTitle","modalBody","modalClose","status"].filter(n=>!i[n]).length?(document.body.innerHTML=`
            <main class="tui-error" role="alert">
                \u5DE5\u4F5C\u53F0\u9875\u9762\u7ED3\u6784\u4E0D\u5B8C\u6574\uFF0C\u8BF7\u5237\u65B0\u9875\u9762\u6216\u8054\u7CFB\u7CFB\u7EDF\u7BA1\u7406\u5458\u3002
            </main>
        `,!1):!0}function Go(){Wo()&&(Er(),qr(),zt(Tr(),{silent:!0}),Or(),Uo(),window.addEventListener("popstate",()=>{const e=Rt();e&&e!==o.screen?.screen?.key&&S(e,{suppressHistory:!0})}),sr(),window.setInterval(sr,1e3),ir())}Go()})();
