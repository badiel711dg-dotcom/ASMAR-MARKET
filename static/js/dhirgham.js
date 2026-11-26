(function(){
    "use strict";

    const root=document.getElementById("dhirgham-widget");
    if(!root || root.dataset.initialized==="1") return;
    root.dataset.initialized="1";

    const panel=document.getElementById("dhirghamPanel");
    const launcher=document.getElementById("dhirghamLauncher");
    const close=document.getElementById("dhirghamClose");
    const form=document.getElementById("dhirghamForm");
    const input=document.getElementById("dhirghamInput");
    const send=document.getElementById("dhirghamSend");
    const mic=document.getElementById("dhirghamMic");
    const messages=document.getElementById("dhirghamMessages");
    const suggestions=document.getElementById("dhirghamSuggestions");
    const csrf=root.dataset.csrf || "";
    const storageKey="moder_one_dhirgham_v1_"+(root.dataset.chatScope || "guest");
    const MAX_HISTORY=16;

    let history=[];
    let recognition=null;
    let listening=false;
    let voiceReplies=false;
    let speaking=false;
    let currentAudio=null;
    let currentAudioUrl=null;
    let ttsController=null;
    let speechGeneration=0;
    let voiceConversation=false;
    let voiceBusy=false;
    let voiceRestartTimer=null;

    // Keep the assistant panel inside the visible viewport when the
    // mobile keyboard opens, without freezing the page behind it.
    const dhirghamViewport=window.visualViewport;

    function syncDhirghamViewport(){
        if(!dhirghamViewport) return;

        const height=dhirghamViewport.height;
        const top=dhirghamViewport.offsetTop || 0;
        const keyboardOpen=(window.innerHeight-height)>120;

        root.style.setProperty("--dh-vv-height",Math.max(180,height)+"px");
        root.style.setProperty("--dh-vv-top",Math.max(0,top)+"px");
        root.classList.toggle("keyboard-open",keyboardOpen && !panel.hidden);
    }

    if(dhirghamViewport){
        dhirghamViewport.addEventListener("resize",syncDhirghamViewport);
        dhirghamViewport.addEventListener("scroll",syncDhirghamViewport);
    }
    window.addEventListener("resize",syncDhirghamViewport);
    window.addEventListener("orientationchange",()=>{
        window.setTimeout(syncDhirghamViewport,150);
    });

    const voiceStatus=document.createElement("div");
    voiceStatus.className="dhirgham-voice-status";
    voiceStatus.setAttribute("role","status");
    voiceStatus.setAttribute("aria-live","polite");
    form.parentNode.insertBefore(voiceStatus,form);

    function setVoiceStatus(text){
        voiceStatus.textContent=text || "";
        voiceStatus.classList.toggle("visible",!!text);
    }

    function persistHistory(){
        try{
            const safe=history.slice(-MAX_HISTORY).map(item=>({
                type:item.type,
                text:String(item.text).slice(0,700),
                signature:item.type==="assistant" ? String(item.signature || "") : ""
            }));
            sessionStorage.setItem(storageKey,JSON.stringify(safe));
        }catch(error){}
    }

    function containsSensitiveData(value){
        return /(password|passcode|otp|cvv|cvc|كلمة\s*المرور|رمز\s*التحقق|كود\s*التحقق|الرقم\s*السري|بيانات\s*البطاقة|رقم\s*البطاقة)/i.test(value)
            || /[\w.+-]+@[\w.-]+\.[a-z]{2,}/i.test(value)
            || /(?:\+?\d[\d\s-]{7,}\d)/.test(value);
    }

    function addMessage(text,type,options={}){
        const item=document.createElement("div");
        item.className="dhirgham-message "+type;

        if(type==="assistant"){
            const avatar=document.createElement("img");
            avatar.className="dhirgham-message-avatar";
            avatar.src=root.querySelector(".dhirgham-avatar img")?.src || "/static/images/dhirgham-avatar.jpg";
            avatar.alt="ضِرغام";
            avatar.loading="lazy";

            const content=document.createElement("span");
            content.className="dhirgham-message-text";
            const fullText=String(text);
            const animate=options.animate===true;
            content.textContent=animate ? "" : fullText;

            item.append(avatar,content);

            if(animate && fullText){
                const characters=Array.from(fullText);
                const delay=characters.length<=250 ? 20 :
                    characters.length<=700 ? 12 :
                    characters.length<=1500 ? 6 : 2;
                let index=0;

                const writeNext=()=>{
                    if(!content.isConnected) return;
                    content.textContent+=characters[index++];
                    const nearBottom=messages.scrollHeight-messages.scrollTop-messages.clientHeight<80;
                    if(nearBottom) messages.scrollTop=messages.scrollHeight;
                    if(index<characters.length) window.setTimeout(writeNext,delay);
                };

                messages.appendChild(item);
                messages.scrollTop=messages.scrollHeight;
                writeNext();
                return item;
            }
        }else{
            item.textContent=String(text);
        }

        messages.appendChild(item);
        messages.scrollTop=messages.scrollHeight;
        return item;
    }

    function restoreHistory(){
        try{
            const saved=JSON.parse(sessionStorage.getItem(storageKey) || "[]");
            if(!Array.isArray(saved)) return;
            const safe=saved.filter(item=>
                item && ["user","assistant"].includes(item.type) &&
                typeof item.text==="string" &&
                item.text.length<=700 &&
                (item.type!=="assistant" ||
                    (typeof item.signature==="string" && /^[a-f0-9]{64}$/.test(item.signature))) &&
                !containsSensitiveData(item.text)
            ).slice(-MAX_HISTORY);
            if(!safe.length) return;
            history=safe;
            messages.innerHTML="";
            safe.forEach(item=>addMessage(item.text,item.type));
        }catch(error){
            history=[];
        }
    }

    function resolvePageContext(){
        const path=window.location.pathname;
        if(path==="/") return "home";
        if(path==="/welcome") return "welcome";
        if(path.startsWith("/categories")) return "category";
        if(path.startsWith("/product/")) return "product";
        if(path.startsWith("/store/")) return "store";
        if(path==="/cart" || path.startsWith("/cart/")) return "cart";
        if(path==="/checkout") return "checkout";
        if(path==="/customer/login" || path==="/login") return "customer_login";
        if(path==="/customer/register" || path==="/register") return "customer_register";
        if(path==="/customer/account") return "customer_account";
        if(path==="/customer/orders") return "customer_orders";
        if(path==="/customer/notifications") return "customer_account";
        if(path.startsWith("/customer/complaints")) return "customer_account";
        if(path.startsWith("/order/success/")) return "customer_orders";
        if(path==="/merchant/login") return "merchant_login";
        if(path==="/merchant/register") return "merchant_register";
        if(path==="/merchant/dashboard") return "merchant_dashboard";
        if(path==="/merchant/product/add") return "add_product";
        if(path.startsWith("/merchant/product/")) return "edit_product";
        if(path==="/merchant/orders" || path.startsWith("/merchant/order/")) return "merchant_orders";
        if(path==="/merchant/settings") return "merchant_settings";
        if(path==="/merchant/analytics" || path==="/merchant/statistics" || path==="/merchant/basic-statistics") return "merchant_analytics";
        if(path==="/merchant/notifications") return "merchant_dashboard";
        if(path.startsWith("/merchant/complaints")) return "merchant_dashboard";
        if(path.startsWith("/merchant/coupons")) return "merchant_dashboard";
        if(path.startsWith("/merchant/offers")) return "merchant_dashboard";
        if(path.startsWith("/merchant/promotions")) return "merchant_dashboard";
        if(path.startsWith("/merchant/subscription")) return "merchant_settings";
        return root.dataset.pageContext || "general";
    }

    root.dataset.pageContext=resolvePageContext();

    function stopSpeaking(){
        speechGeneration++;

        if(ttsController){
            ttsController.abort();
            ttsController=null;
        }

        if(currentAudio){
            currentAudio.pause();
            currentAudio.onended=null;
            currentAudio.onerror=null;
            currentAudio=null;
        }

        if(currentAudioUrl){
            URL.revokeObjectURL(currentAudioUrl);
            currentAudioUrl=null;
        }

        if("speechSynthesis" in window){
            window.speechSynthesis.cancel();
        }

        speaking=false;
    }

    function clearVoiceRestart(){
        if(voiceRestartTimer){
            clearTimeout(voiceRestartTimer);
            voiceRestartTimer=null;
        }
    }

    function scheduleVoiceRestart(){
        clearVoiceRestart();
        if(!voiceConversation || voiceBusy || speaking) return;
        voiceRestartTimer=setTimeout(()=>{
            voiceRestartTimer=null;
            if(voiceConversation && !voiceBusy && !speaking && !panel.hidden){
                startRecognitionCycle();
            }
        },450);
    }

    function stopVoiceConversation(){
        voiceConversation=false;
        voiceBusy=false;
        clearVoiceRestart();
        stopListening();
        stopSpeaking();
        voiceReplies=false;
        setVoiceStatus("");
        if(mic){
            mic.classList.remove("is-voice-active");
            mic.disabled=false;
            mic.setAttribute("aria-label","بدء الاستماع");
            mic.title="تحدث مع ضِرغام";
        }
    }

    async function speakAnswer(text){
        if(!voiceReplies) return;

        stopSpeaking();
        const generation=speechGeneration;
        const controller=new AbortController();
        ttsController=controller;

        setVoiceStatus("ضِرغام يُحضّر صوته...");

        try{
            const response=await fetch("/api/dhirgham/tts",{
                method:"POST",
                credentials:"same-origin",
                headers:{
                    "Content-Type":"application/json",
                    "X-CSRFToken":csrf
                },
                body:JSON.stringify({text:String(text)}),
                signal:controller.signal
            });

            if(!response.ok){
                throw new Error("TTS_HTTP_"+response.status);
            }

            const blob=await response.blob();

            if(generation!==speechGeneration) return;
            if(!blob.size || blob.size>6*1024*1024){
                throw new Error("TTS_INVALID_AUDIO");
            }

            currentAudioUrl=URL.createObjectURL(blob);
            currentAudio=new Audio(currentAudioUrl);

            currentAudio.onplay=()=>{
                if(generation!==speechGeneration) return;
                speaking=true;
                setVoiceStatus("ضِرغام يتحدث الآن");
            };

            currentAudio.onended=()=>{
                if(generation!==speechGeneration) return;
                speaking=false;
                currentAudio=null;
                if(currentAudioUrl){
                    URL.revokeObjectURL(currentAudioUrl);
                    currentAudioUrl=null;
                }
                ttsController=null;
                voiceBusy=false;
                if(voiceConversation){
                    setVoiceStatus("انتهى ضِرغام من الرد. يستمع إليك...");
                    scheduleVoiceRestart();
                }else{
                    setVoiceStatus(listening ? "ضِرغام يستمع إليك" : "");
                }
            };

            currentAudio.onerror=()=>{
                if(generation!==speechGeneration) return;
                stopSpeaking();
                voiceBusy=false;
                setVoiceStatus("تعذر تشغيل صوت ضِرغام. يمكنك قراءة الرد.");
                scheduleVoiceRestart();
            };

            ttsController=null;
            await currentAudio.play();

        }catch(error){
            if(error.name==="AbortError") return;
            if(generation!==speechGeneration) return;

            stopSpeaking();
            voiceBusy=false;
            setVoiceStatus("تعذر توليد صوت ضِرغام حالياً. يمكنك قراءة الرد.");
            scheduleVoiceRestart();
        }
    }

    function stopListening(){
        const activeRecognition=recognition;
        recognition=null;

        if(activeRecognition){
            try{activeRecognition.stop();}catch(error){}
        }

        listening=false;
        if(mic){
            mic.classList.remove("is-listening");
            mic.setAttribute("aria-label","بدء الاستماع");
            mic.title="تحدث مع ضِرغام";
        }
    }

    function startRecognitionCycle(){
        if(!voiceConversation || voiceBusy || speaking || panel.hidden) return;

        const SpeechRecognition=window.SpeechRecognition || window.webkitSpeechRecognition;

        if(!SpeechRecognition){
            setVoiceStatus("التعرف الصوتي غير مدعوم في هذا المتصفح. يمكنك الكتابة بدلاً منه.");
            stopVoiceConversation();
            return;
        }

        if(listening || recognition) return;

        try{
            const activeRecognition=new SpeechRecognition();
            recognition=activeRecognition;
            activeRecognition.lang="ar-SA";
            activeRecognition.continuous=false;
            activeRecognition.interimResults=false;
            activeRecognition.maxAlternatives=1;

            activeRecognition.onstart=()=>{
                if(recognition!==activeRecognition) return;
                listening=true;
                if(mic){
                    mic.classList.add("is-listening");
                    mic.setAttribute("aria-label","إيقاف المحادثة الصوتية");
                    mic.title="إيقاف المحادثة الصوتية";
                }
                setVoiceStatus("ضِرغام يستمع إليك الآن...");
            };

            activeRecognition.onresult=event=>{
                if(recognition!==activeRecognition) return;

                const result=event.results && event.results[0];
                const transcript=result && result[0] ? result[0].transcript.trim() : "";

                voiceBusy=true;
                stopListening();

                if(transcript){
                    submitMessage(transcript,true);
                }else{
                    voiceBusy=false;
                    setVoiceStatus("لم أسمع كلاماً واضحاً. سأستمع مجدداً...");
                    scheduleVoiceRestart();
                }
            };

            activeRecognition.onerror=event=>{
                if(recognition!==activeRecognition) return;

                listening=false;
                if(mic) mic.classList.remove("is-listening");

                const errors={
                    "not-allowed":"يرجى السماح للمتصفح باستخدام الميكروفون.",
                    "service-not-allowed":"خدمة التعرف الصوتي غير متاحة.",
                    "no-speech":"لم أسمع صوتاً. سأحاول الاستماع مجدداً.",
                    "audio-capture":"لم يتم العثور على ميكروفون يعمل.",
                    "network":"تعذر الاتصال بخدمة التعرف الصوتي."
                };

                setVoiceStatus(errors[event.error] || "تعذر الاستماع. سأحاول مجدداً.");

                if(["not-allowed","service-not-allowed","audio-capture"].includes(event.error)){
                    voiceConversation=false;
                    voiceReplies=false;
                    clearVoiceRestart();
                }
            };

            activeRecognition.onend=()=>{
                if(recognition===activeRecognition) recognition=null;

                listening=false;
                if(mic) mic.classList.remove("is-listening");

                if(voiceConversation && !voiceBusy && !speaking){
                    scheduleVoiceRestart();
                }
            };

            activeRecognition.start();

        }catch(error){
            if(recognition) recognition=null;
            listening=false;
            if(mic) mic.classList.remove("is-listening");
            setVoiceStatus("تعذر تشغيل الميكروفون. حاول مرة أخرى.");
            scheduleVoiceRestart();
        }
    }

    function startListening(){
        if(voiceConversation){
            if(speaking || currentAudio || ttsController){
                clearVoiceRestart();
                stopSpeaking();
                voiceBusy=false;
                setVoiceStatus("تمت مقاطعة ضِرغام. استمع إليك الآن...");
                startRecognitionCycle();
            }else{
                stopVoiceConversation();
            }
            return;
        }

        voiceReplies=true;
        voiceConversation=true;
        voiceBusy=false;
        stopSpeaking();
        clearVoiceRestart();
        startRecognitionCycle();
    }

    function toggle(open){
        panel.hidden=!open;
        launcher.setAttribute("aria-expanded",String(open));

        if(open){
            syncDhirghamViewport();
        }else{
            root.classList.remove("keyboard-open");
            stopVoiceConversation();
            setVoiceStatus("");
        }
    }

    async function submitMessage(value,fromVoice){
        const message=String(value || "").trim();
        if(!message || send.disabled){
            if(fromVoice){
                voiceBusy=false;
                scheduleVoiceRestart();
            }
            return;
        }

        if(containsSensitiveData(message)){
            addMessage("حرصاً على خصوصيتك، لا ترسل كلمات المرور أو رموز التحقق أو أرقام الهواتف أو البريد الإلكتروني أو البيانات البنكية. اسألني عن الخطوات فقط.","assistant");
            if(fromVoice){
                voiceBusy=false;
                scheduleVoiceRestart();
            }
            return;
        }

        addMessage(message,"user");
        input.value="";
        send.disabled=true;
        if(fromVoice || voiceConversation){
            voiceBusy=true;
            stopListening();
        }

        const waiting=addMessage("ضِرغام يجهّز إجابته...","assistant");

        try{
            const response=await fetch("/api/dhirgham/chat",{
                method:"POST",
                credentials:"same-origin",
                headers:{"Content-Type":"application/json","X-CSRFToken":csrf},
                body:JSON.stringify({
                    message:message,
                    page_context:root.dataset.pageContext || "general",
                    conversation_history:history.slice(-8).map(item=>({
                        type:item.type,
                        text:String(item.text).slice(0,500),
                        signature:item.type==="assistant" ? String(item.signature || "") : ""
                    }))
                })
            });

            const data=await response.json();
            waiting.remove();

            if(!response.ok || !data.ok){
                addMessage(data.error || "تعذر إرسال الرسالة الآن. حاول مرة أخرى.","assistant error");
                if(voiceConversation){
                    voiceBusy=false;
                    scheduleVoiceRestart();
                }
            }else{
                const answer=String(data.answer || "لم أتمكن من إعداد إجابة الآن.");
                addMessage(answer,"assistant",{animate:true});

                if(!containsSensitiveData(message) && !containsSensitiveData(answer)){
                    history.push({type:"user",text:message});
                    history.push({
                        type:"assistant",
                        text:answer,
                        signature:String(data.history_signature || "")
                    });
                    history=history.slice(-MAX_HISTORY);
                    persistHistory();
                }

                if(fromVoice || voiceReplies){
                    if(voiceConversation) voiceBusy=true;
                    speakAnswer(answer);
                }
            }
        }catch(error){
            waiting.remove();
            addMessage("تعذر الاتصال حالياً. تحقق من اتصالك وحاول مرة أخرى.","assistant error");
            if(voiceConversation){
                voiceBusy=false;
                scheduleVoiceRestart();
            }
        }finally{
            send.disabled=false;
            if(mic) mic.disabled=false;
            // Keep the current keyboard state; avoid forcing page scroll.
        }
    }

    restoreHistory();

    document.addEventListener("submit",event=>{
        const formElement=event.target;
        if(formElement instanceof HTMLFormElement &&
           ["/customer/logout","/merchant/logout"].includes(formElement.getAttribute("action"))){
            try{sessionStorage.removeItem(storageKey);}catch(error){}
            stopVoiceConversation();
        }
    },true);

    launcher.addEventListener("click",()=>toggle(panel.hidden));
    close.addEventListener("click",()=>toggle(false));

    form.addEventListener("submit",event=>{
        event.preventDefault();
        submitMessage(input.value,false);
    });

    if(mic){
        mic.addEventListener("click",startListening);
    }

    suggestions.addEventListener("click",event=>{
        const button=event.target.closest("button[data-message]");
        if(button) submitMessage(button.dataset.message,false);
    });

    document.addEventListener("keydown",event=>{
        if(event.key==="Escape" && !panel.hidden) toggle(false);
    });

    window.addEventListener("pagehide",()=>{
        stopVoiceConversation();
    });
})();
