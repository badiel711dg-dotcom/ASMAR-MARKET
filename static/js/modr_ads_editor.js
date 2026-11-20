(function () {
    "use strict";

    const $ = id => document.getElementById(id);
    const W = 1200;
    const H = 628;

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
    let ready = false;
    let resizeObserver = null;
    let history = [];
    let historyIndex = -1;
    let historyPaused = false;

    function bind(id, event, callback) {
        const el = $(id);
        if (el) el.addEventListener(event, callback);
    }

    function status(message) {
        const el = $("modr-editor-export-status");
        if (el) el.textContent = message;
    }

    function switchTab(name) {
        document.querySelectorAll("[data-studio-tab]").forEach(button => {
            button.classList.toggle(
                "active",
                button.dataset.studioTab === name
            );
        });

        document.querySelectorAll("[data-studio-panel]").forEach(panel => {
            panel.classList.toggle(
                "active",
                panel.dataset.studioPanel === name
            );
        });
    }

    function resizeCanvas() {
        if (!canvas) return;

        const wrap = document.querySelector(".modr-editor-canvas-wrap");
        if (!wrap) return;

        const width = Math.max(1, Math.floor(wrap.clientWidth));
        const scale = width / W;
        const height = Math.max(1, Math.round(H * scale));

        canvas.setDimensions({ width, height });
        canvas.setViewportTransform([scale, 0, 0, scale, 0, 0]);
        canvas.requestRenderAll();
    }

    function refreshLayers() {
        if (!canvas) return;

        const list = $("modr-editor-layers");
        if (!list) return;

        list.replaceChildren();

        canvas.getObjects().slice().reverse().forEach(obj => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "modr-layer-item";

            const name = obj.text ||
                (obj.type === "image" ? "صورة" :
                obj.type === "textbox" ? "نص" :
                obj.type === "circle" ? "دائرة" : "عنصر");

            button.textContent = String(name).slice(0, 35);

            if (canvas.getActiveObject() === obj) {
                button.classList.add("active");
            }

            button.addEventListener("click", () => {
                canvas.setActiveObject(obj);
                canvas.requestRenderAll();
                selectObject(obj);
                refreshLayers();
            });

            list.appendChild(button);
        });
    }

    function selectObject(obj) {
        const ids = [
            "modr-editor-text",
            "modr-editor-size",
            "modr-editor-color",
            "modr-editor-font",
            "modr-editor-align",
            "modr-editor-direction",
            "modr-editor-opacity",
            "modr-editor-rotation"
        ];

        ids.forEach(id => {
            if ($(id)) $(id).disabled = !obj;
        });

        if (!obj) {
            refreshLayers();
            return;
        }

        if ($("modr-editor-text")) {
            $("modr-editor-text").value = obj.text || "";
        }

        if ($("modr-editor-size")) {
            $("modr-editor-size").value = obj.fontSize || 32;
        }

        if ($("modr-editor-color") && typeof obj.fill === "string") {
            if (/^#[0-9a-f]{6}$/i.test(obj.fill)) {
                $("modr-editor-color").value = obj.fill;
            }
        }

        if ($("modr-editor-font")) {
            $("modr-editor-font").value = obj.fontFamily || "Cairo";
        }

        if ($("modr-editor-align")) {
            $("modr-editor-align").value = obj.textAlign || "right";
        }

        if ($("modr-editor-direction")) {
            $("modr-editor-direction").value = obj.direction || "rtl";
        }

        if ($("modr-editor-opacity")) {
            $("modr-editor-opacity").value =
                Math.round((obj.opacity ?? 1) * 100);
        }

        if ($("modr-editor-rotation")) {
            $("modr-editor-rotation").value = Math.round(obj.angle || 0);
        }

        refreshLayers();
    }

    function saveHistory() {
        if (!canvas || historyPaused) return;

        const snapshot = JSON.stringify(
            canvas.toJSON(["name", "locked"])
        );

        if (history[historyIndex] === snapshot) return;

        history = history.slice(0, historyIndex + 1);
        history.push(snapshot);

        if (history.length > 40) history.shift();

        historyIndex = history.length - 1;
    }

    function restoreHistory(index) {
        if (index < 0 || index >= history.length) return;

        historyPaused = true;

        canvas.loadFromJSON(history[index], function () {
            canvas.renderAll();
            historyPaused = false;
            refreshLayers();
            selectObject(canvas.getActiveObject());
        });
    }

    function undo() {
        if (historyIndex > 0) {
            historyIndex--;
            restoreHistory(historyIndex);
        }
    }

    function redo() {
        if (historyIndex < history.length - 1) {
            historyIndex++;
            restoreHistory(historyIndex);
        }
    }


    function makeGradient(top, bottom) {
        return new fabric.Gradient({
            type: "linear",
            gradientUnits: "pixels",
            coords: { x1: 0, y1: 0, x2: W, y2: H },
            colorStops: [
                { offset: 0, color: top },
                { offset: 1, color: bottom }
            ]
        });
    }

    function setBackground(color) {
        if (!canvas) return;
        canvas.backgroundColor = color;
        canvas.requestRenderAll();
        saveHistory();
    }

    function setGradient(name) {
        const gradients = {
            dark: ["#49352D", "#171313"],
            gold: ["#E8D1A0", "#8C6337"],
            light: ["#FFFFFF", "#E9DED2"],
            sunset: ["#9B5146", "#E8B77C"]
        };

        const colors = gradients[name];
        if (!colors) return;

        setBackground(makeGradient(colors[0], colors[1]));
    }


    function addText(text, options = {}) {
        if (!canvas) return;

        const obj = new fabric.Textbox(text || "اكتب نصك هنا", {
            left: options.left ?? 600,
            top: options.top ?? 250,
            width: options.width ?? 520,
            fontSize: options.fontSize ?? 48,
            fontFamily: options.fontFamily ?? "Cairo",
            fill: options.fill ?? "#FFFFFF",
            textAlign: options.textAlign ?? "right",
            direction: "rtl",
            originX: "center",
            originY: "center",
            editable: true,
            cornerColor: "#C5A059",
            borderColor: "#C5A059",
            transparentCorners: false
        });

        canvas.add(obj);
        canvas.setActiveObject(obj);
        canvas.requestRenderAll();
        selectObject(obj);
        refreshLayers();
        saveHistory();
        return obj;
    }


    function addShape(type) {
        if (!canvas) return;

        const common = {
            left: 600,
            top: 314,
            fill: "rgba(197,160,89,0.22)",
            stroke: "#C5A059",
            strokeWidth: 3,
            originX: "center",
            originY: "center",
            cornerColor: "#C5A059",
            transparentCorners: false
        };

        let obj;

        if (type === "circle") {
            obj = new fabric.Circle({
                ...common,
                radius: 95
            });
        } else if (type === "line") {
            obj = new fabric.Line(
                [350, 314, 850, 314],
                { ...common, fill: null, strokeWidth: 5 }
            );
        } else if (type === "roundRect") {
            obj = new fabric.Rect({
                ...common,
                width: 420,
                height: 220,
                rx: 28,
                ry: 28
            });
        } else {
            obj = new fabric.Rect({
                ...common,
                width: 420,
                height: 220
            });
        }

        canvas.add(obj);
        canvas.setActiveObject(obj);
        canvas.requestRenderAll();
        refreshLayers();
        saveHistory();
        return obj;
    }


    function activeObject() {
        return canvas ? canvas.getActiveObject() : null;
    }

    function deleteSelected() {
        const obj = activeObject();
        if (!obj) return;
        canvas.remove(obj);
        canvas.discardActiveObject();
        canvas.requestRenderAll();
        selectObject(null);
        refreshLayers();
        saveHistory();
    }

    function duplicateSelected() {
        const obj = activeObject();
        if (!obj) return;

        obj.clone(function (copy) {
            copy.set({
                left: (obj.left || 0) + 35,
                top: (obj.top || 0) + 35
            });
            canvas.add(copy);
            canvas.setActiveObject(copy);
            canvas.requestRenderAll();
            selectObject(copy);
            refreshLayers();
            saveHistory();
        }, ["name", "locked"]);
    }

    function moveLayer(direction) {
        const obj = activeObject();
        if (!obj) return;

        if (direction === "front") canvas.bringToFront(obj);
        else canvas.sendToBack(obj);

        canvas.requestRenderAll();
        refreshLayers();
        saveHistory();
    }

    function toggleLock() {
        const obj = activeObject();
        if (!obj) return;

        obj.locked = !obj.locked;
        obj.set({
            lockMovementX: obj.locked,
            lockMovementY: obj.locked,
            lockScalingX: obj.locked,
            lockScalingY: obj.locked,
            lockRotation: obj.locked,
            hasControls: !obj.locked
        });

        canvas.requestRenderAll();
        refreshLayers();
        saveHistory();
    }


    function loadEditorImage(file, asBackground) {
        if (!canvas || !file || !file.type.startsWith("image/")) return;

        const reader = new FileReader();

        reader.onload = function (event) {
            fabric.Image.fromURL(event.target.result, function (img) {
                if (!img) return;

                if (asBackground) {
                    img.scaleToWidth(W);
                    if (img.getScaledHeight() < H) img.scaleToHeight(H);
                    img.set({
                        left: W / 2,
                        top: H / 2,
                        originX: "center",
                        originY: "center",
                        selectable: false,
                        evented: false
                    });
                    canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas));
                } else {
                    img.scaleToWidth(Math.min(500, W * 0.45));
                    img.set({
                        left: W / 2,
                        top: H / 2,
                        originX: "center",
                        originY: "center",
                        cornerColor: "#C5A059"
                    });
                    canvas.add(img);
                    canvas.setActiveObject(img);
                    selectObject(img);
                }

                canvas.requestRenderAll();
                refreshLayers();
                saveHistory();
                status("تم تحميل الصورة إلى التصميم.");
            });
        };

        reader.readAsDataURL(file);
    }


    bind("modr-editor-image", "change", function (event) {
        const file = event.target.files[0];
        loadEditorImage(file, false);
        event.target.value = "";
    });

    bind("modr-editor-bg-image", "change", function (event) {
        const file = event.target.files[0];
        loadEditorImage(file, true);
        event.target.value = "";
    });


    function cropSelected(mode) {
        const obj = activeObject();
        if (!obj || obj.type !== "image") {
            status("حدد صورة أولاً.");
            return;
        }

        obj.clipPath = null;

        if (mode === "square") {
            obj.clipPath = new fabric.Rect({
                width: obj.width * 0.8,
                height: obj.height * 0.8,
                originX: "center",
                originY: "center"
            });
        } else if (mode === "rounded") {
            obj.clipPath = new fabric.Rect({
                width: obj.width * 0.8,
                height: obj.height * 0.8,
                rx: 35,
                ry: 35,
                originX: "center",
                originY: "center"
            });
        } else if (mode === "circle") {
            obj.clipPath = new fabric.Circle({
                radius: Math.min(obj.width, obj.height) * 0.4,
                originX: "center",
                originY: "center"
            });
        }

        canvas.requestRenderAll();
        saveHistory();
    }

    bind("modr-editor-crop", "change", function (event) {
        cropSelected(event.target.value);
    });


    bind("modr-editor-add-shape", "click", function () {
        const selector = $("modr-editor-shape");
        const type = selector ? selector.value : "";

        if (!type) {
            status("اختر شكلاً أولاً.");
            return;
        }

        addShape(type);
        status("تمت إضافة الشكل إلى التصميم.");
        selector.value = "";
    });


    bind("modr-editor-add-text", "click", function () {
        const obj = addText("اكتب نصك هنا", {
            fontSize: 48,
            fill: "#FFFFFF",
            textAlign: "right"
        });

        if (obj) {
            status("تمت إضافة النص. اضغط عليه لتعديله.");
        }
    });


    function updateSelectedProperty(property, value) {
        const obj = activeObject();
        if (!obj) return;
        obj.set(property, value);
        canvas.requestRenderAll();
        saveHistory();
    }

    bind("modr-editor-text", "input", e =>
        updateSelectedProperty("text", e.target.value)
    );

    bind("modr-editor-size", "input", e =>
        updateSelectedProperty("fontSize", Math.max(8, Math.min(180, Number(e.target.value) || 8)))
    );

    bind("modr-editor-color", "input", e =>
        updateSelectedProperty("fill", e.target.value)
    );

    bind("modr-editor-font", "change", e =>
        updateSelectedProperty("fontFamily", e.target.value)
    );

    bind("modr-editor-align", "change", e =>
        updateSelectedProperty("textAlign", e.target.value)
    );


    function updateSelectedProperty(property, value) {
        const obj = activeObject();
        if (!obj) return;
        obj.set(property, value);
        canvas.requestRenderAll();
        saveHistory();
    }

    bind("modr-editor-text", "input", e =>
        updateSelectedProperty("text", e.target.value)
    );

    bind("modr-editor-size", "input", e =>
        updateSelectedProperty("fontSize", Math.max(8, Math.min(180, Number(e.target.value) || 8)))
    );

    bind("modr-editor-color", "input", e =>
        updateSelectedProperty("fill", e.target.value)
    );

    bind("modr-editor-font", "change", e =>
        updateSelectedProperty("fontFamily", e.target.value)
    );

    bind("modr-editor-align", "change", e =>
        updateSelectedProperty("textAlign", e.target.value)
    );


    bind("modr-editor-direction", "change", e =>
        updateSelectedProperty("direction", e.target.value)
    );

    bind("modr-editor-opacity", "input", e =>
        updateSelectedProperty("opacity", Number(e.target.value) / 100)
    );

    bind("modr-editor-rotation", "input", e =>
        updateSelectedProperty("angle", Math.max(-180, Math.min(180, Number(e.target.value) || 0)))
    );


    bind("modr-editor-bg-color", "input", e => {
        setBackground(e.target.value);
        saveHistory();
    });

    bind("modr-editor-bg-gradient", "change", e => {
        if (!e.target.value) return;
        setGradient(e.target.value);
        saveHistory();
    });


    bind("modr-editor-duplicate", "click", function () {
        duplicateSelected();
    });

    bind("modr-editor-lock", "click", function () {
        toggleLock();
    });

    bind("modr-editor-front", "click", function () {
        moveLayer("front");
    });

    bind("modr-editor-back", "click", function () {
        moveLayer("back");
    });

    bind("modr-editor-delete", "click", function () {
        deleteSelected();
    });


    function addDesignText(text, options = {}) {
        const obj = new fabric.Textbox(text, {
            left: options.left ?? 600,
            top: options.top ?? 300,
            width: options.width ?? 600,
            fontSize: options.fontSize ?? 44,
            fontFamily: "Cairo",
            fontWeight: options.bold ? "bold" : "normal",
            fill: options.fill ?? "#FFFFFF",
            textAlign: options.align ?? "center",
            direction: "rtl",
            originX: "center",
            originY: "center",
            editable: true,
            cornerColor: "#C5A059",
            borderColor: "#C5A059",
            transparentCorners: false
        });
        canvas.add(obj);
        return obj;
    }

    function addDesignRect(left, top, width, height, fill, options = {}) {
        const obj = new fabric.Rect({
            left, top, width, height, fill,
            originX: "center",
            originY: "center",
            rx: options.radius || 0,
            ry: options.radius || 0,
            angle: options.angle || 0,
            stroke: options.stroke || null,
            strokeWidth: options.strokeWidth || 0,
            selectable: options.selectable !== false,
            evented: options.selectable !== false
        });
        canvas.add(obj);
        return obj;
    }

    function addDesignCircle(left, top, radius, fill, stroke) {
        const obj = new fabric.Circle({
            left, top, radius,
            originX: "center",
            originY: "center",
            fill: fill || "transparent",
            stroke: stroke || null,
            strokeWidth: stroke ? 5 : 0
        });
        canvas.add(obj);
        return obj;
    }

    function applyTemplate(index) {
        if (!canvas || !templates[index]) return;

        const item = templates[index];
        const name = item[0];
        const category = item[1];
        const bg = item[2];
        const accent = item[3];
        const variant = index % 5;

        canvas.discardActiveObject();
        canvas.clear();
        canvas.backgroundColor = bg;

        const light = "#FFFFFF";
        const darkText = "#281B17";
        const foreground = ["#FDFBF7", "#FFFFFF", "#F8F2E9"].includes(bg)
            ? darkText : light;

        if (variant === 0) {
            // Luxury Center
            addDesignCircle(930, 300, 205, "transparent", accent);
            addDesignCircle(930, 300, 165, "transparent", accent);
            addDesignCircle(930, 300, 115, accent);
            addDesignRect(600, 130, 170, 5, accent);
            addDesignText("MODR ONE", {
                top: 100, fontSize: 25, fill: accent, bold: true
            });
            addDesignText(name, {
                left: 430, top: 285, width: 680,
                fontSize: 66, fill: foreground, bold: true
            });
            addDesignText(category, {
                left: 430, top: 365, width: 600,
                fontSize: 27, fill: accent
            });
            addDesignText("اكتشف التميز في كل اختيار", {
                left: 430, top: 445, width: 650,
                fontSize: 24, fill: foreground
            });
        } else if (variant === 1) {
            // Split Layout
            addDesignRect(940, 314, 520, 628, accent);
            addDesignCircle(940, 285, 150, bg, light);
            addDesignCircle(940, 285, 115, "transparent", light);
            addDesignText("MODR", {
                left: 940, top: 285, width: 300,
                fontSize: 58, fill: foreground, bold: true
            });
            addDesignText(category, {
                left: 330, top: 145, width: 480,
                fontSize: 27, fill: accent
            });
            addDesignText(name, {
                left: 330, top: 290, width: 520,
                fontSize: 58, fill: foreground, bold: true
            });
            addDesignText("اختيارات تليق بك", {
                left: 330, top: 390, width: 480,
                fontSize: 25, fill: foreground
            });
            addDesignRect(330, 480, 240, 5, accent);
        } else if (variant === 2) {
            // Bold Typography
            addDesignRect(600, 310, 1450, 175, accent, { angle: -9 });
            addDesignText("MODR ONE", {
                left: 600, top: 115, width: 700,
                fontSize: 28, fill: accent, bold: true
            });
            addDesignText(name, {
                left: 600, top: 285, width: 970,
                fontSize: 68, fill: foreground, bold: true
            });
            addDesignText(category, {
                left: 600, top: 410, width: 650,
                fontSize: 30, fill: foreground
            });
            addDesignText("أسلوب مختلف. تجربة استثنائية.", {
                left: 600, top: 530, width: 850,
                fontSize: 25, fill: foreground
            });
        } else if (variant === 3) {
            // Editorial
            addDesignRect(600, 65, 1200, 130, accent);
            addDesignText("MODR ONE", {
                left: 600, top: 65, width: 700,
                fontSize: 36, fill: bg, bold: true
            });
            addDesignRect(600, 555, 1200, 146, accent);
            addDesignText("اكتشف مجموعتنا الجديدة", {
                left: 600, top: 555, width: 900,
                fontSize: 30, fill: bg, bold: true
            });
            addDesignText(category, {
                left: 600, top: 220, width: 700,
                fontSize: 26, fill: accent
            });
            addDesignText(name, {
                left: 600, top: 345, width: 950,
                fontSize: 65, fill: foreground, bold: true
            });
            addDesignRect(600, 435, 190, 5, accent);
        } else {
            // Modern Frame
            addDesignRect(600, 314, 1110, 550, "transparent", {
                stroke: accent, strokeWidth: 5
            });
            addDesignRect(600, 55, 260, 9, accent);
            addDesignRect(600, 573, 260, 9, accent);
            addDesignCircle(115, 314, 48, accent);
            addDesignCircle(1085, 314, 48, accent);
            addDesignText("MODR ONE", {
                left: 600, top: 160, width: 650,
                fontSize: 27, fill: accent, bold: true
            });
            addDesignText(name, {
                left: 600, top: 300, width: 850,
                fontSize: 65, fill: foreground, bold: true
            });
            addDesignText(category, {
                left: 600, top: 390, width: 700,
                fontSize: 28, fill: accent
            });
            addDesignText("جودة تختارها بثقة", {
                left: 600, top: 480, width: 700,
                fontSize: 24, fill: foreground
            });
        }

        const heading = $("modr-editor-template-name");
        if (heading) heading.textContent = name;

        document.querySelectorAll(".modr-template-choice").forEach(button => {
            button.classList.toggle(
                "active",
                Number(button.dataset.templateIndex) === index
            );
        });

        canvas.requestRenderAll();
        refreshLayers();
        saveHistory();
        status("تم تطبيق قالب: " + name);
    }

    function renderTemplates() {
        const gallery = $("modr-editor-templates");
        if (!gallery) return;

        gallery.replaceChildren();

        templates.forEach((item, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "modr-template-choice";
            button.dataset.templateIndex = String(index);
            button.title = item[0];

            const swatch = document.createElement("span");
            swatch.className = "modr-template-swatch";
            swatch.style.background =
                "linear-gradient(135deg, " + item[2] + ", " + item[3] + ")";

            const label = document.createElement("span");
            label.textContent = item[0];

            const number = document.createElement("small");
            number.textContent = String(index + 1);

            button.append(swatch, label, number);
            button.addEventListener("click", () => applyTemplate(index));
            gallery.appendChild(button);
        });
    }


    function initializeEditor() {
        if (ready) return;

        const element = $("modr-ads-canvas");
        if (!element || typeof fabric === "undefined") {
            status("تعذر تحميل مكتبة محرر التصاميم");
            return;
        }

        canvas = new fabric.Canvas("modr-ads-canvas", {
            preserveObjectStacking: true,
            selection: true,
            backgroundColor: "#FDFBF7"
        });

        ready = true;

        canvas.on("object:added", () => {
            refreshLayers();
            saveHistory();
        });

        canvas.on("object:modified", saveHistory);

        canvas.on("object:removed", () => {
            refreshLayers();
            saveHistory();
        });

        canvas.on("selection:created", selectObject);
        canvas.on("selection:updated", selectObject);
        canvas.on("selection:cleared", () => {
            selectObject();
            refreshLayers();
        });

        renderTemplates();
        resizeCanvas();
        saveHistory();

        if (typeof ResizeObserver !== "undefined") {
            resizeObserver = new ResizeObserver(resizeCanvas);
            const wrap = document.querySelector(".modr-editor-canvas-wrap");
            if (wrap) resizeObserver.observe(wrap);
        } else {
            window.addEventListener("resize", resizeCanvas);
        }
    }


    function openEditor() {
        const editor = $("modr-ads-editor");
        if (!editor) return;

        editor.hidden = false;
        initializeEditor();

        requestAnimationFrame(() => {
            resizeCanvas();
            editor.scrollIntoView({
                behavior: "smooth",
                block: "start"
            });
        });
    }

    bind("modr-editor-open", "click", openEditor);

    bind("modr-editor-undo", "click", undo);
    bind("modr-editor-redo", "click", redo);

    document.querySelectorAll("[data-studio-tab]").forEach(button => {
        button.addEventListener("click", () => {
            switchTab(button.dataset.studioTab);
        });
    });

    bind("creative_type", "change", event => {
        if (event.target.value === "template") openEditor();
    });


    async function exportDesign() {
        if (!canvas || !ready) {
            status("افتح المحرر واختر قالباً أولاً");
            return;
        }

        const imageInput = $("image");
        if (!imageInput) {
            status("تعذر العثور على حقل إرفاق الصورة");
            return;
        }

        try {
            canvas.discardActiveObject();
            canvas.requestRenderAll();

            const dataUrl = canvas.toDataURL({
                format: "png",
                multiplier: W / canvas.getWidth()
            });

            const response = await fetch(dataUrl);
            const blob = await response.blob();

            if (!blob.size || blob.type !== "image/png") {
                throw new Error("Invalid PNG");
            }

            const file = new File(
                [blob],
                "modr-ad-design.png",
                { type: "image/png" }
            );

            const transfer = new DataTransfer();
            transfer.items.add(file);
            imageInput.files = transfer.files;

            status("تم تصدير التصميم وإرفاقه بالطلب بنجاح");
        } catch (error) {
            console.error("MODR ADS export error:", error);
            status("تعذر تصدير التصميم. حاول مرة أخرى");
        }
    }

    bind("modr-editor-export", "click", exportDesign);

})();
