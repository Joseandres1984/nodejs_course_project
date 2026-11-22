/* LUMEN Play 2.0 — independent static edition. Third-party rights remain with their authors. */
(function () {
  "use strict";
  var REPO = "https://studio.blender.org/films/";
  var MP4 = "https://video.blender.org/download/web-videos/";
  var COMMONS = "https://commons.wikimedia.org/wiki/Special:Redirect/file/";
  var thumb = function(id){ return "https://i.ytimg.com/vi/" + id + "/hqdefault.jpg"; };
  var still = function(id){ return "https://i.ytimg.com/vi/" + id + "/maxresdefault.jpg"; };
  var cc = "Cine abierto · CC BY · Blender Studio / Blender Foundation. Créditos y licencias en la página del proyecto original.";
  var film = [
    {id:"charge",title:"Charge",year:2022,duration:"4 min",minutes:4,genre:"Ciencia ficción",category:"open",kind:"Animación",desc:"En un mundo que se queda sin energía, un hombre lucha por su última oportunidad de sobrevivir.",image:still("UXqq0ZvbOnk"),author:"Blender Studio",credit:cc,origin:"https://studio.blender.org/projects/charge/",sources:[{name:"HD · 1080p",url:MP4+"04da454b-9893-4184-98f3-248d00625efe-1080.mp4"},{name:"4K · WebM",url:COMMONS+"Charge_-_Blender_Open_Movie-full_movie.webm",webm:true}]},
    {id:"spring",title:"Spring",year:2019,duration:"8 min",minutes:8,genre:"Fantasía",category:"open",kind:"Animación",desc:"Una pastora, su perro y un mundo ancestral despiertan en una conmovedora historia sin diálogos.",image:still("WhWc3b3KhnY"),author:"Blender Animation Studio",credit:cc,origin:"https://studio.blender.org/projects/spring/",sources:[{name:"HD · 720p",url:MP4+"3d95fb3d-c866-42c8-9db1-fe82f48ccb95-720.mp4"},{name:"2K · WebM",url:COMMONS+"Spring_-_Blender_Open_Movie.webm",webm:true}]},
    {id:"sintel",title:"Sintel",year:2010,duration:"15 min",minutes:15,genre:"Fantasía",category:"open",kind:"Animación",desc:"Una joven recorre un mundo helado buscando al pequeño dragón que una vez salvó.",image:thumb("eRsGyueVLvQ"),author:"Blender Foundation",credit:cc,origin:"https://studio.blender.org/films/sintel/",sources:[{name:"HD · 720p",url:MP4+"0eb052d0-fd51-43e6-aa33-ecdbf77a5d40-720.mp4"}]},
    {id:"sprite",title:"Sprite Fright",year:2021,duration:"10 min",minutes:10,genre:"Comedia",category:"open",kind:"Animación",desc:"Un grupo de adolescentes descubre que el bosque esconde sorpresas tan divertidas como inquietantes.",image:thumb("_cMxraX_5RE"),author:"Blender Studio",credit:cc,origin:"https://studio.blender.org/films/sprite-fright/",sources:[{name:"HD · 720p",url:MP4+"a69d68a5-a0e0-4a80-9d66-49f093c97aaf-720.mp4"},{name:"2K · WebM",url:COMMONS+"Sprite_Fright_-_Blender_Open_Movie-full_movie.webm",webm:true}]},
    {id:"tears",title:"Tears of Steel",year:2012,duration:"12 min",minutes:12,genre:"Ciencia ficción",category:"open",kind:"Acción",desc:"Ámsterdam está bajo ataque y los recuerdos de una vieja historia podrían salvar el futuro.",image:thumb("R6MlUcmOul8"),author:"Blender Institute",credit:cc,origin:"https://studio.blender.org/films/tears-of-steel/",sources:[{name:"HD · 720p",url:MP4+"8533ea43-4271-4a57-9694-e9d0b35e1aa1-720.mp4"},{name:"4K · WebM",url:COMMONS+"Tears_of_Steel_in_4k_-_Official_Blender_Foundation_release.webm",webm:true}]},
    {id:"bunny",title:"Big Buck Bunny",year:2008,duration:"10 min",minutes:10,genre:"Comedia",category:"open",kind:"Animación",desc:"Un conejo gigante le da una inolvidable lección a tres pequeños abusones.",image:thumb("YE7VzlLtp-4"),author:"Blender Foundation",credit:cc,origin:"https://studio.blender.org/films/big-buck-bunny/",sources:[{name:"HD · 720p",url:MP4+"bf1f3fb5-b119-4f9f-9930-8e20e892b898-720.mp4"}]},
    {id:"wingit",title:"Wing It!",year:2023,duration:"4 min",minutes:4,genre:"Comedia",category:"open",kind:"Animación",desc:"Un gato, un ratón y un invento volador protagonizan una aventura desopilante.",image:thumb("u9lj-c29dxI"),author:"Blender Studio",credit:cc,origin:"https://studio.blender.org/films/wing-it/",sources:[{name:"HD · 1080p",url:MP4+"bd0084a5-1d26-4816-ab5e-1bad9e2fb990-1080.mp4"}]},
    {id:"agent",title:"Agent 327",year:2017,duration:"4 min",minutes:4,genre:"Comedia",category:"open",kind:"Acción",desc:"Un agente secreto entra a una barbería y empieza una misión tan peligrosa como absurda.",image:thumb("mN0zPOpADL4"),author:"Blender Studio",credit:cc,origin:"https://studio.blender.org/films/agent-327/",sources:[{name:"HD · MP4",url:MP4+"264ff760-803e-430e-8d81-15648e904183-804.mp4"}]},
    {id:"caminandes",title:"Caminandes: Llamigos",year:2016,duration:"3 min",minutes:3,genre:"Comedia",category:"open",kind:"Animación",desc:"Dos llamas y el césped patagónico: una rivalidad pequeña con consecuencias gigantes.",image:thumb("SkVqJ1SGeL0"),author:"Blender Studio",credit:cc,origin:"https://studio.blender.org/films/caminandes-3/",sources:[{name:"HD · 1080p",url:MP4+"23f3ef79-15dc-44c5-aa45-cf92e78a4509-1080.mp4"}]},
    {id:"coffee",title:"Coffee Run",year:2020,duration:"3 min",minutes:3,genre:"Drama",category:"open",kind:"Animación",desc:"Un café, un recuerdo y un torbellino de sentimientos en apenas tres minutos.",image:thumb("PVGeM40dABA"),author:"Blender Studio",credit:cc,origin:"https://studio.blender.org/films/coffee-run/",sources:[{name:"Full HD · WebM",url:COMMONS+"Coffee_Run_-_Blender_Open_Movie-full_movie.webm",webm:true}]},
    {id:"f1",title:"F1: la película",year:2025,duration:"2 h 35 min",minutes:155,genre:"Acción",category:"new",kind:"Drama",desc:"Un veterano piloto vuelve al circuito para ayudar a un equipo de Fórmula 1 a conseguir lo imposible.",image:"https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=900&q=80",author:"Película comercial",credit:"Título comercial. Imagen ilustrativa. LUMEN Play no aloja ni transmite esta película.",origin:"https://www.justwatch.com/ar/buscar?q=F1"},
    {id:"sinners",title:"Los pecadores",year:2025,duration:"2 h 17 min",minutes:137,genre:"Terror",category:"new",kind:"Drama",desc:"Dos hermanos regresan a su tierra natal y encuentran una amenaza aún más oscura.",image:"https://images.unsplash.com/photo-1518709268805-4e9042af9f23?auto=format&fit=crop&w=900&q=80",author:"Película comercial",credit:"Título comercial. Imagen ilustrativa. Ver disponibilidad en servicios oficiales.",origin:"https://www.justwatch.com/ar/pelicula/pecadores"},
    {id:"onebattle",title:"Una batalla tras otra",year:2025,duration:"2 h 41 min",minutes:161,genre:"Acción",category:"new",kind:"Drama",desc:"Un hombre se ve obligado a volver a un mundo turbulento cuando su pasado golpea de nuevo.",image:"https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=900&q=80",author:"Película comercial",credit:"Título comercial. Imagen ilustrativa. Ver disponibilidad en servicios oficiales.",origin:"https://www.justwatch.com/ar/buscar?q=Una%20batalla%20tras%20otra"},
    {id:"frankenstein",title:"Frankenstein",year:2025,duration:"2 h 29 min",minutes:149,genre:"Fantasía",category:"new",kind:"Drama",desc:"Guillermo del Toro reimagina la historia del creador y la criatura que transforma su vida.",image:"https://images.unsplash.com/photo-1511497584788-876760111969?auto=format&fit=crop&w=900&q=80",author:"Película comercial",credit:"Título comercial. Imagen ilustrativa. Ver disponibilidad en servicios oficiales.",origin:"https://www.netflix.com/search?q=Frankenstein"},
    {id:"traindreams",title:"Sueños de trenes",year:2025,duration:"1 h 42 min",minutes:102,genre:"Drama",category:"new",kind:"Drama",desc:"La historia íntima de una vida entre los cambios del mundo y la belleza de lo cotidiano.",image:"https://images.unsplash.com/photo-1473448912268-2022ce9509d8?auto=format&fit=crop&w=900&q=80",author:"Película comercial",credit:"Título comercial. Imagen ilustrativa. Ver disponibilidad en servicios oficiales.",origin:"https://www.netflix.com/search?q=Train%20Dreams"},
    {id:"kpop",title:"Las guerreras K-pop",year:2025,duration:"1 h 35 min",minutes:95,genre:"Animación",category:"new",kind:"Fantasía",desc:"Un grupo musical con una vida secreta debe defender al mundo de fuerzas sobrenaturales.",image:"https://images.unsplash.com/photo-1514525253161-7a46d19cd819?auto=format&fit=crop&w=900&q=80",author:"Película comercial",credit:"Título comercial. Imagen ilustrativa. Ver disponibilidad en servicios oficiales.",origin:"https://www.netflix.com/search?q=KPop%20Demon%20Hunters"}
  ];
  film.push.apply(film, window.LUMEN_EXTRA_FILMS || []);
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
      '<span class="card-label '+(m.category==="open"?"open":"")+'">'+(m.category==="open"?"CINE ABIERTO":"DESTACADA")+'</span>' +
      '<div class="poster-bottom"><span class="poster-min">'+html(m.year)+' · '+html(m.duration)+'</span><span class="card-play" aria-hidden="true">▶</span></div>' +
      (continueMode?'<div class="progress-track"><span style="width:'+pct.toFixed(1)+'%"></span></div>':'')+'</div>' +
      '<div class="card-info"><div><h3 class="card-title">'+html(m.title)+'</h3><p class="card-sub">'+html(m.genre)+' · '+(m.category==="open"?(m.sources&&m.sources.length?"Reproducir gratis":"Ver gratis en Blender"):"Ver opciones")+'</p></div>' +
      '<button class="card-save '+(saved?"saved":"")+'" data-fav="'+html(m.id)+'" type="button" aria-label="'+(saved?"Quitar de mi lista":"Agregar a mi lista")+'">'+(saved?"♥":"♡")+'</button></div></article>';
  }
  function renderRail(id,items,mode){
    var rail=$(id);if(!rail)return;rail.innerHTML=items.map(function(m){return card(m,mode);}).join("");
  }
  function filteredFilms(){
    var items=film.slice();
    if(state.view==="lista")items=items.filter(function(m){return favorites.has(m.id);});
    else if(state.filter==="Cine abierto")items=items.filter(function(m){return m.category==="open";});
    else if(state.filter==="Destacadas")items=items.filter(function(m){return m.category==="new";});
    else if(state.filter==="Estrenos 2026")items=items.filter(function(m){return m.year===2026;});
    else if(state.filter!=="Todo")items=items.filter(function(m){return m.genre===state.filter || m.kind===state.filter;});
    if(state.query){var q=state.query.toLocaleLowerCase("es");items=items.filter(function(m){return [m.title,m.genre,m.kind,m.desc,m.author,String(m.year)].join(" ").toLocaleLowerCase("es").indexOf(q)!==-1;});}
    return items;
  }
  function render(){
    renderRail("#featuredRail",[byId.charge,byId.spring,byId.sintel,byId.sprite,byId.tears,byId.wingit]);
    renderRail("#openRail",film.filter(function(m){return m.category==="open";}));
    renderRail("#newRail",film.filter(function(m){return m.category==="new";}).sort(function(a,b){return b.year-a.year;}));
    var continuable=Object.keys(progress).filter(function(id){return byId[id] && progress[id].position>7 && progress[id].duration && progress[id].position<progress[id].duration-7;}).map(function(id){return byId[id];});
    $("#continueSection").classList.toggle("hidden",!continuable.length);
    renderRail("#continueRail",continuable,true);
    var items=filteredFilms();
    $("#catalogGrid").innerHTML=items.map(function(m){return card(m,false);}).join("");
    $("#emptyState").classList.toggle("hidden",!!items.length);
    $("#resultCount").textContent=items.length+" títulos";
    $("#catalogTitle").innerHTML=state.view==="lista"?"Mi lista<span class=\"period\">.</span>":state.query?"Resultados de búsqueda<span class=\"period\">.</span>":"Explorá el catálogo<span class=\"period\">.</span>";
    $$(".filter").forEach(function(b){b.classList.toggle("active",b.dataset.filter===state.filter);});
    $$("[data-view]").forEach(function(b){b.classList.toggle("active",b.dataset.view===state.view);});
    $("#heroFav").textContent=favorites.has("charge")?"✓":"＋";
    $("#heroFav").classList.toggle("selected",favorites.has("charge"));
    $("#heroFav").setAttribute("aria-label",favorites.has("charge")?"Quitar Charge de mi lista":"Agregar Charge a mi lista");
  }
  function setView(view){
    state.view=view;state.query="";
    if(view==="cine")state.filter="Cine abierto";
    else if(view==="estrenos")state.filter="Destacadas";
    else state.filter="Todo";
    render();
    if(view==="inicio")window.scrollTo({top:0,behavior:"smooth"});
    else $("#allSection").scrollIntoView({behavior:"smooth",block:"start"});
  }
  function setFilter(filter){state.filter=filter;if(state.view==="lista")state.view="inicio";render();$("#allSection").scrollIntoView({behavior:"smooth"});}
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
    $("#detailTag").textContent=m.category==="open"?(m.sources&&m.sources.length?"CINE ABIERTO · REPRODUCCIÓN GRATIS":"CINE ABIERTO · VER EN BLENDER"):"PELÍCULA COMERCIAL · PLATAFORMA OFICIAL";
    $("#detailTitle").textContent=m.title;
    $("#detailMeta").textContent=m.year+" · "+m.duration+" · "+m.genre+" · "+(m.category==="open"?"Blender":"Ver disponibilidad");
    $("#detailDescription").textContent=m.desc;
    $("#detailCredit").textContent=m.credit;
    $("#detailWatch").textContent=m.category==="open"?(m.sources&&m.sources.length?"▶ Reproducir gratis":"↗ Ver gratis en Blender"):"↗ Dónde verla";
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
    if(m.category==="new" || (m.category==="open" && !(m.sources&&m.sources.length))){window.open(m.origin,"_blank","noopener,noreferrer");return;}
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
    $("#playerFallback").href=m.origin||REPO;
    $("#playerError").classList.add("hidden");
    var sources=availableSources(m),quality=$("#playerQuality");
    quality.innerHTML="";
    sources.forEach(function(s,i){var opt=document.createElement("option");opt.value=String(i);opt.textContent=s.name;quality.appendChild(opt);});
    $("#playerOverlay").classList.remove("hidden");document.body.style.overflow="hidden";
    video.playbackRate=1;$("#playerSpeed").value="1";
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
    video.pause();video.removeAttribute("src");video.load();
    if(state.subtitle){URL.revokeObjectURL(state.subtitle);state.subtitle=null;}
    $$("#player track").forEach(function(el){el.remove();});
    $("#playerOverlay").classList.add("hidden");
    restoreBody();render();
  }
  function captureProgress(){
    var m=byId[state.active];if(!m || m.category!=="open" || !isFinite(video.currentTime) || !isFinite(video.duration))return;
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
  $("#heroPlay").addEventListener("click",function(){playMovie("charge");});
  $("#heroMore").addEventListener("click",function(){openDetails("charge");});
  $("#heroFav").addEventListener("click",function(){toggleFavorite("charge");});
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
  video.addEventListener("error",function(){if(!$("#playerOverlay").classList.contains("hidden"))$("#playerError").classList.remove("hidden");});
  video.addEventListener("loadeddata",function(){$("#playerError").classList.add("hidden");});
  $("#privacyBtn").addEventListener("click",function(){window.alert("Privacidad en LUMEN Play: los videos que elegís de tu equipo se reproducen localmente y no se suben a nuestro servidor. Los favoritos y el progreso se guardan en el navegador mediante almacenamiento local. Cuando abrís servicios externos, rigen sus propias políticas. Esta versión no incluye cuentas ni seguimiento de perfiles.");});
  window.addEventListener("pagehide",function(){captureProgress();local.forEach(function(f){URL.revokeObjectURL(f.url);});});
  if("serviceWorker" in navigator && location.protocol==="https:"){window.addEventListener("load",function(){navigator.serviceWorker.register("./sw.js").catch(function(){});});}
  render();
}());