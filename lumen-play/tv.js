/* LUMEN Play TV: AirPlay (Safari), Google Cast (Chrome/Android) y navegador Smart TV.
   No ejecuta apps externas. Los archivos deben ser públicos y compatibles con la TV. */
(function(){
  "use strict";
  var $=function(s){return document.querySelector(s);};
  var overlay=$("#tvOverlay"),status=$("#tvStatus"),remote=$("#tvRemote");
  if(!overlay||!status)return;
  var castReady=false,castSupported=false,castContext=null,remotePlayer=null,remoteController=null;
  var lastFocus=null;
  var isIOS=/iPhone|iPad|iPod/i.test(navigator.userAgent)||(/Macintosh/i.test(navigator.userAgent)&&navigator.maxTouchPoints>1);
  var supportsWebCast=!isIOS&&/Chrome|Chromium|Edg|OPR|CrMo/i.test(navigator.userAgent);
  // Las aplicaciones con navegador interno no siempre habilitan AirPlay.
  var likelyIOSBrowser=/Safari/i.test(navigator.userAgent) && !/CriOS|FxiOS|EdgiOS|OPiOS/i.test(navigator.userAgent);
  var guide=$("#tvGuide");
  function showMirrorGuide(){
    if(!isIOS){note("La duplicación de pantalla guiada está pensada para iPhone/iPad. En Android usá las opciones del sistema o Google Cast.");return;}
    guide.classList.remove("hidden");
    note("El selector Duplicar pantalla se abre desde el Centro de control del iPhone, no desde una página web. Seguí las instrucciones que aparecen abajo.");
    if(typeof guide.scrollIntoView==="function")guide.scrollIntoView({behavior:"smooth",block:"nearest"});
  }
  $("#tvMirror").addEventListener("click",showMirrorGuide);
  function compatibleChoices(){
    var video=videoElement();
    $("#tvMirrorChoice").classList.toggle("hidden",!isIOS);
    $("#tvCastChoice").classList.toggle("hidden",!supportsWebCast);
    // No ofrecer selector AirPlay de HTML5 sobre un iframe ajeno.
    var canAirplay=playerIsOpen() && !embeddedIsOpen() && typeof video.webkitShowPlaybackTargetPicker==="function";
    $("#tvAirplayChoice").classList.toggle("hidden",!canAirplay);
    var mode=isIOS?"iPhone / iPad":supportsWebCast?"Chrome compatible con Google Cast":"Navegador sin Cast Web Sender";
    var playing=playerIsOpen()?(embeddedIsOpen()?" · película en reproductor integrado":" · película en video HTML5"):" · elegí una película";
    $("#tvDeviceInfo").textContent="Detectado: "+mode+playing+".";
  }
  var bridge=function(){return window.LUMEN_PLAY_TV||null;};
  function note(text){status.textContent=text;}
  function currentMovie(){
    var b=bridge();
    return b&&b.getMovie?b.getMovie():null;
  }
  function videoElement(){var b=bridge();return b&&b.getVideo?b.getVideo():$("#player");}
  function playerIsOpen(){return !$("#playerOverlay").classList.contains("hidden");}
  function embeddedIsOpen(){return !$("#embeddedPlayer").classList.contains("hidden");}
  function setRemoteUI(){
    var session=castContext&&castContext.getCurrentSession?castContext.getCurrentSession():null;
    remote.classList.toggle("hidden",!session);
    if(session){
      var device=session.getCastDevice?session.getCastDevice():null;
      $("#tvRemoteName").textContent=device&&device.friendlyName?"Conectado a "+device.friendlyName:"TV conectada";
    }
  }
  function openTV(){
    lastFocus=document.activeElement;
    overlay.classList.remove("hidden");
    document.body.style.overflow="hidden";
    compatibleChoices();
    guide.classList.add("hidden");
    var m=currentMovie();
    if(isIOS){
      note("En iPhone, usá Duplicar pantalla en una TV compatible con AirPlay; este navegador no puede hacerlo automáticamente. Si abriste LUMEN dentro de otra app, probá Safari.");
      guide.classList.remove("hidden");
    }else if(!m||!playerIsOpen()){
      note("Elegí un largometraje y tocá Reproducir. Después elegí una conexión compatible.");
    }else {
      note("Película seleccionada: "+m.title+". Elegí una conexión compatible.");
    }
    setRemoteUI();
    $("#tvClose").focus();
  }
  function closeTV(){
    overlay.classList.add("hidden");
    var blocked=["#playerOverlay","#detailsOverlay","#searchOverlay","#libraryOverlay"].some(function(selector){
      var item=$(selector);return item&&!item.classList.contains("hidden");
    });
    if(!blocked)document.body.style.overflow="";
    if(lastFocus&&typeof lastFocus.focus==="function")lastFocus.focus();
  }
  $("#tvTopButton").addEventListener("click",openTV);
  $("#tvPlayerButton").addEventListener("click",openTV);
  $("#tvClose").addEventListener("click",closeTV);
  overlay.addEventListener("click",function(event){if(event.target===overlay)closeTV();});
  document.addEventListener("keydown",function(event){
    if(event.key==="Escape"&&!overlay.classList.contains("hidden")){
      event.preventDefault();event.stopImmediatePropagation();closeTV();
    }
  },true);
  $("#tvUrl").textContent=location.host;
  $("#tvCopy").addEventListener("click",function(){
    var url=location.origin+"/?tv=1";
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(url).then(function(){note(isIOS?"Dirección copiada. Podés pegarla en Safari del iPhone o escribirla en el navegador de la TV.":"Dirección copiada. Abrila en el navegador de tu Smart TV.");},
      function(){note("Escribí en el navegador de la TV: "+location.host);});
    }else note("Escribí en el navegador de la TV: "+location.host);
  });
  $("#tvAirPlay").addEventListener("click",function(){
    var m=currentMovie(),video=videoElement();
    if(!m||!playerIsOpen()){note("Primero seleccioná una película y abrí su reproductor.");return;}
    if(embeddedIsOpen()){
      if(isIOS){showMirrorGuide();note("Este video se reproduce dentro de una ventana integrada; el botón AirPlay de LUMEN no puede controlarla. Usá Duplicar pantalla en un televisor AirPlay compatible.");}
      else note("El video usa un reproductor integrado que no controlamos desde el botón AirPlay. Si no tiene su propio icono AirPlay, abrí la web en la TV.");
      return;
    }
    if(typeof video.webkitShowPlaybackTargetPicker==="function"){
      try{video.webkitShowPlaybackTargetPicker();note("Seleccioná tu televisor AirPlay en el selector de Safari. Ambos equipos deben usar la misma red Wi-Fi.");}
      catch(err){note("No se pudo abrir AirPlay. Probá reproducir primero el video en Safari.");}
      return;
    }
    if(video.remote&&typeof video.remote.prompt==="function"){
      video.remote.prompt().then(function(){note("Se abrió el selector de pantalla inalámbrica.");},
      function(){note("No hay un dispositivo compatible disponible desde este navegador.");});
      return;
    }
    if(isIOS)showMirrorGuide();
    else note("AirPlay no está disponible en este navegador; probá Safari en un dispositivo Apple.");
  });
  function publicStream(m){
    if(!m)return null;
    var v=videoElement(),usingHTML5=playerIsOpen()&&!embeddedIsOpen();
    // No enviar al Chromecast una dirección adivinada desde una película en iframe;
    // esa URL nunca se verificó en este reproductor y suele fallar en el receptor.
    if(!usingHTML5||v.error||v.readyState<1)return null;
    var url=v.currentSrc||v.src;
    if(!/^https:\/\//i.test(url))url="";
    // El video debe estar cargado en HTML5 antes de abrir el selector Cast.
    if(!url||!/^https:\/\//i.test(url))return null;
    var mime=/\.webm(\?|$)/i.test(url)?"video/webm":/\.m3u8(\?|$)/i.test(url)?"application/x-mpegURL":"video/mp4";
    return {url:url,type:mime,time:usingHTML5&&isFinite(v.currentTime)?Math.max(0,v.currentTime):0};
  }
  async function castMovie(session,m){
    var src=publicStream(m);
    if(!src){note("Esta película no tiene un archivo directo compatible para Cast. Podés abrir LUMEN Play en el navegador de tu TV.");return;}
    try{
      var info=new chrome.cast.media.MediaInfo(src.url,src.type);
      info.streamType=chrome.cast.media.StreamType.BUFFERED;
      var metadata=new chrome.cast.media.MovieMediaMetadata();
      metadata.title=m.title;
      metadata.subtitle=m.author||"LUMEN Play";
      if(m.image&&/^https:\/\//.test(m.image))metadata.images=[new chrome.cast.Image(m.image)];
      info.metadata=metadata;
      var request=new chrome.cast.media.LoadRequest(info);
      request.currentTime=src.time;
      note("Enviando "+m.title+" al televisor…");
      await session.loadMedia(request);
      if(playerIsOpen()&&!embeddedIsOpen())videoElement().pause();
      note("Película enviada a la TV. Podés controlarla desde esta pantalla.");
      setRemoteUI();
    }catch(err){note("La TV rechazó este archivo o no pudo descargarlo. Probá otra película, otro formato o el navegador de la TV.");}
  }
  $("#tvCast").addEventListener("click",async function(){
    if(isIOS){note("Google Cast Web Sender no funciona desde Safari ni Chrome en iPhone. Usá AirPlay o abrí LUMEN Play directamente en Google TV.");return;}
    if(!supportsWebCast){note("Google Cast desde la web requiere Chrome compatible en Android o computadora. En otra TV usá su navegador.");return;}
    if(!castReady||!castContext){note("Chromecast todavía no está disponible. Revisá que uses Chrome, estés en Wi-Fi y tengas Google Cast habilitado.");return;}
    var m=currentMovie();
    if(!m||!playerIsOpen()){note("Primero abrí la película que querés ver y después volvé a tocar Ver en TV.");return;}
    if(!publicStream(m)){note("Para transmitir con Cast, primero reproducí un MP4 compatible en LUMEN. Los reproductores integrados de terceros no permiten enviar el video desde este módulo. Como alternativa abrí LUMEN Play en el navegador de la TV.");return;}
    try{
      var session=castContext.getCurrentSession();
      if(!session){note("Buscando Chromecast o Google TV en tu red…");await castContext.requestSession();session=castContext.getCurrentSession();}
      if(!session){note("No se conectó ninguna TV. Revisá la misma red Wi-Fi.");return;}
      await castMovie(session,m);
    }catch(err){note("No se pudo establecer la conexión Cast. Comprobá que la TV y el navegador estén en la misma red Wi-Fi.");}
  });
  $("#tvRemotePause").addEventListener("click",function(){
    if(remoteController&&remotePlayer&&remotePlayer.isConnected){
      remoteController.playOrPause();
      note("Control de reproducción enviado a la TV.");
    }else note("No hay una sesión Cast activa.");
  });
  $("#tvDisconnect").addEventListener("click",function(){
    var session=castContext&&castContext.getCurrentSession?castContext.getCurrentSession():null;
    if(session){session.endSession(true);note("Desconectando de la TV…");}
    else note("No hay ninguna TV conectada.");
    setRemoteUI();
  });
  // La API Web Sender no está disponible en Safari/iOS. Se evita cargarla allí.
  if(supportsWebCast&&location.protocol==="https:"){
    window.__onGCastApiAvailable=function(isAvailable){
      if(!isAvailable||!window.cast||!window.chrome||!chrome.cast)return;
      try{
        castContext=cast.framework.CastContext.getInstance();
        castContext.setOptions({
          receiverApplicationId:chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
          autoJoinPolicy:chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED
        });
        remotePlayer=new cast.framework.RemotePlayer();
        remoteController=new cast.framework.RemotePlayerController(remotePlayer);
        castContext.addEventListener(cast.framework.CastContextEventType.SESSION_STATE_CHANGED,function(){
          setRemoteUI();
        });
        castReady=true;
        castSupported=true;
        setRemoteUI();
      }catch(err){castReady=false;}
    };
    var sdk=document.createElement("script");
    sdk.src="https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";
    sdk.async=true;
    sdk.onerror=function(){castReady=false;castSupported=false;};
    document.head.appendChild(sdk);
  }
  // El modo TV permite operar con control remoto mediante tabulador/foco visible.
  compatibleChoices();
  if(new URLSearchParams(location.search).get("tv")==="1"){
    document.body.classList.add("tv-mode");
  }
}());
