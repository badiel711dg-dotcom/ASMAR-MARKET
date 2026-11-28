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
        const height=dhirghamViewport ? dhirghamViewport.height : window.innerHeight;
        const top=dhirghamViewport ? (dhirghamViewport.offsetTop || 0) : 0;
        const keyboardOpen=document.activeElement===input && (window.innerHeight-height)>80;

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
        window.setTimeout(syncDhirghamViewport,180);
    });
    input.addEventListener("focus",()=>{
        window.setTimeout(syncDhirghamViewport,100);
        window.setTimeout(syncDhirghamViewport,350);
    });
    input.addEventListener("blur",()=>{
        window.setTimeout(syncDhirghamViewport,120);
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
            avatar.loading="eager";

            const content=document.createElement("span");
            content.className="dhirgham-message-text";
            const fullText=String(text);
            const animate=options.animate===true;
            content.textContent=animate ? "" : fullText;

            item.append(avatar,content);

            const productList=Array.isArray(options.products)
                ? options.products.slice(0,8) : [];

            if(productList.length){
                const grid=document.createElement("div");
                grid.className="dhirgham-product-cards";

                productList.forEach(product=>{
                    const productUrl=String(product?.url || "");
                    if(!product || !productUrl.startsWith("/product/") || !/^[0-9]+$/.test(productUrl.slice(9))) return;

                    const card=document.createElement("a");
                    card.className="dhirgham-product-card";
                    card.href=String(product.url);
                    card.setAttribute("aria-label","عرض "+String(product.name || "المنتج"));

                    const imageUrl=String(product.image_url || "");
                    if(imageUrl.startsWith("/static/uploads/") && !imageUrl.includes("..")){
                        const image=document.createElement("img");
                        image.className="dhirgham-product-image";
                        image.src=imageUrl;
                        image.alt=String(product.name || "صورة المنتج");
                        image.loading="lazy";
                        image.onerror=()=>image.remove();
                        card.appendChild(image);
                    }

                    const details=document.createElement("div");
                    details.className="dhirgham-product-details";

                    const name=document.createElement("div");
                    name.className="dhirgham-product-name";
                    name.textContent=String(product.name || "منتج");
                    details.appendChild(name);

                    const price=document.createElement("div");
                    price.className="dhirgham-product-price";
                    price.textContent=String(product.current_price ?? "")+" "+String(product.currency || "");
                    details.appendChild(price);

                    if(product.is_offer){
                        const offer=document.createElement("span");
                        offer.className="dhirgham-product-offer";
                        offer.textContent="سعر عرض";
                        details.appendChild(offer);
                    }

                    const status=document.createElement("div");
                    status.className=product.available
                        ? "dhirgham-product-available"
                        : "dhirgham-product-unavailable";
                    status.textContent=product.available
                        ? "متوفر" : "غير متوفر حالياً";
                    details.appendChild(status);

                    if(product.merchant){
                        const merchant=document.createElement("div");
                        merchant.className="dhirgham-product-merchant";
                        merchant.textContent=String(product.merchant);
                        details.appendChild(merchant);
                    }

                    card.appendChild(details);
                    grid.appendChild(card);
                });

                if(grid.childElementCount) item.appendChild(grid);
            }

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
                let serverMessage="";
                try{
                    const errorData=await response.json();
                    serverMessage=String(errorData.error || "");
                }catch(error){}
                const audioError=new Error("TTS_HTTP_"+response.status);
                audioError.httpStatus=response.status;
                audioError.serverMessage=serverMessage;
                throw audioError;
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

            const blocked=error.name==="NotAllowedError";
            const serverMessage=String(error.serverMessage || "");
            let statusMessage="تعذر توليد صوت ضِرغام حالياً. يمكنك قراءة الرد.";

            if(blocked){
                statusMessage="المتصفح منع تشغيل الصوت تلقائياً. تحقق من إعدادات الصوت في المتصفح.";
            }else if(serverMessage){
                statusMessage=serverMessage;
            }else if(error.httpStatus===429){
                statusMessage="خدمة الصوت مشغولة حالياً. انتظر قليلاً ثم حاول مجدداً.";
            }else if(error.httpStatus===503){
                statusMessage="خدمة صوت ضِرغام غير مكتملة الإعداد حالياً.";
            }else if(error.httpStatus===502 || error.httpStatus===504){
                statusMessage="تعذر وصول الصوت من مزوّد الخدمة. يمكنك قراءة الرد.";
            }

            console.warn("DHIRGHAM TTS playback/generation error:",error.name || "Error",error.httpStatus || "");
            stopSpeaking();
            voiceBusy=false;
            setVoiceStatus(statusMessage);
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

            const responseText=await response.text();
            let data;
            try{
                data=JSON.parse(responseText);
            }catch(parseError){
                console.error("DHIRGHAM CHAT NON-JSON RESPONSE",{
                    status:response.status,
                    body:responseText.slice(0,300)
                });
                data={
                    ok:false,
                    error:response.status===400 && responseText.includes("CSRF")
                        ? "انتهت صلاحية الجلسة. حدّث الصفحة ثم حاول مجدداً."
                        : `استجابة غير متوقعة من الخادم (HTTP ${response.status}).`
                };
            }
            waiting.remove();

            if(!response.ok || !data.ok){
                addMessage(data.error || "تعذر إرسال الرسالة الآن. حاول مرة أخرى.","assistant error");
                if(voiceConversation){
                    voiceBusy=false;
                    scheduleVoiceRestart();
                }
            }else{
                const answer=String(data.answer || "لم أتمكن من إعداد إجابة الآن.");
                addMessage(answer,"assistant",{
                    animate:true,
                    products:data.products
                });

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


    // Dhirgham account memory — explicit consent and manual management.
    const memoryTrigger=document.getElementById("dhirghamMemoryTrigger");
    const memoryPanel=document.getElementById("dhirghamMemoryPanel");
    const memoryBack=document.getElementById("dhirghamMemoryBack");
    const memoryConsent=document.getElementById("dhirghamMemoryConsent");
    const memoryInput=document.getElementById("dhirghamMemoryInput");
    const memorySave=document.getElementById("dhirghamMemorySave");
    const memoryDeleteAll=document.getElementById("dhirghamMemoryDeleteAll");
    const memoryList=document.getElementById("dhirghamMemoryList");
    const memoryStatus=document.getElementById("dhirghamMemoryStatus");
    let memoryBusy=false;
    let memoryConsentEnabled=false;

    function memoryMessage(text,isError){
        if(!memoryStatus) return;
        memoryStatus.textContent=text || "";
        memoryStatus.classList.toggle("is-error",!!isError);
    }

    async function memoryRequest(url,method="GET",payload){
        const options={
            method,
            credentials:"same-origin",
            headers:{}
        };

        if(payload !== undefined){
            options.headers["Content-Type"]="application/json";
            options.headers["X-CSRFToken"]=csrf;
            options.body=JSON.stringify(payload);
        }

        const response=await fetch(url,options);
        let data={};
        try{
            data=await response.json();
        }catch(error){
            throw new Error("تعذرت قراءة استجابة الخادم.");
        }

        if(!response.ok || !data.ok){
            throw new Error(data.error || "تعذر تنفيذ العملية.");
        }
        return data;
    }

    function renderMemoryList(items){
        if(!memoryList) return;
        memoryList.replaceChildren();

        if(!Array.isArray(items) || !items.length){
            const empty=document.createElement("p");
            empty.className="dhirgham-memory-empty";
            empty.textContent="لا توجد معلومات محفوظة حتى الآن.";
            memoryList.appendChild(empty);
            return;
        }

        items.forEach(item=>{
            if(!item || typeof item.id!=="string" || typeof item.text!=="string") return;

            const row=document.createElement("article");
            row.className="dhirgham-memory-item";

            const content=document.createElement("p");
            content.textContent=item.text;

            const remove=document.createElement("button");
            remove.type="button";
            remove.className="dhirgham-memory-remove";
            remove.textContent="حذف";
            remove.setAttribute("aria-label","حذف هذه المعلومة");
            remove.addEventListener("click",async()=>{
                if(memoryBusy) return;
                memoryBusy=true;
                remove.disabled=true;
                memoryMessage("جارٍ حذف المعلومة...");
                try{
                    const result=await memoryRequest(
                        "/api/dhirgham/memory/remove",
                        "POST",
                        {id:item.id}
                    );
                    renderMemoryList(result.memories);
                    memoryMessage("تم حذف المعلومة.");
                }catch(error){
                    remove.disabled=false;
                    memoryMessage(error.message,true);
                }finally{
                    memoryBusy=false;
                }
            });

            row.append(content,remove);
            memoryList.appendChild(row);
        });
    }

    async function dhirghamMemoryLoad(){
        if(!memoryPanel || memoryBusy) return;
        memoryBusy=true;
        memoryMessage("جارٍ تحميل الذاكرة...");
        try{
            const data=await memoryRequest("/api/dhirgham/memory");
            memoryConsentEnabled=!!data.consent_enabled;
            if(memoryConsent) memoryConsent.checked=memoryConsentEnabled;
            renderMemoryList(data.memories);
            memoryMessage(
                data.consent_enabled
                    ? "الذاكرة مفعّلة. تُستخدم المعلومات التي أضفتها يدوياً."
                    : "الذاكرة متوقفة. المعلومات القديمة محفوظة ولن تُستخدم حتى تعيد التفعيل."
            );
        }catch(error){
            memoryMessage(error.message,true);
        }finally{
            memoryBusy=false;
        }
    }

    function dhirghamMemoryOpen(){
        if(!memoryPanel || !memoryTrigger) return;
        memoryPanel.hidden=false;
        dhirghamMemoryLoad();
    }

    function dhirghamMemoryClose(){
        if(memoryPanel) memoryPanel.hidden=true;
        memoryMessage("");
    }

    if(memoryTrigger && memoryPanel){
        memoryTrigger.addEventListener("click",dhirghamMemoryOpen);
    }
    if(memoryBack){
        memoryBack.addEventListener("click",dhirghamMemoryClose);
    }

    if(memoryConsent){
        memoryConsent.addEventListener("change",async()=>{
            if(memoryBusy){
                memoryConsent.checked=memoryConsentEnabled;
                return;
            }
            const requested=memoryConsent.checked;
            memoryConsent.disabled=true;
            memoryBusy=true;
            memoryMessage("جارٍ تحديث إعداد الذاكرة...");
            try{
                const data=await memoryRequest(
                    "/api/dhirgham/memory/consent",
                    "POST",
                    {enabled:requested}
                );
                memoryConsentEnabled=!!data.consent_enabled;
                memoryConsent.checked=memoryConsentEnabled;
                memoryMessage(data.message || "تم تحديث إعداد الذاكرة.");
            }catch(error){
                memoryConsent.checked=memoryConsentEnabled;
                memoryMessage(error.message,true);
            }finally{
                memoryConsent.disabled=false;
                memoryBusy=false;
            }
        });
    }

    if(memorySave && memoryInput){
        memorySave.addEventListener("click",async()=>{
            const value=memoryInput.value.trim();
            if(!value){
                memoryMessage("اكتب المعلومة التي تريد حفظها أولاً.",true);
                memoryInput.focus();
                return;
            }
            if(memoryBusy) return;
            memoryBusy=true;
            memorySave.disabled=true;
            memoryMessage("جارٍ حفظ المعلومة...");
            try{
                const data=await memoryRequest(
                    "/api/dhirgham/memory/add",
                    "POST",
                    {text:value}
                );
                memoryInput.value="";
                renderMemoryList(data.memories);
                memoryMessage(data.message || "تم حفظ المعلومة.");
            }catch(error){
                memoryMessage(error.message,true);
            }finally{
                memorySave.disabled=false;
                memoryBusy=false;
            }
        });
    }

    if(memoryDeleteAll){
        memoryDeleteAll.addEventListener("click",async()=>{
            if(memoryBusy) return;
            if(!window.confirm("هل تريد مسح جميع المعلومات المحفوظة وإيقاف ذاكرة ضِرغام؟ لا يمكن التراجع عن هذه العملية.")) return;

            memoryBusy=true;
            memoryDeleteAll.disabled=true;
            memoryMessage("جارٍ مسح الذاكرة...");
            try{
                const data=await memoryRequest(
                    "/api/dhirgham/memory/delete",
                    "POST",
                    {}
                );
                memoryConsentEnabled=false;
                if(memoryConsent) memoryConsent.checked=false;
                renderMemoryList(data.memories);
                memoryMessage(data.message || "تم مسح الذاكرة وإيقافها.");
            }catch(error){
                memoryMessage(error.message,true);
            }finally{
                memoryDeleteAll.disabled=false;
                memoryBusy=false;
            }
        });
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
        if(event.key!=="Escape" || panel.hidden) return;
        if(memoryPanel && !memoryPanel.hidden){
            dhirghamMemoryClose();
            return;
        }
        toggle(false);
    });

    window.addEventListener("pagehide",()=>{
        stopVoiceConversation();
    });
})();
