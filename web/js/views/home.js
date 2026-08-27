"use strict";

import {API} from "../api.js";
import {el, empty} from "../dom.js";
import {setTitle} from "../router.js";
import {section} from "../ui.js";

export const homeView = {
    async render(box) {
        setTitle("Domů");
        const {personalized, sections} = await API.home();
        if (!sections.length) {
            box.replaceChildren(empty("Nic tu není. Zkontroluj přihlášení."));
            return;
        }
        box.replaceChildren();
        if (!personalized) {
            // bez přihlášení posílá YouTube obecný feed — ať to není záměna za For You
            box.appendChild(el(
                "div", "notice",
                "Nepersonalizováno — nejsi přihlášen, tohle je obecný feed YouTube Music.",
            ));
        }
        for (const sec of sections) box.appendChild(section(sec.title, sec.items));
    },
};
