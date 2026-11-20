(function () {
    "use strict";

    const templates = [
        ["عطور ملكية","العطور والجمال","#281B17","#D6B477"],
        ["جمال ناعم","العطور والجمال","#F4E6DF","#A96F69"],
        ["لمسة فاخرة","العطور والجمال","#34232D","#D7B18C"],
        ["أناقة الأزياء","الأزياء","#23352F","#D5B98A"],
        ["موضة عصرية","الأزياء","#E9DED2","#654A42"],
        ["إطلالة راقية","الأزياء","#30303A","#D9C6A1"],
        ["تقنية المستقبل","الإلكترونيات","#142B3A","#57C7D4"],
        ["عالم الأجهزة","الإلكترونيات","#202A45","#A9C7F0"],
        ["تقنية ذكية","الإلكترونيات","#E6EDF2","#326A86"],
        ["مذاق فاخر","المطاعم","#4A261D","#E9B86D"],
        ["شهية طيبة","المطاعم","#F5E7D0","#A65B35"],
        ["نكهة طبيعية","الأغذية","#294331","#D5BD79"],
        ["منزلك أجمل","المنزل","#E9E1D5","#92745B"],
        ["تفاصيل منزلية","المنزل","#34413D","#C9B69A"],
        ["حياة رياضية","الرياضة","#192D43","#E8A94C"],
        ["طاقة وحركة","الرياضة","#3D2927","#F0A36A"],
        ["عروض مميزة","العروض","#742F31","#F3C76B"],
        ["افتتاح جديد","الأعمال","#27384A","#D6B477"],
        ["اختيارك الأفضل","متنوع","#372A25","#CDAA75"],
        ["بصمة MODR","متنوع","#29252D","#D6B477"]
    ];

    let canvas = null;
    let selectedTemplate = 0;
    let ready = false;

    const $ = id => document.getElementById(id);

    function addText(text, options) {
        const obj = new fabric.Textbox(text, Object.assign({
            left: 90, top: 190, width: 520,
            fontFamily: "Cairo, Tahoma, Arial",
            fontSize: 55, fontWeight: "bold",
            fill: "#FFFFFF", textAlign: "right",
            direction: "rtl", editable: true,
            splitByGrapheme: true
        }, options || {}));
        canvas.add(obj);
        return obj;
    }

    function addRect(left, top, width, height, fill, radius) {
        const obj = new fabric.Rect({
            left, top, width, height,
            fill, rx: radius || 0, ry: radius || 0,
            selectable: true
        });
        canvas.add(obj);
        return obj;
    }

    function drawTemplate(index) {
        const t = templates[index];
        if (!canvas || !t) return;

        selectedTemplate = index;
        canvas.clear();
        canvas.backgroundColor = t[2];

        const dark = ["#281B17","#23352F","#34232D","#142B3A",
                      "#202A45","#4A261D","#294331","#34413D",
                      "#192D43","#3D2927","#742F31","#27384A",
                      "#372A25","#29252D"].includes(t[2]);

        addRect(0, 0, 24, 628, t[3]);
        canvas.add(new fabric.Circle({
            left: 820, top: -160, radius: 245,
            fill: t[3], opacity: 0.13,
            selectable: true
        }));
        canvas.add(new fabric.Circle({
            left: 900, top: 390, radius: 130,
            fill: t[3], opacity: 0.20,
            selectable: true
        }));

        addText("اسم علامتك التجارية", {
            left: 80, top: 75, width: 570,
            fontSize: 25, fill: t[3], fontWeight: "bold"
        });

        addText(t[0], {
            left: 80, top: 190, width: 650,
            fontSize: 64, fill: dark ? "#FFFFFF" : "#35251F",
            fontWeight: "bold"
        });

        addText("اكتشف مجموعتنا المميزة", {
            left: 85, top: 285, width: 570,
            fontSize: 30,
            fill: dark ? "#F1E8DC" : "#59463D",
            fontWeight: "normal"
        });

        const badge = addRect(85, 390, 260, 66, t[3], 12);
        addText("تسوّق الآن", {
            left: 100, top: 402, width: 230,
            fontSize: 27, fill: dark ? "#281B17" : "#FFFFFF",
            textAlign: "center"
        });

        addText("MODR ADS  •  إعلانك يبدأ هنا", {
            left: 80, top: 545, width: 650,
            fontSize: 19, fill: t[3], fontWeight: "normal"
        });

        canvas.renderAll();
        refreshLayers();
        selectObject(null);
        if ($("modr-editor-template-name")) {
            $("modr-editor-template-name").textContent = t[0];
        }
    }

    function selectObject(obj) {
        const disabled = !obj;
        ["modr-editor-text","modr-editor-size","modr-editor-color",
         "modr-editor-font","modr-editor-align","modr-editor-direction"]
            .forEach(id => { if ($(id)) $(id).disabled = disabled; });

        if (!obj) return;

        if ($("modr-editor-text")) {
            $("modr-editor-text").value = obj.text || "";
        }
        if ($("modr-editor-size") && obj.fontSize) {
            $("modr-editor-size").value = obj.fontSize;
        }
        if ($("modr-editor-color") && typeof obj.fill === "string" &&
            /^#[0-9a-f]{6}$/i.test(obj.fill)) {
            $("modr-editor-color").value = obj.fill;
        }
        if ($("modr-editor-font") && obj.fontFamily) {
            $("modr-editor-font").value = obj.fontFamily;
        }
        if ($("modr-editor-align") && obj.textAlign) {
            $("modr-editor-align").value = obj.textAlign;
        }
        if ($("modr-editor-direction") && obj.direction) {
            $("modr-editor-direction").value = obj.direction;
        }
    }

    function refreshLayers() {
        const list = $("modr-editor-layers");
        if (!list || !canvas) return;

        list.innerHTML = "";
        canvas.getObjects().slice().reverse().forEach((obj, reverseIndex) => {
            const index = canvas.getObjects().length - 1 - reverseIndex;
            const item = document.createElement("button");
            item.type = "button";
            item.className = "modr-layer-item";
            item.textContent = (obj.text || (obj.type === "image" ? "صورة" :
                obj.type === "rect" ? "شكل" : "عنصر")).toString().slice(0, 35);
            item.addEventListener("click", () => {
                canvas.setActiveObject(obj);
                canvas.renderAll();
                selectObject(obj);
                refreshLayers();
            });
            if (canvas.getActiveObject() === obj) {
                item.classList.add("active");
            }
            list.appendChild(item);
        });
    }

    function addNewText() {
        const obj = addText("اكتب نصك هنا", {
            left: 280, top: 260, width: 500,
            fontSize: 42, fill: "#FFFFFF"
        });
        canvas.setActiveObject(obj);
        canvas.renderAll();
        selectObject(obj);
        refreshLayers();
    }

    function bind(id, event, callback) {
        const el = $(id);
        if (el) el.addEventListener(event, callback);
    }

    function init() {
        const element = $("modr-ads-canvas");
        if (!element || typeof fabric === "undefined") return;

        canvas = new fabric.Canvas(element, {
            preserveObjectStacking: true,
            selection: true,
            allowTouchScrolling: false
        });
        canvas.setDimensions({width: 1200, height: 628});
        canvas.on("selection:created", e => selectObject(e.selected[0]));
        canvas.on("selection:updated", e => selectObject(e.selected[0]));
        canvas.on("selection:cleared", () => selectObject(null));
        canvas.on("object:modified", refreshLayers);
        canvas.on("object:added", refreshLayers);
        canvas.on("object:removed", refreshLayers);

        const gallery = $("modr-editor-templates");
        if (gallery) {
            templates.forEach((t, i) => {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "modr-template-choice";
                button.innerHTML =
                    '<span class="modr-template-swatch" style="background:' +
                    t[2] + ';border-color:' + t[3] + '"></span>' +
                    '<span>' + t[0] + '</span>' +
                    '<small>' + t[1] + '</small>';
                button.addEventListener("click", () => drawTemplate(i));
                gallery.appendChild(button);
            });
        }

        bind("modr-editor-add-text", "click", addNewText);

        bind("modr-editor-text", "input", e => {
            const obj = canvas.getActiveObject();
            if (obj && obj.set && obj.text !== undefined) {
                obj.set("text", e.target.value);
                canvas.requestRenderAll();
                refreshLayers();
            }
        });

        bind("modr-editor-size", "change", e => {
            const obj = canvas.getActiveObject();
            if (obj && obj.set) {
                obj.set("fontSize", Math.max(8, Math.min(180, Number(e.target.value) || 32)));
                canvas.requestRenderAll();
            }
        });

        bind("modr-editor-color", "input", e => {
            const obj = canvas.getActiveObject();
            if (obj && obj.set) {
                obj.set("fill", e.target.value);
                canvas.requestRenderAll();
            }
        });

        bind("modr-editor-font", "change", e => {
            const obj = canvas.getActiveObject();
            if (obj && obj.set) {
                obj.set("fontFamily", e.target.value);
                canvas.requestRenderAll();
            }
        });

        bind("modr-editor-align", "change", e => {
            const obj = canvas.getActiveObject();
            if (obj && obj.set) {
                obj.set("textAlign", e.target.value);
                canvas.requestRenderAll();
            }
        });

        bind("modr-editor-direction", "change", e => {
            const obj = canvas.getActiveObject();
            if (obj && obj.set) {
                obj.set("direction", e.target.value);
                canvas.requestRenderAll();
            }
        });

        bind("modr-editor-delete", "click", () => {
            const obj = canvas.getActiveObject();
            if (obj) {
                canvas.remove(obj);
                canvas.discardActiveObject();
                canvas.requestRenderAll();
                selectObject(null);
                refreshLayers();
            }
        });

        bind("modr-editor-front", "click", () => {
            const obj = canvas.getActiveObject();
            if (obj) {
                canvas.bringToFront(obj);
                canvas.requestRenderAll();
                refreshLayers();
            }
        });

        bind("modr-editor-back", "click", () => {
            const obj = canvas.getActiveObject();
            if (obj) {
                canvas.sendBackwards(obj);
                canvas.requestRenderAll();
                refreshLayers();
            }
        });

        bind("modr-editor-image", "change", e => {
            const file = e.target.files && e.target.files[0];
            if (!file || !/^image\/(png|jpeg|webp)$/.test(file.type)) {
                alert("اختر صورة PNG أو JPG أو WEBP.");
                return;
            }
            const reader = new FileReader();
            reader.onload = () => {
                fabric.Image.fromURL(reader.result, img => {
                    const maxW = 430, maxH = 430;
                    const scale = Math.min(maxW / img.width, maxH / img.height, 1);
                    img.set({
                        left: 720, top: 100,
                        scaleX: scale, scaleY: scale,
                        cornerStyle: "circle",
                        transparentCorners: false
                    });
                    canvas.add(img);
                    canvas.setActiveObject(img);
                    canvas.requestRenderAll();
                    selectObject(img);
                    refreshLayers();
                });
            };
            reader.readAsDataURL(file);
        });

        bind("modr-editor-export", "click", () => {
            const input = $("image");
            if (!input) {
                alert("لم يتم العثور على حقل صورة الإعلان.");
                return;
            }
            canvas.discardActiveObject();
            canvas.renderAll();
            const dataURL = canvas.toDataURL({
                format: "png",
                multiplier: 1
            });

            const binary = atob(dataURL.split(",")[1]);
            const bytes = new Uint8Array(binary.length);

            for (let i = 0; i < binary.length; i++) {
                bytes[i] = binary.charCodeAt(i);
            }

            const blob = new Blob([bytes], {type: "image/png"});
            const file = new File([blob], "modr-ad-design.png", {
                type: "image/png"
            });

            try {
                const transfer = new DataTransfer();
                transfer.items.add(file);
                input.files = transfer.files;
                input.dispatchEvent(new Event("change", {bubbles:true}));

                const status = $("modr-editor-export-status");
                if (status) status.textContent =
                    "تم تجهيز التصميم وإرفاقه بنموذج الإعلان.";

                input.scrollIntoView({behavior:"smooth", block:"center"});
            } catch (err) {
                alert("المتصفح لا يدعم إرفاق الصورة تلقائياً. جرّب متصفحاً حديثاً.");
            }
        });

        drawTemplate(0);
        ready = true;
    }

    window.MODRAdsEditor = {
        open: function () {
            const panel = $("modr-ads-editor");
            if (panel) {
                panel.hidden = false;
                if (!ready) init();
                panel.scrollIntoView({behavior:"smooth", block:"start"});
            }
        }
    };

    document.addEventListener("DOMContentLoaded", function () {
        const type = $("creative_type");
        const open = $("modr-editor-open");
        if (open) open.addEventListener("click", () => window.MODRAdsEditor.open());
        if (type) {
            type.addEventListener("change", () => {
                if (type.value === "template") window.MODRAdsEditor.open();
            });

            if (type.value === "template") {
                window.MODRAdsEditor.open();
            }
        }
    });
})();
