/* LUMEN Play 2.0 — independent static edition. Third-party rights remain with their authors. */
(function () {
  "use strict";
  var REPO = "https://studio.blender.org/films/";
  var MP4 = "https://video.blender.org/static/webseed/";
  var COMMONS = "https://commons.wikimedia.org/wiki/Special:Redirect/file/";
  var thumb = function(id){ return "https://i.ytimg.com/vi/" + id + "/hqdefault.jpg"; };
  var still = function(id){ return "https://i.ytimg.com/vi/" + id + "/maxresdefault.jpg"; };
  var cc = "Cine abierto · CC BY · Blender Studio / Blender Foundation. Créditos y licencias en la página del proyecto original.";
  // Solo largometrajes reproducibles dentro de LUMEN Play.
  var supportsWebm = !!document.createElement("video").canPlayType("video/webm");
  var film = (window.LUMEN_EXTRA_FILMS || []).filter(function(m){
    return m.category === "open" && Number(m.minutes) >= 60 &&
      (Boolean(m.embed) || (m.sources || []).some(function(src){return !!src.url && (!src.webm || supportsWebm);}));
  });
  var byId = {};
  film.forEach(function(m){byId[m.id] = m;});
  var $ = function(sel){return document.querySelector(sel);};
  var $$ = function(sel){return [].slice.call(document.querySelectorAll(sel));};
  var html = function(str){return String(str == null ? "" : str).replace(/[&<>"']/g,function(x){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[x];});};
  var read = function(key,fallback){try {var v=JSON.parse(localStorage.getItem(key));return v == null ? fallback : v;}catch(err){return fallback;}};
  var write = function(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch(err){/* private browsing */}};
  var favorites = new Set(read("lumen-play-favorites-v2",[]));
  var progress = read("lumen-play-progress-v2",{});
  var local = [];
  var state = {filter:"Todo",view:"inicio",query:"",active:null,subtitle:null,toastTimer:null,lastProgress:0};
  var video = $("#player");
  function showToast(message){
    var el=$("#toast");el.textContent=message;el.classList.add("show");
    clearTimeout(state.toastTimer);state.toastTimer=setTimeout(function(){el.classList.remove("show");},2600);
  }
  function card(m,continueMode){
    var saved=favorites.has(m.id), tracked=progress[m.id],pct=(tracked && tracked.duration>0)?Math.max(0,Math.min(100,100*tracked.position/tracked.duration)):0;
    return '<article class="film-card" tabindex="0" role="button" aria-label="Ver información de '+html(m.title)+'" data-id="'+html(m.id)+'">' +
      '<div class="poster"><img loading="lazy" src="'+html(m.image)+'" alt="Imagen de '+html(m.title)+'" referrerpolicy="no-referrer">' +
      '<span class="card-label '+(m.category==="open"?"open":"")+'">'+("LARGOMETRAJE")+'</span>' +
      '<div class="poster-bottom"><span class="poster-min">'+html(m.year)+' · '+html(m.duration)+'</span><span class="card-play" aria-hidden="true">▶</span></div>' +
      (continueMode?'<div class="progress-track"><span style="width:'+pct.toFixed(1)+'%"></span></div>':'')+'</div>' +
      '<div class="card-info"><div><h3 class="card-title">'+html(m.title)+'</h3><p class="card-sub">'+html(m.genre)+' · '+(m.category==="open"?((m.sources&&m.sources.length)||m.embed?"Reproducir gratis":"Ver gratis en Blender"):"Ver opciones")+'</p></div>' +
      '<button class="card-save '+(saved?"saved":"")+'" data-fav="'+html(m.id)+'" type="button" aria-label="'+(saved?"Quitar de mi lista":"Agregar a mi lista")+'">'+(saved?"♥":"♡")+'</button></div></article>';
  }
  function renderRail(id,items,mode){
    var rail=$(id);if(!rail)return;rail.innerHTML=items.map(function(m){return card(m,mode);}).join("");
  }
  function filteredFilms(){
    var items=film.slice().sort(function(a,b){return b.minutes-a.minutes;});
    if(state.view==="lista")items=items.filter(function(m){return favorites.has(m.id);});
    else if(state.filter==="Cine abierto")items=items.filter(function(m){return m.category==="open";});
    else if(state.filter==="Películas completas")items=items.filter(function(m){return m.category==="open" && m.minutes>=60;});
    else if(state.filter==="Destacadas")items=items.filter(function(m){return m.minutes>=60;});
    else if(state.filter==="Estrenos 2026")items=items.filter(function(m){return m.year===2026;});
    else if(state.filter!=="Todo")items=items.filter(function(m){return m.genre===state.filter || m.kind===state.filter;});
    if(state.query){var q=state.query.toLocaleLowerCase("es");items=items.filter(function(m){return [m.title,m.genre,m.kind,m.desc,m.author,String(m.year)].join(" ").toLocaleLowerCase("es").indexOf(q)!==-1;});}
    return items;
  }
  function render(){
    renderRail("#featuredRail",["valkaama2010","sita2008","paywall2018"].map(function(id){return byId[id];}).filter(Boolean));
    
    renderRail("#featureMoviesRail",film.filter(function(m){return m.category==="open" && m.minutes>=60;}).sort(function(a,b){return b.year-a.year;}));
    
    
    var continuable=Object.keys(progress).filter(function(id){return byId[id] && progress[id].position>7 && progress[id].duration && progress[id].position<progress[id].duration-7;}).map(function(id){return byId[id];});
    $("#continueSection").classList.toggle("hidden",!continuable.length);
    renderRail("#continueRail",continuable,true);
    var items=filteredFilms();
    $("#catalogGrid").innerHTML=items.map(function(m){return card(m,false);}).join("");
    $("#emptyState").classList.toggle("hidden",!!items.length);
    $("#resultCount").textContent=items.length+(items.length===1?" largometraje":" largometrajes");
    $("#catalogTitle").innerHTML=state.view==="lista"?"Mi lista<span class=\"period\">.</span>":state.query?"Resultados de búsqueda<span class=\"period\">.</span>":"Explorá el catálogo<span class=\"period\">.</span>";
    $$(".filter").forEach(function(b){b.classList.toggle("active",b.dataset.filter===state.filter);});
    $$("[data-view]").forEach(function(b){b.classList.toggle("active",b.dataset.view===state.view);});
    $("#heroFav").textContent=favorites.has("valkaama2010")?"✓":"＋";
    $("#heroFav").classList.toggle("selected",favorites.has("valkaama2010"));
    $("#heroFav").setAttribute("aria-label",favorites.has("valkaama2010")?"Quitar Valkaama de mi lista":"Agregar Valkaama a mi lista");
  }
  function setView(view){
    state.view=view;state.query="";
    if(view==="cine")state.filter="Películas completas";
    else if(view==="estrenos")state.filter="Películas completas";
    else state.filter="Todo";
    render();
    if(view==="inicio")window.scrollTo({top:0,behavior:"smooth"});
    else $("#allSection").scrollIntoView({behavior:"smooth",block:"start"});
  }
  function setFilter(filter){state.filter=filter;state.query="";if(state.view==="lista")state.view="inicio";render();$("#allSection").scrollIntoView({behavior:"smooth"});}
  function toggleFavorite(id){
    if(!byId[id])return;
    if(favorites.has(id)){favorites.delete(id);showToast("Quitada de tu lista");}else{favorites.add(id);showToast("Agregada a tu lista");}
    write("lumen-play-favorites-v2",Array.from(favorites));render();
    if(state.active===id)updateDetailFavorite();
  }
  function openSearch(){
    $("#searchOverlay").classList.remove("hidden");document.body.style.overflow="hidden";
    $("#searchInput").value=state.query;setTimeout(function(){$("#searchInput").focus();},30);
  }
  function closeSearch(){
    $("#searchOverlay").classList.add("hidden");restoreBody();
  }
  function restoreBody(){
    if(["#searchOverlay","#detailsOverlay","#playerOverlay","#libraryOverlay"].every(function(id){return $(id).classList.contains("hidden");}))document.body.style.overflow="";
  }
  function openDetails(id){
    var m=byId[id];if(!m)return;
    state.active=id;
    $("#detailImage").style.backgroundImage='linear-gradient(0deg,rgba(20,24,33,.4),transparent),url("'+m.image+'")';
    $("#detailTag").textContent="LARGOMETRAJE · REPRODUCCIÓN EN LUMEN PLAY";
    $("#detailTitle").textContent=m.title;
    $("#detailMeta").textContent=m.year+" · "+m.duration+" · "+m.genre+" · "+m.author;
    $("#detailDescription").textContent=m.desc;
    $("#detailCredit").textContent=m.credit;
    $("#detailWatch").textContent="▶ Reproducir acá";
    updateDetailFavorite();
    $("#detailsOverlay").classList.remove("hidden");document.body.style.overflow="hidden";$("#detailsClose").focus();
  }
  function updateDetailFavorite(){
    var m=byId[state.active];if(!m)return;
    $("#detailFav").textContent=favorites.has(m.id)?"✓ En mi lista":"＋ Mi lista";
  }
  function closeDetails(){$("#detailsOverlay").classList.add("hidden");restoreBody();}
  function closeLibrary(){$("#libraryOverlay").classList.add("hidden");restoreBody();}
  function openLibrary(){
    $("#libraryOverlay").classList.remove("hidden");document.body.style.overflow="hidden";$("#libraryClose").focus();
    renderLocal();
  }
  function renderLocal(){
    var root=$("#localList");
    if(!local.length){root.innerHTML='<p class="muted">Todavía no agregaste archivos en esta sesión.</p>';return;}
    root.innerHTML="";
    local.forEach(function(f){
      var item=document.createElement("div");item.className="local-entry";
      var text=document.createElement("div"),title=document.createElement("strong"),sub=document.createElement("span");
      title.textContent=f.name;sub.textContent=(f.size/1024/1024).toFixed(1)+" MB · Archivo en tu dispositivo";text.append(title,sub);
      var btn=document.createElement("button");btn.textContent="Reproducir ▶";btn.addEventListener("click",function(){playLocal(f);});
      item.append(text,btn);root.appendChild(item);
    });
  }
  function addLocalFiles(fileList){
    var good=Array.from(fileList||[]).filter(function(f){return f.type.startsWith("video/")||f.type.startsWith("audio/");});
    good.forEach(function(f){local.push({id:"local-"+Date.now()+"-"+Math.random().toString(36).slice(2),name:f.name,size:f.size,url:URL.createObjectURL(f),mime:f.type});});
    renderLocal();if(good.length)showToast(good.length+" archivo(s) agregado(s)");
  }
  function playLocal(f){
    closeLibrary();
    var m={id:f.id,title:f.name,year:"Local",duration:"",category:"local",author:"Archivo del dispositivo",credit:"Este archivo se reproduce solamente desde tu dispositivo.",origin:"",sources:[{name:"Original",url:f.url}]};
    openPlayer(m);
  }
  function playMovie(id){
    var m=byId[id];if(!m)return;
    if(!m.embed && !availableSources(m).length){showToast("Este título no tiene video compatible");return;}
    openPlayer(m);
  }
  function availableSources(m){
    var canWebm=!!video.canPlayType('video/webm; codecs="vp9"') || !!video.canPlayType("video/webm");
    return (m.sources||[]).filter(function(s){return !s.webm||canWebm;});
  }
  function openPlayer(m){
    closeDetails();
    if(!$("#libraryOverlay").classList.contains("hidden"))closeLibrary();
    state.active=m.id;state.lastProgress=0;
    $("#playerTitle").textContent=m.title;$("#playerCredit").textContent=m.author||"LUMEN Play";
    $("#playerLicense").textContent=m.credit||"";
    $("#playerError").classList.add("hidden");
    var embedBox=$("#embeddedPlayer");
    embedBox.replaceChildren();
    embedBox.classList.toggle("hidden",!m.embed);
    video.classList.toggle("hidden",!!m.embed);
    $(".player-controls").classList.toggle("hidden",!!m.embed);
    var sources=availableSources(m),quality=$("#playerQuality");
    quality.innerHTML="";
    sources.forEach(function(s,i){var opt=document.createElement("option");opt.value=String(i);opt.textContent=s.name;quality.appendChild(opt);});
    $("#playerOverlay").classList.remove("hidden");document.body.style.overflow="hidden";
    video.playbackRate=1;$("#playerSpeed").value="1";
    if(m.embed){
      video.pause();video.removeAttribute("src");video.load();
      var iframe=document.createElement("iframe");
      iframe.title="Reproductor de "+m.title;
      iframe.src=m.embed;
      iframe.setAttribute("allow","accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; fullscreen");
      iframe.setAttribute("referrerpolicy","strict-origin-when-cross-origin");
      iframe.setAttribute("sandbox","allow-scripts allow-same-origin allow-presentation");
      iframe.allowFullscreen=true;
      embedBox.appendChild(iframe);
      return;
    }
    if(!sources.length){video.removeAttribute("src");video.load();$("#playerError").classList.remove("hidden");return;}
    changeSource(sources[0].url, byId[m.id] && progress[m.id] ? progress[m.id].position : 0, true);
  }
  function changeSource(url,time,autoPlay){
    video.pause();video.src=url;video.load();
    if(time>0){video.addEventListener("loadedmetadata",function seekOnce(){video.removeEventListener("loadedmetadata",seekOnce);try{video.currentTime=Math.min(time,Math.max(0,(video.duration||time)-1));}catch(e){}if(autoPlay)video.play().catch(function(){});},{once:true});}
    else if(autoPlay)video.play().catch(function(){});
  }
  function closePlayer(){
    if($("#playerOverlay").classList.contains("hidden"))return;
    captureProgress();
    $("#embeddedPlayer").replaceChildren();
    $("#embeddedPlayer").classList.add("hidden");
    $(".player-controls").classList.remove("hidden");
    video.classList.remove("hidden");
    video.pause();video.removeAttribute("src");video.load();
    if(state.subtitle){URL.revokeObjectURL(state.subtitle);state.subtitle=null;}
    $$("#player track").forEach(function(el){el.remove();});
    $("#playerOverlay").classList.add("hidden");
    restoreBody();render();
  }
  function captureProgress(){
    var m=byId[state.active];if(!m || m.category!=="open" || m.embed || !isFinite(video.currentTime) || !isFinite(video.duration))return;
    var duration=video.duration||m.minutes*60;
    if(video.currentTime>2){progress[m.id]={position:video.currentTime,duration:duration,at:Date.now()};write("lumen-play-progress-v2",progress);}
  }
  function closeAll(){
    if(!$("#playerOverlay").classList.contains("hidden"))closePlayer();
    if(!$("#detailsOverlay").classList.contains("hidden"))closeDetails();
    if(!$("#libraryOverlay").classList.contains("hidden"))closeLibrary();
    if(!$("#searchOverlay").classList.contains("hidden"))closeSearch();
  }
  document.addEventListener("click",function(ev){
    var nav=ev.target.closest("[data-view]");if(nav){setView(nav.dataset.view);return;}
    var fav=ev.target.closest("[data-fav]");if(fav){ev.stopPropagation();toggleFavorite(fav.dataset.fav);return;}
    var item=ev.target.closest(".film-card[data-id]");if(item){openDetails(item.dataset.id);return;}
    var filter=ev.target.closest("[data-filter]");if(filter){setFilter(filter.dataset.filter);}
  });
  document.addEventListener("keydown",function(ev){
    if(ev.key==="Escape"){closeAll();return;}
    if(ev.key==="Enter"||ev.key===" "){var card=document.activeElement.closest(".film-card[data-id]");if(card){ev.preventDefault();openDetails(card.dataset.id);}}
    if(!$("#playerOverlay").classList.contains("hidden") && !["INPUT","TEXTAREA","SELECT","BUTTON"].includes(document.activeElement.tagName)){
      if(ev.key==="ArrowRight"){ev.preventDefault();video.currentTime=Math.min(video.duration||0,video.currentTime+10);}
      if(ev.key==="ArrowLeft"){ev.preventDefault();video.currentTime=Math.max(0,video.currentTime-10);}
    }
  });
  $("#searchBtn").addEventListener("click",openSearch);$("#mobileSearch").addEventListener("click",openSearch);
  $("#searchClose").addEventListener("click",closeSearch);
  $("#searchOverlay").addEventListener("click",function(ev){if(ev.target===this)closeSearch();});
  $("#searchInput").addEventListener("input",function(){state.query=this.value.trim();state.filter="Todo";state.view="inicio";render();});
  $("#searchInput").addEventListener("keydown",function(ev){if(ev.key==="Enter"){closeSearch();$("#allSection").scrollIntoView({behavior:"smooth"});}});
  $("#heroPlay").addEventListener("click",function(){playMovie("valkaama2010");});
  $("#heroMore").addEventListener("click",function(){openDetails("valkaama2010");});
  $("#heroFav").addEventListener("click",function(){toggleFavorite("valkaama2010");});
  $("#exploreBtn").addEventListener("click",function(){setView("cine");});
  $("#detailsClose").addEventListener("click",closeDetails);
  $("#detailsOverlay").addEventListener("click",function(ev){if(ev.target===this)closeDetails();});
  $("#detailWatch").addEventListener("click",function(){playMovie(state.active);});
  $("#detailFav").addEventListener("click",function(){toggleFavorite(state.active);});
  $("#clearFilters").addEventListener("click",function(){state.query="";setView("inicio");$("#allSection").scrollIntoView({behavior:"smooth"});});
  ["#libraryBtn","#libraryOpen","#mobileLibrary"].forEach(function(id){$(id).addEventListener("click",openLibrary);});
  $("#libraryClose").addEventListener("click",closeLibrary);
  $("#libraryOverlay").addEventListener("click",function(ev){if(ev.target===this)closeLibrary();});
  $("#localFiles").addEventListener("change",function(){addLocalFiles(this.files);this.value="";});
  $("#playerClose").addEventListener("click",closePlayer);
  $("#playerFallback").addEventListener("click",function(){
    var m=byId[state.active];
    if(m){openPlayer(m);return;}
    $("#playerError").classList.add("hidden");
    video.load();video.play().catch(function(){$("#playerError").classList.remove("hidden");});
  });
  $("#playerQuality").addEventListener("change",function(){
    var m=byId[state.active]||local.find(function(f){return f.id===state.active;});
    if(!m)return;
    var sources=availableSources(m);
    if(!sources.length||!sources[Number(this.value)])return;
    changeSource(sources[Number(this.value)].url,video.currentTime,!video.paused);
    showToast("Calidad: "+sources[Number(this.value)].name);
  });
  $("#playerSpeed").addEventListener("change",function(){video.playbackRate=Number(this.value)||1;});
  $("#fullscreenBtn").addEventListener("click",function(){
    if(video.requestFullscreen){video.requestFullscreen().catch(function(){showToast("La pantalla completa no está disponible");});}
    else if(video.webkitEnterFullscreen){video.webkitEnterFullscreen();}
  });
  $("#subtitleInput").addEventListener("change",function(){
    var f=this.files&&this.files[0];if(!f)return;
    if(!/\.vtt$/i.test(f.name)){showToast("Solo se admiten subtítulos WebVTT (.vtt)");return;}
    if(state.subtitle)URL.revokeObjectURL(state.subtitle);
    $$("#player track").forEach(function(t){t.remove();});
    state.subtitle=URL.createObjectURL(f);
    var t=document.createElement("track");t.kind="subtitles";t.label="Subtítulos locales";t.srclang="es";t.src=state.subtitle;t.default=true;
    video.appendChild(t);t.addEventListener("load",function(){t.track.mode="showing";});
    showToast("Subtítulos cargados");this.value="";
  });
  video.addEventListener("timeupdate",function(){if(Date.now()-state.lastProgress>4000){captureProgress();state.lastProgress=Date.now();}});
  video.addEventListener("pause",captureProgress);
  video.addEventListener("ended",function(){if(byId[state.active]){delete progress[state.active];write("lumen-play-progress-v2",progress);}showToast("¡Terminaste de ver esta historia!");});
  video.addEventListener("error",function(){var m=byId[state.active];if(m && m.embed)return;if(!$("#playerOverlay").classList.contains("hidden"))$("#playerError").classList.remove("hidden");});
  video.addEventListener("loadeddata",function(){$("#playerError").classList.add("hidden");});
  $("#privacyBtn").addEventListener("click",function(){window.alert("Privacidad en LUMEN Play: los videos que elegís de tu equipo se reproducen localmente y no se suben a nuestro servidor. Los favoritos y el progreso se guardan en el navegador mediante almacenamiento local. Cuando abrís servicios externos, rigen sus propias políticas. Esta versión no incluye cuentas ni seguimiento de perfiles.");});
  window.addEventListener("pagehide",function(){captureProgress();local.forEach(function(f){URL.revokeObjectURL(f.url);});});
  if("serviceWorker" in navigator && location.protocol==="https:"){window.addEventListener("load",function(){navigator.serviceWorker.register("./sw.js").catch(function(){});});}
  render();
}());